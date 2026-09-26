"""Tests for the display layer.

The rules that matter: a table is only drawn for a human, the machine-readable
form is byte-stable, colour is opt-in and ``NO_COLOR`` always wins.
"""

from __future__ import annotations

import io
import json

import pytest

from tests.conftest import TtyStream
from uniservice_lib.console import (
    ALWAYS,
    NEVER,
    Column,
    Console,
    strip_ansi,
    visible_width,
)

pytestmark = pytest.mark.usefixtures("clean_logger")


@pytest.fixture(autouse=True)
def colour_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Neutralise the CI/sandbox environment so colour rules are testable."""
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")


def make_console(**kwargs: object) -> tuple[Console, io.StringIO, io.StringIO]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    console = Console(stdout=stdout, stderr=stderr, **kwargs)  # type: ignore[arg-type]
    return console, stdout, stderr


# --------------------------------------------------------------------------- width


def test_strip_ansi_removes_colour_only() -> None:
    assert strip_ansi("\x1b[1mNAME\x1b[0m") == "NAME"
    assert strip_ansi("plain") == "plain"


def test_visible_width_ignores_colour() -> None:
    assert visible_width("\x1b[32myes\x1b[0m") == 3


# ------------------------------------------------------------------- colour rules


def test_colour_is_off_when_piped() -> None:
    console, _, _ = make_console(color="auto")
    assert console.color is False
    assert console.style("x", "red") == "x"


def test_colour_is_on_for_a_terminal() -> None:
    console = Console(stdout=TtyStream(), stderr=io.StringIO(), color="auto")
    assert console.color is True
    assert console.style("x", "red") == "\x1b[31mx\x1b[0m"


def test_no_color_wins_over_a_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    console = Console(stdout=TtyStream(), stderr=io.StringIO(), color="auto")
    assert console.color is False


def test_a_dumb_terminal_has_no_colour(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("TERM", "dumb")
    console = Console(stdout=TtyStream(), stderr=io.StringIO(), color="auto")
    assert console.color is False


def test_always_forces_colour_down_a_pipe() -> None:
    console, _, _ = make_console(color=ALWAYS)
    assert console.color is True
    assert console.style("x", "red") == "\x1b[31mx\x1b[0m"


def test_never_disables_colour_on_a_terminal() -> None:
    console = Console(stdout=TtyStream(), stderr=io.StringIO(), color=NEVER)
    assert console.color is False


# ------------------------------------------------------------------- table rules


def test_a_pipe_gets_the_tab_separated_contract() -> None:
    console, stdout, _ = make_console(color=NEVER)
    console.table((Column("NAME"), Column("ENABLED"), Column("RUNNING")), [("demo", "yes", "yes")])
    assert stdout.getvalue() == "NAME\tENABLED\tRUNNING\ndemo\tyes\tyes\n"


def test_tsv_cells_are_unstyled() -> None:
    console, stdout, _ = make_console(color=ALWAYS)
    styled = console.style("yes", "green")
    console.table((Column("ENABLED"),), [(styled,)])
    assert stdout.getvalue() == "ENABLED\nyes\n"
    assert "\x1b" not in stdout.getvalue()


def test_a_terminal_gets_an_aligned_table() -> None:
    console = Console(stdout=TtyStream(), stderr=io.StringIO(), color=NEVER)
    console.table(
        (Column("NAME"), Column("COUNT", align="right")),
        [("demo", "1"), ("a-much-longer-name", "22")],
    )
    lines = console.stdout.getvalue().splitlines()
    name_width = len("a-much-longer-name")
    count_width = len("COUNT")
    assert lines[0] == "NAME".ljust(name_width) + "  " + "COUNT"
    assert lines[1] == "─" * (name_width + 2 + count_width)
    assert lines[2] == "demo".ljust(name_width) + "  " + "1".rjust(count_width)
    assert lines[3] == "a-much-longer-name" + "  " + "22".rjust(count_width)


def test_table_alignment_ignores_colour_escapes() -> None:
    console = Console(stdout=TtyStream(), stderr=io.StringIO(), color=ALWAYS)
    console.table((Column("A"), Column("B")), [(console.style("yes", "green"), "x")])
    lines = console.stdout.getvalue().splitlines()
    # "yes" is three visible characters, so the second column starts at index 5.
    assert strip_ansi(lines[2]).split()[0] == "yes"
    assert strip_ansi(lines[2]).index("x") == 5


def test_an_ascii_terminal_gets_ascii_rules_and_marks() -> None:
    stream = TtyStream()
    stream.encoding = "ascii"
    console = Console(stdout=stream, stderr=io.StringIO(), color=NEVER)
    assert console.unicode is False
    assert console.mark("ok") == "v"
    console.table((Column("A"),), [("1",)])
    assert "-" in stream.getvalue()


# ------------------------------------------------------------------ json output


def test_table_can_be_forced_down_a_pipe() -> None:
    console, stdout, _ = make_console(color=NEVER, table=True)
    assert console.is_terminal is True
    console.table((Column("NAME"),), [("demo",)])
    assert "\t" not in stdout.getvalue()


def test_emit_json_is_one_document() -> None:
    console, stdout, _ = make_console()
    console.emit_json([{"name": "demo", "enabled": True}])
    assert json.loads(stdout.getvalue()) == [{"name": "demo", "enabled": True}]


def test_json_mode_never_draws_a_table() -> None:
    console = Console(stdout=TtyStream(), stderr=io.StringIO(), json_mode=True)
    assert console.is_terminal is False


# ------------------------------------------------------------------- marks etc.


def test_success_and_error_use_marks_and_streams() -> None:
    console, stdout, stderr = make_console(color=NEVER)
    console.success("done")
    console.error("broken")
    assert stdout.getvalue() == "v done\n" if not console.unicode else "✔ done\n"
    assert "broken" in stderr.getvalue()


def test_quiet_suppresses_everything_but_errors() -> None:
    console, stdout, stderr = make_console(color=NEVER, quiet=True)
    console.success("done")
    console.warn("careful")
    console.hint("aside")
    console.error("broken")
    assert stdout.getvalue() == ""
    assert "careful" not in stderr.getvalue()
    assert "broken" in stderr.getvalue()


def test_fields_align_on_the_longest_key() -> None:
    console, stdout, _ = make_console(color=NEVER)
    console.fields([("a", "1"), ("longer", "2")])
    lines = stdout.getvalue().splitlines()
    assert lines[0] == "  a       1"
    assert lines[1] == "  longer  2"


def test_check_marks_a_failure_and_prints_the_hint() -> None:
    console, stdout, _ = make_console(color=NEVER)
    console.check("systemctl", False, "not found", hint="install systemd", width=10)
    out = stdout.getvalue()
    assert "not found" in out
    assert "hint: install systemd" in out


def test_check_width_is_honoured() -> None:
    console, stdout, _ = make_console(color=NEVER)
    console.check("a", True, "detail", width=8)
    # two spaces, the mark, a space, the padded label, a space
    assert stdout.getvalue().splitlines()[0].index("detail") == 13
