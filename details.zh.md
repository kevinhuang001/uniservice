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

uniservice 根据生效用户自动判定作用域，没有开关：

- 直接运行：user scope（用户级，`~/.config/systemd/user`、`~/Library/LaunchAgents`）
- `sudo uniservice ...`：system scope（系统级，`/etc/systemd/system`、`/Library/LaunchDaemons`）

`sudo` 会把 `PATH` 重置为 sudoers 的 `secure_path`，其中不含用户安装目录，所以裸写
`sudo uniservice` 只有在 **系统级安装**（`sudo bash install-*.sh`）之后才可用。用户安装请用
绝对路径调用：

```bash
sudo "$(command -v uniservice)" list
```

此时有两处变化：`--` 后面的命令用 **root 的 `PATH`** 解析；定义文件与日志归属 root
（`/root/.uniservice/logs`）。

Windows 上作用域恒为 `system`：`list` 不需要提权，其它命令需要管理员终端。

## list 的跨平台约定

每个后端都返回 `ServiceInfo(name, enabled, running)`，由 CLI 渲染成 TSV（`NAME`、`ENABLED`、`RUNNING`）。共同规则：

- `enabled` / `running` 是三态：平台没有给出确定答案时输出 `?`，绝不会把“未知”当成 `no`。
- 结果按名称排序（忽略大小写），同名行会被合并，因此三平台输出顺序稳定、可直接对比。
- 名称里的制表符、换行、回车和 NUL 会被替换，即使是手工创建的定义也不会破坏 TSV 格式。

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
- 被 mask 的单元是指向 `/dev/null` 的软链接，因此软链接同样会被当作单元文件列出。
- 状态只取“第一行、第一个词”（先看 stdout，再看 stderr），stderr 上的警告不会污染解析结果。
- 识别规则：
  - ENABLED `yes`：`enabled`、`enabled-runtime`
  - ENABLED `no`：`disabled`、`disabled-runtime`、`masked`、`masked-runtime`、`static`、`indirect`、`generated`、
    `transient`、`alias`、`linked`、`linked-runtime`、`bad`、`not-found`
  - RUNNING `yes`：`active`、`activating`、`reloading`
  - RUNNING `no`：`inactive`、`failed`、`deactivating`
  - 其它情况或缺少 `systemctl`：`?`

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
  - `launchctl bootout <domain> <plist>`

### list

- 扫描 `com.uniservice.*.plist` 列出 NAME，并查询状态：
  - ENABLED：`launchctl print-disabled <domain>`。未出现在覆盖表里的 job 视为 **enabled**（launchd 只对显式设置
    过的 job 记录 disabled），只有当所有 domain 查询都失败时才输出 `?`。
  - domain 按“最具体优先”的顺序查询（`gui/<uid>`，然后 `user/<uid>`；system scope 用 `system`），第一个提到该
    label 的 domain 生效。
  - RUNNING：
    1. 先看 `launchctl list`（PID 为 `-` 表示已载入但没有进程）
    2. 否则用 `launchctl print <domain>/<label>` 查找 `pid = <n>`；system scope 的 job 不在 `launchctl list` 中，
       这一步正是为它们准备的
    3. 再否则用命令字符串做 `pgrep -f`（模式按 POSIX ERE 转义）；`pgrep` 退出码 `1` 表示未运行，其它非零码表示 `?`

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

- 主查询（与系统语言无关）：PowerShell
  ```powershell
  Get-ScheduledTask | Where-Object { $_.TaskName -like 'uniservice-*' } |
    Select-Object TaskName, State, Enabled | ConvertTo-Json -Compress
  ```
  `Get-ScheduledTask` 在任何 Windows 语言下都返回固定的英文属性名和状态词，而 `schtasks.exe` 会随系统语言变化。
- 状态推断：
  - ENABLED：`Settings.Enabled`
  - RUNNING：`State`：`Running` => `yes`；`Ready`/`Disabled` => `no`；`Queued`/`Unknown` => `?`
- `list` 是只读操作，因此 **不需要** 管理员权限。
- PowerShell 不可用时的回退：解析 `schtasks.exe /Query /FO CSV /V`。该解析器会去掉 UTF-8 BOM，并根据 **值**
  （叶子名以 `uniservice-` 开头的单元格）来定位任务名列，而不是依赖本地化的表头。ENABLED 则从与语言无关的任务
  XML（`schtasks.exe /Query /TN NAME /XML` 的 `Settings/Enabled`）读取，RUNNING 记为 `?`。
- 若所有查询都失败，命令会报错，而不是假装“没有服务”。

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
