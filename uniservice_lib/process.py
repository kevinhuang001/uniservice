"""Helpers around ``subprocess``.

Every external command uniservice runs goes through :func:`run`, which adds
debug logging and the conventions the backends rely on (``text=True``, and
either captured or discarded output).
"""

from __future__ import annotations

import shlex
import shutil
import subprocess
from pathlib import Path

from .logging_utils import logger

__all__ = ["command_string", "resolve_command_parts", "run"]


def run(
    cmd: list[str],
    *,
    check: bool = True,
    quiet: bool = False,
    capture: bool = False,
    cwd: str | Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run *cmd* and return the completed process.

    Args:
        cmd: Command and arguments, passed to :func:`subprocess.run` verbatim.
        check: Raise :class:`subprocess.CalledProcessError` on a non-zero exit.
        quiet: Discard stdout and stderr.
        capture: Capture stdout and stderr into the returned process.
        cwd: Working directory for the child process.

    ``capture`` wins over ``quiet`` when both are requested.
    """
    kwargs: dict[str, object] = {}
    if capture:
        kwargs["capture_output"] = True
    elif quiet:
        kwargs["stdout"] = subprocess.DEVNULL
        kwargs["stderr"] = subprocess.DEVNULL

    logger.debug("run: %s", command_string(cmd))
    completed = subprocess.run(cmd, check=check, text=True, cwd=cwd, **kwargs)
    if capture:
        if completed.stdout:
            logger.debug("stdout: %s", completed.stdout.rstrip("\n"))
        if completed.stderr:
            logger.debug("stderr: %s", completed.stderr.rstrip("\n"))
    return completed


def command_string(command_parts: list[str]) -> str:
    """Render *command_parts* as a POSIX shell command line."""
    return " ".join(shlex.quote(part) for part in command_parts)


def resolve_command_parts(command_parts: list[str]) -> list[str]:
    """Resolve a relative executable to an absolute path when possible.

    The native supervisors do not inherit the interactive shell's ``PATH`` in a
    predictable way, so a command that is not an absolute path is resolved here.
    A successful resolution is recorded at ``INFO`` (visible with ``-v``) since
    it already made the service work; only a command we could *not* resolve is a
    warning, because that one is likely to fail when the service starts.
    """
    if not command_parts:
        return command_parts

    executable = command_parts[0]
    if Path(executable).is_absolute():
        return command_parts

    resolved = shutil.which(executable)
    if resolved:
        logger.info('Command "%s" is not an absolute path; resolved to "%s"', executable, resolved)
        return [resolved, *command_parts[1:]]

    logger.warning('Command "%s" is not an absolute path and was not found in PATH', executable)
    return command_parts
