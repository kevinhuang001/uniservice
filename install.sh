#!/usr/bin/env bash
#
# uniservice installer.
#
# Installs a single self-contained `uniservice` executable (a Python zipapp) at
# <prefix>/bin/uniservice and records the installation in
# <prefix>/lib/uniservice/install.json.
#
# Because the program is one file, a single installation serves both scopes:
#
#   uniservice ...        -> per-user services
#   sudo uniservice ...   -> system-wide services
#
# so the default prefix is a shared one (/usr/local) whenever that is possible.
#
set -euo pipefail

REPO_SLUG="${UNISERVICE_REPO_SLUG:-kevinhuang001/uniservice}"
REPO_URL="https://github.com/${REPO_SLUG}"
PROGRAM_NAME="uniservice"
PACKAGE_NAME="uniservice_lib"
MANIFEST_NAME="install.json"
DEFAULT_INTERPRETER="/usr/bin/env python3"

# Files created by the pre-1.2.0 installers, which copied the Python package
# next to the launcher.
LEGACY_FILES="utils.py backend_base.py linux_backend.py mac_backend.py windows_backend.py"

prefix=""
mode=""
version=""
expected_sha256=""
from_dir=""
no_modify_path=0
uninstall=0

tmp_dir=""
profile_files=""

log() { printf '%s\n' "$*"; }
warn() { printf 'WARNING: %s\n' "$*" >&2; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

cleanup() {
  if [[ -n "$tmp_dir" && -d "$tmp_dir" ]]; then
    rm -rf "$tmp_dir"
  fi
}
trap cleanup EXIT

usage() {
  cat <<EOF
Usage: install.sh [OPTIONS]

Installs $PROGRAM_NAME for the current user or system-wide.

Options:
  --user                Install for the current user (prefix ~/.local).
  --system              Install system-wide (prefix /usr/local).
  --prefix DIR          Install under DIR (DIR/bin/$PROGRAM_NAME).
                        Default: /usr/local when running as root, ~/.local otherwise.
  --version TAG         Install a specific release, e.g. --version v1.2.0.
                        Default: the latest release, else the main branch archive.
  --sha256 HEX          Verify the downloaded artifact against this SHA-256 digest.
  --from DIR            Build from a local checkout instead of downloading
                        (DIR must contain $PACKAGE_NAME/).
  --no-modify-path      Never edit shell startup files, only print instructions.
  --uninstall           Remove a previous installation recorded in the manifest.
  -h, --help            Show this help.

Environment:
  UNISERVICE_REPO_SLUG  Override the GitHub repository (default: $REPO_SLUG).

Examples:
  curl -fsSL $REPO_URL/raw/main/install.sh | bash
  curl -fsSL $REPO_URL/raw/main/install.sh | sudo bash
  ./install.sh --user --no-modify-path --prefix "\$HOME/opt"
  ./install.sh --version v1.2.0 --sha256 <digest>
  ./install.sh --uninstall
EOF
}

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --user) mode="user" ;;
    --system) mode="system" ;;
    --prefix)
      [[ $# -ge 2 ]] || die "--prefix requires a value"
      prefix="$2"
      shift
      ;;
    --prefix=*) prefix="${1#*=}" ;;
    --version)
      [[ $# -ge 2 ]] || die "--version requires a value"
      version="$2"
      shift
      ;;
    --version=*) version="${1#*=}" ;;
    --sha256)
      [[ $# -ge 2 ]] || die "--sha256 requires a value"
      expected_sha256="$2"
      shift
      ;;
    --sha256=*) expected_sha256="${1#*=}" ;;
    --from)
      [[ $# -ge 2 ]] || die "--from requires a value"
      from_dir="$2"
      shift
      ;;
    --from=*) from_dir="${1#*=}" ;;
    --no-modify-path) no_modify_path=1 ;;
    --uninstall) uninstall=1 ;;
    -h | --help)
      usage
      exit 0
      ;;
    *) die "unknown option: $1 (try --help)" ;;
  esac
  shift
done

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------
os_name="$(uname -s 2>/dev/null || echo unknown)"
uid="$(id -u 2>/dev/null || echo 0)"

if [[ -z "$prefix" ]]; then
  if [[ "$mode" == "system" || ( -z "$mode" && "$uid" -eq 0 ) ]]; then
    prefix="/usr/local"
  else
    prefix="${HOME}/.local"
  fi
fi
# Normalise so that `--prefix ~/.local/` and `--prefix $HOME/.local` compare equal.
prefix="${prefix%/}"
mkdir -p "$prefix" 2>/dev/null || die "cannot create prefix $prefix (use --user, or run with sudo)"
prefix="$(cd "$prefix" && pwd)"

bin_dir="$prefix/bin"
lib_dir="$prefix/lib/$PROGRAM_NAME"
manifest="$lib_dir/$MANIFEST_NAME"

python_hint() {
  case "$os_name" in
    Darwin)
      printf '  - Homebrew: brew install python\n  - Or https://www.python.org/downloads/macos/\n'
      ;;
    *)
      printf '  - Debian/Ubuntu: sudo apt-get update && sudo apt-get install -y python3\n'
      printf '  - RHEL/CentOS/Fedora: sudo dnf install -y python3\n'
      printf '  - Arch: sudo pacman -S python\n'
      printf '  - Alpine: sudo apk add python3\n'
      ;;
  esac
}

find_python() {
  local candidate
  for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
      command -v "$candidate"
      return 0
    fi
  done
  return 1
}

python_is_supported() {
  "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1
}

if ! python_bin="$(find_python)"; then
  printf 'ERROR: python3 is not installed. Please install Python 3.10+ first:\n' >&2
  python_hint >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# Download + build helpers
# ---------------------------------------------------------------------------
downloader=""
for candidate in curl wget; do
  if command -v "$candidate" >/dev/null 2>&1; then
    downloader="$candidate"
    break
  fi
done

download() {
  # download URL DEST
  if [[ "$downloader" == "curl" ]]; then
    curl -fsSL "$1" -o "$2"
  else
    wget -qO "$2" "$1"
  fi
}

uri_exists() {
  if [[ "$downloader" == "curl" ]]; then
    curl -fsSIL -o /dev/null "$1" 2>/dev/null
  else
    wget -q --spider "$1" 2>/dev/null
  fi
}

sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
  else
    "$python_bin" -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$1"
  fi
}

# Echo the newest release tag, or fail when the repository has no releases yet.
latest_release_tag() {
  local effective=""
  if [[ "$downloader" == "curl" ]]; then
    effective="$(curl -fsSIL -o /dev/null -w '%{url_effective}' "$REPO_URL/releases/latest" 2>/dev/null)" || return 1
  elif [[ "$downloader" == "wget" ]]; then
    effective="$(wget -qS --spider --max-redirect=10 "$REPO_URL/releases/latest" 2>&1 |
      awk '/^[[:space:]]+Location: /{location=$2} END{if (location) print location}')" || return 1
  else
    return 1
  fi
  case "$effective" in
    */releases/tag/*) printf '%s\n' "${effective##*/releases/tag/}" ;;
    *) return 1 ;;
  esac
}

build_zipapp() {
  # build_zipapp SRC_DIR DEST
  local src="$1" dest="$2"
  if [[ -f "$src/scripts/build_zipapp.py" ]]; then
    "$python_bin" "$src/scripts/build_zipapp.py" --source "$src" --output "$dest" --quiet >/dev/null
  else
    local staging="$tmp_dir/staging"
    rm -rf "$staging"
    mkdir -p "$staging"
    cp -R "$src/$PACKAGE_NAME" "$staging/$PACKAGE_NAME"
    rm -rf "$staging/$PACKAGE_NAME/__pycache__"
    rm -rf "$staging/$PACKAGE_NAME"/*/__pycache__
    printf 'from uniservice_lib.cli import entrypoint\n\nentrypoint()\n' >"$staging/__main__.py"
    "$python_bin" -m zipapp "$staging" -o "$dest" -p "$DEFAULT_INTERPRETER" -c
  fi
  chmod 0755 "$dest"
}

build_from_archive() {
  # build_from_archive REF DEST
  local ref="$1" dest="$2"
  local archive="$tmp_dir/source.tar.gz"
  local extract="$tmp_dir/src"
  command -v tar >/dev/null 2>&1 || die "tar is required to unpack the source archive"

  log "Downloading the source archive for $ref"
  download "$REPO_URL/archive/refs/heads/$ref.tar.gz" "$archive" 2>/dev/null ||
    download "$REPO_URL/archive/refs/tags/$ref.tar.gz" "$archive"

  mkdir -p "$extract"
  tar -xzf "$archive" -C "$extract"

  # GitHub archives contain exactly one top-level directory.  A glob keeps this
  # working with both GNU and BSD find(1).
  local source_root="" candidate
  for candidate in "$extract"/*/; do
    if [[ -d "$candidate" ]]; then
      source_root="${candidate%/}"
      break
    fi
  done
  [[ -n "$source_root" ]] || die "unexpected archive layout"
  build_zipapp "$source_root" "$dest"
}

resolve_artifact() {
  # resolve_artifact DEST
  local dest="$1"

  if [[ -n "$from_dir" ]]; then
    [[ -d "$from_dir/$PACKAGE_NAME" ]] || die "--from $from_dir does not contain $PACKAGE_NAME/"
    log "Building from local sources: $from_dir"
    build_zipapp "$from_dir" "$dest"
    return 0
  fi

  if [[ -z "$downloader" ]]; then
    die "neither curl nor wget is installed, so nothing can be downloaded (use --from DIR)"
  fi

  local tag="$version" asset
  if [[ -n "$tag" ]]; then
    asset="$REPO_URL/releases/download/$tag/$PROGRAM_NAME"
    if download "$asset" "$dest" 2>/dev/null; then
      log "Downloaded $asset"
      return 0
    fi
    warn "no $PROGRAM_NAME asset in release $tag; building it from that tag's source archive"
    build_from_archive "$tag" "$dest"
    return 0
  fi

  if tag="$(latest_release_tag)"; then
    asset="$REPO_URL/releases/download/$tag/$PROGRAM_NAME"
    if download "$asset" "$dest" 2>/dev/null; then
      log "Downloaded $asset"
      return 0
    fi
    warn "release $tag has no $PROGRAM_NAME asset; building it from source"
    build_from_archive "$tag" "$dest"
    return 0
  fi

  warn "this repository has no releases yet; falling back to the unpinned main branch"
  build_from_archive "main" "$dest"
}

# ---------------------------------------------------------------------------
# Uninstall
# ---------------------------------------------------------------------------
if [[ "$uninstall" -eq 1 ]]; then
  [[ -f "$manifest" ]] || die "no installation recorded at $manifest"
  UNISERVICE_MANIFEST="$manifest" "$python_bin" - <<'PY'
import json
import os
import pathlib
import shutil

manifest = pathlib.Path(os.environ["UNISERVICE_MANIFEST"])
data = json.loads(manifest.read_text(encoding="utf-8"))

removed = []
for entry in data.get("files", []):
    path = pathlib.Path(entry)
    if path.is_file() or path.is_symlink():
        path.unlink()
        removed.append(str(path))

# Only ever delete the manifest's own directory, and only when it really is the
# uniservice one, so a wrong --prefix cannot remove anything else.
if manifest.parent.name == "uniservice":
    shutil.rmtree(manifest.parent, ignore_errors=True)
print(f"Removed {len(removed)} file(s) from the {data.get('version', 'unknown')} installation:")
for item in removed:
    print(f"  {item}")

profiles = [p for p in data.get("profile_files", []) if p]
if profiles:
    print("The PATH line added by the installer was left in place; delete it if you want:")
    for profile in profiles:
        print(f"  {profile}")
PY
  log "OK: uninstalled uniservice from $prefix"
  exit 0
fi

# ---------------------------------------------------------------------------
# Install
# ---------------------------------------------------------------------------
# Running from a checkout installs that checkout; this keeps the
# "git clone && ./install.sh" workflow and the offline case working.
script_dir=""
script_source="${BASH_SOURCE[0]:-}"
case "$script_source" in
  "" | "-" | bash | /dev/fd/* | /proc/self/fd/* | /dev/stdin) script_dir="" ;;
  *)
    if [[ -f "$script_source" ]]; then
      script_dir="$(cd "$(dirname "$script_source")" && pwd)"
    fi
    ;;
esac
if [[ -z "$from_dir" && -n "$script_dir" && -d "$script_dir/$PACKAGE_NAME" ]]; then
  from_dir="$script_dir"
  log "Installing from the local checkout: $from_dir"
fi

python_is_supported "$python_bin" || die "Python 3.10 or newer is required, but $python_bin is $("$python_bin" -V 2>&1)"

tmp_dir="$(mktemp -d 2>/dev/null || mktemp -d -t uniservice)"
artifact="$tmp_dir/$PROGRAM_NAME"

log "Installing $PROGRAM_NAME into $prefix"
resolve_artifact "$artifact"
[[ -s "$artifact" ]] || die "the artifact is empty"

if [[ -n "$expected_sha256" ]]; then
  actual_sha256="$(sha256_of "$artifact")"
  if [[ "$actual_sha256" != "$expected_sha256" ]]; then
    die "SHA-256 mismatch for $artifact: expected $expected_sha256, got $actual_sha256"
  fi
  log "SHA-256 verified: $actual_sha256"
fi

installed_version="$version"
if [[ -z "$installed_version" ]]; then
  installed_version="$("$python_bin" "$artifact" --version 2>/dev/null | awk 'NR==1{print $2}')" || true
  [[ -n "$installed_version" ]] || installed_version="unknown"
fi

mkdir -p "$bin_dir" "$lib_dir" 2>/dev/null ||
  die "cannot write to $prefix (use --user, or run the installer with sudo)"

# Atomic replace: never leave a half-written executable behind.
staged_binary="$bin_dir/.$PROGRAM_NAME.tmp.$$"
trap 'rm -f "$staged_binary"; cleanup' EXIT
cp "$artifact" "$staged_binary"
chmod 0755 "$staged_binary"
mv -f "$staged_binary" "$bin_dir/$PROGRAM_NAME"
log "Installed $bin_dir/$PROGRAM_NAME (version $installed_version)"

# Migrate away from the pre-1.2.0 layout, which copied the package next to the
# launcher instead of shipping one self-contained file.
legacy_removed=0
for legacy in $LEGACY_FILES; do
  if [[ -e "$bin_dir/$legacy" ]]; then
    rm -f "$bin_dir/$legacy"
    legacy_removed=1
  fi
done
if [[ -d "$bin_dir/$PACKAGE_NAME" ]]; then
  rm -rf "${bin_dir:?}/$PACKAGE_NAME"
  legacy_removed=1
fi
if [[ "$legacy_removed" -eq 1 ]]; then
  log "Removed the pre-1.2.0 package files from $bin_dir"
fi

# ---------------------------------------------------------------------------
# PATH
# ---------------------------------------------------------------------------
append_export() {
  # append_export RC_FILE EXPORT_LINE
  local rc_file="$1" export_line="$2"
  if [[ -f "$rc_file" ]] && grep -Fqs "$export_line" "$rc_file" 2>/dev/null; then
    return 0
  fi
  if ! printf '\n# Added by the uniservice installer\n%s\n' "$export_line" >>"$rc_file" 2>/dev/null; then
    warn "could not update $rc_file"
    return 0
  fi
  profile_files="${profile_files:+$profile_files:}$rc_file"
  log "Added $bin_dir to PATH in $rc_file"
}

user_rc_file() {
  case "$(basename "${SHELL:-}")" in
    zsh) printf '%s\n' "$HOME/.zshrc" ;;
    bash)
      if [[ -f "$HOME/.bashrc" ]]; then printf '%s\n' "$HOME/.bashrc"; else printf '%s\n' "$HOME/.profile"; fi
      ;;
    *) printf '%s\n' "$HOME/.profile" ;;
  esac
}

if [[ ":$PATH:" == *":$bin_dir:"* ]]; then
  log "Note: $bin_dir is already on PATH"
elif [[ "$prefix" == "$HOME/.local" ]]; then
  if [[ "$no_modify_path" -eq 1 ]]; then
    log "Note: add this to your shell startup file:"
    log "  export PATH=\"$bin_dir:\$PATH\""
  else
    # shellcheck disable=SC2016  # the literal $PATH must reach the rc file
    append_export "$(user_rc_file)" 'export PATH="$HOME/.local/bin:$PATH"'
  fi
elif [[ "$uid" -eq 0 || "$mode" == "system" ]]; then
  # /usr/local/bin is on PATH for every account by default; never edit /etc/profile.
  if [[ "$uid" -ne 0 ]]; then
    warn "$bin_dir is not on PATH for this shell; it will be after a new login"
  fi
else
  warn "$bin_dir is not on PATH; add it yourself (the installer never edits system files)"
fi

# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------
UNISERVICE_MANIFEST="$manifest" \
  UNISERVICE_VERSION="$installed_version" \
  UNISERVICE_SHA256="$(sha256_of "$artifact")" \
  UNISERVICE_PREFIX="$prefix" \
  UNISERVICE_BINARY="$bin_dir/$PROGRAM_NAME" \
  UNISERVICE_REPO="$REPO_SLUG" \
  UNISERVICE_PROFILES="$profile_files" \
  "$python_bin" - <<'PY'
import datetime
import json
import os
import pathlib

manifest = pathlib.Path(os.environ["UNISERVICE_MANIFEST"])
manifest.parent.mkdir(parents=True, exist_ok=True)
data = {
    "schema": 1,
    "program": "uniservice",
    "version": os.environ["UNISERVICE_VERSION"],
    "sha256": os.environ["UNISERVICE_SHA256"],
    "repository": os.environ["UNISERVICE_REPO"],
    "prefix": os.environ["UNISERVICE_PREFIX"],
    "installed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
    "files": [os.environ["UNISERVICE_BINARY"]],
    "profile_files": [p for p in os.environ.get("UNISERVICE_PROFILES", "").split(":") if p],
}
manifest.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
PY

log ""
log "OK: installed $PROGRAM_NAME $installed_version"
log "Hint: $PROGRAM_NAME --help"
if [[ "$prefix" == "/usr/local" ]]; then
  log "Note: one installation serves both scopes: '$PROGRAM_NAME ...' for user services,"
  log "      'sudo $PROGRAM_NAME ...' for system services."
else
  log "Note: for system services call this install by absolute path (sudo resets PATH):"
  log "      sudo $bin_dir/$PROGRAM_NAME ..."
fi
