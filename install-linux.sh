#!/usr/bin/env bash
#
# Compatibility entry point.
#
# The real installer is ./install.sh, which detects the platform itself.  This
# file only exists because the documented install URL has always been
# install-linux.sh; it forwards all arguments.
#
set -euo pipefail

repo_slug="${UNISERVICE_REPO_SLUG:-kevinhuang001/uniservice}"
installer_url="https://raw.githubusercontent.com/${repo_slug}/main/install.sh"

# Run the sibling installer when executed from a checkout.
script_source="${BASH_SOURCE[0]:-}"
if [[ -n "$script_source" && -f "$script_source" ]]; then
  script_dir="$(cd "$(dirname "$script_source")" && pwd)"
  if [[ -f "$script_dir/install.sh" ]]; then
    exec bash "$script_dir/install.sh" "$@"
  fi
fi

if command -v curl >/dev/null 2>&1; then
  curl -fsSL "$installer_url" | bash -s -- "$@"
elif command -v wget >/dev/null 2>&1; then
  wget -qO- "$installer_url" | bash -s -- "$@"
else
  echo "Neither curl nor wget is installed. Please install one of them first." >&2
  exit 1
fi
