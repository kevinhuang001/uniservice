"""Tests for ``uniservice doctor`` and ``uniservice version``."""

from __future__ import annotations

import io
import json

import pytest

from tests.conftest import FakeBackend
from uniservice_lib.backends.base import Check
from uniservice_lib.commands import Context, diagnostics
from uniservice_lib.console import Console
from uniservice_lib.errors import UnsupportedPlatformError
from uniservice_lib.exitcodes import FAILURE, OK
from uniservice_lib.scope import Scope

pytestmark = pytest.mark.usefixtures("clean_logger")


class ProbeBackend(FakeBackend):
    """A backend whose doctor checks are supplied by the test."""

    def __init__(self, checks: list[Check]) -> None:
        super().__init__()
        self._checks = checks

    def checks(self) -> list[Check]:
        return list(self._checks)


def make_context(backend: object | None = None, *, json_mode: bool = False) -> tuple[Context, io.StringIO]:
    stdout = io.StringIO()
    console = Console(stdout=stdout, stderr=io.StringIO(), color="never", json_mode=json_mode)
    context = Context(console=console, scope=Scope("user"))
    if backend is not None:
        context._backend = backend
    return context, stdout


def run_doctor(checks: list[Check]) -> tuple[int, str]:
    context, stdout = make_context(ProbeBackend(checks))
    code = diagnostics.cmd_doctor(context, object())
    return code, stdout.getvalue()


# --------------------------------------------------------------------- core


def test_core_checks_cover_the_interpreter_and_platform() -> None:
    context, _ = make_context(ProbeBackend([]))
    labels = [check.label for check in diagnostics.core_checks(context)]
    assert labels[:3] == ["python", "platform", "privileges"]
    assert "installation" in labels
    assert "log file" in labels


def test_core_checks_pass_on_this_machine() -> None:
    context, _ = make_context(ProbeBackend([]))
    fatal = [check for check in diagnostics.core_checks(context) if check.fatal and not check.ok]
    assert fatal == []


def test_the_log_check_is_only_a_warning() -> None:
    """An unwritable log file degrades the diagnostics, it does not break uniservice."""
    context, _ = make_context(ProbeBackend([]))
    log = next(check for check in diagnostics.core_checks(context) if check.label == "log file")
    assert log.fatal is False
    assert log.detail.endswith("uniservice.log")


# ------------------------------------------------------------------- doctor


def test_doctor_reports_every_check() -> None:
    code, out = run_doctor([Check(label="systemctl", ok=True, detail="/usr/bin/systemctl")])
    assert code == OK
    assert "python" in out
    assert "systemctl" in out
    assert "all good" in out


def test_doctor_fails_on_a_fatal_check() -> None:
    code, out = run_doctor([Check(label="systemctl", ok=False, detail="not found", hint="install systemd")])
    assert code == FAILURE
    assert "1 problem(s) found" in out
    assert "hint: install systemd" in out


def test_doctor_ignores_a_non_fatal_check() -> None:
    code, out = run_doctor([Check(label="powershell", ok=False, detail="not found", fatal=False)])
    assert code == OK
    assert "all good" in out


def test_doctor_reports_a_platform_without_a_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(scope: Scope) -> object:
        raise UnsupportedPlatformError("Unsupported platform: aix")

    monkeypatch.setattr("uniservice_lib.commands.get_backend", explode)
    context, _ = make_context()
    code = diagnostics.cmd_doctor(context, object())
    assert code == FAILURE
    assert "aix" in context.console.stdout.getvalue()


def test_doctor_json_is_a_list_of_findings() -> None:
    context, stdout = make_context(ProbeBackend([Check(label="x", ok=True, detail="fine")]), json_mode=True)
    assert diagnostics.cmd_doctor(context, object()) == OK
    payload = json.loads(stdout.getvalue())
    assert {"label", "ok", "detail", "hint", "fatal"} <= set(payload[0])


def test_doctor_quiet_only_shows_problems() -> None:
    stdout = io.StringIO()
    console = Console(stdout=stdout, stderr=io.StringIO(), color="never", quiet=True)
    context = Context(console=console, scope=Scope("user"))
    context._backend = ProbeBackend([Check(label="x", ok=True, detail="fine")])
    assert diagnostics.cmd_doctor(context, object()) == OK
    assert stdout.getvalue() == ""


# ------------------------------------------------------------------ version


def test_version_reports_the_components() -> None:
    context, stdout = make_context()
    assert diagnostics.cmd_version(context, object()) == OK
    out = stdout.getvalue()
    assert out.startswith("uniservice ")
    assert "python" in out
    assert "platform" in out


def test_version_json() -> None:
    context, stdout = make_context(json_mode=True)
    assert diagnostics.cmd_version(context, object()) == OK
    payload = json.loads(stdout.getvalue())
    assert set(payload) == {"uniservice", "python", "executable", "platform", "scope", "install", "log"}
