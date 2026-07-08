param(
  [string]$RepoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path,
  [string]$ProbeLog = (Join-Path (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path ".mica\codex-probe.jsonl"),
  [string[]]$ExpectedTools = @("git", "npm", "terraform"),
  [string]$CodexCommand = "codex"
)

$ErrorActionPreference = "Stop"

$codex = Get-Command $CodexCommand -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $codex) {
  [Console]::Error.WriteLine("Codex CLI was not found. Install Codex first, then rerun this probe.")
  exit 2
}

$shimDir = (Resolve-Path -LiteralPath (Join-Path $RepoRoot "shims")).Path
$proxyDir = (Resolve-Path -LiteralPath (Join-Path $RepoRoot "proxy")).Path
$probePath = [System.IO.Path]::GetFullPath($ProbeLog)
New-Item -ItemType Directory -Force -Path ([System.IO.Path]::GetDirectoryName($probePath)) | Out-Null
if (Test-Path -LiteralPath $probePath) {
  Remove-Item -LiteralPath $probePath -Force
}

$originalPath = $env:PATH
$oldProxyMode = $env:MICA_PROXY_MODE
$oldProbeLog = $env:MICA_PROBE_LOG
$oldOriginalPath = $env:MICA_ORIGINAL_PATH
$oldPythonPath = $env:PYTHONPATH

try {
  $env:MICA_ORIGINAL_PATH = $originalPath
  $env:PATH = "$shimDir;$originalPath"
  $env:MICA_PROXY_MODE = "probe"
  $env:MICA_PROBE_LOG = $probePath
  $env:PYTHONPATH = "$proxyDir;$oldPythonPath"

  $prompt = @"
Run these shell commands exactly once from the current repository, without editing files:

git status
npm -v
terraform --version

After running them, summarize whether each command succeeded.
"@

  & $codex.Source exec -C $RepoRoot $prompt
  $codexExit = $LASTEXITCODE

  Write-Host ""
  Write-Host "Mica Codex probe summary:"
  python -m mica_probe --log $probePath --expect ($ExpectedTools -join ",")

  exit $codexExit
}
finally {
  $env:PATH = $originalPath
  if ($null -eq $oldProxyMode) { Remove-Item Env:MICA_PROXY_MODE -ErrorAction SilentlyContinue } else { $env:MICA_PROXY_MODE = $oldProxyMode }
  if ($null -eq $oldProbeLog) { Remove-Item Env:MICA_PROBE_LOG -ErrorAction SilentlyContinue } else { $env:MICA_PROBE_LOG = $oldProbeLog }
  if ($null -eq $oldOriginalPath) { Remove-Item Env:MICA_ORIGINAL_PATH -ErrorAction SilentlyContinue } else { $env:MICA_ORIGINAL_PATH = $oldOriginalPath }
  if ($null -eq $oldPythonPath) { Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue } else { $env:PYTHONPATH = $oldPythonPath }
}
