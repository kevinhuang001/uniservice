"""Service commands: the primary interface.

The display rules that matter here:

* ``list`` prints a table on a terminal and the tab separated contract
  (``NAME<TAB>ENABLED<TAB>RUNNING``) when stdout is redirected, so existing
  scripts keep working while a human gets something readable.
* ``status`` and ``logs`` deliberately hand the terminal to the native tool:
  its output *is* the answer, and reformatting it would lose information.
* everything else reports one line per affected service and exits non-zero if
  any of them failed, so ``uniservice restart a b c`` is usable in a script.
"""

from __future__ import annotations

import shlex
import sys
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path

from ..backends import ServiceDefinition, ServiceInfo
from ..console import Column
from ..errors import ServiceNotFoundError, UniserviceError
from ..exitcodes import FAILURE, OK
from ..logging_utils import logger
from ..naming import validate_service_name
from ..platform_utils import WINDOWS, platform
from ..process import resolve_command_parts
from . import Context

__all__ = [
    "AddRequest",
    "cmd_add",
    "cmd_control",
    "cmd_list",
    "cmd_logs",
    "cmd_remove",
    "cmd_show",
    "cmd_status",
    "format_tristate",
    "normalize_rows",
    "parse_add_argv",
    "render_add_command",
    "sanitize_field",
]

#: ``add`` performs ``enable`` + ``start`` after writing the definition.
PAST_TENSE = {
    "enable": "enabled",
    "disable": "disabled",
    "start": "started",
    "stop": "stopped",
    "restart": "restarted",
}

#: Control characters are replaced so that a single service can never break the
#: tab-separated ``list`` contract.
_FIELD_TRANSLATION = str.maketrans({"\t": " ", "\n": " ", "\r": " ", "\x00": ""})

LIST_COLUMNS = (
    Column("NAME"),
    Column("ENABLED"),
    Column("RUNNING"),
)

#: Running-state styling for the table; the tri-state value picks the entry.
_STATE_STYLES = {
    True: "green",
    False: "dim",
    None: "yellow",
}

_GLYPH = {True: "yes", False: "no", None: "?"}


def format_tristate(value: bool | None) -> str:
    """Render a tri-state value as ``yes``/``no``/``?``."""
    return _GLYPH[value]


def sanitize_field(value: str) -> str:
    """Make *value* safe to embed in a tab-separated line."""
    return value.translate(_FIELD_TRANSLATION)


def normalize_rows(rows: Iterable[ServiceInfo]) -> list[ServiceInfo]:
    """Sort, de-duplicate and sanitize *rows* for display.

    Rows are sorted so the output is stable across platforms, duplicate names
    (two Scheduled Tasks in different folders sharing a leaf name) are collapsed
    and rows without a usable name are dropped.
    """
    normalized: list[ServiceInfo] = []
    seen: set[str] = set()
    for row in sorted(rows, key=lambda item: (item.name.casefold(), item.name)):
        name = sanitize_field(row.name)
        if not name.strip() or name in seen:
            continue
        seen.add(name)
        normalized.append(ServiceInfo(name=name, enabled=row.enabled, running=row.running))
    return normalized


def service_payload(row: ServiceInfo, scope: str) -> dict[str, object]:
    """Return the ``--json`` shape of one service."""
    return {"name": row.name, "scope": scope, "enabled": row.enabled, "running": row.running}


def render_add_command(
    definition: ServiceDefinition,
    *,
    command_line: Callable[[Sequence[str]], str],
    windows: bool | None = None,
) -> str:
    """Return the ``uniservice add`` command that recreates *definition*.

    *command_line* is the backend's quoting helper, because Windows and POSIX
    disagree about how a command line is spelled.  *windows* only decides
    whether a system service is spelled with a leading ``sudo``; it defaults to
    the host platform.
    """
    if windows is None:
        windows = platform() == WINDOWS
    prefix = "sudo " if definition.scope == "system" and not windows else ""
    name = command_line([definition.name])
    workdir = command_line([definition.workdir])
    command = definition.raw or command_line(list(definition.command_parts))
    return f"{prefix}uniservice add {name} --workdir {workdir} -- {command}"


# --------------------------------------------------------------------- parsing


class AddRequest:
    """The parsed arguments of ``uniservice add``."""

    __slots__ = ("command_parts", "name", "workdir")

    def __init__(self, name: str, workdir: str, command_parts: tuple[str, ...]) -> None:
        self.name = name
        self.workdir = workdir
        self.command_parts = command_parts

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, AddRequest):
            return NotImplemented
        return (self.name, self.workdir, self.command_parts) == (other.name, other.workdir, other.command_parts)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"AddRequest(name={self.name!r}, workdir={self.workdir!r}, command_parts={self.command_parts!r})"


def parse_add_argv(argv: Sequence[str]) -> AddRequest:
    """Parse the raw ``add`` arguments (argparse cannot express this grammar)."""
    arguments = list(argv)
    if not arguments or arguments[0] == "--":
        raise UniserviceError("Missing NAME. Usage: uniservice add NAME [--workdir DIR] -- COMMAND [ARG ...]")

    name = validate_service_name(arguments[0])
    workdir = ""
    command_parts: list[str] = []

    rest = arguments[1:]
    index = 0
    while index < len(rest):
        token = rest[index]
        if token == "--":
            command_parts = rest[index + 1 :]
            break
        if token == "--workdir":
            if index + 1 >= len(rest):
                raise UniserviceError("Missing value for --workdir.")
            workdir = rest[index + 1]
            index += 2
            continue
        if token.startswith("--"):
            raise UniserviceError(f"Unknown option for add: {token}")
        command_parts = rest[index:]
        break

    validate_command(command_parts)
    return AddRequest(name=name, workdir=workdir, command_parts=tuple(command_parts))


def validate_command(command_parts: Sequence[str]) -> None:
    """Reject a command the native supervisors could not run.

    Every backend wraps the command as ``<shell> -lc '<cmd>'``, and the shell
    parses that string as a script: a leading ``-`` is taken as an *option to the
    shell itself*, so ``--`` produces ``bash: --: invalid option`` and the full
    usage text on every restart.  Saying so once beats a service that floods its
    log.
    """
    if command_parts and command_parts[0].startswith("-"):
        raise UniserviceError(
            f'Invalid COMMAND: "{command_parts[0]}" starts with "-", which the shell would read as an '
            'option. Did you add an extra "--"? Write the program to run after a single "--".'
        )


# -------------------------------------------------------------------- commands


def cmd_list(ctx: Context, args: object) -> int:
    """Print every service uniservice manages."""
    ctx.require("list")
    logger.info("cmd=list scope=%s", ctx.scope.value)
    rows = normalize_rows(ctx.backend.list_info())

    if ctx.console.json_mode:
        ctx.console.emit_json([service_payload(row, ctx.scope.value) for row in rows])
        return OK
    if ctx.console.quiet:
        for row in rows:
            ctx.console.out(row.name)
        return OK

    ctx.console.table(
        LIST_COLUMNS,
        [(row.name, *tristate_styled(ctx, row)) for row in rows],
    )
    if not rows and ctx.console.is_terminal:
        ctx.console.out()
        ctx.console.hint("no services in the " + ctx.scope.value + " scope yet")
        ctx.console.hint("create one with: uniservice add NAME -- COMMAND")
    return OK


def tristate_styled(ctx: Context, row: ServiceInfo) -> tuple[str, str]:
    """Return the coloured cells; the console strips colour when piped."""
    enabled = ctx.console.style(_GLYPH[row.enabled], _STATE_STYLES[row.enabled])
    running = ctx.console.style(_GLYPH[row.running], _STATE_STYLES[row.running])
    return enabled, running


def cmd_status(ctx: Context, args: object) -> int:
    """Show one service's native status, or a table of everything."""
    name = getattr(args, "name", None)
    if name is None:
        return _status_overview(ctx)
    return _status_one(ctx, name)


def _status_overview(ctx: Context) -> int:
    ctx.require("list")
    logger.info("cmd=status scope=%s", ctx.scope.value)
    rows = normalize_rows(ctx.backend.list_info())
    if ctx.console.json_mode:
        ctx.console.emit_json([service_payload(row, ctx.scope.value) for row in rows])
        return OK
    if ctx.console.quiet:
        for row in rows:
            ctx.console.out(row.name)
        return OK

    running = sum(1 for row in rows if row.running is True)
    ctx.console.heading(f"uniservice · {ctx.scope.value} scope")
    if rows:
        ctx.console.table(LIST_COLUMNS, [(row.name, *tristate_styled(ctx, row)) for row in rows])
    ctx.console.out()
    ctx.console.out(f"{len(rows)} service(s), {running} running")
    return OK


def _status_one(ctx: Context, name: str) -> int:
    name = validate_service_name(name)
    ctx.require("status")
    if not ctx.backend.exists(name):
        raise ServiceNotFoundError(name)
    logger.info("cmd=status name=%s scope=%s", name, ctx.scope.value)

    info = next((row for row in normalize_rows(ctx.backend.list_info()) if row.name == name), None)
    if info is not None:
        ctx.console.heading(f"{name} · {ctx.scope.value} scope · {_describe_state(info)}")
        ctx.console.out()
    ctx.console.flush()
    ctx.backend.status(name)
    return OK


def _describe_state(info: ServiceInfo) -> str:
    return f"{_GLYPH[info.running]} (running) · {_GLYPH[info.enabled]} (enabled)"


def cmd_logs(ctx: Context, args: object) -> int:
    """Stream the captured output of one service."""
    name = validate_service_name(args.name)
    ctx.require("logs")
    if not ctx.backend.exists(name):
        raise ServiceNotFoundError(name)
    logger.info("cmd=logs name=%s scope=%s follow=%s", name, ctx.scope.value, args.follow)
    if ctx.console.is_terminal:
        suffix = " (following)" if args.follow else ""
        ctx.console.note(f"--- {name}: last {args.lines} lines{suffix} ---")
    ctx.console.flush()
    ctx.backend.logs(name, lines=args.lines, follow=args.follow)
    return OK


def cmd_show(ctx: Context, args: object) -> int:
    """Print how a service is defined, and how to recreate it."""
    name = validate_service_name(args.name)
    ctx.require("show")
    logger.info("cmd=show name=%s scope=%s", name, ctx.scope.value)
    definition = ctx.backend.definition(name)

    if ctx.console.json_mode:
        ctx.console.emit_json(
            {
                "name": definition.name,
                "scope": definition.scope,
                "location": definition.location,
                "workdir": definition.workdir,
                "command": list(definition.command_parts),
                "raw": definition.raw,
                "recreate": render_add_command(definition, command_line=ctx.backend.command_line),
            }
        )
        return OK

    ctx.console.heading(f"{name} · {definition.scope} scope")
    ctx.console.fields(
        [
            ("command", definition.raw or ctx.backend.command_line(list(definition.command_parts))),
            ("workdir", definition.workdir or "(unknown)"),
            ("location", definition.location),
        ]
    )
    ctx.console.out()
    ctx.console.hint("recreate it with:")
    ctx.console.out("  " + render_add_command(definition, command_line=ctx.backend.command_line))
    return OK


def cmd_add(ctx: Context, args: object) -> int:
    """Create a service definition, enable it and start it."""
    ctx.require("add")
    request = parse_add_argv(args.argv)
    if not request.command_parts:
        raise UniserviceError("Missing COMMAND. Usage: uniservice add NAME [--workdir DIR] -- COMMAND [ARG ...]")

    logger.info("cmd=add name=%s scope=%s", request.name, ctx.scope.value)
    command_parts = resolve_command_parts(list(request.command_parts))

    if request.workdir:
        workdir = Path(request.workdir)
    else:
        workdir = Path.cwd()
        logger.warning("No --workdir provided; the command runs in the current directory: %s", workdir)

    replaced = ctx.backend.exists(request.name)
    if replaced:
        confirm_overwrite(request.name)
        ctx.backend.stop(request.name)
        ctx.backend.disable(request.name)
        ctx.backend.remove(request.name)

    ctx.backend.create(request.name, workdir, command_parts)
    ctx.backend.enable(request.name)
    ctx.backend.start(request.name)

    ctx.console.success(f'{"replaced" if replaced else "added"} "{request.name}"')
    if not ctx.console.quiet:
        definition = ctx.backend.definition(request.name)
        ctx.console.fields(
            [
                ("command", ctx.backend.command_line(command_parts)),
                ("workdir", str(workdir)),
                ("location", definition.location),
            ]
        )
        ctx.console.out()
        ctx.console.hint(f"follow its output with: uniservice logs {shlex.quote(request.name)} -f")
    return OK


def cmd_control(ctx: Context, args: object) -> int:
    """Run one lifecycle verb against one or more services."""
    command = args.command
    ctx.require(command)
    names = [validate_service_name(name) for name in args.names]
    logger.info("cmd=%s names=%s scope=%s", command, ",".join(names), ctx.scope.value)
    return _apply(ctx, command, names)


def cmd_remove(ctx: Context, args: object) -> int:
    """Stop, disable and delete one or more services."""
    ctx.require("remove")
    names = [validate_service_name(name) for name in args.names]
    logger.info("cmd=remove names=%s scope=%s", ",".join(names), ctx.scope.value)
    return _apply(ctx, "remove", names)


def _apply(ctx: Context, command: str, names: Sequence[str]) -> int:
    """Apply *command* to every name, reporting each one and aggregating."""
    failures = 0
    for name in names:
        try:
            if not ctx.backend.exists(name):
                raise ServiceNotFoundError(name)
            if command == "remove":
                ctx.backend.stop(name)
                ctx.backend.disable(name)
                ctx.backend.remove(name)
            else:
                getattr(ctx.backend, command)(name)
        except UniserviceError as exc:
            failures += 1
            ctx.console.error(f'"{name}": {exc}')
            continue
        verb = "removed" if command == "remove" else PAST_TENSE[command]
        ctx.console.success(f'{verb} "{name}"')

    if len(names) > 1 and not ctx.console.quiet:
        ctx.console.out(f"{len(names) - failures}/{len(names)} {PAST_TENSE[command]}")
    return FAILURE if failures else OK


def confirm_overwrite(name: str) -> None:
    """Ask the user before replacing an existing service definition."""
    if not sys.stdin.isatty():
        raise UniserviceError(
            f'Service "{name}" already exists. '
            "Run in an interactive terminal to confirm the overwrite, or remove it first."
        )
    answer = input(f'Service "{name}" already exists. Overwrite? [y/N] ').strip().lower()
    if answer not in {"y", "yes"}:
        raise UniserviceError("Aborted.")
