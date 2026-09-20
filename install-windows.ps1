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

  Alternative: pipx install uniservice  (or: irm ... | iex -Pipx)

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

$RepoSlug = if ($env:UNISERVICE_REPO_SLUG) { $env:UNISERVICE_REPO_SLUG } else { 'kevinhuang001/uniservice' }
$RepoUrl = "https://github.com/$RepoSlug"
$ProgramName = 'uniservice'
$PackageName = 'uniservice_lib'
$ManifestName = 'install.json'

try {
  $current = [Net.ServicePointManager]::SecurityProtocol
  [Net.ServicePointManager]::SecurityProtocol = $current -bor [Net.SecurityProtocolType]::Tls12
} catch {}

function Write-Step { param([string]$Message) Write-Host $Message }
function Write-Note { param([string]$Message) Write-Host "WARNING: $Message" -ForegroundColor Yellow }
function Fail { param([string]$Message) throw "uniservice installer: $Message" }

function Get-PythonCommand {
  $py = Get-Command py -ErrorAction SilentlyContinue
  if ($py) {
    & py -3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' 2>$null
    if ($LASTEXITCODE -eq 0) { return @{ File = 'py'; PrefixArgs = @('-3') } }
  }
  $python = Get-Command python -ErrorAction SilentlyContinue
  if ($python) {
    & python -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' 2>$null
    if ($LASTEXITCODE -eq 0) { return @{ File = 'python'; PrefixArgs = @() } }
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
    $release = Invoke-RestMethod -Uri "https://api.github.com/repos/$RepoSlug/releases/latest" -Headers $headers
    if ($release -and $release.tag_name) { return [string]$release.tag_name }
  } catch {}
  return $null
}

function Expand-SourceArchive {
  param([string]$Ref, [string]$WorkDir)
  $zipPath = Join-Path $WorkDir 'source.zip'
  Write-Step "Downloading the source archive for $Ref"
  try {
    Save-File -Uri "$RepoUrl/archive/refs/heads/$Ref.zip" -Destination $zipPath
  } catch {
    Save-File -Uri "$RepoUrl/archive/refs/tags/$Ref.zip" -Destination $zipPath
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
    Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName $PackageName) } |
    Select-Object -First 1
  if (-not $candidate) { Fail 'unexpected source archive layout' }
  return $candidate.FullName
}

function New-Zipapp {
  param([string]$SourceDir, [string]$Destination, [hashtable]$PythonCommand)
  $builder = Join-Path $SourceDir 'scripts\build_zipapp.py'
  $prefixArgs = $PythonCommand.PrefixArgs
  if (Test-Path -LiteralPath $builder) {
    & $PythonCommand.File @prefixArgs $builder --source $SourceDir --output $Destination --quiet | Out-Null
  } else {
    & $PythonCommand.File @prefixArgs -m zipapp $SourceDir -o $Destination -c
  }
  if ($LASTEXITCODE -ne 0) { Fail "could not build the zipapp from $SourceDir" }
}

function Resolve-Artifact {
  param([string]$Destination, [string]$WorkDir, [hashtable]$PythonCommand)

  $tag = $Version
  if (-not $tag) {
    $tag = Get-LatestReleaseTag
    if ($tag) {
      Write-Step "Latest release: $tag"
    } else {
      Write-Note 'this repository has no releases yet; falling back to the unpinned main branch'
    }
  }

  if ($tag) {
    $asset = "$RepoUrl/releases/download/$tag/$ProgramName"
    try {
      Save-File -Uri $asset -Destination $Destination
      Write-Step "Downloaded $asset"
      return $tag
    } catch {
      Write-Note "no $ProgramName asset in release $tag; building it from that tag's source archive"
    }
  }

  $ref = if ($tag) { $tag } else { 'main' }
  $sourceDir = Expand-SourceArchive -Ref $ref -WorkDir $WorkDir
  New-Zipapp -SourceDir $sourceDir -Destination $Destination -PythonCommand $PythonCommand
  return $ref
}

function Get-ManifestPath {
  param([string]$TargetPrefix)
  return (Join-Path $TargetPrefix $ManifestName)
}

function Invoke-Uninstall {
  param([string]$TargetPrefix)
  $manifestPath = Get-ManifestPath -TargetPrefix $TargetPrefix
  $removedSomething = $false

  if (Test-Path -LiteralPath $manifestPath) {
    $data = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    foreach ($entry in @($data.files)) {
      if ($entry -and (Test-Path -LiteralPath $entry)) {
        Remove-Item -Force -LiteralPath $entry
        Write-Step "Removed $entry"
        $removedSomething = $true
      }
    }
    Remove-Item -Force -LiteralPath $manifestPath -ErrorAction SilentlyContinue

    # Prune directories that are empty now, deepest first, and only inside the
    # recorded prefix: a wrong -Prefix can therefore never delete real content.
    if ($data.prefix -and (Test-Path -LiteralPath $data.prefix)) {
      Get-ChildItem -LiteralPath $data.prefix -Recurse -Directory -Force -ErrorAction SilentlyContinue |
        Sort-Object { $_.FullName.Length } -Descending |
        ForEach-Object {
          if (-not (Get-ChildItem -LiteralPath $_.FullName -Force -ErrorAction SilentlyContinue)) {
            Remove-Item -LiteralPath $_.FullName -Force -ErrorAction SilentlyContinue
          }
        }
      if (-not (Get-ChildItem -LiteralPath $data.prefix -Force -ErrorAction SilentlyContinue)) {
        Remove-Item -LiteralPath $data.prefix -Force -ErrorAction SilentlyContinue
      }
    }
    if ($data.profile_managed) {
      Write-Note "the PowerShell profile may still contain a PATH line for uniservice: $($data.profile)"
    }
  }

  $pipx = Get-Command pipx -ErrorAction SilentlyContinue
  if ($pipx) {
    & pipx uninstall $ProgramName 2>$null
    if ($LASTEXITCODE -eq 0) { $removedSomething = $true }
  }

  if ($removedSomething) {
    Write-Step 'OK: uninstalled uniservice'
  } else {
    Write-Note "nothing was removed: no installation manifest at $manifestPath"
  }
}

function Invoke-PipxInstall {
  $pipx = Get-Command pipx -ErrorAction SilentlyContinue
  if (-not $pipx) {
    Fail 'pipx is not installed; see https://pipx.pypa.io/ or drop -Pipx'
  }
  & pipx install --force "$RepoUrl/archive/refs/heads/main.tar.gz"
  if ($LASTEXITCODE -ne 0) { Fail 'pipx install failed' }
  Write-Step 'OK: installed uniservice with pipx'
  Write-Step "Hint: run 'uniservice --help' (add pipx's bin directory to PATH if needed)"
}

function Invoke-PortableInstall {
  param([string]$TargetPrefix)

  $pythonCommand = Get-PythonCommand
  if (-not $pythonCommand) {
    Show-PythonHint
    Fail 'Python 3.10+ is required'
  }

  $binDir = Join-Path $TargetPrefix 'bin'
  New-Item -ItemType Directory -Force -Path $binDir | Out-Null

  $workDir = Join-Path ([System.IO.Path]::GetTempPath()) ("uniservice-" + [Guid]::NewGuid().ToString('N'))
  New-Item -ItemType Directory -Force -Path $workDir | Out-Null

  try {
    $artifact = Join-Path $workDir "$ProgramName.pyz"
    $resolvedVersion = Resolve-Artifact -Destination $artifact -WorkDir $workDir -PythonCommand $pythonCommand

    if ($Sha256) {
      $actual = (Get-FileHash -LiteralPath $artifact -Algorithm SHA256).Hash.ToLowerInvariant()
      if ($actual -ne $Sha256.ToLowerInvariant()) {
        Fail "SHA-256 mismatch: expected $Sha256, got $actual"
      }
      Write-Step "SHA-256 verified: $actual"
    }

    $installedVersion = $Version
    if (-not $installedVersion) {
      $prefixArgs = $pythonCommand.PrefixArgs
      $output = (& $pythonCommand.File @prefixArgs $artifact --version 2>$null | Out-String).Trim()
      if ($output -match '(\S+)\s*$') { $installedVersion = $Matches[1] }
    }
    if (-not $installedVersion) { $installedVersion = $resolvedVersion }

    $targetPyz = Join-Path $binDir "$ProgramName.pyz"
    Copy-Item -LiteralPath $artifact -Destination $targetPyz -Force

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
    Write-Step "Installed $shim (version $installedVersion)"

    # Remove the pre-1.2.0 layout, which copied the program and the package.
    foreach ($legacy in @('uniservice', 'utils.py', 'backend_base.py', 'linux_backend.py', 'mac_backend.py', 'windows_backend.py')) {
      $legacyPath = Join-Path $binDir $legacy
      if (Test-Path -LiteralPath $legacyPath) { Remove-Item -Force -LiteralPath $legacyPath }
    }
    $legacyPackage = Join-Path $binDir $PackageName
    if (Test-Path -LiteralPath $legacyPackage) { Remove-Item -Recurse -Force -LiteralPath $legacyPackage }

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

    $manifest = [ordered]@{
      schema          = 1
      program         = $ProgramName
      version         = $installedVersion
      repository      = $RepoSlug
      prefix          = $TargetPrefix
      installed_at    = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
      files           = @($targetPyz, $shim)
      profile         = $profilePath
      profile_managed = [bool]$profilePath
    }
    Set-Content -LiteralPath (Get-ManifestPath -TargetPrefix $TargetPrefix) `
      -Value ($manifest | ConvertTo-Json -Depth 4) -Encoding UTF8

    Write-Step ''
    Write-Step "OK: installed $ProgramName $installedVersion"
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
  $portablePrefix = if ($Prefix) { $Prefix } else { Join-Path $env:LOCALAPPDATA 'uniservice' }

  if ($Uninstall) {
    Invoke-Uninstall -TargetPrefix $portablePrefix
    return
  }
  if ($Pipx) {
    Invoke-PipxInstall
    return
  }
  Invoke-PortableInstall -TargetPrefix $portablePrefix
}

Invoke-Main
