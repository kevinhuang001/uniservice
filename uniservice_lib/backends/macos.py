"""macOS backend: launchd LaunchAgents and LaunchDaemons."""

from __future__ import annotations

import os
import plistlib
import re
import shlex
import shutil
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

from ..errors import ServiceNotFoundError, UniserviceError
from ..logging_utils import logger
from ..naming import (
    LAUNCHD_LABEL_PREFIX,
    LAUNCHD_PLIST_SUFFIX,
    macos_label,
    macos_plist_name,
    parse_macos_plist_name,
)
from ..platform_utils import is_root_unix, sudo_target_uid, user_home_for_uid
from ..process import command_string, run
from ..scope import Scope
from .base import Backend, ServiceInfo

__all__ = [
    "MacOSBackend",
    "collect_plist_entries",
    "escape_pgrep_pattern",
    "macos_domains",
    "macos_log_paths",
    "macos_plist_root",
    "parse_launchctl_list",
    "parse_print_disabled",
    "pgrep_running",
    "render_plist",
]

LAUNCHCTL = "launchctl"
PGREP = "pgrep"
TAIL = "tail"

#: ``launchctl print-disabled`` renders overrides either as ``enabled``/
#: ``disabled`` (modern macOS) or as ``true``/``false`` (older releases), where
#: ``true`` means the job is disabled.
_PRINT_DISABLED_RE = re.compile(r'"([^"]+)"\s*=>\s*(enabled|disabled|true|false)', re.IGNORECASE)

#: ``launchctl print`` reports ``pid = 1234`` while the job has a process.
_PRINT_PID_RE = re.compile(r"^\s*pid\s*=\s*\d+\s*$", re.MULTILINE)

#: Characters with a special meaning in POSIX extended regular expressions, as
#: used by ``pgrep -f``.  ``re.escape`` is deliberately not used because it also
#: escapes ordinary characters such as ``-`` whose behaviour after a backslash
#: is undefined by POSIX.
_PGREP_SPECIAL_CHARACTERS = frozenset(".^$*+?()[]{}|\\")


def macos_user_home() -> Path:
    """Return the home directory that owns user-scope launch agents.

    When uniservice is executed through ``sudo`` the agents must belong to the
    invoking user, not to root, so ``SUDO_UID`` is honoured when present.
    """
    uid = sudo_target_uid() if is_root_unix() else None
    if uid is not None:
        return user_home_for_uid(uid)
    return Path.home()


def macos_plist_root(scope: Scope) -> Path:
    """Return the directory that holds uniservice plists for *scope*."""
    if scope.is_system:
        return Path("/Library/LaunchDaemons")
    return macos_user_home() / "Library" / "LaunchAgents"


def macos_domains(scope: Scope) -> list[str]:
    """Return the launchd domains to query, most specific first."""
    if scope.is_system:
        return ["system"]
    uid = sudo_target_uid() if is_root_unix() else None
    uid = uid if uid is not None else os.getuid()
    return [f"gui/{uid}", f"user/{uid}"]


def macos_log_dir(scope: Scope) -> Path:
    """Return the directory that holds captured stdout/stderr files."""
    if scope.is_system:
        return Path("/var/log/uniservice")
    return macos_user_home() / ".uniservice" / "services"


def macos_log_paths(name: str, scope: Scope) -> tuple[Path, Path]:
    """Return the ``(stdout, stderr)`` log paths for *name*."""
    directory = macos_log_dir(scope)
    return directory / f"{name}.out.log", directory / f"{name}.err.log"


def collect_plist_entries(root: Path) -> list[tuple[str, str, Path]]:
    """Return sorted ``(name, label, plist_path)`` entries under *root*."""
    if not root.is_dir():
        return []

    entries: list[tuple[str, str, Path]] = []
    for path in root.glob(f"{LAUNCHD_LABEL_PREFIX}*{LAUNCHD_PLIST_SUFFIX}"):
        if not (path.is_file() or path.is_symlink()):
            continue
        name = parse_macos_plist_name(path.name)
        if name is None or not name.strip():
            continue
        entries.append((name, path.stem, path))
    return sorted(entries, key=lambda entry: (entry[0].casefold(), entry[0]))


def parse_print_disabled(text: str) -> dict[str, bool]:
    """Parse ``launchctl print-disabled`` into ``{label: disabled}``."""
    overrides: dict[str, bool] = {}
    for match in _PRINT_DISABLED_RE.finditer(text or ""):
        label = match.group(1)
        token = match.group(2).lower()
        overrides[label] = token in {"disabled", "true"}
    return overrides


def parse_launchctl_list(text: str) -> dict[str, bool]:
    """Parse ``launchctl list`` into ``{label: running}``.

    The output is a table of ``PID Status Label``; a ``-`` PID means the job is
    loaded but has no process.
    """
    running: dict[str, bool] = {}
    for line in (text or "").splitlines():
        parts = line.split(None, 2)
        if len(parts) < 3:
            continue
        pid, _status, label = parts[0], parts[1], parts[2]
        if not label.startswith(LAUNCHD_LABEL_PREFIX):
            continue
        running[label] = pid != "-"
    return running


def escape_pgrep_pattern(pattern: str) -> str:
    """Escape *pattern* so ``pgrep -f`` treats it as a literal string."""
    return "".join(f"\\{character}" if character in _PGREP_SPECIAL_CHARACTERS else character for character in pattern)


def pgrep_running(command: str) -> bool | None:
    """Return whether *command* currently has a matching process.

    ``pgrep`` exits ``0`` when it matched, ``1`` when it did not and anything
    else on error; the error case is reported as "unknown" instead of "not
    running".
    """
    if not command.strip():
        return None
    if shutil.which(PGREP) is None:
        return None

    completed = run([PGREP, "-f", escape_pgrep_pattern(command)], check=False, capture=True)
    if completed.returncode == 0:
        return True
    if completed.returncode == 1:
        return False
    logger.debug("pgrep failed rc=%s for %r", completed.returncode, command)
    return None


def read_plist_command(plist_path: Path) -> str | None:
    """Return the shell command stored in ``ProgramArguments``."""
    try:
        data = plistlib.loads(plist_path.read_bytes())
    except Exception as exc:  # a corrupt plist must not break list
        logger.debug("could not read plist %s: %s", plist_path, exc)
        return None
    if not isinstance(data, dict):
        return None
    arguments = data.get("ProgramArguments")
    if isinstance(arguments, list) and len(arguments) >= 3 and isinstance(arguments[2], str):
        return arguments[2].strip() or None
    return None


def render_plist(label: str, workdir: Path, command: str, out_path: Path, err_path: Path) -> str:
    """Render the plist XML for a uniservice job."""
    return "\n".join(
        [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">',
            '<plist version="1.0">',
            "<dict>",
            "  <key>Label</key>",
            f"  <string>{xml_escape(label)}</string>",
            "  <key>WorkingDirectory</key>",
            f"  <string>{xml_escape(str(workdir))}</string>",
            "  <key>StandardOutPath</key>",
            f"  <string>{xml_escape(str(out_path))}</string>",
            "  <key>StandardErrorPath</key>",
            f"  <string>{xml_escape(str(err_path))}</string>",
            "  <key>ProgramArguments</key>",
            "  <array>",
            "    <string>/bin/bash</string>",
            "    <string>-lc</string>",
            f"    <string>{xml_escape(command)}</string>",
            "  </array>",
            "  <key>RunAtLoad</key>",
            "  <true/>",
            "  <key>KeepAlive</key>",
            "  <true/>",
            "</dict>",
            "</plist>",
            "",
        ]
    )


class MacOSBackend(Backend):
    """launchd-based backend used on macOS."""

    def _plist_path(self, name: str) -> Path:
        return macos_plist_root(self.scope) / macos_plist_name(name)

    def _label(self, name: str) -> str:
        return macos_label(name)

    def _domains(self) -> list[str]:
        return macos_domains(self.scope)

    def _bootout_all(self, plist_path: Path) -> None:
        for domain in self._domains():
            run([LAUNCHCTL, "bootout", domain, str(plist_path)], check=False, quiet=True)

    def _bootstrap(self, label: str, plist_path: Path) -> str:
        last_error = ""
        for domain in self._domains():
            run([LAUNCHCTL, "enable", f"{domain}/{label}"], check=False, quiet=True)
            completed = run([LAUNCHCTL, "bootstrap", domain, str(plist_path)], check=False, capture=True)
            if completed.returncode == 0:
                return domain
            output = (completed.stdout or "") + "\n" + (completed.stderr or "")
            last_error = output.strip() or f"launchctl bootstrap failed with exit code {completed.returncode}"
        raise UniserviceError(last_error)

    def create(self, name: str, workdir: Path, command_parts: list[str]) -> None:
        logger.info("mac create name=%s workdir=%s", name, workdir)
        plist_path = self._plist_path(name)
        plist_path.parent.mkdir(parents=True, exist_ok=True)

        out_path, err_path = macos_log_paths(name, self.scope)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        content = render_plist(
            self._label(name),
            workdir,
            command_string(command_parts),
            out_path,
            err_path,
        )
        plist_path.write_text(content, encoding="utf-8")
        logger.debug("mac wrote plist %s", plist_path)

        if self.scope.is_system:
            os.chmod(plist_path, 0o644)

    def cat(self, name: str) -> None:
        logger.info("mac cat name=%s", name)
        plist_path = self._plist_path(name)
        if not plist_path.exists():
            raise ServiceNotFoundError(name)

        data = plistlib.loads(plist_path.read_bytes())
        workdir = data.get("WorkingDirectory") if isinstance(data, dict) else None
        arguments = data.get("ProgramArguments") if isinstance(data, dict) else None
        if not isinstance(workdir, str) or not isinstance(arguments, list) or len(arguments) < 3:
            raise UniserviceError(f"Invalid plist: {plist_path}")

        command = arguments[2]
        if not isinstance(command, str):
            raise UniserviceError(f"Invalid plist: {plist_path}")

        command_tokens = shlex.split(command)
        quoted_command = " ".join(shlex.quote(token) for token in command_tokens)
        prefix = "sudo " if self.scope.is_system else ""
        print(f"{prefix}uniservice add {shlex.quote(name)} --workdir {shlex.quote(workdir)} -- {quoted_command}")

    def status(self, name: str) -> None:
        logger.info("mac status name=%s", name)
        plist_path = self._plist_path(name)
        if not plist_path.exists():
            raise ServiceNotFoundError(name)

        label = self._label(name)
        last_error = ""
        for domain in self._domains():
            completed = run([LAUNCHCTL, "print", f"{domain}/{label}"], check=False, capture=True)
            if completed.returncode == 0:
                _print_stream(completed.stdout)
                _print_stream(completed.stderr)
                return
            output = (completed.stdout or "") + "\n" + (completed.stderr or "")
            last_error = output.strip() or f"launchctl print failed (rc={completed.returncode})"
        raise UniserviceError(last_error)

    def logs(self, name: str, *, lines: int, follow: bool) -> None:
        logger.info("mac logs name=%s lines=%s follow=%s", name, lines, follow)
        plist_path = self._plist_path(name)
        if not plist_path.exists():
            raise ServiceNotFoundError(name)

        out_path, err_path = macos_log_paths(name, self.scope)
        try:
            data = plistlib.loads(plist_path.read_bytes())
        except Exception:  # fall back to the default paths
            data = {}
        if isinstance(data, dict):
            plist_out = data.get("StandardOutPath")
            plist_err = data.get("StandardErrorPath")
            if isinstance(plist_out, str) and plist_out.strip():
                out_path = Path(plist_out.strip())
            if isinstance(plist_err, str) and plist_err.strip():
                err_path = Path(plist_err.strip())

        if follow:
            run([TAIL, "-n", str(lines), "-f", str(out_path), str(err_path)], check=False)
        else:
            run([TAIL, "-n", str(lines), str(out_path)], check=False)
            run([TAIL, "-n", str(lines), str(err_path)], check=False)

    def exists(self, name: str) -> bool:
        plist_path = self._plist_path(name)
        exists = plist_path.exists()
        logger.debug("mac exists(%s)=%s path=%s", name, exists, plist_path)
        return exists

    def enable(self, name: str) -> None:
        logger.info("mac enable name=%s", name)
        plist_path = self._plist_path(name)
        if not plist_path.exists():
            raise ServiceNotFoundError(name)

        label = self._label(name)
        last_error = ""
        for domain in self._domains():
            completed = run([LAUNCHCTL, "enable", f"{domain}/{label}"], check=False, capture=True)
            if completed.returncode == 0:
                return
            output = (completed.stdout or "") + "\n" + (completed.stderr or "")
            last_error = output.strip() or f"launchctl enable failed (rc={completed.returncode})"
        raise UniserviceError(last_error)

    def disable(self, name: str) -> None:
        logger.info("mac disable name=%s", name)
        label = self._label(name)
        last_error = ""
        for domain in self._domains():
            completed = run([LAUNCHCTL, "disable", f"{domain}/{label}"], check=False, capture=True)
            if completed.returncode == 0:
                return
            output = (completed.stdout or "") + "\n" + (completed.stderr or "")
            last_error = output.strip() or f"launchctl disable failed (rc={completed.returncode})"
        raise UniserviceError(last_error)

    def start(self, name: str) -> None:
        logger.info("mac start name=%s", name)
        plist_path = self._plist_path(name)
        if not plist_path.exists():
            raise ServiceNotFoundError(name)

        label = self._label(name)
        domain = self._bootstrap(label, plist_path)
        run([LAUNCHCTL, "enable", f"{domain}/{label}"], check=False)
        run([LAUNCHCTL, "kickstart", "-k", f"{domain}/{label}"], check=False)

    def stop(self, name: str) -> None:
        logger.info("mac stop name=%s", name)
        plist_path = self._plist_path(name)
        if not plist_path.exists():
            raise ServiceNotFoundError(name)

        label = self._label(name)
        for domain in self._domains():
            run([LAUNCHCTL, "kill", "SIGTERM", f"{domain}/{label}"], check=False, quiet=True)
            run([LAUNCHCTL, "stop", f"{domain}/{label}"], check=False, quiet=True)

        run([LAUNCHCTL, "kill", "SIGTERM", label], check=False, quiet=True)
        run([LAUNCHCTL, "stop", label], check=False, quiet=True)

        self._bootout_all(plist_path)

    def remove(self, name: str) -> None:
        logger.info("mac remove name=%s", name)
        plist_path = self._plist_path(name)
        if plist_path.exists():
            plist_path.unlink()

    def list_info(self) -> list[ServiceInfo]:
        logger.info("mac list_info scope=%s", self.scope.value)
        entries = collect_plist_entries(macos_plist_root(self.scope))
        if not entries:
            return []

        if shutil.which(LAUNCHCTL) is None:
            logger.warning("launchctl not found; the enabled/running state is unavailable.")
            return [ServiceInfo(name=name, enabled=None, running=None) for name, _label, _path in entries]

        disabled_overrides, overrides_known = self._read_disabled_overrides()
        listed = self._launchctl_list()

        rows: list[ServiceInfo] = []
        for name, label, plist_path in entries:
            # launchd treats a job without a disabled override as enabled; a job
            # that is absent from print-disabled used to be reported as "?" even
            # though the documentation promised "yes".
            enabled = None if not overrides_known else not disabled_overrides.get(label, False)
            rows.append(
                ServiceInfo(
                    name=name,
                    enabled=enabled,
                    running=self._running_state(label, plist_path, listed),
                )
            )
        return rows

    def _read_disabled_overrides(self) -> tuple[dict[str, bool], bool]:
        """Return ``({label: disabled}, overrides_known)``.

        Domains are queried most-specific first and the first domain that
        mentions a label wins, instead of the last one overwriting the others.
        """
        overrides: dict[str, bool] = {}
        known = False
        for domain in self._domains():
            completed = run([LAUNCHCTL, "print-disabled", domain], check=False, capture=True)
            if completed.returncode != 0:
                logger.debug("launchctl print-disabled %s failed rc=%s", domain, completed.returncode)
                continue
            known = True
            text = (completed.stdout or "") + "\n" + (completed.stderr or "")
            for label, disabled in parse_print_disabled(text).items():
                overrides.setdefault(label, disabled)
        return overrides, known

    def _launchctl_list(self) -> dict[str, bool] | None:
        completed = run([LAUNCHCTL, "list"], check=False, capture=True)
        if completed.returncode != 0:
            logger.debug("launchctl list failed rc=%s", completed.returncode)
            return None
        return parse_launchctl_list(completed.stdout or "")

    def _running_state(self, label: str, plist_path: Path, listed: dict[str, bool] | None) -> bool | None:
        if listed is not None and label in listed:
            return listed[label]

        # ``launchctl list`` only covers the caller's domain, so system jobs
        # need an explicit ``launchctl print``.
        for domain in self._domains():
            completed = run([LAUNCHCTL, "print", f"{domain}/{label}"], check=False, capture=True)
            if completed.returncode != 0:
                continue
            text = (completed.stdout or "") + "\n" + (completed.stderr or "")
            return _PRINT_PID_RE.search(text) is not None

        command = read_plist_command(plist_path)
        if command:
            return pgrep_running(command)
        return None


def _print_stream(text: str | None) -> None:
    if text:
        print(text, end="" if text.endswith("\n") else "\n")
