"""Tests for the Windows (Scheduled Tasks) backend."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from tests.conftest import FakeRunner, completed
from uniservice_lib.backends import windows
from uniservice_lib.backends.windows import (
    WindowsBackend,
    parse_powershell_task_json,
    parse_schtasks_task_names,
    parse_task_xml_enabled,
    service_info_from_task,
    win_build_tr,
)
from uniservice_lib.errors import ServiceNotFoundError, UniserviceError
from uniservice_lib.scope import Scope

pytestmark = pytest.mark.usefixtures("clean_logger")

# A realistic ``schtasks /Query /FO CSV /V`` header on an English Windows.
ENGLISH_CSV = (
    '"HostName","TaskName","Next Run Time","Status","Logon Mode","Last Run Time","Last Result",'
    '"Author","Task To Run","Start In","Comment","Scheduled Task State"\n'
    '"PC","uniservice-demo","N/A","Ready","Interactive/Background","N/A","0","user",'
    '"cmd.exe /c ""cd /d """"C:\\tmp"""" && echo hi""","N/A","","Enabled"\n'
    '"PC","\\Microsoft\\Windows\\Defrag","N/A","Ready","Interactive/Background","N/A","0","Microsoft",'
    '"defrag.exe","N/A","","Enabled"\n'
)

# The same query on a Chinese Windows: every header and state word is translated.
CHINESE_CSV = (
    '"主机名","任务名","下次运行时间","状态","登录模式","上次运行时间","上次结果","作者","要运行的任务","起始于","注释","计划任务状态"\n'
    '"PC","uniservice-demo","N/A","就绪","交互式/后台","N/A","0","user","cmd.exe /c echo hi","N/A","","已启用"\n'
    '"PC","\\Microsoft\\Windows\\Defrag","N/A","就绪","交互式/后台","N/A","0","Microsoft","defrag.exe","N/A","","已启用"\n'
)

TASK_XML_WITH_ENABLED = """<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <Triggers>
    <TimeTrigger>
      <StartBoundary>2024-01-01T00:00:00</StartBoundary>
      <Enabled>false</Enabled>
    </TimeTrigger>
  </Triggers>
  <Settings>
    <Enabled>true</Enabled>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
  </Settings>
</Task>
"""


@pytest.fixture
def backend() -> WindowsBackend:
    return WindowsBackend(Scope("system"))


# ---------------------------------------------------------------------------
# parsing helpers
# ---------------------------------------------------------------------------


def test_parse_powershell_task_json_handles_a_single_object() -> None:
    payload = json.dumps({"name": "uniservice-demo", "state": "Ready", "enabled": True})
    assert parse_powershell_task_json(payload) == [{"name": "uniservice-demo", "state": "Ready", "enabled": True}]


def test_parse_powershell_task_json_handles_a_list_and_a_bom() -> None:
    payload = "\ufeff" + json.dumps([{"name": "uniservice-a"}, {"name": "uniservice-b"}])
    assert len(parse_powershell_task_json(payload)) == 2


def test_parse_powershell_task_json_handles_empty_output() -> None:
    assert parse_powershell_task_json("") == []
    assert parse_powershell_task_json("   \n") == []


def test_parse_powershell_task_json_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        parse_powershell_task_json("not json")


@pytest.mark.parametrize(
    ("state", "expected_running"),
    [
        ("Running", True),
        ("Ready", False),
        ("Disabled", False),
        ("Queued", None),
        ("Unknown", None),
        ("", None),
    ],
)
def test_service_info_from_task_maps_states(state: str, expected_running: bool | None) -> None:
    row = {"name": "uniservice-demo", "state": state, "enabled": True}
    info = service_info_from_task(row)
    assert info is not None
    assert info.name == "demo"
    assert info.running is expected_running


def test_service_info_from_task_keeps_a_missing_enabled_flag_unknown() -> None:
    info = service_info_from_task({"name": "uniservice-demo", "state": "Ready"})
    assert info is not None
    assert info.enabled is None


def test_service_info_from_task_skips_foreign_tasks() -> None:
    assert service_info_from_task({"name": "Microsoft\\Defrag", "state": "Ready"}) is None


def test_parse_schtasks_task_names_uses_the_english_header() -> None:
    assert parse_schtasks_task_names(ENGLISH_CSV) == ["demo"]


def test_parse_schtasks_task_names_is_locale_independent() -> None:
    """Regression: list returned nothing on non-English Windows installations."""
    assert parse_schtasks_task_names(CHINESE_CSV) == ["demo"]


def test_parse_schtasks_task_names_strips_a_bom() -> None:
    assert parse_schtasks_task_names("\ufeff" + ENGLISH_CSV) == ["demo"]


def test_parse_schtasks_task_names_on_empty_input() -> None:
    assert parse_schtasks_task_names("") == []
    assert parse_schtasks_task_names('"TaskName","Status"\n') == []


def test_parse_task_xml_enabled_reads_the_settings_element() -> None:
    assert parse_task_xml_enabled(TASK_XML_WITH_ENABLED) is True


def test_parse_task_xml_enabled_defaults_to_true() -> None:
    xml = "<Task><Settings><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy></Settings></Task>"
    assert parse_task_xml_enabled(xml) is True


def test_parse_task_xml_enabled_returns_none_for_garbage() -> None:
    assert parse_task_xml_enabled("<not-xml") is None
    assert parse_task_xml_enabled("") is None


def test_win_build_tr_sets_workdir_and_redirects_logs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROGRAMDATA", str(tmp_path))
    action = win_build_tr("demo", Path(r"C:\work"), ["C:\\python.exe", "-m", "http.server"])

    assert action.startswith('cmd.exe /c "cd /d ""C:\\work"" && ')
    assert "C:\\python.exe -m http.server" in action
    assert str(tmp_path / "uniservice" / "logs" / "services" / "demo.out.log") in action
    assert str(tmp_path / "uniservice" / "logs" / "services" / "demo.err.log") in action


# ---------------------------------------------------------------------------
# list_info
# ---------------------------------------------------------------------------


def test_list_info_does_not_require_admin(
    backend: WindowsBackend,
    monkeypatch: pytest.MonkeyPatch,
    fake_runner: Callable[..., FakeRunner],
) -> None:
    """Regression: list used to abort for non-elevated users."""
    monkeypatch.setattr(windows, "is_admin_windows", lambda: False)
    runner = fake_runner(windows)
    runner.add_command(
        "powershell.exe",
        stdout=json.dumps(
            [
                {"name": "uniservice-demo", "state": "Running", "enabled": True},
                {"name": "uniservice-idle", "state": "Ready", "enabled": False},
            ]
        ),
    )

    rows = backend.list_info()

    assert [(row.name, row.enabled, row.running) for row in rows] == [
        ("demo", True, True),
        ("idle", False, False),
    ]


def test_list_info_uses_powershell_and_never_schtasks(
    backend: WindowsBackend,
    fake_runner: Callable[..., FakeRunner],
) -> None:
    runner = fake_runner(windows)
    runner.add_command("powershell.exe", stdout=json.dumps([{"name": "uniservice-demo", "state": "Ready"}]))
    runner.add_command("schtasks.exe", stdout=ENGLISH_CSV)

    backend.list_info()

    assert runner.commands_matching("powershell.exe")
    assert runner.commands_matching("schtasks.exe") == []


def test_list_info_falls_back_to_schtasks_when_powershell_fails(
    backend: WindowsBackend,
    fake_runner: Callable[..., FakeRunner],
) -> None:
    """The schtasks fallback must still find services on a localized Windows."""
    runner = fake_runner(windows)
    runner.add_command("powershell.exe", returncode=1, stderr="Get-ScheduledTask is not available")
    runner.add_command("schtasks.exe", "/FO", "CSV", stdout=CHINESE_CSV)
    runner.add_command("schtasks.exe", "/XML", stdout=TASK_XML_WITH_ENABLED)

    rows = backend.list_info()

    assert [(row.name, row.enabled, row.running) for row in rows] == [("demo", True, None)]


def test_list_info_falls_back_when_powershell_is_missing(
    backend: WindowsBackend,
    monkeypatch: pytest.MonkeyPatch,
    fake_runner: Callable[..., FakeRunner],
) -> None:
    runner = fake_runner(windows)
    runner.add_command("schtasks.exe", "/FO", "CSV", stdout=ENGLISH_CSV)
    runner.add_command("schtasks.exe", "/XML", stdout=TASK_XML_WITH_ENABLED)

    def run_without_powershell(cmd: list[str], **kwargs: object) -> object:
        if cmd and cmd[0] == "powershell.exe":
            raise FileNotFoundError("powershell.exe")
        return runner(cmd, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(windows, "run", run_without_powershell)

    assert [row.name for row in backend.list_info()] == ["demo"]


def test_list_info_returns_empty_when_there_are_no_services(
    backend: WindowsBackend,
    fake_runner: Callable[..., FakeRunner],
) -> None:
    runner = fake_runner(windows)
    runner.add_command("powershell.exe", stdout="")
    assert backend.list_info() == []


def test_list_info_raises_when_every_query_fails(
    backend: WindowsBackend,
    fake_runner: Callable[..., FakeRunner],
) -> None:
    """Regression: a failed query used to be reported as "no services"."""
    runner = fake_runner(windows)
    runner.add_command("powershell.exe", returncode=1, stderr="nope")
    runner.add_command("schtasks.exe", returncode=1, stderr="ERROR: Access is denied.")

    with pytest.raises(UniserviceError):
        backend.list_info()


def test_list_info_falls_back_when_powershell_output_is_not_json(
    backend: WindowsBackend,
    fake_runner: Callable[..., FakeRunner],
) -> None:
    runner = fake_runner(windows)
    runner.add_command("powershell.exe", stdout="<html>error</html>")
    runner.add_command("schtasks.exe", "/FO", "CSV", stdout=ENGLISH_CSV)
    runner.add_command("schtasks.exe", "/XML", stdout=TASK_XML_WITH_ENABLED)

    assert [row.name for row in backend.list_info()] == ["demo"]


# ---------------------------------------------------------------------------
# lifecycle
# ---------------------------------------------------------------------------


def test_mutating_commands_require_admin(
    backend: WindowsBackend,
    monkeypatch: pytest.MonkeyPatch,
    fake_runner: Callable[..., FakeRunner],
) -> None:
    monkeypatch.setattr(windows, "is_admin_windows", lambda: False)
    fake_runner(windows)
    with pytest.raises(UniserviceError):
        backend.create("demo", Path("C:/tmp"), ["C:/python.exe"])


def test_exists_queries_the_task(
    backend: WindowsBackend,
    monkeypatch: pytest.MonkeyPatch,
    fake_runner: Callable[..., FakeRunner],
) -> None:
    monkeypatch.setattr(windows, "is_admin_windows", lambda: True)
    runner = fake_runner(windows)
    runner.add_command("schtasks.exe", "/Query", returncode=0)

    assert backend.exists("demo") is True
    assert runner.commands_matching("schtasks.exe", "/Query", "uniservice-demo")


def test_remove_is_forced(
    backend: WindowsBackend,
    monkeypatch: pytest.MonkeyPatch,
    fake_runner: Callable[..., FakeRunner],
) -> None:
    monkeypatch.setattr(windows, "is_admin_windows", lambda: True)
    runner = fake_runner(windows)

    backend.remove("demo")

    assert runner.commands_matching("schtasks.exe", "/Delete", "uniservice-demo", "/F")


def test_cat_round_trips_the_add_command(
    backend: WindowsBackend,
    monkeypatch: pytest.MonkeyPatch,
    fake_runner: Callable[..., FakeRunner],
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(windows, "is_admin_windows", lambda: True)
    # ``win_cmdline_split`` is Windows-only; the test only needs a stable split.
    monkeypatch.setattr(windows, "win_cmdline_split", lambda cmdline: cmdline.split())
    xml = (
        '<?xml version="1.0"?><Task><Actions><Exec>'
        "<Command>cmd.exe</Command>"
        "<Arguments>/c &quot;cd /d &quot;&quot;C:\\tmp&quot;&quot; &amp;&amp; "
        "C:\\python.exe -m http.server 8000&quot;</Arguments>"
        "</Exec></Actions></Task>"
    )
    runner = fake_runner(windows)
    runner.add_command("schtasks.exe", "/XML", stdout=xml)

    backend.cat("demo")

    output = capsys.readouterr().out.strip()
    assert output.startswith('uniservice add "demo" --workdir "C:\\tmp" -- ')
    assert "http.server 8000" in output


def test_cat_requires_the_task_to_exist(
    backend: WindowsBackend,
    monkeypatch: pytest.MonkeyPatch,
    fake_runner: Callable[..., FakeRunner],
) -> None:
    monkeypatch.setattr(windows, "is_admin_windows", lambda: True)
    runner = fake_runner(windows)
    runner.add_command("schtasks.exe", "/XML", returncode=1, stderr="not found")

    with pytest.raises(ServiceNotFoundError):
        backend.cat("demo")


def test_start_detects_a_non_zero_last_result(
    backend: WindowsBackend,
    monkeypatch: pytest.MonkeyPatch,
    fake_runner: Callable[..., FakeRunner],
) -> None:
    monkeypatch.setattr(windows, "is_admin_windows", lambda: True)
    monkeypatch.setattr(windows.time, "sleep", lambda _seconds: None)
    runner = fake_runner(windows)
    runner.add_command(
        "schtasks.exe",
        "/V",
        stdout="Status: Ready\nLast Run Result: 0x1\n",
    )

    with pytest.raises(UniserviceError):
        backend.start("demo")


def test_start_accepts_a_running_task(
    backend: WindowsBackend,
    monkeypatch: pytest.MonkeyPatch,
    fake_runner: Callable[..., FakeRunner],
) -> None:
    monkeypatch.setattr(windows, "is_admin_windows", lambda: True)
    monkeypatch.setattr(windows.time, "sleep", lambda _seconds: None)
    runner = fake_runner(windows)
    runner.add_command("schtasks.exe", "/V", stdout="Status: Running\nLast Run Result: 0x0\n")

    backend.start("demo")


def test_fake_runner_default_is_used_for_unmatched_commands() -> None:
    runner = FakeRunner(default=completed(7))
    assert runner(["anything"], check=False).returncode == 7


# ---------------------------------------------------------------------------
# status / logs / lifecycle command shapes
# ---------------------------------------------------------------------------


def test_create_builds_an_onstart_system_task(
    backend: WindowsBackend,
    monkeypatch: pytest.MonkeyPatch,
    fake_runner: Callable[..., FakeRunner],
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(windows, "is_admin_windows", lambda: True)
    monkeypatch.setenv("PROGRAMDATA", str(tmp_path))
    runner = fake_runner(windows)

    backend.create("demo", Path("C:/work"), ["C:/python.exe", "-m", "http.server"])

    (command,) = runner.commands_matching("schtasks.exe", "/Create")
    assert command[:4] == ["schtasks.exe", "/Create", "/TN", "uniservice-demo"]
    for flag in ("/SC", "ONSTART", "/RU", "SYSTEM", "/RL", "HIGHEST", "/F"):
        assert flag in command
    action = command[command.index("/TR") + 1]
    assert "cd /d " in action
    assert "C:/python.exe -m http.server" in action


def test_status_uses_the_verbose_listing(
    backend: WindowsBackend,
    monkeypatch: pytest.MonkeyPatch,
    fake_runner: Callable[..., FakeRunner],
) -> None:
    monkeypatch.setattr(windows, "is_admin_windows", lambda: True)
    runner = fake_runner(windows)

    backend.status("demo")

    assert runner.commands_matching("schtasks.exe", "/Query", "uniservice-demo", "/V", "/FO", "LIST")


def test_logs_reads_stdout_and_stderr(
    backend: WindowsBackend,
    monkeypatch: pytest.MonkeyPatch,
    fake_runner: Callable[..., FakeRunner],
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(windows, "is_admin_windows", lambda: True)
    monkeypatch.setenv("PROGRAMDATA", str(tmp_path))
    runner = fake_runner(windows)

    backend.logs("demo", lines=15, follow=False)

    log_dir = tmp_path / "uniservice" / "logs" / "services"
    scripts = [command[-1] for command in runner.calls]
    assert any(str(log_dir / "demo.out.log") in script and "-Tail 15" in script for script in scripts)
    assert any(str(log_dir / "demo.err.log") in script and "-Tail 15" in script for script in scripts)
    assert all("-Wait" not in script for script in scripts)


def test_logs_follow_waits_for_new_lines(
    backend: WindowsBackend,
    monkeypatch: pytest.MonkeyPatch,
    fake_runner: Callable[..., FakeRunner],
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(windows, "is_admin_windows", lambda: True)
    monkeypatch.setenv("PROGRAMDATA", str(tmp_path))
    runner = fake_runner(windows)

    backend.logs("demo", lines=15, follow=True)

    scripts = [command[-1] for command in runner.calls]
    assert any("-Wait" in script and "-Tail 15" in script for script in scripts)


def test_enable_and_disable_change_the_task_state(
    backend: WindowsBackend,
    monkeypatch: pytest.MonkeyPatch,
    fake_runner: Callable[..., FakeRunner],
) -> None:
    monkeypatch.setattr(windows, "is_admin_windows", lambda: True)
    runner = fake_runner(windows)

    backend.enable("demo")
    backend.disable("demo")

    assert runner.commands_matching("schtasks.exe", "/Change", "uniservice-demo", "/Enable")
    assert runner.commands_matching("schtasks.exe", "/Change", "uniservice-demo", "/Disable")


def test_stop_ends_the_task(
    backend: WindowsBackend,
    monkeypatch: pytest.MonkeyPatch,
    fake_runner: Callable[..., FakeRunner],
) -> None:
    monkeypatch.setattr(windows, "is_admin_windows", lambda: True)
    runner = fake_runner(windows)

    backend.stop("demo")

    assert runner.commands_matching("schtasks.exe", "/End", "uniservice-demo")


def test_exists_is_false_when_the_query_fails(
    backend: WindowsBackend,
    monkeypatch: pytest.MonkeyPatch,
    fake_runner: Callable[..., FakeRunner],
) -> None:
    monkeypatch.setattr(windows, "is_admin_windows", lambda: True)
    runner = fake_runner(windows)
    runner.add_command("schtasks.exe", "/Query", returncode=1, stderr="not found")

    assert backend.exists("demo") is False


def test_task_enabled_returns_none_when_the_xml_query_fails(
    backend: WindowsBackend,
    fake_runner: Callable[..., FakeRunner],
) -> None:
    runner = fake_runner(windows)
    runner.add_command("schtasks.exe", "/XML", returncode=1)

    assert backend._task_enabled("demo") is None
