# OpenCode Probe Report

## Purpose

This report tracks whether OpenCode reaches Mica PATH shims for external binary commands on Windows.

Probe mode is observational. It records shim hits, preserves command behavior, and does not create approvals or block execution.

## Probe Command

```powershell
.\scripts\probe-opencode.ps1
```

The script runs OpenCode with:

```text
opencode run --auto <prompt>
```

The prompt asks OpenCode to run:

```text
git status
npm -v
terraform --version
```

## Expected Evidence

The script writes:

```text
.mica/opencode-probe.jsonl
```

It then prints a `mica_probe` summary with:

- total shim hits
- per-tool hit state
- hit rate
- observed commands
- whether a command would require approval under the active policy

## Current Automated Verification

Automated tests cover the shared probe mechanism and fake CLI behavior:

- shims invoke `mica-proxy`
- probe mode records JSONL events
- low-risk commands still execute
- stdout, stderr, and exit code pass through
- probe summaries report hit state for expected tools

## Real Probe Status

Real local OpenCode probing was previously run from this repository on Windows and observed `hit_rate=1.0` for the expected tools:

```json
{
  "expected_tools": ["git", "npm", "terraform"],
  "hit_rate": 1.0,
  "interpretation": "OpenCode reached Mica PATH shims for the tested tools."
}
```

OpenCode may invoke additional `git` commands internally for repository detection and snapshots. A total hit count greater than three is expected and does not indicate a failure. The key Slice 1 evidence is the per-tool hit matrix.

## Interpretation

- `hit_rate=1.0`: Mica can proceed to approval-mode testing for the observed command paths.
- Partial hit rate: inspect which tools bypassed PATH and whether the agent used absolute paths, built-ins, or internal libraries.
- Zero hit rate: do not claim command governance for OpenCode until the execution path is understood.

Local PATH shim mode remains non-sandboxed. It only governs external binaries resolved through PATH.
