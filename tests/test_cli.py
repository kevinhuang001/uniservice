"""Tests for the command line layer."""

from __future__ import annotations

import io
import subprocess

import pytest

from tests.conftest import FakeBackend
from uniservice_lib import cli
from uniservice_lib.backends.base import ServiceInfo
from uniservice_lib.commands import Context, service
from uniservice_lib.console import Console, strip_ansi
from uniservice_lib.errors import UniserviceError
from uniservice_lib.exitcodes import FAILURE, OK, USAGE
from uniservice_lib.scope import Scope

pytestmark = pytest.mark.usefixtures("clean_logger")


@pytest.fixture
def install_backend(monkeypatch: pytest.MonkeyPatch):
    """Return a factory that installs a :class:`FakeBackend` in the commands."""

    def install(*, exists: bool = True, rows: list[ServiceInfo] | None = None) -> FakeBackend:
        backend = FakeBackend(exists=exists, rows=rows or [])
        monkeypatch.setattr("uniservice_lib.commands.get_backend", lambda scope: backend)
        return backend

    return install


# ---------------------------------------------------------------------------
# parse_add_argv
# ---------------------------------------------------------------------------


def test_parse_add_argv_with_separator() -> None:
    request = service.parse_add_argv(["demo", "--workdir", "/tmp", "--", "python3", "-m", "http.server"])
    assert request.name == "demo"
    assert request.workdir == "/tmp"
    assert request.command_parts == ("python3", "-m", "http.server")


def test_parse_add_argv_without_workdir() -> None:
    request = service.parse_add_argv(["demo", "--", "/usr/bin/true"])
    assert request.workdir == ""
    assert request.command_parts == ("/usr/bin/true",)


def test_parse_add_argv_without_separator() -> None:
    request = service.parse_add_argv(["demo", "python3", "-V"])
    assert request.command_parts == ("python3", "-V")


def test_parse_add_argv_strips_padding() -> None:
    assert service.parse_add_argv(["  demo  ", "--", "true"]).name == "demo"


@pytest.mark.parametrize("argv", [[], ["--"], ["--workdir", "/tmp", "--", "true"]])
def test_parse_add_argv_requires_a_name(argv: list[str]) -> None:
    with pytest.raises(UniserviceError):
        service.parse_add_argv(argv)


@pytest.mark.parametrize("first", ["--", "-x", "-"])
def test_parse_add_argv_rejects_a_command_the_shell_would_misread(first: str) -> None:
    """`bash -lc '-- ...'` prints its usage on every restart, so refuse it."""
    with pytest.raises(UniserviceError, match="starts with"):
        service.parse_add_argv(["demo", "--workdir", "/tmp", "--", first, "python3", "-m", "http.server"])


def test_parse_add_argv_accepts_a_path_that_merely_starts_with_a_dot() -> None:
    request = service.parse_add_argv(["demo", "--", "./server", "--flag"])
    assert request.command_parts == ("./server", "--flag")


def test_parse_add_argv_requires_a_workdir_value() -> None:
    with pytest.raises(UniserviceError, match="Missing value for --workdir"):
        service.parse_add_argv(["demo", "--workdir"])


def test_parse_add_argv_rejects_unknown_options() -> None:
    with pytest.raises(UniserviceError, match="Unknown option"):
        service.parse_add_argv(["demo", "--verbose", "--", "true"])


@pytest.mark.parametrize("name", ["bad/name", "bad\\name", "bad\tname"])
def test_parse_add_argv_rejects_unsafe_names(name: str) -> None:
    with pytest.raises(UniserviceError):
        service.parse_add_argv([name, "--", "true"])


# ---------------------------------------------------------------------------
# rendering helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [(True, "yes"), (False, "no"), (None, "?")],
)
def test_format_tristate(value: bool | None, expected: str) -> None:
    assert service.format_tristate(value) is expected


def test_sanitize_field_replaces_control_characters() -> None:
    assert service.sanitize_field("a\tb\nc\rd") == "a b c d"


def test_normalize_rows_sorts_case_insensitively() -> None:
    rows = [
        ServiceInfo("zeta", True, True),
        ServiceInfo("Alpha", False, None),
        ServiceInfo("beta", None, False),
    ]
    assert [(row.name, row.enabled, row.running) for row in service.normalize_rows(rows)] == [
        ("Alpha", False, None),
        ("beta", None, False),
        ("zeta", True, True),
    ]


def test_normalize_rows_drops_duplicates_and_empty_names() -> None:
    rows = [
        ServiceInfo("demo", True, True),
        ServiceInfo("demo", False, False),
        ServiceInfo("   ", True, True),
    ]
    assert [row.name for row in service.normalize_rows(rows)] == ["demo"]


def test_normalize_rows_keeps_hostile_names_on_one_line() -> None:
    rows = [ServiceInfo("evil\tname\nhere", True, False)]
    assert service.normalize_rows(rows)[0].name == "evil name here"


def test_render_add_command_prefixes_sudo_for_the_system_scope() -> None:
    from uniservice_lib.backends.base import ServiceDefinition

    definition = ServiceDefinition(
        name="demo",
        scope="system",
        location="/etc/systemd/system/uniservice-demo.service",
        workdir="/srv/app",
        command_parts=("python3", "-m", "http.server"),
    )
    line = service.render_add_command(definition, command_line=lambda parts: " ".join(parts), windows=False)
    assert line == "sudo uniservice add demo --workdir /srv/app -- python3 -m http.server"


def test_render_add_command_prefers_the_raw_command_line() -> None:
    from uniservice_lib.backends.base import ServiceDefinition

    definition = ServiceDefinition(
        name="demo",
        scope="user",
        location="\\uniservice\\demo",
        workdir="",
        raw="cmd.exe /c foo",
    )
    rendered = service.render_add_command(definition, command_line=lambda parts: " ".join(parts))
    assert rendered.endswith("-- cmd.exe /c foo")


# ---------------------------------------------------------------------------
# Context.require
# ---------------------------------------------------------------------------


def _context(monkeypatch: pytest.MonkeyPatch) -> Context:
    return Context(console=Console(stdout=io.StringIO()), scope=Scope("user"))


def test_require_lets_list_run_unelevated_on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression: list used to demand administrator rights on Windows."""
    monkeypatch.setattr("uniservice_lib.commands.platform", lambda: "win")
    monkeypatch.setattr("uniservice_lib.commands.is_admin_windows", lambda: False)
    _context(monkeypatch).require("list")


def test_require_rejects_mutating_commands_unelevated_on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("uniservice_lib.commands.platform", lambda: "win")
    monkeypatch.setattr("uniservice_lib.commands.is_admin_windows", lambda: False)
    with pytest.raises(UniserviceError, match="admin"):
        _context(monkeypatch).require("start")


def test_require_rejects_system_scope_without_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("uniservice_lib.commands.platform", lambda: "linux")
    monkeypatch.setattr("uniservice_lib.commands.is_root_unix", lambda: False)
    context = Context(console=Console(stdout=io.StringIO()), scope=Scope("system"))
    with pytest.raises(UniserviceError, match="Permission denied"):
        context.require("list")


def test_require_accepts_user_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("uniservice_lib.commands.platform", lambda: "linux")
    monkeypatch.setattr("uniservice_lib.commands.is_root_unix", lambda: False)
    _context(monkeypatch).require("list")


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


def test_list_prints_tsv_when_piped(install_backend, cli_privileges: None, capsys: pytest.CaptureFixture[str]) -> None:
    install_backend(rows=[ServiceInfo("demo", True, True), ServiceInfo("idle", False, None)])

    assert cli.main(["list"]) == OK

    assert capsys.readouterr().out.splitlines() == [
        "NAME\tENABLED\tRUNNING",
        "demo\tyes\tyes",
        "idle\tno\t?",
    ]


def test_list_ls_alias(install_backend, cli_privileges: None, capsys: pytest.CaptureFixture[str]) -> None:
    install_backend(rows=[ServiceInfo("demo", True, True)])
    assert cli.main(["ls"]) == OK
    assert "demo\tyes\tyes" in capsys.readouterr().out


def test_list_json(install_backend, cli_privileges: None, host_scope: str, capsys: pytest.CaptureFixture[str]) -> None:
    install_backend(rows=[ServiceInfo("demo", True, None)])

    assert cli.main(["list", "--json"]) == OK

    import json

    assert json.loads(capsys.readouterr().out) == [
        {"name": "demo", "scope": host_scope, "enabled": True, "running": None}
    ]


def test_list_quiet_prints_only_names(
    install_backend, cli_privileges: None, capsys: pytest.CaptureFixture[str]
) -> None:
    install_backend(rows=[ServiceInfo("demo", True, True), ServiceInfo("api", False, False)])
    assert cli.main(["list", "--quiet"]) == OK
    assert capsys.readouterr().out.splitlines() == ["api", "demo"]


def test_list_on_a_terminal_draws_a_table(install_backend, cli_privileges: None, tty) -> None:
    install_backend(rows=[ServiceInfo("demo", True, False)])

    assert cli.main(["list"]) == OK

    out = tty.getvalue()
    assert "NAME" in out and "ENABLED" in out and "RUNNING" in out
    assert "─" in out  # the rule under the header
    assert "\t" not in out


def test_list_on_a_terminal_explains_an_empty_scope(
    install_backend, cli_privileges: None, host_scope: str, tty
) -> None:
    install_backend(rows=[])
    assert cli.main(["list"]) == OK
    assert f"no services in the {host_scope} scope yet" in tty.getvalue()


def test_list_reports_backend_failures(
    monkeypatch: pytest.MonkeyPatch, cli_privileges: None, capsys: pytest.CaptureFixture[str]
) -> None:
    class FailingBackend(FakeBackend):
        def list_info(self) -> list[ServiceInfo]:
            raise UniserviceError("query failed")

    monkeypatch.setattr("uniservice_lib.commands.get_backend", lambda scope: FailingBackend())

    assert cli.main(["list"]) == FAILURE
    assert "query failed" in capsys.readouterr().err


def test_called_process_error_maps_to_its_exit_code(
    monkeypatch: pytest.MonkeyPatch, cli_privileges: None, capsys: pytest.CaptureFixture[str]
) -> None:
    class FailingBackend(FakeBackend):
        def list_info(self) -> list[ServiceInfo]:
            raise subprocess.CalledProcessError(3, ["systemctl", "list"], stderr="Unit not found.\n")

    monkeypatch.setattr("uniservice_lib.commands.get_backend", lambda scope: FailingBackend())

    assert cli.main(["list"]) == 3
    err = capsys.readouterr().err
    assert "command failed (3): systemctl list" in err
    assert "Unit not found." in err


# ---------------------------------------------------------------------------
# lifecycle verbs
# ---------------------------------------------------------------------------


def test_start_reports_success(install_backend, cli_privileges: None, capsys: pytest.CaptureFixture[str]) -> None:
    backend = install_backend()

    assert cli.main(["start", "demo"]) == OK

    assert backend.actions() == ["exists", "start"]
    assert 'started "demo"' in capsys.readouterr().out


def test_start_reports_a_missing_service(
    install_backend, cli_privileges: None, capsys: pytest.CaptureFixture[str]
) -> None:
    install_backend(exists=False)

    assert cli.main(["start", "demo"]) == FAILURE

    assert 'Service "demo" not found.' in capsys.readouterr().err


def test_restart_uses_the_backend_verb(install_backend, cli_privileges: None) -> None:
    backend = install_backend()
    assert cli.main(["restart", "demo"]) == OK
    assert backend.actions() == ["exists", "restart"]


def test_remove_stops_disables_then_deletes(install_backend, cli_privileges: None) -> None:
    backend = install_backend()
    assert cli.main(["remove", "demo"]) == OK
    assert backend.actions() == ["exists", "stop", "disable", "remove"]


def test_remove_alias_rm(install_backend, cli_privileges: None) -> None:
    backend = install_backend()
    assert cli.main(["rm", "demo"]) == OK
    assert backend.actions() == ["exists", "stop", "disable", "remove"]


def test_multiple_names_are_applied_in_order(install_backend, cli_privileges: None) -> None:
    backend = install_backend()
    assert cli.main(["restart", "a", "b"]) == OK
    assert backend.actions() == ["exists", "restart", "exists", "restart"]


def test_multiple_names_report_a_summary_and_fail_if_any_failed(
    install_backend, cli_privileges: None, capsys: pytest.CaptureFixture[str]
) -> None:
    backend = install_backend()
    backend.exists_value = False

    assert cli.main(["start", "a", "b"]) == FAILURE

    err = capsys.readouterr().err
    assert err.count("not found") == 2
    assert 'started "a"' not in err


def test_partial_failure_still_reports_the_ones_that_worked(
    install_backend, cli_privileges: None, capsys: pytest.CaptureFixture[str]
) -> None:
    backend = install_backend()

    def exists(name: str) -> bool:
        return name != "b"

    backend.exists = exists  # type: ignore[method-assign]

    assert cli.main(["start", "a", "b"]) == FAILURE
    captured = capsys.readouterr()
    assert 'started "a"' in captured.out
    assert "1/2 started" in captured.out
    assert '"b"' in captured.err


# ---------------------------------------------------------------------------
# add / show
# ---------------------------------------------------------------------------


def test_add_creates_enables_and_starts(
    install_backend, cli_privileges: None, capsys: pytest.CaptureFixture[str]
) -> None:
    backend = install_backend(exists=False)

    assert cli.main(["add", "demo", "--workdir", "/tmp", "--", "/usr/bin/env", "true"]) == OK

    assert backend.actions() == ["exists", "create", "enable", "start", "definition"]
    assert 'added "demo"' in capsys.readouterr().out


def test_add_defaults_to_the_current_directory(
    install_backend, cli_privileges: None, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    backend = install_backend(exists=False)
    monkeypatch.chdir(tmp_path)

    assert cli.main(["add", "demo", "--", "/usr/bin/env", "true"]) == OK

    create = next(call for call in backend.calls if call[0] == "create")
    assert create[1][1] == tmp_path


def test_add_requires_a_name(cli_privileges: None, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["add"]) == FAILURE
    assert "Missing NAME" in capsys.readouterr().err


def test_add_requires_a_command(install_backend, cli_privileges: None, capsys: pytest.CaptureFixture[str]) -> None:
    install_backend(exists=False)
    assert cli.main(["add", "demo", "--workdir", "/tmp", "--"]) == FAILURE
    assert "Missing COMMAND" in capsys.readouterr().err


def test_add_refuses_to_overwrite_without_a_terminal(
    install_backend, cli_privileges: None, capsys: pytest.CaptureFixture[str]
) -> None:
    backend = install_backend(exists=True)

    assert cli.main(["add", "demo", "--", "/usr/bin/env", "true"]) == FAILURE

    assert "already exists" in capsys.readouterr().err
    assert "create" not in backend.actions()


def test_add_overwrites_after_confirmation(
    install_backend, cli_privileges: None, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    backend = install_backend(exists=True)
    monkeypatch.setattr("sys.stdin", io.StringIO("y\n"))
    monkeypatch.setattr("sys.stdin.isatty", lambda: True, raising=False)

    assert cli.main(["add", "demo", "--", "/usr/bin/env", "true"]) == OK

    assert backend.actions() == ["exists", "stop", "disable", "remove", "create", "enable", "start", "definition"]
    assert 'replaced "demo"' in capsys.readouterr().out


def test_show_prints_the_definition_and_the_recreate_line(
    install_backend, cli_privileges: None, host_scope: str, capsys: pytest.CaptureFixture[str]
) -> None:
    install_backend()

    assert cli.main(["show", "demo"]) == OK

    out = capsys.readouterr().out
    assert f"demo · {host_scope} scope" in out
    assert "location" in out
    assert "uniservice add demo --workdir /tmp -- /usr/bin/env true" in out


def test_show_reports_a_missing_service(monkeypatch: pytest.MonkeyPatch, cli_privileges: None) -> None:
    from uniservice_lib.errors import ServiceNotFoundError

    class MissingBackend(FakeBackend):
        def definition(self, name: str):
            raise ServiceNotFoundError(name)

    monkeypatch.setattr("uniservice_lib.commands.get_backend", lambda scope: MissingBackend())

    assert cli.main(["show", "demo"]) == FAILURE


def test_show_json(install_backend, cli_privileges: None, capsys: pytest.CaptureFixture[str]) -> None:
    install_backend()

    assert cli.main(["show", "demo", "--json"]) == OK

    import json

    payload = json.loads(capsys.readouterr().out)
    assert payload["name"] == "demo"
    # A system-scope service (everything on Windows) is prefixed with sudo.
    assert "uniservice add demo" in payload["recreate"]


# ---------------------------------------------------------------------------
# status / logs
# ---------------------------------------------------------------------------


def test_status_without_a_name_prints_an_overview(
    install_backend, cli_privileges: None, host_scope: str, capsys: pytest.CaptureFixture[str]
) -> None:
    install_backend(rows=[ServiceInfo("demo", True, True), ServiceInfo("api", True, False)])

    assert cli.main(["status"]) == OK

    out = capsys.readouterr().out
    assert f"{host_scope} scope" in out
    assert "demo\tyes\tyes" in out
    assert "2 service(s), 1 running" in out


def test_status_with_a_name_prints_a_header_then_the_native_output(
    install_backend, cli_privileges: None, host_scope: str, capsys: pytest.CaptureFixture[str]
) -> None:
    backend = install_backend(rows=[ServiceInfo("demo", True, True)])

    assert cli.main(["status", "demo"]) == OK

    out = capsys.readouterr().out
    assert f"demo · {host_scope} scope · yes (running) · yes (enabled)" in out
    assert backend.actions() == ["exists", "list_info", "status"]


def test_status_flushes_our_header_before_the_native_output(
    install_backend, cli_privileges: None, host_scope: str, tty, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: a buffered header used to surface after systemctl's output."""
    backend = install_backend(rows=[ServiceInfo("demo", True, True)])
    monkeypatch.setattr(backend, "status", lambda name: tty.write("native output\n"), raising=False)

    assert cli.main(["status", "demo"]) == OK

    # The console colours the heading, so compare the printable text.
    lines = [strip_ansi(line) for line in tty.getvalue().splitlines()]
    assert lines[0].startswith(f"demo · {host_scope} scope")
    assert "native output" in lines


def test_status_of_a_missing_service_fails(install_backend, cli_privileges: None) -> None:
    install_backend(exists=False)
    assert cli.main(["status", "demo"]) == FAILURE


def test_logs_passes_lines_and_follow(install_backend, cli_privileges: None) -> None:
    backend = install_backend()

    assert cli.main(["logs", "demo", "--lines", "10", "--follow"]) == OK

    assert backend.actions() == ["exists", "logs"]
    _action, args, kwargs = backend.calls[-1]
    assert args == ("demo",)
    assert kwargs == {"lines": 10, "follow": True}


def test_logs_accepts_the_short_flags(install_backend, cli_privileges: None) -> None:
    backend = install_backend()

    assert cli.main(["logs", "demo", "-n", "5", "-f"]) == OK

    assert backend.calls[-1][2] == {"lines": 5, "follow": True}


# ---------------------------------------------------------------------------
# diagnostics
# ---------------------------------------------------------------------------


def test_version_prints_the_components(cli_privileges: None, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["version"]) == OK
    out = capsys.readouterr().out
    assert "uniservice" in out
    assert "python" in out
    assert "platform" in out


def test_doctor_reports_every_check(cli_privileges: None, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["doctor"]) in (OK, FAILURE)
    out = capsys.readouterr().out
    assert "python" in out
    assert "platform" in out


def test_doctor_json(cli_privileges: None, capsys: pytest.CaptureFixture[str]) -> None:
    import json

    cli.main(["doctor", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert {item["label"] for item in payload} >= {"python", "platform", "privileges"}


# ---------------------------------------------------------------------------
# usage and errors
# ---------------------------------------------------------------------------


def test_no_arguments_prints_the_usage(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main([]) == USAGE
    assert "usage:" in capsys.readouterr().err


def test_help_prints_the_usage(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["--help"]) == OK
    assert "service commands" in capsys.readouterr().out


def test_help_with_a_topic_prints_that_command(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(["help", "add"]) == OK
    assert "add" in capsys.readouterr().out


def test_help_with_an_unknown_topic_is_a_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["help", "nope"]) == USAGE
    assert "unknown command" in capsys.readouterr().err


def test_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["--version"]) == OK
    assert "uniservice" in capsys.readouterr().out


def test_unknown_command_is_a_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["frobnicate"]) == USAGE
    assert "invalid choice" in capsys.readouterr().err


def test_unknown_flag_is_a_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["list", "--nope"]) == USAGE
    assert "unrecognized arguments" in capsys.readouterr().err


def test_negative_line_counts_are_rejected(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["logs", "demo", "--lines", "-1"]) == USAGE
    assert "greater than or equal to 0" in capsys.readouterr().err


def test_global_flags_work_before_and_after_the_command(
    install_backend, cli_privileges: None, capsys: pytest.CaptureFixture[str]
) -> None:
    install_backend(rows=[ServiceInfo("demo", True, True)])

    assert cli.main(["--json", "list"]) == OK
    before = capsys.readouterr().out
    assert cli.main(["list", "--json"]) == OK
    after = capsys.readouterr().out
    assert before == after


def test_unexpected_errors_never_traceback(
    monkeypatch: pytest.MonkeyPatch, cli_privileges: None, capsys: pytest.CaptureFixture[str]
) -> None:
    class ExplodingBackend(FakeBackend):
        def list_info(self) -> list[ServiceInfo]:
            raise RuntimeError("boom")

    monkeypatch.setattr("uniservice_lib.commands.get_backend", lambda scope: ExplodingBackend())

    assert cli.main(["list"]) == FAILURE
    assert "RuntimeError: boom" in capsys.readouterr().err
