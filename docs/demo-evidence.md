# Demo Evidence

This file records a real local Slice 0 dogfood run from this workspace. It is evidence for the Windows PATH shim plus `mica-proxy` approval loop, not a claim of strong sandboxing.

## Run Metadata

- Date: 2026-07-07
- Workspace: `C:\Users\24582\Projects\mica`
- API: FastAPI started locally on `http://127.0.0.1:8765`
- Database: temporary SQLite database under `%TEMP%\mica-demo-evidence-runtime`
- Verification script: `scripts\verify-slice0.ps1`
- Decision mode: `-AutoDecision rejected`

Command:

```powershell
.\scripts\verify-slice0.ps1 -AutoDecision rejected -ApiBaseUrl http://127.0.0.1:8765/api
```

## Terminal Evidence

The script created a throwaway local bare Git repository, ran a low-risk command, then ran a high-risk command.

Observed stdout:

```text
Initialized empty Git repository in C:/Users/24582/AppData/Local/Temp/mica-slice0-verify/remote.git/
[main (root-commit) e363e2b] init
 1 file changed, 1 insertion(+)
 create mode 100644 README.md
Checking low-risk command: git status
On branch main
Your branch is based on 'origin/main', but the upstream is gone.
  (use "git branch --unset-upstream" to fixup)

nothing to commit, working tree clean
Checking high-risk command: git push origin main
Slice 0 verification passed
```

Observed stderr:

```text
Cloning into 'work'...
warning: You appear to have cloned an empty repository.
done.
warning: in the working copy of 'README.md', CRLF will be replaced by LF the next time Git touches it
MICA_APPROVAL_REJECTED
```

Interpretation:

- `git status` passed through to the real Git executable and exited `0`.
- `git push origin main` created a high-risk approval.
- The auto decision rejected the approval.
- The proxy returned `MICA_APPROVAL_REJECTED` and exit code `126`.
- The verification script treated that as the expected rejected-path success condition.

## SQLite Evidence

The temporary SQLite database recorded:

```json
{
  "command_approvals": 1,
  "command_records": 2,
  "approvals": [
    {
      "tool": "git",
      "command_line": "git push origin main",
      "risk_level": "high",
      "status": "REJECTED",
      "resolved_by": "mica-slice0-verify",
      "comment": "auto rejected from verify-slice0"
    }
  ],
  "commands": [
    {
      "tool": "git",
      "command_line": "git status",
      "risk_level": "low",
      "requires_approval": false,
      "status": "COMPLETED",
      "exit_code": 0
    },
    {
      "tool": "git",
      "command_line": "git push origin main",
      "risk_level": "high",
      "requires_approval": true,
      "status": "REJECTED",
      "exit_code": 126
    }
  ]
}
```

## Boundary

This dogfood run proves policy-gated execution for external binaries that resolve through PATH shims. It does not prove that Local mode is a strong sandbox. PowerShell/cmd built-ins, absolute executable paths, direct library calls, and arbitrary behavior inside binaries remain outside this enforcement layer.
