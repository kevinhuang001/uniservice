"""Linux backend: systemd user and system units."""

from __future__ import annotations

import shlex
import shutil
from pathlib import Path

from ..errors import ServiceNotFoundError, UniserviceError
from ..logging_utils import logger
from ..naming import SYSTEMD_UNIT_PREFIX, SYSTEMD_UNIT_SUFFIX, parse_systemd_unit_name, systemd_unit_name
from ..process import command_string, run
from ..scope import Scope
from .base import Backend, ServiceInfo, classify_state

__all__ = [
    "SYSTEMD_ACTIVE_STATES",
    "SYSTEMD_DISABLED_STATES",
    "SYSTEMD_ENABLED_STATES",
    "SYSTEMD_INACTIVE_STATES",
    "LinuxBackend",
    "collect_unit_names",
    "systemctl_command",
    "systemd_root",
]

#: ``systemctl is-enabled`` results that mean "starts on boot".
SYSTEMD_ENABLED_STATES = frozenset({"enabled", "enabled-runtime"})

#: ``systemctl is-enabled`` results that mean "does not start on boot".
#: ``static`` units have no ``[Install]`` section and cannot be enabled;
#: ``masked`` and friends are explicitly prevented from starting.
SYSTEMD_DISABLED_STATES = frozenset(
    {
        "disabled",
        "disabled-runtime",
        "masked",
        "masked-runtime",
        "static",
        "indirect",
        "generated",
        "transient",
        "alias",
        "linked",
        "linked-runtime",
        "bad",
        "not-found",
    }
)

#: ``systemctl is-active`` results that mean "the unit is up".
#: ``activating``/``reloading`` are transient but the unit is being served, so
#: they count as running.
SYSTEMD_ACTIVE_STATES = frozenset({"active", "activating", "reloading"})

#: ``systemctl is-active`` results that mean "the unit is not up".
SYSTEMD_INACTIVE_STATES = frozenset({"inactive", "failed", "deactivating"})

SYSTEMCTL = "systemctl"
JOURNALCTL = "journalctl"


def systemd_root(scope: Scope) -> Path:
    """Return the directory that holds uniservice unit files for *scope*."""
    if scope.is_system:
        return Path("/etc/systemd/system")
    return Path.home() / ".config" / "systemd" / "user"


def systemctl_command(scope: Scope) -> list[str]:
    """Return the ``systemctl`` invocation prefix for *scope*."""
    if scope.is_system:
        return [SYSTEMCTL]
    return [SYSTEMCTL, "--user"]


def collect_unit_names(root: Path) -> list[str]:
    """Return the service names of every uniservice unit under *root*.

    Masked units are symlinks to ``/dev/null`` and non-regular files are
    therefore *not* skipped: ``is_symlink()`` is checked as well, otherwise
    masked services would silently disappear from ``uniservice list``.
    """
    if not root.is_dir():
        return []

    names: set[str] = set()
    for path in root.glob(f"{SYSTEMD_UNIT_PREFIX}*{SYSTEMD_UNIT_SUFFIX}"):
        if not (path.is_file() or path.is_symlink()):
            continue
        name = parse_systemd_unit_name(path.name)
        if name is None or not name.strip():
            continue
        names.add(name)
    return sorted(names, key=lambda item: (item.casefold(), item))


class LinuxBackend(Backend):
    """systemd-based backend used on Linux."""

    def _unit_path(self, name: str) -> Path:
        return systemd_root(self.scope) / systemd_unit_name(name)

    def _systemctl(self) -> list[str]:
        return systemctl_command(self.scope)

    def create(self, name: str, workdir: Path, command_parts: list[str]) -> None:
        logger.info("linux create name=%s workdir=%s", name, workdir)
        if shutil.which(SYSTEMCTL) is None:
            raise UniserviceError("systemctl not found; systemd is required on Linux.")

        unit_path = self._unit_path(name)
        unit_path.parent.mkdir(parents=True, exist_ok=True)

        wanted_by = "multi-user.target" if self.scope.is_system else "default.target"
        content = "\n".join(
            [
                "[Unit]",
                f"Description=uniservice {name}",
                "After=network.target",
                "",
                "[Service]",
                "Type=simple",
                f"WorkingDirectory={workdir}",
                f"ExecStart=/usr/bin/env bash -lc {shlex.quote(command_string(command_parts))}",
                "Restart=always",
                "RestartSec=2",
                "",
                "[Install]",
                f"WantedBy={wanted_by}",
                "",
            ]
        )
        unit_path.write_text(content, encoding="utf-8")
        logger.debug("linux wrote unit %s", unit_path)

    def cat(self, name: str) -> None:
        logger.info("linux cat name=%s", name)
        unit_path = self._unit_path(name)
        if not unit_path.exists():
            raise ServiceNotFoundError(name)

        workdir = _read_unit_field(unit_path, "WorkingDirectory")
        exec_start = _read_unit_field(unit_path, "ExecStart")
        if workdir is None or exec_start is None:
            raise UniserviceError(f"Invalid unit file: {unit_path}")

        tokens = shlex.split(exec_start)
        try:
            index = tokens.index("-lc")
        except ValueError:
            raise UniserviceError(f"Unsupported ExecStart format: {exec_start}") from None
        if index + 1 >= len(tokens):
            raise UniserviceError(f"Unsupported ExecStart format: {exec_start}")

        command_tokens = shlex.split(tokens[index + 1])
        quoted_command = " ".join(shlex.quote(token) for token in command_tokens)
        prefix = "sudo " if self.scope.is_system else ""
        print(f"{prefix}uniservice add {shlex.quote(name)} --workdir {shlex.quote(workdir)} -- {quoted_command}")

    def status(self, name: str) -> None:
        logger.info("linux status name=%s", name)
        unit_path = self._unit_path(name)
        if not unit_path.exists():
            raise ServiceNotFoundError(name)
        if shutil.which(SYSTEMCTL) is None:
            raise UniserviceError("systemctl is not installed.")
        run([*self._systemctl(), "status", systemd_unit_name(name), "--no-pager", "-l"], check=False)

    def logs(self, name: str, *, lines: int, follow: bool) -> None:
        logger.info("linux logs name=%s lines=%s follow=%s", name, lines, follow)
        unit_path = self._unit_path(name)
        if not unit_path.exists():
            raise ServiceNotFoundError(name)
        if shutil.which(JOURNALCTL) is None:
            raise UniserviceError("journalctl is not installed.")

        unit = systemd_unit_name(name)
        if self.scope.is_system:
            cmd = [JOURNALCTL, "-u", unit, "--no-pager", "-n", str(lines)]
        else:
            cmd = [JOURNALCTL, "--user-unit", unit, "--no-pager", "-n", str(lines)]
        if follow:
            cmd.append("-f")
        run(cmd, check=False)

    def exists(self, name: str) -> bool:
        unit_path = self._unit_path(name)
        exists = unit_path.exists()
        logger.debug("linux exists(%s)=%s path=%s", name, exists, unit_path)
        return exists

    def enable(self, name: str) -> None:
        logger.info("linux enable name=%s", name)
        base = self._systemctl()
        run([*base, "daemon-reload"])
        run([*base, "enable", systemd_unit_name(name)])

    def disable(self, name: str) -> None:
        logger.info("linux disable name=%s", name)
        base = self._systemctl()
        run([*base, "daemon-reload"])
        run([*base, "disable", systemd_unit_name(name)])
        run([*base, "reset-failed", systemd_unit_name(name)], check=False, capture=True)

    def start(self, name: str) -> None:
        logger.info("linux start name=%s", name)
        base = self._systemctl()
        run([*base, "daemon-reload"])
        run([*base, "start", systemd_unit_name(name)])

    def stop(self, name: str) -> None:
        logger.info("linux stop name=%s", name)
        run([*self._systemctl(), "stop", systemd_unit_name(name)])

    def remove(self, name: str) -> None:
        logger.info("linux remove name=%s", name)
        unit_path = self._unit_path(name)
        if unit_path.exists():
            unit_path.unlink()

    def list_info(self) -> list[ServiceInfo]:
        logger.info("linux list_info scope=%s", self.scope.value)
        names = collect_unit_names(systemd_root(self.scope))
        if not names:
            return []

        if shutil.which(SYSTEMCTL) is None:
            logger.warning("systemctl not found; the enabled/running state is unavailable.")
            return [ServiceInfo(name=name, enabled=None, running=None) for name in names]

        base = self._systemctl()
        rows: list[ServiceInfo] = []
        for name in names:
            unit = systemd_unit_name(name)
            enabled_stdout, enabled_stderr = self._query(base, "is-enabled", unit)
            running_stdout, running_stderr = self._query(base, "is-active", unit)
            rows.append(
                ServiceInfo(
                    name=name,
                    enabled=classify_state(
                        enabled_stdout,
                        enabled_stderr,
                        true_states=SYSTEMD_ENABLED_STATES,
                        false_states=SYSTEMD_DISABLED_STATES,
                    ),
                    running=classify_state(
                        running_stdout,
                        running_stderr,
                        true_states=SYSTEMD_ACTIVE_STATES,
                        false_states=SYSTEMD_INACTIVE_STATES,
                    ),
                )
            )
        return rows

    @staticmethod
    def _query(base: list[str], verb: str, unit: str) -> tuple[str, str]:
        """Run ``systemctl <verb> <unit>`` and return ``(stdout, stderr)``."""
        completed = run([*base, verb, unit], check=False, capture=True)
        return completed.stdout or "", completed.stderr or ""


def _read_unit_field(unit_path: Path, key: str) -> str | None:
    prefix = f"{key}="
    for raw_line in unit_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line.startswith(prefix):
            return line[len(prefix) :].strip()
    return None
