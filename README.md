# uniservice

[中文说明](README.zh.md) · [![CI](https://github.com/kevinhuang001/uniservice/actions/workflows/ci.yml/badge.svg)](https://github.com/kevinhuang001/uniservice/actions/workflows/ci.yml)

Cross-platform service manager that delegates long-running processes, autostart and supervision to native OS mechanisms:

- Linux: systemd (user/system)
- macOS: launchd (LaunchAgents/LaunchDaemons)
- Windows: Scheduled Tasks (admin required)

More platform details: [details.md](details.md) ([中文](details.zh.md))

Requires **Python 3.10+**. No third-party runtime dependencies.

## Install

Install scripts:

1. Check that Python 3.10+ exists (otherwise ask you to install it first)
2. Copy `uniservice` and its `uniservice_lib` package into a PATH directory, and append PATH export into the profile

Run the script from a checkout to install those exact files, or pipe it from the web to install the latest `main`.

### macOS

```bash
curl -fsSL https://raw.githubusercontent.com/kevinhuang001/uniservice/main/install-macos.sh | bash
```

- For a system-wide install (so `sudo uniservice ...` uses the same version):
  ```bash
  curl -fsSL https://raw.githubusercontent.com/kevinhuang001/uniservice/main/install-macos.sh | sudo bash
  ```

- non-root: installs to `~/.local/bin/` and writes `~/.profile`
- root: installs to `/usr/local/bin/` and writes `/etc/profile`

### Linux

```bash
curl -fsSL https://raw.githubusercontent.com/kevinhuang001/uniservice/main/install-linux.sh | bash
```

For a system-wide install:

```bash
curl -fsSL https://raw.githubusercontent.com/kevinhuang001/uniservice/main/install-linux.sh | sudo bash
```

Same behavior as macOS.

### Windows

Run in PowerShell:

```powershell
iwr -useb https://raw.githubusercontent.com/kevinhuang001/uniservice/main/install-windows.ps1 | iex
```

It installs to `%LOCALAPPDATA%\uniservice\bin\` and updates PATH (profile + user PATH).

Reopen the terminal, then:

```bash
uniservice --help
```

### From source

```bash
git clone https://github.com/kevinhuang001/uniservice.git
cd uniservice
python -m pip install -e ".[dev]"   # optional: also installs pytest and ruff
```

## Usage

### Scope (macOS/Linux)

- Run `uniservice` normally: manages current-user services.
- Run via `sudo uniservice ...`: manages system services.

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
uniservice                  executable entry point (thin launcher)
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
tests/                      pytest suite (unit, end-to-end, opt-in integration)
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

The default suite mocks the native tools, so it runs on every platform. Opt-in integration tests drive the real
service manager of the host:

```bash
UNISERVICE_RUN_INTEGRATION=1 python -m pytest -m integration -v
```

CI runs lint, shellcheck/PowerShell checks and the full test suite on Ubuntu, macOS and Windows.

## Uninstall

Uninstall includes:

1) Remove the `uniservice` command from PATH
2) Remove services created by uniservice (recommended)

macOS/Linux (non-root install):

```bash
rm -rf ~/.local/bin/uniservice ~/.local/bin/uniservice_lib
rm -f  ~/.local/bin/utils.py ~/.local/bin/backend_base.py ~/.local/bin/linux_backend.py ~/.local/bin/mac_backend.py ~/.local/bin/windows_backend.py
```

macOS/Linux (root install):

```bash
sudo rm -rf /usr/local/bin/uniservice /usr/local/bin/uniservice_lib
sudo rm -f  /usr/local/bin/utils.py /usr/local/bin/backend_base.py /usr/local/bin/linux_backend.py /usr/local/bin/mac_backend.py /usr/local/bin/windows_backend.py
```

Windows:

```powershell
Remove-Item -Recurse -Force (Join-Path $env:LOCALAPPDATA 'uniservice\bin')
```
