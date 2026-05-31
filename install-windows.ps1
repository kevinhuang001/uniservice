Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Show-InstallHint {
  Write-Host "python3 未安装。请先安装 Python 3：" -ForegroundColor Yellow
  Write-Host "  - https://www.python.org/downloads/windows/"
  Write-Host "  - 或 Microsoft Store 搜索 Python"
  throw "Python 3 is required."
}

$root = $PSScriptRoot
$files = @(
  'uniservice',
  'utils.py',
  'backend_base.py',
  'linux_backend.py',
  'mac_backend.py',
  'windows_backend.py'
)
foreach ($f in $files) {
  $p = Join-Path $root $f
  if (-not (Test-Path -LiteralPath $p)) {
    throw "未找到 $p"
  }
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

foreach ($f in $files) {
  Copy-Item -LiteralPath (Join-Path $root $f) -Destination (Join-Path $installDir $f) -Force
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

Write-Host "OK: 已安装到 $installDir"
Write-Host "提示: 重新打开 PowerShell/CMD 后可直接使用 uniservice"
