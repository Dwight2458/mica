# Troubleshooting

This file records issues that were reproduced in this repository before being documented. Notes copied from related projects should be treated as hypotheses until they are rechecked here.

## Web Build: Google Fonts Fetch Failure

Symptom:

```text
next/font: error:
Failed to fetch `Geist` from Google Fonts.
```

Reproduced with:

```powershell
pnpm build:web
```

Resolution:

The Web app now uses system font stacks in `apps/web/src/app/globals.css` instead of `next/font/google`, so production builds do not depend on fetching Google Fonts.

## OpenCode Availability From Web

Validated without consuming a real agent prompt:

```powershell
opencode --version
```

and:

```http
GET /api/agent-runs/agents
```

On a machine with OpenCode installed, the API should return `opencode` with `available=true` and the resolved executable path. If unavailable, the `/runs` page disables the OpenCode option and shows the backend reason.

## Fake OpenCode Reproduction

The backend test suite uses a temporary `opencode.cmd` launcher that invokes a Python script. This verifies these behaviors without spending real model quota:

- JSON-line stdout is normalized into run events.
- Plain text stdout is preserved.
- stderr is written as `command_output` with `stream=stderr`.
- non-zero exit codes mark the run as `failed`.
- canceling a running child process marks the run as `cancelled`.
- high-risk `tool_use` output without a proxy-created approval records an `unintercepted` policy warning.

Run:

```powershell
cd apps/api
uv run pytest tests/test_agent_runs.py -q
```

## Real Prompt Runs

Starting a real OpenCode run from `/runs` may use the user's local OpenCode configuration, model account, subscription, or quota. Automated verification does not submit a real prompt by default. Use a local disposable repository when manually testing high-risk commands such as `git push`.

## Local-Mode Boundary

Mica's local Web-launched OpenCode runs inject a controlled PATH and `MICA_RUN_ID`, but local mode is not a strong sandbox. It governs external binaries that resolve through Mica shims. It does not reliably intercept PowerShell or cmd built-ins, absolute executable paths, direct library calls, or hostile child processes.
