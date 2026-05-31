# uniservice：各平台 add/list/remove/cat/enable/disable/start/stop 原理

本文只介绍不同操作系统上 `uniservice add / list / cat / enable / disable / start / stop / remove` 背后的原生机制与典型落盘位置。

## Linux（systemd）

Linux 上用 systemd 的 `.service` unit 来托管进程（自启/守护/重启均由 systemd 完成）。

**add**

- 写入 unit 文件：
  - `--user`：`~/.config/systemd/user/uniservice-NAME.service`
  - `--system`：`/etc/systemd/system/uniservice-NAME.service`
- unit 的关键字段：
  - `WorkingDirectory=...`（来自 `--workdir`，不传则默认当前目录）
  - `ExecStart=/usr/bin/env bash -lc '<cmd>'`
  - `Restart=always`、`RestartSec=2`
  - `WantedBy=default.target`（user）或 `multi-user.target`（system）
- 让 systemd 识别并启用：
  - `systemctl daemon-reload`
  - `systemctl enable --now uniservice-NAME.service`（user 作用域用 `systemctl --user ...`；等价于 enable + start）
- 若同名服务已存在，uniservice 会提示是否覆盖；选择覆盖会先 remove 再 add。

**enable**

- `systemctl enable uniservice-NAME.service`（user 作用域用 `systemctl --user ...`）

**disable**

- `systemctl disable uniservice-NAME.service`（忽略失败）

**start**

- `systemctl start uniservice-NAME.service`

**stop**

- `systemctl stop uniservice-NAME.service`（忽略失败）

**list**

- 通过扫描对应目录下 `uniservice-*.service` 来列出 NAME，并用 systemd 查询状态：
  - ENABLED：`systemctl is-enabled uniservice-NAME.service`
  - RUNNING：`systemctl is-active uniservice-NAME.service`

**remove**

- 关闭并取消自启（忽略失败）：
  - `systemctl disable --now uniservice-NAME.service`
  - `systemctl reset-failed uniservice-NAME.service`
  - `systemctl daemon-reload`
- 删除 unit 文件。

**cat**

- 读取对应的 unit 文件，从 `WorkingDirectory=` 和 `ExecStart=... -lc '<cmd>'` 里提取工作目录与命令。
- 输出一条等价的 `uniservice add --workdir ... -- ...`，用于复原/迁移。

## macOS（launchd）

macOS 上用 launchd 的 plist（LaunchAgents/LaunchDaemons）描述 job，并通过 `launchctl bootstrap` 注册到 domain 让 launchd 托管。

**add**

- 写入 plist：
  - `--user`：`~/Library/LaunchAgents/com.uniservice.NAME.plist`
  - `--system`：`/Library/LaunchDaemons/com.uniservice.NAME.plist`
- plist 的关键字段：
  - `Label=com.uniservice.NAME`
  - `WorkingDirectory=...`（来自 `--workdir`，不传则默认当前目录）
  - `ProgramArguments=[/bin/bash, -lc, '<cmd>']`
  - `RunAtLoad=true`
  - `KeepAlive=true`
- 注册并拉起：
  - 先尝试 `launchctl bootout ...` 卸载旧的（通常会忽略失败，常见于“原本没加载过”）
  - `launchctl bootstrap <domain> <plist>`
  - 若 `bootstrap` 返回 5（Input/output error），会回退尝试 `launchctl load -w <plist>`
  - `launchctl enable <domain>/<label>`（可能被忽略失败）
  - `launchctl kickstart -k <domain>/<label>`（可能被忽略失败）
- domain 选择：
  - `--system`：`system`
  - `--user`：通常是 `gui/<uid>`（某些会话环境下也可能是 `user/<uid>`）
- 若同名服务已存在，uniservice 会提示是否覆盖；选择覆盖会先 remove 再 add。

**enable**

- 只修改“是否允许启动”的开关：`launchctl enable <domain>/<label>`  
  不负责拉起进程；要运行请用 `start`。

**disable**

- 只修改“是否允许启动”的开关：`launchctl disable <domain>/<label>`  
  不负责停止进程；要停止请用 `stop`。

**start**

- `launchctl bootstrap <domain> <plist>` 后再 `launchctl kickstart -k <domain>/<label>`  
  注意：plist 里 `RunAtLoad=true`，因此 bootstrap/load 本身也可能触发立即启动。

**stop**

- `launchctl stop/kill ...` 后执行 `bootout/unload` 卸载 job，避免被 `KeepAlive=true` 立即拉起

**list**

- 通过扫描对应目录下 `com.uniservice.*.plist` 来列出 NAME，并用 launchd 查询状态：
  - ENABLED：`launchctl print-disabled <domain>`（未标记 disabled 视为 enabled）
  - RUNNING：`launchctl list`（PID 非 `-` 视为 running）

**remove**

- `launchctl bootout <domain> <plist>` 反注册（通常忽略失败）
- 删除 plist 文件。

**cat**

- 读取对应 plist，从 `WorkingDirectory` 与 `ProgramArguments` 中提取工作目录与命令。
- 输出一条等价的 `uniservice add --workdir ... -- ...`，用于复原/迁移。

## Windows（Scheduled Tasks 计划任务）

Windows 上用计划任务实现“开机触发 + SYSTEM 身份运行”的托管方式，通过 `schtasks.exe` 管理任务。

**add**

- 创建任务：
  - 任务名：`uniservice-NAME`
  - 触发：`/SC ONSTART`
  - 运行账号：`/RU SYSTEM`
  - 权限：`/RL HIGHEST`
  - 动作：`/TR "<cmd>"`（一般会包一层 `cmd.exe /c "cd /d <workdir> && <command>"` 以设置工作目录）
- 通常需要管理员权限（否则无法创建 ONSTART + SYSTEM 的任务）。
- 若同名服务已存在，uniservice 会提示是否覆盖；选择覆盖会先 remove 再 add。

**enable**

- `schtasks.exe /Change /TN uniservice-NAME /Enable`

**disable**

- `schtasks.exe /Change /TN uniservice-NAME /Disable`

**start**

- `schtasks.exe /Run /TN uniservice-NAME`

**stop**

- `schtasks.exe /End /TN uniservice-NAME`（忽略失败）

**list**

- `schtasks.exe /Query /FO CSV /V`，筛选 `TaskName` 以 `uniservice-` 开头的任务，并从输出字段推断：
  - ENABLED：`Scheduled Task State`（Enabled/Disabled）
  - RUNNING：`Status`（Running/Ready 等）

**remove**

- `schtasks.exe /End /TN uniservice-NAME`（忽略失败）
- `schtasks.exe /Delete /TN uniservice-NAME /F`（忽略失败）

**cat**

- 读取计划任务的 XML（`schtasks.exe /Query /TN uniservice-NAME /XML`），从动作里提取工作目录与命令。
- 尽可能输出一条等价的 `uniservice add --workdir ... -- ...`；若解析失败则直接输出任务的原始 Command/Arguments。
