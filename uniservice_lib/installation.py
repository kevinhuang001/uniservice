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
from .logging_utils import logger

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

#: On Windows these are read line by line while they run, so removing them from
#: inside the command they started makes cmd.exe complain ("The batch file cannot
#: be found") for every remaining line.
WINDOWS_DEFERRED_SUFFIXES = frozenset({".cmd", ".bat"})


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


def remove_installation(
    installation: Installation, *, dry_run: bool = False, defer: bool = True
) -> tuple[list[Path], list[Path]]:
    """Remove everything the manifest records.

    Returns ``(removed, deferred)``.  *deferred* is non-empty only on Windows,
    where the running executable cannot be deleted by the process that is running
    it: those files are handed to a detached ``cmd.exe`` once this process exits,
    and registered for deletion at the next boot as a backstop.  Pass
    ``defer=False`` to report them instead of scheduling anything.
    """
    prefix = installation.prefix.resolve()
    removed: list[Path] = []
    deferred: list[Path] = []
    # Only the image this process is actually running from has to be deferred;
    # comparing against the *recorded* path would defer any file at all.
    running = {_normcase(path) for path in running_commands()}

    for target in installation.recorded_files:
        resolved = _inside_prefix(target, prefix)
        if resolved is None:
            continue
        if not resolved.exists():
            continue
        if dry_run:
            removed.append(resolved)
            continue
        if os.name == "nt" and (_normcase(resolved) in running or resolved.suffix.lower() in WINDOWS_DEFERRED_SUFFIXES):
            deferred.append(resolved)
            continue
        _unlink(resolved)
        removed.append(resolved)

    if not dry_run:
        installation.manifest.unlink(missing_ok=True)
        _prune_empty_directories(prefix)
        for path in deferred:
            if defer:
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
    if _normcase(resolved) != _normcase(prefix) and _normcase(prefix) not in {
        _normcase(parent) for parent in resolved.parents
    }:
        return None
    return resolved


def _normcase(path: Path) -> str:
    """Comparable form of *path*; Windows paths are case-insensitive."""
    return os.path.normcase(str(path))


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
    """Finish removing *path* after this process exits.

    Windows maps a running image without ``FILE_SHARE_DELETE``, so ``DeleteFile``
    on our own executable cannot succeed while we are running, and there is no
    portable "delete yourself" call.  Two mechanisms are used together:

    1. a detached ``cmd.exe`` that waits for this process to exit, deletes the
       file and prunes the directories that only become empty afterwards - this
       is what removes it "now";
    2. ``MoveFileEx(..., MOVEFILE_DELAY_UNTIL_REBOOT)``, which Windows guarantees
       even if the helper is blocked, so the file cannot survive a reboot.
    """
    if os.name != "nt":  # pragma: no cover - guarded by the caller
        return

    _register_reboot_delete(path)

    # Deepest first; rmdir fails harmlessly on a directory that still has files.
    prune = " & ".join(
        f'rmdir "{directory}" 2>nul'
        for directory in (path.parent, prefix / "lib" / LIB_DIR_NAME, prefix / "lib", prefix)
    )
    try:
        subprocess.Popen(  # a fixed cmd.exe invocation, no shell involved
            f'cmd.exe /c ping -n 3 127.0.0.1 >nul & del /f /q "{path}" & {prune}',
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            # CREATE_NO_WINDOW rather than DETACHED_PROCESS: cmd.exe with no
            # console at all can fail its own redirections.
            creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP,
            close_fds=True,
        )
    except OSError as exc:
        # The reboot registration above still gets rid of it; say so rather than
        # pretending the command is gone.
        raise UniserviceError(f"{path} will be removed the next time Windows restarts ({exc})") from None


def _register_reboot_delete(path: Path) -> None:
    """Ask Windows to delete *path* during the next boot, best effort."""
    if os.name != "nt":  # pragma: no cover - guarded by the caller
        return
    try:
        import ctypes

        movefile_delay_until_reboot = 0x4
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.MoveFileExW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint]
        kernel32.MoveFileExW.restype = ctypes.c_int
        if not kernel32.MoveFileExW(str(path), None, movefile_delay_until_reboot):
            # Needs elevation for the machine-wide pending-rename list; a per-user
            # install can still be handled by the helper process.
            logger.debug("MoveFileEx DELAY_UNTIL_REBOOT failed for %s (error %s)", path, ctypes.get_last_error())
    except Exception as exc:  # pragma: no cover - depends on the host
        logger.debug("could not register a reboot delete for %s: %s", path, exc)
