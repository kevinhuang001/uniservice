"""The ``uniservice`` command line.

This module is only the entry point: it parses, builds the
:class:`~uniservice_lib.commands.Context`, dispatches to one command function
and turns failures into exit codes.  Everything a command *does* lives in
:mod:`uniservice_lib.commands`.
"""

from __future__ import annotations

import os
import subprocess
import sys
import traceback
from collections.abc import Sequence
from typing import Any

from .commands import Context, selfcmd, service
from .commands import diagnostics as diagnostics_cmd
from .console import Console
from .errors import UniserviceError, UsageError
from .exitcodes import FAILURE, INTERRUPTED, OK, USAGE
from .logging_utils import logger, setup_logging
from .parser import PROG, build_parser, subcommand_help, usage_text
from .scope import Scope

__all__ = ["entrypoint", "main"]

#: Subcommand aliases, normalised before dispatch.
ALIASES = {"ls": "list", "rm": "remove"}

#: The verbs that share one implementation.
CONTROL_VERBS = frozenset({"start", "stop", "restart", "enable", "disable"})


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return the process exit status."""
    arguments = list(sys.argv[1:] if argv is None else argv)

    if not arguments:
        print(usage_text(), file=sys.stderr, end="")
        return USAGE

    parser = build_parser()
    try:
        args = parser.parse_args(arguments)
    except UsageError as exc:
        print(f"{PROG}: {exc}", file=sys.stderr)
        return USAGE
    except SystemExit as exc:  # argparse's --version and per-command --help
        return int(exc.code or OK)

    setup_logging(verbose=bool(getattr(args, "verbose", False)))
    console = Console(
        color=getattr(args, "color", "auto"),
        unicode=not getattr(args, "ascii", False),
        quiet=bool(getattr(args, "quiet", False)),
        json_mode=bool(getattr(args, "json", False)),
        table=bool(getattr(args, "table", False)),
    )
    ctx = Context(console=console, scope=Scope.from_env())

    try:
        if getattr(args, "show_help", False) or args.command is None:
            stream = None if getattr(args, "show_help", False) else sys.stderr
            print(usage_text(), end="", file=stream)
            return OK if getattr(args, "show_help", False) else USAGE
        return dispatch(ctx, args)
    except UsageError as exc:
        console.err(f"{PROG}: {exc}")
        return USAGE
    except UniserviceError as exc:
        logger.debug("command failed", exc_info=True)
        console.error(str(exc))
        return FAILURE
    except subprocess.CalledProcessError as exc:
        logger.debug("subprocess failed", exc_info=True)
        rendered = " ".join(str(part) for part in exc.cmd)
        console.error(f"command failed ({exc.returncode}): {rendered}")
        detail = (getattr(exc, "stderr", None) or getattr(exc, "stdout", None) or "").strip()
        for line in detail.splitlines():
            console.err(f"  {line}")
        return exc.returncode or FAILURE
    except KeyboardInterrupt:
        console.err("")
        console.err(f"{PROG}: interrupted")
        return INTERRUPTED
    except BrokenPipeError:
        _silence_broken_pipe()
        return FAILURE
    except Exception as exc:  # the CLI must never traceback
        if getattr(args, "verbose", False):
            traceback.print_exc()
        else:
            logger.debug("unexpected failure", exc_info=True)
        console.error(f"{type(exc).__name__}: {exc}")
        return FAILURE


def dispatch(ctx: Context, args: Any) -> int:
    """Call the command function named by ``args.command``."""
    command = ALIASES.get(args.command, args.command)
    args.command = command

    if command == "help":
        return _cmd_help(args.topic)
    if command == "list":
        return service.cmd_list(ctx, args)
    if command == "add":
        return service.cmd_add(ctx, args)
    if command == "status":
        return service.cmd_status(ctx, args)
    if command == "logs":
        return service.cmd_logs(ctx, args)
    if command == "show":
        return service.cmd_show(ctx, args)
    if command == "remove":
        return service.cmd_remove(ctx, args)
    if command in CONTROL_VERBS:
        return service.cmd_control(ctx, args)
    if command == "self":
        return _cmd_self(ctx, args)
    if command == "doctor":
        return diagnostics_cmd.cmd_doctor(ctx, args)
    if command == "version":
        return diagnostics_cmd.cmd_version(ctx, args)
    raise UsageError(f"unknown command {command!r}")  # pragma: no cover - parser rejects it first


def _cmd_self(ctx: Context, args: Any) -> int:
    sub = getattr(args, "self_command", None)
    if sub == "info":
        return selfcmd.cmd_info(ctx, args)
    if sub == "uninstall":
        return selfcmd.cmd_uninstall(ctx, args)
    # `uniservice self` on its own: show what `self` can do instead of failing.
    print(subcommand_help("self"), end="", file=sys.stderr)
    return USAGE


def _cmd_help(topic: str | None) -> int:
    if not topic:
        print(usage_text(), end="")
        return OK
    text = subcommand_help(topic)
    if not text:
        raise UsageError(f"unknown command {topic!r}")
    print(text, end="")
    return OK


def entrypoint() -> None:
    """Console-script entry point."""
    raise SystemExit(main())


def _silence_broken_pipe() -> None:
    """Avoid a second BrokenPipeError while the interpreter shuts down."""
    try:
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
    except OSError:  # pragma: no cover - best effort only
        pass
