"""The ``uniservice`` command tree.

Argparse does the parsing; the help text is written by hand because a flat list
of eleven verbs says nothing about which of them belong together.  Commands are
grouped by what they act on:

``service commands``
    Every one of them acts on a service, so they need no group of their own -
    exactly like ``curl``'s arguments are ``aria2curl``'s primary interface.
    Installing and removing uniservice itself belongs to the install scripts,
    which own the layout and can delete the command from a different process.
``diagnostics``
    ``doctor`` and ``version`` describe the machine, not any service.

The parser never prints usage itself: :class:`UsageError` is raised and the
command line layer decides how to report it.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from typing import Any

from . import __version__
from .console import COLOR_CHOICES

PROG = "uniservice"

#: ``(group, ((usage form, summary), ...))`` — rendered by :func:`usage_text`.
COMMAND_GROUPS: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    (
        "service commands",
        (
            ("list, ls", "list the services uniservice manages"),
            ("add NAME -- COMMAND...", "create, enable and start a service"),
            ("start|stop|restart NAME...", "change the running state"),
            ("enable|disable NAME...", "change whether it starts at boot"),
            ("remove, rm NAME...", "stop, disable and delete a service"),
            ("status [NAME]", "native status for NAME, or a table of everything"),
            ("logs NAME [-f]", "print the captured output"),
            ("show NAME", "how the service is defined and how to recreate it"),
        ),
    ),
    (
        "diagnostics",
        (
            ("doctor", "check this machine end to end, installation included"),
            ("version", "print component versions"),
            ("help [COMMAND]", "this text, or one command's options"),
        ),
    ),
)

_GLOBAL_HELP = (
    ("--color WHEN", "auto (default), always or never"),
    ("--ascii", "use ASCII status marks and rules"),
    ("--json", "machine-readable output where supported"),
    ("-q, --quiet", "only report failures"),
    ("-v, --verbose", "debug logging on stderr"),
    ("-h, --help", "this text"),
    ("--version", "print the version and exit"),
)

_SCOPE_HELP = (
    "running this yourself manages user services (systemd --user, ~/Library/LaunchAgents);",
    "running it through sudo (macOS/Linux) or an Administrator shell (Windows) manages",
    "system services (/etc/systemd/system, /Library/LaunchDaemons, a SYSTEM Scheduled Task).",
    "",
    "sudo resets PATH to the sudoers secure_path, which never contains your home directory,",
    "so a per-user install has to be called by absolute path:",
    '    sudo "$(command -v uniservice)" list',
)

_EXAMPLE_HELP = (
    "uniservice add web --workdir ~/site -- python3 -m http.server 8080",
    "uniservice list",
    "uniservice logs web -f",
    "sudo uniservice restart web",
    "uniservice doctor",
)


def usage_text() -> str:
    """Return the top level help."""
    lines = [
        f"{PROG} {__version__} — manage background services with systemd, launchd or Scheduled Tasks",
        "",
        "usage:",
        f"  {PROG} <command> [options]",
        "",
    ]
    for title, entries in COMMAND_GROUPS:
        lines.append(f"{title}:")
        width = max(len(form) for form, _ in entries)
        lines.extend(f"  {form.ljust(width)}  {summary}" for form, summary in entries)
        lines.append("")
    lines.append("global options:")
    width = max(len(form) for form, _ in _GLOBAL_HELP)
    lines.extend(f"  {form.ljust(width)}  {summary}" for form, summary in _GLOBAL_HELP)
    lines.append("")
    lines.append("scope:")
    lines.extend(f"  {line}" if line else "" for line in _SCOPE_HELP)
    lines.append("")
    lines.append("examples:")
    lines.extend(f"  {line}" for line in _EXAMPLE_HELP)
    return "\n".join(lines) + "\n"


class _Parser(argparse.ArgumentParser):
    """An ``ArgumentParser`` that reports errors instead of exiting."""

    def error(self, message: str) -> Any:
        from .errors import UsageError

        raise UsageError(message)


def _add_global_flags(parser: argparse.ArgumentParser, *, suppressed: bool) -> None:
    """Declare the global flags.

    The second declaration (on a subcommand) uses ``SUPPRESS`` so that a flag
    given *before* the command is not overwritten by the subcommand's default,
    which is the classic argparse ``parents=`` pitfall.
    """
    default: Any = argparse.SUPPRESS if suppressed else None

    def value_default(value: Any) -> Any:
        return argparse.SUPPRESS if suppressed else value

    parser.add_argument(
        "--color",
        choices=COLOR_CHOICES,
        default=value_default("auto"),
        metavar="WHEN",
        help="auto (default), always or never",
    )
    parser.add_argument("--ascii", action="store_true", default=value_default(False), help="use ASCII status marks")
    parser.add_argument(
        "--json", action="store_true", default=value_default(False), help="machine-readable output where supported"
    )
    parser.add_argument("-q", "--quiet", action="store_true", default=value_default(False), help="only report failures")
    parser.add_argument(
        "-v", "--verbose", action="store_true", default=value_default(False), help="debug logging on stderr"
    )
    del default


def _service_parsers(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    listing = subparsers.add_parser("list", aliases=["ls"], help="list the services uniservice manages")
    listing.add_argument("--table", action="store_true", help="draw the table even when stdout is a pipe")

    add = subparsers.add_parser("add", help="create, enable and start a service")
    add.add_argument("argv", nargs=argparse.REMAINDER, metavar="NAME [--workdir DIR] -- COMMAND [ARG ...]")

    for command, help_text in (
        ("start", "start a stopped service"),
        ("stop", "stop a running service"),
        ("restart", "stop and start a service"),
        ("enable", "start the service automatically at boot/login"),
        ("disable", "stop starting the service automatically"),
        ("remove", "stop, disable and delete a service"),
    ):
        parser = subparsers.add_parser(command, aliases=["rm"] if command == "remove" else [], help=help_text)
        parser.add_argument("names", nargs="+", metavar="NAME", help="one or more service names")

    status = subparsers.add_parser("status", help="show the native status, or a table of everything")
    status.add_argument("name", nargs="?", help="service name; omit to show every service")
    status.add_argument("--table", action="store_true", help="draw the table even when stdout is a pipe")

    logs = subparsers.add_parser("logs", help="print the captured service output")
    logs.add_argument("name", help="service name")
    logs.add_argument("-n", "--lines", type=_non_negative_int, default=200, help="number of lines (default: 200)")
    logs.add_argument("-f", "--follow", action="store_true", help="keep streaming new lines")

    show = subparsers.add_parser("show", help="print how a service is defined")
    show.add_argument("name", help="service name")


def _diagnostic_parsers(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    subparsers.add_parser("doctor", help="check this machine end to end")
    subparsers.add_parser("version", help="print component versions")

    help_parser = subparsers.add_parser("help", help="this text, or one command's options")
    help_parser.add_argument("topic", nargs="?", metavar="COMMAND", help="command to explain")


def build_parser() -> argparse.ArgumentParser:
    """Build the ``uniservice`` argument parser."""
    parser = _Parser(prog=PROG, add_help=False, allow_abbrev=False, description=usage_text())
    _add_global_flags(parser, suppressed=False)
    parser.add_argument("-h", "--help", action="store_true", dest="show_help", help="show this text")
    parser.add_argument("--version", action="version", version=f"{PROG} {__version__}")

    # Deliberately not required: a bare `uniservice --help` must print the help
    # instead of failing the "COMMAND is required" check.  The dispatcher turns
    # a missing command into a usage error.
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")
    _service_parsers(subparsers)
    _diagnostic_parsers(subparsers)
    for subparser in _registered(subparsers):
        _add_global_flags(subparser, suppressed=True)
    return parser


def _registered(subparsers: argparse._SubParsersAction) -> Sequence[argparse.ArgumentParser]:  # type: ignore[type-arg]
    """Return every subcommand parser once.

    ``choices`` maps each alias to the *same* parser object, so adding the
    global flags without de-duplicating would declare them twice.
    """
    unique: list[argparse.ArgumentParser] = []
    seen: set[int] = set()
    for parser in subparsers.choices.values():
        if id(parser) in seen:
            continue
        seen.add(id(parser))
        unique.append(parser)
    return unique


def subcommand_help(topic: str) -> str:
    """Return argparse's option help for *topic*, or an empty string."""
    parser = build_parser()
    action = next(
        (item for item in parser._actions if isinstance(item, argparse._SubParsersAction)),
        None,
    )
    if action is None:  # pragma: no cover - build_parser always adds one
        return ""
    subparser = action.choices.get(topic)
    if subparser is None:
        return ""
    return subparser.format_help()


def _non_negative_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid integer value: {value!r}") from None
    if number < 0:
        raise argparse.ArgumentTypeError("must be greater than or equal to 0")
    return number
