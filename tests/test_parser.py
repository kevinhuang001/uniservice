"""Tests for the command tree and the help text."""

from __future__ import annotations

import argparse
import re

import pytest

from uniservice_lib.errors import UsageError
from uniservice_lib.parser import build_parser, subcommand_help, usage_text


def _subparser_action(parser: argparse.ArgumentParser) -> argparse._SubParsersAction:  # type: ignore[type-arg]
    action = next(item for item in parser._actions if isinstance(item, argparse._SubParsersAction))
    return action


def _all_names() -> set[str]:
    """Every command word the parser accepts, at any depth."""
    parser = build_parser()
    names: set[str] = set()
    for name, subparser in _subparser_action(parser).choices.items():
        names.add(name)
        nested = next(
            (item for item in subparser._actions if isinstance(item, argparse._SubParsersAction)),
            None,
        )
        if nested is not None:
            names.update(nested.choices)
    return names


def test_every_command_is_documented() -> None:
    """A command that is not in the help text does not exist as far as users go."""
    text = usage_text()
    for name in sorted(_all_names()):
        assert name in text, f"{name} is missing from the help text"


def test_every_documented_command_exists() -> None:
    from uniservice_lib.parser import COMMAND_GROUPS

    known = _all_names()
    for group, entries in COMMAND_GROUPS:
        for form, _summary in entries:
            head = form.split()[0]
            words = [word.strip() for word in re.split(r"[,|]", head) if word.strip()]
            for word in words:
                assert word in known, f"{group}: {word} is documented but not implemented"


def test_usage_lists_the_three_groups() -> None:
    text = usage_text()
    assert "service commands:" in text
    assert "installation:" in text
    assert "diagnostics:" in text


def test_usage_explains_the_scope_rule() -> None:
    text = usage_text()
    assert "sudo" in text
    assert "secure_path" in text


def test_global_flags_are_accepted_on_both_sides_of_the_command() -> None:
    parser = build_parser()
    before = parser.parse_args(["--color", "never", "list"])
    after = parser.parse_args(["list", "--color", "never"])
    assert before.color == "never"
    assert after.color == "never"


def test_a_global_flag_given_before_the_command_survives() -> None:
    """Regression: argparse's subparser defaults used to overwrite it."""
    parser = build_parser()
    args = parser.parse_args(["--json", "list"])
    assert args.json is True


def test_global_flags_reach_nested_subcommands() -> None:
    parser = build_parser()
    assert parser.parse_args(["self", "info", "--json"]).json is True
    assert parser.parse_args(["self", "--json", "info"]).json is True


def test_aliases_point_at_the_same_parser() -> None:
    action = _subparser_action(build_parser())
    assert action.choices["ls"] is action.choices["list"]
    assert action.choices["rm"] is action.choices["remove"]


def test_control_verbs_take_many_names() -> None:
    args = build_parser().parse_args(["restart", "a", "b", "c"])
    assert args.names == ["a", "b", "c"]


def test_add_absorbs_everything_after_the_command() -> None:
    args = build_parser().parse_args(["add", "demo", "--workdir", "/tmp", "--", "python3", "-m", "http.server"])
    assert args.argv == ["demo", "--workdir", "/tmp", "--", "python3", "-m", "http.server"]


def test_only_list_and_status_take_table() -> None:
    parser = build_parser()
    assert parser.parse_args(["list", "--table"]).table is True
    assert parser.parse_args(["status", "--table"]).table is True
    with pytest.raises(UsageError):
        parser.parse_args(["show", "demo", "--table"])


def test_no_command_is_allowed() -> None:
    """`uniservice --help` must parse; the dispatcher decides what a bare run means."""
    args = build_parser().parse_args(["--help"])
    assert args.command is None
    assert args.show_help is True


def test_unknown_commands_raise_a_usage_error() -> None:
    with pytest.raises(UsageError, match="invalid choice"):
        build_parser().parse_args(["frobnicate"])


def test_unknown_flags_raise_a_usage_error() -> None:
    with pytest.raises(UsageError, match="unrecognized arguments"):
        build_parser().parse_args(["list", "--nope"])


def test_subcommand_help_covers_topics() -> None:
    assert "uniservice add" in subcommand_help("add")
    assert subcommand_help("self") != ""
    assert subcommand_help("nope") == ""


def test_line_counts_must_be_non_negative() -> None:
    with pytest.raises(UsageError, match="greater than or equal to 0"):
        build_parser().parse_args(["logs", "demo", "--lines", "-1"])


def test_line_counts_must_be_numbers() -> None:
    with pytest.raises(UsageError, match="invalid integer value"):
        build_parser().parse_args(["logs", "demo", "--lines", "many"])
