"""Locate an installation of uniservice and read the manifest its installer wrote.

The installers write a small ``key=value`` manifest next to the command they
install:

    <prefix>/bin/uniservice          the command
    <prefix>/lib/uniservice/manifest what was installed

The manifest is *read* here, never written or acted on: ``uniservice doctor``
and ``uniservice version`` report where this copy lives and how it was
installed, and removing it is the install scripts' job
(``install.sh --uninstall``, ``install-windows.ps1 -Uninstall``).  Those run as a
different process from the command they delete, which is the only way to remove
a running image on Windows without a deferred-delete helper.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "MANIFEST_NAME",
    "Installation",
    "find_installation",
    "manifest_path_for",
    "read_manifest",
    "running_commands",
]

MANIFEST_NAME = "manifest"
LIB_DIR_NAME = "uniservice"


@dataclass(frozen=True)
class Installation:
    """A manifest-recorded installation of the command itself."""

    prefix: Path
    command: Path
    manifest: Path
    fields: dict[str, str]

    @property
    def version(self) -> str:
        return self.fields.get("version") or "unknown"

    @property
    def kind(self) -> str:
        return self.fields.get("kind") or "unknown"


def manifest_path_for(command: Path) -> Path:
    """Return where the manifest for *command* would live."""
    return command.parent.parent / "lib" / LIB_DIR_NAME / MANIFEST_NAME


def read_manifest(path: Path) -> dict[str, str]:
    """Parse a ``key=value`` manifest.  The file is never sourced or imported."""
    fields: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        key, separator, value = line.partition("=")
        if separator and key.strip():
            fields[key.strip()] = value.strip()
    return fields


def running_commands() -> list[Path]:
    """Paths that could be the command currently executing, most likely first.

    A frozen binary reports itself through ``sys.executable``; a zipapp is the
    script named in ``sys.argv[0]`` and its interpreter is irrelevant.
    """
    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable))
    if sys.argv and sys.argv[0]:
        candidates.append(Path(sys.argv[0]))

    resolved: list[Path] = []
    for candidate in candidates:
        try:
            path = Path(candidate).resolve()
        except OSError:  # pragma: no cover - defensive
            continue
        if path not in resolved:
            resolved.append(path)
    return resolved


def find_installation(command: Path | None = None) -> Installation | None:
    """Return the installation this command belongs to, or ``None``."""
    commands = [command] if command is not None else running_commands()
    for candidate in commands:
        manifest = manifest_path_for(candidate)
        if manifest.is_file():
            return Installation(
                prefix=candidate.parent.parent,
                command=candidate,
                manifest=manifest,
                fields=read_manifest(manifest),
            )
    return None
