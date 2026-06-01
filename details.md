# Platform internals

[中文说明](details.zh.md)

This document explains how `uniservice` maps commands to native OS mechanisms:

- `add`
- `list`
- `cat`
- `status`
- `logs`
- `enable`
- `disable`
- `start`
- `stop`
- `remove`

## Scope (macOS/Linux)

uniservice decides scope automatically:

- Normal execution: user scope
- `sudo uniservice ...`: system scope

## Linux (systemd)

Linux uses systemd `.service` units. Autostart, supervision and restarts are handled by systemd.

### add

- Write a unit file:
  - user scope: `~/.config/systemd/user/uniservice-NAME.service`
  - system scope: `/etc/systemd/system/uniservice-NAME.service`
- Key fields:
  - `WorkingDirectory=...` (from `--workdir`, defaults to current directory)
  - `ExecStart=/usr/bin/env bash -lc '<cmd>'`
  - `Restart=always`, `RestartSec=2`
  - `WantedBy=default.target` (user) or `multi-user.target` (system)
- Reload and activate:
  - `systemctl daemon-reload`
  - `systemctl enable --now uniservice-NAME.service` (user scope uses `systemctl --user ...`)
- If a service with the same name exists, uniservice asks before overwriting.

### enable / disable

- `enable`: `systemctl enable uniservice-NAME.service`
- `disable`: `systemctl disable uniservice-NAME.service`

### start / stop

- `start`: `systemctl start uniservice-NAME.service`
- `stop`: `systemctl stop uniservice-NAME.service`

### list

- Scan `uniservice-*.service` in the unit directory to list names.
- For each service:
  - ENABLED: `systemctl is-enabled uniservice-NAME.service`
  - RUNNING: `systemctl is-active uniservice-NAME.service`

### remove

- Stop + disable, then remove the unit file:
  - `systemctl disable --now uniservice-NAME.service`
  - `systemctl reset-failed uniservice-NAME.service`
  - `systemctl daemon-reload`

### cat

- Read the unit file and extract:
  - `WorkingDirectory=`
  - the shell command inside `ExecStart=... bash -lc '<cmd>'`
- Print an equivalent `uniservice add NAME --workdir ... -- ...`.

### status

- Delegates to systemd status output:
  - system scope: `systemctl status uniservice-NAME.service`
  - user scope: `systemctl --user status uniservice-NAME.service`

### logs

- Delegates to journald:
  - system scope: `journalctl -u uniservice-NAME.service -n <lines> [-f]`
  - user scope: `journalctl --user-unit uniservice-NAME.service -n <lines> [-f]`

## macOS (launchd)

macOS uses launchd plists (LaunchAgents/LaunchDaemons) and `launchctl` to manage jobs.

### add

- Write a plist:
  - user scope: `~/Library/LaunchAgents/com.uniservice.NAME.plist`
  - system scope: `/Library/LaunchDaemons/com.uniservice.NAME.plist`
- Key fields:
  - `Label=com.uniservice.NAME`
  - `WorkingDirectory=...` (from `--workdir`, defaults to current directory)
  - `ProgramArguments=[/bin/bash, -lc, '<cmd>']`
  - `RunAtLoad=true`
  - `KeepAlive=true`
- Register and start:
  - `launchctl bootstrap <domain> <plist>`
  - If `bootstrap` fails with exit code 5 (Input/output error), fall back to `launchctl load -w <plist>` for compatibility.
  - `launchctl enable <domain>/<label>`
  - `launchctl kickstart -k <domain>/<label>`
- Domain selection:
  - system scope: `system`
  - user scope: typically `gui/<uid>` (some sessions use `user/<uid>`)

### enable / disable

- `enable`: only flips the “allowed to run” flag: `launchctl enable <domain>/<label>`  
  It does not start the process by itself.
- `disable`: only flips the “allowed to run” flag: `launchctl disable <domain>/<label>`  
  It does not stop the process by itself.

Note: because the plist contains `RunAtLoad=true`, some load/register operations may start the job immediately.

### start

- Ensure the job is registered, then start it:
  - `launchctl bootstrap <domain> <plist>`
  - `launchctl kickstart -k <domain>/<label>`

### stop

- Stop/terminate and unload the job to prevent `KeepAlive=true` from instantly restarting it:
  - `launchctl stop/kill ...`
  - `launchctl bootout ...` (and legacy unload when needed)

### list

- Scan `com.uniservice.*.plist` in the plist directory to list names.
- For each service:
  - ENABLED: `launchctl print-disabled <domain>` (not listed as disabled => enabled)
  - RUNNING:
    - try `launchctl list` (PID present => running)
    - if not available, fall back to `pgrep -f` on the command string

### remove

- Unregister/unload the job and delete the plist file:
  - `launchctl bootout <domain> <plist>` (best-effort)
  - delete plist

### cat

- Read the plist and extract:
  - `WorkingDirectory`
  - the command in `ProgramArguments`
- Print an equivalent `uniservice add NAME --workdir ... -- ...`.

### status

- Delegates to launchd’s job inspection:
  - user scope: `launchctl print gui/<uid>/com.uniservice.NAME` (or `user/<uid>` fallback)
  - system scope: `launchctl print system/com.uniservice.NAME`

### logs

- launchd itself does not provide a unified per-job log viewer.
- uniservice writes `StandardOutPath` / `StandardErrorPath` into the plist and tails those files:
  - user scope: `~/.uniservice/services/NAME.out.log` and `~/.uniservice/services/NAME.err.log`
  - system scope: `/var/log/uniservice/NAME.out.log` and `/var/log/uniservice/NAME.err.log`

## Windows (Scheduled Tasks)

Windows uses Scheduled Tasks managed via `schtasks.exe`.

### add

- Create a task:
  - Task name: `uniservice-NAME`
  - Trigger: `/SC ONSTART`
  - Account: `/RU SYSTEM`
  - Privilege: `/RL HIGHEST`
  - Action: `/TR "<cmd>"` (typically wraps `cmd.exe /c "cd /d <workdir> && <command>"` to set working directory)
- Admin privileges are required to create ONSTART + SYSTEM tasks.

### enable / disable

- `enable`: `schtasks.exe /Change /TN uniservice-NAME /Enable`
- `disable`: `schtasks.exe /Change /TN uniservice-NAME /Disable`

### start / stop

- `start`: `schtasks.exe /Run /TN uniservice-NAME`
- `stop`: `schtasks.exe /End /TN uniservice-NAME`

### list

- `schtasks.exe /Query /FO CSV /V`, filter tasks with `TaskName` starting with `uniservice-`.
- Infer:
  - ENABLED from `Scheduled Task State` (Enabled/Disabled)
  - RUNNING from `Status` (Running/Ready/etc.)

### remove

- Stop, then delete:
  - `schtasks.exe /End /TN uniservice-NAME`
  - `schtasks.exe /Delete /TN uniservice-NAME /F`

### cat

- Read task XML: `schtasks.exe /Query /TN uniservice-NAME /XML`
- Extract workdir + command from the action fields.
- Print an equivalent `uniservice add NAME --workdir ... -- ...` when possible; otherwise print raw Command/Arguments.

### status

- Delegates to Task Scheduler’s verbose query output:
  - `schtasks.exe /Query /TN uniservice-NAME /V /FO LIST`

### logs

- Scheduled Tasks do not provide a unified “service logs” viewer.
- uniservice appends stdout/stderr redirections to the task action so logs are captured:
  - `%ProgramData%\uniservice\logs\services\NAME.out.log`
  - `%ProgramData%\uniservice\logs\services\NAME.err.log`
- `logs --follow` tails the log files via PowerShell `Get-Content -Wait`.
