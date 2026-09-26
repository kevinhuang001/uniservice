"""Tests for ``uniservice self``."""

from __future__ import annotations

import io
import json

import pytest

from tests.test_installation import make_installation
from uniservice_lib.commands import Context, selfcmd
from uniservice_lib.console import Console
from uniservice_lib.exitcodes import OK
from uniservice_lib.scope import Scope

pytestmark = pytest.mark.usefixtures("clean_logger")


def make_context(*, json_mode: bool = False) -> tuple[Context, io.StringIO, io.StringIO]:
    stdout, stderr = io.StringIO(), io.StringIO()
    console = Console(stdout=stdout, stderr=stderr, color="never", json_mode=json_mode)
    return Context(console=console, scope=Scope("user")), stdout, stderr


def test_info_describes_a_recorded_installation(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    installation = make_installation(tmp_path)
    monkeypatch.setattr(selfcmd, "find_installation", lambda: installation)

    context, stdout, _ = make_context()
    assert selfcmd.cmd_info(context, object()) == OK

    out = stdout.getvalue()
    assert "uniservice 1.3.0 · binary" in out
    assert str(installation.prefix) in out
    assert str(installation.manifest) in out
    assert str(installation.command) in out


def test_info_json(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    installation = make_installation(tmp_path)
    monkeypatch.setattr(selfcmd, "find_installation", lambda: installation)

    context, stdout, _ = make_context(json_mode=True)
    assert selfcmd.cmd_info(context, object()) == OK

    payload = json.loads(stdout.getvalue())
    assert payload["kind"] == "binary"
    assert payload["version"] == "1.3.0"
    assert payload["prefix"] == str(installation.prefix)


def test_info_reports_an_unmanaged_copy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(selfcmd, "find_installation", lambda: None)

    context, _, stderr = make_context()
    assert selfcmd.cmd_info(context, object()) == OK

    assert "not installed by install.sh" in stderr.getvalue()


def test_info_json_for_an_unmanaged_copy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(selfcmd, "find_installation", lambda: None)

    context, stdout, _ = make_context(json_mode=True)
    assert selfcmd.cmd_info(context, object()) == OK

    assert json.loads(stdout.getvalue())["managed"] is False


def test_uninstall_removes_the_recorded_files(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    installation = make_installation(tmp_path)
    monkeypatch.setattr(selfcmd, "find_installation", lambda: installation)

    context, stdout, _ = make_context()
    assert selfcmd.cmd_uninstall(context, object()) == OK

    assert not installation.command.exists()
    assert not installation.manifest.exists()
    assert "removed uniservice 1.3.0" in stdout.getvalue()


def test_uninstall_dry_run_changes_nothing(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    installation = make_installation(tmp_path)
    monkeypatch.setattr(selfcmd, "find_installation", lambda: installation)

    context, stdout, _ = make_context()
    args = type("Args", (), {"dry_run": True})()
    assert selfcmd.cmd_uninstall(context, args) == OK

    assert installation.command.exists()
    assert "would remove" in stdout.getvalue()


def test_uninstall_json(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    installation = make_installation(tmp_path)
    monkeypatch.setattr(selfcmd, "find_installation", lambda: installation)

    context, stdout, _ = make_context(json_mode=True)
    assert selfcmd.cmd_uninstall(context, object()) == OK

    payload = json.loads(stdout.getvalue())
    assert payload["dry_run"] is False
    assert payload["removed"] == [str(installation.command)]


def test_uninstall_explains_how_to_remove_an_unmanaged_copy(monkeypatch: pytest.MonkeyPatch) -> None:
    from uniservice_lib.errors import UniserviceError

    monkeypatch.setattr(selfcmd, "find_installation", lambda: None)

    context, _, _ = make_context()
    with pytest.raises(UniserviceError, match="pipx uninstall uniservice"):
        selfcmd.cmd_uninstall(context, object())
