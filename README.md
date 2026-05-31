# uniservice

[中文说明](README.zh.md)

Cross-platform service manager that delegates long-running processes, autostart and supervision to native OS mechanisms:

- Linux: systemd (user/system)
- macOS: launchd (LaunchAgents/LaunchDaemons)
- Windows: Scheduled Tasks (admin required)

More platform details: [details.md](details.md) ([中文](details.zh.md))

## Install

Install scripts:

1. Check Python 3 exists (otherwise ask you to install it first)
2. Copy `uniservice` and its Python modules into a PATH directory, and append PATH export into profile

### macOS

```bash
curl -fsSL https://raw.githubusercontent.com/kevinhuang001/uniservice/main/install-macos.sh | bash
```

- non-root: installs to `~/.local/bin/` and writes `~/.profile`
- root: installs to `/usr/local/bin/` and writes `/etc/profile`

Reopen terminal, then:

```bash
uniservice --help
```

### Linux

```bash
curl -fsSL https://raw.githubusercontent.com/kevinhuang001/uniservice/main/install-linux.sh | bash
```

Same behavior as macOS.

### Windows

Run in PowerShell:

```powershell
iwr -useb https://raw.githubusercontent.com/kevinhuang001/uniservice/main/install-windows.ps1 | iex
```

It installs to `%LOCALAPPDATA%\uniservice\bin\` and updates PATH (profile + user PATH). Reopen terminal to take effect.

## Usage

### Scope (macOS/Linux)

- Run `uniservice` normally: manages current-user services.
- Run via `sudo uniservice ...`: manages system services.

### Add

```bash
uniservice add --name demo --workdir /tmp -- python3 -m http.server 8000
```

- If the executable is not an absolute path, uniservice will try to resolve it from PATH and print a WARNING.
- If `--workdir` is not provided, the command runs in the current directory.
- If a service with the same name already exists, uniservice will ask whether to overwrite it.
- `add` performs `enable` + `start`.

### List

```bash
uniservice list
```

Output is TSV (tab-separated):

- NAME service name
- ENABLED yes/no/?
- RUNNING yes/no/?

### Control

```bash
uniservice enable  --name demo
uniservice start   --name demo
uniservice stop    --name demo
uniservice disable --name demo
```

### Remove

```bash
uniservice remove --name demo
```

`remove` performs `stop` + `disable` before deleting the definition.

### Cat

```bash
uniservice cat --name demo
```

## Logging

- Console: WARNING and above
- File: DEBUG and above
- Log file:
  - macOS/Linux: `~/.uniservice/logs/uniservice.log`
  - Windows: `%LOCALAPPDATA%\uniservice\logs\uniservice.log`

## Uninstall

Uninstall includes:

1) Remove the `uniservice` command from PATH  
2) Remove services created by uniservice (recommended)

### Remove command files

macOS/Linux (non-root install):

```bash
rm -f ~/.local/bin/uniservice ~/.local/bin/utils.py ~/.local/bin/backend_base.py ~/.local/bin/linux_backend.py ~/.local/bin/mac_backend.py ~/.local/bin/windows_backend.py
```

macOS/Linux (root install):

```bash
sudo rm -f /usr/local/bin/uniservice /usr/local/bin/utils.py /usr/local/bin/backend_base.py /usr/local/bin/linux_backend.py /usr/local/bin/mac_backend.py /usr/local/bin/windows_backend.py
```

Windows:

```powershell
Remove-Item -Recurse -Force (Join-Path $env:LOCALAPPDATA 'uniservice\bin')
```
