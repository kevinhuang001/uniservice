# Changelog

All notable changes to this project are documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Changed

- macOS: dropped the `launchctl load -w` / `unload -w` fallback from `start()` and `stop()`. Those
  are the pre-10.10 launchctl subcommands, and uniservice now only uses the supported interface:
  `launchctl bootstrap` to register and `launchctl bootout` to unregister. `start` reports the
  `bootstrap` error directly instead of silently retrying through the deprecated path.

## [1.2.1] - 2026-09-20

### Changed

- **The installer targets `/usr/local` and nothing else.** The `~/.local` fallback is gone:
  when the installer cannot write to `/usr/local` it stops with
  `ERROR: cannot write to /usr/local; run the installer with sudo`, before downloading anything.
  `/usr/local/bin` is already on every account's `PATH`, so there is now no PATH handling at
  all — no shell startup file is read or written, and the manifest no longer carries
  `profile_files`.
- Removed the `--user`, `--system` and `--no-modify-path` options together with the code behind
  them. `--prefix DIR` remains for packaging and tests, where no elevated privileges are wanted
  or available.

## [1.2.0] - 2026-09-20

A single self-contained install artifact, and an installer that can undo itself.

### Added

- `scripts/build_zipapp.py` builds the release artifact: one self-contained `uniservice`
  executable (~30 KB, stdlib only). The build is byte-for-byte reproducible, so a published
  `--sha256` is meaningful.
- `install.sh`, one installer for macOS and Linux:
  - `--user` / `--system` / `--prefix DIR` (default: `/usr/local` when root, else `~/.local`)
  - `--version TAG` to install a specific release, `--sha256 HEX` to verify it
  - `--from DIR` to build a local checkout without touching the network
  - `--no-modify-path` to never edit shell startup files
  - `--uninstall` removes exactly what `<prefix>/lib/uniservice/install.json` records
  - `--help`
- `.github/workflows/release.yml`: pushing a `v*` tag publishes the wheel, the sdist, the
  zipapp, `uniservice.sha256` and `SHA256SUMS` to a GitHub release.
- `install-windows.ps1` gained `-Prefix`, `-Version`, `-Sha256`, `-NoModifyPath`, `-Pipx` and
  `-Uninstall`, and records its manifest next to the portable installation.
- Tests for the artifact and the installer: `tests/test_packaging.py` checks the zipapp
  contents and reproducibility, `tests/test_install_script.py` runs install → verify →
  uninstall for real against throwaway prefixes. CI also builds the zipapp twice, runs it,
  and exercises the installer on Ubuntu and macOS.

### Changed

- **The installation is now a single file.** The old installers copied `uniservice` plus the
  `uniservice_lib` package directory into a `bin` directory, which could drift and could not
  be uninstalled. `<prefix>/bin/uniservice` is now self-contained, so copying that one file
  anywhere is a valid installation.
- **The default prefix is the shared `/usr/local`, not `~/.local`.** One installation now
  serves both scopes: `uniservice ...` for per-user services and `sudo uniservice ...` for
  system services, with no second copy and no dependency on a user's home directory.
- **`/etc/profile` is never edited.** For a `--user` install the `PATH` line goes into the
  startup file of the shell you actually use (`~/.zshrc` for zsh, `~/.bashrc` for bash) and is
  recorded in the manifest so it can be reported on uninstall.
- The installer no longer installs an unversioned moving target by default: it prefers the
  newest tagged release and only falls back to the `main` archive, with a warning, when the
  repository has no releases yet.
- **No compatibility with the pre-1.2.0 installer.** `install-linux.sh` and `install-macos.sh`
  are gone (use `install.sh`) and the installers no longer look for or remove the old
  flat-layout files. Install once with the new installer and remove the old files yourself.

## [1.1.0] - 2026-09-20

Modular rewrite with a focus on making `uniservice list` correct on all three platforms.

### Changed

- **Code structure**: the flat modules (`utils.py`, `backend_base.py`, `linux_backend.py`, `mac_backend.py`,
  `windows_backend.py`) were replaced by the `uniservice_lib` package:
  - `uniservice_lib/cli.py` – argument parsing, dispatch, TSV rendering
  - `uniservice_lib/backends/{base,linux,macos,windows}.py` – one module per platform behind a common `Backend`
    interface
  - `uniservice_lib/{naming,scope,process,platform_utils,logging_utils,errors}.py` – focused single-purpose helpers
  - `uniservice` is now a thin launcher
- Failure reporting uses an `UniserviceError` hierarchy instead of `SystemExit(str)` raised from deep inside the
  backends; the CLI renders one `FAIL: ...` line and a non-zero status.
- `pyproject.toml` adds package metadata, a `uniservice` console script, ruff and pytest configuration; the project
  now declares Python 3.10+.
- Install scripts copy/download the `uniservice_lib` package (instead of a hard-coded list of modules), remove the
  pre-1.1.0 flat modules, and support `UNISERVICE_REPO_ARCHIVE`.

### Fixed

`list`:

- macOS: a job with no explicit override is now reported as enabled (`yes`) instead of `?`, matching launchd
  semantics and the documented behaviour.
- macOS: domain overrides are merged with "most specific domain wins" instead of last-write-wins, so `user/<uid>` can
  no longer mask `gui/<uid>`.
- macOS: running state no longer depends only on `launchctl list`, which never reports system-scope jobs; it now
  falls back to `launchctl print <domain>/<label>` and reads the authoritative `pid =` field.
- macOS: the `pgrep -f` fallback escapes regular-expression metacharacters and interprets the exit code (`1` =
  not running, anything else = `?`), instead of reporting "not running" on any failure.
- macOS: a missing `launchctl` yields `?` instead of raising.
- Linux: transitional `systemctl is-active` states are no longer reported as `no` (`activating`/`reloading` are
  `yes`, `deactivating` is `no`).
- Linux: `is-enabled`/`is-active` output is parsed from the first token of the first non-empty line of stdout, then
  stderr, so a warning on stderr can no longer corrupt the state.
- Linux: masked units (symlinks to `/dev/null`) are listed again instead of being skipped by the `is_file()` check.
- Linux: unit names are derived by removing the exact prefix/suffix rather than `Path.stem`, and directories or empty
  names are skipped.
- Windows: `list` no longer requires an elevated shell.
- Windows: querying now uses `Get-ScheduledTask`, which is locale-independent; previously `list` returned nothing on
  any non-English Windows because the CSV column headers were matched in English.
- Windows: the `schtasks.exe` fallback strips the UTF-8 BOM and locates the task-name column from the cell values
  rather than the localized header, and reads `Settings/Enabled` from the locale-independent task XML.
- Windows: a failed Task Scheduler query raises a clear error instead of being reported as "no services".
- Windows: `State` values are mapped explicitly (`Running` = `yes`, `Ready`/`Disabled` = `no`, `Queued`/`Unknown` =
  `?`) instead of "anything that is not Running" = `no`.
- All platforms: rows are sorted by name (case-insensitive) and duplicate names are collapsed, so the output order is
  stable and comparable.
- All platforms: control characters in a name are sanitised and empty names are dropped, keeping the output valid
  TSV.

Other:

- Service names are validated: `/`, `\`, control characters, NUL, `.`, `..` and a leading `-` are rejected, which
  previously let `add` create stray directories inside the unit directory.
- `setup_logging()` no longer crashes when the log directory cannot be created.
- Windows `cat` renders the recovered command line with `subprocess.list2cmdline`.

### Added

- `uniservice --version`.
- `logs -f` as a short form of `--follow`.
- `tests/`: 240+ pytest tests covering the naming/scope/process helpers, all three backends (including one
  regression test per fixed `list` bug), the CLI, an end-to-end run of the shipped launcher with stub OS tools, and
  opt-in integration tests that drive the real service manager. Library coverage is ~90%.
- `.github/workflows/ci.yml`: ruff, shellcheck, a PowerShell parse check, and the full test suite on Ubuntu, macOS
  and Windows with Python 3.10 and 3.13.

### Documentation

- Explained how scope is derived and how a **user** install reaches the system scope: `sudo` resets `PATH` to the
  sudoers `secure_path`, which excludes `~/.local/bin`, so a bare `sudo uniservice` only works after a system-wide
  install. With a user install, call `sudo "$(command -v uniservice)" ...`, or link it into `/usr/local/bin`. The
  install scripts and `uniservice --help` now print the same hint.

