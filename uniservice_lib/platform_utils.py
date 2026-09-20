"""Platform detection and privilege helpers."""

from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path

try:  # pragma: no cover - unavailable on Windows
    import pwd
except ImportError:  # pragma: no cover - Windows
    pwd = None  # type: ignore[assignment]

__all__ = [
    "is_admin_windows",
    "is_root_unix",
    "platform",
    "sudo_target_uid",
    "user_home_for_uid",
    "win_cmdline_split",
]

LINUX = "linux"
MACOS = "mac"
WINDOWS = "win"
UNSUPPORTED = "unsupported"


def platform() -> str:
    """Return one of ``linux``, ``mac``, ``win`` or ``unsupported``."""
    if sys.platform.startswith("linux"):
        return LINUX
    if sys.platform == "darwin":
        return MACOS
    if os.name == "nt":
        return WINDOWS
    return UNSUPPORTED


def is_admin_windows() -> bool:
    """Return ``True`` when the current Windows process is elevated."""
    if os.name != "nt":
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def is_root_unix() -> bool:
    """Return ``True`` when the current POSIX process runs as root."""
    return hasattr(os, "geteuid") and os.geteuid() == 0


def sudo_target_uid() -> int | None:
    """Return ``SUDO_UID`` when running under ``sudo``, otherwise ``None``."""
    if os.name == "nt":
        return None
    raw = os.environ.get("SUDO_UID")
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def user_home_for_uid(uid: int) -> Path:
    """Return the home directory of *uid* on POSIX systems."""
    if os.name == "nt":
        raise RuntimeError("user_home_for_uid is not available on Windows.")
    if pwd is None:  # pragma: no cover - defensive
        raise RuntimeError("The pwd module is not available.")
    return Path(pwd.getpwuid(uid).pw_dir)


def win_cmdline_split(cmdline: str) -> list[str]:
    """Split a Windows command line the same way ``CreateProcess`` does."""
    if os.name != "nt":
        raise RuntimeError("win_cmdline_split is only available on Windows.")

    argc = ctypes.c_int()
    function = ctypes.windll.shell32.CommandLineToArgvW
    function.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_int)]
    function.restype = ctypes.POINTER(ctypes.c_wchar_p)
    argv = function(cmdline, ctypes.byref(argc))
    if not argv:
        raise RuntimeError("CommandLineToArgvW failed.")
    try:
        return [argv[index] for index in range(argc.value)]
    finally:
        free = ctypes.windll.kernel32.LocalFree
        free.argtypes = [ctypes.c_void_p]
        free.restype = ctypes.c_void_p
        free(argv)
