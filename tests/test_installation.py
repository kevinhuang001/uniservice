"""Tests for locating an installation of uniservice and reading its manifest."""

from __future__ import annotations

from pathlib import Path

from uniservice_lib.installation import (
    Installation,
    find_installation,
    manifest_path_for,
    read_manifest,
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
