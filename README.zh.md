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
| — | Python 包（[PyPI](https://pypi.org/project/uniservice/)） | ~37 KB | pipx、uv 或 pip + Python 3.10+ |

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
# Windows —— 推荐的便携 zipapp（需要 Python 3.10+）
iwr -useb https://raw.githubusercontent.com/kevinhuang001/uniservice/main/install-windows.ps1 | iex

# ……或者完全不需要 Python 的独立 exe
$env:UNISERVICE_BINARY = 1; iwr -useb https://raw.githubusercontent.com/kevinhuang001/uniservice/main/install-windows.ps1 | iex
```

管道喂给 `iex` 时磁盘上没有文件，所以用 `UNISERVICE_BINARY` 环境变量来选择产物。想用开关参数的话，
先把脚本下载下来：

```powershell
iwr -useb https://raw.githubusercontent.com/kevinhuang001/uniservice/main/install-windows.ps1 -OutFile install-windows.ps1
./install-windows.ps1 -Binary
```

`install.sh` 同样认 `UNISERVICE_BINARY=1`。

### PyPI

`uniservice` 也发布在 [PyPI](https://pypi.org/project/uniservice/) 上。请用**全局**方式安装，
因为只有它会把命令放到 `sudo` 能找到的地方：

```bash
sudo pipx install --global uniservice    # venv 在 /opt/pipx，命令在 /usr/local/bin
uniservice --help                        # ……而且 `sudo uniservice ...` 也能用
```

`pipx --global` 写的是 `/opt/pipx` 和 `/usr/local/bin`，和安装器的落点完全一致。它的前提是 pipx 本身
为系统级安装（apt、brew 或官方独立安装脚本）；用 `pip install --user` 装的 pipx 无法在 `sudo` 下运行。

用户级安装当然也能用，只是命令落在你的家目录里，而 `sudo` 永远不会去那里找：

| 安装方式 | 命令落在 | `sudo uniservice` |
| --- | --- | --- |
| `sudo pipx install --global uniservice`（**推荐**） | `/usr/local/bin`（venv 在 `/opt/pipx`） | 正常 |
| `./install.sh`（上面那种） | `/usr/local/bin` | 正常 |
| `pipx install uniservice` | `~/.local/bin` | **找不到** |
| `uv tool install uniservice` | `~/.local/bin` | **找不到** |

`sudo` 会用 `secure_path` 重新拼 `PATH`，其中永远不含你的家目录，所以用户级安装对它就是不存在。
`sudo "$(command -v uniservice)" ...` 也能凑合，代价是 root 依赖于你家目录里的 venv。
`uv tool install` 自己没有全局模式 —— 想用 uv 装成系统级只能自己重定向 `UV_TOOL_DIR`，
所以受支持的 `/usr/local/bin/uniservice` 来源就两个：pipx 和安装器。

卸载请用当初安装它的工具 —— `pipx uninstall uniservice` 或 `uv tool uninstall uniservice`。
`uniservice self uninstall` 不会碰不是自己装的副本，并会明确告诉你。

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
| `uniservice-<version>-py3-none-any.whl`、`.tar.gz` | 同一份代码的 Python 包，PyPI 上也有 |
| `SHA256SUMS` | 以上全部的摘要 |

### 自己校验

```bash
base=https://github.com/kevinhuang001/uniservice/releases/latest/download
curl -fsSLO "$base/uniservice" && curl -fsSLO "$base/SHA256SUMS"
grep ' uniservice$' SHA256SUMS | sha256sum -c -
sudo install -m 0755 uniservice /usr/local/bin/uniservice
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

```
uniservice <command> [options]
```

| 命令 | 作用 |
| --- | --- |
| `list`、`ls` | 列出 uniservice 管理的服务 |
| `add NAME -- COMMAND...` | 创建、启用并启动一个服务 |
| `start`、`stop`、`restart NAME...` | 改变运行状态 |
| `enable`、`disable NAME...` | 改变是否开机/登录自启 |
| `remove`、`rm NAME...` | 停止、禁用并删除服务 |
| `status [NAME]` | `NAME` 的原生状态；不带参数则是全部服务的表格 |
| `logs NAME [-f]` | 打印捕获的输出 |
| `show NAME` | 服务是怎么定义的，以及如何重建它 |
| `self info`、`self uninstall` | 管理 uniservice 自身的安装 |
| `doctor` | 端到端体检这台机器 |
| `version` | 打印各组件版本 |

所有控制类命令都接受**一个或多个**名字并逐个汇报，所以 `uniservice restart api worker` 是一条命令；
只要其中任何一个失败，整体退出码就是非零。

安装类命令放在 `self` 下面是有意的：`uniservice remove NAME` 删的是**服务**，`uniservice self uninstall`
删的是 **uniservice 自己**。在命令树里把这件事说清楚，`uniservice --help` 才不会读起来像是两者平级。

### 作用域（macOS/Linux）

作用域来自你的权限，而不是某个开关：

| 运行方式 | 作用域 | 定义文件位置 |
| --- | --- | --- |
| `uniservice ...` | 用户级 | `~/.config/systemd/user/`、`~/Library/LaunchAgents/` |
| `sudo uniservice ...` | 系统级 | `/etc/systemd/system/`、`/Library/LaunchDaemons/` |

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

- 如果可执行文件不是全路径，uniservice 会从 PATH 解析它（用 `-v` 可以看到）。
- 如果不设置 `--workdir`，默认使用当前目录执行命令。
- 若同名服务已存在，会提示是否覆盖。
- `add` 会执行 `enable` + `start`，然后打印命令、工作目录和它写下的定义文件。

服务名不能包含 `/`、`\`、控制字符或 NUL，不能是 `.`/`..`，也不能以 `-` 开头（这些字符会逃出定义目录或破坏原生
定义格式）。

### list

```bash
uniservice list              # 终端里是表格，被重定向时是 TSV
uniservice list --table      # 管道里也画表格：uniservice list --table | less
uniservice list --json       # 机器可读
uniservice list --quiet      # 只输出名字
```

表格有三列：

| 列 | 含义 |
| --- | --- |
| `NAME` | 服务名 |
| `ENABLED` | 是否启用自启：`yes` / `no` / `?` |
| `RUNNING` | 是否正在运行：`yes` / `no` / `?` |

`?` 表示平台没有给出确定答案（例如缺少 `systemctl`、launchd 查询失败，或单元处于过渡状态），绝不会靠猜。
名称中的控制字符会被替换、重复行会被合并，因此 TSV 形式始终合法。

当 stdout 不是终端时，输出就是既有的制表符契约 `NAME<TAB>ENABLED<TAB>RUNNING`（含表头），所以已有脚本
不需要任何改动。

### 控制

```bash
uniservice start   demo
uniservice stop    demo
uniservice restart demo        # 一次原生 restart，而不是 stop + start
uniservice enable  demo        # 开机/登录自启
uniservice disable demo
uniservice restart api worker  # 一次操作多个
```

### 状态与日志

```bash
uniservice status              # 全部服务的表格 + 一行汇总
uniservice status demo         # 先是 uniservice 的结论，再是原生工具自己的输出
uniservice logs   demo         # 最后 200 行
uniservice logs   demo -n 50
uniservice logs   demo -f      # 持续跟随
```

`status NAME` 和 `logs NAME` 是故意把终端交给原生工具的：它的输出**就是**答案，重新排版 `systemctl status`
或 `journalctl` 只会丢信息。

### show

```bash
uniservice show demo
```

```
demo · user scope
  command   /usr/bin/python3 -m http.server 8000
  workdir   /srv/demo
  location  /home/me/.config/systemd/user/uniservice-demo.service

recreate it with:
  uniservice add demo --workdir /srv/demo -- /usr/bin/python3 -m http.server 8000
```

`--json` 给出同样的字段（含 `recreate`）。

### remove

```bash
uniservice remove demo
uniservice rm demo api         # 一次停止、禁用并删除多个
```

`remove` 会先执行 `stop` + `disable` 再删除定义。

### self

```bash
uniservice self info            # 这份命令装在哪、是怎么装的
uniservice self uninstall       # 把它删掉
uniservice self uninstall --dry-run
```

### doctor 与 version

```bash
uniservice doctor
```

```
uniservice doctor
  ✔ python           3.13.5 (/usr/bin/python3)
  ✔ platform         linux (linux)
  ✔ privileges       normal user · user scope
  ✔ installation     not managed by install.sh; that is fine for pipx, uv or a source checkout
  ✔ log file         /home/me/.uniservice/logs/uniservice.log
  ✔ systemctl        /usr/bin/systemctl
  ✔ journalctl       /usr/bin/journalctl
  ✔ systemd manager  running (systemctl --user is-system-running)
  ✔ unit directory   /home/me/.config/systemd/user

all good
```

`doctor` 会检查解释器、平台、权限、安装方式和日志文件，然后让后端去探测原生监督器：systemd（包括
`is-system-running`——在从未用 systemd 启动的容器里，正是这一项会失败）、launchd 的各个 domain，或任务计划程序。
非致命项的失败（可选工具缺失、日志文件不可写）只作为警告汇报，不影响退出码。

`uniservice version` 则打印各组件的版本，是往 issue 里粘贴用的。

### 输出规则

| 参数 | 效果 |
| --- | --- |
| `--color=auto\|always\|never` | 颜色；`auto` 表示终端、未设 `NO_COLOR` 且 `TERM` 不是 `dumb` |
| `--ascii` | 用 ASCII 的 `v x -` 代替 `✔ ✘ • ─` |
| `--json` | 在支持的命令上向 stdout 输出一份 JSON |
| `-q`、`--quiet` | 只报错误；`list` 只输出名字 |
| `-v`、`--verbose` | 在 stderr 上打开 debug 日志 |

颜色与 Unicode 每次运行只判定一次：被重定向的 stdout 永远不会拿到 ANSI 转义，而使用旧代码页的 Windows 控制台
会自动退回 ASCII 字符集。

## 日志

- 控制台：WARNING 及以上（`-v` 降到 DEBUG），带 `uniservice:` 前缀
- 文件：DEBUG 及以上，带时间戳
- 日志文件：
  - macOS/Linux：`~/.uniservice/logs/uniservice.log`
  - Windows：`%LOCALAPPDATA%\uniservice\logs\uniservice.log`

## 代码结构

```
uniservice                  可执行入口（很薄的启动器，也是 zipapp 运行的入口）
uniservice_lib/
  cli.py                    入口：解析、构造 Context、分发、退出码
  parser.py                 命令树与分组帮助文本
  console.py                展示层：tty/颜色/Unicode、表格、JSON
  exitcodes.py              退出码常量
  commands/
    __init__.py             Context：console + scope + backend，以及权限规则
    service.py              list、add、start/stop/restart、enable/disable、remove、status、logs、show
    selfcmd.py              self info、self uninstall
    diagnostics.py          doctor、version
  scope.py                  user / system 作用域
  naming.py                 服务名校验与原生定义名
  process.py                子进程封装
  platform_utils.py         平台与权限探测
  logging_utils.py          控制台 + 文件日志
  errors.py                 异常体系
  installation.py           安装器留下的 manifest
  backends/
    __init__.py             后端选择
    base.py                 Backend 接口、ServiceInfo、ServiceDefinition、Check
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

后端**返回数据**，由展示层负责渲染：`definition()` 描述一个服务，`checks()` 描述运行环境，
`command_line()` 按该平台 shell 的规则拼命令行。只有 `status()` 和 `logs()` 会直接输出，因为那里原生工具
自己的输出**就是**答案。

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

`uniservice` 可以自己删掉自己：

```bash
sudo uniservice self uninstall        # 装在自定义前缀时直接：uniservice self uninstall
uniservice self uninstall --dry-run   # 先看看会删什么
```

它读取安装器写下的 manifest（`/usr/local/lib/uniservice/manifest`），只删除记录过的文件，并把因此
变空的目录清理掉。安装器从未写过任何 `PATH` 行，所以没有别的东西要清。Windows 上正在运行的 `.exe`
无法删除自己，命令会把最后这个文件交给一个短命 helper，命令返回后稍等片刻它就消失了。

**你自己创建的服务不受影响** —— 只删命令本身。不想要的服务请在命令还在的时候先删掉：

```bash
uniservice list
uniservice remove <name>
```

如果命令已经损坏或已被删掉，安装器仍然可以收拾残局：

```bash
sudo ./install.sh --uninstall          # macOS/Linux，同一份 manifest
./install.sh --uninstall --prefix DIR  # 装在自定义前缀时
./install-windows.ps1 -Uninstall       # Windows
```
