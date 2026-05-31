from __future__ import annotations

import os
import plistlib
import shlex
import re
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

from backend_base import Backend, ServiceInfo
from utils import Scope, command_string, is_root_unix, logger, run, sudo_target_uid, user_home_for_uid


def mac_label(name: str) -> str:
    return f"com.uniservice.{name}"


def mac_plist_path(name: str, scope: Scope) -> Path:
    label = mac_label(name)
    if scope.value == "system":
        return Path("/Library/LaunchDaemons") / f"{label}.plist"
    uid = sudo_target_uid() if is_root_unix() else None
    home = user_home_for_uid(uid) if uid is not None else Path.home()
    return home / "Library/LaunchAgents" / f"{label}.plist"


def mac_domains(scope: Scope) -> list[str]:
    if scope.value == "system":
        return ["system"]
    uid = sudo_target_uid() if is_root_unix() else None
    uid = uid if uid is not None else os.getuid()
    return [f"gui/{uid}", f"user/{uid}"]


class MacBackend(Backend):
    def _plist_path(self, name: str) -> Path:
        return mac_plist_path(name, self.scope)

    def _label(self, name: str) -> str:
        return mac_label(name)

    def _domains(self) -> list[str]:
        return mac_domains(self.scope)

    def _bootout_all(self, plist_path: Path) -> None:
        for domain in self._domains():
            run(["launchctl", "bootout", domain, str(plist_path)], check=False, quiet=True)

    def _bootstrap(self, plist_path: Path) -> str:
        last_err = ""
        for domain in self._domains():
            run(["launchctl", "enable", f"{domain}/{plist_path.stem}"], check=False, quiet=True)
            cp = run(["launchctl", "bootstrap", domain, str(plist_path)], check=False, capture=True)
            if cp.returncode == 0:
                return domain
            out = (cp.stdout or "") + "\n" + (cp.stderr or "")
            last_err = out.strip() or f"launchctl bootstrap failed with exit code {cp.returncode}"
        raise SystemExit(last_err)

    def _load_legacy(self, plist_path: Path) -> bool:
        cp = run(["launchctl", "load", "-w", str(plist_path)], check=False, capture=True)
        logger.info("launchctl load -w rc=%s out=%r err=%r", cp.returncode, (cp.stdout or "").strip(), (cp.stderr or "").strip())
        return cp.returncode == 0

    def _unload_legacy(self, plist_path: Path) -> None:
        cp = run(["launchctl", "unload", "-w", str(plist_path)], check=False, capture=True)
        logger.info("launchctl unload -w rc=%s out=%r err=%r", cp.returncode, (cp.stdout or "").strip(), (cp.stderr or "").strip())

    def create(self, name: str, wd: Path, command_parts: list[str]) -> None:
        logger.info("mac create name=%s wd=%s", name, wd)
        plist_path = self._plist_path(name)
        plist_path.parent.mkdir(parents=True, exist_ok=True)

        label = self._label(name)
        cmd_str = command_string(command_parts)
        content = "\n".join(
            [
                '<?xml version="1.0" encoding="UTF-8"?>',
                '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">',
                '<plist version="1.0">',
                "<dict>",
                "  <key>Label</key>",
                f"  <string>{xml_escape(label)}</string>",
                "  <key>WorkingDirectory</key>",
                f"  <string>{xml_escape(str(wd))}</string>",
                "  <key>ProgramArguments</key>",
                "  <array>",
                "    <string>/bin/bash</string>",
                "    <string>-lc</string>",
                f"    <string>{xml_escape(cmd_str)}</string>",
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
        plist_path.write_text(content, encoding="utf-8")

        if self.scope.value == "system":
            os.chmod(plist_path, 0o644)

    def cat(self, name: str) -> None:
        logger.info("mac cat name=%s", name)
        plist_path = self._plist_path(name)
        if not plist_path.exists():
            raise SystemExit(f"Service not found: {name}")

        data = plistlib.loads(plist_path.read_bytes())
        wd = data.get("WorkingDirectory")
        args = data.get("ProgramArguments")
        if not isinstance(wd, str) or not isinstance(args, list) or len(args) < 3:
            raise SystemExit(f"Invalid plist: {plist_path}")

        cmd_str = args[2]
        if not isinstance(cmd_str, str):
            raise SystemExit(f"Invalid plist: {plist_path}")

        cmd_tokens = shlex.split(cmd_str)
        quoted_cmd = " ".join(shlex.quote(t) for t in cmd_tokens)
        scope_flag = "--system" if self.scope.value == "system" else "--user"
        print(f"uniservice add --name {shlex.quote(name)} {scope_flag} --workdir {shlex.quote(wd)} -- {quoted_cmd}")

    def exists(self, name: str) -> bool:
        plist_path = self._plist_path(name)
        exists = plist_path.exists()
        logger.debug("mac exists(%s)=%s path=%s", name, exists, plist_path)
        return exists

    def enable(self, name: str) -> None:
        logger.info("mac enable name=%s", name)
        plist_path = self._plist_path(name)
        if not plist_path.exists():
            raise SystemExit(f"Service not found: {name}")
        label = self._label(name)
        last_err = ""
        for domain in self._domains():
            cp = run(["launchctl", "enable", f"{domain}/{label}"], check=False, capture=True)
            if cp.returncode == 0:
                return
            text = (cp.stdout or "") + "\n" + (cp.stderr or "")
            last_err = text.strip() or f"launchctl enable failed (rc={cp.returncode})"
        raise SystemExit(last_err)

    def disable(self, name: str) -> None:
        logger.info("mac disable name=%s", name)
        plist_path = self._plist_path(name)
        label = self._label(name)
        last_err = ""
        for domain in self._domains():
            cp = run(["launchctl", "disable", f"{domain}/{label}"], check=False, capture=True)
            if cp.returncode == 0:
                return
            text = (cp.stdout or "") + "\n" + (cp.stderr or "")
            last_err = text.strip() or f"launchctl disable failed (rc={cp.returncode})"
        raise SystemExit(last_err)

    def start(self, name: str) -> None:
        logger.info("mac start name=%s", name)
        plist_path = self._plist_path(name)
        if not plist_path.exists():
            raise SystemExit(f"Service not found: {name}")
        label = self._label(name)
        bootstrap_err: SystemExit | None = None
        try:
            domain = self._bootstrap(plist_path)
            run(["launchctl", "enable", f"{domain}/{label}"], check=False)
            run(["launchctl", "kickstart", "-k", f"{domain}/{label}"], check=False)
            return
        except SystemExit as ex:
            bootstrap_err = ex
            logger.info("launchctl bootstrap failed for %s: %s", label, str(ex))
        if self._load_legacy(plist_path):
            run(["launchctl", "start", label], check=False, quiet=True)
            return
        raise bootstrap_err

    def stop(self, name: str) -> None:
        logger.info("mac stop name=%s", name)
        plist_path = self._plist_path(name)
        if not plist_path.exists():
            raise SystemExit(f"Service not found: {name}")

        label = self._label(name)
        for domain in self._domains():
            run(["launchctl", "kill", "SIGTERM", f"{domain}/{label}"], check=False, quiet=True)
            run(["launchctl", "stop", f"{domain}/{label}"], check=False, quiet=True)

        run(["launchctl", "kill", "SIGTERM", label], check=False, quiet=True)
        run(["launchctl", "stop", label], check=False, quiet=True)

        self._bootout_all(plist_path)
        self._unload_legacy(plist_path)

    def remove(self, name: str) -> None:
        logger.info("mac remove name=%s", name)
        plist_path = self._plist_path(name)
        if plist_path.exists():
            plist_path.unlink()

    def list_info(self) -> list[ServiceInfo]:
        logger.info("mac list_info")
        root = self._plist_path("X").parent
        if not root.exists():
            return []

        prefix = "com.uniservice."
        names: list[str] = []
        labels: list[str] = []
        for p in sorted(root.glob("com.uniservice.*.plist")):
            label = p.stem
            if label.startswith(prefix):
                names.append(label[len(prefix) :])
                labels.append(label)

        disabled_map: dict[str, bool] = {}
        for domain in self._domains():
            cp = run(["launchctl", "print-disabled", domain], check=False, capture=True)
            text = (cp.stdout or "") + "\n" + (cp.stderr or "")
            for m in re.finditer(r'"(?P<label>[^"]+)"\s*=>\s*(?P<state>enabled|disabled)', text, flags=re.IGNORECASE):
                lab = m.group("label")
                state = m.group("state").lower()
                disabled_map[lab] = state == "disabled"
            for m in re.finditer(r'"(?P<label>[^"]+)"\s*=>\s*(?P<flag>true|false)', text, flags=re.IGNORECASE):
                lab = m.group("label")
                flag = m.group("flag").lower() == "true"
                disabled_map[lab] = flag

        running_map: dict[str, bool] = {}
        cp_list = run(["launchctl", "list"], check=False, capture=True)
        for line in (cp_list.stdout or "").splitlines():
            parts = line.split()
            if len(parts) < 3:
                continue
            pid, _status, label = parts[0], parts[1], parts[2]
            if label in labels:
                running_map[label] = pid != "-"

        cmd_map: dict[str, str] = {}
        for p in sorted(root.glob("com.uniservice.*.plist")):
            label = p.stem
            if label not in labels:
                continue
            try:
                data = plistlib.loads(p.read_bytes())
            except Exception:
                continue
            args = data.get("ProgramArguments")
            if not isinstance(args, list) or len(args) < 3:
                continue
            cmd_str = args[2]
            if isinstance(cmd_str, str) and cmd_str.strip():
                cmd_map[label] = cmd_str.strip()

        out: list[ServiceInfo] = []
        for n, lab in zip(names, labels, strict=False):
            disabled = disabled_map.get(lab)
            enabled = None if disabled is None else (not disabled)
            running = running_map.get(lab)
            if running is None:
                cmd = cmd_map.get(lab)
                if cmd:
                    cp = run(["pgrep", "-f", cmd], check=False, quiet=True)
                    running = cp.returncode == 0
            out.append(ServiceInfo(name=n, enabled=enabled, running=running))

        return out
