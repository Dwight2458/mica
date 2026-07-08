# Docker Runner

Mica now includes a minimal Python `DockerRunner` implementation under `apps/api/app/runners/docker_runner.py`, Linux container shims under `docker-shims/`, and a small evidence service under `apps/api/app/services/docker_execution_service.py`.

This is the first code-level step after the Docker isolation spike. It is intentionally small: it executes one command in a disposable container, returns structured execution results, streams line-oriented stdout/stderr into trace events while the process is running, snapshots workspace files before and after execution, records Docker network-policy decisions and network-mode evidence, and can record that execution as a Mica run, command record, file-change evidence, network evidence, and event chain. It is exposed through an experimental API route. It also has an opt-in proxy injection configuration that mounts Mica's proxy, policy, and Linux shims into the container.

## Defaults

`DockerRunner` uses conservative local defaults:

- `docker run`
- `--rm`
- `--network none`
- bind mount the provided workspace to `/workspace`
- set working directory to `/workspace`
- do not mount the user's home directory

`network_mode` can be explicitly set to `bridge` for approval probes that need the containerized `mica-proxy` to call back to the host API. The default remains `none`. The API validates requests against `policies/docker-policy.json` and rejects `bridge` unless that policy allows it and the request also sets `allow_host_callback=true` and `inject_proxy=true`.

## Docker Network Policy

The default API policy lives at `policies/docker-policy.json`:

```json
{
  "version": 1,
  "network": {
    "allowed_modes": ["none", "bridge"],
    "require_host_callback_for_bridge": true,
    "require_proxy_injection_for_bridge": true
  }
}
```

`allowed_modes` controls which Docker `network_mode` values the experimental API accepts. `require_host_callback_for_bridge` keeps host callbacks explicit, and `require_proxy_injection_for_bridge` reserves `bridge` mode for runs that actually inject the containerized `mica-proxy`. Bridge networking is currently used only when that proxy must call back to the host Mica API during approval probes. Allowed runs record a `policy_decision` event before Docker starts, with the selected mode, allowed modes, callback flag, proxy-injection flag, and decision reason. This is API-level request validation plus trace evidence. It is not firewalling, packet inspection, or a complete network sandbox.

## Python Usage

```python
from pathlib import Path

from app.runners.docker_runner import DockerRunner

runner = DockerRunner(image="python:3.12-slim")
result = runner.run(
    workspace=Path(r"C:\path\to\throwaway-workspace"),
    command=["python", "-c", "print('hello from container')"],
)

print(result.exit_code)
print(result.stdout)
print(result.stderr)
print(result.duration_ms)
```

Record Docker execution evidence:

```python
from pathlib import Path

from app.db.session import Database
from app.services.docker_execution_service import DockerExecutionService

database = Database("sqlite:///mica.db")
database.init_db()

with database.session_factory() as session:
    evidence = DockerExecutionService(session).execute(
        workspace=Path(r"C:\path\to\throwaway-workspace"),
        command=["python", "-c", "print('hello from container')"],
    )

print(evidence.run.id)
print(evidence.command.exit_code)
print(evidence.result.stdout)
```

Opt into container proxy injection:

```python
from pathlib import Path

from app.runners.docker_runner import DockerProxyInjection, DockerRunner

repo = Path(r"C:\Users\24582\Projects\mica")
runner = DockerRunner(
    image="python:3.12-slim",
    proxy_injection=DockerProxyInjection(
        proxy_dir=repo / "proxy",
        shim_dir=repo / "docker-shims",
        policy_file=repo / "policies" / "command-policy.json",
        api_base_url="http://host.docker.internal:8000/api",
    ),
)
```

This mounts:

- `proxy/` to `/mica/proxy`
- `docker-shims/` to `/mica/shims`
- `policies/command-policy.json` to `/mica/policies/command-policy.json`
- `/mica/shims` before the container's original PATH
- `PYTHONPATH=/mica/proxy`
- `MICA_API_BASE_URL`, `MICA_POLICY_FILE`, and `MICA_ORIGINAL_PATH`

Call the experimental API:

```powershell
pnpm dev:api
```

```powershell
$body = @{
  workspace = "C:\path\to\throwaway-workspace"
  image = "python:3.12-slim"
  command = @("python", "-c", "print('hello from docker')")
} | ConvertTo-Json

Invoke-RestMethod `
  -Uri http://localhost:8000/api/docker/execute `
  -Method Post `
  -ContentType "application/json" `
  -Body $body
```

Enable proxy injection through the API:

```powershell
$body = @{
  workspace = "C:\path\to\throwaway-workspace"
  image = "mica-python-git:local"
  command = @("git", "status")
  inject_proxy = $true
  network_mode = "bridge"
  allow_host_callback = $true
  api_base_url = "http://host.docker.internal:8000/api"
} | ConvertTo-Json

Invoke-RestMethod `
  -Uri http://localhost:8000/api/docker/execute `
  -Method Post `
  -ContentType "application/json" `
  -Body $body
```

`image` defaults to `python:3.12-slim`. For approval probes, use an image that contains Python plus the target real executable, such as a local image with `git` installed. `inject_proxy` is off by default. Turning it on mounts `/mica/shims`, `/mica/proxy`, and `/mica/policies/command-policy.json` into the container and puts `/mica/shims` first in PATH. When `network_mode=bridge` is needed for host API callbacks, the request must also be allowed by `policies/docker-policy.json` and set `allow_host_callback=true` plus `inject_proxy=true`; otherwise the API fails closed with HTTP 400.

## Docker Approval Probe

Build the local probe image first:

```powershell
.\scripts\build-docker-probe-image.ps1 -Image mica-python-git:local
```

Use the probe script to verify the approval loop through the Docker execute API:

```powershell
pnpm dev:api
.\scripts\verify-docker-approval-probe.ps1 `
  -Image mica-python-git:local `
  -AutoDecision rejected `
  -NetworkMode bridge `
  -ApiBaseUrl http://localhost:8000/api `
  -ContainerApiBaseUrl http://host.docker.internal:8000/api
```

The script:

- creates a throwaway workspace
- posts to `/api/docker/execute`
- sets `inject_proxy=true`
- sets `network_mode=bridge` by default so the container can reach the host API
- sets `allow_host_callback=true` so the bridge network choice is explicit
- runs `git push origin main` by default
- uses `ApiBaseUrl` for host-side API calls and `ContainerApiBaseUrl` for the API URL injected into the container
- optionally polls `/approvals?status=pending` and auto-decides each approval
- expects `rejected` probes to return exit code `126`

The default image is built from `docker/mica-python-git.Dockerfile` and includes Python plus Git. This probe still does not prove hostile-process containment; it only checks the intended Docker PATH shim and approval path.

## Real Local Evidence

Verified on 2026-07-07 with:

```text
image: python:3.12-slim
network_mode: none
workspace: C:\Users\24582\AppData\Local\Temp\mica-docker-runner-real
exit_code: 0
stdout: mica-runner-ok
proof_exists: true
```

The runner wrote `runner-proof.txt` inside the mounted throwaway workspace from inside the container.

Docker approval proxy injection was also verified on 2026-07-07. A container running `mica-python-git:local` executed `git push origin main` through `/mica/shims/git`, created a high-risk approval linked to the same Docker run, received an auto-reject decision, and returned exit code `126`. The run summary showed two commands: the outer Docker execution and the inner proxy-mediated `git push`. The `/runs` page now exposes this as Run Evidence, and the API can query it directly through `GET /api/commands?run_id={id}`. See [Docker Approval Probe Evidence](docker-approval-probe.md).

Docker live output was verified on 2026-07-07. A slow Python command emitted five stdout lines over roughly six seconds; the first `command_output` event was visible after 847ms while the Docker API request was still running. See [Docker Live Output Evidence](docker-live-output.md).

Docker workspace evidence records `file_changed` trace events for files created, modified, or deleted under the mounted workspace. Each event includes the relative path, change type, and before/after size plus SHA-256 hashes when the file exists. This is audit evidence, not a filesystem security boundary.

Docker network evidence records one `network_evidence` trace event for each Docker execution. It captures the Docker `network_mode`, maps `none` to `network_access=disabled`, maps `bridge` to `network_access=host-reachable`, and flags `host_callback_required=true` for bridge mode. This is metadata evidence about how Docker was invoked; it is not packet capture, egress policy enforcement, or firewall proof.

Docker policy evidence records one `policy_decision` trace event for each allowed Docker API execution. It captures that the `docker-network` policy allowed the requested `network_mode`, the allowed mode list, whether `allow_host_callback` and `inject_proxy` were present, and whether bridge mode requires those flags.

## Automated Tests

Run:

```powershell
cd apps\api
uv run pytest tests/test_docker_runner.py
uv run pytest tests/test_docker_execution_service.py
uv run pytest tests/test_docker_execute_api.py
```

The tests verify:

- `--rm` is used
- `--network none` is used
- the workspace is bind-mounted to `/workspace`
- the container working directory is `/workspace`
- stdout, stderr, exit code, and duration are returned
- missing workspaces are rejected before Docker is invoked
- optional proxy injection mounts proxy, shims, and policy into the container
- optional proxy injection sets container PATH, PYTHONPATH, MICA_API_BASE_URL, MICA_POLICY_FILE, and MICA_ORIGINAL_PATH
- Linux Docker shims call `python -m mica_proxy`
- Docker executions can create run, command, streamed command-output, file-changed, network-evidence, command-finished, and run-completed evidence
- `POST /api/docker/execute` returns run, command, and Docker result payloads
- `POST /api/docker/execute` loads `policies/docker-policy.json`, rejects disallowed network modes, rejects `network_mode=bridge` unless `allow_host_callback=true` and `inject_proxy=true`, and records allowed decisions as `policy_decision` trace events
- run summaries include Docker command duration and success counts
- `build-docker-probe-image.ps1` invokes `docker build` with the local probe Dockerfile and emits JSON evidence

## Boundary

This is not a complete strong sandbox yet. Proxy injection prepares the container PATH for command proxying and has been verified with a Python plus Git probe image. Docker stdout/stderr is streamed into `command_output` events while the process is running, workspace file changes are recorded after command execution, Docker network mode is recorded as metadata, and `policies/docker-policy.json` validates the requested network mode before Docker starts with an allowed `policy_decision` trace event. These are governance and evidence features; they do not prevent hostile absolute-path execution, direct library calls, packet-level network behavior, or arbitrary behavior inside binaries.

The next step is to productize Docker approval mode: reduce the temporary `bridge` networking requirement where possible and add richer network policy controls beyond allowed modes and the explicit host-callback gate. Local PATH shim mode and Docker execution mode are different enforcement layers.
