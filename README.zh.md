# uniservice

[English](README.md)

跨平台服务管理工具（类似 nssm，但不依赖常驻守护进程），把“长期运行/自启/托管”交给操作系统原生机制：

- Linux：systemd（user/system）
- macOS：launchd（LaunchAgents/LaunchDaemons）
- Windows：计划任务（需要管理员权限）

平台实现细节见：[details.zh.md](details.zh.md)（[English](details.md)）

## 安装

安装脚本会做两件事：

1. 检查是否存在 Python 3（没有会提示先安装）
2. 把 `uniservice` 及其依赖模块复制到 PATH 目录，并写入 profile，把该目录加入环境变量

### macOS

```bash
./install-macos.sh
```

- 非 root：安装到 `~/.local/bin/`，并写入 `~/.profile`
- root：安装到 `/usr/local/bin/`，并写入 `/etc/profile`

安装后重新打开终端验证：

```bash
uniservice --help
```

### Linux

```bash
./install-linux.sh
```

规则同 macOS。

### Windows

PowerShell 执行：

```powershell
.\install-windows.ps1
```

安装到 `%LOCALAPPDATA%\uniservice\bin\`，并更新 PATH（profile + 用户级 PATH）。重开终端生效。

## 使用

### add

```bash
uniservice add --name demo --user --workdir /tmp -- python3 -m http.server 8000
```

- 如果可执行文件不是全路径，uniservice 会尝试从 PATH 自动补全，并给 WARNING。
- 若同名服务已存在，会提示是否覆盖。
- `add` 会执行 `enable` + `start`。

### list

```bash
uniservice list --user
```

输出为 TSV（三列，以制表符分隔）：

- NAME：服务名
- ENABLED：是否启用自启（yes/no/?）
- RUNNING：是否正在运行（yes/no/?）

### 控制

```bash
uniservice enable  --name demo --user
uniservice start   --name demo --user
uniservice stop    --name demo --user
uniservice disable --name demo --user
```

### remove

```bash
uniservice remove --name demo --user
```

`remove` 会先执行 `stop` + `disable` 再删除定义。

### cat

```bash
uniservice cat --name demo --user
```

## 日志

- 控制台：WARNING 及以上
- 文件：DEBUG 及以上
- 日志文件：
  - macOS/Linux：`~/.uniservice/logs/uniservice.log`
  - Windows：`%LOCALAPPDATA%\uniservice\logs\uniservice.log`

## 卸载

卸载包含两部分：

1) 从 PATH 移除 uniservice 命令文件  
2) 删除 uniservice 创建的服务（建议）

macOS/Linux（非 root 安装）：

```bash
rm -f ~/.local/bin/uniservice ~/.local/bin/utils.py ~/.local/bin/backend_base.py ~/.local/bin/linux_backend.py ~/.local/bin/mac_backend.py ~/.local/bin/windows_backend.py
```

macOS/Linux（root 安装）：

```bash
sudo rm -f /usr/local/bin/uniservice /usr/local/bin/utils.py /usr/local/bin/backend_base.py /usr/local/bin/linux_backend.py /usr/local/bin/mac_backend.py /usr/local/bin/windows_backend.py
```

Windows：

```powershell
Remove-Item -Recurse -Force (Join-Path $env:LOCALAPPDATA 'uniservice\bin')
```
