from __future__ import annotations

import ctypes
import logging
import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

try:
    import pwd
except Exception:
    pwd = None


def eprint(*args: object) -> None:
    print(*args, file=sys.stderr)

logger = logging.getLogger("uniservice")


def log_path() -> Path:
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData/Local")
        return Path(base) / "uniservice" / "logs" / "uniservice.log"
    return Path.home() / ".uniservice" / "logs" / "uniservice.log"


def setup_logging() -> None:
    logger.setLevel(logging.DEBUG)
    if logger.handlers:
        return

    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

    console = logging.StreamHandler(stream=sys.stderr)
    console.setLevel(logging.WARNING)
    console.setFormatter(fmt)
    logger.addHandler(console)

    path = log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(path, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)


def run(
    cmd: list[str],
    *,
    check: bool = True,
    quiet: bool = False,
    capture: bool = False,
) -> subprocess.CompletedProcess[str]:
    kwargs: dict[str, object] = {}
    if capture:
        kwargs["capture_output"] = True
    elif quiet:
        kwargs["stdout"] = subprocess.DEVNULL
        kwargs["stderr"] = subprocess.DEVNULL
    logger.debug("run: %s", " ".join(cmd))
    cp = subprocess.run(cmd, check=check, text=True, **kwargs)
    if capture:
        if cp.stdout:
            logger.debug("stdout: %s", cp.stdout.rstrip("\n"))
        if cp.stderr:
            logger.debug("stderr: %s", cp.stderr.rstrip("\n"))
    return cp


def platform() -> str:
    if sys.platform.startswith("linux"):
        return "linux"
    if sys.platform == "darwin":
        return "mac"
    if os.name == "nt":
        return "win"
    return "unsupported"


def is_admin_windows() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def is_root_unix() -> bool:
    return hasattr(os, "geteuid") and os.geteuid() == 0


def sudo_target_uid() -> int | None:
    if os.name == "nt":
        return None
    v = os.environ.get("SUDO_UID")
    if not v:
        return None
    try:
        return int(v)
    except ValueError:
        return None


def user_home_for_uid(uid: int) -> Path:
    if os.name == "nt":
        raise RuntimeError("user_home_for_uid is not available on Windows.")
    if pwd is None:
        raise RuntimeError("pwd module is not available.")
    return Path(pwd.getpwuid(uid).pw_dir)


def command_string(command_parts: list[str]) -> str:
    return " ".join(shlex.quote(p) for p in command_parts)


def resolve_command_parts(command_parts: list[str]) -> list[str]:
    if not command_parts:
        return command_parts

    exe = command_parts[0]
    if os.path.isabs(exe):
        return command_parts

    resolved = shutil.which(exe)
    if resolved:
        logger.warning('Command "%s" is not an absolute path; resolved to "%s"', exe, resolved)
        return [resolved, *command_parts[1:]]

    logger.warning('Command "%s" is not an absolute path and was not found in PATH', exe)
    return command_parts

@dataclass(frozen=True)
class Scope:
    value: str

    @staticmethod
    def from_args(args: object) -> "Scope":
        if getattr(args, "system", False):
            return Scope("system")
        if getattr(args, "user", False):
            return Scope("user")
        if os.name != "nt" and is_root_unix():
            return Scope("system")
        return Scope("user")


def win_cmdline_split(cmdline: str) -> list[str]:
    if os.name != "nt":
        raise RuntimeError("win_cmdline_split is only available on Windows.")

    argc = ctypes.c_int()
    fn = ctypes.windll.shell32.CommandLineToArgvW
    fn.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_int)]
    fn.restype = ctypes.POINTER(ctypes.c_wchar_p)
    argv = fn(cmdline, ctypes.byref(argc))
    if not argv:
        raise RuntimeError("CommandLineToArgvW failed.")
    try:
        return [argv[i] for i in range(argc.value)]
    finally:
        free = ctypes.windll.kernel32.LocalFree
        free.argtypes = [ctypes.c_void_p]
        free.restype = ctypes.c_void_p
        free(argv)
