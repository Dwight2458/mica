# Slice 2 Spec: Controlled OpenCode Approval Mode

## Goal

After Slice 1 proves OpenCode reaches Mica PATH shims, Slice 2 starts using the same shim path for real approval enforcement.

This slice is intentionally narrow: run OpenCode under a controlled PATH, let high-risk external binary commands create approvals, and preserve the child process exit behavior.

## Entrypoint

Use:

```powershell
.\scripts\run-controlled-opencode.ps1 -Prompt "Run git push origin main exactly once. Do not edit files."
```

The script:

- resolves the real `opencode` command before changing PATH
- removes Mica shims from `MICA_ORIGINAL_PATH` to avoid recursion
- prepends `shims/` to PATH
- clears `MICA_PROXY_MODE` and `MICA_PROBE_LOG`
- sets `MICA_API_BASE_URL`
- creates a run record through `POST /api/runs`
- sets `MICA_RUN_ID` so proxy-created command records are grouped under the run
- runs `opencode run --auto <prompt>`
- finishes the run through `PATCH /api/runs/{id}/finish`
- returns OpenCode's process exit code

## Policy File

The proxy reads `policies/command-policy.json` by default. Set `MICA_POLICY_FILE` to use a custom policy for a run.

Rules are intentionally simple in this slice:

- `tool`: shimmed external binary name
- `argv_prefix`: prefix match against command argv
- `action`: `require_approval`
- `risk_level`: displayed and persisted with approval
- `reason`: displayed and persisted with approval

This slice includes shims for `git`, `npm`, `terraform`, and `kubectl`. Policy rules for tools without shims do not enforce anything in Local mode.

## Approval Behavior

When OpenCode invokes `git push`, the `git.cmd` shim calls `mica-proxy`.

- If approved, `mica-proxy` executes the real `git` executable and returns its exit code.
- If rejected, `mica-proxy` prints `MICA_APPROVAL_REJECTED` and returns `126`.
- If the API is unavailable, the proxy fails closed.
- If approval times out, the proxy prints `MICA_APPROVAL_TIMEOUT` and returns `124`.

## Command Records

The proxy creates command records for commands that reach Mica shims:

- low-risk commands: `started` then `completed` or `failed`
- high-risk commands: `waiting_approval` with `approval_id`, then `completed`, `failed`, `rejected`, or `timeout`

Command records include exit code and duration. They do not yet store stdout or stderr; those streams still pass directly through to the Agent CLI.

## Run Records and Summaries

The controlled OpenCode launcher creates one run record before starting OpenCode. Every shimmed command record created by `mica-proxy` includes the current `MICA_RUN_ID`.

The API exposes:

- `GET /api/runs`
- `GET /api/runs/{id}`
- `PATCH /api/runs/{id}/finish`
- `GET /api/runs/{id}/summary`

The summary reports total commands, successful commands, failed commands, approval count, rejected count, risky command count, total command duration, and a small failure summary for the first failed, rejected, or timed-out command.

The web UI exposes the same information at `/runs`.

## Event Records and Trace View

Service-layer state changes write trace events into `events`.

Current events include:

- `run_created`
- `command_started`
- `command_finished`
- `approval_required`
- `approval_approved`
- `approval_rejected`
- `run_completed`
- `run_failed`

The API exposes:

- `GET /api/events`
- `GET /api/events?run_id=<run-id>`
- `GET /api/events/stream?run_id=<run-id>`
- `GET /api/events/stream?run_id=<run-id>&replay=true`

The `/runs` page shows a run-scoped Trace Events panel with event message, related command or approval id, and JSON payload. The panel subscribes to the SSE stream; `replay=true` is available for deterministic debug and tests.

## Test Scope

Automated tests use a fake OpenCode CLI and a fake real `git.cmd` so they can prove approval behavior without pushing to a real remote.

Manual testing with real OpenCode must use a local test repository and local bare `origin` remote.

## Acceptance Criteria

- Fake OpenCode calling `git push origin main` creates a command approval payload.
- Approved decision executes the fake real git command.
- Rejected decision prevents real git execution and returns exit code `126`.
- Custom `MICA_POLICY_FILE` rules are honored when the matching shim exists.
- Low-risk and high-risk commands create command records.
- Controlled OpenCode runs create run records and link command records with `run_id`.
- Run summaries and failure summaries are available through API and `/runs`.
- Trace events are persisted for run, command, and approval state changes.
- The `/runs` page can show run-scoped trace events through SSE.
- Real OpenCode can be launched with `run-controlled-opencode.ps1`.
- Documentation warns that Local mode is still not a hard sandbox.
