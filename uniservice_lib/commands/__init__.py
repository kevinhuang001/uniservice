"""Command implementations.

Each command is a function ``(Context, argparse.Namespace) -> int`` that
returns a process exit code, renders everything through
:class:`~uniservice_lib.console.Console` and raises
:class:`~uniservice_lib.errors.UniserviceError` for failures.  Nothing here
calls ``sys.exit``, which keeps every command callable from a test.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..backends import Backend, get_backend
from ..console import Console
from ..errors import UniserviceError
from ..platform_utils import WINDOWS, is_admin_windows, is_root_unix, platform
from ..scope import Scope

__all__ = ["Context"]


@dataclass
class Context:
    """What every command needs: where to print, and which backend to drive.

    The backend is built on first use, so commands that only inspect the
    installation (``version``, ``self info``) keep working on a platform that
    has no backend at all, and ``doctor`` can report that fact instead of
    failing before it starts.
    """

    console: Console
    scope: Scope
    _backend: Backend | None = field(default=None, repr=False)

    @property
    def backend(self) -> Backend:
        """The backend for this platform, built once."""
        if self._backend is None:
            self._backend = get_backend(self.scope)
        return self._backend

    @property
    def is_system(self) -> bool:
        """Whether this invocation manages machine-wide services."""
        return self.scope.is_system

    def require(self, command: str) -> None:
        """Refuse a command the current privileges cannot perform.

        ``list`` is the one read-only query that works unelevated on Windows,
        because reading the Task Scheduler needs no privileges.
        """
        if platform() == WINDOWS:
            if command == "list":
                return
            if not is_admin_windows():
                raise UniserviceError(
                    "Windows only supports admin execution for uniservice. "
                    "Open an Administrator shell and run it again."
                )
            return
        if self.scope.is_system and not is_root_unix():
            raise UniserviceError("Permission denied. Try running with sudo.")
