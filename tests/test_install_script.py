"""End-to-end tests for ``install.sh``.

Every test runs the real installer in a subprocess against a throwaway prefix, so
the install -> verify -> uninstall lifecycle, the manifest and the PATH policy are
all exercised for real.  ``--from`` is not needed: the installer notices that it
is running from a checkout and builds the local sources.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.conftest import REPO_ROOT

INSTALLER = REPO_ROOT / "install.sh"

pytestmark = pytest.mark.skipif(os.name == "nt", reason="install.sh is POSIX-only")


def run_installer(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.setdefault("SHELL", "/bin/sh")
    if env:
        environment.update(env)
    return subprocess.run(
        ["bash", str(INSTALLER), *args],
        capture_output=True,
        text=True,
        env=environment,
        timeout=300,
        check=False,
    )


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_help_lists_the_options() -> None:
    completed = run_installer("--help")
    assert completed.returncode == 0
    for flag in ("--prefix", "--version", "--sha256", "--from", "--uninstall", "--no-modify-path"):
        assert flag in completed.stdout


def test_unknown_option_is_rejected() -> None:
    completed = run_installer("--definitely-not-an-option")
    assert completed.returncode == 1
    assert "unknown option" in completed.stderr


def test_install_then_uninstall_round_trip(tmp_path: Path) -> None:
    prefix = tmp_path / "pfx"

    installed = run_installer("--prefix", str(prefix), "--no-modify-path")
    assert installed.returncode == 0, installed.stderr

    binary = prefix / "bin" / "uniservice"
    manifest_path = prefix / "lib" / "uniservice" / "install.json"
    assert binary.is_file()
    assert os.access(binary, os.X_OK)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema"] == 1
    assert manifest["prefix"] == str(prefix)
    assert manifest["files"] == [str(binary)]
    assert len(manifest["sha256"]) == 64
    assert manifest["sha256"] == sha256_of(binary)
    assert manifest["version"]
    assert manifest["profile_files"] == []

    completed = subprocess.run(
        [sys.executable, str(binary), "--version"],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert completed.returncode == 0
    assert completed.stdout.strip().startswith("uniservice ")

    removed = run_installer("--uninstall", "--prefix", str(prefix))
    assert removed.returncode == 0, removed.stderr
    assert not binary.exists()
    assert not manifest_path.exists()
    # Only empty directories are pruned, so a throwaway prefix disappears
    # entirely while a prefix holding anything else is left alone.
    assert not prefix.exists()


def test_uninstall_leaves_a_prefix_that_holds_other_files(tmp_path: Path) -> None:
    prefix = tmp_path / "pfx"
    assert run_installer("--prefix", str(prefix), "--no-modify-path").returncode == 0
    keeper = prefix / "keep.txt"
    keeper.write_text("not ours\n", encoding="utf-8")

    assert run_installer("--uninstall", "--prefix", str(prefix)).returncode == 0

    assert keeper.read_text(encoding="utf-8") == "not ours\n"
    assert not (prefix / "bin" / "uniservice").exists()
    assert not (prefix / "lib").exists()


def test_installed_artifact_is_a_single_self_contained_file(tmp_path: Path) -> None:
    """Copying just the executable to a bare directory must be enough."""
    prefix = tmp_path / "pfx"
    assert run_installer("--prefix", str(prefix), "--no-modify-path").returncode == 0

    standalone = tmp_path / "elsewhere" / "uniservice"
    standalone.parent.mkdir()
    standalone.write_bytes((prefix / "bin" / "uniservice").read_bytes())
    standalone.chmod(0o755)

    completed = subprocess.run(
        [sys.executable, str(standalone), "--version"],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip().startswith("uniservice ")


def test_checksum_verification_accepts_the_reproducible_build(tmp_path: Path) -> None:
    from tests.test_packaging import build_module

    reference = build_module.build(tmp_path / "reference" / "uniservice")
    digest = build_module.sha256_of(reference)

    prefix = tmp_path / "pfx"
    completed = run_installer("--prefix", str(prefix), "--no-modify-path", "--sha256", digest)
    assert completed.returncode == 0, completed.stderr
    assert "SHA-256 verified" in completed.stdout
    assert sha256_of(prefix / "bin" / "uniservice") == digest


def test_checksum_verification_rejects_a_wrong_digest(tmp_path: Path) -> None:
    prefix = tmp_path / "pfx"
    completed = run_installer("--prefix", str(prefix), "--no-modify-path", "--sha256", "deadbeef")
    assert completed.returncode == 1
    assert "SHA-256 mismatch" in completed.stderr
    assert not (prefix / "bin" / "uniservice").exists()


def test_from_requires_the_package(tmp_path: Path) -> None:
    completed = run_installer("--prefix", str(tmp_path / "pfx"), "--from", str(tmp_path))
    assert completed.returncode == 1
    assert "does not contain uniservice_lib" in completed.stderr


def test_default_user_prefix_and_profile_update(tmp_path: Path) -> None:
    home = tmp_path / "userhome"
    home.mkdir(exist_ok=True)
    bashrc = home / ".bashrc"
    bashrc.write_text("# existing content\n", encoding="utf-8")
    environment = {"HOME": str(home), "SHELL": "/bin/bash"}

    completed = run_installer("--user", env=environment)
    assert completed.returncode == 0, completed.stderr

    binary = home / ".local" / "bin" / "uniservice"
    assert binary.is_file()

    contents = bashrc.read_text(encoding="utf-8")
    assert contents.count('export PATH="$HOME/.local/bin:$PATH"') == 1

    manifest = json.loads((home / ".local" / "lib" / "uniservice" / "install.json").read_text(encoding="utf-8"))
    assert manifest["profile_files"] == [str(bashrc)]

    # Re-installing must not append the line a second time.
    again = run_installer("--user", env=environment)
    assert again.returncode == 0, again.stderr
    assert bashrc.read_text(encoding="utf-8").count('export PATH="$HOME/.local/bin:$PATH"') == 1


def test_no_modify_path_leaves_the_shell_files_alone(tmp_path: Path) -> None:
    home = tmp_path / "userhome"
    home.mkdir(exist_ok=True)
    bashrc = home / ".bashrc"
    bashrc.write_text("# existing content\n", encoding="utf-8")
    environment = {"HOME": str(home), "SHELL": "/bin/bash"}

    completed = run_installer("--user", "--no-modify-path", env=environment)
    assert completed.returncode == 0, completed.stderr
    assert bashrc.read_text(encoding="utf-8") == "# existing content\n"
    assert "add this to your shell startup file" in completed.stdout


def test_zsh_users_get_a_zshrc_hint(tmp_path: Path) -> None:
    home = tmp_path / "userhome"
    home.mkdir(exist_ok=True)
    zshrc = home / ".zshrc"
    zshrc.write_text("", encoding="utf-8")

    completed = run_installer("--user", env={"HOME": str(home), "SHELL": "/bin/zsh"})
    assert completed.returncode == 0, completed.stderr
    assert 'export PATH="$HOME/.local/bin:$PATH"' in zshrc.read_text(encoding="utf-8")


def test_compatibility_shims_forward_to_install_sh() -> None:
    for shim in ("install-linux.sh", "install-macos.sh"):
        completed = subprocess.run(
            ["bash", str(REPO_ROOT / shim), "--help"],
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
        assert completed.returncode == 0, completed.stderr
        assert "Usage: install.sh" in completed.stdout
