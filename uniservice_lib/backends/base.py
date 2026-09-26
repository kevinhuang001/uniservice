"""Backend contract and shared state-parsing helpers.

A backend is the only place that knows about a specific operating system.  The
command line layer treats every backend identically through the :class:`Backend`
interface.

Backends return **data**, not output: :meth:`Backend.definition` describes a
service so that the display layer can render it, and :meth:`Backend.checks`
describes the environment so that ``uniservice doctor`` can report it.  The two
methods that deliberately hand the terminal to a native tool are
:meth:`Backend.status` and :meth:`Backend.logs`, because their output *is* the
answer and reformatting it would lose information.
"""

from __future__ import annotations

import os
import shlex
import shutil
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from ..logging_utils import logger
from ..scope import Scope

__all__ = [
    "Backend",
    "Check",
    "ServiceDefinition",
    "ServiceInfo",
    "classify_state",
    "clear_files",
    "directory_check",
    "first_token",
    "tool_check",
]


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


@dataclass(frozen=True)
class ServiceDefinition:
    """Everything uniservice knows about a service it created.

    ``location`` is where the native definition lives: a unit or plist path on
    Linux and macOS, and the Scheduled Task name on Windows, which has no file
    uniservice owns.

    ``command_parts`` is empty when the native definition could not be
    decomposed back into an argument vector (a Scheduled Task whose action is a
    single opaque command line, for example); then ``raw`` holds the native
    command line instead and that is what gets shown.
    """

    name: str
    scope: str
    location: str
    workdir: str
    command_parts: tuple[str, ...] = ()
    raw: str = ""


@dataclass(frozen=True)
class Check:
    """One line of ``uniservice doctor``."""

    label: str
    ok: bool
    detail: str
    hint: str = ""
    #: A failing non-fatal check reports a warning instead of failing the run.
    fatal: bool = True


class Backend(ABC):
    """Operations every platform must implement."""

    def __init__(self, scope: Scope) -> None:
        self.scope = scope

    @abstractmethod
    def create(self, name: str, workdir: Path, command_parts: list[str]) -> None:
        """Write the native definition for *name*."""

    @abstractmethod
    def definition(self, name: str) -> ServiceDefinition:
        """Describe *name* so that ``uniservice show`` can render it."""

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

    def restart(self, name: str) -> None:
        """Stop and start *name*.

        The portable default; a backend with a native restart verb overrides it
        so that the supervisor can do it in one step.
        """
        self.stop(name)
        self.start(name)

    @abstractmethod
    def remove(self, name: str) -> None:
        """Delete the definition for *name*."""

    @abstractmethod
    def list_info(self) -> list[ServiceInfo]:
        """Return one :class:`ServiceInfo` per service uniservice manages."""

    def command_line(self, parts: Sequence[str]) -> str:
        """Render *parts* as a command line this platform's shell would accept.

        Used by ``uniservice show`` to print a runnable ``add`` command.  The
        default is POSIX quoting; Windows overrides it because it has its own
        (and incompatible) quoting rules.
        """
        return " ".join(shlex.quote(part) for part in parts)

    def checks(self) -> list[Check]:
        """Return the platform specific ``doctor`` checks.

        The base implementation reports nothing, so a backend that has nothing
        to probe does not have to implement anything.
        """
        return []


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


def tool_check(program: str, *, hint: str = "", fatal: bool = True) -> Check:
    """Return a :class:`Check` for an external program the backend needs."""
    path = shutil.which(program)
    if path:
        return Check(label=program, ok=True, detail=path, fatal=fatal)
    return Check(label=program, ok=False, detail="not found", hint=hint, fatal=fatal)


def directory_check(path: Path, *, label: str, hint: str = "", fatal: bool = True) -> Check:
    """Return a :class:`Check` for a directory the backend writes into.

    A directory that does not exist yet is fine as long as the nearest existing
    ancestor is writable, because ``create`` makes the parents it needs.
    """
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    writable = os.access(probe, os.W_OK)
    suffix = "" if path.exists() else f" (not created yet; {probe} must be writable)"
    return Check(
        label=label,
        ok=writable,
        detail=f"{path}{suffix}",
        hint=hint or f"{probe} is not writable by this user",
        fatal=fatal,
    )
