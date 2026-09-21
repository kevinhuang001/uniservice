# uniservice

[中文说明](README.zh.md) · [![CI](https://github.com/kevinhuang001/uniservice/actions/workflows/ci.yml/badge.svg)](https://github.com/kevinhuang001/uniservice/actions/workflows/ci.yml)

Cross-platform service manager that delegates long-running processes, autostart and supervision to native OS mechanisms:

- Linux: systemd (user/system)
- macOS: launchd (LaunchAgents/LaunchDaemons)
- Windows: Scheduled Tasks (admin required)

More platform details: [details.md](details.md) ([中文](details.zh.md))

Requires **Python 3.10+**. No third-party runtime dependencies.

## Install

Every release publishes **two artifacts**, and the installer lets you pick one:

| | Artifact | Size | Requires |
| --- | --- | --- | --- |
| **default** | portable zipapp | ~30 KB | Python 3.10+ on the machine |
| `--binary` | standalone binary | ~24 MB | nothing (bundles its own CPython) |
| — | Python package ([PyPI](https://pypi.org/project/uniservice/)) | ~37 KB | pipx, uv or pip + Python 3.10+ |

**The zipapp is the recommended default**: one small file that is byte-identical on every
platform, and it runs on the Python you already have. The standalone binary exists for machines
with no Python environment; because PyInstaller cannot cross-compile, it is built and published
separately for each OS and CPU architecture.

Either way the command lands in `/usr/local/bin/uniservice` and is recorded in
`/usr/local/lib/uniservice/manifest`. `/usr/local/bin` is already on `PATH` for every account, so
the installer never edits a shell profile, and one installation serves both scopes:
`uniservice ...` for per-user services and `sudo uniservice ...` for system services.

Writing to `/usr/local` needs root, and the installer does not silently fall back somewhere else:
**run it with `sudo` or it stops with an error**. No `~/.local` install, no PATH edits.

### One-liner

```bash
# macOS / Linux — the recommended portable zipapp (needs Python 3.10+)
curl -fsSL https://raw.githubusercontent.com/kevinhuang001/uniservice/main/install.sh | sudo bash

# ... or the standalone binary, which needs no Python at all
curl -fsSL https://raw.githubusercontent.com/kevinhuang001/uniservice/main/install.sh | sudo bash -s -- --binary
```

```powershell
# Windows — the recommended portable zipapp (needs Python 3.10+)
iwr -useb https://raw.githubusercontent.com/kevinhuang001/uniservice/main/install-windows.ps1 | iex

# ... or the standalone .exe, which needs no Python at all
$env:UNISERVICE_BINARY = 1; iwr -useb https://raw.githubusercontent.com/kevinhuang001/uniservice/main/install-windows.ps1 | iex
```

Piping into `iex` leaves no file on disk, so the artifact is selected with the
`UNISERVICE_BINARY` environment variable. If you would rather use the switch, download the script
first:

```powershell
iwr -useb https://raw.githubusercontent.com/kevinhuang001/uniservice/main/install-windows.ps1 -OutFile install-windows.ps1
./install-windows.ps1 -Binary
```

The same `UNISERVICE_BINARY=1` environment variable works for `install.sh`.

### PyPI

`uniservice` is published on [PyPI](https://pypi.org/project/uniservice/) as well, so any Python
package frontend can install it:

```bash
pipx install uniservice        # or: uv tool install uniservice
uniservice --help
```

This route is a normal Python entry point, so where the command lands depends on the frontend —
and that decides whether `sudo uniservice ...` can find it:

| How you install it | Command lands in | `sudo uniservice` |
| --- | --- | --- |
| `pipx install uniservice` | `~/.local/bin` | **not found** |
| `sudo pipx install --global uniservice` | `/usr/local/bin` (venv in `/opt/pipx`) | works |
| `./install.sh` (above) | `/usr/local/bin` | works |

`sudo` builds its own `PATH` from `secure_path`, which never contains your home directory, so a
per-user install is invisible to it. For system services use `sudo pipx install --global`, or the
installer; `sudo "$(command -v uniservice)" ...` also works, at the cost of depending on a venv
inside your home directory. Note that `sudo pipx` only works when pipx itself was installed
system-wide (apt, brew, or the standalone installer), not with `pip install --user`.

Uninstall with the frontend that installed it — `pipx uninstall uniservice` or
`uv tool uninstall uniservice`. `uniservice uninstall` refuses to touch a copy it did not install
and tells you so.

### Installer options

```
--binary               install the standalone binary instead of the zipapp
--prefix DIR           install under DIR instead of /usr/local
                       (for packaging and tests; needs no elevated privileges)
--version TAG          install a specific release, e.g. --version v1.2.0
--sha256 HEX           verify the artifact against this digest
                       (by default the digest published in SHA256SUMS is used)
--from FILE            install a local zipapp or binary instead of downloading
--uninstall            remove a previous installation, using its manifest
```

```bash
sudo ./install.sh                                  # recommended: the zipapp
sudo ./install.sh --binary                         # no Python needed
sudo ./install.sh --version v1.2.0                 # pin a release
./install.sh --prefix /tmp/uniservice-test         # unprivileged, for packaging/tests
sudo ./install.sh --uninstall
```

The zipapp build is byte-for-byte reproducible, so pinning a `--sha256` gives a verifiable
install. When a release has no asset for your platform the installer says so and points at the
zipapp alternative.

### Release assets

| Asset | Notes |
| --- | --- |
| `uniservice` | the portable zipapp (recommended) |
| `uniservice-linux-x86_64`, `uniservice-linux-aarch64` | standalone binaries |
| `uniservice-macos-arm64`, `uniservice-macos-x86_64` | standalone binaries |
| `uniservice-windows-x86_64.exe` | standalone binary |
| `uniservice-<version>-py3-none-any.whl`, `.tar.gz` | the same code as a Python package, also on PyPI |
| `SHA256SUMS` | digests for everything above |

### Verify the checksum yourself

```bash
base=https://github.com/kevinhuang001/uniservice/releases/latest/download
curl -fsSLO "$base/uniservice" && curl -fsSLO "$base/SHA256SUMS"
grep ' uniservice$' SHA256SUMS | sha256sum -c -
sudo install -m 0755 uniservice /usr/local/bin/uniservice
```

### Windows notes

The default (zipapp) layout installs `uniservice.pyz` plus a `uniservice.cmd` shim into
`%LOCALAPPDATA%\uniservice\bin` and adds it to your user `PATH` and PowerShell profile.
`-Binary` installs `uniservice.exe` there instead, with no shim and no Python requirement.
`-Uninstall` reverses either.

Reopen the terminal, then:

```bash
uniservice --help
```

## Usage

### Scope (macOS/Linux)

The scope is derived from your privileges, not from a flag:

| How you run it | Scope | Definitions live in |
| --- | --- | --- |
| `uniservice ...` | user | `~/.config/systemd/user/`, `~/Library/LaunchAgents/` |
| `sudo uniservice ...` | system | `/etc/systemd/system/`, `/Library/LaunchDaemons/` |

Because the installer puts the command in `/usr/local/bin` (on every account's `PATH`), both
forms work with no further setup.

Two things change under `sudo`:

- the command after `--` is resolved with **root's** `PATH`, so `python3` may
  resolve to `/usr/bin/python3` instead of your conda/venv copy — pass an
  absolute path when that matters;
- the definition and its logs belong to root (`/root/.uniservice/logs/`).

On Windows there is no `sudo`: `uniservice list` works in any shell, every other
command needs an **Administrator** PowerShell/CMD.

### Add

```bash
uniservice add demo --workdir /tmp -- python3 -m http.server 8000
```

- If the executable is not an absolute path, uniservice will try to resolve it from PATH and print a WARNING.
- If `--workdir` is not provided, the command runs in the current directory.
- If a service with the same name already exists, uniservice will ask whether to overwrite it.
- `add` performs `enable` + `start`.

Service names must not contain `/`, `\`, control characters or NUL, must not be `.`/`..`, and must not start with `-`
(those characters would escape the definition directory or break the native definition format).

### List

```bash
uniservice list
```

Output is TSV (tab-separated), sorted by name:

| Column | Meaning |
| --- | --- |
| `NAME` | service name |
| `ENABLED` | starts automatically: `yes` / `no` / `?` |
| `RUNNING` | currently running: `yes` / `no` / `?` |

`?` means the platform did not give a definitive answer (for example `systemctl` is missing, the launchd override
query failed, or a unit is in a transitional state). It is never a guess. Names containing control characters are
sanitised and duplicate rows are collapsed, so the output always stays valid TSV.

### Control

```bash
uniservice enable  demo
uniservice start   demo
uniservice stop    demo
uniservice disable demo
```

### Status and logs

```bash
uniservice status demo
uniservice logs   demo --lines 200
uniservice logs   demo --follow      # or -f
```

### Remove

```bash
uniservice remove demo
```

`remove` performs `stop` + `disable` before deleting the definition.

### Cat

```bash
uniservice cat demo
```

Prints an equivalent `uniservice add ...` command for the service.

## Logging

- Console: WARNING and above
- File: DEBUG and above
- Log file:
  - macOS/Linux: `~/.uniservice/logs/uniservice.log`
  - Windows: `%LOCALAPPDATA%\uniservice\logs\uniservice.log`

## Project layout

```
uniservice                  executable entry point (thin launcher, and what the zipapp runs)
uniservice_lib/
  cli.py                    argument parsing and command dispatch
  scope.py                  user vs. system scope
  naming.py                 service-name validation and native definition names
  process.py                subprocess helpers
  platform_utils.py         platform and privilege detection
  logging_utils.py          console + file logging
  errors.py                 exception hierarchy
  backends/
    __init__.py             backend selection
    base.py                 Backend interface, ServiceInfo, state parsing
    linux.py                systemd units
    macos.py                launchd jobs
    windows.py              Scheduled Tasks
scripts/build_zipapp.py     builds the portable zipapp (the recommended artifact)
scripts/build_binary.py     builds the standalone binary (PyInstaller, per platform)
packaging/entrypoint.py     PyInstaller entry point
install.sh                  macOS/Linux installer (artifact choice, manifest, --uninstall)
install-windows.ps1         Windows installer (zipapp by default, -Binary for the .exe)
tests/                      pytest suite (unit, end-to-end, installer, opt-in integration)
.github/workflows/          CI (3 platforms + 5 binary targets) and the release workflow
```

Each backend implements the same `Backend` interface, so adding a platform means adding one module and registering it
in `uniservice_lib/backends/__init__.py`.

## Development

```bash
python -m pip install -e ".[dev]"

ruff check .            # lint
ruff format --check .   # formatting
python -m pytest        # unit + end-to-end tests
```

Build both artifacts and try the installer against a throwaway prefix:

```bash
python scripts/build_zipapp.py --output dist/uniservice            # ~30 KB, needs Python
python -m pip install -e ".[build]"
python scripts/build_binary.py --output-dir dist                   # ~24 MB, self-contained

./install.sh --prefix /tmp/uniservice-test --from dist/uniservice
/tmp/uniservice-test/bin/uniservice --version
./install.sh --uninstall --prefix /tmp/uniservice-test
```

The zipapp build is deterministic, so `pytest tests/test_packaging.py tests/test_install_script.py` can compare a
locally built artifact against the digest the installer computes. The installer tests serve a fake release over
`file://`, so they exercise the download, the asset selection and the checksum verification without the network.

The default suite mocks the native tools, so it runs on every platform. Opt-in integration tests drive the real
service manager of the host:

```bash
UNISERVICE_RUN_INTEGRATION=1 python -m pytest -m integration -v
```

CI runs lint, shellcheck/PowerShell checks, the reproducible zipapp build, the full test suite on Ubuntu, macOS and
Windows, and builds the standalone binary for five targets. Pushing a `v*` tag runs
`.github/workflows/release.yml`, which publishes the wheel, the sdist, the zipapp, every platform binary and
`SHA256SUMS` as a GitHub release.

## Uninstall

`uniservice` removes itself:

```bash
sudo uniservice uninstall        # or: uniservice uninstall, for a --prefix install
uniservice uninstall --dry-run   # show what would be removed first
```

It reads the manifest its installer wrote (`/usr/local/lib/uniservice/manifest`), deletes exactly
those files and prunes the directories that become empty. It never added a `PATH` line, so there is
nothing else to clean up. On Windows the running `.exe` cannot delete itself, so the command hands
that last file to a short-lived helper and it disappears a moment after the command returns.

**Your services are untouched** - only the command is removed. Delete the services you no longer
want first, while the command still exists:

```bash
uniservice list
uniservice remove <name>
```

If the command is already broken or gone, the installer can still clean up after it:

```bash
sudo ./install.sh --uninstall              # macOS/Linux, same manifest
./install.sh --uninstall --prefix DIR      # if you installed to a custom prefix
./install-windows.ps1 -Uninstall           # Windows
```
