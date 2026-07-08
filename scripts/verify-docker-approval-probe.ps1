param(
  [string]$ApiBaseUrl = "http://localhost:8000/api",
  [string]$ContainerApiBaseUrl = "http://host.docker.internal:8000/api",
  [ValidateSet("none", "bridge")]
  [string]$NetworkMode = "bridge",
  [string]$WorkDir = (Join-Path $env:TEMP "mica-docker-approval-probe"),
  [string]$Image = "mica-python-git:local",
  [string[]]$Command = @("git", "push", "origin", "main"),
  [ValidateSet("", "approved", "rejected")]
  [string]$AutoDecision = "",
  [int]$ExpectedExitCode = -1
)

$ErrorActionPreference = "Stop"

function Start-MicaAutoDecisionJob {
  param(
    [string]$BaseUrl,
    [string]$Decision
  )

  return Start-Job -ScriptBlock {
    param($JobApiBaseUrl, $JobDecision)

    $deadline = (Get-Date).AddSeconds(90)
    while ((Get-Date) -lt $deadline) {
      try {
        $pendingApprovals = Invoke-RestMethod -Method Get -Uri "$JobApiBaseUrl/approvals?status=pending"
        foreach ($approval in @($pendingApprovals)) {
          if ($null -eq $approval -or -not $approval.id) {
            continue
          }
          $body = @{
            decision = $JobDecision
            resolved_by = "mica-docker-approval-probe"
            comment = "auto $JobDecision from Docker approval probe"
          } | ConvertTo-Json -Compress
          Invoke-RestMethod `
            -Method Post `
            -Uri "$JobApiBaseUrl/approvals/$($approval.id)/decide" `
            -Body $body `
            -ContentType "application/json" | Out-Null
        }
      }
      catch {
        # The probe command remains blocked or fails closed if approval cannot be completed.
      }
      Start-Sleep -Milliseconds 200
    }
  } -ArgumentList $BaseUrl, $Decision
}

$workspace = [System.IO.Path]::GetFullPath($WorkDir)
New-Item -ItemType Directory -Force -Path $workspace | Out-Null

$decisionJob = $null
$started = [System.Diagnostics.Stopwatch]::StartNew()

try {
  if ($AutoDecision) {
    $decisionJob = Start-MicaAutoDecisionJob -BaseUrl $ApiBaseUrl -Decision $AutoDecision
  }

  $body = @{
    workspace = $workspace
    image = $Image
    network_mode = $NetworkMode
    allow_host_callback = ($NetworkMode -eq "bridge")
    command = $Command
    inject_proxy = $true
    api_base_url = $ContainerApiBaseUrl
  } | ConvertTo-Json -Depth 6

  $response = Invoke-RestMethod `
    -Method Post `
    -Uri "$ApiBaseUrl/docker/execute" `
    -Body $body `
    -ContentType "application/json"

  $started.Stop()
  $dockerExitCode = [int]$response.result.exit_code
  $effectiveExpectedExitCode = $ExpectedExitCode
  if ($effectiveExpectedExitCode -lt 0) {
    if ($AutoDecision -eq "rejected") {
      $effectiveExpectedExitCode = 126
    }
    elseif ($AutoDecision -eq "approved") {
      $effectiveExpectedExitCode = 0
    }
    else {
      $effectiveExpectedExitCode = $dockerExitCode
    }
  }

  if ($dockerExitCode -ne $effectiveExpectedExitCode) {
    throw "Expected Docker command exit code $effectiveExpectedExitCode, got $dockerExitCode."
  }

  $commandLine = $Command -join " "
  $approvalId = $response.command.approval_id
  $approvalStatus = $null
  $runSummary = $null
  try {
    $approvals = Invoke-RestMethod -Method Get -Uri "$ApiBaseUrl/approvals"
    $matchingApproval = (
      $approvals |
        Where-Object { $_.command_line -eq $commandLine } |
        Sort-Object -Property created_at -Descending |
        Select-Object -First 1
    )
    if ($null -ne $matchingApproval) {
      $approvalId = $matchingApproval.id
      $approvalStatus = $matchingApproval.status
    }
  }
  catch {
    # The probe result remains useful even if the history lookup is unavailable.
  }

  try {
    $runSummary = Invoke-RestMethod -Method Get -Uri "$ApiBaseUrl/runs/$($response.run.id)/summary"
  }
  catch {
    # Older or incompatible APIs may not expose run summaries yet.
  }

  [ordered]@{
    status = "completed"
    api_base_url = $ApiBaseUrl
    container_api_base_url = $ContainerApiBaseUrl
    network_mode = $NetworkMode
    allow_host_callback = ($NetworkMode -eq "bridge")
    workspace = $workspace
    image = $Image
    command = $Command
    inject_proxy = $true
    auto_decision = $AutoDecision
    expected_exit_code = $effectiveExpectedExitCode
    docker_exit_code = $dockerExitCode
    stdout = $response.result.stdout
    stderr = $response.result.stderr
    run_id = $response.run.id
    command_id = $response.command.id
    approval_id = $approvalId
    approval_status = $approvalStatus
    run_summary = $runSummary
    duration_ms = [int]$started.ElapsedMilliseconds
    boundary = "Docker approval probe. Proves API-level proxy injection path only when run against a real API and Docker image with Python plus target binaries."
  } | ConvertTo-Json -Depth 6
  exit 0
}
finally {
  if ($null -ne $decisionJob) {
    Stop-Job -Job $decisionJob -ErrorAction SilentlyContinue
    Receive-Job -Job $decisionJob -ErrorAction SilentlyContinue | Out-Null
    Remove-Job -Job $decisionJob -Force -ErrorAction SilentlyContinue
  }
}
