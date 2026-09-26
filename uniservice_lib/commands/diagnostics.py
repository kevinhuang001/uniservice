"""Diagnostics: ``uniservice doctor`` and ``uniservice version``.

``doctor`` answers the only question that matters when something does not work:
*can this machine supervise a service at all?* It checks the interpreter, the
platform, the privileges, the installation and the log file, then delegates to
the backend, which probes the native supervisor (systemd, launchd, the Task
Scheduler).  A check that fails but is not fatal is reported as a warning, so a
machine that merely lacks an optional tool does not look broken.
"""

from __future__ import annotations

import os
import sys

from ..backends import Check
from ..errors import UniserviceError, UnsupportedPlatformError
from ..exitcodes import FAILURE, OK
from ..installation import find_installation
from ..logging_utils import log_path
from ..platform_utils import UNSUPPORTED, WINDOWS, is_admin_windows, is_root_unix, platform
from . import Context

__all__ = ["cmd_doctor", "cmd_version"]

#: The interpreter uniservice needs; ``requires-python`` in pyproject.toml.
MINIMUM_PYTHON = (3, 10)


def cmd_version(ctx: Context, args: object) -> int:
    """Print the version of uniservice and of the things it runs on."""
    from .. import __version__

    installation = find_installation()
    install = (
        f"{installation.prefix} ({installation.kind} {installation.version})"
        if installation
        else "not managed by an installer"
    )
    payload = {
        "uniservice": __version__,
        "python": sys.version.split()[0],
        "executable": sys.executable,
        "platform": platform(),
        "scope": ctx.scope.value,
        "install": install,
        "log": str(log_path()),
    }
    if ctx.console.json_mode:
        ctx.console.emit_json(payload)
        return OK

    ctx.console.heading(f"uniservice {__version__}")
    ctx.console.fields(
        [
            ("python", f"{sys.version.split()[0]} ({sys.executable})"),
            ("platform", f"{platform()} · {ctx.scope.value} scope"),
            ("install", install),
            ("log", str(log_path())),
        ]
    )
    return OK


def cmd_doctor(ctx: Context, args: object) -> int:
    """Check the environment end to end."""
    checks = core_checks(ctx)
    checks.extend(_backend_checks(ctx))

    failures = [check for check in checks if not check.ok and check.fatal]
    if ctx.console.json_mode:
        ctx.console.emit_json(
            [
                {"label": check.label, "ok": check.ok, "detail": check.detail, "hint": check.hint, "fatal": check.fatal}
                for check in checks
            ]
        )
        return FAILURE if failures else OK

    if not ctx.console.quiet:
        ctx.console.heading("uniservice doctor")
    width = max(len(check.label) for check in checks) + 1
    for check in checks:
        ctx.console.check(check.label, check.ok, check.detail, hint=check.hint, fatal=check.fatal, width=width)
    if not ctx.console.quiet:
        ctx.console.out()
        ctx.console.out("all good" if not failures else f"{len(failures)} problem(s) found")
    return FAILURE if failures else OK


def core_checks(ctx: Context) -> list[Check]:
    """Return the checks that do not depend on the native supervisor."""
    checks = [
        Check(
            label="python",
            ok=sys.version_info[:2] >= MINIMUM_PYTHON,
            detail=f"{sys.version.split()[0]} ({sys.executable})",
            hint=f"uniservice needs Python {MINIMUM_PYTHON[0]}.{MINIMUM_PYTHON[1]} or newer",
        ),
        _platform_check(),
        _privilege_check(ctx),
    ]
    installation = find_installation()
    checks.append(
        Check(
            label="installation",
            ok=True,
            detail=(
                f"{installation.prefix} ({installation.kind} {installation.version})"
                if installation
                else "not managed by install.sh; that is fine for pipx, uv or a source checkout"
            ),
            fatal=False,
        )
    )
    checks.append(_log_check())
    return checks


def _platform_check() -> Check:
    name = platform()
    return Check(
        label="platform",
        ok=name != UNSUPPORTED,
        detail=f"{name} ({sys.platform})",
        hint="uniservice supports Linux (systemd), macOS (launchd) and Windows (Scheduled Tasks)",
    )


def _privilege_check(ctx: Context) -> Check:
    elevated = is_admin_windows() if platform() == WINDOWS else is_root_unix()
    return Check(
        label="privileges",
        ok=True,
        detail=(
            f"{'elevated' if elevated else 'normal user'} · {ctx.scope.value} scope"
            + ("" if elevated else " (use sudo or an Administrator shell for system services)")
        ),
        fatal=False,
    )


def _log_check() -> Check:
    path = log_path()
    probe = path.parent
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    writable = os.access(probe, os.W_OK)
    return Check(
        label="log file",
        ok=writable,
        detail=str(path),
        hint=f"{probe} is not writable; diagnostics will not be recorded",
        fatal=False,
    )


def _backend_checks(ctx: Context) -> list[Check]:
    """Probe the native supervisor, reporting a broken backend as a finding."""
    try:
        backend = ctx.backend
    except UnsupportedPlatformError as exc:
        return [Check(label="backend", ok=False, detail=str(exc), hint="nothing can be managed on this platform")]
    try:
        return backend.checks()
    except UniserviceError as exc:  # pragma: no cover - defensive
        return [Check(label="backend", ok=False, detail=str(exc))]
