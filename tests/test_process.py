"""Tests for the subprocess helpers."""

from __future__ import annotations

import subprocess

import pytest

from uniservice_lib.process import command_string, resolve_command_parts, run


def test_command_string_quotes_arguments() -> None:
    assert command_string(["/usr/bin/python3", "-m", "http.server", "8000"]) == "/usr/bin/python3 -m http.server 8000"
    assert command_string(["echo", "hello world"]) == "echo 'hello world'"
    assert command_string(["echo", "it's"]) == """echo 'it'"'"'s'"""


def test_resolve_command_parts_keeps_absolute_paths() -> None:
    parts = ["/usr/bin/python3", "-m", "http.server"]
    assert resolve_command_parts(parts) == parts


def test_resolve_command_parts_resolves_relative_executables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("uniservice_lib.process.shutil.which", lambda name: "/usr/bin/python3")
    assert resolve_command_parts(["python3", "-V"]) == ["/usr/bin/python3", "-V"]


def test_resolve_command_parts_keeps_unresolvable_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("uniservice_lib.process.shutil.which", lambda name: None)
    assert resolve_command_parts(["does-not-exist", "arg"]) == ["does-not-exist", "arg"]


def test_resolve_command_parts_handles_empty_input() -> None:
    assert resolve_command_parts([]) == []


def test_run_returns_completed_process(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="out", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = run(["echo", "hi"], capture=True)

    assert result.stdout == "out"
    assert captured["cmd"] == ["echo", "hi"]
    assert captured["kwargs"]["text"] is True  # type: ignore[index]
    assert captured["kwargs"]["capture_output"] is True  # type: ignore[index]


def test_run_quiet_discards_output(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured.update(kwargs)
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    run(["echo", "hi"], quiet=True)

    assert captured["stdout"] is subprocess.DEVNULL
    assert captured["stderr"] is subprocess.DEVNULL


def test_run_propagates_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.CalledProcessError(3, cmd)

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(subprocess.CalledProcessError):
        run(["false"])
