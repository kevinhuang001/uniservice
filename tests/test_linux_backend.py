"""Tests for the Linux (systemd) backend."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from tests.conftest import FakeRunner
from uniservice_lib.backends import linux
from uniservice_lib.backends.linux import LinuxBackend, collect_unit_names
from uniservice_lib.errors import ServiceNotFoundError, UniserviceError
from uniservice_lib.scope import USER, Scope

pytestmark = pytest.mark.usefixtures("clean_logger")


@pytest.fixture
def unit_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "systemd" / "user"
    root.mkdir(parents=True)
    monkeypatch.setattr(linux, "systemd_root", lambda scope: root)
    return root


@pytest.fixture
def backend() -> LinuxBackend:
    return LinuxBackend(Scope(USER))


def write_unit(root: Path, name: str, content: str = "[Service]\n") -> Path:
    path = root / f"uniservice-{name}.service"
    path.write_text(content, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# collect_unit_names
# ---------------------------------------------------------------------------


def test_collect_unit_names_returns_empty_for_missing_directory(tmp_path: Path) -> None:
    assert collect_unit_names(tmp_path / "nope") == []


def test_collect_unit_names_ignores_foreign_files(tmp_path: Path) -> None:
    write_unit(tmp_path, "kept")
    (tmp_path / "other.service").write_text("", encoding="utf-8")
    (tmp_path / "uniservice-timer.timer").write_text("", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("", encoding="utf-8")
    assert collect_unit_names(tmp_path) == ["kept"]


def test_collect_unit_names_ignores_directories(tmp_path: Path) -> None:
    write_unit(tmp_path, "kept")
    (tmp_path / "uniservice-directory.service").mkdir()
    assert collect_unit_names(tmp_path) == ["kept"]


def test_collect_unit_names_includes_masked_symlinks(tmp_path: Path) -> None:
    """A masked unit is a symlink to /dev/null and must still be listed."""
    write_unit(tmp_path, "kept")
    try:
        (tmp_path / "uniservice-masked.service").symlink_to("/dev/null")
    except (OSError, NotImplementedError):  # pragma: no cover - Windows without symlink rights
        pytest.skip("creating symlinks requires privileges on this host")
    assert collect_unit_names(tmp_path) == ["kept", "masked"]


def test_collect_unit_names_keeps_dots_and_sorts_case_insensitively(tmp_path: Path) -> None:
    write_unit(tmp_path, "zeta")
    write_unit(tmp_path, "Alpha")
    write_unit(tmp_path, "my.app")
    assert collect_unit_names(tmp_path) == ["Alpha", "my.app", "zeta"]


# ---------------------------------------------------------------------------
# list_info
# ---------------------------------------------------------------------------


def test_list_info_returns_empty_without_units(
    backend: LinuxBackend,
    unit_root: Path,
    fake_runner: Callable[..., FakeRunner],
) -> None:
    fake_runner(linux)
    assert backend.list_info() == []


@pytest.mark.parametrize(
    ("enabled_state", "active_state", "expected_enabled", "expected_running"),
    [
        ("enabled", "active", True, True),
        ("enabled", "activating", True, True),
        ("enabled", "reloading", True, True),
        ("enabled", "deactivating", True, False),
        ("enabled", "inactive", True, False),
        ("enabled", "failed", True, False),
        ("enabled-runtime", "active", True, True),
        ("disabled", "inactive", False, False),
        ("masked", "inactive", False, False),
        ("static", "active", False, True),
        ("bad", "unknown", False, None),
        ("who-knows", "who-knows", None, None),
    ],
)
def test_list_info_classifies_systemd_states(
    backend: LinuxBackend,
    unit_root: Path,
    fake_runner: Callable[..., FakeRunner],
    fake_which: Callable[..., None],
    enabled_state: str,
    active_state: str,
    expected_enabled: bool | None,
    expected_running: bool | None,
) -> None:
    write_unit(unit_root, "demo")
    fake_which(linux, "systemctl")
    runner = fake_runner(linux)
    runner.add_command("is-enabled", "uniservice-demo.service", stdout=f"{enabled_state}\n")
    runner.add_command("is-active", "uniservice-demo.service", stdout=f"{active_state}\n")

    rows = backend.list_info()

    assert len(rows) == 1
    assert rows[0].name == "demo"
    assert rows[0].enabled is expected_enabled
    assert rows[0].running is expected_running


def test_list_info_ignores_stderr_warnings_next_to_stdout(
    backend: LinuxBackend,
    unit_root: Path,
    fake_runner: Callable[..., FakeRunner],
    fake_which: Callable[..., None],
) -> None:
    """Regression: stdout and stderr used to be concatenated before parsing."""
    write_unit(unit_root, "demo")
    fake_which(linux, "systemctl")
    runner = fake_runner(linux)
    runner.add_command(
        "is-enabled",
        "uniservice-demo.service",
        stdout="enabled\n",
        stderr="Warning: some systemd notice\n",
    )
    runner.add_command(
        "is-active",
        "uniservice-demo.service",
        stdout="active\n",
        stderr="Warning: some systemd notice\n",
    )

    row = backend.list_info()[0]

    assert row.enabled is True
    assert row.running is True


def test_list_info_reports_unknown_when_only_an_error_is_printed(
    backend: LinuxBackend,
    unit_root: Path,
    fake_runner: Callable[..., FakeRunner],
    fake_which: Callable[..., None],
) -> None:
    write_unit(unit_root, "demo")
    fake_which(linux, "systemctl")
    runner = fake_runner(linux)
    runner.add_command(
        "is-enabled",
        "uniservice-demo.service",
        returncode=1,
        stderr="Failed to get unit file state for uniservice-demo.service: No such file or directory\n",
    )
    runner.add_command("is-active", "uniservice-demo.service", returncode=1, stdout="inactive\n")

    row = backend.list_info()[0]

    assert row.enabled is None
    assert row.running is False


def test_list_info_reports_unknown_when_systemctl_is_missing(
    backend: LinuxBackend,
    unit_root: Path,
    fake_runner: Callable[..., FakeRunner],
    fake_which: Callable[..., None],
) -> None:
    write_unit(unit_root, "demo")
    write_unit(unit_root, "other")
    fake_which(linux)
    runner = fake_runner(linux)

    rows = backend.list_info()

    assert [row.name for row in rows] == ["demo", "other"]
    assert all(row.enabled is None and row.running is None for row in rows)
    assert runner.calls == []


def test_list_info_queries_user_scope_units(
    backend: LinuxBackend,
    unit_root: Path,
    fake_runner: Callable[..., FakeRunner],
    fake_which: Callable[..., None],
) -> None:
    write_unit(unit_root, "demo")
    fake_which(linux, "systemctl")
    runner = fake_runner(linux)
    runner.add_command("is-enabled", stdout="enabled\n")
    runner.add_command("is-active", stdout="active\n")

    backend.list_info()

    assert runner.commands_matching("--user", "is-enabled", "uniservice-demo.service")
    assert runner.commands_matching("--user", "is-active", "uniservice-demo.service")


def test_list_info_uses_system_scope_without_user_flag(
    unit_root: Path,
    fake_runner: Callable[..., FakeRunner],
    fake_which: Callable[..., None],
) -> None:
    write_unit(unit_root, "demo")
    fake_which(linux, "systemctl")
    runner = fake_runner(linux)
    runner.add_command("is-enabled", stdout="enabled\n")
    runner.add_command("is-active", stdout="active\n")

    LinuxBackend(Scope("system")).list_info()

    assert runner.commands_matching("is-enabled", "uniservice-demo.service")
    assert all("--user" not in cmd for cmd in runner.calls)


# ---------------------------------------------------------------------------
# create / cat / exists / lifecycle
# ---------------------------------------------------------------------------


def test_create_writes_the_expected_unit(
    backend: LinuxBackend,
    unit_root: Path,
    tmp_path: Path,
    fake_which: Callable[..., None],
    fake_runner: Callable[..., FakeRunner],
) -> None:
    workdir = tmp_path / "work"
    fake_which(linux, "systemctl")
    fake_runner(linux)

    backend.create("demo", workdir, ["/usr/bin/python3", "-m", "http.server", "8000"])

    unit = (unit_root / "uniservice-demo.service").read_text(encoding="utf-8")
    assert f"WorkingDirectory={workdir}" in unit
    assert "ExecStart=/usr/bin/env bash -lc '/usr/bin/python3 -m http.server 8000'" in unit
    assert "WantedBy=default.target" in unit


def test_create_requires_systemctl(
    backend: LinuxBackend,
    unit_root: Path,
    tmp_path: Path,
    fake_which: Callable[..., None],
) -> None:
    fake_which(linux)
    with pytest.raises(UniserviceError):
        backend.create("demo", tmp_path, ["/usr/bin/true"])


def test_cat_round_trips_the_add_command(
    backend: LinuxBackend,
    unit_root: Path,
    tmp_path: Path,
    fake_which: Callable[..., None],
    fake_runner: Callable[..., FakeRunner],
    capsys: pytest.CaptureFixture[str],
) -> None:
    workdir = tmp_path / "work"
    fake_which(linux, "systemctl")
    fake_runner(linux)
    backend.create("demo", workdir, ["/usr/bin/python3", "-m", "http.server", "8000"])

    backend.cat("demo")

    output = capsys.readouterr().out.strip()
    assert output.startswith("uniservice add demo --workdir ")
    assert str(workdir) in output
    assert output.endswith("-- /usr/bin/python3 -m http.server 8000")


def test_cat_rejects_a_missing_service(backend: LinuxBackend, unit_root: Path) -> None:
    with pytest.raises(ServiceNotFoundError):
        backend.cat("nope")


def test_exists_reflects_the_unit_file(backend: LinuxBackend, unit_root: Path) -> None:
    assert backend.exists("demo") is False
    write_unit(unit_root, "demo")
    assert backend.exists("demo") is True


def test_remove_deletes_the_unit_file(backend: LinuxBackend, unit_root: Path) -> None:
    path = write_unit(unit_root, "demo")
    backend.remove("demo")
    assert not path.exists()


def test_disable_swallows_reset_failed_output(
    backend: LinuxBackend,
    fake_which: Callable[..., None],
    fake_runner: Callable[..., FakeRunner],
) -> None:
    fake_which(linux, "systemctl")
    runner = fake_runner(linux)
    runner.add_command("reset-failed", returncode=1, stderr="Unit not loaded")

    backend.disable("demo")

    assert runner.commands_matching("reset-failed")


# ---------------------------------------------------------------------------
# status / logs / lifecycle command shapes
# ---------------------------------------------------------------------------


def test_status_delegates_to_systemctl(
    backend: LinuxBackend,
    unit_root: Path,
    fake_which: Callable[..., None],
    fake_runner: Callable[..., FakeRunner],
) -> None:
    write_unit(unit_root, "demo")
    fake_which(linux, "systemctl")
    runner = fake_runner(linux)

    backend.status("demo")

    assert runner.commands_matching("--user", "status", "uniservice-demo.service", "--no-pager", "-l")


def test_status_requires_an_existing_unit(backend: LinuxBackend, unit_root: Path) -> None:
    with pytest.raises(ServiceNotFoundError):
        backend.status("demo")


def test_status_requires_systemctl(
    backend: LinuxBackend,
    unit_root: Path,
    fake_which: Callable[..., None],
    fake_runner: Callable[..., FakeRunner],
) -> None:
    write_unit(unit_root, "demo")
    fake_which(linux)
    fake_runner(linux)
    with pytest.raises(UniserviceError):
        backend.status("demo")


def test_logs_uses_the_user_journal(
    backend: LinuxBackend,
    unit_root: Path,
    fake_which: Callable[..., None],
    fake_runner: Callable[..., FakeRunner],
) -> None:
    write_unit(unit_root, "demo")
    fake_which(linux, "journalctl")
    runner = fake_runner(linux)

    backend.logs("demo", lines=25, follow=False)

    assert runner.commands_matching("journalctl", "--user-unit", "uniservice-demo.service", "-n", "25")
    assert all("-f" not in cmd for cmd in runner.calls)


def test_logs_follow_adds_the_follow_flag(
    backend: LinuxBackend,
    unit_root: Path,
    fake_which: Callable[..., None],
    fake_runner: Callable[..., FakeRunner],
) -> None:
    write_unit(unit_root, "demo")
    fake_which(linux, "journalctl")
    runner = fake_runner(linux)

    backend.logs("demo", lines=10, follow=True)

    assert runner.commands_matching("journalctl", "uniservice-demo.service", "-f")


def test_logs_uses_the_system_journal_for_system_scope(
    unit_root: Path,
    fake_which: Callable[..., None],
    fake_runner: Callable[..., FakeRunner],
) -> None:
    write_unit(unit_root, "demo")
    fake_which(linux, "journalctl")
    runner = fake_runner(linux)

    LinuxBackend(Scope("system")).logs("demo", lines=10, follow=False)

    assert runner.commands_matching("journalctl", "-u", "uniservice-demo.service")


def test_logs_requires_journalctl(
    backend: LinuxBackend,
    unit_root: Path,
    fake_which: Callable[..., None],
    fake_runner: Callable[..., FakeRunner],
) -> None:
    write_unit(unit_root, "demo")
    fake_which(linux)
    fake_runner(linux)
    with pytest.raises(UniserviceError):
        backend.logs("demo", lines=10, follow=False)


def test_enable_reloads_then_enables(
    backend: LinuxBackend,
    fake_which: Callable[..., None],
    fake_runner: Callable[..., FakeRunner],
) -> None:
    fake_which(linux, "systemctl")
    runner = fake_runner(linux)

    backend.enable("demo")

    assert runner.commands_matching("--user", "daemon-reload")
    assert runner.commands_matching("--user", "enable", "uniservice-demo.service")


def test_start_reloads_then_starts(
    backend: LinuxBackend,
    fake_which: Callable[..., None],
    fake_runner: Callable[..., FakeRunner],
) -> None:
    fake_which(linux, "systemctl")
    runner = fake_runner(linux)

    backend.start("demo")

    assert runner.commands_matching("--user", "daemon-reload")
    assert runner.commands_matching("--user", "start", "uniservice-demo.service")


def test_stop_stops_the_unit(
    backend: LinuxBackend,
    fake_which: Callable[..., None],
    fake_runner: Callable[..., FakeRunner],
) -> None:
    fake_which(linux, "systemctl")
    runner = fake_runner(linux)

    backend.stop("demo")

    assert runner.commands_matching("--user", "stop", "uniservice-demo.service")
    assert not runner.commands_matching("daemon-reload")


def test_disable_resets_failed_units(
    backend: LinuxBackend,
    fake_which: Callable[..., None],
    fake_runner: Callable[..., FakeRunner],
) -> None:
    fake_which(linux, "systemctl")
    runner = fake_runner(linux)

    backend.disable("demo")

    assert runner.commands_matching("--user", "disable", "uniservice-demo.service")
    assert runner.commands_matching("--user", "reset-failed", "uniservice-demo.service")
