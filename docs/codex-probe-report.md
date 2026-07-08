# Codex CLI Probe Report

## Purpose

This report tracks whether Codex CLI reaches Mica PATH shims for external binary commands on Windows.

The probe is observational. It does not block commands and does not create approvals. Its only job is to prove whether Mica can see commands before claiming governance for Codex CLI.

## Probe Command

```powershell
.\scripts\probe-codex.ps1
```

The script uses:

```text
codex exec -C <repo> <prompt>
```

The prompt asks Codex to run:

```text
git status
npm -v
terraform --version
```

## Expected Evidence

The script writes:

```text
.mica/codex-probe.jsonl
```

It then prints a `mica_probe` summary with:

- total shim hits
- per-tool hit state
- hit rate
- commands observed through Mica shims

## Current Automated Verification

Automated tests use a fake `codex.cmd` and fake real tools. This verifies that:

- `probe-codex.ps1` resolves Codex before PATH mutation
- controlled PATH injection reaches Mica shims
- probe mode writes JSONL events
- stdout and exit code pass through
- `mica_probe` reports `hit_rate=1.0` for `git`, `npm`, and `terraform`

## Real Probe Status

Real local Codex CLI probing was run on 2026-07-07 from `C:\Users\24582\Projects\mica` with:

```powershell
.\scripts\probe-codex.ps1
```

Observed Codex CLI:

```text
OpenAI Codex v0.142.5
```

Observed command execution path:

```text
Codex invoked PowerShell commands:
- powershell.exe -Command 'npm -v'
- powershell.exe -Command 'git status'
- powershell.exe -Command 'terraform --version'
```

Even though Codex launched commands through PowerShell, those external binaries still resolved through PATH and hit Mica shims.

Hit matrix:

```json
{
  "total_hits": 3,
  "hit_tools": 3,
  "hit_rate": 1.0,
  "tools": {
    "git": {
      "hit": true,
      "hit_count": 1,
      "commands": ["git status"]
    },
    "npm": {
      "hit": true,
      "hit_count": 1,
      "commands": ["npm -v"]
    },
    "terraform": {
      "hit": true,
      "hit_count": 1,
      "commands": ["terraform --version"]
    }
  }
}
```

Real executables resolved by `mica-proxy`:

- `git`: `C:\Program Files\Git\cmd\git.EXE`
- `npm`: `C:\Program Files\nodejs\npm.CMD`
- `terraform`: `C:\Users\24582\AppData\Local\Microsoft\WinGet\Packages\Hashicorp.Terraform_Microsoft.Winget.Source_8wekyb3d8bbwe\terraform.EXE`

## Interpretation

- `hit_rate=1.0`: Codex CLI commands reached Mica shims for the tested tools.
- Partial hit rate: inspect which tools bypassed PATH.
- Zero hit rate: do not claim Mica can govern Codex CLI until the execution path is understood.

Local PATH shim mode remains non-sandboxed. It only observes external binaries resolved through PATH.
