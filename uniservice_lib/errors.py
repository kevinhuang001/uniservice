"""Exception hierarchy for uniservice.

Every failure that is expected during normal operation is raised as a subclass
of :class:`UniserviceError`.  The command line layer turns those into a single
``FAIL: <message>`` line on stderr and a non-zero exit status, which keeps the
backends free of ``print``/``sys.exit`` calls and makes them testable.
"""

from __future__ import annotations

__all__ = [
    "InvalidServiceNameError",
    "ServiceNotFoundError",
    "UniserviceError",
    "UnsupportedPlatformError",
]


class UniserviceError(Exception):
    """Base class for user-facing uniservice failures."""


class ServiceNotFoundError(UniserviceError):
    """Raised when no service definition exists for a given name."""

    def __init__(self, name: str) -> None:
        super().__init__(f'Service "{name}" not found.')
        self.name = name


class InvalidServiceNameError(UniserviceError):
    """Raised when a service name cannot be safely used in a definition path."""


class UnsupportedPlatformError(UniserviceError):
    """Raised when the host platform has no backend implementation."""
