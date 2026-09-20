#!/usr/bin/env python3
"""Build the single-file ``uniservice`` zipapp.

The zipapp is the installation artifact for machines that only have a Python
interpreter: one self-contained executable file (~30 KB) that can be dropped
into any directory on ``PATH``.

Having a single file is what lets one installation serve both scopes: the same
``/usr/local/bin/uniservice`` is run by the user (per-user services) and through
``sudo`` (system-wide services), with no sibling package directory for root to
resolve and no way to end up with a "script without its library".
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
import tempfile
import zipapp
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_NAME = "uniservice_lib"
DEFAULT_INTERPRETER = "/usr/bin/env python3"
DEFAULT_OUTPUT = "uniservice"

#: The earliest timestamp a zip entry can store.  Stamping every staged file with
#: it makes the archive byte-for-byte reproducible, which is what allows
#: ``install.sh --sha256`` to be meaningful for locally built artifacts.
ZIP_EPOCH = 315532800  # 1980-01-01T00:00:00Z

#: Copied into the archive so that ``python uniservice`` executes the CLI.
#: The zipapp runs on whatever ``python3`` the invoking user's PATH resolves to,
#: so it checks the version itself and fails with a message that names the
#: interpreter instead of raising a bare SyntaxError from somewhere inside.
MAIN_MODULE = """\
import sys

if sys.version_info < (3, 10):
    sys.exit(
        f"uniservice requires Python 3.10+, but this is {sys.version.split()[0]} at {sys.executable}"
    )

from uniservice_lib.cli import entrypoint

entrypoint()
"""


def normalize_mtimes(root: Path) -> None:
    """Stamp every path under *root* (inclusive) with :data:`ZIP_EPOCH`."""
    for path in sorted(root.rglob("*"), reverse=True):
        os.utime(path, (ZIP_EPOCH, ZIP_EPOCH))
    os.utime(root, (ZIP_EPOCH, ZIP_EPOCH))


def build(
    output: Path,
    *,
    source: Path | None = None,
    interpreter: str = DEFAULT_INTERPRETER,
    compress: bool = True,
) -> Path:
    """Build the zipapp at *output* from *source* and return its path."""
    source = (source or REPO_ROOT).resolve()
    package = source / PACKAGE_NAME
    if not (package / "__init__.py").is_file():
        raise FileNotFoundError(f"{PACKAGE_NAME} not found in {source}")

    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        staging = Path(tmp) / "app"
        staging.mkdir()
        shutil.copytree(
            package,
            staging / PACKAGE_NAME,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
        )
        (staging / "__main__.py").write_text(MAIN_MODULE, encoding="utf-8")
        normalize_mtimes(staging)
        zipapp.create_archive(staging, target=output, interpreter=interpreter, compressed=compress)

    output.chmod(0o755)
    return output


def sha256_of(path: Path) -> str:
    """Return the hex SHA-256 digest of *path*."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    """Command line entry point."""
    parser = argparse.ArgumentParser(description="Build the uniservice zipapp.")
    parser.add_argument("-o", "--output", default=DEFAULT_OUTPUT, help=f"output path (default: {DEFAULT_OUTPUT})")
    parser.add_argument("--source", default=str(REPO_ROOT), help="repository root to build from")
    parser.add_argument("--interpreter", default=DEFAULT_INTERPRETER, help="shebang line for the archive")
    parser.add_argument("--no-compress", action="store_true", help="store files uncompressed")
    parser.add_argument("-q", "--quiet", action="store_true", help="only print the output path")
    args = parser.parse_args(argv)

    try:
        output = build(
            Path(args.output),
            source=Path(args.source),
            interpreter=args.interpreter,
            compress=not args.no_compress,
        )
    except (FileNotFoundError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.quiet:
        print(output)
    else:
        size = output.stat().st_size
        print(f"Built {output} ({size} bytes)")
        print(f"sha256 {sha256_of(output)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
