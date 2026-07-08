# Slice 0: Windows Command Approval Proxy

This file is the canonical short entrypoint for Slice 0 verification. The full engineering spec lives in [slice-0-command-approval-proxy.md](slice-0-command-approval-proxy.md).

## Status

Slice 0 is implemented as a Windows-first PATH shim plus command proxy proof.

Implemented artifacts:

- `proxy/mica_proxy.py`
- `shims/git.cmd`
- `shims/npm.cmd`
- `shims/terraform.cmd`
- `scripts/install-shims.ps1`
- `scripts/probe-path.ps1`
- FastAPI approval endpoints under `/api/approvals`
- SQLite-backed approval records
- Next.js approval console at `/approvals`

## Manual Verification

Start the API and Web console:

```powershell
pnpm dev:api
pnpm dev:web
```

Install or inspect shims:

```powershell
.\scripts\install-shims.ps1
.\scripts\probe-path.ps1
```

Apply the controlled environment in the terminal you want to govern:

```powershell
$env:MICA_ORIGINAL_PATH = $env:PATH
$env:PATH = "C:\Users\24582\Projects\mica\shims;$env:MICA_ORIGINAL_PATH"
$env:MICA_API_BASE_URL = "http://localhost:8000/api"
```

The proxy also accepts the legacy Slice 0 variable `MICA_API_URL`. Prefer `MICA_API_BASE_URL` for new scripts.

Low-risk command:

```powershell
git status
```

Expected result:

- command resolves through `shims/git.cmd`
- `mica-proxy` classifies it as low risk
- real `git.exe` runs from `MICA_ORIGINAL_PATH`
- stdout, stderr, and exit code are preserved
- no approval is created

High-risk command, using only a local bare repository:

```powershell
git push origin main
```

Expected result:

- terminal blocks while waiting for approval
- `/approvals` shows a pending high-risk command
- Reject prints `MICA_APPROVAL_REJECTED` and exits `126`
- Approve runs the real `git.exe`
- SQLite records the approval and decision

Scripted verification:

```powershell
.\scripts\verify-slice0.ps1 -AutoDecision rejected -ApiBaseUrl http://localhost:8000/api
```

The script creates a throwaway local bare repository, checks `git status`, runs `git push origin main`, auto-rejects the pending approval, and expects the proxy to return `126`.

Fail-closed check:

```powershell
# Stop the API, then run a high-risk command in a throwaway repo.
git push origin main
```

Expected result:

- command is not allowed to execute
- proxy returns a non-zero exit code
- terminal output explains that approval could not be completed

Automated timeout and API-unavailable evidence is tracked in [fail-closed-evidence.md](fail-closed-evidence.md).

## Boundary

Local PATH shim mode is not a strong sandbox. It governs external binaries that resolve through PATH. It does not reliably intercept PowerShell or cmd built-ins, direct absolute executable paths, or behavior inside arbitrary binaries.
