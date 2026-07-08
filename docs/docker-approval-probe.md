# Docker Approval Probe Evidence

Date: 2026-07-07

This document records the first real Docker approval probe for Mica's opt-in proxy injection path.

## What This Proves

- A container can run with Mica Linux shims mounted ahead of the original PATH.
- The shimmed `git` command reaches `python -m mica_proxy` inside the container.
- `mica_proxy` can call back to the host Mica API through `host.docker.internal`.
- The Docker API requires explicit `allow_host_callback=true` when `network_mode=bridge` is used for that callback path.
- A high-risk `git push origin main` command creates an approval record linked to the same Docker run.
- Auto-rejecting that approval makes the container command return exit code `126`.
- The run summary includes both the outer Docker command and the inner proxy-mediated `git push` command.

## Commands

Build the local probe image:

```powershell
.\scripts\build-docker-probe-image.ps1 -Image mica-python-git:local
```

Run the rejected approval probe against a temporary API on port `8010`:

```powershell
.\scripts\verify-docker-approval-probe.ps1 `
  -Image mica-python-git:local `
  -AutoDecision rejected `
  -NetworkMode bridge `
  -ApiBaseUrl http://127.0.0.1:8010/api `
  -ContainerApiBaseUrl http://host.docker.internal:8010/api
```

## Result

```json
{
  "status": "completed",
  "api_base_url": "http://127.0.0.1:8010/api",
  "container_api_base_url": "http://host.docker.internal:8010/api",
  "network_mode": "bridge",
  "allow_host_callback": true,
  "workspace": "C:\\Users\\24582\\AppData\\Local\\Temp\\mica-docker-approval-probe",
  "image": "mica-python-git:local",
  "command": ["git", "push", "origin", "main"],
  "inject_proxy": true,
  "auto_decision": "rejected",
  "expected_exit_code": 126,
  "docker_exit_code": 126,
  "run_id": "17ec036a-16af-43e0-8f38-694b94723ead",
  "command_id": "828d991e-1992-4bdd-b734-ccb064421d7c",
  "approval_id": "c63403f9-006e-49dc-9e06-c7b92d5fc28d",
  "approval_status": "rejected",
  "run_summary": {
    "run_id": "c1aa14d8-0436-46ac-bbf5-6ecfe6f06fbf",
    "source": "docker",
    "status": "failed",
    "total_commands": 2,
    "successful_commands": 0,
    "failed_commands": 2,
    "approval_count": 1,
    "rejected_count": 1,
    "risky_command_count": 1,
    "failure_summary": {
      "failed_command": "git push origin main",
      "exit_code": 126
    }
  },
  "duration_ms": 3116
}
```

## Boundary

This evidence proves the intended Docker PATH shim and approval path for an external binary command. It does not prove hostile-process containment, file diff capture, live streaming from Docker, or protection against absolute binary paths inside the container.

The default Docker runner still uses `network_mode=none`. This probe intentionally uses `network_mode=bridge` plus `allow_host_callback=true` so the containerized proxy can call back to the host approval API.
