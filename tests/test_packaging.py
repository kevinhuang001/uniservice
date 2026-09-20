"""Tests for the single-file zipapp artifact that the installers ship."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import zipfile
from pathlib import Path
from types import ModuleType

import pytest

from tests.conftest import REPO_ROOT

BUILD_SCRIPT = REPO_ROOT / "scripts" / "build_zipapp.py"


def _load_build_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("uniservice_build_zipapp", BUILD_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build_module = _load_build_module()


@pytest.fixture
def zipapp(tmp_path: Path) -> Path:
    return build_module.build(tmp_path / "dist" / "uniservice")


def test_build_creates_an_executable_file(zipapp: Path) -> None:
    assert zipapp.is_file()
    assert zipapp.stat().st_size > 10_000
    if os.name != "nt":
        assert os.access(zipapp, os.X_OK)


def test_build_packages_the_whole_package(zipapp: Path) -> None:
    with zipfile.ZipFile(zipapp) as archive:
        names = set(archive.namelist())

    assert "__main__.py" in names
    assert "uniservice_lib/__init__.py" in names
    assert "uniservice_lib/cli.py" in names
    assert "uniservice_lib/backends/linux.py" in names
    assert "uniservice_lib/backends/macos.py" in names
    assert "uniservice_lib/backends/windows.py" in names
    assert not [name for name in names if "__pycache__" in name]


def test_build_is_reproducible(tmp_path: Path) -> None:
    first = build_module.build(tmp_path / "a" / "uniservice")
    second = build_module.build(tmp_path / "b" / "uniservice")
    assert first.read_bytes() == second.read_bytes()
    assert build_module.sha256_of(first) == build_module.sha256_of(second)


def test_build_rejects_a_source_tree_without_the_package(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        build_module.build(tmp_path / "out", source=tmp_path)


def test_zipapp_runs_the_cli(zipapp: Path) -> None:
    completed = subprocess.run(
        [sys.executable, str(zipapp), "--version"],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip().startswith("uniservice ")


def test_zipapp_lists_services(zipapp: Path) -> None:
    completed = subprocess.run(
        [sys.executable, str(zipapp), "list"],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.splitlines()[0] == "NAME\tENABLED\tRUNNING"


def test_zipapp_reports_its_scope_epilog(zipapp: Path) -> None:
    completed = subprocess.run(
        [sys.executable, str(zipapp), "--help"],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert completed.returncode == 0
    assert "sudo" in completed.stdout


def test_command_line_build_prints_the_digest(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    output = tmp_path / "uniservice"
    assert build_module.main(["--output", str(output)]) == 0

    printed = capsys.readouterr().out
    assert "Built" in printed
    assert build_module.sha256_of(output) in printed


def test_command_line_build_quiet_prints_only_the_path(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    output = tmp_path / "uniservice"
    assert build_module.main(["--output", str(output), "--quiet"]) == 0
    assert capsys.readouterr().out.strip() == str(output)


def test_command_line_build_reports_a_bad_source(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert build_module.main(["--output", str(tmp_path / "out"), "--source", str(tmp_path)]) == 1
    assert "uniservice_lib not found" in capsys.readouterr().err
