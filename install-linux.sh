#!/usr/bin/env bash
#
# Install the uniservice command for the current user (or system-wide with sudo).
#
# Two modes:
#   1. Run from a checkout: copies ./uniservice and ./uniservice_lib
#   2. Piped from the web:  downloads the repository archive and copies from it
#
# Environment overrides:
#   UNISERVICE_REPO_ARCHIVE  archive URL (default: the GitHub `main` tarball)
#
set -euo pipefail

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is not installed. Please install Python 3.10+ first:" 1>&2
  echo "  - Debian/Ubuntu: sudo apt-get update && sudo apt-get install -y python3" 1>&2
  echo "  - RHEL/CentOS/Fedora: sudo dnf install -y python3  (or sudo yum install -y python3)" 1>&2
  echo "  - Arch: sudo pacman -S python" 1>&2
  exit 1
fi

default_archive="https://github.com/kevinhuang001/uniservice/archive/refs/heads/main.tar.gz"

# ---------------------------------------------------------------------------
# Locate the sources: an existing checkout first, the release archive second.
# ---------------------------------------------------------------------------
script_dir=""
script_source="${BASH_SOURCE[0]:-}"
case "$script_source" in
  ""|"-"|bash|/dev/fd/*|/proc/self/fd/*|/dev/stdin)
    script_dir=""
    ;;
  *)
    if [[ -f "$script_source" ]]; then
      script_dir="$(cd "$(dirname "$script_source")" && pwd)"
    fi
    ;;
esac

tmp_dir=""
cleanup() {
  if [[ -n "$tmp_dir" && -d "$tmp_dir" ]]; then
    rm -rf "$tmp_dir"
  fi
}
trap cleanup EXIT

root_dir="$script_dir"
need_download=false
if [[ -z "$root_dir" || ! -f "${root_dir}/uniservice" || ! -d "${root_dir}/uniservice_lib" ]]; then
  need_download=true
fi

if [[ "$need_download" == "true" ]]; then
  archive_url="${UNISERVICE_REPO_ARCHIVE:-$default_archive}"

  if command -v curl >/dev/null 2>&1; then
    downloader="curl"
  elif command -v wget >/dev/null 2>&1; then
    downloader="wget"
  else
    echo "Neither curl nor wget is installed. Please install one of them first." 1>&2
    exit 1
  fi

  if ! command -v tar >/dev/null 2>&1; then
    echo "tar is required to unpack the uniservice archive." 1>&2
    exit 1
  fi

  tmp_dir="$(mktemp -d 2>/dev/null || mktemp -d -t uniservice)"
  archive="${tmp_dir}/uniservice.tar.gz"
  if [[ "$downloader" == "curl" ]]; then
    curl -fsSL "$archive_url" -o "$archive"
  else
    wget -qO "$archive" "$archive_url"
  fi
  tar -xzf "$archive" -C "$tmp_dir"

  shopt -s nullglob
  candidates=("${tmp_dir}"/uniservice-*/)
  shopt -u nullglob
  if [[ "${#candidates[@]}" -eq 0 ]]; then
    echo "Could not find the unpacked uniservice sources in the archive." 1>&2
    exit 1
  fi
  root_dir="${candidates[0]%/}"
fi

if [[ ! -f "${root_dir}/uniservice" || ! -d "${root_dir}/uniservice_lib" ]]; then
  echo "Invalid uniservice sources in ${root_dir}" 1>&2
  exit 1
fi

chmod +x "${root_dir}/uniservice"

# ---------------------------------------------------------------------------
# Copy the command and its package into a PATH directory.
# ---------------------------------------------------------------------------
if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
  bin_dir="/usr/local/bin"
else
  bin_dir="${HOME}/.local/bin"
  mkdir -p "$bin_dir"
fi

cp -f "${root_dir}/uniservice" "${bin_dir}/uniservice"
rm -rf "${bin_dir}/uniservice_lib"
cp -R "${root_dir}/uniservice_lib" "${bin_dir}/uniservice_lib"
rm -rf "${bin_dir}/uniservice_lib/__pycache__"
chmod +x "${bin_dir}/uniservice"

# Remove modules from the pre-1.1.0 flat layout so a stale copy cannot shadow
# the package.
for legacy in utils.py backend_base.py linux_backend.py mac_backend.py windows_backend.py; do
  rm -f "${bin_dir}/${legacy}"
done

dst="${bin_dir}/uniservice"

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  profile="${HOME}/.profile"
  # shellcheck disable=SC2016  # the literal $HOME/$PATH must be written to the profile
  export_line='export PATH="$HOME/.local/bin:$PATH"'
  if ! grep -Fqs "$export_line" "$profile" 2>/dev/null; then
    printf "\n%s\n" "$export_line" >>"$profile"
  fi
else
  profile="/etc/profile"
  # shellcheck disable=SC2016  # the literal $PATH must be written to the profile
  export_line='export PATH="/usr/local/bin:$PATH"'
  if ! grep -Fqs "$export_line" "$profile" 2>/dev/null; then
    printf "\n%s\n" "$export_line" >>"$profile"
  fi
fi

echo "OK: Installed to ${dst}"
echo "Hint: Reopen your terminal, then run: uniservice --help"
