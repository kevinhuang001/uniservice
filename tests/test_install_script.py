"""End-to-end tests for ``install.sh``.

Every test runs the real installer in a subprocess against a throwaway prefix, so
the install -> verify -> uninstall lifecycle, the manifest, the artifact choice,
the platform checks and the permission checks are all exercised for real.

The download path is tested against a ``file://`` tree laid out like a GitHub
release; the zipapp asset is a real zipapp built by ``scripts/build_zipapp.py``
and the binary asset is a stub carrying this platform's executable magic.  The
real standalone binaries are smoke tested by the ``binaries`` job in CI.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.build_binary import asset_name
from scripts.build_zipapp import build as build_zipapp
from tests.conftest import REPO_ROOT
from uniservice_lib import __version__

INSTALLER = REPO_ROOT / "install.sh"
DEFAULT_PREFIX = Path("/usr/local")
ZIPAPP_ASSET = "uniservice"

pytestmark = pytest.mark.skipif(os.name == "nt", reason="install.sh is POSIX-only")

#: First bytes of the executable formats ``check_artifact_format`` recognises.
MAGIC = {"linux": b"\x7fELF", "darwin": b"\xcf\xfa\xed\xfe"}


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


def make_script_stub(path: Path, *, version: str = "0.0.0") -> Path:
    """An executable that answers ``--version`` like the real zipapp."""
    path.write_text(f"#!/bin/sh\necho 'uniservice {version}'\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def make_binary_stub(path: Path) -> Path:
    """An executable carrying this platform's magic bytes (not runnable)."""
    magic = MAGIC.get(sys.platform, MAGIC["linux"])
    path.write_bytes(magic + b"\nstub payload\n")
    path.chmod(0o755)
    return path


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def manifest_of(prefix: Path) -> dict[str, str]:
    """Parse the key=value manifest into a dict."""
    text = (prefix / "lib" / "uniservice" / "manifest").read_text(encoding="utf-8")
    return dict(line.split("=", 1) for line in text.splitlines() if "=" in line)


def build_release_tree(tmp_path: Path, *, tag: str, asset: str = ZIPAPP_ASSET, digest: str | None = None) -> Path:
    """Lay out ``<base>/releases/download/<tag>/<asset>`` plus SHA256SUMS."""
    release = tmp_path / "repo" / "releases" / "download" / tag
    release.mkdir(parents=True)
    if asset == ZIPAPP_ASSET:
        build_zipapp(release / asset)  # a real, runnable zipapp
    else:
        make_binary_stub(release / asset)  # magic bytes only; not runnable
    actual = digest or sha256_of(release / asset)
    (release / "SHA256SUMS").write_text(f"{actual}  {asset}\n", encoding="utf-8")
    return tmp_path / "repo"


# ---------------------------------------------------------------------------
# basics
# ---------------------------------------------------------------------------


def test_help_offers_both_artifacts() -> None:
    completed = run_installer("--help")
    assert completed.returncode == 0
    for flag in ("--binary", "--prefix", "--version", "--sha256", "--from", "--uninstall"):
        assert flag in completed.stdout
    assert "zipapp" in completed.stdout
    assert "recommended" in completed.stdout
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


# ---------------------------------------------------------------------------
# install / uninstall lifecycle
# ---------------------------------------------------------------------------


def test_install_then_uninstall_round_trip(tmp_path: Path) -> None:
    prefix = tmp_path / "pfx"
    stub = make_script_stub(tmp_path / "stub", version="9.9.9")

    installed = run_installer("--prefix", str(prefix), "--from", str(stub))
    assert installed.returncode == 0, installed.stderr

    binary = prefix / "bin" / "uniservice"
    assert binary.is_file()
    assert os.access(binary, os.X_OK)

    manifest = manifest_of(prefix)
    assert manifest["schema"] == "1"
    assert manifest["program"] == "uniservice"
    assert manifest["kind"] == "zipapp"
    assert manifest["version"] == "9.9.9"  # read back from the installed file
    assert manifest["asset"] == "stub"
    assert manifest["prefix"] == str(prefix)
    assert manifest["binary"] == str(binary)
    assert manifest["sha256"] == sha256_of(stub)

    removed = run_installer("--uninstall", "--prefix", str(prefix))
    assert removed.returncode == 0, removed.stderr
    assert not binary.exists()
    # Only empty directories are pruned, so a throwaway prefix disappears
    # entirely while a prefix holding anything else is left alone.
    assert not prefix.exists()


def test_from_detects_a_standalone_binary(tmp_path: Path) -> None:
    prefix = tmp_path / "pfx"
    stub = make_binary_stub(tmp_path / "uniservice-linux-x86_64")

    completed = run_installer("--prefix", str(prefix), "--from", str(stub))

    assert completed.returncode == 0, completed.stderr
    assert manifest_of(prefix)["kind"] == "binary"


def test_uninstall_leaves_a_prefix_that_holds_other_files(tmp_path: Path) -> None:
    prefix = tmp_path / "pfx"
    stub = make_script_stub(tmp_path / "stub")
    assert run_installer("--prefix", str(prefix), "--from", str(stub)).returncode == 0
    keeper = prefix / "keep.txt"
    keeper.write_text("not ours\n", encoding="utf-8")

    assert run_installer("--uninstall", "--prefix", str(prefix)).returncode == 0

    assert keeper.read_text(encoding="utf-8") == "not ours\n"
    assert not (prefix / "bin" / "uniservice").exists()
    assert not (prefix / "lib").exists()


def test_uninstall_without_a_manifest_fails(tmp_path: Path) -> None:
    completed = run_installer("--uninstall", "--prefix", str(tmp_path / "pfx"))
    assert completed.returncode == 1
    assert "no installation recorded" in completed.stderr


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
    stub = make_script_stub(tmp_path / "stub")

    completed = run_installer("--prefix", str(tmp_path / "pfx"), "--from", str(stub), env={"HOME": str(home)})

    assert completed.returncode == 0, completed.stderr
    for path, content in startup_files.items():
        assert path.read_text(encoding="utf-8") == content


# ---------------------------------------------------------------------------
# checksums
# ---------------------------------------------------------------------------


def test_checksum_verification_accepts_the_right_digest(tmp_path: Path) -> None:
    prefix = tmp_path / "pfx"
    stub = make_script_stub(tmp_path / "stub")

    completed = run_installer("--prefix", str(prefix), "--from", str(stub), "--sha256", sha256_of(stub))

    assert completed.returncode == 0, completed.stderr
    assert "SHA-256 verified" in completed.stdout


def test_checksum_verification_rejects_a_wrong_digest(tmp_path: Path) -> None:
    prefix = tmp_path / "pfx"
    stub = make_script_stub(tmp_path / "stub")

    completed = run_installer("--prefix", str(prefix), "--from", str(stub), "--sha256", "deadbeef")

    assert completed.returncode == 1
    assert "SHA-256 mismatch" in completed.stderr
    assert not (prefix / "bin" / "uniservice").exists()


def test_from_requires_an_existing_file(tmp_path: Path) -> None:
    completed = run_installer("--prefix", str(tmp_path / "pfx"), "--from", str(tmp_path / "nope"))
    assert completed.returncode == 1
    assert "does not exist" in completed.stderr


# ---------------------------------------------------------------------------
# the download path, served offline over file://
# ---------------------------------------------------------------------------


def test_installs_the_zipapp_by_default(tmp_path: Path) -> None:
    base = build_release_tree(tmp_path, tag="v9.9.9")
    prefix = tmp_path / "pfx"

    completed = run_installer(
        "--prefix",
        str(prefix),
        "--version",
        "v9.9.9",
        env={"UNISERVICE_REPO_URL": f"file://{base}"},
    )

    assert completed.returncode == 0, completed.stderr
    assert f"Downloading file://{base}/releases/download/v9.9.9/{ZIPAPP_ASSET}" in completed.stdout
    assert "SHA-256 verified" in completed.stdout  # the digest came from SHA256SUMS
    assert manifest_of(prefix)["kind"] == "zipapp"
    assert manifest_of(prefix)["version"] == __version__  # read from the real zipapp

    # The installed artifact really is the recommended portable zipapp.
    installed = subprocess.run(
        [sys.executable, str(prefix / "bin" / "uniservice"), "--version"],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert installed.returncode == 0
    assert installed.stdout.strip() == f"uniservice {__version__}"


def test_binary_flag_selects_the_platform_binary(tmp_path: Path) -> None:
    base = build_release_tree(tmp_path, tag="v9.9.9", asset=asset_name())
    prefix = tmp_path / "pfx"

    completed = run_installer(
        "--prefix",
        str(prefix),
        "--version",
        "v9.9.9",
        "--binary",
        env={"UNISERVICE_REPO_URL": f"file://{base}"},
    )

    assert completed.returncode == 0, completed.stderr
    assert f"/{asset_name()}" in completed.stdout
    assert manifest_of(prefix)["kind"] == "binary"
    assert manifest_of(prefix)["asset"] == asset_name()
    assert manifest_of(prefix)["version"] == "v9.9.9"


def test_binary_flag_explains_itself_when_the_platform_is_missing(tmp_path: Path) -> None:
    base = build_release_tree(tmp_path, tag="v9.9.9")  # only the zipapp is published

    completed = run_installer(
        "--prefix",
        str(tmp_path / "pfx"),
        "--version",
        "v9.9.9",
        "--binary",
        env={"UNISERVICE_REPO_URL": f"file://{base}"},
    )

    assert completed.returncode == 1
    assert "could not download" in completed.stderr
    assert "--binary" in completed.stderr  # points at the zipapp alternative


def test_zipapp_download_without_a_shebang_is_rejected(tmp_path: Path) -> None:
    """An error page saved as the asset must never be installed."""
    base = build_release_tree(tmp_path, tag="v9.9.9")
    release = base / "releases" / "download" / "v9.9.9"
    (release / ZIPAPP_ASSET).write_text("<html>404 Not Found</html>\n", encoding="utf-8")
    (release / "SHA256SUMS").write_text(f"{sha256_of(release / ZIPAPP_ASSET)}  {ZIPAPP_ASSET}\n", encoding="utf-8")

    completed = run_installer(
        "--prefix",
        str(tmp_path / "pfx"),
        "--version",
        "v9.9.9",
        env={"UNISERVICE_REPO_URL": f"file://{base}"},
    )

    assert completed.returncode == 1
    assert "not a zipapp" in completed.stderr


def test_a_tampered_asset_is_rejected(tmp_path: Path) -> None:
    base = build_release_tree(tmp_path, tag="v9.9.9", digest="0" * 64)

    completed = run_installer(
        "--prefix",
        str(tmp_path / "pfx"),
        "--version",
        "v9.9.9",
        env={"UNISERVICE_REPO_URL": f"file://{base}"},
    )

    assert completed.returncode == 1
    assert "SHA-256 mismatch" in completed.stderr
    assert not (tmp_path / "pfx" / "bin" / "uniservice").exists()
