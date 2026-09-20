# uniservice

[中文说明](README.zh.md) · [![CI](https://github.com/kevinhuang001/uniservice/actions/workflows/ci.yml/badge.svg)](https://github.com/kevinhuang001/uniservice/actions/workflows/ci.yml)

Cross-platform service manager that delegates long-running processes, autostart and supervision to native OS mechanisms:

- Linux: systemd (user/system)
- macOS: launchd (LaunchAgents/LaunchDaemons)
- Windows: Scheduled Tasks (admin required)

More platform details: [details.md](details.md) ([中文](details.zh.md))

Requires **Python 3.10+**. No third-party runtime dependencies.

## Install

`uniservice` ships as **one self-contained executable file** (a Python zipapp, ~30 KB, no
dependencies beyond Python 3.10+). Having a single file is what lets *one* installation serve
both scopes: the same `/usr/local/bin/uniservice` runs as you (per-user services) and through
`sudo` (system services).

The installer therefore defaults to a **shared prefix** (`/usr/local`, which is already on
`PATH` for every account) and only falls back to `~/.local` when there is no permission to
do that. It never edits `/etc/profile`, it records everything it created in a manifest, and it
can undo the installation exactly.

### One-liner

```bash
# macOS / Linux — installs to /usr/local when run with sudo, to ~/.local otherwise
curl -fsSL https://raw.githubusercontent.com/kevinhuang001/uniservice/main/install.sh | bash
curl -fsSL https://raw.githubusercontent.com/kevinhuang001/uniservice/main/install.sh | sudo bash
```

`install-linux.sh` and `install-macos.sh` are kept as compatibility aliases for the same
installer, so existing commands keep working.

```powershell
# Windows — portable layout under %LOCALAPPDATA%\uniservice\bin
iwr -useb https://raw.githubusercontent.com/kevinhuang001/uniservice/main/install-windows.ps1 | iex
```

### Installer options

```
--user / --system      choose the scope of the *installation* (default: root -> /usr/local)
--prefix DIR           install under DIR (DIR/bin/uniservice)
--version TAG          install a specific release, e.g. --version v1.2.0
--sha256 HEX           verify the downloaded artifact against this digest
--from DIR             build from a local checkout instead of downloading
--no-modify-path       never edit shell startup files, only print instructions
--uninstall            remove a previous installation, using its manifest
```

```bash
./install.sh --version v1.2.0 --sha256 "$(cat uniservice.sha256 | awk '{print $1}')"
./install.sh --user --prefix "$HOME/opt" --no-modify-path
./install.sh --uninstall
```

Each release publishes `uniservice` (the zipapp), a wheel, an sdist and `SHA256SUMS`; the
zipapp build is byte-for-byte reproducible, so pinning a `--sha256` gives a verifiable
install. When the repository has no release yet the installer falls back to building the
`main` branch archive locally and says so.

### Verify the checksum yourself

```bash
curl -fsSLO https://github.com/kevinhuang001/uniservice/releases/latest/download/uniservice
curl -fsSLO https://github.com/kevinhuang001/uniservice/releases/latest/download/uniservice.sha256
sha256sum -c uniservice.sha256
install -m 0755 uniservice /usr/local/bin/uniservice   # or ~/.local/bin
```

### Alternatives

```bash
pipx install uniservice        # or: uv tool install uniservice
# from a checkout:
python -m pip install -e ".[dev]"
python scripts/build_zipapp.py --output dist/uniservice   # build the single file yourself
```

### Windows notes

The portable layout installs `uniservice.pyz` plus a `uniservice.cmd` shim into
`%LOCALAPPDATA%\uniservice\bin` and adds it to your user `PATH` and PowerShell profile.
`-Pipx` installs through pipx instead, and `-Uninstall` reverses a portable install.

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

Because the default install prefix is `/usr/local` (already on every account's `PATH`),
`sudo uniservice ...` works out of the box there. Only a `--user` install (prefix `~/.local`) needs
the absolute path, since `sudo` resets `PATH` to the sudoers `secure_path`:

```bash
sudo "$(command -v uniservice)" add demo --workdir /tmp -- python3 -m http.server 8000
```

Two things change under `sudo`:

- the command after `--` is resolved with **root's** `PATH`, so `python3` may
  resolve to `/usr/bin/python3` instead of your conda/venv copy — pass an
  absolute path when that matters;
- the definition and its logs belong to root (`/root/.uniservice/logs/`).

Alternatively link the user install into the shared prefix once:

```bash
sudo ln -sf "$(command -v uniservice)" /usr/local/bin/uniservice
```

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
scripts/build_zipapp.py     builds the single-file release artifact
install.sh                  the installer (prefix, manifest, --uninstall)
install-linux.sh            compatibility aliases kept for the documented URLs
install-macos.sh
install-windows.ps1         Windows installer (portable layout, pipx opt-in)
tests/                      pytest suite (unit, end-to-end, installer, opt-in integration)
.github/workflows/          CI (3 platforms) and the release workflow
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

Build the release artifact and try the installer against a throwaway prefix:

```bash
python scripts/build_zipapp.py --output dist/uniservice
./install.sh --prefix /tmp/uniservice-test --no-modify-path
/tmp/uniservice-test/bin/uniservice --version
./install.sh --uninstall --prefix /tmp/uniservice-test
```

The zipapp build is deterministic, so `pytest tests/test_packaging.py tests/test_install_script.py`
can compare a locally built artifact against the digest the installer computes.

The default suite mocks the native tools, so it runs on every platform. Opt-in integration tests drive the real
service manager of the host:

```bash
UNISERVICE_RUN_INTEGRATION=1 python -m pytest -m integration -v
```

CI runs lint, shellcheck/PowerShell checks, a reproducible-zipapp build and the full test suite on Ubuntu, macOS and
Windows. Pushing a `v*` tag runs `.github/workflows/release.yml`, which publishes the wheel, the sdist, the zipapp
and `SHA256SUMS` as a GitHub release.

## Uninstall

```bash
./install.sh --uninstall              # macOS/Linux, uses the recorded manifest
./install.sh --uninstall --prefix DIR # if you installed to a custom prefix
```

```powershell
./install-windows.ps1 -Uninstall      # Windows portable layout
pipx uninstall uniservice             # if you installed with pipx
```

The installer removes exactly what it recorded in `<prefix>/lib/uniservice/install.json`. It leaves the
`PATH` line it added to your shell startup file behind on purpose and tells you which file to edit.
Remember to remove the services you created first:

```bash
uniservice list
uniservice remove <name>
```
