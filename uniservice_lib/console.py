"""Terminal rendering.

Everything the command line prints goes through :class:`Console`, which decides
— once — whether colour and Unicode box drawing are available and then renders
aligned tables, key/value blocks and status marks consistently.

The rule that keeps scripts working: **a table is only drawn on a terminal**.
When stdout is a pipe or a file, :func:`Console.table` degrades to the tab
separated contract scripts already depend on, and ``--json`` replaces both with
machine-readable output.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any, TextIO

__all__ = [
    "AUTO",
    "COLOR_CHOICES",
    "Column",
    "Console",
    "Mark",
    "strip_ansi",
    "visible_width",
]

AUTO = "auto"
ALWAYS = "always"
NEVER = "never"
COLOR_CHOICES = (AUTO, ALWAYS, NEVER)

#: SGR escape sequences, used to measure a styled string's real width.
_ANSI = re.compile(r"\x1b\[[0-9;]*m")

_STYLES = {
    "bold": "1",
    "dim": "2",
    "red": "31",
    "green": "32",
    "yellow": "33",
    "blue": "34",
    "magenta": "35",
    "cyan": "36",
    "grey": "90",
}

#: Status marks, with an ASCII fallback for terminals that cannot render them.
_UNICODE_MARKS = {"ok": "✔", "fail": "✘", "info": "•", "arrow": "→"}
_ASCII_MARKS = {"ok": "v", "fail": "x", "info": "-", "arrow": "->"}


class Mark:
    """The status marks, kept in a class so both alphabets are addressable."""

    OK = "ok"
    FAIL = "fail"
    INFO = "info"
    ARROW = "arrow"


def strip_ansi(text: str) -> str:
    """Return *text* without its SGR escape sequences."""
    return _ANSI.sub("", text)


def visible_width(text: str) -> int:
    """Return the printed width of *text*, ignoring colour escapes."""
    return len(strip_ansi(text))


@dataclass(frozen=True)
class Column:
    """One column of a :meth:`Console.table`."""

    title: str
    align: str = "left"
    style: str = ""

    @property
    def right(self) -> bool:
        return self.align == "right"


def _is_tty(stream: TextIO | None) -> bool:
    if stream is None:  # pragma: no cover - defensive
        return False
    try:
        return bool(stream.isatty())
    except (AttributeError, ValueError):  # pragma: no cover - closed stream
        return False


def _dumb_terminal() -> bool:
    return os.environ.get("TERM", "").lower() in ("dumb", "unknown")


def _encoding_is_utf8(stream: TextIO | None) -> bool:
    encoding = getattr(stream, "encoding", None) or ""
    return "utf" in encoding.lower()


class Console:
    """Render output for one invocation.

    Args:
        stdout: Where normal output goes.  Defaults to :data:`sys.stdout`.
        stderr: Where diagnostics go.  Defaults to :data:`sys.stderr`.
        color: ``auto`` (a terminal, and ``NO_COLOR`` unset), ``always`` or
            ``never``.
        unicode: Whether box drawing and status marks may use Unicode.
        quiet: Suppress everything except errors and explicitly requested data.
        json_mode: Emit JSON documents instead of tables.
        table: Draw a table even when stdout is not a terminal, which is what
            ``--table`` asks for (``uniservice list --table | less``).
    """

    def __init__(
        self,
        *,
        stdout: TextIO | None = None,
        stderr: TextIO | None = None,
        color: str = AUTO,
        unicode: bool = True,
        quiet: bool = False,
        json_mode: bool = False,
        table: bool = False,
    ) -> None:
        self.stdout = stdout if stdout is not None else sys.stdout
        self.stderr = stderr if stderr is not None else sys.stderr
        self.quiet = quiet
        self.json_mode = json_mode
        self._table = table
        self.color = self._resolve_color(color)
        # Box drawing and status marks need a UTF-8 capable stdout; a Windows
        # console on a legacy code page gets the ASCII alphabet instead.
        self.unicode = unicode and _encoding_is_utf8(self.stdout)
        self._marks = _UNICODE_MARKS if self.unicode else _ASCII_MARKS

    # ------------------------------------------------------------------ setup
    def _resolve_color(self, choice: str) -> bool:
        if choice == ALWAYS:
            return True
        if choice == NEVER:
            return False
        if os.environ.get("NO_COLOR"):
            return False
        if _dumb_terminal():
            return False
        return _is_tty(self.stdout)

    @property
    def is_terminal(self) -> bool:
        """Whether a table may be drawn instead of the machine-readable form.

        True on a terminal, or when ``--table`` asked for one explicitly, so
        that ``uniservice list --table | less`` keeps the human rendering.
        """
        return (self._table or _is_tty(self.stdout)) and not self.json_mode

    def mark(self, name: str) -> str:
        """Return the status mark called *name* for this terminal."""
        return self._marks[name]

    def style(self, text: str, *styles: str) -> str:
        """Wrap *text* in the given SGR styles when colour is enabled."""
        codes = [_STYLES[style] for style in styles if style in _STYLES]
        if not self.color or not codes:
            return text
        return f"\x1b[{';'.join(codes)}m{text}\x1b[0m"

    # ---------------------------------------------------------------- streams
    def out(self, text: str = "") -> None:
        """Print *text* to stdout."""
        print(text, file=self.stdout)

    def flush(self) -> None:
        """Flush both streams.

        Called before handing the terminal to a native tool: our own output is
        buffered by Python while the child writes straight to the file
        descriptor, so without this the header of ``status NAME`` can appear
        *after* ``systemctl``'s output when stdout is a pipe.
        """
        for stream in (self.stdout, self.stderr):
            with contextlib.suppress(OSError, ValueError):  # pragma: no cover - already closed
                stream.flush()

    def raw(self, text: str) -> None:
        """Write *text* to stdout exactly as given (native tool output)."""
        self.stdout.write(text)
        if not text.endswith("\n"):
            self.stdout.write("\n")
        self.stdout.flush()

    def err(self, text: str = "") -> None:
        """Print *text* to stderr."""
        print(text, file=self.stderr)

    def error(self, text: str) -> None:
        """Report a failure: red ``✘`` on stderr, never suppressed."""
        self.err(f"{self.style(self.mark(Mark.FAIL), 'red')} {text}")

    def success(self, text: str) -> None:
        """Report a completed action on stdout (suppressed by ``--quiet``)."""
        if self.quiet:
            return
        self.out(f"{self.style(self.mark(Mark.OK), 'green')} {text}")

    def warn(self, text: str) -> None:
        """Report something the user should notice but that is not a failure."""
        if self.quiet:
            return
        self.err(f"{self.style(self.mark(Mark.INFO), 'yellow')} {text}")

    def note(self, text: str) -> None:
        """Print a dim aside on stderr (suppressed by ``--quiet``)."""
        if self.quiet:
            return
        self.err(self.style(text, "dim"))

    def hint(self, text: str) -> None:
        """Print a dim aside on stdout, next to the data it belongs to."""
        if self.quiet:
            return
        self.out(self.style(text, "dim"))

    def heading(self, text: str) -> None:
        """Print a bold title line."""
        if self.quiet:
            return
        self.out(self.style(text, "bold"))

    def check(
        self,
        label: str,
        ok: bool,
        detail: str,
        *,
        hint: str = "",
        fatal: bool = True,
        width: int = 20,
    ) -> None:
        """Print one ``doctor`` line: a mark, a label, then the finding.

        A failing check that is not ``fatal`` is only a warning: the machine
        works, it is merely not configured the way we would prefer.
        """
        if self.quiet and ok:
            return
        mark = self.mark(Mark.OK if ok else (Mark.FAIL if fatal else Mark.INFO))
        colour = "green" if ok else ("red" if fatal else "yellow")
        self.out(f"  {self.style(mark, colour)} {label.ljust(width)} {detail}")
        if not ok and hint:
            self.out(f"    {self.style(f'hint: {hint}', 'dim')}")

    # ----------------------------------------------------------------- blocks
    def fields(self, pairs: Sequence[tuple[str, str]], *, indent: str = "  ") -> None:
        """Print an aligned ``key   value`` block."""
        if self.quiet or not pairs:
            return
        width = max(len(key) for key, _ in pairs)
        for key, value in pairs:
            self.out(f"{indent}{self.style(key.ljust(width), 'dim')}  {value}")

    def table(self, columns: Sequence[Column], rows: Iterable[Sequence[str]]) -> None:
        """Draw an aligned table, or the tab separated equivalent when piped.

        Args:
            columns: The header cells, each with its alignment and style.
            rows: Already-rendered cells.  Cells may contain colour escapes;
                alignment measures their visible width.
        """
        materialized = [list(row) for row in rows]
        if not self.is_terminal:
            self._write_tsv(columns, materialized)
            return
        if not materialized:
            return

        widths = [visible_width(column.title) for column in columns]
        for row in materialized:
            for index, cell in enumerate(row):
                widths[index] = max(widths[index], visible_width(cell))

        header = "  ".join(
            self.style(column.title.ljust(widths[index]), "bold") for index, column in enumerate(columns)
        )
        self.out(header.rstrip())
        rule = "─" if self.unicode else "-"
        width = min(sum(widths) + 2 * (len(widths) - 1), shutil.get_terminal_size((80, 24)).columns - 1)
        self.out(self.style(rule * width, "dim"))
        for row in materialized:
            cells = []
            for index, cell in enumerate(row):
                pad = widths[index] - visible_width(cell)
                cells.append((" " * pad + cell) if columns[index].right else (cell + " " * pad))
            self.out("  ".join(cells).rstrip())

    def _write_tsv(self, columns: Sequence[Column], rows: Sequence[Sequence[str]]) -> None:
        """The script-facing form: tabs, no styling, header first."""
        self.out("\t".join(strip_ansi(column.title) for column in columns))
        for row in rows:
            self.out("\t".join(strip_ansi(cell) for cell in row))

    # ------------------------------------------------------------------- json
    def emit_json(self, payload: Any) -> None:
        """Print *payload* as one JSON document on stdout."""
        self.out(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=False))
