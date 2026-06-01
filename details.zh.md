# 平台实现细节

[English](details.md)

本文只介绍不同操作系统上 `uniservice` 各命令背后的原生机制与典型落盘位置：

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

## 作用域（macOS/Linux）

uniservice 会自动判定作用域：

- 直接运行：user scope（用户级）
- `sudo uniservice ...`：system scope（系统级）

## Linux（systemd）

Linux 上用 systemd 的 `.service` unit 来托管进程（自启/守护/重启均由 systemd 完成）。

### add

- 写入 unit 文件：
  - user scope：`~/.config/systemd/user/uniservice-NAME.service`
  - system scope：`/etc/systemd/system/uniservice-NAME.service`
- unit 的关键字段：
  - `WorkingDirectory=...`（来自 `--workdir`，不传则默认当前目录）
  - `ExecStart=/usr/bin/env bash -lc '<cmd>'`
  - `Restart=always`、`RestartSec=2`
  - `WantedBy=default.target`（user）或 `multi-user.target`（system）
- 让 systemd 识别并启用：
  - `systemctl daemon-reload`
  - `systemctl enable --now uniservice-NAME.service`（user 作用域用 `systemctl --user ...`；等价于 enable + start）
- 若同名服务已存在，uniservice 会提示是否覆盖；选择覆盖会先 remove 再 add。

### enable / disable

- `enable`：`systemctl enable uniservice-NAME.service`（user 作用域用 `systemctl --user ...`）
- `disable`：`systemctl disable uniservice-NAME.service`

### start / stop

- `start`：`systemctl start uniservice-NAME.service`
- `stop`：`systemctl stop uniservice-NAME.service`

### list

- 通过扫描对应目录下 `uniservice-*.service` 来列出 NAME，并用 systemd 查询状态：
  - ENABLED：`systemctl is-enabled uniservice-NAME.service`
  - RUNNING：`systemctl is-active uniservice-NAME.service`

### remove

- 关闭并取消自启：
  - `systemctl disable --now uniservice-NAME.service`
  - `systemctl reset-failed uniservice-NAME.service`
  - `systemctl daemon-reload`
- 删除 unit 文件。

### cat

- 读取对应的 unit 文件，从 `WorkingDirectory=` 和 `ExecStart=... -lc '<cmd>'` 里提取工作目录与命令。
- 输出一条等价的 `uniservice add NAME --workdir ... -- ...`，用于复原/迁移。

### status

- 直接调用 systemd 的 status 输出：
  - system scope：`systemctl status uniservice-NAME.service`
  - user scope：`systemctl --user status uniservice-NAME.service`

### logs

- 直接调用 journald：
  - system scope：`journalctl -u uniservice-NAME.service -n <lines> [-f]`
  - user scope：`journalctl --user-unit uniservice-NAME.service -n <lines> [-f]`

## macOS（launchd）

macOS 上用 launchd 的 plist（LaunchAgents/LaunchDaemons）描述 job，并通过 `launchctl` 管理。

### add

- 写入 plist：
  - user scope：`~/Library/LaunchAgents/com.uniservice.NAME.plist`
  - system scope：`/Library/LaunchDaemons/com.uniservice.NAME.plist`
- plist 的关键字段：
  - `Label=com.uniservice.NAME`
  - `WorkingDirectory=...`（来自 `--workdir`，不传则默认当前目录）
  - `ProgramArguments=[/bin/bash, -lc, '<cmd>']`
  - `RunAtLoad=true`
  - `KeepAlive=true`
- 注册并启动：
  - `launchctl bootstrap <domain> <plist>`
  - 若 `bootstrap` 返回 5（Input/output error），会回退尝试 `launchctl load -w <plist>`（兼容一些环境差异）
  - `launchctl enable <domain>/<label>`
  - `launchctl kickstart -k <domain>/<label>`
- domain 选择：
  - system scope：`system`
  - user scope：通常是 `gui/<uid>`（某些会话环境下也可能是 `user/<uid>`）

### enable / disable

- `enable`：只修改“是否允许启动”的开关：`launchctl enable <domain>/<label>`；不负责拉起进程
- `disable`：只修改“是否允许启动”的开关：`launchctl disable <domain>/<label>`；不负责停止进程

注意：因为 plist 里包含 `RunAtLoad=true`，某些“载入/注册”动作本身可能会触发立即启动。

### start

- 确保已注册后启动：
  - `launchctl bootstrap <domain> <plist>`
  - `launchctl kickstart -k <domain>/<label>`

### stop

- 停止并卸载 job，避免 `KeepAlive=true` 立刻拉起：
  - `launchctl stop/kill ...`
  - `launchctl bootout ...`（必要时配合 legacy unload）

### list

- 扫描 `com.uniservice.*.plist` 列出 NAME，并查询状态：
  - ENABLED：`launchctl print-disabled <domain>`（未标记 disabled 视为 enabled）
  - RUNNING：优先 `launchctl list`；拿不到时回退 `pgrep -f`（按命令字符串判断）

### remove

- 反注册/卸载并删除 plist：
  - `launchctl bootout <domain> <plist>`（尽力而为）
  - 删除 plist 文件

### cat

- 读取 plist，从 `WorkingDirectory` 与 `ProgramArguments` 中提取工作目录与命令。
- 输出一条等价的 `uniservice add NAME --workdir ... -- ...`。

### status

- 直接用 launchd 的 job 检查能力：
  - user scope：`launchctl print gui/<uid>/com.uniservice.NAME`（或回退 `user/<uid>`）
  - system scope：`launchctl print system/com.uniservice.NAME`

### logs

- launchd 本身没有统一的 per-job 日志查看器。
- uniservice 会在 plist 写入 `StandardOutPath` / `StandardErrorPath`，并通过 `tail` 读取对应文件：
  - user scope：`~/.uniservice/services/NAME.out.log` 与 `~/.uniservice/services/NAME.err.log`
  - system scope：`/var/log/uniservice/NAME.out.log` 与 `/var/log/uniservice/NAME.err.log`

## Windows（Scheduled Tasks 计划任务）

Windows 上用计划任务实现托管，通过 `schtasks.exe` 管理任务。

### add

- 创建任务：
  - 任务名：`uniservice-NAME`
  - 触发：`/SC ONSTART`
  - 运行账号：`/RU SYSTEM`
  - 权限：`/RL HIGHEST`
  - 动作：`/TR "<cmd>"`（通常包一层 `cmd.exe /c "cd /d <workdir> && <command>"` 以设置工作目录）
- 通常需要管理员权限（否则无法创建 ONSTART + SYSTEM 的任务）。

### enable / disable

- `enable`：`schtasks.exe /Change /TN uniservice-NAME /Enable`
- `disable`：`schtasks.exe /Change /TN uniservice-NAME /Disable`

### start / stop

- `start`：`schtasks.exe /Run /TN uniservice-NAME`
- `stop`：`schtasks.exe /End /TN uniservice-NAME`

### list

- `schtasks.exe /Query /FO CSV /V`，筛选 `TaskName` 以 `uniservice-` 开头的任务，并从输出字段推断：
  - ENABLED：`Scheduled Task State`（Enabled/Disabled）
  - RUNNING：`Status`（Running/Ready 等）

### remove

- 停止后删除：
  - `schtasks.exe /End /TN uniservice-NAME`
  - `schtasks.exe /Delete /TN uniservice-NAME /F`

### cat

- 读取计划任务的 XML（`schtasks.exe /Query /TN uniservice-NAME /XML`），从动作里提取工作目录与命令。
- 尽可能输出等价的 `uniservice add NAME --workdir ... -- ...`；若解析失败则输出任务的原始 Command/Arguments。

### status

- 直接用计划任务的 verbose 输出：
  - `schtasks.exe /Query /TN uniservice-NAME /V /FO LIST`

### logs

- 计划任务本身没有统一的“服务日志”查看器。
- uniservice 会在任务动作里追加 stdout/stderr 重定向，把日志落到文件：
  - `%ProgramData%\uniservice\logs\services\NAME.out.log`
  - `%ProgramData%\uniservice\logs\services\NAME.err.log`
- `logs --follow` 会用 PowerShell `Get-Content -Wait` 跟随输出。
