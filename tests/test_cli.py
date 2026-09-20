"""Tests for the command line layer."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tests.conftest import FakeBackend
from uniservice_lib import cli
from uniservice_lib.backends.base import ServiceInfo
from uniservice_lib.errors import UniserviceError
from uniservice_lib.scope import Scope

pytestmark = pytest.mark.usefixtures("clean_logger")


@pytest.fixture
def install_backend(monkeypatch: pytest.MonkeyPatch):
    """Return a factory that installs a :class:`FakeBackend` in the CLI."""

    def install(*, exists: bool = True, rows: list[ServiceInfo] | None = None) -> FakeBackend:
        backend = FakeBackend(exists=exists, rows=rows or [])
        monkeypatch.setattr(cli, "get_backend", lambda scope: backend)
        return backend

    return install


# ---------------------------------------------------------------------------
# parse_add_argv
# ---------------------------------------------------------------------------


def test_parse_add_argv_with_separator() -> None:
    request = cli.parse_add_argv(["demo", "--workdir", "/tmp", "--", "python3", "-m", "http.server"])
    assert request.name == "demo"
    assert request.workdir == "/tmp"
    assert request.command_parts == ("python3", "-m", "http.server")


def test_parse_add_argv_without_workdir() -> None:
    request = cli.parse_add_argv(["demo", "--", "/usr/bin/true"])
    assert request.workdir == ""
    assert request.command_parts == ("/usr/bin/true",)


def test_parse_add_argv_without_separator() -> None:
    request = cli.parse_add_argv(["demo", "python3", "-V"])
    assert request.command_parts == ("python3", "-V")


def test_parse_add_argv_strips_padding() -> None:
    assert cli.parse_add_argv(["  demo  ", "--", "true"]).name == "demo"


@pytest.mark.parametrize("argv", [[], ["--"], ["--workdir", "/tmp", "--", "true"]])
def test_parse_add_argv_requires_a_name(argv: list[str]) -> None:
    with pytest.raises(UniserviceError):
        cli.parse_add_argv(argv)


def test_parse_add_argv_requires_a_workdir_value() -> None:
    with pytest.raises(UniserviceError, match="Missing value for --workdir"):
        cli.parse_add_argv(["demo", "--workdir"])


def test_parse_add_argv_rejects_unknown_options() -> None:
    with pytest.raises(UniserviceError, match="Unknown option"):
        cli.parse_add_argv(["demo", "--verbose", "--", "true"])


@pytest.mark.parametrize("name", ["bad/name", "bad\\name", "bad\tname"])
def test_parse_add_argv_rejects_unsafe_names(name: str) -> None:
    with pytest.raises(UniserviceError):
        cli.parse_add_argv([name, "--", "true"])


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [(True, "yes"), (False, "no"), (None, "?")],
)
def test_format_tristate(value: bool | None, expected: str) -> None:
    assert cli.format_tristate(value) is expected


def test_sanitize_field_replaces_control_characters() -> None:
    assert cli.sanitize_field("a\tb\nc\rd") == "a b c d"


def test_render_list_sorts_case_insensitively() -> None:
    rows = [
        ServiceInfo("zeta", True, True),
        ServiceInfo("Alpha", False, None),
        ServiceInfo("beta", None, False),
    ]
    assert cli.render_list(rows) == [
        "NAME\tENABLED\tRUNNING",
        "Alpha\tno\t?",
        "beta\t?\tno",
        "zeta\tyes\tyes",
    ]


def test_render_list_drops_duplicates_and_empty_names() -> None:
    rows = [
        ServiceInfo("demo", True, True),
        ServiceInfo("demo", False, False),
        ServiceInfo("   ", True, True),
    ]
    assert cli.render_list(rows) == ["NAME\tENABLED\tRUNNING", "demo\tyes\tyes"]


def test_render_list_keeps_the_tsv_shape_for_hostile_names() -> None:
    rows = [ServiceInfo("evil\tname\nhere", True, False)]
    lines = cli.render_list(rows)
    assert lines[1] == "evil name here\tyes\tno"


def test_render_list_without_rows_prints_only_the_header() -> None:
    assert cli.render_list([]) == ["NAME\tENABLED\tRUNNING"]


# ---------------------------------------------------------------------------
# ensure_scope_allowed
# ---------------------------------------------------------------------------


def test_ensure_scope_allowed_lets_list_run_unelevated_on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression: list used to demand administrator rights on Windows."""
    monkeypatch.setattr(cli, "platform", lambda: "win")
    monkeypatch.setattr(cli, "is_admin_windows", lambda: False)
    cli.ensure_scope_allowed(Scope("system"), command="list")


def test_ensure_scope_allowed_rejects_mutating_commands_unelevated_on_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli, "platform", lambda: "win")
    monkeypatch.setattr(cli, "is_admin_windows", lambda: False)
    with pytest.raises(UniserviceError):
        cli.ensure_scope_allowed(Scope("system"), command="start")


def test_ensure_scope_allowed_rejects_system_scope_without_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "platform", lambda: "linux")
    monkeypatch.setattr(cli, "is_root_unix", lambda: False)
    with pytest.raises(UniserviceError, match="Permission denied"):
        cli.ensure_scope_allowed(Scope("system"), command="list")


def test_ensure_scope_allowed_accepts_user_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "platform", lambda: "linux")
    monkeypatch.setattr(cli, "is_root_unix", lambda: False)
    cli.ensure_scope_allowed(Scope("user"), command="list")


# ---------------------------------------------------------------------------
# main dispatch
# ---------------------------------------------------------------------------


def test_main_list_prints_the_table(
    install_backend,
    cli_privileges: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    install_backend(rows=[ServiceInfo("demo", True, True), ServiceInfo("idle", False, None)])

    assert cli.main(["list"]) == 0

    assert capsys.readouterr().out.splitlines() == [
        "NAME\tENABLED\tRUNNING",
        "demo\tyes\tyes",
        "idle\tno\t?",
    ]


def test_main_list_reports_backend_failures(
    monkeypatch: pytest.MonkeyPatch,
    cli_privileges: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class FailingBackend(FakeBackend):
        def list_info(self) -> list[ServiceInfo]:
            raise UniserviceError("query failed")

    monkeypatch.setattr(cli, "get_backend", lambda scope: FailingBackend())

    assert cli.main(["list"]) == 1
    assert "FAIL: query failed" in capsys.readouterr().err


def test_main_maps_called_process_error_to_its_exit_code(
    monkeypatch: pytest.MonkeyPatch,
    cli_privileges: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class FailingBackend(FakeBackend):
        def list_info(self) -> list[ServiceInfo]:
            raise subprocess.CalledProcessError(3, ["systemctl", "list"])

    monkeypatch.setattr(cli, "get_backend", lambda scope: FailingBackend())

    assert cli.main(["list"]) == 3
    assert "FAIL: command failed (3): systemctl list" in capsys.readouterr().err


def test_main_requires_a_subcommand() -> None:
    with pytest.raises(SystemExit) as excinfo:
        cli.main([])
    assert excinfo.value.code == 2


def test_main_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["--version"])
    assert excinfo.value.code == 0
    assert "uniservice" in capsys.readouterr().out


def test_main_rejects_negative_line_counts() -> None:
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["logs", "demo", "--lines", "-1"])
    assert excinfo.value.code == 2


def test_main_start_reports_success(
    install_backend,
    cli_privileges: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    backend = install_backend()

    assert cli.main(["start", "demo"]) == 0

    assert backend.actions() == ["exists", "start"]
    assert 'OK: started "demo"' in capsys.readouterr().out


def test_main_start_reports_a_missing_service(
    install_backend,
    cli_privileges: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    install_backend(exists=False)

    assert cli.main(["start", "demo"]) == 1
    assert 'FAIL: Service "demo" not found.' in capsys.readouterr().err


def test_main_remove_stops_disables_then_deletes(
    install_backend,
    cli_privileges: None,
) -> None:
    backend = install_backend()

    assert cli.main(["remove", "demo"]) == 0

    assert backend.actions() == ["exists", "stop", "disable", "remove"]


def test_main_cat_delegates(
    install_backend,
    cli_privileges: None,
) -> None:
    backend = install_backend()
    assert cli.main(["cat", "demo"]) == 0
    assert backend.actions() == ["exists", "cat"]


def test_main_logs_passes_lines_and_follow(
    install_backend,
    cli_privileges: None,
) -> None:
    backend = install_backend()

    assert cli.main(["logs", "demo", "--lines", "5", "--follow"]) == 0

    assert backend.calls[-1] == ("logs", ("demo",), {"lines": 5, "follow": True})


def test_main_logs_short_follow_flag(
    install_backend,
    cli_privileges: None,
) -> None:
    backend = install_backend()

    assert cli.main(["logs", "demo", "-f"]) == 0

    assert backend.calls[-1] == ("logs", ("demo",), {"lines": 200, "follow": True})


def test_main_add_creates_enables_and_starts(
    install_backend,
    cli_privileges: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    backend = install_backend(exists=False)

    assert cli.main(["add", "demo", "--workdir", "/tmp", "--", "/usr/bin/true"]) == 0

    assert backend.calls[0] == ("exists", ("demo",), {})
    action, args, _kwargs = backend.calls[1]
    assert action == "create"
    assert args[0] == "demo"
    assert args[1] == Path("/tmp")
    assert args[2] == ["/usr/bin/true"]
    assert backend.actions()[2:] == ["enable", "start"]
    assert 'OK: added "demo"' in capsys.readouterr().out


def test_main_add_defaults_to_the_current_directory(
    install_backend,
    cli_privileges: None,
) -> None:
    backend = install_backend(exists=False)

    assert cli.main(["add", "demo", "--", "/usr/bin/true"]) == 0

    assert backend.calls[1][1][1] == Path.cwd()


def test_main_add_refuses_to_overwrite_without_a_terminal(
    install_backend,
    cli_privileges: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    install_backend(exists=True)

    assert cli.main(["add", "demo", "--", "/usr/bin/true"]) == 1

    assert "already exists" in capsys.readouterr().err


def test_main_add_requires_a_command(
    install_backend,
    cli_privileges: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    install_backend(exists=False)

    assert cli.main(["add", "demo", "--workdir", "/tmp"]) == 1
    assert "Missing COMMAND after --" in capsys.readouterr().err


def test_main_add_requires_a_name(
    install_backend,
    cli_privileges: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    install_backend(exists=False)

    assert cli.main(["add", "--", "/usr/bin/true"]) == 1
    assert "Missing NAME." in capsys.readouterr().err
