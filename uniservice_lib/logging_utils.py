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


def eprint(*args: object) -> None:
    """Print *args* to stderr."""
    print(*args, file=sys.stderr)


def log_path() -> Path:
    """Return the platform-specific uniservice log file path."""
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "uniservice" / "logs" / "uniservice.log"
    return Path.home() / ".uniservice" / "logs" / "uniservice.log"


def setup_logging() -> None:
    """Install the console and file handlers on the uniservice logger.

    The function is idempotent: calling it twice does not duplicate handlers.
    A log file that cannot be created is reported once but never prevents the
    command from running.
    """
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    if logger.handlers:
        return

    formatter = logging.Formatter(_LOG_FORMAT)

    console = logging.StreamHandler(stream=sys.stderr)
    console.setLevel(CONSOLE_LEVEL)
    console.setFormatter(formatter)
    logger.addHandler(console)

    try:
        path = log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(path, encoding="utf-8")
    except OSError as exc:
        logger.warning("Could not open the uniservice log file: %s", exc)
        return

    file_handler.setLevel(FILE_LEVEL)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
