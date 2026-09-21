# Changelog

All notable changes to this project are documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- The release workflow uploads the wheel and the sdist to PyPI through
  `pypa/gh-action-pypi-publish`, right after the GitHub release is published. It authenticates with
  the `PYPI_API_TOKEN` secret and skips itself with a notice while that secret is absent, so an
  unconfigured upload never fails a release. Trusted Publishing is a one-line switch: delete the
  `password:` input and add a pending publisher on PyPI for this repository.

### Fixed

- Re-creating a service under the same name starts with an empty log. `create` now removes the
  previous incarnation's captured output on macOS and Windows, so `uniservice logs` cannot show
  requests or errors from a service that no longer exists. On Linux the output belongs to journald,
  which has no per-unit delete, so `logs` still reports that unit's whole journal history.

- `add` rejects a COMMAND whose first word starts with `-` (an extra `--` being the usual cause).
  Every backend runs the command as `<shell> -lc '<cmd>'` and the shell parses that string as a
  script, so `bash -lc '-- python3 -m http.server 8000'` answers `bash: --: invalid option`
  followed by the whole usage text - and `Restart=always` / `KeepAlive=true` repeats it on every
  restart, which looks like the service is flooding its log.

## [1.4.0] - 2026-09-20

### Added

- `uniservice uninstall` (and `--dry-run`): the command removes itself using the manifest its
  installer wrote, instead of making you remember `install.sh --uninstall`. Services are
  deliberately left alone. On POSIX the running file is unlinked directly; on Windows, where a
  running image cannot be deleted, the remaining files are handed to a short-lived `cmd.exe` that
  also prunes the directories that only become empty afterwards, and the same file is registered
  with `MoveFileEx(..., MOVEFILE_DELAY_UNTIL_REBOOT)` so it cannot survive a reboot even if that
  helper is blocked. `install.sh --uninstall` stays as the fallback for when the command is broken
  or already gone.
- `uniservice_lib/installation.py` locates an installation from the running command
  (`sys.executable` when frozen, `sys.argv[0]` for the zipapp) and refuses to delete anything
  outside the recorded prefix, so a tampered manifest cannot point the removal elsewhere.
- `UNISERVICE_BINARY=1` selects the standalone binary for both installers. `iwr ... | iex` evaluates
  the script without writing it to disk, so the Windows one-liner had no way to reach `-Binary`;
  the environment variable gives it one.

### Fixed

- Windows: `install-windows.ps1` wrote the manifest to `<prefix>\manifest` while `install.sh` and
  `uniservice uninstall` both expect `<prefix>/lib/uniservice/manifest`, so the command reported
  "no uniservice installation is recorded" and left everything behind. It now uses the same layout
  (and creates the directory, which `Set-Content` does not do).
- `remove_installation` compared the recorded path against itself instead of the image the process
  is actually running from, so on Windows every file looked like "deleting myself" and was
  deferred. It now compares against `sys.executable` / `sys.argv[0]`.
- Windows: `uniservice.cmd` was deleted from under the `cmd.exe` executing it, which printed
  "The batch file cannot be found."; `.cmd`/`.bat` are deferred with the running image.

### Documentation

- Removed the `pipx install uniservice` / `uv tool install uniservice` instructions: the project has
  never been published to PyPI, and the name is currently unclaimed, so that line was one
  registration away from pointing users at somebody else's package. The documented installation
  routes are now exactly the artifacts a release contains.

## [1.3.0] - 2026-09-20

### Added

- **A second distribution artifact.** Besides the portable zipapp, every release now publishes a
  standalone binary built with PyInstaller (`scripts/build_binary.py`, `packaging/entrypoint.py`).
  It bundles its own CPython, so it needs no Python on the target machine and always runs on
  exactly the interpreter that was verified when it was packaged - which removes the "which
  python3 does this run on?" ambiguity of the zipapp. It is ~24 MB, starts in ~257 ms instead of
  ~38 ms, and PyInstaller cannot cross-compile, so the release builds one asset per platform:
  `uniservice-linux-x86_64`, `uniservice-linux-aarch64`, `uniservice-macos-arm64`,
  `uniservice-macos-x86_64` and `uniservice-windows-x86_64.exe`.
- `install.sh --binary` installs that standalone binary; the default stays the zipapp, which is
  smaller and runs on the Python you already have. `install-windows.ps1` gained `-Binary` in the
  same spirit. When a release has no asset for the current platform, `--binary` says so and
  points at the zipapp.
- `UNISERVICE_REPO_URL` makes the installer point at a mirror or a `file://` tree, which is also
  how the installer tests exercise downloads offline.
- The zipapp now checks `sys.version_info` before importing anything and exits with
  `uniservice requires Python 3.10+, but this is 3.9.2 at /usr/bin/python3` instead of failing
  somewhere inside with a `SyntaxError`.

### Changed

- The installer no longer needs Python at all: it writes the manifest as `key=value`
  (`schema`, `program`, `kind`, `version`, `asset`, `sha256`, `prefix`, `binary`, `installed_at`)
  instead of JSON, and never shells out to an interpreter. `--from` now takes an already built
  zipapp or binary rather than building one from source.
- Every download is verified when the release publishes a `SHA256SUMS` entry for the asset, and a
  downloaded artifact is checked for the platform's executable magic (ELF / Mach-O) or a zipapp
  shebang before it can be installed, so an error page can never land in `/usr/local/bin`.
- CI builds the standalone binary for all five targets on every push, so the matrix cannot rot
  between releases.
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

