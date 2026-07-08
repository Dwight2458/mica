param(
  [string]$RepoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path,
  [string]$ApiBaseUrl = "http://localhost:8000/api",
  [string]$WorkDir = (Join-Path $env:TEMP "mica-slice0-verify"),
  [switch]$SkipRepoSetup,
  [ValidateSet("", "approved", "rejected")]
  [string]$AutoDecision = ""
)

$ErrorActionPreference = "Stop"

function Start-MicaAutoDecisionJob {
  param(
    [string]$BaseUrl,
    [string]$Decision
  )

  return Start-Job -ScriptBlock {
    param($JobApiBaseUrl, $JobDecision)

    $deadline = (Get-Date).AddSeconds(60)
    while ((Get-Date) -lt $deadline) {
      try {
        $pendingApprovals = Invoke-RestMethod -Method Get -Uri "$JobApiBaseUrl/approvals?status=pending"
        foreach ($approval in @($pendingApprovals)) {
          if ($null -eq $approval -or -not $approval.id) {
            continue
          }
          $body = @{
            decision = $JobDecision
            resolved_by = "mica-slice0-verify"
            comment = "auto $JobDecision from verify-slice0"
          } | ConvertTo-Json -Compress
          Invoke-RestMethod `
            -Method Post `
            -Uri "$JobApiBaseUrl/approvals/$($approval.id)/decide" `
            -Body $body `
            -ContentType "application/json" | Out-Null
        }
      }
      catch {
        # The proxy remains fail-closed if approval cannot be completed.
      }
      Start-Sleep -Milliseconds 200
    }
  } -ArgumentList $BaseUrl, $Decision
}

function Initialize-ThrowawayRepo {
  param([string]$TargetDir)

  if (Test-Path -LiteralPath $TargetDir) {
    Remove-Item -LiteralPath $TargetDir -Recurse -Force
  }
  New-Item -ItemType Directory -Force -Path $TargetDir | Out-Null

  Push-Location -LiteralPath $TargetDir
  try {
    git init --bare remote.git | Out-Host
    git clone remote.git work | Out-Host
    Push-Location -LiteralPath (Join-Path $TargetDir "work")
    try {
      git config user.email "mica@example.local" | Out-Host
      git config user.name "Mica Demo" | Out-Host
      "hello" | Set-Content README.md
      git add README.md | Out-Host
      git commit -m "init" | Out-Host
      git branch -M main | Out-Host
    }
    finally {
      Pop-Location
    }
  }
  finally {
    Pop-Location
  }
}

$shimDir = (Resolve-Path -LiteralPath (Join-Path $RepoRoot "shims")).Path
$proxyDir = (Resolve-Path -LiteralPath (Join-Path $RepoRoot "proxy")).Path
$oldPath = $env:PATH
$oldOriginalPath = $env:MICA_ORIGINAL_PATH
$oldPythonPath = $env:PYTHONPATH
$oldApiBaseUrl = $env:MICA_API_BASE_URL
$oldApprovalTimeout = $env:MICA_APPROVAL_TIMEOUT_SECONDS
$oldApprovalPoll = $env:MICA_APPROVAL_POLL_SECONDS
$decisionJob = $null

try {
  if (-not $SkipRepoSetup) {
    Initialize-ThrowawayRepo -TargetDir $WorkDir
    $WorkDir = Join-Path $WorkDir "work"
  }
  else {
    New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null
  }

  $env:MICA_ORIGINAL_PATH = $oldPath
  $env:PATH = "$shimDir;$oldPath"
  $env:PYTHONPATH = "$proxyDir;$oldPythonPath"
  $env:MICA_API_BASE_URL = $ApiBaseUrl
  if (-not $env:MICA_APPROVAL_TIMEOUT_SECONDS) {
    $env:MICA_APPROVAL_TIMEOUT_SECONDS = "60"
  }
  if (-not $env:MICA_APPROVAL_POLL_SECONDS) {
    $env:MICA_APPROVAL_POLL_SECONDS = "0.2"
  }

  if ($AutoDecision) {
    $decisionJob = Start-MicaAutoDecisionJob -BaseUrl $ApiBaseUrl -Decision $AutoDecision
  }

  Push-Location -LiteralPath $WorkDir
  try {
    Write-Host "Checking low-risk command: git status"
    git status
    $statusExit = $LASTEXITCODE
    if ($statusExit -ne 0) {
      throw "Expected git status to exit 0, got $statusExit."
    }

    Write-Host "Checking high-risk command: git push origin main"
    git push origin main
    $pushExit = $LASTEXITCODE
  }
  finally {
    Pop-Location
  }

  if ($AutoDecision -eq "rejected" -and $pushExit -ne 126) {
    throw "Expected rejected git push to exit 126, got $pushExit."
  }
  if ($AutoDecision -eq "approved" -and $pushExit -ne 0) {
    throw "Expected approved git push to exit 0, got $pushExit."
  }
  if (-not $AutoDecision -and $pushExit -eq 0) {
    Write-Host "Manual approval path completed with exit 0."
  }

  Write-Host "Slice 0 verification passed"
  exit 0
}
finally {
  if ($null -ne $decisionJob) {
    Stop-Job -Job $decisionJob -ErrorAction SilentlyContinue
    Receive-Job -Job $decisionJob -ErrorAction SilentlyContinue | Out-Null
    Remove-Job -Job $decisionJob -Force -ErrorAction SilentlyContinue
  }
  $env:PATH = $oldPath
  if ($null -eq $oldOriginalPath) { Remove-Item Env:MICA_ORIGINAL_PATH -ErrorAction SilentlyContinue } else { $env:MICA_ORIGINAL_PATH = $oldOriginalPath }
  if ($null -eq $oldPythonPath) { Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue } else { $env:PYTHONPATH = $oldPythonPath }
  if ($null -eq $oldApiBaseUrl) { Remove-Item Env:MICA_API_BASE_URL -ErrorAction SilentlyContinue } else { $env:MICA_API_BASE_URL = $oldApiBaseUrl }
  if ($null -eq $oldApprovalTimeout) { Remove-Item Env:MICA_APPROVAL_TIMEOUT_SECONDS -ErrorAction SilentlyContinue } else { $env:MICA_APPROVAL_TIMEOUT_SECONDS = $oldApprovalTimeout }
  if ($null -eq $oldApprovalPoll) { Remove-Item Env:MICA_APPROVAL_POLL_SECONDS -ErrorAction SilentlyContinue } else { $env:MICA_APPROVAL_POLL_SECONDS = $oldApprovalPoll }
}
