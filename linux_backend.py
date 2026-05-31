from __future__ import annotations

import shlex
import shutil
from pathlib import Path

from backend_base import Backend, ServiceInfo
from utils import Scope, command_string, logger, run


def unit_filename(name: str) -> str:
    return f"uniservice-{name}.service"


def linux_unit_path(name: str, scope: Scope) -> Path:
    if scope.value == "system":
        return Path("/etc/systemd/system") / unit_filename(name)
    return Path.home() / ".config/systemd/user" / unit_filename(name)


def linux_systemctl_args(scope: Scope) -> list[str]:
    if scope.value == "user":
        return ["systemctl", "--user"]
    return ["systemctl"]


class LinuxBackend(Backend):
    def _unit_path(self, name: str) -> Path:
        return linux_unit_path(name, self.scope)

    def _systemctl(self) -> list[str]:
        return linux_systemctl_args(self.scope)

    def create(self, name: str, wd: Path, command_parts: list[str]) -> None:
        logger.info("linux create name=%s wd=%s", name, wd)
        if shutil.which("systemctl") is None:
            raise SystemExit("systemctl not found; systemd is required on Linux.")

        unit_path = self._unit_path(name)
        unit_path.parent.mkdir(parents=True, exist_ok=True)

        cmd_str = command_string(command_parts)
        cmd_arg = shlex.quote(cmd_str)

        wanted_by = "multi-user.target" if self.scope.value == "system" else "default.target"
        content = "\n".join(
            [
                "[Unit]",
                f"Description=uniservice {name}",
                "After=network.target",
                "",
                "[Service]",
                "Type=simple",
                f"WorkingDirectory={wd}",
                f"ExecStart=/usr/bin/env bash -lc {cmd_arg}",
                "Restart=always",
                "RestartSec=2",
                "",
                "[Install]",
                f"WantedBy={wanted_by}",
                "",
            ]
        )
        unit_path.write_text(content, encoding="utf-8")

    def cat(self, name: str) -> None:
        logger.info("linux cat name=%s", name)
        unit_path = self._unit_path(name)
        if not unit_path.exists():
            raise SystemExit(f"Service not found: {name}")

        wd: str | None = None
        exec_start: str | None = None
        for line in unit_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("WorkingDirectory="):
                wd = line.split("=", 1)[1].strip()
            if line.startswith("ExecStart="):
                exec_start = line.split("=", 1)[1].strip()

        if wd is None or exec_start is None:
            raise SystemExit(f"Invalid unit file: {unit_path}")

        tokens = shlex.split(exec_start)
        try:
            idx = tokens.index("-lc")
        except ValueError:
            raise SystemExit(f"Unsupported ExecStart format: {exec_start}")

        if idx + 1 >= len(tokens):
            raise SystemExit(f"Unsupported ExecStart format: {exec_start}")

        cmd_str = tokens[idx + 1]
        cmd_tokens = shlex.split(cmd_str)
        quoted_cmd = " ".join(shlex.quote(t) for t in cmd_tokens)
        scope_flag = "--system" if self.scope.value == "system" else "--user"
        print(f"uniservice add --name {shlex.quote(name)} {scope_flag} --workdir {shlex.quote(wd)} -- {quoted_cmd}")

    def exists(self, name: str) -> bool:
        unit_path = self._unit_path(name)
        exists = unit_path.exists()
        logger.debug("linux exists(%s)=%s path=%s", name, exists, unit_path)
        return exists

    def enable(self, name: str) -> None:
        logger.info("linux enable name=%s", name)
        base = self._systemctl()
        run(base + ["daemon-reload"])
        run(base + ["enable", unit_filename(name)])

    def disable(self, name: str) -> None:
        logger.info("linux disable name=%s", name)
        base = self._systemctl()
        run(base + ["daemon-reload"])
        run(base + ["disable", unit_filename(name)])
        run(base + ["reset-failed", unit_filename(name)], check=False)

    def start(self, name: str) -> None:
        logger.info("linux start name=%s", name)
        base = self._systemctl()
        run(base + ["daemon-reload"])
        run(base + ["start", unit_filename(name)])

    def stop(self, name: str) -> None:
        logger.info("linux stop name=%s", name)
        base = self._systemctl()
        run(base + ["stop", unit_filename(name)])

    def remove(self, name: str) -> None:
        logger.info("linux remove name=%s", name)
        unit_path = self._unit_path(name)
        if unit_path.exists():
            unit_path.unlink()

    def list_info(self) -> list[ServiceInfo]:
        logger.info("linux list_info")
        root = self._unit_path("X").parent
        if not root.exists():
            return []

        names: list[str] = []
        for p in sorted(root.glob("uniservice-*.service")):
            stem = p.stem
            prefix = "uniservice-"
            if stem.startswith(prefix):
                names.append(stem[len(prefix) :])

        if shutil.which("systemctl") is None:
            return [ServiceInfo(name=n, enabled=None, running=None) for n in names]

        base = self._systemctl()
        out: list[ServiceInfo] = []
        for n in names:
            unit = unit_filename(n)
            cp_enabled = run(base + ["is-enabled", unit], check=False, capture=True)
            enabled_text = ((cp_enabled.stdout or "") + (cp_enabled.stderr or "")).strip().lower()
            enabled: bool | None
            if enabled_text.startswith("enabled"):
                enabled = True
            elif enabled_text.startswith(("disabled", "masked", "static", "indirect", "generated", "transient")):
                enabled = False
            else:
                enabled = None

            cp_active = run(base + ["is-active", unit], check=False, capture=True)
            active_text = ((cp_active.stdout or "") + (cp_active.stderr or "")).strip().lower()
            if active_text.startswith("active"):
                running = True
            elif active_text:
                running = False
            else:
                running = None

            out.append(ServiceInfo(name=n, enabled=enabled, running=running))

        return out
