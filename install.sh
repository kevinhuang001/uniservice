#!/usr/bin/env bash
#
# uniservice installer.
#
# Every release publishes two artifacts, and this installer lets you pick:
#
#   default    portable zipapp       ~30 KB, needs Python 3.10+ on this machine
#   --binary   standalone binary     bundles CPython, needs nothing, but is
#                                    built per OS/architecture (~24 MB)
#
# The zipapp is the recommended default: one 30 KB file, identical on every
# platform, and it uses the Python you already have.
#
# Either way the command lands in /usr/local/bin/uniservice and is recorded in
# /usr/local/lib/uniservice/manifest, so one installation serves both scopes:
#
#   uniservice ...        -> per-user services
#   sudo uniservice ...   -> system-wide services
#
# /usr/local/bin is on every account's PATH, so the installer never edits a shell
# startup file. Writing there needs root: run it with sudo, or it fails.
#
set -euo pipefail

REPO_SLUG="${UNISERVICE_REPO_SLUG:-kevinhuang001/uniservice}"
REPO_URL="${UNISERVICE_REPO_URL:-https://github.com/${REPO_SLUG}}"
PROGRAM_NAME="uniservice"
MANIFEST_NAME="manifest"
CHECKSUM_FILE="SHA256SUMS"
DEFAULT_PREFIX="/usr/local"
MIN_PYTHON="3.10"

want_binary=0
prefix=""
version=""
expected_sha256=""
from_file=""
uninstall=0
dry_run=0

tmp_dir=""
artifact=""

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

Two artifacts are published for every release:

  (default)   the portable zipapp: one ~30 KB file that runs on any platform,
              but needs Python $MIN_PYTHON+ on this machine  [recommended]
  --binary    a standalone binary that bundles its own CPython and needs no
              Python at all, built for one OS/architecture (~24 MB)

The installer must be able to write to $DEFAULT_PREFIX, so run it with sudo when
you are not root. It never edits shell startup files: $DEFAULT_PREFIX/bin is
already on PATH.

Options:
  --binary              Install the standalone binary instead of the zipapp.
  --prefix DIR          Install under DIR instead of $DEFAULT_PREFIX. For
                        packaging and tests; needs no elevated privileges.
  --version TAG         Release to install, e.g. --version v1.2.0.
                        Default: the latest release.
  --sha256 HEX          Verify the artifact against this SHA-256 digest.
                        By default the digest published in $CHECKSUM_FILE is used.
  --from FILE           Install a local zipapp or binary instead of downloading.
  --uninstall           Remove a previous installation recorded in the
                        manifest. This is the only way to uninstall: the command
                        cannot delete itself on Windows, so removal lives here,
                        where it runs as a different process from the command it
                        deletes.
  --dry-run             With --uninstall, list what would be removed and stop.
  -h, --help            Show this help.

Environment:
  UNISERVICE_BINARY     Same as --binary (any value except 0/false/no).
  UNISERVICE_REPO_SLUG  GitHub repository (default: $REPO_SLUG).
  UNISERVICE_REPO_URL   Full base URL, for a mirror or a file:// tree
                        (default: https://github.com/<slug>).

Examples:
  curl -fsSL $REPO_URL/raw/main/install.sh | sudo bash
  curl -fsSL $REPO_URL/raw/main/install.sh | sudo bash -s -- --binary
  sudo ./install.sh --version v1.2.0
  sudo ./install.sh --uninstall
EOF
}

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --binary) want_binary=1 ;;
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
      from_file="$2"
      shift
      ;;
    --from=*) from_file="${1#*=}" ;;
    --uninstall) uninstall=1 ;;
    --dry-run) dry_run=1 ;;
    -h | --help)
      usage
      exit 0
      ;;
    *) die "unknown option: $1 (try --help)" ;;
  esac
  shift
done

# Same choice as --binary, for when the installer is piped into a shell and there
# is nowhere to put an argument: `curl ... | sudo bash -s -- --binary` works, but
# `UNISERVICE_BINARY=1 curl ... | sudo bash` is friendlier in scripts.
case "${UNISERVICE_BINARY:-}" in
  "" | 0 | false | no | False | No) ;;
  *) want_binary=1 ;;
esac

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------
if [[ -z "$prefix" ]]; then
  prefix="$DEFAULT_PREFIX"
fi
prefix="${prefix%/}"
[[ -n "$prefix" ]] || die "--prefix requires a non-empty value"

bin_dir="$prefix/bin"
lib_dir="$prefix/lib/$PROGRAM_NAME"
manifest="$lib_dir/$MANIFEST_NAME"

PLATFORM_OS=""
PLATFORM_ARCH=""
detect_platform() {
  # Sets PLATFORM_OS and PLATFORM_ARCH.  The binary asset names are produced by
  # scripts/build_binary.py; PyInstaller cannot cross-compile, so the name
  # encodes the OS and the CPU architecture.
  local machine
  case "$(uname -s 2>/dev/null || echo unknown)" in
    Linux) PLATFORM_OS="linux" ;;
    Darwin) PLATFORM_OS="macos" ;;
    *) PLATFORM_OS="unknown" ;;
  esac

  machine="$(uname -m 2>/dev/null || echo unknown)"
  case "$machine" in
    x86_64 | amd64) PLATFORM_ARCH="x86_64" ;;
    aarch64) PLATFORM_ARCH="aarch64" ;;
    arm64) PLATFORM_ARCH="arm64" ;;
    *) PLATFORM_ARCH="$machine" ;;
  esac
}

manifest_value() {
  # manifest_value KEY - never sources the file
  awk -F= -v key="$1" '$1 == key { sub(/^[^=]*=/, ""); print; exit }' "$manifest"
}

sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
  else
    die "neither sha256sum nor shasum is available to verify the download"
  fi
}

detect_kind() {
  # A zipapp starts with its shebang; everything else is treated as a binary.
  if [[ "$(head -c 2 "$1")" == "#!" ]]; then
    printf 'zipapp\n'
  else
    printf 'binary\n'
  fi
}

check_artifact_format() {
  # Fail loudly on an HTML error page, or on a binary for another platform.
  local file="$1" kind="$2" magic
  if [[ "$kind" == "zipapp" ]]; then
    [[ "$(head -c 2 "$file")" == "#!" ]] || die "$file is not a zipapp: it does not start with a shebang"
    return 0
  fi

  magic="$(head -c 4 "$file" | od -An -tx1 | tr -d ' \n')"
  case "$PLATFORM_OS" in
    linux)
      [[ "$magic" == "7f454c46" ]] || die "$file is not a Linux executable (magic $magic)"
      ;;
    macos)
      case "$magic" in
        cffaedfe | cefaedfe | cafebabe | cafebabf) ;;
        *) die "$file is not a macOS executable (magic $magic)" ;;
      esac
      ;;
    *)
      warn "cannot verify the executable format for $PLATFORM_OS"
      ;;
  esac
}

require_python() {
  # The zipapp runs on whatever python3 the invoking user's PATH resolves to.
  local candidate
  for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 &&
      "$candidate" -c "import sys; raise SystemExit(0 if sys.version_info >= tuple(int(p) for p in '$MIN_PYTHON'.split('.')) else 1)" >/dev/null 2>&1; then
      log "Using $("$candidate" -V 2>&1) at $(command -v "$candidate")"
      return 0
    fi
  done
  die "the portable zipapp needs Python $MIN_PYTHON+, but no suitable python3 is on PATH; install Python, or pick the standalone binary with --binary"
}

# ---------------------------------------------------------------------------
# Uninstall
# ---------------------------------------------------------------------------
if [[ "$dry_run" -eq 1 && "$uninstall" -eq 0 ]]; then
  die "--dry-run only applies to --uninstall"
fi

if [[ "$uninstall" -eq 1 ]]; then
  [[ -f "$manifest" ]] || die "no installation recorded at $manifest"

  recorded_prefix="$(manifest_value prefix)"
  recorded_binary="$(manifest_value binary)"
  recorded_version="$(manifest_value version)"
  [[ -n "$recorded_prefix" ]] || recorded_prefix="$prefix"
  [[ -n "$recorded_binary" ]] || recorded_binary="$bin_dir/$PROGRAM_NAME"

  if [[ "$dry_run" -eq 1 ]]; then
    log "Would remove:"
    [[ -e "$recorded_binary" ]] && log "  $recorded_binary"
    log "  $manifest"
    log "  and any directory under $recorded_prefix that becomes empty"
    exit 0
  fi

  if [[ -e "$recorded_binary" ]]; then
    [[ -w "$(dirname "$recorded_binary")" ]] || die "cannot remove $recorded_binary; run the installer with sudo"
    rm -f "$recorded_binary"
    log "Removed $recorded_binary"
  fi
  rm -f "$manifest"

  # Prune directories that are empty now, deepest first, and only inside the
  # recorded prefix: a wrong --prefix can therefore never delete real content.
  # `-exec ... \;` (one at a time, not `+`) matters: find evaluates `-empty` when
  # it visits a directory, so the child has to be gone before the parent is seen.
  if [[ -d "$recorded_prefix" ]]; then
    find "$recorded_prefix" -depth -type d -empty -exec rmdir {} \; 2>/dev/null || true
    rmdir "$recorded_prefix" 2>/dev/null || true
  fi

  log "OK: uninstalled $PROGRAM_NAME ${recorded_version:+$recorded_version }from $recorded_prefix"
  exit 0
fi

# ---------------------------------------------------------------------------
# Install
# ---------------------------------------------------------------------------
mkdir -p "$prefix" 2>/dev/null || die "cannot create $prefix; run the installer with sudo"
[[ -w "$prefix" ]] || die "cannot write to $prefix; run the installer with sudo"
mkdir -p "$bin_dir" "$lib_dir" 2>/dev/null || die "cannot create $bin_dir and $lib_dir; run the installer with sudo"
[[ -w "$bin_dir" && -w "$lib_dir" ]] || die "cannot write to $bin_dir and $lib_dir; run the installer with sudo"
prefix="$(cd "$prefix" && pwd)"
bin_dir="$prefix/bin"
lib_dir="$prefix/lib/$PROGRAM_NAME"
manifest="$lib_dir/$MANIFEST_NAME"

detect_platform

tmp_dir="$(mktemp -d 2>/dev/null || mktemp -d -t uniservice)"

if [[ -n "$from_file" ]]; then
  # A local file is an explicit choice; the format checks below guard downloads,
  # where the real risk is an HTML error page being saved as the command.
  [[ -f "$from_file" ]] || die "--from $from_file does not exist"
  artifact="$from_file"
  kind="$(detect_kind "$artifact")"
  asset="$(basename "$artifact")"
  log "Installing the local $kind $asset into $prefix"
else
  downloader=""
  for candidate in curl wget; do
    if command -v "$candidate" >/dev/null 2>&1; then
      downloader="$candidate"
      break
    fi
  done
  [[ -n "$downloader" ]] || die "neither curl nor wget is installed, so nothing can be downloaded (use --from FILE)"

  download() {
    # download URL DEST
    if [[ "$downloader" == "curl" ]]; then
      curl -fsSL "$1" -o "$2"
    else
      wget -qO "$2" "$1"
    fi
  }

  latest_release_tag() {
    local effective=""
    [[ "$downloader" == "curl" ]] || return 1
    effective="$(curl -fsSIL -o /dev/null -w '%{url_effective}' "$REPO_URL/releases/latest" 2>/dev/null)" || return 1
    case "$effective" in
      */releases/tag/*) printf '%s\n' "${effective##*/releases/tag/}" ;;
      *) return 1 ;;
    esac
  }

  release_checksum_for() {
    # release_checksum_for TAG ASSET - prints the published digest, or nothing
    local tag="$1" name="$2" sums="$tmp_dir/$CHECKSUM_FILE"
    download "$REPO_URL/releases/download/$tag/$CHECKSUM_FILE" "$sums" 2>/dev/null || return 1
    awk -v name="$name" '$2 == name || $2 == "./" name { print $1; exit }' "$sums"
  }

  if [[ "$want_binary" -eq 1 ]]; then
    kind="binary"
    asset="$PROGRAM_NAME-$PLATFORM_OS-$PLATFORM_ARCH"
    if [[ "$PLATFORM_OS" == "unknown" ]]; then
      die "no standalone binary is published for $(uname -s 2>/dev/null || echo this system); drop --binary to use the portable zipapp instead"
    fi
  else
    kind="zipapp"
    asset="$PROGRAM_NAME"
    require_python
  fi

  log "Installing $asset ($kind) into $prefix"

  tag="$version"
  if [[ -z "$tag" ]]; then
    if ! tag="$(latest_release_tag)"; then
      die "could not determine the latest release from $REPO_URL; pass --version TAG"
    fi
    log "Latest release: $tag"
  fi

  artifact="$tmp_dir/$asset"
  log "Downloading $REPO_URL/releases/download/$tag/$asset"
  download "$REPO_URL/releases/download/$tag/$asset" "$artifact" || {
    if [[ "$kind" == "binary" ]]; then
      die "could not download $asset from release $tag; drop --binary to use the portable zipapp instead"
    fi
    die "could not download $asset from release $tag"
  }

  if [[ -z "$expected_sha256" ]] && published_sha256="$(release_checksum_for "$tag" "$asset")"; then
    expected_sha256="$published_sha256"
  fi
fi

check_artifact_format "$artifact" "$kind"
# For a download the Python check already ran before fetching, to fail fast.
if [[ -n "$from_file" && "$kind" == "zipapp" ]]; then
  require_python
fi
# A downloaded file is not executable yet; a user-supplied one keeps its mode.
[[ -n "$from_file" ]] || chmod 0755 "$artifact"

if [[ -n "$expected_sha256" ]]; then
  actual_sha256="$(sha256_of "$artifact")"
  [[ "$actual_sha256" == "$expected_sha256" ]] ||
    die "SHA-256 mismatch for $artifact: expected $expected_sha256, got $actual_sha256"
  log "SHA-256 verified: $actual_sha256"
else
  warn "no published checksum for $asset; installing without verification"
fi

# Prefer the version the artifact reports over the release tag: they are the same
# for a well-formed release, but the artifact is the truth.
installed_version="$("$artifact" --version 2>/dev/null | awk 'NR==1{print $2}')" || true
if [[ -z "$installed_version" ]]; then
  installed_version="$version"
fi
[[ -n "$installed_version" ]] || installed_version="unknown"

# Atomic replace: never leave a half-written executable behind.
staged_binary="$bin_dir/.$PROGRAM_NAME.tmp.$$"
trap 'rm -f "$staged_binary"; cleanup' EXIT
cp "$artifact" "$staged_binary"
chmod 0755 "$staged_binary"
mv -f "$staged_binary" "$bin_dir/$PROGRAM_NAME"
log "Installed $bin_dir/$PROGRAM_NAME (version $installed_version, $kind)"

# /usr/local/bin is on every account's PATH, so the installer never edits shell
# startup files.  Only a custom --prefix can need a note.
if [[ ":$PATH:" != *":$bin_dir:"* ]]; then
  warn "$bin_dir is not on PATH in this shell"
fi

{
  printf 'schema=1\n'
  printf 'program=%s\n' "$PROGRAM_NAME"
  printf 'kind=%s\n' "$kind"
  printf 'version=%s\n' "$installed_version"
  printf 'asset=%s\n' "$asset"
  printf 'sha256=%s\n' "$(sha256_of "$artifact")"
  printf 'prefix=%s\n' "$prefix"
  printf 'binary=%s\n' "$bin_dir/$PROGRAM_NAME"
  printf 'installed_at=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
} >"$manifest"

log ""
log "OK: installed $PROGRAM_NAME $installed_version ($kind)"
log "Hint: $PROGRAM_NAME --help"
log "Note: one installation serves both scopes: '$PROGRAM_NAME ...' for user services,"
log "      'sudo $PROGRAM_NAME ...' for system services."
