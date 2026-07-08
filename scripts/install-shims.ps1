param(
  [string]$RepoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path,
  [string[]]$Tools = @("git", "npm", "terraform", "kubectl")
)

$ErrorActionPreference = "Stop"

$shimDir = Join-Path $RepoRoot "shims"
$proxyDir = Join-Path $RepoRoot "proxy"
New-Item -ItemType Directory -Force -Path $shimDir | Out-Null

$originalPath = $env:PATH
$shimFullPath = (Resolve-Path -LiteralPath $shimDir).Path
$pathParts = $originalPath -split ';' | Where-Object { $_ -and ((Resolve-Path -LiteralPath $_ -ErrorAction SilentlyContinue).Path -ne $shimFullPath) }
$env:PATH = ($pathParts -join ';')

try {
  foreach ($tool in $Tools) {
    $command = Get-Command $tool -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $command) {
      Write-Warning "Skipping $tool because no real executable was found on PATH."
      continue
    }

    $realPath = $command.Source
    $envName = "MICA_REAL_$($tool.ToUpperInvariant().Replace('-', '_'))"
    $shimPath = Join-Path $shimDir "$tool.cmd"
    $content = @"
@echo off
setlocal
set "$envName=$realPath"
set "MICA_PROXY_DIR=$proxyDir"
set "PYTHONPATH=%MICA_PROXY_DIR%;%PYTHONPATH%"
python -m mica_proxy --tool $tool -- %*
exit /b %ERRORLEVEL%
"@
    Set-Content -LiteralPath $shimPath -Value $content -Encoding ascii
    Write-Host "Generated shim: $shimPath -> $realPath"
  }
}
finally {
  $env:PATH = $originalPath
}

Write-Host ""
Write-Host "Use this controlled PATH in the current shell:"
Write-Host "`$env:MICA_ORIGINAL_PATH = '$originalPath'"
Write-Host "`$env:PATH = '$shimFullPath;' + `$env:MICA_ORIGINAL_PATH"
Write-Host "`$env:MICA_API_BASE_URL = 'http://localhost:8000/api'"
