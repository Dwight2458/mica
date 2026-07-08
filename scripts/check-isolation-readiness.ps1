param(
  [string]$DockerCommand = "docker",
  [string]$WslCommand = "wsl",
  [string]$ReportPath = ""
)

$ErrorActionPreference = "Stop"

function Invoke-ToolCapture {
  param(
    [string]$Command,
    [string[]]$Arguments
  )

  $output = & $Command @Arguments 2>&1
  return @{
    exit_code = $LASTEXITCODE
    output = (($output | Out-String).Trim())
  }
}

function Normalize-ToolOutput {
  param([string]$Value)

  if ($null -eq $Value) {
    return ""
  }
  return (($Value -replace "`0", "") -replace "\s+", " ").Trim()
}

function Test-DockerReadiness {
  param([string]$Command)

  $docker = Get-Command $Command -ErrorAction SilentlyContinue | Select-Object -First 1
  if (-not $docker) {
    return [ordered]@{
      installed = $false
      daemon_reachable = $false
      version = $null
      diagnostic = "Docker CLI was not found."
    }
  }

  $version = Invoke-ToolCapture -Command $docker.Source -Arguments @("--version")
  $info = Invoke-ToolCapture -Command $docker.Source -Arguments @("info")
  return [ordered]@{
    installed = $true
    daemon_reachable = ($info.exit_code -eq 0)
    version = $version.output
    diagnostic = if ($info.exit_code -eq 0) { "Docker daemon reachable" } else { $info.output }
  }
}

function Test-WslReadiness {
  param([string]$Command)

  $wsl = Get-Command $Command -ErrorAction SilentlyContinue | Select-Object -First 1
  if (-not $wsl) {
    return [ordered]@{
      installed = $false
      wsl2_available = $false
      status = $null
      distributions = $null
      diagnostic = "WSL CLI was not found."
    }
  }

  $status = Invoke-ToolCapture -Command $wsl.Source -Arguments @("--status")
  $distributions = Invoke-ToolCapture -Command $wsl.Source -Arguments @("-l", "-v")
  $normalizedStatus = Normalize-ToolOutput -Value $status.output
  $normalizedDistributions = Normalize-ToolOutput -Value $distributions.output
  $combined = "$normalizedStatus $normalizedDistributions"
  return [ordered]@{
    installed = $true
    wsl2_available = ($combined -match "(?i)(Default Version:\s*2|Version\s+2|\s2\s*$)")
    status = $normalizedStatus
    distributions = $normalizedDistributions
    diagnostic = if ($combined -match "(?i)(Default Version:\s*2|Version\s+2|\s2\s*$)") { "WSL2 available" } else { "WSL found, but WSL2 was not confirmed." }
  }
}

function Get-Recommendation {
  param(
    [hashtable]$Docker,
    [hashtable]$Wsl
  )

  if ($Docker.daemon_reachable) {
    return "docker"
  }
  if ($Wsl.wsl2_available) {
    return "wsl2"
  }
  return "local-only"
}

function Write-ReadinessReport {
  param(
    [string]$Path,
    [hashtable]$Payload
  )

  $recommendation = $Payload.recommended_next_provider
  $summary = if ($recommendation -eq "local-only") {
    "No strong isolation provider is currently ready."
  }
  else {
    "Recommended next provider: $recommendation."
  }

  $markdown = @"
# Isolation Readiness Report

## Summary

$summary

## Docker

- Installed: $($Payload.docker.installed)
- Daemon reachable: $($Payload.docker.daemon_reachable)
- Diagnostic: $($Payload.docker.diagnostic)

## WSL

- Installed: $($Payload.wsl.installed)
- WSL2 available: $($Payload.wsl.wsl2_available)
- Diagnostic: $($Payload.wsl.diagnostic)

## Boundary

Local PATH shim mode remains non-sandboxed. This readiness check does not implement a Docker runner, WSL runner, filesystem policy, network policy, or hostile-process containment. It only reports whether this machine appears ready for a future stronger isolation slice.
"@

  New-Item -ItemType Directory -Force -Path ([System.IO.Path]::GetDirectoryName([System.IO.Path]::GetFullPath($Path))) | Out-Null
  [System.IO.File]::WriteAllText([System.IO.Path]::GetFullPath($Path), $markdown, [System.Text.UTF8Encoding]::new($false))
}

$dockerResult = Test-DockerReadiness -Command $DockerCommand
$wslResult = Test-WslReadiness -Command $WslCommand
$payload = [ordered]@{
  generated_at = (Get-Date).ToUniversalTime().ToString("o")
  docker = $dockerResult
  wsl = $wslResult
  recommended_next_provider = Get-Recommendation -Docker $dockerResult -Wsl $wslResult
  boundary = "Readiness only. Local PATH shim mode remains non-sandboxed until Docker, WSL2, or remote workers are actually used as the execution boundary."
}

if ($ReportPath) {
  Write-ReadinessReport -Path $ReportPath -Payload $payload
}

$payload | ConvertTo-Json -Depth 6
