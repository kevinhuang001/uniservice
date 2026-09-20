"""Locate and remove an installation of uniservice itself.

The installers write a small ``key=value`` manifest next to the command they
install:

    <prefix>/bin/uniservice          the command
    <prefix>/lib/uniservice/manifest what was installed

``uniservice uninstall`` reads it back and removes exactly those files, which is
the same contract ``install.sh --uninstall`` implements for the case where the
command itself is broken or already gone.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .errors import UniserviceError

__all__ = [
    "MANIFEST_NAME",
    "Installation",
    "find_installation",
    "manifest_path_for",
    "read_manifest",
    "remove_installation",
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

    @property
    def recorded_files(self) -> list[Path]:
        """The files the installer created, in removal order."""
        files = []
        for key in ("shim", "binary"):
            value = (self.fields.get(key) or "").strip()
            if value:
                files.append(Path(value))
        return files


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


def remove_installation(installation: Installation, *, dry_run: bool = False) -> tuple[list[Path], list[Path]]:
    """Remove everything the manifest records.

    Returns ``(removed, deferred)``.  *deferred* is non-empty only on Windows,
    where the running executable cannot be deleted by the process that is running
    it: those files are deleted by a detached ``cmd.exe`` once this process exits.
    """
    prefix = installation.prefix.resolve()
    removed: list[Path] = []
    deferred: list[Path] = []
    running = installation.command.resolve()

    for target in installation.recorded_files:
        resolved = _inside_prefix(target, prefix)
        if resolved is None:
            continue
        if not resolved.exists():
            continue
        if dry_run:
            removed.append(resolved)
            continue
        if os.name == "nt" and resolved == running:
            deferred.append(resolved)
            continue
        _unlink(resolved)
        removed.append(resolved)

    if not dry_run:
        installation.manifest.unlink(missing_ok=True)
        _prune_empty_directories(prefix)
        for path in deferred:
            _schedule_windows_delete(path, prefix)

    return removed, deferred


def _inside_prefix(target: Path, prefix: Path) -> Path | None:
    """Resolve *target*, or return ``None`` when it is not inside *prefix*.

    The manifest lives in a root-owned directory, but a tampered or hand-edited
    one must still not be able to point the removal at anything else.
    """
    try:
        resolved = target.resolve()
    except OSError:  # pragma: no cover - defensive
        return None
    if resolved != prefix and prefix not in resolved.parents:
        return None
    return resolved


def _unlink(path: Path) -> None:
    try:
        path.unlink()
    except PermissionError as exc:
        raise UniserviceError(f"cannot remove {path} ({exc.strerror}); run 'sudo {path.name} uninstall'") from None
    except OSError as exc:
        raise UniserviceError(f"cannot remove {path}: {exc}") from None


def _prune_empty_directories(root: Path) -> None:
    """Remove directories that are empty now, deepest first, inside *root* only."""
    if not root.is_dir():
        return
    directories = sorted((item for item in root.rglob("*") if item.is_dir()), key=lambda item: len(item.parts))
    for directory in reversed(directories):
        with contextlib.suppress(OSError):
            directory.rmdir()
    with contextlib.suppress(OSError):
        root.rmdir()


def _schedule_windows_delete(path: Path, prefix: Path) -> None:
    """Ask a detached ``cmd.exe`` to finish removing *path* once this process exits.

    Windows refuses to delete a running image, and there is no portable "delete
    yourself" call, so the deletion - and the pruning of the directories that
    only become empty afterwards - is handed to a short-lived helper.
    """
    if os.name != "nt":  # pragma: no cover - guarded by the caller
        return
    # Deepest first; rmdir fails harmlessly on a directory that still has files.
    prune = " & ".join(
        f'rmdir "{directory}" 2>nul'
        for directory in (path.parent, prefix / "lib" / LIB_DIR_NAME, prefix / "lib", prefix)
    )
    try:
        subprocess.Popen(  # a fixed cmd.exe invocation, no shell involved
            f'cmd.exe /c ping -n 3 127.0.0.1 >nul & del /f /q "{path}" & {prune}',
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
            close_fds=True,
        )
    except OSError as exc:  # pragma: no cover - depends on the host
        raise UniserviceError(f"could not schedule the removal of {path}: {exc}") from None
