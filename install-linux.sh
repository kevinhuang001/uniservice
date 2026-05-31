#!/usr/bin/env bash
set -euo pipefail

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 未安装。请先安装 Python 3：" 1>&2
  echo "  - Debian/Ubuntu: sudo apt-get update && sudo apt-get install -y python3" 1>&2
  echo "  - RHEL/CentOS/Fedora: sudo dnf install -y python3  (或 sudo yum install -y python3)" 1>&2
  echo "  - Arch: sudo pacman -S python" 1>&2
  exit 1
fi

root_dir="$(cd "$(dirname "$0")" && pwd)"
files=(
  "uniservice"
  "utils.py"
  "backend_base.py"
  "linux_backend.py"
  "mac_backend.py"
  "windows_backend.py"
)

for f in "${files[@]}"; do
  if [[ ! -f "${root_dir}/${f}" ]]; then
    echo "未找到 ${root_dir}/${f}" 1>&2
    exit 1
  fi
done

chmod +x "${root_dir}/uniservice"

if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
  bin_dir="/usr/local/bin"
else
  bin_dir="${HOME}/.local/bin"
  mkdir -p "$bin_dir"
fi

for f in "${files[@]}"; do
  cp -f "${root_dir}/${f}" "${bin_dir}/${f}"
done
chmod +x "${bin_dir}/uniservice"

dst="${bin_dir}/uniservice"

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  profile="${HOME}/.profile"
  export_line='export PATH="$HOME/.local/bin:$PATH"'
  if ! grep -Fqs "$export_line" "$profile" 2>/dev/null; then
    printf "\n%s\n" "$export_line" >>"$profile"
  fi
else
  profile="/etc/profile"
  export_line='export PATH="/usr/local/bin:$PATH"'
  if ! grep -Fqs "$export_line" "$profile" 2>/dev/null; then
    printf "\n%s\n" "$export_line" >>"$profile"
  fi
fi

echo "OK: 已安装到 ${dst}"
echo "提示: 重新打开终端后可直接使用 uniservice"
