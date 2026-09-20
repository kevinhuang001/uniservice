"""Execution scope of a command.

The scope decides *where* a service definition lives and *which* system
instance supervises it:

``user``
    Owned by the invoking user (``systemctl --user``, ``~/Library/LaunchAgents``).
``system``
    Owned by the machine (``systemctl``, ``/Library/LaunchDaemons``, a SYSTEM
    Scheduled Task).

On Windows the scope is always ``system`` because Scheduled Tasks created by
uniservice run as ``SYSTEM``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from .platform_utils import is_root_unix

__all__ = ["SYSTEM", "USER", "Scope"]

USER = "user"
SYSTEM = "system"
VALID_SCOPES = frozenset({USER, SYSTEM})


@dataclass(frozen=True)
class Scope:
    """A validated service scope."""

    value: str

    def __post_init__(self) -> None:
        if self.value not in VALID_SCOPES:
            raise ValueError(f"Invalid scope: {self.value!r}")

    @property
    def is_system(self) -> bool:
        """Whether this is the machine-wide scope."""
        return self.value == SYSTEM

    @property
    def is_user(self) -> bool:
        """Whether this is the per-user scope."""
        return self.value == USER

    @classmethod
    def from_env(cls) -> Scope:
        """Derive the scope from the current process privileges."""
        if os.name == "nt" or is_root_unix():
            return cls(SYSTEM)
        return cls(USER)
