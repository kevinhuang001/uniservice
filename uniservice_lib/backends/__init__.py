"""Backend implementations for the supported operating systems."""

from __future__ import annotations

import sys

from ..errors import UnsupportedPlatformError
from ..platform_utils import LINUX, MACOS, WINDOWS, platform
from ..scope import Scope
from .base import Backend, ServiceInfo, classify_state, first_token

__all__ = ["Backend", "ServiceInfo", "classify_state", "first_token", "get_backend"]


def get_backend(scope: Scope) -> Backend:
    """Instantiate the backend for the current platform."""
    name = platform()
    if name == LINUX:
        from .linux import LinuxBackend

        return LinuxBackend(scope)
    if name == MACOS:
        from .macos import MacOSBackend

        return MacOSBackend(scope)
    if name == WINDOWS:
        from .windows import WindowsBackend

        return WindowsBackend(scope)
    raise UnsupportedPlatformError(f"Unsupported platform: {sys.platform}")
