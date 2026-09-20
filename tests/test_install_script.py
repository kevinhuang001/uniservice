"""End-to-end tests for ``install.sh``.

Every test runs the real installer in a subprocess against a throwaway prefix, so
the install -> verify -> uninstall lifecycle, the manifest and the permission
checks are all exercised for real.  ``--from`` is not needed: the installer
notices that it is running from a checkout and builds the local sources.
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
DEFAULT_PREFIX = Path("/usr/local")

pytestmark = pytest.mark.skipif(os.name == "nt", reason="install.sh is POSIX-only")


def _is_root() -> bool:
    """True on POSIX when running as root.

    ``os.geteuid`` does not exist on Windows, and a ``skipif`` marker is
    evaluated while the module is imported, before the module-level skip above
    can take effect.
    """
    return hasattr(os, "geteuid") and os.geteuid() == 0


def run_installer(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
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


def test_help_documents_the_options() -> None:
    completed = run_installer("--help")
    assert completed.returncode == 0
    for flag in ("--prefix", "--version", "--sha256", "--from", "--uninstall"):
        assert flag in completed.stdout
    assert "/usr/local" in completed.stdout
    assert "sudo" in completed.stdout


def test_unknown_option_is_rejected() -> None:
    completed = run_installer("--definitely-not-an-option")
    assert completed.returncode == 1
    assert "unknown option" in completed.stderr


@pytest.mark.skipif(_is_root(), reason="root can write to /usr/local")
def test_default_prefix_is_usr_local_and_needs_permission() -> None:
    if os.access(DEFAULT_PREFIX, os.W_OK):
        pytest.skip(f"{DEFAULT_PREFIX} happens to be writable on this host")

    completed = run_installer()

    assert completed.returncode == 1
    assert "sudo" in completed.stderr
    assert not (DEFAULT_PREFIX / "bin" / "uniservice").exists()


@pytest.mark.skipif(_is_root(), reason="root ignores directory permissions")
def test_unwritable_prefix_fails_before_downloading(tmp_path: Path) -> None:
    prefix = tmp_path / "readonly"
    prefix.mkdir()
    prefix.chmod(0o500)
    try:
        completed = run_installer("--prefix", str(prefix))
    finally:
        prefix.chmod(0o700)

    assert completed.returncode == 1
    assert "sudo" in completed.stderr
    assert not (prefix / "bin").exists()


def test_install_then_uninstall_round_trip(tmp_path: Path) -> None:
    prefix = tmp_path / "pfx"

    installed = run_installer("--prefix", str(prefix))
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
    assert "profile_files" not in manifest

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
    assert run_installer("--prefix", str(prefix)).returncode == 0
    keeper = prefix / "keep.txt"
    keeper.write_text("not ours\n", encoding="utf-8")

    assert run_installer("--uninstall", "--prefix", str(prefix)).returncode == 0

    assert keeper.read_text(encoding="utf-8") == "not ours\n"
    assert not (prefix / "bin" / "uniservice").exists()
    assert not (prefix / "lib").exists()


def test_installer_never_touches_shell_startup_files(tmp_path: Path) -> None:
    """The installer targets /usr/local and must not edit any profile."""
    home = tmp_path / "userhome"
    home.mkdir(exist_ok=True)
    startup_files = {
        home / ".bashrc": "# bashrc\n",
        home / ".zshrc": "# zshrc\n",
        home / ".profile": "# profile\n",
    }
    for path, content in startup_files.items():
        path.write_text(content, encoding="utf-8")

    completed = run_installer("--prefix", str(tmp_path / "pfx"), env={"HOME": str(home)})

    assert completed.returncode == 0, completed.stderr
    for path, content in startup_files.items():
        assert path.read_text(encoding="utf-8") == content


def test_installed_artifact_is_a_single_self_contained_file(tmp_path: Path) -> None:
    """Copying just the executable to a bare directory must be enough."""
    prefix = tmp_path / "pfx"
    assert run_installer("--prefix", str(prefix)).returncode == 0

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
    completed = run_installer("--prefix", str(prefix), "--sha256", digest)
    assert completed.returncode == 0, completed.stderr
    assert "SHA-256 verified" in completed.stdout
    assert sha256_of(prefix / "bin" / "uniservice") == digest


def test_checksum_verification_rejects_a_wrong_digest(tmp_path: Path) -> None:
    prefix = tmp_path / "pfx"
    completed = run_installer("--prefix", str(prefix), "--sha256", "deadbeef")
    assert completed.returncode == 1
    assert "SHA-256 mismatch" in completed.stderr
    assert not (prefix / "bin" / "uniservice").exists()


def test_from_requires_the_package(tmp_path: Path) -> None:
    completed = run_installer("--prefix", str(tmp_path / "pfx"), "--from", str(tmp_path))
    assert completed.returncode == 1
    assert "does not contain uniservice_lib" in completed.stderr
