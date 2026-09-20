#
# Install the uniservice command for the current user.
#
# Two modes:
#   1. Run from a checkout: copies .\uniservice and .\uniservice_lib
#   2. Piped from the web:  downloads the repository archive and copies from it
#
# Environment overrides:
#   UNISERVICE_REPO_ARCHIVE  archive URL (default: the GitHub `main` zip)
#
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

try {
  $current = [Net.ServicePointManager]::SecurityProtocol
  [Net.ServicePointManager]::SecurityProtocol = $current -bor [Net.SecurityProtocolType]::Tls12
} catch {}

function Show-InstallHint {
  Write-Host "Python 3 is not installed. Please install Python 3.10+ first:" -ForegroundColor Yellow
  Write-Host "  - https://www.python.org/downloads/windows/"
  Write-Host "  - Or search for Python in Microsoft Store"
  throw "Python 3 is required."
}

$defaultArchive = 'https://github.com/kevinhuang001/uniservice/archive/refs/heads/main.zip'
$archiveUrl = if ($env:UNISERVICE_REPO_ARCHIVE) { $env:UNISERVICE_REPO_ARCHIVE } else { $defaultArchive }

$root = $PSScriptRoot
$needDownload = $true
if (-not [string]::IsNullOrWhiteSpace($root)) {
  if ((Test-Path -LiteralPath (Join-Path $root 'uniservice')) -and (Test-Path -LiteralPath (Join-Path $root 'uniservice_lib'))) {
    $needDownload = $false
  }
}

$tmpRoot = $null
try {
  if ($needDownload) {
    $tmpRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("uniservice-" + [Guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Force -Path $tmpRoot | Out-Null

    $zipPath = Join-Path $tmpRoot 'uniservice.zip'
    $params = @{ Uri = $archiveUrl; OutFile = $zipPath }
    if ($PSVersionTable.PSVersion.Major -lt 6) { $params.UseBasicParsing = $true }
    Invoke-WebRequest @params | Out-Null

    $extractDir = Join-Path $tmpRoot 'src'
    New-Item -ItemType Directory -Force -Path $extractDir | Out-Null
    if (Get-Command Expand-Archive -ErrorAction SilentlyContinue) {
      Expand-Archive -LiteralPath $zipPath -DestinationPath $extractDir -Force
    } else {
      Add-Type -AssemblyName System.IO.Compression.FileSystem
      [System.IO.Compression.ZipFile]::ExtractToDirectory($zipPath, $extractDir)
    }

    $candidate = Get-ChildItem -LiteralPath $extractDir -Directory |
      Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName 'uniservice') } |
      Select-Object -First 1
    if (-not $candidate) {
      throw "Could not find the unpacked uniservice sources in the archive."
    }
    $root = $candidate.FullName
  }

  if (-not (Test-Path -LiteralPath (Join-Path $root 'uniservice')) -or
      -not (Test-Path -LiteralPath (Join-Path $root 'uniservice_lib'))) {
    throw "Invalid uniservice sources in $root"
  }

  $py = Get-Command python -ErrorAction SilentlyContinue
  $py3 = Get-Command py -ErrorAction SilentlyContinue

  $hasPy3 = $false
  if ($py3) {
    try {
      & py -3 --version 1>$null 2>$null
      $hasPy3 = $true
    } catch {}
  }
  if (-not $hasPy3 -and $py) {
    try {
      $v = & python --version 2>&1
      if ($v -match '^Python\s+3\.') { $hasPy3 = $true }
    } catch {}
  }

  if (-not $hasPy3) {
    Show-InstallHint
  }

  $installDir = Join-Path $env:LOCALAPPDATA 'uniservice\bin'
  New-Item -ItemType Directory -Force -Path $installDir | Out-Null

  Copy-Item -LiteralPath (Join-Path $root 'uniservice') -Destination (Join-Path $installDir 'uniservice') -Force

  $targetLib = Join-Path $installDir 'uniservice_lib'
  if (Test-Path -LiteralPath $targetLib) {
    Remove-Item -Recurse -Force -LiteralPath $targetLib
  }
  Copy-Item -LiteralPath (Join-Path $root 'uniservice_lib') -Destination $targetLib -Recurse -Force

  $pycache = Join-Path $targetLib '__pycache__'
  if (Test-Path -LiteralPath $pycache) {
    Remove-Item -Recurse -Force -LiteralPath $pycache
  }

  # Remove modules from the pre-1.1.0 flat layout so a stale copy cannot shadow
  # the package.
  foreach ($legacy in @('utils.py', 'backend_base.py', 'linux_backend.py', 'mac_backend.py', 'windows_backend.py')) {
    $legacyPath = Join-Path $installDir $legacy
    if (Test-Path -LiteralPath $legacyPath) {
      Remove-Item -Force -LiteralPath $legacyPath
    }
  }

  $shim = Join-Path $installDir 'uniservice.cmd'
  $shimContent = @(
    '@echo off'
    'setlocal'
    'where py >nul 2>nul'
    'if %errorlevel%==0 ('
    '  py -3 "%~dp0uniservice" %*'
    '  exit /b %errorlevel%'
    ')'
    'where python >nul 2>nul'
    'if %errorlevel%==0 ('
    '  python "%~dp0uniservice" %*'
    '  exit /b %errorlevel%'
    ')'
    'echo Python 3 not found. Please install it from https://www.python.org/downloads/windows/'
    'exit /b 1'
  ) -join "`r`n"
  Set-Content -LiteralPath $shim -Value $shimContent -Encoding ASCII

  $currentPath = [Environment]::GetEnvironmentVariable('Path', 'User')
  if (-not $currentPath) { $currentPath = '' }
  $parts = $currentPath -split ';' | Where-Object { $_ -ne '' }
  if ($parts -notcontains $installDir) {
    $newPath = ($parts + $installDir) -join ';'
    [Environment]::SetEnvironmentVariable('Path', $newPath, 'User')
    $env:Path = $env:Path + ';' + $installDir
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
  }

  Write-Host "OK: Installed to $installDir"
  Write-Host "Hint: Reopen PowerShell/CMD, then run: uniservice --help"
} finally {
  if ($tmpRoot -and (Test-Path -LiteralPath $tmpRoot)) {
    Remove-Item -Recurse -Force -LiteralPath $tmpRoot
  }
}
