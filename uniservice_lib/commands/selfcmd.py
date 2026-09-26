"""Commands that act on the uniservice installation, not on a service.

They live in their own group so that ``uniservice --help`` does not suggest that
a *service* can be installed or uninstalled: ``uniservice remove NAME`` deletes
a service, ``uniservice self uninstall`` deletes uniservice itself.
"""

from __future__ import annotations

from ..console import Column
from ..errors import UniserviceError
from ..exitcodes import OK
from ..installation import find_installation, manifest_path_for, remove_installation, running_commands
from ..logging_utils import logger
from . import Context

__all__ = ["cmd_info", "cmd_uninstall"]


def _installation_payload(installation, *, command: str) -> dict[str, object]:  # type: ignore[no-untyped-def]
    return {
        "program": installation.fields.get("program", "uniservice"),
        "version": installation.version,
        "kind": installation.kind,
        "prefix": str(installation.prefix),
        "command": command,
        "manifest": str(installation.manifest),
        "asset": installation.fields.get("asset", ""),
        "sha256": installation.fields.get("sha256", ""),
        "installed_at": installation.fields.get("installed_at", ""),
    }


def cmd_info(ctx: Context, args: object) -> int:
    """Report where this uniservice lives and how it was installed."""
    installation = find_installation()
    if installation is None:
        locations = ", ".join(str(path) for path in (manifest_path_for(c) for c in running_commands()))
        if ctx.console.json_mode:
            ctx.console.emit_json({"managed": False, "looked_for": locations})
            return OK
        ctx.console.warn("this copy was not installed by install.sh or install-windows.ps1")
        ctx.console.fields(
            [
                ("manifest", locations or "(no location to look in)"),
                ("hint", "installed with pipx or uv? manage it with that tool"),
            ]
        )
        return OK

    logger.info("cmd=self.info prefix=%s kind=%s", installation.prefix, installation.kind)
    payload = _installation_payload(installation, command=str(installation.command))
    if ctx.console.json_mode:
        ctx.console.emit_json(payload)
        return OK

    ctx.console.heading(f"uniservice {installation.version} · {installation.kind}")
    asset = installation.fields.get("asset") or "(unknown)"
    digest = installation.fields.get("sha256") or ""
    ctx.console.fields(
        [
            ("prefix", str(installation.prefix)),
            ("command", str(installation.command)),
            ("manifest", str(installation.manifest)),
            ("asset", f"{asset}  sha256 {digest[:12]}…" if digest else asset),
            ("installed", installation.fields.get("installed_at") or "(unknown)"),
        ]
    )
    rendered = False
    for path in installation.recorded_files:
        if not rendered:
            ctx.console.out()
            ctx.console.hint("installed files:")
            rendered = True
        ctx.console.out(f"  {path}")
    ctx.console.out()
    ctx.console.hint("remove it with: uniservice self uninstall")
    return OK


def cmd_uninstall(ctx: Context, args: object) -> int:
    """Remove the uniservice command itself; never touches services."""
    dry_run = bool(getattr(args, "dry_run", False))
    installation = find_installation()
    if installation is None:
        locations = ", ".join(str(path) for path in (manifest_path_for(c) for c in running_commands()))
        raise UniserviceError(
            f"no uniservice installation is recorded at {locations or 'this location'}. "
            "Only a copy placed there by install.sh or install-windows.ps1 writes a manifest; "
            "if this one came from PyPI, remove it with `pipx uninstall uniservice` "
            "(`uv tool uninstall uniservice` or `pip uninstall uniservice`)."
        )

    logger.info("cmd=self.uninstall prefix=%s kind=%s dry_run=%s", installation.prefix, installation.kind, dry_run)
    removed, deferred = remove_installation(installation, dry_run=dry_run)

    if ctx.console.json_mode:
        ctx.console.emit_json(
            {
                "prefix": str(installation.prefix),
                "version": installation.version,
                "dry_run": dry_run,
                "removed": [str(path) for path in removed],
                "deferred": [str(path) for path in deferred],
            }
        )
        return OK

    verb = "would remove" if dry_run else "removed"
    ctx.console.success(f"{verb} uniservice {installation.version} ({installation.kind}) from {installation.prefix}")
    if removed or deferred:
        ctx.console.table(
            (Column("FILE"), Column("WHEN")),
            [
                (str(path), "a moment after this command exits" if path in deferred else "now")
                for path in [*removed, *deferred]
            ],
        )
    elif not dry_run:
        ctx.console.note("there was nothing left to remove")
    if not dry_run:
        ctx.console.note("services you created are untouched; delete them with 'uniservice remove NAME'")
    return OK
