<#
.SYNOPSIS
  Install the uniservice command for the current user.

.DESCRIPTION
  Every release publishes two artifacts and this installer lets you pick:

    (default)  the portable zipapp  - one ~30 KB file, needs Python 3.10+
    -Binary    the standalone binary - bundles CPython, needs no Python (~24 MB)

  The zipapp is the recommended default. Either way the command lands in
  %LOCALAPPDATA%\uniservice\bin and the installation is recorded in a manifest
  so -Uninstall can undo it exactly.

  `uniservice list` works in any shell; every other command creates or changes a
  Scheduled Task that runs as SYSTEM and therefore needs an elevated shell.

  When this script is piped straight into Invoke-Expression there is no file on
  disk to pass a switch to, so the same choice is available as an environment
  variable:

    $env:UNISERVICE_BINARY = 1; iwr -useb <url> | iex

.PARAMETER Binary
  Install the standalone binary instead of the portable zipapp.

.PARAMETER Prefix
  Install under this directory instead of %LOCALAPPDATA%\uniservice.

.PARAMETER Version
  Release to install, for example -Version v1.2.0. Default: the latest release.

.PARAMETER Sha256
  Verify the artifact against this SHA-256 digest. By default the digest
  published in SHA256SUMS is used.

.PARAMETER From
  Install a local zipapp or .exe instead of downloading one.

.PARAMETER NoModifyPath
  Never edit PATH (user environment or PowerShell profile).

.PARAMETER Uninstall
  Remove a previous installation recorded in the manifest.

.EXAMPLE
  iwr -useb https://raw.githubusercontent.com/kevinhuang001/uniservice/main/install-windows.ps1 | iex

.EXAMPLE
  ./install-windows.ps1 -Binary -Version v1.2.0

.EXAMPLE
  ./install-windows.ps1 -Uninstall
#>
[CmdletBinding()]
param(
  [switch]$Binary,
  [string]$Prefix = '',
  [string]$Version = '',
  [string]$Sha256 = '',
  [string]$From = '',
  [switch]$NoModifyPath,
  [switch]$Uninstall
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
# On PowerShell 7.3+ a failing native command would otherwise throw before the
# $LASTEXITCODE checks below can run.
$PSNativeCommandUseErrorActionPreference = $false

$RepoSlug = if ($env:UNISERVICE_REPO_SLUG) { $env:UNISERVICE_REPO_SLUG } else { 'kevinhuang001/uniservice' }
$RepoUrl = if ($env:UNISERVICE_REPO_URL) { $env:UNISERVICE_REPO_URL } else { "https://github.com/$RepoSlug" }
$ProgramName = 'uniservice'
$ManifestName = 'manifest'
$ChecksumFile = 'SHA256SUMS'
$MinPython = '3.10'

try {
  $current = [Net.ServicePointManager]::SecurityProtocol
  [Net.ServicePointManager]::SecurityProtocol = $current -bor [Net.SecurityProtocolType]::Tls12
} catch {}

function Write-Step { param([string]$Message) Write-Host $Message }
function Write-Note { param([string]$Message) Write-Host "WARNING: $Message" -ForegroundColor Yellow }
function Fail { param([string]$Message) throw "uniservice installer: $Message" }

function Get-AssetName {
  param([switch]$Standalone)
  if (-not $Standalone) { return $ProgramName }  # the portable zipapp
  $arch = switch ($env:PROCESSOR_ARCHITECTURE) {
    'AMD64' { 'x86_64' }
    'ARM64' { 'arm64' }
    'x86' { 'x86' }
    default { $env:PROCESSOR_ARCHITECTURE.ToLowerInvariant() }
  }
  return "$ProgramName-windows-$arch.exe"
}

function Save-File {
  param([string]$Uri, [string]$Destination)
  $params = @{ Uri = $Uri; OutFile = $Destination }
  if ($PSVersionTable.PSVersion.Major -lt 6) { $params.UseBasicParsing = $true }
  Invoke-WebRequest @params | Out-Null
}

function Get-LatestReleaseTag {
  # Returns $null when the repository has no releases yet.
  try {
    $headers = @{ 'User-Agent' = 'uniservice-installer' }
    $release = Invoke-RestMethod -Uri "https://api.github.com/repos/$RepoSlug/releases/latest" -Headers $headers
    if ($release -and $release.tag_name) { return [string]$release.tag_name }
  } catch {}
  return $null
}

function Get-ReleaseChecksum {
  param([string]$Tag, [string]$Asset, [string]$WorkDir)
  $sums = Join-Path $WorkDir $ChecksumFile
  try {
    Save-File -Uri "$RepoUrl/releases/download/$Tag/$ChecksumFile" -Destination $sums
  } catch {
    return ''
  }
  foreach ($line in Get-Content -LiteralPath $sums) {
    $parts = $line -split '\s+', 2
    if ($parts.Count -eq 2 -and $parts[1].Trim() -eq $Asset) { return $parts[0].Trim() }
  }
  return ''
}

function Test-PythonAvailable {
  foreach ($candidate in @('py', 'python')) {
    $command = Get-Command $candidate -ErrorAction SilentlyContinue
    if (-not $command) { continue }
    $args = if ($candidate -eq 'py') { @('-3', '-c') } else { @('-c') }
    & $candidate @args 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' 2>$null
    if ($LASTEXITCODE -eq 0) { return $true }
  }
  return $false
}

function Get-ManifestPath {
  param([string]$TargetPrefix)
  # Same layout as install.sh: <prefix>/lib/uniservice/manifest, so that
  # `uniservice uninstall` finds it from the running command on every platform.
  return (Join-Path (Join-Path (Join-Path $TargetPrefix 'lib') $ProgramName) $ManifestName)
}

function Read-Manifest {
  param([string]$Path)
  $values = @{}
  foreach ($line in Get-Content -LiteralPath $Path) {
    $parts = $line -split '=', 2
    if ($parts.Count -eq 2) { $values[$parts[0]] = $parts[1] }
  }
  return $values
}

function Invoke-Uninstall {
  param([string]$TargetPrefix)
  $manifestPath = Get-ManifestPath -TargetPrefix $TargetPrefix
  if (-not (Test-Path -LiteralPath $manifestPath)) {
    Write-Note "nothing was removed: no installation manifest at $manifestPath"
    return
  }

  $data = Read-Manifest -Path $manifestPath
  foreach ($key in @('binary', 'shim')) {
    if ($data.ContainsKey($key) -and $data[$key] -and (Test-Path -LiteralPath $data[$key])) {
      Remove-Item -Force -LiteralPath $data[$key]
      Write-Step "Removed $($data[$key])"
    }
  }
  Remove-Item -Force -LiteralPath $manifestPath -ErrorAction SilentlyContinue

  # Prune directories that are empty now, deepest first, and only inside the
  # recorded prefix: a wrong -Prefix can therefore never delete real content.
  $recordedPrefix = if ($data.ContainsKey('prefix') -and $data['prefix']) { $data['prefix'] } else { $TargetPrefix }
  if (Test-Path -LiteralPath $recordedPrefix) {
    Get-ChildItem -LiteralPath $recordedPrefix -Recurse -Directory -Force -ErrorAction SilentlyContinue |
      Sort-Object { $_.FullName.Length } -Descending |
      ForEach-Object {
        if (-not (Get-ChildItem -LiteralPath $_.FullName -Force -ErrorAction SilentlyContinue)) {
          Remove-Item -LiteralPath $_.FullName -Force -ErrorAction SilentlyContinue
        }
      }
    if (-not (Get-ChildItem -LiteralPath $recordedPrefix -Force -ErrorAction SilentlyContinue)) {
      Remove-Item -LiteralPath $recordedPrefix -Force -ErrorAction SilentlyContinue
    }
  }
  Write-Step "OK: uninstalled $ProgramName from $recordedPrefix"
}

function Invoke-Install {
  param([string]$TargetPrefix)

  $standalone = [bool]$Binary
  # Same choice as -Binary, for when the script is piped straight into
  # Invoke-Expression: `iwr ... | iex` leaves no file to pass a switch to.
  if (-not $standalone -and $env:UNISERVICE_BINARY) {
    $standalone = $env:UNISERVICE_BINARY -notin @('0', 'false', 'no', 'False', 'No')
  }
  $asset = Get-AssetName -Standalone:$standalone
  $kind = if ($standalone) { 'binary' } else { 'zipapp' }

  if (-not $standalone -and -not (Test-PythonAvailable)) {
    Fail "the portable zipapp needs Python $MinPython+; install Python, or pick the standalone binary with -Binary"
  }

  $binDir = Join-Path $TargetPrefix 'bin'
  New-Item -ItemType Directory -Force -Path $binDir | Out-Null

  $workDir = Join-Path ([System.IO.Path]::GetTempPath()) ("uniservice-" + [Guid]::NewGuid().ToString('N'))
  New-Item -ItemType Directory -Force -Path $workDir | Out-Null

  try {
    if ($From) {
      if (-not (Test-Path -LiteralPath $From)) { Fail "$From does not exist" }
      $artifact = (Resolve-Path -LiteralPath $From).Path
      $asset = Split-Path -Leaf $artifact
      # A zipapp starts with '#!'; read the bytes rather than a line of a binary.
      $head = [System.IO.File]::ReadAllBytes($artifact)
      $kind = if ($head.Length -ge 2 -and $head[0] -eq 0x23 -and $head[1] -eq 0x21) { 'zipapp' } else { 'binary' }
      Write-Step "Installing the local $kind $asset into $TargetPrefix"
    } else {
      $tag = $Version
      if (-not $tag) {
        $tag = Get-LatestReleaseTag
        if (-not $tag) { Fail "could not determine the latest release from $RepoUrl; pass -Version TAG" }
        Write-Step "Latest release: $tag"
      }

      $artifact = Join-Path $workDir $asset
      Write-Step "Downloading $RepoUrl/releases/download/$tag/$asset"
      try {
        Save-File -Uri "$RepoUrl/releases/download/$tag/$asset" -Destination $artifact
      } catch {
        if ($standalone) { Fail "could not download $asset from release $tag; drop -Binary to use the portable zipapp instead" }
        Fail "could not download $asset from release $tag"
      }

      if (-not $Sha256) { $Sha256 = Get-ReleaseChecksum -Tag $tag -Asset $asset -WorkDir $workDir }
    }

    if ($Sha256) {
      $actual = (Get-FileHash -LiteralPath $artifact -Algorithm SHA256).Hash.ToLowerInvariant()
      if ($actual -ne $Sha256.ToLowerInvariant()) {
        Fail "SHA-256 mismatch for $artifact`: expected $Sha256, got $actual"
      }
      Write-Step "SHA-256 verified: $actual"
    } elseif (-not $From) {
      Write-Note "no published checksum for $asset; installing without verification"
    }

    $installedVersion = $Version
    if (-not $installedVersion) { $installedVersion = 'unknown' }

    $shim = ''
    if ($kind -eq 'binary') {
      $target = Join-Path $binDir "$ProgramName.exe"
      Copy-Item -LiteralPath $artifact -Destination $target -Force
    } else {
      $target = Join-Path $binDir "$ProgramName.pyz"
      Copy-Item -LiteralPath $artifact -Destination $target -Force
      $shim = Join-Path $binDir "$ProgramName.cmd"
      $shimContent = @(
        '@echo off'
        'setlocal'
        'where py >nul 2>nul'
        'if %errorlevel%==0 ('
        '  py -3 "%~dp0uniservice.pyz" %*'
        '  exit /b %errorlevel%'
        ')'
        'where python >nul 2>nul'
        'if %errorlevel%==0 ('
        '  python "%~dp0uniservice.pyz" %*'
        '  exit /b %errorlevel%'
        ')'
        'echo Python 3 not found. Please install it from https://www.python.org/downloads/windows/'
        'exit /b 1'
      ) -join "`r`n"
      Set-Content -LiteralPath $shim -Value $shimContent -Encoding ASCII
    }
    Write-Step "Installed $target (version $installedVersion, $kind)"

    $profilePath = $null
    if (-not $NoModifyPath -and -not $Prefix) {
      $currentPath = [Environment]::GetEnvironmentVariable('Path', 'User')
      if (-not $currentPath) { $currentPath = '' }
      $parts = $currentPath -split ';' | Where-Object { $_ -ne '' }
      if ($parts -notcontains $binDir) {
        [Environment]::SetEnvironmentVariable('Path', (($parts + $binDir) -join ';'), 'User')
        $env:Path = $env:Path + ';' + $binDir
        Write-Step "Added $binDir to the user PATH"
      }

      $profilePath = $PROFILE
      $profileDir = Split-Path -Parent $profilePath
      if ($profileDir) { New-Item -ItemType Directory -Force -Path $profileDir | Out-Null }
      $snippet = @"
`$uniserviceBin = Join-Path `$env:LOCALAPPDATA 'uniservice\bin'
if (`$env:Path -notlike "*`$uniserviceBin*") { `$env:Path = `$env:Path + ';' + `$uniserviceBin }
"@
      $existing = ''
      if (Test-Path -LiteralPath $profilePath) {
        $existing = Get-Content -LiteralPath $profilePath -Raw -ErrorAction SilentlyContinue
      }
      if ($existing -notlike '*uniservice\bin*') {
        Add-Content -LiteralPath $profilePath -Value "`r`n$snippet`r`n"
        Write-Step "Added $binDir to your PowerShell profile"
      }
    } elseif (-not $NoModifyPath) {
      Write-Step "Note: add $binDir to PATH yourself (custom -Prefix)"
    }

    $lines = @(
      'schema=1'
      "program=$ProgramName"
      "kind=$kind"
      "version=$installedVersion"
      "asset=$asset"
      "sha256=$((Get-FileHash -LiteralPath $artifact -Algorithm SHA256).Hash.ToLowerInvariant())"
      "prefix=$TargetPrefix"
      "binary=$target"
      "shim=$shim"
      "installed_at=$((Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ'))"
    )
    $manifestPath = Get-ManifestPath -TargetPrefix $TargetPrefix
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $manifestPath) | Out-Null
    Set-Content -LiteralPath $manifestPath -Value $lines -Encoding UTF8

    Write-Step ''
    Write-Step "OK: installed $ProgramName $installedVersion ($kind)"
    Write-Step "Hint: reopen PowerShell/CMD, then run: $ProgramName --help"
    Write-Step ''
    Write-Step "Note: $ProgramName creates Scheduled Tasks that run as SYSTEM, so 'add',"
    Write-Step "      'start', 'stop' and 'remove' need an Administrator PowerShell/CMD."
    Write-Step "      '$ProgramName list' works without elevation."
  } finally {
    if (Test-Path -LiteralPath $workDir) {
      Remove-Item -Recurse -Force -LiteralPath $workDir -ErrorAction SilentlyContinue
    }
  }
}

function Invoke-Main {
  $targetPrefix = if ($Prefix) { $Prefix } else { Join-Path $env:LOCALAPPDATA 'uniservice' }
  if ($Uninstall) {
    Invoke-Uninstall -TargetPrefix $targetPrefix
    return
  }
  Invoke-Install -TargetPrefix $targetPrefix
}

Invoke-Main
# The script reports failures by throwing, so a clean run must exit 0 even if
# the last native command it ran reported a non-zero status.
$global:LASTEXITCODE = 0
