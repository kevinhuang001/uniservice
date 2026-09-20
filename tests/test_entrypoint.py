"""End-to-end tests that execute the real ``uniservice`` launcher.

These tests do not mock anything: they run the shipped script as the user would,
which also covers the launcher's ``sys.path`` bootstrap.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.conftest import CLI_PATH
from uniservice_lib.backends.macos import render_plist

SYSTEMCTL_STUB = """#!/usr/bin/env bash
for arg in "$@"; do
  case "$arg" in
    is-enabled) echo enabled; exit 0 ;;
    is-active) echo active; exit 0 ;;
  esac
done
exit 0
"""

LAUNCHCTL_STUB = """#!/usr/bin/env bash
case "$1" in
  print-disabled) printf 'disabled services = {\\n}\\n'; exit 0 ;;
  list) printf 'PID\\tStatus\\tLabel\\n'; exit 0 ;;
  print) printf '\\tpid = 4242\\n'; exit 0 ;;
esac
exit 0
"""


def run_cli(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """Run the shipped launcher with *args* in a subprocess."""
    environment = os.environ.copy()
    if env:
        environment.update(env)
    return subprocess.run(
        [sys.executable, str(CLI_PATH), *args],
        capture_output=True,
        text=True,
        env=environment,
        timeout=180,
        check=False,
    )


def test_launcher_reports_its_version() -> None:
    completed = run_cli("--version")
    assert completed.returncode == 0
    assert "uniservice" in completed.stdout


def test_launcher_prints_help() -> None:
    completed = run_cli("--help")
    assert completed.returncode == 0
    assert "COMMAND" in completed.stdout


def test_launcher_rejects_unknown_commands() -> None:
    completed = run_cli("definitely-not-a-command")
    assert completed.returncode == 2


def test_launcher_lists_on_the_host_platform(tmp_path: Path) -> None:
    """Exercise the real service manager of the host with an isolated HOME."""
    completed = run_cli("list", env={"HOME": str(tmp_path), "USERPROFILE": str(tmp_path)})
    combined = (completed.stdout + completed.stderr).lower()
    if completed.returncode != 0 and ("admin" in combined or "permission" in combined or "sudo" in combined):
        pytest.skip("querying services requires elevated privileges on this host")

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.splitlines()[0] == "NAME\tENABLED\tRUNNING"


@pytest.mark.skipif(os.name == "nt", reason="uses POSIX stub executables")
def test_launcher_lists_real_definitions_end_to_end(tmp_path: Path) -> None:
    """Write a definition, stub the OS tool and check the full TSV pipeline."""
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)

    if sys.platform == "darwin":
        stub_name, stub = "launchctl", LAUNCHCTL_STUB
        definition_dir = home / "Library" / "LaunchAgents"
        definition_dir.mkdir(parents=True)
        (definition_dir / "com.uniservice.demo.plist").write_text(
            render_plist(
                "com.uniservice.demo",
                Path("/tmp"),
                "/usr/bin/true",
                home / "demo.out.log",
                home / "demo.err.log",
            ),
            encoding="utf-8",
        )
    else:
        stub_name, stub = "systemctl", SYSTEMCTL_STUB
        definition_dir = home / ".config" / "systemd" / "user"
        definition_dir.mkdir(parents=True)
        (definition_dir / "uniservice-demo.service").write_text(
            "[Service]\nExecStart=/usr/bin/true\n",
            encoding="utf-8",
        )

    stub_path = bindir / stub_name
    stub_path.write_text(stub, encoding="utf-8")
    stub_path.chmod(0o755)

    environment = {
        "HOME": str(home),
        "USERPROFILE": str(home),
        "PATH": f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}",
    }
    completed = run_cli("list", env=environment)

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.splitlines() == ["NAME\tENABLED\tRUNNING", "demo\tyes\tyes"]
