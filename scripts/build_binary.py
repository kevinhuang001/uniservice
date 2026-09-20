#!/usr/bin/env python3
"""Build the standalone ``uniservice`` binary with PyInstaller.

PyInstaller embeds a CPython interpreter and the standard library into one
executable, so the target machine does not need Python installed at all - and
because the interpreter is fixed at build time, ``uniservice`` always runs on
exactly the interpreter that was verified when it was packaged.

The cost is that PyInstaller **cannot cross-compile**: the artifact only runs on
the operating system and CPU architecture it was built on.  The release workflow
therefore builds one asset per platform, and the asset name encodes both, so the
installer can select the right one from ``uname -s`` / ``uname -m``.
"""

from __future__ import annotations

import argparse
import hashlib
import platform
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ENTRY_POINT = REPO_ROOT / "packaging" / "entrypoint.py"
PROGRAM_NAME = "uniservice"

#: ``sys.platform`` -> the ``uname -s`` spelling the installer produces.
OS_NAMES = {"linux": "linux", "darwin": "macos", "win32": "windows"}

#: ``platform.machine()`` -> the ``uname -m`` spelling the installer produces.
#: macOS reports ``arm64`` while Linux reports ``aarch64``; they are kept apart
#: because the installer compares them literally.
ARCH_NAMES = {"amd64": "x86_64", "x86_64": "x86_64", "aarch64": "aarch64", "arm64": "arm64"}

#: Modules nothing in uniservice imports, kept out of the archive.
EXCLUDED_MODULES = ("tkinter", "unittest", "pydoc", "doctest", "lib2to3", "test")

#: ``plistlib`` imports this at module level; naming it explicitly means a future
#: refactor cannot silently break reading launchd plists on macOS.
HIDDEN_IMPORTS = ("xml.parsers.expat",)


def asset_name(os_name: str | None = None, machine: str | None = None) -> str:
    """Return the release asset name, e.g. ``uniservice-linux-x86_64``."""
    resolved_os = os_name or OS_NAMES.get(sys.platform, sys.platform)
    resolved_machine = (machine or platform.machine()).lower()
    resolved_arch = ARCH_NAMES.get(resolved_machine, resolved_machine)
    suffix = ".exe" if resolved_os == "windows" else ""
    return f"{PROGRAM_NAME}-{resolved_os}-{resolved_arch}{suffix}"


def sha256_of(path: Path) -> str:
    """Return the hex SHA-256 digest of *path*."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build(output_dir: Path, *, name: str | None = None, strip: bool = False) -> Path:
    """Build the binary into *output_dir* and return its path."""
    output_dir = output_dir.resolve()
    work_dir = output_dir / "_work"
    spec_dir = output_dir / "_spec"
    for directory in (output_dir, work_dir, spec_dir):
        directory.mkdir(parents=True, exist_ok=True)

    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--onefile",
        "--console",
        "--noconfirm",
        "--clean",
        "--noupx",
        "--name",
        PROGRAM_NAME,
        "--paths",
        str(REPO_ROOT),
        "--distpath",
        str(output_dir),
        "--workpath",
        str(work_dir),
        "--specpath",
        str(spec_dir),
        str(ENTRY_POINT),
    ]
    for module in EXCLUDED_MODULES:
        command += ["--exclude-module", module]
    for module in HIDDEN_IMPORTS:
        command += ["--hidden-import", module]
    if strip:
        command.append("--strip")

    subprocess.run(command, check=True)

    produced_name = f"{PROGRAM_NAME}.exe" if sys.platform == "win32" else PROGRAM_NAME
    produced = output_dir / produced_name
    if not produced.is_file():
        raise FileNotFoundError(f"PyInstaller did not produce {produced}")

    target = output_dir / (name or asset_name())
    produced.replace(target)
    target.chmod(0o755)
    return target


def main(argv: list[str] | None = None) -> int:
    """Command line entry point."""
    parser = argparse.ArgumentParser(description="Build the standalone uniservice binary.")
    parser.add_argument("-o", "--output-dir", default="dist", help="directory for the artifact")
    parser.add_argument("--name", default=None, help="artifact name (default: the platform asset name)")
    parser.add_argument("--strip", action="store_true", help="strip symbols (Linux only)")
    parser.add_argument("--print-asset-name", action="store_true", help="print the asset name and exit")
    parser.add_argument("-q", "--quiet", action="store_true", help="only print the output path")
    args = parser.parse_args(argv)

    if args.print_asset_name:
        print(asset_name())
        return 0

    try:
        target = build(Path(args.output_dir), name=args.name, strip=args.strip)
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.quiet:
        print(target)
    else:
        print(f"Built {target} ({target.stat().st_size} bytes)")
        print(f"sha256 {sha256_of(target)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
