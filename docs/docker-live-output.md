# Docker Live Output Evidence

Date: 2026-07-07

This document records the first real Docker live-output probe for Mica's Docker execution path.

## What This Proves

- Docker stdout is read while the container is still running.
- Each output line is written as its own `command_output` trace event.
- The Web `/runs` page can receive these events through the existing run-scoped SSE stream.
- The Web `/runs` page also replays historical events and renders `command_output` records in a dedicated monospace Realtime Logs panel.
- The final Docker result still preserves stdout and exit code.

## Probe Command

The probe ran a temporary API on port `8010`, then posted to `POST /api/docker/execute` with this container command:

```powershell
@("python", "-u", "-c", "import time; [print(f'line-{i}', flush=True) or time.sleep(1) for i in range(1,6)]")
```

The `-u` flag makes Python stdout unbuffered so each line is available to Docker immediately.

## Result

```json
{
  "status": "completed",
  "run_id": "8c9db811-058b-44cc-9427-a73acffcb5b8",
  "first_output_seen_at_ms": 847,
  "total_elapsed_ms": 5785,
  "response_exit_code": 0,
  "final_output_event_count": 5,
  "final_outputs": [
    "line-1\n",
    "line-2\n",
    "line-3\n",
    "line-4\n",
    "line-5\n"
  ],
  "poll_samples": [
    {
      "elapsed_ms": 308,
      "job_state": "Running",
      "output_count": 0
    },
    {
      "elapsed_ms": 588,
      "job_state": "Running",
      "output_count": 0
    },
    {
      "elapsed_ms": 847,
      "job_state": "Running",
      "output_count": 1
    }
  ]
}
```

The first output event appeared while the API request was still running. That is the key signal: Docker output is no longer only persisted after command completion.

## Boundary

This proves line-oriented stdout/stderr streaming from the Docker process into Mica trace events and the Run Detail UI. It does not yet provide a browser terminal emulator, stdin support, or backpressure-aware log storage.
