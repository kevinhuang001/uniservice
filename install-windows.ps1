<#
.SYNOPSIS
  Install the uniservice command for the current user.

.DESCRIPTION
  Installs a single self-contained `uniservice.pyz` (the same artifact used on
  Linux and macOS) under %LOCALAPPDATA%\uniservice\bin together with a
  `uniservice.cmd` shim, and records the installation in install.json so that
  -Uninstall can undo it exactly.

  `uniservice list` works in any shell; every other command creates or changes a
  Scheduled Task that runs as SYSTEM and therefore needs an elevated shell.

  Alternatives:
    pipx install uniservice          (or: irm ... | iex -Pipx)

.PARAMETER Prefix
  Install under this directory instead of %LOCALAPPDATA%\uniservice.

.PARAMETER Version
  Install a specific release tag, for example -Version v1.2.0.

.PARAMETER Sha256
  Verify the downloaded artifact against this SHA-256 digest.

.PARAMETER NoModifyPath
  Never edit PATH (user environment or PowerShell profile).

.PARAMETER Pipx
  Install through pipx instead of the portable layout.

.PARAMETER Uninstall
  Remove a previous installation recorded in the manifest.

.EXAMPLE
  iwr -useb https://raw.githubusercontent.com/kevinhuang001/uniservice/main/install-windows.ps1 | iex

.EXAMPLE
  ./install-windows.ps1 -Uninstall
#>
[CmdletBinding()]
param(
  [string]$Prefix = '',
  [string]$Version = '',
  [string]$Sha256 = '',
  [switch]$NoModifyPath,
  [switch]$Pipx,
  [switch]$Uninstall
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
# On PowerShell 7.3+ a failing native command would otherwise throw before the
# $LASTEXITCODE checks below can run.
$PSNativeCommandUseErrorActionPreference = $false

$repoSlug = if ($env:UNISERVICE_REPO_SLUG) { $env:UNISERVICE_REPO_SLUG } else { 'kevinhuang001/uniservice' }
$repoUrl = "https://github.com/$repoSlug"
$programName = 'uniservice'
$packageName = 'uniservice_lib'
$manifestName = 'install.json'

try {
  $current = [Net.ServicePointManager]::SecurityProtocol
  [Net.ServicePointManager]::SecurityProtocol = $current -bor [Net.SecurityProtocolType]::Tls12
} catch {}

function Write-Info { param([string]$Message) Write-Host $Message }
function Write-Warn { param([string]$Message) Write-Warning $Message }
function Fail { param([string]$Message) throw "uniservice installer: $Message" }

function Get-PythonCommand {
  $py = Get-Command py -ErrorAction SilentlyContinue
  if ($py) {
    try {
      & py -3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' 2>$null
      if ($LASTEXITCODE -eq 0) { return @{ File = 'py'; PrefixArgs = @('-3') } }
    } catch {}
  }
  $python = Get-Command python -ErrorAction SilentlyContinue
  if ($python) {
    try {
      & python -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' 2>$null
      if ($LASTEXITCODE -eq 0) { return @{ File = 'python'; PrefixArgs = @() } }
    } catch {}
  }
  return $null
}

function Show-PythonHint {
  Write-Host 'Python 3.10+ is required but was not found. Please install it first:' -ForegroundColor Yellow
  Write-Host '  - https://www.python.org/downloads/windows/'
  Write-Host '  - Or search for Python in the Microsoft Store'
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
    $release = Invoke-RestMethod -Uri "https://api.github.com/repos/$repoSlug/releases/latest" -Headers $headers
    if ($release -and $release.tag_name) { return [string]$release.tag_name }
  } catch {}
  return $null
}

function Expand-SourceArchive {
  param([string]$Ref, [string]$WorkDir, [string]$Python)
  $zipPath = Join-Path $WorkDir 'source.zip'
  Write-Info "Downloading the source archive for $Ref"
  try {
    Save-File -Uri "$repoUrl/archive/refs/heads/$Ref.zip" -Destination $zipPath
  } catch {
    Save-File -Uri "$repoUrl/archive/refs/tags/$Ref.zip" -Destination $zipPath
  }

  $extractDir = Join-Path $WorkDir 'src'
  New-Item -ItemType Directory -Force -Path $extractDir | Out-Null
  if (Get-Command Expand-Archive -ErrorAction SilentlyContinue) {
    Expand-Archive -LiteralPath $zipPath -DestinationPath $extractDir -Force
  } else {
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [System.IO.Compression.ZipFile]::ExtractToDirectory($zipPath, $extractDir)
  }

  $candidate = Get-ChildItem -LiteralPath $extractDir -Directory |
    Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName $packageName) } |
    Select-Object -First 1
  if (-not $candidate) { Fail 'unexpected source archive layout' }
  return $candidate.FullName
}

function New-Zipapp {
  param([string]$SourceDir, [string]$Destination, [string]$Python, [string[]]$PythonPrefixArgs)
  $builder = Join-Path $SourceDir 'scripts\build_zipapp.py'
  if (Test-Path -LiteralPath $builder) {
    & $Python @PythonPrefixArgs $builder --source $SourceDir --output $Destination --quiet | Out-Null
  } else {
    & $Python @PythonPrefixArgs -m zipapp $SourceDir -o $Destination -c
  }
  if ($LASTEXITCODE -ne 0) { Fail "could not build the zipapp from $SourceDir" }
}

function Resolve-Artifact {
  param([string]$Destination, [string]$WorkDir, [hashtable]$PythonCommand)

  $python = $PythonCommand.File
  $pythonPrefix = $PythonCommand.PrefixArgs

  $tag = $Version
  if (-not $tag) {
    $tag = Get-LatestReleaseTag
    if ($tag) {
      Write-Info "Latest release: $tag"
    } else {
      Write-Warn "this repository has no releases yet; falling back to the unpinned main branch"
    }
  }

  if ($tag) {
    $asset = "$repoUrl/releases/download/$tag/$programName"
    try {
      Save-File -Uri $asset -Destination $Destination
      Write-Info "Downloaded $asset"
      return $tag
    } catch {
      Write-Warn "no $programName asset in release $tag; building it from that tag's source archive"
    }
  }

  $ref = if ($tag) { $tag } else { 'main' }
  $sourceDir = Expand-SourceArchive -Ref $ref -WorkDir $WorkDir -Python $python
  New-Zipapp -SourceDir $sourceDir -Destination $Destination -Python $python -PythonPrefixArgs $pythonPrefix
  return $ref
}

function Get-ManifestPath {
  param([string]$TargetPrefix)
  return (Join-Path $TargetPrefix $manifestName)
}

# ---------------------------------------------------------------------------
# Uninstall
# ---------------------------------------------------------------------------
if ($Uninstall) {
  $portablePrefix = if ($Prefix) { $Prefix } else { Join-Path $env:LOCALAPPDATA 'uniservice' }
  $manifestPath = Get-ManifestPath -TargetPrefix $portablePrefix
  $removedSomething = $false

  if (Test-Path -LiteralPath $manifestPath) {
    $data = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    foreach ($entry in @($data.files)) {
      if ($entry -and (Test-Path -LiteralPath $entry)) {
        Remove-Item -Force -LiteralPath $entry
        Write-Info "Removed $entry"
        $removedSomething = $true
      }
    }
    if ($data.profile) {
      Write-Warn "the PowerShell profile still contains a PATH line for uniservice: $($data.profile)"
    }
    foreach ($directory in @($data.directories)) {
      # Only ever delete a directory that the manifest names and that is
      # actually an uniservice directory.
      if ($directory -and (Test-Path -LiteralPath $directory) -and (Split-Path -Leaf $directory) -eq 'uniservice') {
        Remove-Item -Recurse -Force -LiteralPath $directory -ErrorAction SilentlyContinue
      }
    }
    Remove-Item -Force -LiteralPath $manifestPath -ErrorAction SilentlyContinue
  }

  $pipx = Get-Command pipx -ErrorAction SilentlyContinue
  if ($pipx) {
    & pipx uninstall $programName 2>$null
    if ($LASTEXITCODE -eq 0) { $removedSomething = $true }
  }

  if (-not $removedSomething) {
    Write-Warn "nothing was removed: no installation manifest at $manifestPath"
  } else {
    Write-Info 'OK: uninstalled uniservice'
  }
  exit 0
}

# ---------------------------------------------------------------------------
# pipx
# ---------------------------------------------------------------------------
if ($Pipx) {
  $pipx = Get-Command pipx -ErrorAction SilentlyContinue
  if (-not $pipx) {
    Fail 'pipx is not installed; see https://pipx.pypa.io/ or drop -Pipx'
  }
  & pipx install --force "$repoUrl/archive/refs/heads/main.tar.gz"
  if ($LASTEXITCODE -ne 0) { Fail 'pipx install failed' }
  Write-Info 'OK: installed uniservice with pipx'
  Write-Info "Hint: run 'uniservice --help' (add pipx's bin directory to PATH if needed)"
  exit 0
}

# ---------------------------------------------------------------------------
# Portable install: one .pyz file + a .cmd shim
# ---------------------------------------------------------------------------
$pythonCommand = Get-PythonCommand
if (-not $pythonCommand) {
  Show-PythonHint
  exit 1
}

$targetPrefix = if ($Prefix) { $Prefix } else { Join-Path $env:LOCALAPPDATA 'uniservice' }
$binDir = Join-Path $targetPrefix 'bin'
New-Item -ItemType Directory -Force -Path $binDir | Out-Null

$workDir = Join-Path ([System.IO.Path]::GetTempPath()) ("uniservice-" + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $workDir | Out-Null

try {
  $artifact = Join-Path $workDir "$programName.pyz"
  $resolvedVersion = Resolve-Artifact -Destination $artifact -WorkDir $workDir -PythonCommand $pythonCommand

  if ($Sha256) {
    $actual = (Get-FileHash -LiteralPath $artifact -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $Sha256.ToLowerInvariant()) {
      Fail "SHA-256 mismatch: expected $Sha256, got $actual"
    }
    Write-Info "SHA-256 verified: $actual"
  }

  $installedVersion = $Version
  if (-not $installedVersion) {
    try {
      $prefixArgs = $pythonCommand.PrefixArgs
      $output = (& $pythonCommand.File @prefixArgs $artifact --version 2>$null | Out-String).Trim()
      if ($output -match '(\S+)\s*$') { $installedVersion = $Matches[1] }
    } catch {}
  }
  if (-not $installedVersion) { $installedVersion = $resolvedVersion }

  $targetPyz = Join-Path $binDir "$programName.pyz"
  Copy-Item -LiteralPath $artifact -Destination $targetPyz -Force

  $shim = Join-Path $binDir "$programName.cmd"
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
  Write-Info "Installed $shim (version $installedVersion)"

  # Remove modules from the pre-1.2.0 layout.
  foreach ($legacy in @('uniservice', 'utils.py', 'backend_base.py', 'linux_backend.py', 'mac_backend.py', 'windows_backend.py')) {
    $legacyPath = Join-Path $binDir $legacy
    if (Test-Path -LiteralPath $legacyPath) { Remove-Item -Force -LiteralPath $legacyPath }
  }
  $legacyPackage = Join-Path $binDir $packageName
  if (Test-Path -LiteralPath $legacyPackage) { Remove-Item -Recurse -Force -LiteralPath $legacyPackage }

  # PATH
  $profilePath = $null
  $isDefaultPrefix = -not $Prefix
  if (-not $NoModifyPath -and $isDefaultPrefix) {
    $currentPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    if (-not $currentPath) { $currentPath = '' }
    $parts = $currentPath -split ';' | Where-Object { $_ -ne '' }
    if ($parts -notcontains $binDir) {
      [Environment]::SetEnvironmentVariable('Path', (($parts + $binDir) -join ';'), 'User')
      $env:Path = $env:Path + ';' + $binDir
      Write-Info "Added $binDir to the user PATH"
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
      Write-Info "Added $binDir to your PowerShell profile"
    }
  } elseif (-not $NoModifyPath) {
    Write-Info "Note: add $binDir to PATH yourself (custom -Prefix)"
  }

  $manifest = [ordered]@{
    schema          = 1
    program         = $programName
    version         = $installedVersion
    repository      = $repoSlug
    prefix          = $targetPrefix
    installed_at    = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
    files           = @($targetPyz, $shim)
    directories     = @($targetPrefix)
    profile         = $profilePath
    profile_managed = [bool]$profilePath
  }
  Set-Content -LiteralPath (Get-ManifestPath -TargetPrefix $targetPrefix) `
    -Value ($manifest | ConvertTo-Json -Depth 4) -Encoding UTF8

  Write-Info ''
  Write-Info "OK: installed $programName $installedVersion"
  Write-Info "Hint: reopen PowerShell/CMD, then run: $programName --help"
  Write-Info ''
  Write-Info "Note: $programName creates Scheduled Tasks that run as SYSTEM, so 'add',"
  Write-Info "      'start', 'stop' and 'remove' need an Administrator PowerShell/CMD."
  Write-Info "      '$programName list' works without elevation."
} finally {
  if (Test-Path -LiteralPath $workDir) {
    Remove-Item -Recurse -Force -LiteralPath $workDir -ErrorAction SilentlyContinue
  }
}
