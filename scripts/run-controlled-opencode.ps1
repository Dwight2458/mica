param(
  [string]$RepoRoot = "",
  [string]$OpenCodeCommand = "opencode",
  [Parameter(Mandatory = $true)]
  [string]$Prompt,
  [string]$ApiBaseUrl = "http://localhost:8000/api"
)

$ErrorActionPreference = "Stop"

if (-not $RepoRoot) {
  $RepoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
}

$opencode = Get-Command $OpenCodeCommand -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $opencode) {
  [Console]::Error.WriteLine("OpenCode CLI was not found. Install opencode first, then rerun this command.")
  exit 2
}

$shimDir = (Resolve-Path -LiteralPath (Join-Path $RepoRoot "shims")).Path
$proxyDir = (Resolve-Path -LiteralPath (Join-Path $RepoRoot "proxy")).Path

function Remove-ShimDirFromPath {
  param(
    [string]$PathValue,
    [string]$ShimDir
  )

  $parts = @()
  foreach ($part in ($PathValue -split ';')) {
    if (-not $part) {
      continue
    }
    $resolved = (Resolve-Path -LiteralPath $part -ErrorAction SilentlyContinue)
    if ($resolved -and $resolved.Path -eq $ShimDir) {
      continue
    }
    $parts += $part
  }
  return ($parts -join ';')
}

$oldPath = $env:PATH
$oldApiBaseUrl = $env:MICA_API_BASE_URL
$oldProxyMode = $env:MICA_PROXY_MODE
$oldProbeLog = $env:MICA_PROBE_LOG
$oldOriginalPath = $env:MICA_ORIGINAL_PATH
$oldPythonPath = $env:PYTHONPATH
$oldRunId = $env:MICA_RUN_ID

try {
  $originalPath = Remove-ShimDirFromPath -PathValue $oldPath -ShimDir $shimDir
  $env:MICA_ORIGINAL_PATH = $originalPath
  $env:PATH = "$shimDir;$originalPath"
  $env:MICA_API_BASE_URL = $ApiBaseUrl
  $env:PYTHONPATH = "$proxyDir;$oldPythonPath"

  Remove-Item Env:MICA_PROXY_MODE -ErrorAction SilentlyContinue
  Remove-Item Env:MICA_PROBE_LOG -ErrorAction SilentlyContinue

  $runId = $null
  try {
    $runPayload = @{
      source = "opencode"
      cwd = (Get-Location).Path
    } | ConvertTo-Json -Compress
    $run = Invoke-RestMethod -Method Post -Uri "$ApiBaseUrl/runs" -Body $runPayload -ContentType "application/json"
    $runId = $run.id
    $env:MICA_RUN_ID = $runId
    Write-Host "Mica run: $runId"
  }
  catch {
    Write-Warning "Could not create Mica run record. Commands may still execute, but they will not be grouped into a run. $($_.Exception.Message)"
    Remove-Item Env:MICA_RUN_ID -ErrorAction SilentlyContinue
  }

  & $opencode.Source run --auto $Prompt
  $opencodeExit = $LASTEXITCODE
  if ($runId) {
    try {
      Invoke-RestMethod -Method Patch -Uri "$ApiBaseUrl/runs/$runId/finish" | Out-Null
    }
    catch {
      Write-Warning "Could not finish Mica run record $runId. $($_.Exception.Message)"
    }
  }
  exit $opencodeExit
}
finally {
  $env:PATH = $oldPath
  if ($null -eq $oldApiBaseUrl) { Remove-Item Env:MICA_API_BASE_URL -ErrorAction SilentlyContinue } else { $env:MICA_API_BASE_URL = $oldApiBaseUrl }
  if ($null -eq $oldProxyMode) { Remove-Item Env:MICA_PROXY_MODE -ErrorAction SilentlyContinue } else { $env:MICA_PROXY_MODE = $oldProxyMode }
  if ($null -eq $oldProbeLog) { Remove-Item Env:MICA_PROBE_LOG -ErrorAction SilentlyContinue } else { $env:MICA_PROBE_LOG = $oldProbeLog }
  if ($null -eq $oldOriginalPath) { Remove-Item Env:MICA_ORIGINAL_PATH -ErrorAction SilentlyContinue } else { $env:MICA_ORIGINAL_PATH = $oldOriginalPath }
  if ($null -eq $oldPythonPath) { Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue } else { $env:PYTHONPATH = $oldPythonPath }
  if ($null -eq $oldRunId) { Remove-Item Env:MICA_RUN_ID -ErrorAction SilentlyContinue } else { $env:MICA_RUN_ID = $oldRunId }
}
