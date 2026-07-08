param(
  [string]$DockerCommand = "docker",
  [string]$Image = "mica-python-git:local",
  [string]$Dockerfile = "",
  [string]$Context = ""
)

$ErrorActionPreference = "Stop"

if (-not $Dockerfile) {
  $Dockerfile = Join-Path $PSScriptRoot "..\docker\mica-python-git.Dockerfile"
}

if (-not $Context) {
  $Context = Join-Path $PSScriptRoot ".."
}

$resolvedDockerfile = [System.IO.Path]::GetFullPath($Dockerfile)
$resolvedContext = [System.IO.Path]::GetFullPath($Context)
$started = [System.Diagnostics.Stopwatch]::StartNew()

function Write-MicaBuildResult {
  param(
    [string]$Status,
    [int]$ExitCode,
    [string[]]$OutputLines,
    [string]$ErrorMessage = ""
  )

  [ordered]@{
    status = $Status
    image = $Image
    dockerfile = $resolvedDockerfile
    context = $resolvedContext
    command = @($DockerCommand, "build", "-t", $Image, "-f", $resolvedDockerfile, $resolvedContext)
    exit_code = $ExitCode
    output = $OutputLines
    error_message = $ErrorMessage
    duration_ms = [int]$started.ElapsedMilliseconds
    boundary = "Builds a local Docker probe image with Python plus Git for Mica proxy-injection approval tests."
  } | ConvertTo-Json -Depth 6
}

if (-not (Test-Path -LiteralPath $resolvedDockerfile)) {
  Write-MicaBuildResult `
    -Status "failed" `
    -ExitCode 3 `
    -OutputLines @() `
    -ErrorMessage "Dockerfile not found: $resolvedDockerfile"
  exit 3
}

$docker = Get-Command $DockerCommand -ErrorAction SilentlyContinue | Select-Object -First 1
if ($null -eq $docker) {
  Write-MicaBuildResult `
    -Status "failed" `
    -ExitCode 2 `
    -OutputLines @() `
    -ErrorMessage "Docker command not found: $DockerCommand"
  exit 2
}

$arguments = @("build", "-t", $Image, "-f", $resolvedDockerfile, $resolvedContext)
$previousErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
try {
  $output = & $docker.Source @arguments 2>&1
  $exitCode = if ($null -ne $LASTEXITCODE) { [int]$LASTEXITCODE } else { 0 }
}
finally {
  $ErrorActionPreference = $previousErrorActionPreference
}
$started.Stop()
$status = if ($exitCode -eq 0) { "completed" } else { "failed" }
$lines = @($output | ForEach-Object { $_.ToString() })

Write-MicaBuildResult -Status $status -ExitCode $exitCode -OutputLines $lines
exit $exitCode
