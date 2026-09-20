"""Tests for the scope model."""

from __future__ import annotations

import os

import pytest

from uniservice_lib.scope import SYSTEM, USER, Scope


def test_scope_rejects_unknown_values() -> None:
    with pytest.raises(ValueError):
        Scope("machine")


def test_is_system_and_is_user() -> None:
    assert Scope(SYSTEM).is_system is True
    assert Scope(SYSTEM).is_user is False
    assert Scope(USER).is_user is True
    assert Scope(USER).is_system is False


def test_from_env_returns_system_for_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("uniservice_lib.scope.is_root_unix", lambda: True)
    monkeypatch.setattr(os, "name", "posix")
    assert Scope.from_env() == Scope(SYSTEM)


def test_from_env_returns_user_for_regular_user(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("uniservice_lib.scope.is_root_unix", lambda: False)
    monkeypatch.setattr(os, "name", "posix")
    assert Scope.from_env() == Scope(USER)


def test_from_env_returns_system_on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("uniservice_lib.scope.is_root_unix", lambda: False)
    monkeypatch.setattr(os, "name", "nt")
    assert Scope.from_env() == Scope(SYSTEM)
