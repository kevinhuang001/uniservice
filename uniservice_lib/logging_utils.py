"""Logging and stderr helpers.

uniservice writes everything at ``DEBUG`` and above to a log file while keeping
the console at ``WARNING`` and above, so normal commands stay quiet but
recoverable problems (for example a command that is not an absolute path) are
still visible.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

__all__ = ["CONSOLE_LEVEL", "FILE_LEVEL", "eprint", "log_path", "logger", "setup_logging"]

LOGGER_NAME = "uniservice"
logger = logging.getLogger(LOGGER_NAME)

CONSOLE_LEVEL = logging.WARNING
FILE_LEVEL = logging.DEBUG

_LOG_FORMAT = "%(asctime)s %(levelname)s %(message)s"

#: The console shows a short prefix; the log file keeps the timestamp.
_CONSOLE_FORMAT = "uniservice: %(message)s"


def eprint(*args: object) -> None:
    """Print *args* to stderr."""
    print(*args, file=sys.stderr)


def log_path() -> Path:
    """Return the platform-specific uniservice log file path."""
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "uniservice" / "logs" / "uniservice.log"
    return Path.home() / ".uniservice" / "logs" / "uniservice.log"


_console_handler = logging.StreamHandler(stream=sys.stderr)


def setup_logging(*, verbose: bool = False) -> None:
    """Install the console and file handlers on the uniservice logger.

    The function is idempotent: calling it twice does not duplicate handlers.
    ``verbose`` (``uniservice -v``) turns the console handler down to DEBUG,
    which is how a single failing command is diagnosed without hunting for the
    log file.  A log file that cannot be created is reported once but never
    prevents the command from running.
    """
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    _console_handler.setLevel(logging.DEBUG if verbose else CONSOLE_LEVEL)
    _console_handler.setFormatter(logging.Formatter(_CONSOLE_FORMAT))
    if logger.handlers:
        return

    logger.addHandler(_console_handler)
    _console_handler.setStream(sys.stderr)

    try:
        path = log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(path, encoding="utf-8")
    except OSError as exc:
        logger.warning("Could not open the uniservice log file: %s", exc)
        return

    file_handler.setLevel(FILE_LEVEL)
    file_handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    logger.addHandler(file_handler)
