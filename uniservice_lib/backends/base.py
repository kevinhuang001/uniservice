"""Backend contract and shared state-parsing helpers.

A backend is the only place that knows about a specific operating system.  The
command line layer treats every backend identically through the :class:`Backend`
interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from ..logging_utils import logger
from ..scope import Scope

__all__ = ["Backend", "ServiceInfo", "classify_state", "clear_files", "first_token"]


@dataclass(frozen=True)
class ServiceInfo:
    """A single row of ``uniservice list``.

    ``enabled`` and ``running`` are tri-state: ``True``/``False`` when the
    platform reported a definitive answer and ``None`` when it did not (which
    renders as ``?``).
    """

    name: str
    enabled: bool | None
    running: bool | None


class Backend(ABC):
    """Operations every platform must implement."""

    def __init__(self, scope: Scope) -> None:
        self.scope = scope

    @abstractmethod
    def create(self, name: str, workdir: Path, command_parts: list[str]) -> None:
        """Write the native definition for *name*."""

    @abstractmethod
    def cat(self, name: str) -> None:
        """Print an equivalent ``uniservice add`` command."""

    @abstractmethod
    def status(self, name: str) -> None:
        """Print the native status output."""

    @abstractmethod
    def logs(self, name: str, *, lines: int, follow: bool) -> None:
        """Print (and optionally follow) the service logs."""

    @abstractmethod
    def exists(self, name: str) -> bool:
        """Return whether a definition for *name* exists."""

    @abstractmethod
    def enable(self, name: str) -> None:
        """Enable autostart for *name*."""

    @abstractmethod
    def disable(self, name: str) -> None:
        """Disable autostart for *name*."""

    @abstractmethod
    def start(self, name: str) -> None:
        """Start *name*."""

    @abstractmethod
    def stop(self, name: str) -> None:
        """Stop *name*."""

    @abstractmethod
    def remove(self, name: str) -> None:
        """Delete the definition for *name*."""

    @abstractmethod
    def list_info(self) -> list[ServiceInfo]:
        """Return one :class:`ServiceInfo` per service uniservice manages."""


def first_token(*texts: str) -> str:
    """Return the first non-empty token found in *texts*, lower-cased.

    Native tools write their state to stdout and warnings to stderr.  Passing
    the two streams separately (instead of concatenating them) keeps a warning
    from corrupting the parsed state, which was the source of a ``list`` bug on
    Linux and macOS.
    """
    for text in texts:
        for line in (text or "").splitlines():
            stripped = line.strip()
            if stripped:
                return stripped.split()[0].lower()
    return ""


def classify_state(*texts: str, true_states: frozenset[str], false_states: frozenset[str]) -> bool | None:
    """Map native state text onto a tri-state value.

    Anything that is not explicitly known becomes ``None`` so that ``list``
    reports ``?`` instead of guessing.
    """
    token = first_token(*texts)
    if token in true_states:
        return True
    if token in false_states:
        return False
    return None


def clear_files(*paths: Path) -> list[Path]:
    """Delete the *paths* that exist and return the ones actually removed.

    The file-based backends call this before writing a new definition so that a
    service re-created under the same name starts with an empty log instead of
    inheriting the previous incarnation's output.
    """
    removed: list[Path] = []
    for path in paths:
        if not path.exists():
            continue
        try:
            path.unlink()
        except OSError as exc:
            logger.debug("could not remove the old log %s: %s", path, exc)
            continue
        removed.append(path)
    return removed
