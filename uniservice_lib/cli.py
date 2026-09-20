"""Command line interface for uniservice."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from . import __version__
from .backends import get_backend
from .backends.base import ServiceInfo
from .errors import ServiceNotFoundError, UniserviceError
from .installation import find_installation, manifest_path_for, remove_installation, running_commands
from .logging_utils import eprint, logger, setup_logging
from .naming import validate_service_name
from .platform_utils import WINDOWS, is_admin_windows, is_root_unix, platform
from .process import resolve_command_parts
from .scope import Scope

__all__ = [
    "EXIT_FAILURE",
    "EXIT_SUCCESS",
    "LIST_HEADER",
    "AddRequest",
    "build_parser",
    "entrypoint",
    "format_tristate",
    "main",
    "parse_add_argv",
    "render_list",
    "sanitize_field",
]

EXIT_SUCCESS = 0
EXIT_FAILURE = 1

LIST_HEADER = "NAME\tENABLED\tRUNNING"

#: ``add`` performs ``enable`` + ``start`` after writing the definition.
PAST_TENSE = {
    "enable": "enabled",
    "disable": "disabled",
    "start": "started",
    "stop": "stopped",
}

#: Control characters are replaced so that a single service can never break the
#: tab-separated ``list`` contract.
_FIELD_TRANSLATION = str.maketrans({"\t": " ", "\n": " ", "\r": " ", "\x00": ""})


@dataclass(frozen=True)
class AddRequest:
    """The parsed arguments of ``uniservice add``."""

    name: str
    workdir: str
    command_parts: tuple[str, ...]


def build_parser() -> argparse.ArgumentParser:
    """Build the ``uniservice`` argument parser."""
    parser = argparse.ArgumentParser(
        prog="uniservice",
        description="Cross-platform service manager (systemd / launchd / Scheduled Tasks).",
        epilog=(
            "scope: running this command yourself manages per-user services; running it through sudo "
            "(macOS/Linux) or an Administrator shell (Windows) manages system-wide services. sudo resets "
            'PATH, so call a user install by absolute path: sudo "$(command -v uniservice)" list'
        ),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    subparsers.add_parser("list", help="list managed services as TSV")

    cat = subparsers.add_parser("cat", help="print an equivalent add command")
    cat.add_argument("name", help="service name")

    status = subparsers.add_parser("status", help="show the native service status")
    status.add_argument("name", help="service name")

    logs = subparsers.add_parser("logs", help="show captured service logs")
    logs.add_argument("name", help="service name")
    logs.add_argument("--lines", type=_non_negative_int, default=200, help="number of log lines (default: 200)")
    logs.add_argument("--follow", "-f", action="store_true", help="keep streaming new log lines")

    for command, help_text in (
        ("enable", "start the service automatically at boot/login"),
        ("disable", "stop starting the service automatically"),
        ("start", "start the service now"),
        ("stop", "stop the running service"),
        ("remove", "stop, disable and delete the service"),
    ):
        subparser = subparsers.add_parser(command, help=help_text)
        subparser.add_argument("name", help="service name")

    add = subparsers.add_parser("add", help="create, enable and start a service")
    add.add_argument("argv", nargs=argparse.REMAINDER, help="NAME [--workdir DIR] -- COMMAND [ARG ...]")

    uninstall = subparsers.add_parser(
        "uninstall",
        help="remove the uniservice command itself",
        description=(
            "Removes the uniservice command and the files its installer recorded. "
            "Services you created are left alone; delete them with 'uniservice remove NAME' first "
            "if you do not want them."
        ),
    )
    uninstall.add_argument("--dry-run", action="store_true", help="show what would be removed")

    return parser


def parse_add_argv(argv: Sequence[str]) -> AddRequest:
    """Parse the raw ``add`` arguments (argparse cannot express this grammar)."""
    arguments = list(argv)
    if not arguments or arguments[0] == "--":
        raise UniserviceError("Missing NAME.")

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

    _validate_command(command_parts)
    return AddRequest(name=name, workdir=workdir, command_parts=tuple(command_parts))


def _validate_command(command_parts: Sequence[str]) -> None:
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


def format_tristate(value: bool | None) -> str:
    """Render a tri-state value as ``yes``/``no``/``?``."""
    if value is True:
        return "yes"
    if value is False:
        return "no"
    return "?"


def sanitize_field(value: str) -> str:
    """Make *value* safe to embed in a tab-separated line."""
    return value.translate(_FIELD_TRANSLATION)


def render_list(rows: Iterable[ServiceInfo]) -> list[str]:
    """Render *rows* as the documented TSV table.

    Rows are sorted so the output is stable across platforms, duplicate names
    (two Scheduled Tasks in different folders sharing a leaf name) are collapsed
    and rows without a usable name are dropped.
    """
    lines = [LIST_HEADER]
    seen: set[str] = set()
    for row in sorted(rows, key=lambda item: (item.name.casefold(), item.name)):
        name = sanitize_field(row.name)
        if not name.strip() or name in seen:
            continue
        seen.add(name)
        lines.append(f"{name}\t{format_tristate(row.enabled)}\t{format_tristate(row.running)}")
    return lines


def ensure_scope_allowed(scope: Scope, *, command: str) -> None:
    """Reject commands the current privileges cannot perform."""
    if platform() == WINDOWS:
        if command == "list":
            # Querying the Task Scheduler is read-only and works unelevated.
            return
        if not is_admin_windows():
            raise UniserviceError("Windows only supports admin execution for uniservice.")
        return

    if scope.is_system and not is_root_unix():
        raise UniserviceError("Permission denied. Try running with sudo.")


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return the process exit status."""
    setup_logging()
    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        return _dispatch(arguments)
    except UniserviceError as exc:
        eprint(f"FAIL: {exc}")
        return EXIT_FAILURE
    except subprocess.CalledProcessError as exc:
        rendered = " ".join(str(part) for part in exc.cmd)
        eprint(f"FAIL: command failed ({exc.returncode}): {rendered}")
        return exc.returncode or EXIT_FAILURE
    except KeyboardInterrupt:
        eprint("FAIL: interrupted")
        return 130
    except BrokenPipeError:
        _silence_broken_pipe()
        return EXIT_FAILURE
    except Exception as exc:  # the CLI must never traceback
        eprint(f"FAIL: {type(exc).__name__}: {exc}")
        return EXIT_FAILURE


def entrypoint() -> None:
    """Console-script entry point."""
    raise SystemExit(main())


def _dispatch(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "uninstall":
        return _cmd_uninstall(dry_run=args.dry_run)
    if args.command == "list":
        return _cmd_list()
    if args.command == "add":
        return _cmd_add(args.argv)
    if args.command == "logs":
        return _cmd_logs(args)
    return _cmd_service(args)


def _cmd_uninstall(*, dry_run: bool) -> int:
    """Remove the uniservice command itself; never touches services."""
    installation = find_installation()
    if installation is None:
        locations = ", ".join(str(path) for path in (manifest_path_for(c) for c in running_commands()))
        raise UniserviceError(
            f"no uniservice installation is recorded at {locations or 'this location'}. "
            "If it was installed with pip or pipx, uninstall it with that tool instead."
        )

    logger.info("cmd=uninstall prefix=%s kind=%s", installation.prefix, installation.kind)
    removed, deferred = remove_installation(installation, dry_run=dry_run)

    print(
        f"{'Would remove' if dry_run else 'Removed'} "
        f"uniservice {installation.version} ({installation.kind}) from {installation.prefix}"
    )
    for path in removed:
        print(f"  {path}")
    for path in deferred:
        # Windows only: a running image cannot delete itself, so it is handed to
        # a helper that runs once this process is gone.
        print(f"  {path} (a moment after this command exits)")
    if not removed and not deferred and not dry_run:
        print("  (there was nothing left to remove)")

    if not dry_run:
        print("Note: services you created are untouched. Remove them with 'uniservice remove NAME'.")
    return EXIT_SUCCESS


def _cmd_list() -> int:
    scope = Scope.from_env()
    ensure_scope_allowed(scope, command="list")
    logger.info("cmd=list scope=%s", scope.value)
    backend = get_backend(scope)
    for line in render_list(backend.list_info()):
        print(line)
    return EXIT_SUCCESS


def _cmd_service(args: argparse.Namespace) -> int:
    scope = Scope.from_env()
    ensure_scope_allowed(scope, command=args.command)
    name = validate_service_name(args.name)
    backend = get_backend(scope)
    if not backend.exists(name):
        raise ServiceNotFoundError(name)

    logger.info("cmd=%s name=%s scope=%s", args.command, name, scope.value)
    if args.command == "cat":
        backend.cat(name)
        return EXIT_SUCCESS
    if args.command == "status":
        backend.status(name)
        return EXIT_SUCCESS
    if args.command == "remove":
        backend.stop(name)
        backend.disable(name)
        backend.remove(name)
        print(f'OK: removed "{name}"')
        return EXIT_SUCCESS

    getattr(backend, args.command)(name)
    print(f'OK: {PAST_TENSE[args.command]} "{name}"')
    return EXIT_SUCCESS


def _cmd_logs(args: argparse.Namespace) -> int:
    scope = Scope.from_env()
    ensure_scope_allowed(scope, command="logs")
    name = validate_service_name(args.name)
    backend = get_backend(scope)
    if not backend.exists(name):
        raise ServiceNotFoundError(name)

    logger.info("cmd=logs name=%s scope=%s", name, scope.value)
    backend.logs(name, lines=args.lines, follow=args.follow)
    return EXIT_SUCCESS


def _cmd_add(argv: Sequence[str]) -> int:
    scope = Scope.from_env()
    ensure_scope_allowed(scope, command="add")
    request = parse_add_argv(argv)
    if not request.command_parts:
        raise UniserviceError("Missing COMMAND after --")

    backend = get_backend(scope)
    logger.info("cmd=add name=%s scope=%s", request.name, scope.value)
    command_parts = resolve_command_parts(list(request.command_parts))

    if request.workdir:
        workdir = Path(request.workdir)
    else:
        workdir = Path.cwd()
        logger.warning("No --workdir provided; the command runs in the current directory: %s", workdir)

    if backend.exists(request.name):
        _confirm_overwrite(request.name)
        backend.stop(request.name)
        backend.disable(request.name)
        backend.remove(request.name)

    backend.create(request.name, workdir, command_parts)
    backend.enable(request.name)
    backend.start(request.name)

    print(f'OK: added "{request.name}"')
    if scope.is_system and platform() != WINDOWS:
        print(f"Hint: Run: sudo uniservice status {request.name}")
    else:
        print(f"Hint: Run: uniservice status {request.name}")
    return EXIT_SUCCESS


def _confirm_overwrite(name: str) -> None:
    """Ask the user before replacing an existing service definition."""
    if not sys.stdin.isatty():
        raise UniserviceError(
            f'Service "{name}" already exists. '
            "Run in an interactive terminal to confirm the overwrite, or remove it first."
        )
    answer = input(f'Service "{name}" already exists. Overwrite? [y/N] ').strip().lower()
    if answer not in {"y", "yes"}:
        raise UniserviceError("Aborted.")


def _non_negative_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid integer value: {value!r}") from None
    if number < 0:
        raise argparse.ArgumentTypeError("must be greater than or equal to 0")
    return number


def _silence_broken_pipe() -> None:
    """Avoid a second BrokenPipeError while the interpreter shuts down."""
    try:
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
    except OSError:  # pragma: no cover - best effort only
        pass
