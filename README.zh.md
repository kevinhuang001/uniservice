# uniservice

[English](README.md) · [![CI](https://github.com/kevinhuang001/uniservice/actions/workflows/ci.yml/badge.svg)](https://github.com/kevinhuang001/uniservice/actions/workflows/ci.yml)

跨平台服务管理工具，把“长期运行/自启/托管”交给操作系统原生机制：

- Linux：systemd（user/system）
- macOS：launchd（LaunchAgents/LaunchDaemons）
- Windows：计划任务（需要管理员权限）

平台实现细节见：[details.zh.md](details.zh.md)（[English](details.md)）

需要 **Python 3.10+**，运行时没有任何第三方依赖。

## 安装

每次 release 会发布**两种产物**，安装器让你选：

| | 产物 | 体积 | 要求 |
| --- | --- | --- | --- |
| **默认** | 便携 zipapp | ~30 KB | 机器上有 Python 3.10+ |
| `--binary` | 独立二进制 | ~24 MB | 什么都不需要（自带 CPython） |

**推荐默认的 zipapp**：一个很小的文件，在任何平台上内容一致，直接跑你已有的 Python。独立二进制是给
没有 Python 环境的机器准备的；因为 PyInstaller **不能交叉编译**，它必须按 OS + CPU 架构分别构建和发布。

两种方式都把命令装进 `/usr/local/bin/uniservice`，并在 `/usr/local/lib/uniservice/manifest` 里记录。
`/usr/local/bin` 本来就在每个账号的 `PATH` 里，所以安装器不会去改任何 shell 启动文件；一次安装同时服务
两种 scope：`uniservice ...` 管用户级，`sudo uniservice ...` 管系统级。

写 `/usr/local` 需要 root，而安装器**不会偷偷退回别的位置**：不带 `sudo` 运行会直接报错。
没有 `~/.local` 安装，也没有 PATH 改写。

### 一行安装

```bash
# macOS / Linux —— 推荐的便携 zipapp（需要 Python 3.10+）
curl -fsSL https://raw.githubusercontent.com/kevinhuang001/uniservice/main/install.sh | sudo bash

# ……或者完全不需要 Python 的独立二进制
curl -fsSL https://raw.githubusercontent.com/kevinhuang001/uniservice/main/install.sh | sudo bash -s -- --binary
```

```powershell
# Windows —— 默认便携 zipapp（需要 Python 3.10+），或加 -Binary 装独立 exe
iwr -useb https://raw.githubusercontent.com/kevinhuang001/uniservice/main/install-windows.ps1 | iex
./install-windows.ps1 -Binary
```

### 安装器参数

```
--binary               装独立二进制而不是 zipapp
--prefix DIR           装到 DIR 而不是 /usr/local
                       （给打包和测试用，不需要提权）
--version TAG          安装指定 release，例如 --version v1.2.0
--sha256 HEX           校验产物的 SHA-256
                       （默认用 release 里 SHA256SUMS 发布的摘要）
--from FILE            安装本地的 zipapp 或二进制，不走网络
--uninstall            按 manifest 精确卸载
```

```bash
sudo ./install.sh                              # 推荐：zipapp
sudo ./install.sh --binary                     # 不需要 Python
sudo ./install.sh --version v1.2.0             # 固定 release
./install.sh --prefix /tmp/uniservice-test     # 不提权，用于打包/测试
sudo ./install.sh --uninstall
```

zipapp 的构建是**逐字节可复现**的，所以固定 `--sha256` 就能得到可验证的安装。如果某个 release 没有你
这个平台的二进制，安装器会明确告诉你并指向 zipapp。

### Release 产物

| 产物 | 说明 |
| --- | --- |
| `uniservice` | 便携 zipapp（推荐） |
| `uniservice-linux-x86_64`、`uniservice-linux-aarch64` | 独立二进制 |
| `uniservice-macos-arm64`、`uniservice-macos-x86_64` | 独立二进制 |
| `uniservice-windows-x86_64.exe` | 独立二进制 |
| `uniservice-<version>-py3-none-any.whl`、`.tar.gz` | 给 `pipx` / `pip` |
| `SHA256SUMS` | 以上全部的摘要 |

### 自己校验

```bash
base=https://github.com/kevinhuang001/uniservice/releases/latest/download
curl -fsSLO "$base/uniservice" && curl -fsSLO "$base/SHA256SUMS"
grep ' uniservice$' SHA256SUMS | sha256sum -c -
sudo install -m 0755 uniservice /usr/local/bin/uniservice
```

### 其它安装方式

```bash
pipx install uniservice        # 或 uv tool install uniservice
# 从源码：
python -m pip install -e ".[dev]"
python -m pip install -e ".[build]" && python scripts/build_binary.py   # 构建独立二进制
python scripts/build_zipapp.py --output dist/uniservice                 # 构建 zipapp
```

### Windows 说明

默认（zipapp）布局会把 `uniservice.pyz` 和 `uniservice.cmd` 装进 `%LOCALAPPDATA%\uniservice\bin`，并写入
用户 `PATH` 和 PowerShell profile。`-Binary` 则改为把 `uniservice.exe` 装到那里，不需要 shim，也不需要
Python。`-Uninstall` 两种都能撤销。

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

安装器把命令放进 `/usr/local/bin`（每个账号的 `PATH` 都包含它），所以两种用法都不需要额外设置。

在 `sudo` 下有两处行为差异：

- `--` 后面的命令是用 **root 的 `PATH`** 解析的，`python3` 可能解析到 `/usr/bin/python3` 而不是你的
  conda/venv；在意的话请传绝对路径；
- 定义文件和日志属于 root（`/root/.uniservice/logs/`）。

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
scripts/build_zipapp.py     构建便携 zipapp（推荐产物）
scripts/build_binary.py     构建独立二进制（PyInstaller，按平台）
packaging/entrypoint.py     PyInstaller 入口
install.sh                  macOS/Linux 安装器（产物选择、manifest、--uninstall）
install-windows.ps1         Windows 安装器（默认 zipapp，-Binary 装 exe）
tests/                      pytest 测试（单元、端到端、安装器、可选集成）
.github/workflows/          CI（三平台 + 5 个二进制目标）与发布流程
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

构建两种产物，并对一个临时前缀试跑安装器：

```bash
python scripts/build_zipapp.py --output dist/uniservice            # ~30 KB，需要 Python
python -m pip install -e ".[build]"
python scripts/build_binary.py --output-dir dist                   # ~24 MB，自包含

./install.sh --prefix /tmp/uniservice-test --from dist/uniservice
/tmp/uniservice-test/bin/uniservice --version
./install.sh --uninstall --prefix /tmp/uniservice-test
```

zipapp 构建是确定性的，所以 `pytest tests/test_packaging.py tests/test_install_script.py` 可以拿本地构建
出的产物去比对安装器算出的摘要。安装器测试用 `file://` 提供一棵伪造的 release 目录树，因此下载、产物
选择、校验和验证全都在离线状态下被真实执行。

默认测试会 mock 系统命令，因此在三个平台上都能运行。可选的集成测试会真正调用宿主机的服务管理器：

```bash
UNISERVICE_RUN_INTEGRATION=1 python -m pytest -m integration -v
```

CI 会在 Ubuntu、macOS、Windows 上运行静态检查、shellcheck/PowerShell 检查、可复现 zipapp 构建以及完整
测试，并为 5 个目标构建独立二进制。推送 `v*` tag 会触发 `.github/workflows/release.yml`，发布 wheel、
sdist、zipapp、各平台二进制和 `SHA256SUMS`。

## 卸载

```bash
sudo ./install.sh --uninstall          # macOS/Linux，按记录的 manifest 卸载
./install.sh --uninstall --prefix DIR  # 装在自定义前缀时
```

```powershell
./install-windows.ps1 -Uninstall      # Windows 便携布局
pipx uninstall uniservice             # 用 pipx 安装的情况
```

安装器只删除记录在 `/usr/local/lib/uniservice/manifest` 里的内容，并把因此变空的目录清理掉；它从未
写过任何 `PATH` 行，所以没有需要清理的东西。别忘了先删掉自己创建的服务：

```bash
uniservice list
uniservice remove <name>
```
