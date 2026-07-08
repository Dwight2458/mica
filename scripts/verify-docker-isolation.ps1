param(
  [string]$DockerCommand = "docker",
  [string]$Image = "python:3.12-slim",
  [string]$WorkDir = (Join-Path $env:TEMP "mica-docker-isolation-spike"),
  [string]$ReportPath = ""
)

$ErrorActionPreference = "Stop"

function Write-SpikeReport {
  param(
    [string]$Path,
    [hashtable]$Payload
  )

  $markdown = @"
# Docker Isolation Spike

## Summary

- Status: $($Payload.status)
- Image: $($Payload.image)
- Exit code: $($Payload.exit_code)
- Network: $($Payload.network_mode)
- Workspace: $($Payload.workspace)

## Evidence

The spike ran a single container with:

- `--rm`
- `--network none`
- network: none
- mounted workspace: $($Payload.workspace) -> /workspace
- working directory: `/workspace`

Container stdout:

~~~text
$($Payload.stdout)
~~~

Container stderr:

~~~text
$($Payload.stderr)
~~~

## Boundary

This is a spike, not a full Docker Runner. It proves that this machine can execute a command in a disposable container with network disabled and a mounted throwaway workspace. It does not yet provide policy injection, command proxying inside the container, secret filtering, file diff capture, or lifecycle integration with Mica runs.
"@

  New-Item -ItemType Directory -Force -Path ([System.IO.Path]::GetDirectoryName([System.IO.Path]::GetFullPath($Path))) | Out-Null
  [System.IO.File]::WriteAllText([System.IO.Path]::GetFullPath($Path), $markdown, [System.Text.UTF8Encoding]::new($false))
}

$docker = Get-Command $DockerCommand -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $docker) {
  [Console]::Error.WriteLine("Docker CLI was not found.")
  exit 2
}

$workspace = [System.IO.Path]::GetFullPath($WorkDir)
New-Item -ItemType Directory -Force -Path $workspace | Out-Null

$containerCommand = "from pathlib import Path; p=Path('/workspace/mica-docker-proof.txt'); p.write_text('mica-docker-ok\n', encoding='utf-8'); print(p.read_text(encoding='utf-8').strip())"
$mount = "type=bind,source=$workspace,target=/workspace"
$arguments = @(
  "run",
  "--rm",
  "--network", "none",
  "--mount", $mount,
  "-w", "/workspace",
  $Image,
  "python",
  "-c",
  $containerCommand
)

$started = [System.Diagnostics.Stopwatch]::StartNew()
$output = & $docker.Source @arguments 2>&1
$exitCode = $LASTEXITCODE
$started.Stop()
$combinedOutput = (($output | Out-String).Trim())
$proofPath = Join-Path $workspace "mica-docker-proof.txt"
$proofExists = Test-Path -LiteralPath $proofPath

$payload = [ordered]@{
  status = if ($exitCode -eq 0) { "completed" } else { "failed" }
  image = $Image
  exit_code = $exitCode
  duration_ms = [int]$started.ElapsedMilliseconds
  network_mode = "none"
  workspace = $workspace
  workspace_mounted = $proofExists
  proof_file = if ($proofExists) { $proofPath } else { $null }
  stdout = $combinedOutput
  stderr = ""
  command = "docker " + ($arguments -join " ")
  boundary = "Docker spike only. Not a full Docker Runner or strong policy integration yet."
}

if ($ReportPath) {
  Write-SpikeReport -Path $ReportPath -Payload $payload
}

$payload | ConvertTo-Json -Depth 6
exit $exitCode
