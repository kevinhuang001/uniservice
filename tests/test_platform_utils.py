"""Tests for backend selection and platform helpers."""

from __future__ import annotations

import os
import sys

import pytest

from uniservice_lib import platform_utils
from uniservice_lib.backends import get_backend
from uniservice_lib.backends.linux import LinuxBackend
from uniservice_lib.backends.macos import MacOSBackend
from uniservice_lib.backends.windows import WindowsBackend
from uniservice_lib.errors import UnsupportedPlatformError
from uniservice_lib.scope import Scope


@pytest.mark.parametrize(
    ("name", "expected_type"),
    [("linux", LinuxBackend), ("mac", MacOSBackend), ("win", WindowsBackend)],
)
def test_get_backend_selects_by_platform(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    expected_type: type,
) -> None:
    monkeypatch.setattr("uniservice_lib.backends.platform", lambda: name)
    assert isinstance(get_backend(Scope("user")), expected_type)


def test_get_backend_rejects_unsupported_platforms(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("uniservice_lib.backends.platform", lambda: "unsupported")
    with pytest.raises(UnsupportedPlatformError):
        get_backend(Scope("user"))


@pytest.mark.parametrize(
    ("sys_platform", "os_name", "expected"),
    [
        ("linux", "posix", "linux"),
        ("linux2", "posix", "linux"),
        ("darwin", "posix", "mac"),
        ("win32", "nt", "win"),
        ("freebsd13", "posix", "unsupported"),
    ],
)
def test_platform_mapping(
    monkeypatch: pytest.MonkeyPatch,
    sys_platform: str,
    os_name: str,
    expected: str,
) -> None:
    monkeypatch.setattr(sys, "platform", sys_platform)
    monkeypatch.setattr(os, "name", os_name)
    assert platform_utils.platform() == expected


def test_is_admin_windows_is_false_off_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "name", "posix")
    assert platform_utils.is_admin_windows() is False


def test_sudo_target_uid_parses_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "name", "posix")
    monkeypatch.setenv("SUDO_UID", "1000")
    assert platform_utils.sudo_target_uid() == 1000


@pytest.mark.parametrize("value", ["", "not-a-number"])
def test_sudo_target_uid_ignores_invalid_values(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setattr(os, "name", "posix")
    monkeypatch.setenv("SUDO_UID", value)
    assert platform_utils.sudo_target_uid() is None


def test_sudo_target_uid_is_none_on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setenv("SUDO_UID", "1000")
    assert platform_utils.sudo_target_uid() is None


@pytest.mark.skipif(os.name == "nt", reason="pwd is not available on Windows")
def test_user_home_for_uid_returns_the_current_home() -> None:
    assert platform_utils.user_home_for_uid(os.getuid()).exists()


def test_win_cmdline_split_is_rejected_off_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "name", "posix")
    with pytest.raises(RuntimeError):
        platform_utils.win_cmdline_split("a b")
