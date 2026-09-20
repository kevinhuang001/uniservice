#!/usr/bin/env bash
#
# uniservice installer.
#
# Installs a single self-contained `uniservice` executable (a Python zipapp) at
# /usr/local/bin/uniservice and records the installation in
# /usr/local/lib/uniservice/install.json.
#
# Because the program is one file, one installation serves both scopes:
#
#   uniservice ...        -> per-user services
#   sudo uniservice ...   -> system-wide services
#
# /usr/local/bin is on every account's PATH, so nothing else has to be arranged.
# Writing there needs root: run the installer with sudo, or it fails.
#
set -euo pipefail

REPO_SLUG="${UNISERVICE_REPO_SLUG:-kevinhuang001/uniservice}"
REPO_URL="https://github.com/${REPO_SLUG}"
PROGRAM_NAME="uniservice"
PACKAGE_NAME="uniservice_lib"
MANIFEST_NAME="install.json"
DEFAULT_INTERPRETER="/usr/bin/env python3"
DEFAULT_PREFIX="/usr/local"

prefix=""
version=""
expected_sha256=""
from_dir=""
uninstall=0

tmp_dir=""

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

Installs $PROGRAM_NAME into $DEFAULT_PREFIX. One installation there serves both
scopes: '$PROGRAM_NAME ...' manages per-user services and 'sudo $PROGRAM_NAME ...'
manages system services.

The installer must be able to write to $DEFAULT_PREFIX, so run it with sudo when
you are not root. It never edits shell startup files: $DEFAULT_PREFIX/bin is
already on PATH.

Options:
  --prefix DIR          Install under DIR instead of $DEFAULT_PREFIX. For
                        packaging and tests; needs no elevated privileges.
  --version TAG         Install a specific release, e.g. --version v1.2.0.
                        Default: the latest release, else the main branch archive.
  --sha256 HEX          Verify the downloaded artifact against this SHA-256 digest.
  --from DIR            Build from a local checkout instead of downloading
                        (DIR must contain $PACKAGE_NAME/).
  --uninstall           Remove a previous installation recorded in the manifest.
  -h, --help            Show this help.

Environment:
  UNISERVICE_REPO_SLUG  Override the GitHub repository (default: $REPO_SLUG).

Examples:
  curl -fsSL $REPO_URL/raw/main/install.sh | sudo bash
  ./install.sh --version v1.2.0 --sha256 <digest>
  sudo ./install.sh --uninstall
EOF
}

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
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

if [[ -z "$prefix" ]]; then
  prefix="$DEFAULT_PREFIX"
fi
prefix="${prefix%/}"
[[ -n "$prefix" ]] || die "--prefix requires a non-empty value"

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
  [[ -w "$bin_dir" && -w "$lib_dir" ]] || die "cannot remove the installation under $prefix; run the installer with sudo"
  UNISERVICE_MANIFEST="$manifest" "$python_bin" - <<'PY'
import json
import os
import pathlib

manifest = pathlib.Path(os.environ["UNISERVICE_MANIFEST"])
data = json.loads(manifest.read_text(encoding="utf-8"))

removed = []
for entry in data.get("files", []):
    path = pathlib.Path(entry)
    if path.is_file() or path.is_symlink():
        path.unlink()
        removed.append(str(path))

manifest.unlink(missing_ok=True)

# Prune directories that are empty now, deepest first, and only inside the
# recorded prefix: a wrong --prefix can therefore never delete real content.
prefix = data.get("prefix")
if isinstance(prefix, str) and prefix:
    root = pathlib.Path(prefix)
    if root.is_dir():
        directories = sorted((item for item in root.rglob("*") if item.is_dir()), key=lambda item: len(item.parts))
        for directory in reversed(directories):
            try:
                directory.rmdir()
            except OSError:
                pass
        try:
            root.rmdir()
        except OSError:
            pass

print(f"Removed {len(removed)} file(s) from the {data.get('version', 'unknown')} installation:")
for item in removed:
    print(f"  {item}")
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

# Fail before downloading anything: the target prefix must be writable.
mkdir -p "$prefix" 2>/dev/null || die "cannot create $prefix; run the installer with sudo"
[[ -w "$prefix" ]] || die "cannot write to $prefix; run the installer with sudo"
mkdir -p "$bin_dir" "$lib_dir" 2>/dev/null || die "cannot create $bin_dir and $lib_dir; run the installer with sudo"
[[ -w "$bin_dir" && -w "$lib_dir" ]] || die "cannot write to $bin_dir and $lib_dir; run the installer with sudo"
prefix="$(cd "$prefix" && pwd)"
bin_dir="$prefix/bin"
lib_dir="$prefix/lib/$PROGRAM_NAME"
manifest="$lib_dir/$MANIFEST_NAME"

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

# Atomic replace: never leave a half-written executable behind.
staged_binary="$bin_dir/.$PROGRAM_NAME.tmp.$$"
trap 'rm -f "$staged_binary"; cleanup' EXIT
cp "$artifact" "$staged_binary"
chmod 0755 "$staged_binary"
mv -f "$staged_binary" "$bin_dir/$PROGRAM_NAME"
log "Installed $bin_dir/$PROGRAM_NAME (version $installed_version)"

# ---------------------------------------------------------------------------
# PATH
# ---------------------------------------------------------------------------
# /usr/local/bin is on every account's PATH, so the installer never edits shell
# startup files.  Only a custom --prefix can need a note.
if [[ ":$PATH:" != *":$bin_dir:"* ]]; then
  warn "$bin_dir is not on PATH in this shell"
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
}
manifest.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
PY

log ""
log "OK: installed $PROGRAM_NAME $installed_version"
log "Hint: $PROGRAM_NAME --help"
log "Note: one installation serves both scopes: '$PROGRAM_NAME ...' for user services,"
log "      'sudo $PROGRAM_NAME ...' for system services."
