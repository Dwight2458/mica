param(
  [string]$RepoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path,
  [string[]]$Tools = @("git", "npm", "terraform", "kubectl")
)

$ErrorActionPreference = "Stop"

$shimDir = (Resolve-Path -LiteralPath (Join-Path $RepoRoot "shims")).Path

Write-Host "Current PATH resolution:"
foreach ($tool in $Tools) {
  $command = Get-Command $tool -ErrorAction SilentlyContinue | Select-Object -First 1
  $source = if ($command) { $command.Source } else { "<missing>" }
  Write-Host "  $tool -> $source"
}

Write-Host ""
Write-Host "Controlled PATH resolution with shims first:"
$originalPath = $env:PATH
$env:PATH = "$shimDir;$originalPath"
try {
  foreach ($tool in $Tools) {
    $command = Get-Command $tool -ErrorAction SilentlyContinue | Select-Object -First 1
    $source = if ($command) { $command.Source } else { "<missing>" }
    $isShim = $source -like "$shimDir*"
    $status = if ($isShim) { "shim" } else { "not-shim" }
    Write-Host "  $tool -> $source [$status]"
  }
}
finally {
  $env:PATH = $originalPath
}

Write-Host ""
Write-Host "If a tool does not resolve to shims first, run scripts/install-shims.ps1 and ensure shims/ is first in PATH."
