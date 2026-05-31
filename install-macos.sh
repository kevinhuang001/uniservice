#!/usr/bin/env bash
set -euo pipefail

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is not installed. Please install Python 3 first:" 1>&2
  echo "  - Homebrew: brew install python" 1>&2
  echo "  - Or download from https://www.python.org/downloads/macos/" 1>&2
  exit 1
fi

files=(
  "uniservice"
  "utils.py"
  "backend_base.py"
  "linux_backend.py"
  "mac_backend.py"
  "windows_backend.py"
)

script_dir=""
if [[ -n "${BASH_SOURCE[0]:-}" && -f "${BASH_SOURCE[0]}" ]]; then
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi

root_dir="$script_dir"
need_download=false
if [[ -z "$root_dir" ]]; then
  need_download=true
else
  for f in "${files[@]}"; do
    if [[ ! -f "${root_dir}/${f}" ]]; then
      need_download=true
      break
    fi
  done
fi

if [[ "$need_download" == "true" ]]; then
  repo_raw_base="${UNISERVICE_REPO_RAW_BASE:-https://raw.githubusercontent.com/kevinhuang001/uniservice/main}"
  if command -v curl >/dev/null 2>&1; then
    downloader="curl"
  elif command -v wget >/dev/null 2>&1; then
    downloader="wget"
  else
    echo "Neither curl nor wget is installed. Please install one of them first." 1>&2
    exit 1
  fi

  tmp_dir="$(mktemp -d 2>/dev/null || mktemp -d -t uniservice)"
  trap 'rm -rf "$tmp_dir"' EXIT
  root_dir="$tmp_dir"

  for f in "${files[@]}"; do
    url="${repo_raw_base}/${f}"
    dst="${root_dir}/${f}"
    if [[ "$downloader" == "curl" ]]; then
      curl -fsSL "$url" -o "$dst"
    else
      wget -qO "$dst" "$url"
    fi
  done
fi

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
