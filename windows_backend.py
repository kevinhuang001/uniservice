from __future__ import annotations

import csv
import io
import subprocess
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from backend_base import Backend, ServiceInfo
from utils import is_admin_windows, logger, run, win_cmdline_split


def win_task_name(name: str) -> str:
    return f"uniservice-{name}"


def win_build_tr(wd: Path, command_parts: list[str]) -> str:
    cmdline = subprocess.list2cmdline(command_parts)
    wd_str = str(wd).replace('"', '""')
    cmdline_inner = cmdline.replace('"', '""')
    return f'cmd.exe /c "cd /d ""{wd_str}"" && {cmdline_inner}"'


class WindowsBackend(Backend):
    def _require_admin(self) -> None:
        if not is_admin_windows():
            raise SystemExit("Windows only supports admin execution for uniservice.")

    def _task_name(self, name: str) -> str:
        return win_task_name(name)

    def create(self, name: str, wd: Path, command_parts: list[str]) -> None:
        logger.info("windows create name=%s wd=%s", name, wd)
        self._require_admin()
        tn = self._task_name(name)
        tr = win_build_tr(wd, command_parts)
        run(
            [
                "schtasks.exe",
                "/Create",
                "/TN",
                tn,
                "/TR",
                tr,
                "/SC",
                "ONSTART",
                "/RU",
                "SYSTEM",
                "/RL",
                "HIGHEST",
                "/F",
            ],
            capture=True,
        )

    def cat(self, name: str) -> None:
        logger.info("windows cat name=%s", name)
        self._require_admin()
        tn = self._task_name(name)
        cp = run(["schtasks.exe", "/Query", "/TN", tn, "/XML"], check=False, capture=True)
        if cp.returncode != 0:
            raise SystemExit(f"Service not found: {name}")

        xml_text = (cp.stdout or "").lstrip("\ufeff")
        root = ET.fromstring(xml_text)

        cmd: str | None = None
        args: str | None = None
        for el in root.iter():
            tag = el.tag.rsplit("}", 1)[-1]
            if tag == "Command" and el.text:
                cmd = el.text.strip()
            if tag == "Arguments" and el.text:
                args = el.text.strip()

        if not cmd or not args:
            raise SystemExit("Unable to read task command.")

        workdir = ""
        cmdline = ""
        if cmd.lower().endswith("cmd.exe") and args.lower().startswith("/c"):
            rest = args[2:].lstrip()
            if rest.startswith('"') and rest.endswith('"'):
                inner = rest[1:-1].replace('""', '"')
            else:
                inner = rest.replace('""', '"')

            lower = inner.lower()
            prefix = "cd /d "
            if lower.startswith(prefix):
                after = inner[len(prefix) :]
                if after.startswith('"'):
                    end = after.find('"', 1)
                    if end != -1:
                        workdir = after[1:end]
                        remain = after[end + 1 :]
                        if remain.startswith(" && "):
                            cmdline = remain[4:]

        if workdir and cmdline:
            argv = win_cmdline_split(cmdline)
            quoted = " ".join(shlex_quote_windows(a) for a in argv)
            print(f'uniservice add --name "{name}" --workdir "{workdir}" -- {quoted}')
            return

        print(f"{cmd} {args}")

    def exists(self, name: str) -> bool:
        self._require_admin()
        tn = self._task_name(name)
        cp = run(["schtasks.exe", "/Query", "/TN", tn], check=False, quiet=True)
        exists = cp.returncode == 0
        logger.debug("windows exists(%s)=%s", name, exists)
        return exists

    def enable(self, name: str) -> None:
        logger.info("windows enable name=%s", name)
        self._require_admin()
        tn = self._task_name(name)
        run(["schtasks.exe", "/Change", "/TN", tn, "/Enable"], capture=True)

    def disable(self, name: str) -> None:
        logger.info("windows disable name=%s", name)
        self._require_admin()
        tn = self._task_name(name)
        run(["schtasks.exe", "/Change", "/TN", tn, "/Disable"], capture=True)

    def start(self, name: str) -> None:
        logger.info("windows start name=%s", name)
        self._require_admin()
        tn = self._task_name(name)
        run(["schtasks.exe", "/Run", "/TN", tn], capture=True)
        time.sleep(0.6)
        info = self._query_task_info(name)
        status = (info.get("status") or "").lower()
        last_result = info.get("last run result") or info.get("last result") or ""
        if status != "running" and last_result and last_result not in {"0x0", "0"}:
            raise SystemExit(f'Task "{tn}" exited. Last Run Result={last_result}')

    def stop(self, name: str) -> None:
        logger.info("windows stop name=%s", name)
        self._require_admin()
        tn = self._task_name(name)
        run(["schtasks.exe", "/End", "/TN", tn], check=False, capture=True)

    def remove(self, name: str) -> None:
        logger.info("windows remove name=%s", name)
        self._require_admin()
        tn = self._task_name(name)
        run(["schtasks.exe", "/Delete", "/TN", tn, "/F"], check=False, capture=True)

    def list_info(self) -> list[ServiceInfo]:
        logger.info("windows list_info")
        self._require_admin()
        cp = run(["schtasks.exe", "/Query", "/FO", "CSV", "/V"], check=False, capture=True)
        text = cp.stdout or ""
        if not text.strip():
            return []

        out: list[ServiceInfo] = []
        reader = csv.DictReader(io.StringIO(text))
        for row in reader:
            tn = (row.get("TaskName") or "").strip()
            base = tn.split("\\")[-1]
            if not base.startswith("uniservice-"):
                continue
            name = base[len("uniservice-") :]
            status = (row.get("Status") or row.get("Task Status") or "").strip().lower()
            state = (row.get("Scheduled Task State") or row.get("State") or "").strip().lower()

            running: bool | None
            if status == "running":
                running = True
            elif status:
                running = False
            else:
                running = None

            enabled: bool | None
            if state == "enabled":
                enabled = True
            elif state == "disabled":
                enabled = False
            else:
                enabled = None

            out.append(ServiceInfo(name=name, enabled=enabled, running=running))

        return out

    def _query_task_info(self, name: str) -> dict[str, str]:
        tn = self._task_name(name)
        cp = run(["schtasks.exe", "/Query", "/TN", tn, "/V", "/FO", "LIST"], check=False, capture=True)
        text = (cp.stdout or "") + "\n" + (cp.stderr or "")
        info: dict[str, str] = {}
        for line in text.splitlines():
            if ":" not in line:
                continue
            k, v = line.split(":", 1)
            k = k.strip().lower()
            v = v.strip()
            if k and v:
                info[k] = v
        return info


def shlex_quote_windows(s: str) -> str:
    if not s:
        return '""'
    if any(ch in s for ch in ' \t"'):
        return '"' + s.replace('"', '\\"') + '"'
    return s
