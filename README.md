# uniservice

一个跨平台的“服务管理工具”（类似 nssm 的定位，但不依赖常驻守护进程），把“长期运行/自启/托管”交给各平台原生机制：

- Linux：systemd user service / system service
- macOS：launchd LaunchAgents / LaunchDaemons
- Windows：Scheduled Task（计划任务，要求管理员运行）

uniservice 提供统一的命令：

- `uniservice add`：创建并托管一个服务（会注册并尝试启用/拉起）
- `uniservice list`：列出由 uniservice 创建的服务
- `uniservice cat`：复原出服务对应的 add 命令
- `uniservice enable`：启用服务（设置为随系统启动/用户登录自动启动）
- `uniservice disable`：禁用服务（取消自启）
- `uniservice start`：启动服务
- `uniservice stop`：停止服务
- `uniservice remove`：删除由 uniservice 创建的服务

## 安装

uniservice 是 Python 程序。安装脚本会做两件事：

1. 检查是否存在 Python 3（找不到会提示你先安装）
2. 把 `uniservice` 及其依赖模块复制到一个 PATH 目录，并写入 profile，把该目录加入环境变量

### macOS

```bash
./install-macos.sh
```

- 非 root：安装到 `~/.local/bin/`，并写入 `~/.profile`
- root（sudo）：安装到 `/usr/local/bin/`，并写入 `/etc/profile`

安装后请重新打开终端（或重新登录），然后验证：

```bash
uniservice --help
```

### Linux

```bash
./install-linux.sh
```

规则同 macOS：

- 非 root：安装到 `~/.local/bin/`，并写入 `~/.profile`
- root（sudo）：安装到 `/usr/local/bin/`，并写入 `/etc/profile`

安装后重新打开终端验证：

```bash
uniservice --help
```

### Windows

PowerShell 执行：

```powershell
.\install-windows.ps1
```

- 安装目录：`%LOCALAPPDATA%\uniservice\bin\`
- 写入 PowerShell Profile：`$PROFILE`（每次打开 PowerShell 都会把该目录加入 `$env:Path`）
- 同时设置用户级 PATH（保证 CMD/其它进程也可用，通常需要重新打开终端生效）

安装后重新打开 PowerShell 或 CMD 验证：

```powershell
uniservice --help
```

## 使用

### 1) 创建服务（add）

基本用法：

```bash
uniservice add --name demo --user -- python3 -m http.server 8000
```

- `--name`：服务名（uniservice 只管理自己创建的服务）
- `--user` / `--system`：
  - macOS/Linux 默认是 `--user`
  - `--system` 需要 root（`sudo ...`）
- `--` 后面是你要运行的命令及参数
- 若同名服务已存在，会提示是否覆盖（非交互环境会直接报错退出）
 - `add` 默认会执行 `enable` + `start`

指定工作目录（不写默认当前目录）：

```bash
uniservice add --name demo --user --workdir /tmp -- python3 -m http.server 8000
```

### 2) 列出服务（list）

```bash
uniservice list --user
```

输出为制表符分隔（TSV）三列：

- NAME：服务名
- ENABLED：是否启用自启（yes/no/?）
- RUNNING：是否正在运行（yes/no/?）

系统级服务（macOS/Linux 需要 root）：

```bash
sudo uniservice list --system
```

### 3) 删除服务（remove）

```bash
uniservice remove --name demo --user
```

系统级服务（macOS/Linux 需要 root）：

```bash
sudo uniservice remove --name demo --system
```

`remove` 默认会执行 `stop` + `disable` 后再删除。

### enable/disable 与 start/stop 的关系

- `enable/disable`：只控制“是否允许自启/是否允许被拉起”
- `start/stop`：只控制“当前是否运行”
- `add/remove`：是组合动作（add=enable+start，remove=stop+disable+删除定义）

### 4) 复原服务命令（cat）

把已创建的服务“还原成一条可重新执行的 add 命令”（便于迁移/排查）：

```bash
uniservice cat --name demo --user
```

## 日志

- 控制台：只输出 WARNING 及以上日志
- 文件：记录全部日志（DEBUG 及以上）
- 日志文件位置：
  - macOS/Linux：`~/.uniservice/logs/uniservice.log`
  - Windows：`%LOCALAPPDATA%\uniservice\logs\uniservice.log`

## 平台实现细节（你需要知道的点）

### Linux（systemd）

- user scope：
  - unit 文件：`~/.config/systemd/user/uniservice-NAME.service`
  - 管理命令：`systemctl --user ...`
- system scope：
  - unit 文件：`/etc/systemd/system/uniservice-NAME.service`
  - 管理命令：`systemctl ...`
- 创建时会执行：
  - `daemon-reload`
  - `enable --now`
- 进程由 systemd 托管，异常退出会按 unit 配置重启（当前配置为 `Restart=always`）

### macOS（launchd）

- user scope：
  - plist：`~/Library/LaunchAgents/com.uniservice.NAME.plist`
  - domain：`gui/<uid>`（并兼容尝试 `user/<uid>`）
- system scope：
  - plist：`/Library/LaunchDaemons/com.uniservice.NAME.plist`
  - domain：`system`
- 创建时会执行：
  - `launchctl bootout ...`（卸载旧的，同步静默处理）
  - `launchctl bootstrap ...`
  - `launchctl enable ...`（忽略失败）
  - `launchctl kickstart -k ...`（忽略失败）

### Windows（Scheduled Task）

- 仅支持“管理员权限执行 uniservice”（不是管理员会直接报错退出）
- 任务名：`uniservice-NAME`
- 触发：ONSTART（开机触发），账号 SYSTEM
- 目前实现基于计划任务而不是 SCM 真正的 Windows Service

## 卸载

卸载包含两部分：

1) 卸载 uniservice 命令本身（从 PATH 中移除）
2) 删除 uniservice 创建的服务（如果你不再需要这些服务）

### 1) 卸载 uniservice 命令

#### macOS / Linux

如果是非 root 安装：

```bash
rm -f ~/.local/bin/uniservice ~/.local/bin/utils.py ~/.local/bin/backend_base.py ~/.local/bin/linux_backend.py ~/.local/bin/mac_backend.py ~/.local/bin/windows_backend.py
```

并在 `~/.profile` 中删除这一行（如果你不再需要它）：

```bash
export PATH="$HOME/.local/bin:$PATH"
```

如果是 root（sudo）安装：

```bash
sudo rm -f /usr/local/bin/uniservice /usr/local/bin/utils.py /usr/local/bin/backend_base.py /usr/local/bin/linux_backend.py /usr/local/bin/mac_backend.py /usr/local/bin/windows_backend.py
```

并在 `/etc/profile` 中删除这一行（如果你不再需要它）：

```bash
export PATH="/usr/local/bin:$PATH"
```

#### Windows

删除安装目录：

```powershell
Remove-Item -Recurse -Force (Join-Path $env:LOCALAPPDATA 'uniservice\bin')
```

并从以下两处移除 PATH 注入（按你公司环境习惯选择保留/删除）：

- 用户级 PATH：系统环境变量里把 `%LOCALAPPDATA%\uniservice\bin` 删掉
- PowerShell Profile：编辑 `$PROFILE`，删除包含 `uniservice\bin` 的那段代码

### 2) 删除 uniservice 创建的服务

建议在卸载命令前先把服务删掉：

- macOS/Linux：`uniservice list ...` 找到名字后 `uniservice remove ...`
- Windows：同样 `uniservice list` / `uniservice remove`（需要管理员 PowerShell）

示例：

```bash
uniservice list --user
uniservice remove --name demo --user
```

系统级：

```bash
sudo uniservice list --system
sudo uniservice remove --name demo --system
```
