"""Canonical names for the native definitions uniservice creates.

Keeping the mapping between a *service name* and the file/task/label that
represents it in one place means the backends, the installers and the tests all
agree on the layout, and that parsing is the exact inverse of formatting.
"""

from __future__ import annotations

from .errors import InvalidServiceNameError

__all__ = [
    "LAUNCHD_LABEL_PREFIX",
    "LAUNCHD_PLIST_SUFFIX",
    "SYSTEMD_UNIT_PREFIX",
    "SYSTEMD_UNIT_SUFFIX",
    "WINDOWS_TASK_PREFIX",
    "macos_label",
    "macos_plist_name",
    "parse_macos_plist_name",
    "parse_systemd_unit_name",
    "parse_windows_task_name",
    "systemd_unit_name",
    "validate_service_name",
    "windows_task_name",
]

SYSTEMD_UNIT_PREFIX = "uniservice-"
SYSTEMD_UNIT_SUFFIX = ".service"
LAUNCHD_LABEL_PREFIX = "com.uniservice."
LAUNCHD_PLIST_SUFFIX = ".plist"
WINDOWS_TASK_PREFIX = "uniservice-"

#: Characters that must never appear in a service name.  ``/`` and ``\\`` would
#: turn the definition path into a nested path (and let ``..`` components escape
#: the unit directory), while the remaining ones break either the TSV output of
#: ``uniservice list`` or the native definition format itself.
_FORBIDDEN_NAME_CHARACTERS = frozenset("/\\\t\n\r\x00")

#: Upper bound that keeps every name valid for systemd, launchd and schtasks.
MAX_NAME_LENGTH = 200


def systemd_unit_name(name: str) -> str:
    """Return the systemd unit file name for *name*."""
    return f"{SYSTEMD_UNIT_PREFIX}{name}{SYSTEMD_UNIT_SUFFIX}"


def parse_systemd_unit_name(filename: str) -> str | None:
    """Return the service name encoded in a systemd unit file name."""
    return _strip_affixes(filename, SYSTEMD_UNIT_PREFIX, SYSTEMD_UNIT_SUFFIX)


def macos_label(name: str) -> str:
    """Return the launchd label for *name*."""
    return f"{LAUNCHD_LABEL_PREFIX}{name}"


def macos_plist_name(name: str) -> str:
    """Return the launchd plist file name for *name*."""
    return f"{LAUNCHD_LABEL_PREFIX}{name}{LAUNCHD_PLIST_SUFFIX}"


def parse_macos_plist_name(filename: str) -> str | None:
    """Return the service name encoded in a launchd plist file name."""
    return _strip_affixes(filename, LAUNCHD_LABEL_PREFIX, LAUNCHD_PLIST_SUFFIX)


def windows_task_name(name: str) -> str:
    """Return the Scheduled Task name for *name*."""
    return f"{WINDOWS_TASK_PREFIX}{name}"


def parse_windows_task_name(task_name: str) -> str | None:
    """Return the service name encoded in a Scheduled Task name.

    Task Scheduler reports tasks below a folder as ``\\Folder\\Task``; only the
    leaf component is relevant here.
    """
    leaf = task_name.strip().rsplit("\\", 1)[-1]
    return _strip_affixes(leaf, WINDOWS_TASK_PREFIX, "")


def validate_service_name(name: str) -> str:
    """Validate *name* and return it with surrounding whitespace removed.

    Raises :class:`~uniservice_lib.errors.InvalidServiceNameError` when the name
    cannot be used to build a definition path.
    """
    normalized = name.strip()
    if not normalized:
        raise InvalidServiceNameError("Missing NAME.")
    if normalized in {".", ".."}:
        raise InvalidServiceNameError(f'Invalid service name: "{name}"')
    if normalized.startswith("-"):
        raise InvalidServiceNameError(f'Invalid service name: "{name}" (must not start with "-")')
    if any(character in _FORBIDDEN_NAME_CHARACTERS for character in normalized):
        raise InvalidServiceNameError(
            f'Invalid service name: "{name}" (must not contain "/", "\\", control characters or NUL)'
        )
    if len(normalized) > MAX_NAME_LENGTH:
        raise InvalidServiceNameError(f'Invalid service name: "{name}" (longer than {MAX_NAME_LENGTH} characters)')
    return normalized


def _strip_affixes(value: str, prefix: str, suffix: str) -> str | None:
    if suffix:
        if not value.endswith(suffix):
            return None
        value = value[: -len(suffix)]
    if not value.startswith(prefix):
        return None
    return value[len(prefix) :]
