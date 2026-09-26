"""Shared pytest fixtures for the uniservice test suite."""

from __future__ import annotations

import io
import subprocess
import sys
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CLI_PATH = REPO_ROOT / "uniservice"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from uniservice_lib.backends.base import Check, ServiceDefinition, ServiceInfo  # noqa: E402
from uniservice_lib.logging_utils import logger  # noqa: E402


def completed(returncode: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    """Build a :class:`subprocess.CompletedProcess` for fake runners."""
    return subprocess.CompletedProcess(args=["fake"], returncode=returncode, stdout=stdout, stderr=stderr)


class FakeRunner:
    """A scriptable stand-in for :func:`uniservice_lib.process.run`.

    Rules are matched in registration order against the command list; the first
    match wins.  Every invocation is recorded so tests can assert on the exact
    commands a backend issued.
    """

    def __init__(self, *, default: subprocess.CompletedProcess[str] | None = None) -> None:
        self.calls: list[list[str]] = []
        self._rules: list[tuple[Callable[[list[str]], bool], subprocess.CompletedProcess[str]]] = []
        self._default = default or completed()

    def add_rule(
        self,
        matcher: Callable[[list[str]], bool],
        *,
        returncode: int = 0,
        stdout: str = "",
        stderr: str = "",
    ) -> FakeRunner:
        """Register a response for every command accepted by *matcher*."""
        self._rules.append((matcher, completed(returncode, stdout, stderr)))
        return self

    def add_command(
        self,
        *needles: str,
        returncode: int = 0,
        stdout: str = "",
        stderr: str = "",
    ) -> FakeRunner:
        """Register a response for commands containing all *needles*."""
        return self.add_rule(
            lambda cmd: all(needle in cmd for needle in needles),
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
        )

    def commands_matching(self, *needles: str) -> list[list[str]]:
        """Return every recorded command containing all *needles*."""
        return [cmd for cmd in self.calls if all(needle in cmd for needle in needles)]

    def __call__(
        self,
        cmd: Sequence[str],
        *,
        check: bool = True,
        quiet: bool = False,
        capture: bool = False,
        cwd: object = None,
    ) -> subprocess.CompletedProcess[str]:
        command = list(cmd)
        self.calls.append(command)
        for matcher, response in self._rules:
            if matcher(command):
                if check and response.returncode != 0:
                    raise subprocess.CalledProcessError(response.returncode, command)
                return response
        if check and self._default.returncode != 0:
            raise subprocess.CalledProcessError(self._default.returncode, command)
        return self._default


class FakeBackend:
    """In-memory :class:`~uniservice_lib.backends.base.Backend` for CLI tests."""

    def __init__(self, *, exists: bool = True, rows: Iterable[ServiceInfo] = ()) -> None:
        self.exists_value = exists
        self.rows = list(rows)
        self.calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []
        self.scope: object = None

    def _record(self, action: str, *args: object, **kwargs: object) -> None:
        self.calls.append((action, args, kwargs))

    def actions(self) -> list[str]:
        return [action for action, _args, _kwargs in self.calls]

    def create(self, name: str, workdir: Path, command_parts: list[str]) -> None:
        self._record("create", name, workdir, list(command_parts))

    def definition(self, name: str) -> ServiceDefinition:
        self._record("definition", name)
        return ServiceDefinition(
            name=name,
            scope=self.scope.value if self.scope is not None else "user",
            location=f"/fake/{name}.unit",
            workdir="/tmp",
            command_parts=("/usr/bin/env", "true"),
        )

    def command_line(self, parts: Iterable[str]) -> str:
        return " ".join(str(part) for part in parts)

    def checks(self) -> list[Check]:
        self._record("checks")
        return []

    def status(self, name: str) -> None:
        self._record("status", name)

    def logs(self, name: str, *, lines: int, follow: bool) -> None:
        self._record("logs", name, lines=lines, follow=follow)

    def exists(self, name: str) -> bool:
        self._record("exists", name)
        return self.exists_value

    def enable(self, name: str) -> None:
        self._record("enable", name)

    def disable(self, name: str) -> None:
        self._record("disable", name)

    def start(self, name: str) -> None:
        self._record("start", name)

    def stop(self, name: str) -> None:
        self._record("stop", name)

    def restart(self, name: str) -> None:
        self._record("restart", name)

    def remove(self, name: str) -> None:
        self._record("remove", name)

    def list_info(self) -> list[ServiceInfo]:
        self._record("list_info")
        return list(self.rows)


@pytest.fixture(autouse=True)
def isolated_home(request: pytest.FixtureRequest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Keep ``$HOME``, ``%LOCALAPPDATA%`` and the log file inside ``tmp_path``.

    Integration tests are exempt: they must reach the real service manager,
    which resolves its unit directories from the user manager's environment
    rather than from ``HOME``.
    """
    if request.node.get_closest_marker("integration") is not None:
        return Path.home()

    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("LOCALAPPDATA", str(home / "AppData" / "Local"))
    monkeypatch.delenv("SUDO_UID", raising=False)
    return home


@pytest.fixture(autouse=True)
def clean_logger() -> Iterable[None]:
    """Detach logging handlers so ``setup_logging`` runs fresh in each test."""
    yield
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()


@pytest.fixture
def fake_runner(monkeypatch: pytest.MonkeyPatch) -> Callable[..., FakeRunner]:
    """Install a :class:`FakeRunner` as ``run`` in a backend module."""

    def install(module: object, *, default: subprocess.CompletedProcess[str] | None = None) -> FakeRunner:
        runner = FakeRunner(default=default)
        monkeypatch.setattr(module, "run", runner)
        return runner

    return install


@pytest.fixture
def fake_which(monkeypatch: pytest.MonkeyPatch) -> Callable[..., None]:
    """Control ``shutil.which`` inside a backend module."""

    def install(module: object, *available: str) -> None:
        names = set(available)

        def which(name: str) -> str | None:
            return f"/usr/bin/{name}" if name in names else None

        monkeypatch.setattr(module.shutil, "which", which)  # type: ignore[attr-defined]

    return install


@pytest.fixture
def cli_privileges(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the CLI believe it runs with sufficient privileges on any host."""
    monkeypatch.setattr("uniservice_lib.commands.is_root_unix", lambda: True)
    monkeypatch.setattr("uniservice_lib.commands.is_admin_windows", lambda: True)


class TtyStream(io.StringIO):
    """A stream that claims to be a terminal, so tables are rendered."""

    encoding = "utf-8"

    def isatty(self) -> bool:
        return True


@pytest.fixture
def tty(monkeypatch: pytest.MonkeyPatch) -> TtyStream:
    """Give the CLI a fake terminal as its output stream.

    ``sys.stdout`` cannot be monkeypatched here: pytest re-installs its own
    capture object for the call phase, *after* fixtures have run, so the CLI
    would never see the replacement.  Swapping the console factory instead is
    immune to that.
    """
    from uniservice_lib import cli as cli_module

    # A fake terminal must behave the same on a developer machine (which may set
    # NO_COLOR and TERM=dumb) as on a CI runner (which may set neither), so pin
    # the two variables the colour decision reads.
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")

    stream = TtyStream()
    real = cli_module.Console

    def factory(**kwargs: object) -> object:
        kwargs["stdout"] = stream
        kwargs.setdefault("stderr", stream)
        return real(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(cli_module, "Console", factory)
    return stream
