"""Tests for the pure naming/validation helpers."""

from __future__ import annotations

import pytest

from uniservice_lib.errors import InvalidServiceNameError
from uniservice_lib.naming import (
    macos_label,
    macos_plist_name,
    parse_macos_plist_name,
    parse_systemd_unit_name,
    parse_windows_task_name,
    systemd_unit_name,
    validate_service_name,
    windows_task_name,
)


@pytest.mark.parametrize("name", ["demo", "demo.v2", "my_app", "a-b-c", "UPPER"])
def test_systemd_unit_name_round_trip(name: str) -> None:
    assert parse_systemd_unit_name(systemd_unit_name(name)) == name


@pytest.mark.parametrize("filename", ["other.service", "uniservice-demo.timer", "uniservice-demo", "demo.service"])
def test_parse_systemd_unit_name_rejects_foreign_files(filename: str) -> None:
    assert parse_systemd_unit_name(filename) is None


def test_systemd_unit_name_keeps_dots_in_service_name() -> None:
    assert systemd_unit_name("my.app") == "uniservice-my.app.service"
    assert parse_systemd_unit_name("uniservice-my.app.service") == "my.app"


def test_parse_systemd_unit_name_rejects_empty_name() -> None:
    assert parse_systemd_unit_name("uniservice-.service") == ""


@pytest.mark.parametrize("name", ["demo", "demo.v2", "my_app"])
def test_macos_plist_name_round_trip(name: str) -> None:
    assert parse_macos_plist_name(macos_plist_name(name)) == name
    assert macos_label(name) == f"com.uniservice.{name}"


@pytest.mark.parametrize("filename", ["com.apple.foo.plist", "com.uniservice.demo.json", "demo.plist"])
def test_parse_macos_plist_name_rejects_foreign_files(filename: str) -> None:
    assert parse_macos_plist_name(filename) is None


@pytest.mark.parametrize("name", ["demo", "demo.v2"])
def test_windows_task_name_round_trip(name: str) -> None:
    assert parse_windows_task_name(windows_task_name(name)) == name


def test_parse_windows_task_name_handles_folders() -> None:
    assert parse_windows_task_name("\\uniservice-demo") == "demo"
    assert parse_windows_task_name("\\Folder\\uniservice-demo") == "demo"
    assert parse_windows_task_name("uniservice-demo") == "demo"


def test_parse_windows_task_name_rejects_foreign_tasks() -> None:
    assert parse_windows_task_name("\\Microsoft\\Windows\\Defrag") is None
    assert parse_windows_task_name("uniservice-") == ""


@pytest.mark.parametrize("name", ["demo", "demo.v2", "  padded  "])
def test_validate_service_name_accepts(name: str) -> None:
    assert validate_service_name(name) == name.strip()


@pytest.mark.parametrize(
    "name",
    ["", "   ", ".", "..", "a/b", "a\\b", "tab\there", "line\nbreak", "nul\x00byte", "-option", "--workdir"],
)
def test_validate_service_name_rejects(name: str) -> None:
    with pytest.raises(InvalidServiceNameError):
        validate_service_name(name)


def test_validate_service_name_rejects_overlong_names() -> None:
    with pytest.raises(InvalidServiceNameError):
        validate_service_name("x" * 201)
