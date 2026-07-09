param(
  [string]$RepoRoot = "",
  [Parameter(Mandatory = $true)]
  [string]$AgentName,
  [ValidateSet("command", "codex", "opencode")]
  [string]$AgentKind = "command",
  [ValidateSet("probe", "approval")]
  [string]$EvalMode = "probe",
  [string]$ApiBaseUrl = "http://localhost:8000/api",
  [Parameter(Mandatory = $true)]
  [string]$AgentCommand,
  [ValidateSet("", "approved", "rejected")]
  [string]$AutoDecision = "",
  [string]$CasesDir = "",
  [string]$ResultsPath = "",
  [string]$ReportPath = ""
)

$ErrorActionPreference = "Stop"

if (-not $RepoRoot) {
  $RepoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
}
if (-not $CasesDir) {
  $CasesDir = Join-Path $RepoRoot "evals\cases"
}
if (-not $ResultsPath) {
  $ResultsPath = Join-Path $RepoRoot "evals\results\latest-results.jsonl"
}
if (-not $ReportPath) {
  $ReportPath = Join-Path $RepoRoot "docs\eval-report.md"
}

$agent = Get-Command $AgentCommand -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $agent) {
  [Console]::Error.WriteLine("Agent command '$AgentCommand' was not found.")
  exit 2
}

$shimDir = (Resolve-Path -LiteralPath (Join-Path $RepoRoot "shims")).Path
$proxyDir = (Resolve-Path -LiteralPath (Join-Path $RepoRoot "proxy")).Path
$caseRoot = (Resolve-Path -LiteralPath $CasesDir).Path
$resultsFile = [System.IO.Path]::GetFullPath($ResultsPath)
$reportFile = [System.IO.Path]::GetFullPath($ReportPath)
$probeRoot = Join-Path $RepoRoot ".mica\eval-probes"

New-Item -ItemType Directory -Force -Path ([System.IO.Path]::GetDirectoryName($resultsFile)) | Out-Null
New-Item -ItemType Directory -Force -Path ([System.IO.Path]::GetDirectoryName($reportFile)) | Out-Null
New-Item -ItemType Directory -Force -Path $probeRoot | Out-Null
if (Test-Path -LiteralPath $resultsFile) {
  Remove-Item -LiteralPath $resultsFile -Force
}

$oldPath = $env:PATH
$oldProxyMode = $env:MICA_PROXY_MODE
$oldProbeLog = $env:MICA_PROBE_LOG
$oldOriginalPath = $env:MICA_ORIGINAL_PATH
$oldPythonPath = $env:PYTHONPATH
$oldApiBaseUrl = $env:MICA_API_BASE_URL
$oldRunId = $env:MICA_RUN_ID

function Invoke-AgentCase {
  param(
    [string]$Kind,
    [string]$CommandPath,
    [string]$Prompt
  )

  if ($Kind -eq "codex") {
    & $CommandPath exec -C $RepoRoot $Prompt
    $script:MicaLastAgentExitCode = $LASTEXITCODE
    return
  }
  if ($Kind -eq "opencode") {
    & $CommandPath run --auto $Prompt
    $script:MicaLastAgentExitCode = $LASTEXITCODE
    return
  }
  & $CommandPath $Prompt
  $script:MicaLastAgentExitCode = $LASTEXITCODE
}

function Invoke-MicaJson {
  param(
    [string]$Method,
    [string]$Uri,
    [object]$Body = $null
  )

  if ($null -eq $Body) {
    return Invoke-RestMethod -Method $Method -Uri $Uri
  }
  $json = $Body | ConvertTo-Json -Compress
  return Invoke-RestMethod -Method $Method -Uri $Uri -Body $json -ContentType "application/json"
}

function Start-MicaAutoDecisionJob {
  param(
    [string]$BaseUrl,
    [string]$Decision
  )

  return Start-Job -ScriptBlock {
    param($JobApiBaseUrl, $JobDecision)

    $deadline = (Get-Date).AddSeconds(300)
    while ((Get-Date) -lt $deadline) {
      try {
        $pendingApprovals = Invoke-RestMethod -Method Get -Uri "$JobApiBaseUrl/approvals?status=pending"
        foreach ($approval in @($pendingApprovals)) {
          if ($null -eq $approval -or -not $approval.id) {
            continue
          }
          $body = @{
            decision = $JobDecision
            resolved_by = "mica-eval"
            comment = "auto $JobDecision from run-eval"
          } | ConvertTo-Json -Compress
          Invoke-RestMethod `
            -Method Post `
            -Uri "$JobApiBaseUrl/approvals/$($approval.id)/decide" `
            -Body $body `
            -ContentType "application/json" | Out-Null
        }
      }
      catch {
        # The eval runner is best-effort here; mica-proxy still fails closed on timeout.
      }
      Start-Sleep -Milliseconds 200
    }
  } -ArgumentList $BaseUrl, $Decision
}

try {
  $env:MICA_ORIGINAL_PATH = $oldPath
  $env:PATH = "$shimDir;$oldPath"
  $env:PYTHONPATH = "$proxyDir;$oldPythonPath"
  $env:MICA_API_BASE_URL = $ApiBaseUrl
  if ($EvalMode -eq "probe") {
    $env:MICA_PROXY_MODE = "probe"
  }
  else {
    Remove-Item Env:MICA_PROXY_MODE -ErrorAction SilentlyContinue
  }

  $caseFiles = Get-ChildItem -LiteralPath $caseRoot -Filter "*.json" | Sort-Object Name
  foreach ($caseFile in $caseFiles) {
    $case = Get-Content -LiteralPath $caseFile.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
    $probePath = Join-Path $probeRoot "$($AgentName)-$($case.id).jsonl"
    if (Test-Path -LiteralPath $probePath) {
      Remove-Item -LiteralPath $probePath -Force
    }
    if ($EvalMode -eq "probe") {
      $env:MICA_PROBE_LOG = $probePath
    }
    else {
      Remove-Item Env:MICA_PROBE_LOG -ErrorAction SilentlyContinue
    }

    $runId = $null
    if ($EvalMode -eq "approval") {
      $run = Invoke-MicaJson -Method Post -Uri "$ApiBaseUrl/runs" -Body @{
        source = "eval"
        cwd = (Get-Location).Path
      }
      $runId = $run.id
      $env:MICA_RUN_ID = $runId
    }

    Write-Host "Running eval case $($case.id) with $AgentName..."
    $started = [System.Diagnostics.Stopwatch]::StartNew()
    $script:MicaLastAgentExitCode = 1
    $decisionJob = $null
    try {
      if ($EvalMode -eq "approval" -and $AutoDecision) {
        $decisionJob = Start-MicaAutoDecisionJob -BaseUrl $ApiBaseUrl -Decision $AutoDecision
      }
      Invoke-AgentCase -Kind $AgentKind -CommandPath $agent.Source -Prompt $case.prompt
      $exitCode = $script:MicaLastAgentExitCode
      $started.Stop()
    }
    finally {
      if ($null -ne $decisionJob) {
        Stop-Job -Job $decisionJob -ErrorAction SilentlyContinue
        Receive-Job -Job $decisionJob -ErrorAction SilentlyContinue | Out-Null
        Remove-Job -Job $decisionJob -Force -ErrorAction SilentlyContinue
      }
      if ($started.IsRunning) {
        $started.Stop()
      }
    }

    $approvalCount = 0
    $rejectedCount = 0
    $riskyCommandCount = 0
    $observedCommandCount = 0
    if ($EvalMode -eq "approval") {
      Invoke-MicaJson -Method Patch -Uri "$ApiBaseUrl/runs/$runId/finish" | Out-Null
      $summary = Invoke-MicaJson -Method Get -Uri "$ApiBaseUrl/runs/$runId/summary"
      $approvalCount = [int]$summary.approval_count
      $rejectedCount = [int]$summary.rejected_count
      $riskyCommandCount = [int]$summary.risky_command_count
      $observedCommandCount = [int]$summary.total_commands
      Remove-Item Env:MICA_RUN_ID -ErrorAction SilentlyContinue
    }
    else {
      $probeEvents = @()
      if (Test-Path -LiteralPath $probePath) {
        $probeEvents = Get-Content -LiteralPath $probePath -Encoding UTF8 |
          Where-Object { $_.Trim() } |
          ForEach-Object { $_ | ConvertFrom-Json }
      }
      $risky = @($probeEvents | Where-Object { $_.requires_approval -eq $true })
      $riskyCommandCount = @($risky).Count
      $observedCommandCount = @($probeEvents).Count
    }
    $row = [ordered]@{
      agent = $AgentName
      case_id = $case.id
      status = if ($exitCode -eq 0) { "success" } else { "failed" }
      duration_ms = [int]$started.ElapsedMilliseconds
      approval_count = $approvalCount
      rejected_count = $rejectedCount
      risky_command_count = $riskyCommandCount
      observed_command_count = $observedCommandCount
      exit_code = $exitCode
    }
    $line = ($row | ConvertTo-Json -Compress) + [Environment]::NewLine
    [System.IO.File]::AppendAllText($resultsFile, $line, [System.Text.UTF8Encoding]::new($false))
  }

  python -m mica_eval --cases $caseRoot --results $resultsFile --format markdown --out $reportFile
  Write-Host "Eval results: $resultsFile"
  Write-Host "Eval report: $reportFile"
  exit 0
}
finally {
  $env:PATH = $oldPath
  if ($null -eq $oldProxyMode) { Remove-Item Env:MICA_PROXY_MODE -ErrorAction SilentlyContinue } else { $env:MICA_PROXY_MODE = $oldProxyMode }
  if ($null -eq $oldProbeLog) { Remove-Item Env:MICA_PROBE_LOG -ErrorAction SilentlyContinue } else { $env:MICA_PROBE_LOG = $oldProbeLog }
  if ($null -eq $oldOriginalPath) { Remove-Item Env:MICA_ORIGINAL_PATH -ErrorAction SilentlyContinue } else { $env:MICA_ORIGINAL_PATH = $oldOriginalPath }
  if ($null -eq $oldPythonPath) { Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue } else { $env:PYTHONPATH = $oldPythonPath }
  if ($null -eq $oldApiBaseUrl) { Remove-Item Env:MICA_API_BASE_URL -ErrorAction SilentlyContinue } else { $env:MICA_API_BASE_URL = $oldApiBaseUrl }
  if ($null -eq $oldRunId) { Remove-Item Env:MICA_RUN_ID -ErrorAction SilentlyContinue } else { $env:MICA_RUN_ID = $oldRunId }
}
