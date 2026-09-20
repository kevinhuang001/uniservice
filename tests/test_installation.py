"""Tests for locating and removing an installation of uniservice itself."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from uniservice_lib.errors import UniserviceError
from uniservice_lib.installation import (
    Installation,
    find_installation,
    manifest_path_for,
    read_manifest,
    remove_installation,
    running_commands,
)

MANIFEST = """\
schema=1
program=uniservice
kind=binary
version=1.3.0
asset=uniservice-linux-x86_64
sha256=abc
prefix={prefix}
binary={binary}
installed_at=2026-09-20T00:00:00Z
"""


def make_installation(tmp_path: Path, *, extra: str = "") -> Installation:
    """Lay out a fake prefix with a manifest and a command."""
    prefix = tmp_path / "pfx"
    binary = prefix / "bin" / "uniservice"
    binary.parent.mkdir(parents=True)
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    binary.chmod(0o755)

    manifest = manifest_path_for(binary)
    manifest.parent.mkdir(parents=True)
    manifest.write_text(MANIFEST.format(prefix=prefix, binary=binary) + extra, encoding="utf-8")

    return Installation(prefix=prefix, command=binary, manifest=manifest, fields=read_manifest(manifest))


def test_manifest_path_sits_beside_the_command(tmp_path: Path) -> None:
    assert manifest_path_for(tmp_path / "usr/local/bin/uniservice") == (tmp_path / "usr/local/lib/uniservice/manifest")


def test_read_manifest_parses_key_value_lines(tmp_path: Path) -> None:
    installation = make_installation(tmp_path)
    assert installation.fields["kind"] == "binary"
    assert installation.version == "1.3.0"
    assert installation.kind == "binary"
    assert installation.recorded_files == [installation.prefix / "bin" / "uniservice"]


def test_read_manifest_ignores_junk_lines(tmp_path: Path) -> None:
    path = tmp_path / "manifest"
    path.write_text("kind=zipapp\nnot a pair\n=empty key\nversion=1.0\n", encoding="utf-8")
    assert read_manifest(path) == {"kind": "zipapp", "version": "1.0"}


def test_find_installation_returns_none_without_a_manifest(tmp_path: Path) -> None:
    command = tmp_path / "pfx" / "bin" / "uniservice"
    command.parent.mkdir(parents=True)
    command.write_text("", encoding="utf-8")
    assert find_installation(command) is None


def test_find_installation_reads_the_manifest(tmp_path: Path) -> None:
    installation = make_installation(tmp_path)
    found = find_installation(installation.command)
    assert found is not None
    assert found.prefix == installation.prefix
    assert found.version == "1.3.0"


def test_running_commands_includes_argv0() -> None:
    assert any(path.name in {"pytest", "python", "uniservice"} or path.is_file() for path in running_commands())


def test_remove_installation_deletes_the_recorded_files(tmp_path: Path) -> None:
    installation = make_installation(tmp_path)

    removed, deferred = remove_installation(installation)

    assert removed == [installation.prefix / "bin" / "uniservice"]
    assert deferred == []
    assert not installation.prefix.exists()  # empty directories are pruned too


def test_remove_installation_keeps_other_files(tmp_path: Path) -> None:
    installation = make_installation(tmp_path)
    keeper = installation.prefix / "keep.txt"
    keeper.write_text("not ours\n", encoding="utf-8")

    remove_installation(installation)

    assert keeper.read_text(encoding="utf-8") == "not ours\n"
    assert not (installation.prefix / "bin").exists()


def test_dry_run_changes_nothing(tmp_path: Path) -> None:
    installation = make_installation(tmp_path)

    removed, deferred = remove_installation(installation, dry_run=True)

    assert removed == [installation.prefix / "bin" / "uniservice"]
    assert deferred == []
    assert installation.command.exists()
    assert installation.manifest.exists()


def test_paths_outside_the_prefix_are_ignored(tmp_path: Path) -> None:
    """A tampered manifest must not be able to delete anything else."""
    installation = make_installation(tmp_path)
    outsider = tmp_path / "important.txt"
    outsider.write_text("do not delete\n", encoding="utf-8")
    tampered = dict(installation.fields) | {"binary": str(outsider)}

    remove_installation(Installation(installation.prefix, installation.command, installation.manifest, tampered))

    assert outsider.read_text(encoding="utf-8") == "do not delete\n"


@pytest.mark.skipif(os.name != "nt", reason="Windows-only removal rules")
def test_running_image_and_batch_shim_are_deferred_on_windows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    installation = make_installation(tmp_path)
    shim = installation.prefix / "bin" / "uniservice.cmd"
    shim.write_text("@echo off\n", encoding="utf-8")
    # Record the shim too, as the zipapp install does.
    fields = dict(installation.fields) | {"shim": str(shim)}
    installation = Installation(installation.prefix, installation.command, installation.manifest, fields)

    scheduled: list[Path] = []
    monkeypatch.setattr("uniservice_lib.installation.running_commands", lambda: [installation.command])
    monkeypatch.setattr(
        "uniservice_lib.installation._schedule_windows_delete",
        lambda path, prefix: scheduled.append(path),
    )

    removed, deferred = remove_installation(installation)

    assert removed == []
    assert deferred == [shim, installation.command]
    assert scheduled == [shim, installation.command]
    assert installation.command.exists()  # still there until the helper runs
    assert not installation.manifest.exists()


def test_remove_installation_reports_a_permission_problem(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    installation = make_installation(tmp_path)
    original = Path.unlink

    def deny(self: Path, *args: object, **kwargs: object) -> None:
        if self.name == "uniservice":
            raise PermissionError(13, "Permission denied", str(self))
        original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", deny)

    with pytest.raises(UniserviceError, match="run 'sudo uniservice uninstall'"):
        remove_installation(installation)
