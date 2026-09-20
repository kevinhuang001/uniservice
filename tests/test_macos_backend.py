"""Tests for the macOS (launchd) backend."""

from __future__ import annotations

import plistlib
from collections.abc import Callable
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

import pytest

from tests.conftest import FakeRunner, completed
from uniservice_lib.backends import macos
from uniservice_lib.backends.macos import (
    MacOSBackend,
    collect_plist_entries,
    escape_pgrep_pattern,
    macos_domains,
    macos_log_paths,
    macos_plist_root,
    parse_launchctl_list,
    parse_print_disabled,
    pgrep_running,
    render_plist,
)
from uniservice_lib.errors import ServiceNotFoundError, UniserviceError
from uniservice_lib.scope import SYSTEM, USER, Scope

pytestmark = pytest.mark.usefixtures("clean_logger")

DOMAIN = "gui/501"


@pytest.fixture
def plist_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "Library" / "LaunchAgents"
    root.mkdir(parents=True)
    monkeypatch.setattr(macos, "macos_plist_root", lambda scope: root)
    monkeypatch.setattr(macos, "macos_domains", lambda scope: [DOMAIN])
    return root


@pytest.fixture
def backend() -> MacOSBackend:
    return MacOSBackend(Scope(USER))


def write_plist(root: Path, name: str, command: str = "/usr/bin/true") -> Path:
    path = root / f"com.uniservice.{name}.plist"
    path.write_text(
        render_plist(
            f"com.uniservice.{name}",
            Path("/tmp"),
            command,
            root.parent / f"{name}.out.log",
            root.parent / f"{name}.err.log",
        ),
        encoding="utf-8",
    )
    return path


# ---------------------------------------------------------------------------
# pure helpers
# ---------------------------------------------------------------------------


def test_macos_plist_root_for_system_scope() -> None:
    assert macos_plist_root(Scope(SYSTEM)) == Path("/Library/LaunchDaemons")


def test_macos_domains_for_system_scope() -> None:
    assert macos_domains(Scope(SYSTEM)) == ["system"]


def test_macos_log_paths() -> None:
    stdout, stderr = macos_log_paths("demo", Scope(SYSTEM))
    assert stdout == Path("/var/log/uniservice/demo.out.log")
    assert stderr == Path("/var/log/uniservice/demo.err.log")


def test_collect_plist_entries_missing_directory(tmp_path: Path) -> None:
    assert collect_plist_entries(tmp_path / "nope") == []


def test_collect_plist_entries_skips_foreign_plists(tmp_path: Path) -> None:
    write_plist(tmp_path, "kept")
    (tmp_path / "com.apple.something.plist").write_text("", encoding="utf-8")
    (tmp_path / "com.uniservice.other.txt").write_text("", encoding="utf-8")
    entries = collect_plist_entries(tmp_path)
    assert [name for name, _label, _path in entries] == ["kept"]


def test_parse_print_disabled_understands_both_spellings() -> None:
    text = (
        "disabled services = {\n"
        '    "com.uniservice.alpha" => disabled\n'
        '    "com.uniservice.beta" => enabled\n'
        '    "com.uniservice.gamma" => true\n'
        '    "com.uniservice.delta" => false\n'
        "}\n"
    )
    assert parse_print_disabled(text) == {
        "com.uniservice.alpha": True,
        "com.uniservice.beta": False,
        "com.uniservice.gamma": True,
        "com.uniservice.delta": False,
    }


def test_parse_launchctl_list_reads_pid_column() -> None:
    text = "PID\tStatus\tLabel\n-\t0\tcom.uniservice.loaded\n4242\t0\tcom.uniservice.running\n1\t0\tcom.apple.other\n"
    assert parse_launchctl_list(text) == {
        "com.uniservice.loaded": False,
        "com.uniservice.running": True,
    }


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("python3 -m http.server 8000", r"python3 -m http\.server 8000"),
        ("a|b", r"a\|b"),
        ("/usr/bin/[x]", r"/usr/bin/\[x\]"),
        ("--flag", "--flag"),
    ],
)
def test_escape_pgrep_pattern(command: str, expected: str) -> None:
    assert escape_pgrep_pattern(command) == expected


def test_render_plist_escapes_xml(tmp_path: Path) -> None:
    workdir = tmp_path / "<dir>"
    xml = render_plist(
        "com.uniservice.demo",
        workdir,
        "echo '<hi>'",
        tmp_path / "out.log",
        tmp_path / "err.log",
    )
    assert f"<string>{xml_escape(str(workdir))}</string>" in xml
    assert plistlib.loads(xml.encode("utf-8"))["Label"] == "com.uniservice.demo"


# ---------------------------------------------------------------------------
# list_info
# ---------------------------------------------------------------------------


def test_list_info_returns_empty_without_plists(
    backend: MacOSBackend,
    plist_root: Path,
    fake_runner: Callable[..., FakeRunner],
) -> None:
    fake_runner(macos)
    assert backend.list_info() == []


def test_list_info_reports_unknown_states_without_launchctl(
    backend: MacOSBackend,
    plist_root: Path,
    fake_which: Callable[..., None],
    fake_runner: Callable[..., FakeRunner],
) -> None:
    write_plist(plist_root, "demo")
    fake_which(macos)
    runner = fake_runner(macos)

    rows = backend.list_info()

    assert rows[0].enabled is None
    assert rows[0].running is None
    assert runner.calls == []


def test_list_info_treats_a_job_without_override_as_enabled(
    backend: MacOSBackend,
    plist_root: Path,
    fake_which: Callable[..., None],
    fake_runner: Callable[..., FakeRunner],
) -> None:
    """Regression: a job absent from print-disabled used to be reported as "?"."""
    write_plist(plist_root, "demo")
    fake_which(macos, "launchctl")
    runner = fake_runner(macos)
    runner.add_command(
        "launchctl",
        "print-disabled",
        stdout='disabled services = {\n    "com.uniservice.other" => disabled\n}\n',
    )
    runner.add_command("launchctl", "list", stdout="PID\tStatus\tLabel\n")

    row = backend.list_info()[0]

    assert row.enabled is True


@pytest.mark.parametrize(
    ("state", "expected_enabled"),
    [("disabled", False), ("enabled", True), ("true", False), ("false", True)],
)
def test_list_info_reads_disabled_overrides(
    backend: MacOSBackend,
    plist_root: Path,
    fake_which: Callable[..., None],
    fake_runner: Callable[..., FakeRunner],
    state: str,
    expected_enabled: bool,
) -> None:
    write_plist(plist_root, "demo")
    fake_which(macos, "launchctl")
    runner = fake_runner(macos)
    runner.add_command(
        "launchctl",
        "print-disabled",
        stdout=f'disabled services = {{\n    "com.uniservice.demo" => {state}\n}}\n',
    )
    runner.add_command("launchctl", "list", stdout="PID\tStatus\tLabel\n")

    assert backend.list_info()[0].enabled is expected_enabled


def test_list_info_reports_unknown_when_every_domain_query_fails(
    backend: MacOSBackend,
    plist_root: Path,
    fake_which: Callable[..., None],
    fake_runner: Callable[..., FakeRunner],
) -> None:
    write_plist(plist_root, "demo")
    fake_which(macos, "launchctl")
    fake_runner(macos, default=completed(1))

    assert backend.list_info()[0].enabled is None


def test_list_info_lets_the_most_specific_domain_win(
    plist_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_which: Callable[..., None],
    fake_runner: Callable[..., FakeRunner],
) -> None:
    """Regression: merging used to be last-wins, so user/<uid> overrode gui/<uid>."""
    write_plist(plist_root, "demo")
    monkeypatch.setattr(macos, "macos_domains", lambda scope: ["gui/501", "user/501"])
    fake_which(macos, "launchctl")
    runner = fake_runner(macos)
    runner.add_command("launchctl", "print-disabled", "gui/501", stdout='"com.uniservice.demo" => enabled\n')
    runner.add_command("launchctl", "print-disabled", "user/501", stdout='"com.uniservice.demo" => disabled\n')
    runner.add_command("launchctl", "list", stdout="PID\tStatus\tLabel\n")

    assert MacOSBackend(Scope(USER)).list_info()[0].enabled is True


def test_list_info_reads_running_state_from_launchctl_list(
    backend: MacOSBackend,
    plist_root: Path,
    fake_which: Callable[..., None],
    fake_runner: Callable[..., FakeRunner],
) -> None:
    write_plist(plist_root, "loaded")
    write_plist(plist_root, "running")
    fake_which(macos, "launchctl")
    runner = fake_runner(macos)
    runner.add_command("launchctl", "print-disabled", stdout="disabled services = {\n}\n")
    runner.add_command(
        "launchctl",
        "list",
        stdout="PID\tStatus\tLabel\n-\t0\tcom.uniservice.loaded\n4242\t0\tcom.uniservice.running\n",
    )

    rows = {row.name: row for row in backend.list_info()}

    assert rows["loaded"].running is False
    assert rows["running"].running is True


def test_list_info_falls_back_to_launchctl_print_for_system_jobs(
    plist_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_which: Callable[..., None],
    fake_runner: Callable[..., FakeRunner],
) -> None:
    """Regression: launchctl list does not cover the system domain."""
    write_plist(plist_root, "demo")
    monkeypatch.setattr(macos, "macos_domains", lambda scope: ["system"])
    fake_which(macos, "launchctl")
    runner = fake_runner(macos)
    runner.add_command("launchctl", "print-disabled", stdout="disabled services = {\n}\n")
    runner.add_command("launchctl", "list", stdout="PID\tStatus\tLabel\n")
    runner.add_command("launchctl", "print", "system/com.uniservice.demo", stdout="\tpid = 987\n")

    assert MacOSBackend(Scope(SYSTEM)).list_info()[0].running is True


def test_list_info_print_without_pid_means_not_running(
    backend: MacOSBackend,
    plist_root: Path,
    fake_which: Callable[..., None],
    fake_runner: Callable[..., FakeRunner],
) -> None:
    write_plist(plist_root, "demo")
    fake_which(macos, "launchctl")
    runner = fake_runner(macos)
    runner.add_command("launchctl", "print-disabled", stdout="disabled services = {\n}\n")
    runner.add_command("launchctl", "list", stdout="PID\tStatus\tLabel\n")
    runner.add_command("launchctl", "print", stdout="\tstate = waiting\n")

    assert backend.list_info()[0].running is False


def test_list_info_falls_back_to_pgrep(
    backend: MacOSBackend,
    plist_root: Path,
    fake_which: Callable[..., None],
    fake_runner: Callable[..., FakeRunner],
) -> None:
    write_plist(plist_root, "demo", command="/usr/bin/python3 -m http.server")
    fake_which(macos, "launchctl", "pgrep")
    runner = fake_runner(macos)
    runner.add_command("launchctl", "print-disabled", stdout="disabled services = {\n}\n")
    runner.add_command("launchctl", "list", stdout="PID\tStatus\tLabel\n")
    runner.add_command("launchctl", "print", returncode=113)
    runner.add_command("pgrep", returncode=0)

    assert backend.list_info()[0].running is True


@pytest.mark.parametrize(("returncode", "expected"), [(0, True), (1, False), (2, None), (3, None)])
def test_pgrep_running_interprets_exit_codes(
    fake_which: Callable[..., None],
    fake_runner: Callable[..., FakeRunner],
    returncode: int,
    expected: bool | None,
) -> None:
    """Regression: any pgrep failure used to be reported as "not running"."""
    fake_which(macos, "pgrep")
    runner = fake_runner(macos)
    runner.add_command("pgrep", returncode=returncode)
    assert pgrep_running("/usr/bin/python3 -m http.server") is expected


def test_pgrep_running_without_pgrep_returns_none(
    fake_which: Callable[..., None],
    fake_runner: Callable[..., FakeRunner],
) -> None:
    fake_which(macos)
    fake_runner(macos)
    assert pgrep_running("/usr/bin/true") is None


# ---------------------------------------------------------------------------
# create / cat / exists
# ---------------------------------------------------------------------------


def test_create_writes_a_parsable_plist(
    backend: MacOSBackend,
    plist_root: Path,
    tmp_path: Path,
    fake_runner: Callable[..., FakeRunner],
) -> None:
    workdir = tmp_path / "work"
    fake_runner(macos)

    backend.create("demo", workdir, ["/usr/bin/python3", "-m", "http.server", "8000"])

    data = plistlib.loads((plist_root / "com.uniservice.demo.plist").read_bytes())
    assert data["Label"] == "com.uniservice.demo"
    assert data["WorkingDirectory"] == str(workdir)
    assert data["ProgramArguments"] == ["/bin/bash", "-lc", "/usr/bin/python3 -m http.server 8000"]


def test_cat_round_trips_the_add_command(
    backend: MacOSBackend,
    plist_root: Path,
    tmp_path: Path,
    fake_runner: Callable[..., FakeRunner],
    capsys: pytest.CaptureFixture[str],
) -> None:
    workdir = tmp_path / "work"
    fake_runner(macos)
    backend.create("demo", workdir, ["/usr/bin/python3", "-m", "http.server", "8000"])

    backend.cat("demo")

    output = capsys.readouterr().out.strip()
    assert output.startswith("uniservice add demo --workdir ")
    assert str(workdir) in output
    assert output.endswith("-- /usr/bin/python3 -m http.server 8000")


def test_cat_rejects_a_missing_service(backend: MacOSBackend, plist_root: Path) -> None:
    with pytest.raises(ServiceNotFoundError):
        backend.cat("nope")


def test_exists_reflects_the_plist(backend: MacOSBackend, plist_root: Path) -> None:
    assert backend.exists("demo") is False
    write_plist(plist_root, "demo")
    assert backend.exists("demo") is True


# ---------------------------------------------------------------------------
# status / logs / lifecycle command shapes
# ---------------------------------------------------------------------------


def test_status_prints_the_launchctl_output(
    backend: MacOSBackend,
    plist_root: Path,
    fake_runner: Callable[..., FakeRunner],
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_plist(plist_root, "demo")
    runner = fake_runner(macos)
    runner.add_command("launchctl", "print", stdout="state = running\n")

    backend.status("demo")

    assert "state = running" in capsys.readouterr().out
    assert runner.commands_matching("launchctl", "print", f"{DOMAIN}/com.uniservice.demo")


def test_status_raises_when_no_domain_knows_the_job(
    backend: MacOSBackend,
    plist_root: Path,
    fake_runner: Callable[..., FakeRunner],
) -> None:
    write_plist(plist_root, "demo")
    fake_runner(macos, default=completed(113, stderr="Could not find service"))

    with pytest.raises(UniserviceError, match="Could not find service"):
        backend.status("demo")


def test_logs_tails_the_recorded_paths(
    backend: MacOSBackend,
    plist_root: Path,
    fake_runner: Callable[..., FakeRunner],
) -> None:
    fake_runner(macos)
    backend.create("demo", Path("/tmp"), ["/usr/bin/true"])
    out_path, err_path = macos_log_paths("demo", Scope(USER))
    runner = fake_runner(macos)

    backend.logs("demo", lines=5, follow=False)

    assert runner.calls == [
        ["tail", "-n", "5", str(out_path)],
        ["tail", "-n", "5", str(err_path)],
    ]


def test_logs_follow_tails_both_files_at_once(
    backend: MacOSBackend,
    plist_root: Path,
    fake_runner: Callable[..., FakeRunner],
) -> None:
    fake_runner(macos)
    backend.create("demo", Path("/tmp"), ["/usr/bin/true"])
    out_path, err_path = macos_log_paths("demo", Scope(USER))
    runner = fake_runner(macos)

    backend.logs("demo", lines=7, follow=True)

    assert runner.calls == [["tail", "-n", "7", "-f", str(out_path), str(err_path)]]


def test_logs_prefers_the_paths_stored_in_the_plist(
    backend: MacOSBackend,
    plist_root: Path,
    fake_runner: Callable[..., FakeRunner],
) -> None:
    custom_out = plist_root.parent / "custom.out.log"
    custom_err = plist_root.parent / "custom.err.log"
    (plist_root / "com.uniservice.demo.plist").write_text(
        render_plist("com.uniservice.demo", Path("/tmp"), "/usr/bin/true", custom_out, custom_err),
        encoding="utf-8",
    )
    runner = fake_runner(macos)

    backend.logs("demo", lines=3, follow=False)

    assert runner.calls == [
        ["tail", "-n", "3", str(custom_out)],
        ["tail", "-n", "3", str(custom_err)],
    ]


def test_enable_stops_at_the_first_successful_domain(
    backend: MacOSBackend,
    plist_root: Path,
    fake_runner: Callable[..., FakeRunner],
) -> None:
    write_plist(plist_root, "demo")
    runner = fake_runner(macos, default=completed(1, stderr="nope"))
    runner.add_command("launchctl", "enable", stdout="")

    backend.enable("demo")

    assert runner.commands_matching("launchctl", "enable", f"{DOMAIN}/com.uniservice.demo")


def test_enable_raises_when_every_domain_fails(
    backend: MacOSBackend,
    plist_root: Path,
    fake_runner: Callable[..., FakeRunner],
) -> None:
    write_plist(plist_root, "demo")
    fake_runner(macos, default=completed(1, stderr="Operation not permitted"))

    with pytest.raises(UniserviceError, match="Operation not permitted"):
        backend.enable("demo")


def test_disable_flips_the_override(
    backend: MacOSBackend,
    plist_root: Path,
    fake_runner: Callable[..., FakeRunner],
) -> None:
    write_plist(plist_root, "demo")
    runner = fake_runner(macos)

    backend.disable("demo")

    assert runner.commands_matching("launchctl", "disable", f"{DOMAIN}/com.uniservice.demo")


def test_start_bootstraps_then_kickstarts(
    backend: MacOSBackend,
    plist_root: Path,
    fake_runner: Callable[..., FakeRunner],
) -> None:
    write_plist(plist_root, "demo")
    runner = fake_runner(macos)

    backend.start("demo")

    assert runner.commands_matching("launchctl", "bootstrap", DOMAIN)
    assert runner.commands_matching("launchctl", "kickstart", "-k", f"{DOMAIN}/com.uniservice.demo")


def test_start_reports_the_bootstrap_error_when_everything_fails(
    backend: MacOSBackend,
    plist_root: Path,
    fake_runner: Callable[..., FakeRunner],
) -> None:
    write_plist(plist_root, "demo")
    fake_runner(macos, default=completed(5, stderr="Input/output error"))

    with pytest.raises(UniserviceError, match="Input/output error"):
        backend.start("demo")


def test_stop_kills_and_boots_out(
    backend: MacOSBackend,
    plist_root: Path,
    fake_runner: Callable[..., FakeRunner],
) -> None:
    plist_path = write_plist(plist_root, "demo")
    runner = fake_runner(macos)

    backend.stop("demo")

    assert runner.commands_matching("launchctl", "kill", "SIGTERM", f"{DOMAIN}/com.uniservice.demo")
    assert runner.commands_matching("launchctl", "stop", f"{DOMAIN}/com.uniservice.demo")
    assert runner.commands_matching("launchctl", "bootout", DOMAIN, str(plist_path))


def test_remove_deletes_the_plist(
    backend: MacOSBackend,
    plist_root: Path,
    fake_runner: Callable[..., FakeRunner],
) -> None:
    plist_path = write_plist(plist_root, "demo")
    fake_runner(macos)

    backend.remove("demo")

    assert not plist_path.exists()
