#!/usr/bin/env bash
set -euo pipefail

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is not installed. Please install Python 3 first:" 1>&2
  echo "  - Homebrew: brew install python" 1>&2
  echo "  - Or download from https://www.python.org/downloads/macos/" 1>&2
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
    echo "File not found: ${root_dir}/${f}" 1>&2
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

echo "OK: Installed to ${dst}"
echo "Hint: Reopen your terminal, then run: uniservice"
