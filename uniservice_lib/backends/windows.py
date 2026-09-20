"""Windows backend: Scheduled Tasks managed through ``schtasks.exe``.

The task *state* queries used for ``uniservice list`` go through
``Get-ScheduledTask`` (PowerShell) because ``schtasks.exe`` translates its
column headers and state words, which made ``list`` return nothing on any
non-English Windows installation.  A locale-independent ``schtasks.exe`` reader
is kept as a fallback for hosts where PowerShell is unavailable.
"""

from __future__ import annotations

import csv
import io
import json
import os
import subprocess
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from ..errors import ServiceNotFoundError, UniserviceError
from ..logging_utils import logger
from ..naming import parse_windows_task_name, windows_task_name
from ..platform_utils import is_admin_windows, win_cmdline_split
from ..process import run
from .base import Backend, ServiceInfo, classify_state

__all__ = [
    "WINDOWS_NOT_RUNNING_STATES",
    "WINDOWS_RUNNING_STATES",
    "WindowsBackend",
    "parse_powershell_task_json",
    "parse_schtasks_task_names",
    "parse_task_xml_enabled",
    "service_info_from_task",
    "win_build_tr",
]

SCHTASKS = "schtasks.exe"
POWERSHELL = "powershell.exe"

#: ``MSFT_TaskState`` values that mean the task currently has a process.
WINDOWS_RUNNING_STATES = frozenset({"running"})

#: ``MSFT_TaskState`` values that mean the task has no process.
WINDOWS_NOT_RUNNING_STATES = frozenset({"ready", "disabled"})

#: How long to wait after ``schtasks /Run`` before asking for the task state.
START_SETTLE_SECONDS = 0.6

#: Column headers that name the task name column on an English Windows.
_ENGLISH_TASK_NAME_COLUMNS = frozenset({"taskname", "task name", "task"})

#: One-liner PowerShell query that is immune to console locale and encoding.
#: Individual unreadable tasks are skipped (``SilentlyContinue``); only a missing
#: ``Get-ScheduledTask`` cmdlet is treated as a hard failure so that the caller
#: can fall back to ``schtasks.exe``.
POWERSHELL_TASK_QUERY = (
    "$ErrorActionPreference='SilentlyContinue'; "
    "if (-not (Get-Command Get-ScheduledTask -ErrorAction SilentlyContinue)) "
    "{ Write-Error 'Get-ScheduledTask is not available'; exit 1 }; "
    "$tasks = @(Get-ScheduledTask | Where-Object { $_.TaskName -like 'uniservice-*' }); "
    "$rows = @($tasks | ForEach-Object { "
    "$enabled = if ($null -ne $_.Settings -and $null -ne $_.Settings.Enabled) "
    "{ [bool]$_.Settings.Enabled } else { $true }; "
    "[pscustomobject]@{ name = [string]$_.TaskName; state = [string]$_.State; enabled = $enabled } }); "
    "if ($rows.Count -gt 0) { $rows | ConvertTo-Json -Compress }"
)


def win_build_tr(name: str, workdir: Path, command_parts: list[str]) -> str:
    """Build the ``/TR`` action: run *command_parts* in *workdir*, capturing logs."""
    cmdline = subprocess.list2cmdline(command_parts)
    workdir_str = str(workdir).replace('"', '""')
    cmdline_inner = cmdline.replace('"', '""')
    log_dir = win_log_dir()
    out_path = str(log_dir / f"{name}.out.log").replace('"', '""')
    err_path = str(log_dir / f"{name}.err.log").replace('"', '""')
    return f'cmd.exe /c "cd /d ""{workdir_str}"" && {cmdline_inner} 1>> ""{out_path}"" 2>> ""{err_path}"""'


def win_log_dir() -> Path:
    """Return the directory that holds captured task output."""
    program_data = os.environ.get("PROGRAMDATA") or r"C:\ProgramData"
    return Path(program_data) / "uniservice" / "logs" / "services"


def parse_powershell_task_json(text: str) -> list[dict[str, object]]:
    """Parse the JSON emitted by :data:`POWERSHELL_TASK_QUERY`."""
    cleaned = (text or "").lstrip("\ufeff").strip()
    if not cleaned:
        return []
    data = json.loads(cleaned)
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        raise ValueError("Unexpected PowerShell task query output.")
    return [row for row in data if isinstance(row, dict)]


def parse_schtasks_task_names(csv_text: str) -> list[str]:
    """Extract uniservice task names from ``schtasks /FO CSV`` output.

    The output is deliberately not keyed on the (localized) header names: the
    task name column is the one whose cells are task names, which is detected
    from the values themselves.
    """
    text = (csv_text or "").lstrip("\ufeff")
    if not text.strip():
        return []

    rows = [row for row in csv.reader(io.StringIO(text)) if row]
    if len(rows) < 2:
        return []
    header, data = rows[0], rows[1:]

    for index, column in enumerate(header):
        if column.strip().casefold() in _ENGLISH_TASK_NAME_COLUMNS:
            names = _names_in_column(data, index)
            if names:
                return sorted(set(names), key=lambda item: (item.casefold(), item))

    best: list[str] = []
    for index in range(len(header)):
        names = _names_in_column(data, index)
        if len(names) > len(best):
            best = names
    return sorted(set(best), key=lambda item: (item.casefold(), item))


def parse_task_xml_enabled(xml_text: str) -> bool | None:
    """Return ``Settings/Enabled`` from a Scheduled Task XML definition.

    The result is locale-independent because the Task Scheduler XML schema uses
    English element names.  Only ``Settings/Enabled`` is consulted: trigger
    elements have an ``Enabled`` child of their own.
    """
    text = (xml_text or "").lstrip("\ufeff").strip()
    if not text:
        return None
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return None

    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] != "Settings":
            continue
        for child in element:
            if child.tag.rsplit("}", 1)[-1] == "Enabled" and child.text is not None:
                return child.text.strip().lower() == "true"
        return True  # <Enabled> is optional and defaults to true
    return True


def service_info_from_task(row: dict[str, object]) -> ServiceInfo | None:
    """Convert one PowerShell result object into a :class:`ServiceInfo`."""
    name = parse_windows_task_name(str(row.get("name") or ""))
    if name is None or not name.strip():
        return None

    enabled_value = row.get("enabled")
    enabled = enabled_value if isinstance(enabled_value, bool) else None
    running = classify_state(
        str(row.get("state") or ""),
        true_states=WINDOWS_RUNNING_STATES,
        false_states=WINDOWS_NOT_RUNNING_STATES,
    )
    return ServiceInfo(name=name, enabled=enabled, running=running)


def _names_in_column(rows: list[list[str]], index: int) -> list[str]:
    names: list[str] = []
    for row in rows:
        if index >= len(row):
            return []
        cell = row[index].strip()
        if not cell:
            continue
        name = parse_windows_task_name(cell)
        if name is None or not name.strip():
            continue
        names.append(name)
    return names


class WindowsBackend(Backend):
    """Scheduled Task backend used on Windows."""

    def _require_admin(self) -> None:
        if not is_admin_windows():
            raise UniserviceError("Windows only supports admin execution for uniservice.")

    def _task_name(self, name: str) -> str:
        return windows_task_name(name)

    def create(self, name: str, workdir: Path, command_parts: list[str]) -> None:
        logger.info("windows create name=%s workdir=%s", name, workdir)
        self._require_admin()
        run(
            [
                SCHTASKS,
                "/Create",
                "/TN",
                self._task_name(name),
                "/TR",
                win_build_tr(name, workdir, command_parts),
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
        task_name = self._task_name(name)
        completed = run([SCHTASKS, "/Query", "/TN", task_name, "/XML"], check=False, capture=True)
        if completed.returncode != 0:
            raise ServiceNotFoundError(name)

        xml_text = (completed.stdout or "").lstrip("\ufeff")
        root = ET.fromstring(xml_text)

        command: str | None = None
        arguments: str | None = None
        for element in root.iter():
            tag = element.tag.rsplit("}", 1)[-1]
            if tag == "Command" and element.text:
                command = element.text.strip()
            if tag == "Arguments" and element.text:
                arguments = element.text.strip()

        if not command or not arguments:
            raise UniserviceError("Unable to read the scheduled task command.")

        workdir, cmdline = _split_task_action(command, arguments)
        if workdir and cmdline:
            argv = win_cmdline_split(cmdline)
            quoted = subprocess.list2cmdline(argv)
            print(f'uniservice add "{name}" --workdir "{workdir}" -- {quoted}')
            return

        print(f"{command} {arguments}")

    def status(self, name: str) -> None:
        logger.info("windows status name=%s", name)
        self._require_admin()
        run([SCHTASKS, "/Query", "/TN", self._task_name(name), "/V", "/FO", "LIST"], check=False)

    def logs(self, name: str, *, lines: int, follow: bool) -> None:
        logger.info("windows logs name=%s lines=%s follow=%s", name, lines, follow)
        self._require_admin()
        log_dir = win_log_dir()
        out_path = log_dir / f"{name}.out.log"
        err_path = log_dir / f"{name}.err.log"
        if follow:
            run(
                [
                    POWERSHELL,
                    "-NoProfile",
                    "-Command",
                    f"Get-Content -LiteralPath @('{out_path}','{err_path}') -Tail {lines} -Wait",
                ],
                check=False,
            )
        else:
            for path in (out_path, err_path):
                run(
                    [
                        POWERSHELL,
                        "-NoProfile",
                        "-Command",
                        f'Get-Content -LiteralPath "{path}" -Tail {lines}',
                    ],
                    check=False,
                )

    def exists(self, name: str) -> bool:
        self._require_admin()
        completed = run([SCHTASKS, "/Query", "/TN", self._task_name(name)], check=False, quiet=True)
        exists = completed.returncode == 0
        logger.debug("windows exists(%s)=%s", name, exists)
        return exists

    def enable(self, name: str) -> None:
        logger.info("windows enable name=%s", name)
        self._require_admin()
        run([SCHTASKS, "/Change", "/TN", self._task_name(name), "/Enable"], capture=True)

    def disable(self, name: str) -> None:
        logger.info("windows disable name=%s", name)
        self._require_admin()
        run([SCHTASKS, "/Change", "/TN", self._task_name(name), "/Disable"], capture=True)

    def start(self, name: str) -> None:
        logger.info("windows start name=%s", name)
        self._require_admin()
        task_name = self._task_name(name)
        run([SCHTASKS, "/Run", "/TN", task_name], capture=True)
        time.sleep(START_SETTLE_SECONDS)
        info = self._query_task_info(name)
        status = (info.get("status") or "").lower()
        last_result = info.get("last run result") or info.get("last result") or ""
        if status != "running" and last_result and last_result not in {"0x0", "0"}:
            raise UniserviceError(f'Task "{task_name}" exited. Last Run Result={last_result}')

    def stop(self, name: str) -> None:
        logger.info("windows stop name=%s", name)
        self._require_admin()
        run([SCHTASKS, "/End", "/TN", self._task_name(name)], check=False, capture=True)

    def remove(self, name: str) -> None:
        logger.info("windows remove name=%s", name)
        self._require_admin()
        run([SCHTASKS, "/Delete", "/TN", self._task_name(name), "/F"], check=False, capture=True)

    def list_info(self) -> list[ServiceInfo]:
        """Return every ``uniservice-*`` task without requiring elevation.

        Querying the Task Scheduler is read-only, so unlike the mutating
        commands ``list`` works for non-administrators as well.
        """
        logger.info("windows list_info")
        services = self._list_via_powershell()
        if services is None:
            services = self._list_via_schtasks()
        return services

    def _list_via_powershell(self) -> list[ServiceInfo] | None:
        try:
            completed = run(
                [POWERSHELL, "-NoProfile", "-NonInteractive", "-Command", POWERSHELL_TASK_QUERY],
                check=False,
                capture=True,
            )
        except OSError as exc:
            logger.warning("PowerShell is unavailable: %s", exc)
            return None

        if completed.returncode != 0:
            logger.warning(
                "PowerShell scheduled task query failed (rc=%s): %s",
                completed.returncode,
                (completed.stderr or "").strip(),
            )
            return None

        try:
            rows = parse_powershell_task_json(completed.stdout or "")
        except (ValueError, json.JSONDecodeError) as exc:
            logger.warning("Could not parse the PowerShell task query output: %s", exc)
            return None

        services = [service_info_from_task(row) for row in rows]
        return [service for service in services if service is not None]

    def _list_via_schtasks(self) -> list[ServiceInfo]:
        completed = run([SCHTASKS, "/Query", "/FO", "CSV", "/V"], check=False, capture=True)
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip() or f"exit code {completed.returncode}"
            raise UniserviceError(f"Could not query scheduled tasks: {detail}")

        names = parse_schtasks_task_names(completed.stdout or "")
        return [ServiceInfo(name=name, enabled=self._task_enabled(name), running=None) for name in names]

    def _task_enabled(self, name: str) -> bool | None:
        completed = run(
            [SCHTASKS, "/Query", "/TN", self._task_name(name), "/XML"],
            check=False,
            capture=True,
        )
        if completed.returncode != 0:
            return None
        return parse_task_xml_enabled(completed.stdout or "")

    def _query_task_info(self, name: str) -> dict[str, str]:
        completed = run(
            [SCHTASKS, "/Query", "/TN", self._task_name(name), "/V", "/FO", "LIST"],
            check=False,
            capture=True,
        )
        text = (completed.stdout or "") + "\n" + (completed.stderr or "")
        info: dict[str, str] = {}
        for line in text.splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            key = key.strip().lower()
            value = value.strip()
            if key and value:
                info[key] = value
        return info


def _split_task_action(command: str, arguments: str) -> tuple[str, str]:
    """Recover ``(workdir, cmdline)`` from a ``cmd.exe /c "cd /d ..."`` action."""
    if not command.lower().endswith("cmd.exe") or not arguments.lower().startswith("/c"):
        return "", ""

    rest = arguments[2:].lstrip()
    if len(rest) >= 2 and rest.startswith('"') and rest.endswith('"'):
        rest = rest[1:-1]
    inner = rest.replace('""', '"')

    prefix = "cd /d "
    if not inner.lower().startswith(prefix):
        return "", ""

    after = inner[len(prefix) :]
    if not after.startswith('"'):
        return "", ""
    end = after.find('"', 1)
    if end == -1:
        return "", ""

    workdir = after[1:end]
    remainder = after[end + 1 :]
    if remainder.startswith(" && "):
        return workdir, remainder[4:]
    return workdir, ""
