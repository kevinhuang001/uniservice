"""Opt-in tests that drive the real OS service manager.

They are skipped unless ``UNISERVICE_RUN_INTEGRATION=1`` is set because they
register, start and remove a real service on the host:

    UNISERVICE_RUN_INTEGRATION=1 python -m pytest -m integration -v

Each test additionally skips itself when the host has no usable service manager
(for example a CI container without a systemd user session).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from uniservice_lib import cli
from uniservice_lib.backends.base import ServiceInfo
from uniservice_lib.backends.linux import LinuxBackend
from uniservice_lib.backends.macos import MacOSBackend
from uniservice_lib.backends.windows import WindowsBackend
from uniservice_lib.scope import Scope

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("UNISERVICE_RUN_INTEGRATION") != "1",
        reason="set UNISERVICE_RUN_INTEGRATION=1 to exercise the real service manager",
    ),
]


def _have_user_systemd() -> bool:
    if sys.platform != "linux" or shutil.which("systemctl") is None:
        return False
    completed = subprocess.run(
        ["systemctl", "--user", "is-system-running"],
        capture_output=True,
        text=True,
        check=False,
    )
    output = (completed.stdout + completed.stderr).lower()
    return completed.returncode == 0 or "running" in output or "degraded" in output


def _have_launchd() -> bool:
    if sys.platform != "darwin" or shutil.which("launchctl") is None:
        return False
    completed = subprocess.run(
        ["launchctl", "print", f"gui/{os.getuid()}"],
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.returncode == 0


def _have_schtasks() -> bool:
    if os.name != "nt" or shutil.which("schtasks.exe") is None:
        return False
    from uniservice_lib.platform_utils import is_admin_windows

    return is_admin_windows()


def _find(rows: list[ServiceInfo], name: str) -> ServiceInfo | None:
    return next((row for row in rows if row.name == name), None)


@pytest.mark.skipif(not _have_user_systemd(), reason="no usable systemd user session")
def test_linux_service_lifecycle(tmp_path: Path) -> None:
    name = f"itest-{os.getpid()}"
    backend = LinuxBackend(Scope("user"))
    try:
        assert cli.main(["add", name, "--workdir", str(tmp_path), "--", "/bin/sleep", "300"]) == 0
        row = _find(backend.list_info(), name)
        assert row is not None, "the created service must appear in list"
        assert row.enabled is True
        assert row.running is True
    finally:
        cli.main(["remove", name])
    assert _find(backend.list_info(), name) is None


@pytest.mark.skipif(not _have_launchd(), reason="no usable launchd user domain")
def test_macos_service_lifecycle(tmp_path: Path) -> None:
    name = f"itest-{os.getpid()}"
    backend = MacOSBackend(Scope("user"))
    try:
        assert cli.main(["add", name, "--workdir", str(tmp_path), "--", "/bin/sleep", "300"]) == 0
        row = _find(backend.list_info(), name)
        assert row is not None, "the created service must appear in list"
        assert row.enabled is True
        assert row.running is True
    finally:
        cli.main(["remove", name])
    assert _find(backend.list_info(), name) is None


@pytest.mark.skipif(not _have_schtasks(), reason="schtasks.exe is not available")
def test_windows_service_lifecycle(tmp_path: Path) -> None:
    name = f"itest-{os.getpid()}"
    backend = WindowsBackend(Scope("system"))
    try:
        assert cli.main(["add", name, "--workdir", str(tmp_path), "--", "cmd.exe", "/c", "exit", "0"]) == 0
        row = _find(backend.list_info(), name)
        assert row is not None, "the created task must appear in list"
        assert row.enabled is True
    finally:
        cli.main(["remove", name])
    assert _find(backend.list_info(), name) is None
