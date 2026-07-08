param(
  [string]$ApiBaseUrl = "http://localhost:8000/api",
  [string]$ContainerApiBaseUrl = "http://host.docker.internal:8000/api",
  [ValidateSet("none", "bridge")]
  [string]$NetworkMode = "bridge",
  [string]$WorkDir = (Join-Path $env:TEMP "mica-docker-demo-capture"),
  [string]$Image = "mica-python-git:local",
  [string[]]$Command = @("git", "push", "origin", "main"),
  [ValidateSet("", "approved", "rejected")]
  [string]$AutoDecision = "rejected",
  [int]$ExpectedExitCode = -1,
  [string]$ReportPath = (Join-Path (Get-Location) "docs\docker-demo-capture.md")
)

$ErrorActionPreference = "Stop"

function Invoke-MicaGet {
  param(
    [string]$BaseUrl,
    [string]$Path
  )

  try {
    return Invoke-RestMethod -Method Get -Uri "$BaseUrl/$Path"
  }
  catch {
    return $null
  }
}

function ConvertTo-MicaJsonBlock {
  param([object]$Value)

  if ($null -eq $Value) {
    return "null"
  }
  return ($Value | ConvertTo-Json -Depth 12)
}

function Add-MicaSection {
  param(
    [System.Text.StringBuilder]$Builder,
    [string]$Title,
    [string]$Body
  )

  [void]$Builder.AppendLine("")
  [void]$Builder.AppendLine("## $Title")
  [void]$Builder.AppendLine("")
  [void]$Builder.AppendLine($Body)
}

$probeScript = Join-Path $PSScriptRoot "verify-docker-approval-probe.ps1"
if (-not (Test-Path -LiteralPath $probeScript)) {
  throw "Missing probe script: $probeScript"
}

$workspace = [System.IO.Path]::GetFullPath($WorkDir)
$resolvedReportPath = [System.IO.Path]::GetFullPath($ReportPath)
$reportDirectory = Split-Path -Parent $resolvedReportPath
if ($reportDirectory) {
  New-Item -ItemType Directory -Force -Path $reportDirectory | Out-Null
}

$probeParams = @{
  ApiBaseUrl = $ApiBaseUrl
  ContainerApiBaseUrl = $ContainerApiBaseUrl
  NetworkMode = $NetworkMode
  WorkDir = $workspace
  Image = $Image
  Command = $Command
  AutoDecision = $AutoDecision
  ExpectedExitCode = $ExpectedExitCode
}

$probeOutput = & $probeScript @probeParams
if ($LASTEXITCODE -ne 0) {
  throw "Docker approval probe failed with exit code $LASTEXITCODE. Output: $probeOutput"
}

$probe = $probeOutput | ConvertFrom-Json
$runId = [string]$probe.run_id

$commands = @()
$events = @()
$approvals = @()
$summary = $probe.run_summary

if ($runId) {
  $commandsResponse = Invoke-MicaGet -BaseUrl $ApiBaseUrl -Path "commands?run_id=$([uri]::EscapeDataString($runId))"
  if ($null -ne $commandsResponse) {
    $commands = @($commandsResponse)
  }

  $eventsResponse = Invoke-MicaGet -BaseUrl $ApiBaseUrl -Path "events?run_id=$([uri]::EscapeDataString($runId))"
  if ($null -ne $eventsResponse) {
    $events = @($eventsResponse)
  }

  $summaryResponse = Invoke-MicaGet -BaseUrl $ApiBaseUrl -Path "runs/$([uri]::EscapeDataString($runId))/summary"
  if ($null -ne $summaryResponse) {
    $summary = $summaryResponse
  }
}

$approvalsResponse = Invoke-MicaGet -BaseUrl $ApiBaseUrl -Path "approvals"
if ($null -ne $approvalsResponse) {
  $approvals = @($approvalsResponse)
}

$commandLine = $Command -join " "
$builder = [System.Text.StringBuilder]::new()
[void]$builder.AppendLine("# Mica Docker Demo Capture")
[void]$builder.AppendLine("")
[void]$builder.AppendLine("Generated: $(Get-Date -Format o)")
[void]$builder.AppendLine("")
[void]$builder.AppendLine("This report captures one opt-in Docker proxy-injection demo run for Mica AgentOps.")

Add-MicaSection -Builder $builder -Title "Scenario" -Body @"
- API base URL: ``$ApiBaseUrl``
- Container API base URL: ``$ContainerApiBaseUrl``
- Image: ``$Image``
- Network mode: ``$NetworkMode``
- Allow host callback: ``$($probe.allow_host_callback)``
- Workspace: ``$workspace``
- Command: ``$commandLine``
- Auto decision: ``$AutoDecision``
"@

Add-MicaSection -Builder $builder -Title "Result" -Body @"
- Status: ``$($probe.status)``
- Run ID: ``$runId``
- Command ID: ``$($probe.command_id)``
- Approval ID: ``$($probe.approval_id)``
- Approval status: ``$($probe.approval_status)``
- Expected exit code: ``$($probe.expected_exit_code)``
- Docker exit code: ``$($probe.docker_exit_code)``
- Duration: ``$($probe.duration_ms)`` ms
- stderr: ``$($probe.stderr)``
"@

Add-MicaSection -Builder $builder -Title "Evidence Checklist" -Body @"
- Docker wrapper command recorded: ``$($commands.Count -gt 0)``
- Trace events captured: ``$($events.Count)``
- Approval records captured: ``$($approvals.Count)``
- Run summary captured: ``$($null -ne $summary)``
"@

Add-MicaSection -Builder $builder -Title "Run Summary" -Body "``````json`n$(ConvertTo-MicaJsonBlock -Value $summary)`n``````"
Add-MicaSection -Builder $builder -Title "Command Records" -Body "``````json`n$(ConvertTo-MicaJsonBlock -Value $commands)`n``````"
Add-MicaSection -Builder $builder -Title "Trace Events" -Body "``````json`n$(ConvertTo-MicaJsonBlock -Value $events)`n``````"
Add-MicaSection -Builder $builder -Title "Approval Records" -Body "``````json`n$(ConvertTo-MicaJsonBlock -Value $approvals)`n``````"

Add-MicaSection -Builder $builder -Title "Boundary" -Body @"
Local PATH shim mode is not a strong security sandbox.

This Docker demo proves the opt-in proxy injection and evidence collection path for external binary commands that resolve through mounted shims. It does not prove protection against hostile absolute-path execution, direct library calls, arbitrary network/file behavior inside binaries, or a complete container security profile.
"@

Set-Content -LiteralPath $resolvedReportPath -Value $builder.ToString() -Encoding utf8

[ordered]@{
  status = "completed"
  report_path = $resolvedReportPath
  run_id = $runId
  command_count = $commands.Count
  event_count = $events.Count
  approval_count = $approvals.Count
  docker_exit_code = [int]$probe.docker_exit_code
  boundary = "Demo capture only. Docker proxy injection is opt-in and Local PATH shim mode is not a strong security sandbox."
} | ConvertTo-Json -Depth 6
