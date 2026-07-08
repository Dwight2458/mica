# Mica Demo Script

This walkthrough demonstrates Mica's current survival path: policy-gated command execution for local Coding Agent CLI workflows on Windows.

## What The Demo Proves

The demo should prove:

- external binary commands can be routed through Mica PATH shims
- low-risk commands run normally
- high-risk commands block before execution
- a Web approval controls whether the real command executes
- command, approval, run, event, and summary evidence is persisted
- probe mode can verify whether an Agent CLI reaches the shims before governance is claimed

## Setup

Install dependencies:

```powershell
pnpm install
cd apps\api
uv sync
cd ..\..
```

Start services:

```powershell
pnpm dev:api
pnpm dev:web
```

Open the Web console:

```text
http://localhost:3000
```

## Part 1: Slice 0 Command Approval

For a quick scripted verification, run:

```powershell
.\scripts\verify-slice0.ps1 -AutoDecision rejected -ApiBaseUrl http://localhost:8000/api
```

This creates a throwaway local bare repo and verifies the low-risk and rejected high-risk paths.

See [demo-evidence.md](demo-evidence.md) for a captured local run.

Create a throwaway local bare repository:

```powershell
$demoRoot = Join-Path $env:TEMP "mica-demo"
Remove-Item -Recurse -Force $demoRoot -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $demoRoot | Out-Null
Set-Location $demoRoot
git init --bare remote.git
git clone remote.git work
Set-Location work
"hello" | Set-Content README.md
git add README.md
git commit -m "init"
```

Enable Mica shims in that terminal:

```powershell
$repo = "C:\Users\24582\Projects\mica"
$env:MICA_ORIGINAL_PATH = $env:PATH
$env:PATH = "$repo\shims;$env:MICA_ORIGINAL_PATH"
$env:MICA_API_BASE_URL = "http://localhost:8000/api"
$env:PYTHONPATH = "$repo\proxy;$env:PYTHONPATH"
```

Run a low-risk command:

```powershell
git status
```

Expected demo talking point:

```text
git status resolves through the shim, but policy classifies it as low risk, so real git output and exit code are preserved.
```

Run a high-risk command:

```powershell
git push origin main
```

Expected demo talking point:

```text
The terminal blocks before real git push executes. The Web approvals page shows a pending high-risk command.
```

Reject once:

```text
Open /approvals, click Reject.
```

Expected terminal result:

```text
MICA_APPROVAL_REJECTED
exit code 126
```

Run again and approve:

```powershell
git push origin main
```

```text
Open /approvals, click Approve.
```

Expected result:

```text
The real git executable runs. stdout, stderr, and exit code are preserved.
```

## Part 2: Agent CLI Probe

Run OpenCode probe if OpenCode is installed:

```powershell
.\scripts\probe-opencode.ps1
```

Run Codex probe if Codex CLI is installed:

```powershell
.\scripts\probe-codex.ps1
```

Expected demo talking point:

```text
Mica does not claim governance for an Agent CLI until probe evidence shows that the agent reaches PATH shims.
```

## Part 3: Eval And Summary

Run probe-mode eval:

```powershell
.\scripts\run-eval.ps1 -AgentName codex -AgentKind codex -AgentCommand codex
```

Run approval-mode eval with an automatic reject decision in a throwaway workspace:

```powershell
.\scripts\run-eval.ps1 -AgentName opencode -AgentKind opencode -AgentCommand opencode -EvalMode approval -AutoDecision rejected -ApiBaseUrl http://localhost:8000/api
```

Expected demo talking point:

```text
Eval output summarizes success rate, duration, approval count, rejection count, and risky command count.
```

## Screens To Capture

Recommended screenshots for a README or portfolio:

- `/approvals` with a pending `git push`
- `/commands` showing completed and rejected command records
- `/runs` showing a run summary and trace events
- terminal showing `MICA_APPROVAL_REJECTED`
- probe summary showing `hit_rate=1.0`

## Honest Limits To Say Out Loud

Local PATH shim mode is not a strong sandbox. It does not reliably intercept shell built-ins, direct absolute executable paths, or arbitrary behavior inside binaries. Stronger isolation belongs to Docker, WSL2, or remote worker slices.
