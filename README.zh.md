# uniservice

[English](README.md) · [![CI](https://github.com/kevinhuang001/uniservice/actions/workflows/ci.yml/badge.svg)](https://github.com/kevinhuang001/uniservice/actions/workflows/ci.yml)

跨平台服务管理工具，把“长期运行/自启/托管”交给操作系统原生机制：

- Linux：systemd（user/system）
- macOS：launchd（LaunchAgents/LaunchDaemons）
- Windows：计划任务（需要管理员权限）

平台实现细节见：[details.zh.md](details.zh.md)（[English](details.md)）

需要 **Python 3.10+**，运行时没有任何第三方依赖。

## 安装

`uniservice` 的发布产物是**一个自包含的可执行文件**（Python zipapp，约 30 KB，除 Python 3.10+
外无任何依赖）。之所以坚持单文件，是因为它让**一次安装同时服务两种 scope**：同一个
`/usr/local/bin/uniservice`，你自己运行就是用户级服务，`sudo` 运行就是系统级服务。

因此安装器默认装到**共享前缀** `/usr/local`（每个账号的 `PATH` 里本来就有它），没有权限时才退回
`~/.local`。它不会再改 `/etc/profile`，会把创建的每个文件记录进 manifest，并据此精确卸载。

### 一行安装

```bash
# macOS / Linux —— 加 sudo 就装到 /usr/local，否则装到 ~/.local
curl -fsSL https://raw.githubusercontent.com/kevinhuang001/uniservice/main/install.sh | bash
curl -fsSL https://raw.githubusercontent.com/kevinhuang001/uniservice/main/install.sh | sudo bash
```

`install-linux.sh` 和 `install-macos.sh` 作为兼容别名保留，老命令继续可用。

```powershell
# Windows —— 便携布局，装到 %LOCALAPPDATA%\uniservice\bin
iwr -useb https://raw.githubusercontent.com/kevinhuang001/uniservice/main/install-windows.ps1 | iex
```

### 安装器参数

```
--user / --system      选择"安装"的 scope（默认：root -> /usr/local）
--prefix DIR           装到 DIR（即 DIR/bin/uniservice）
--version TAG          安装指定 release，例如 --version v1.2.0
--sha256 HEX           校验下载产物的 SHA-256
--from DIR             从本地代码仓库构建，不走网络
--no-modify-path       不改任何 shell 启动文件，只打印提示
--uninstall            按 manifest 精确卸载
```

```bash
./install.sh --version v1.2.0 --sha256 "$(awk '{print $1}' uniservice.sha256)"
./install.sh --user --prefix "$HOME/opt" --no-modify-path
./install.sh --uninstall
```

每次 release 会发布 `uniservice`（zipapp）、wheel、sdist 和 `SHA256SUMS`；zipapp 的构建是**逐字节
可复现**的，所以固定 `--sha256` 就能得到可验证的安装。仓库还没有 release 时，安装器会退回本地构建
`main` 分支源码包，并明确告诉你。

### 自己校验

```bash
curl -fsSLO https://github.com/kevinhuang001/uniservice/releases/latest/download/uniservice
curl -fsSLO https://github.com/kevinhuang001/uniservice/releases/latest/download/uniservice.sha256
sha256sum -c uniservice.sha256
install -m 0755 uniservice /usr/local/bin/uniservice   # 或 ~/.local/bin
```

### 其它安装方式

```bash
pipx install uniservice        # 或 uv tool install uniservice
# 从源码：
python -m pip install -e ".[dev]"
python scripts/build_zipapp.py --output dist/uniservice   # 自己构建单文件
```

### Windows 说明

便携布局会把 `uniservice.pyz` 和 `uniservice.cmd` 装进 `%LOCALAPPDATA%\uniservice\bin`，并写入
用户 `PATH` 和 PowerShell profile。`-Pipx` 改为用 pipx 安装，`-Uninstall` 撤销便携安装。

重开终端后：

```bash
uniservice --help
```

## 使用

### 作用域（macOS/Linux）

作用域由你的权限决定，没有开关：

| 运行方式 | 作用域 | 定义文件位置 |
| --- | --- | --- |
| `uniservice ...` | user（当前用户） | `~/.config/systemd/user/`、`~/Library/LaunchAgents/` |
| `sudo uniservice ...` | system（整机） | `/etc/systemd/system/`、`/Library/LaunchDaemons/` |

默认前缀是 `/usr/local`（每个账号的 `PATH` 都包含它），所以那里装的 `sudo uniservice ...` 直接可用。
只有 `--user` 安装（前缀 `~/.local`）才需要用绝对路径，因为 `sudo` 会把 `PATH` 重置成 sudoers 的
`secure_path`：

```bash
sudo "$(command -v uniservice)" add demo --workdir /tmp -- python3 -m http.server 8000
```

在 `sudo` 下有两处行为差异：

- `--` 后面的命令是用 **root 的 `PATH`** 解析的，`python3` 可能解析到 `/usr/bin/python3` 而不是你的
  conda/venv；在意的话请传绝对路径；
- 定义文件和日志属于 root（`/root/.uniservice/logs/`）。

也可以把用户安装链接进共享前缀：

```bash
sudo ln -sf "$(command -v uniservice)" /usr/local/bin/uniservice
```

Windows 没有 `sudo`：`uniservice list` 在普通终端即可运行，其它命令需要 **管理员** PowerShell/CMD。

### add

```bash
uniservice add demo --workdir /tmp -- python3 -m http.server 8000
```

- 如果可执行文件不是全路径，uniservice 会尝试从 PATH 自动补全，并给出 WARNING。
- 如果不设置 `--workdir`，默认使用当前目录执行命令。
- 若同名服务已存在，会提示是否覆盖。
- `add` 会执行 `enable` + `start`。

服务名不能包含 `/`、`\`、控制字符或 NUL，不能是 `.`/`..`，也不能以 `-` 开头（这些字符会逃出定义目录或破坏原生
定义格式）。

### list

```bash
uniservice list
```

输出为 TSV（制表符分隔），按名称排序：

| 列 | 含义 |
| --- | --- |
| `NAME` | 服务名 |
| `ENABLED` | 是否启用自启：`yes` / `no` / `?` |
| `RUNNING` | 是否正在运行：`yes` / `no` / `?` |

`?` 表示平台没有给出确定答案（例如缺少 `systemctl`、launchd 查询失败，或单元处于过渡状态），绝不会靠猜。
名称中的控制字符会被替换、重复行会被合并，因此输出始终是合法的 TSV。

### 控制

```bash
uniservice enable  demo
uniservice start   demo
uniservice stop    demo
uniservice disable demo
```

### 状态与日志

```bash
uniservice status demo
uniservice logs   demo --lines 200
uniservice logs   demo --follow      # 或 -f
```

### remove

```bash
uniservice remove demo
```

`remove` 会先执行 `stop` + `disable` 再删除定义。

### cat

```bash
uniservice cat demo
```

打印一条等价的 `uniservice add ...` 命令。

## 日志

- 控制台：WARNING 及以上
- 文件：DEBUG 及以上
- 日志文件：
  - macOS/Linux：`~/.uniservice/logs/uniservice.log`
  - Windows：`%LOCALAPPDATA%\uniservice\logs\uniservice.log`

## 代码结构

```
uniservice                  可执行入口（很薄的启动器，也是 zipapp 运行的入口）
uniservice_lib/
  cli.py                    参数解析与命令分发
  scope.py                  user / system 作用域
  naming.py                 服务名校验与原生定义名
  process.py                子进程封装
  platform_utils.py         平台与权限探测
  logging_utils.py          控制台 + 文件日志
  errors.py                 异常体系
  backends/
    __init__.py             后端选择
    base.py                 Backend 接口、ServiceInfo、状态解析
    linux.py                systemd 单元
    macos.py                launchd 任务
    windows.py              计划任务
scripts/build_zipapp.py     构建单文件发布产物
install.sh                  安装器（前缀、manifest、--uninstall）
install-linux.sh            为保持文档 URL 可用而保留的兼容别名
install-macos.sh
install-windows.ps1         Windows 安装器（便携布局，可选 pipx）
tests/                      pytest 测试（单元、端到端、安装器、可选集成）
.github/workflows/          CI（三平台）与发布流程
```

所有后端实现同一个 `Backend` 接口：新增平台只需要新增一个模块，并在
`uniservice_lib/backends/__init__.py` 中注册。

## 开发

```bash
python -m pip install -e ".[dev]"

ruff check .            # 静态检查
ruff format --check .   # 格式检查
python -m pytest        # 单元 + 端到端测试
```

构建发布产物并对一个临时前缀试跑安装器：

```bash
python scripts/build_zipapp.py --output dist/uniservice
./install.sh --prefix /tmp/uniservice-test --no-modify-path
/tmp/uniservice-test/bin/uniservice --version
./install.sh --uninstall --prefix /tmp/uniservice-test
```

zipapp 构建是确定性的，所以 `pytest tests/test_packaging.py tests/test_install_script.py` 可以拿本地
构建出的产物去比对安装器算出的摘要。

默认测试会 mock 系统命令，因此在三个平台上都能运行。可选的集成测试会真正调用宿主机的服务管理器：

```bash
UNISERVICE_RUN_INTEGRATION=1 python -m pytest -m integration -v
```

CI 会在 Ubuntu、macOS、Windows 上运行静态检查、shellcheck/PowerShell 检查、可复现 zipapp 构建以及
完整测试。推送 `v*` tag 会触发 `.github/workflows/release.yml`，发布 wheel、sdist、zipapp 和
`SHA256SUMS`。

## 卸载

```bash
./install.sh --uninstall              # macOS/Linux，按记录的 manifest 卸载
./install.sh --uninstall --prefix DIR # 装在自定义前缀时
```

```powershell
./install-windows.ps1 -Uninstall      # Windows 便携布局
pipx uninstall uniservice             # 用 pipx 安装的情况
```

安装器只会删除记录在 `<prefix>/lib/uniservice/install.json` 里的内容。它**故意保留**写进 shell 启动文件
的那行 `PATH`，并告诉你该改哪个文件。别忘了先删掉自己创建的服务：

```bash
uniservice list
uniservice remove <name>
```
