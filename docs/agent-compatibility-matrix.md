# Agent CLI Compatibility Matrix

Mica only claims command governance for an Agent CLI after probe evidence shows that the agent reaches Mica PATH shims.

| Agent CLI | Probe Script | Tested Tools | Evidence Status | Notes |
| --- | --- | --- | --- | --- |
| OpenCode | `scripts/probe-opencode.ps1` | `git`, `npm`, `terraform` | Real local probe previously observed `hit_rate=1.0`; see [opencode-probe-report.md](opencode-probe-report.md) | OpenCode may run extra internal `git` commands for repository inspection and snapshots. |
| Codex CLI | `scripts/probe-codex.ps1` | `git`, `npm`, `terraform` | Real local probe observed `hit_rate=1.0` on 2026-07-07; Web adapter now available as `codex-cli`; see [codex-probe-report.md](codex-probe-report.md) | Probe uses `codex exec -C <repo> <prompt>`. Web runs use `codex exec --json --cd <repo> --sandbox <mode> --config approval_policy="never" --skip-git-repo-check <prompt>`. On Windows, Mica defaults `<mode>` to `danger-full-access` because `workspace-write` can fail to launch shell commands with `CreateProcessAsUserW failed: 5`; override with `MICA_CODEX_SANDBOX`. External binaries still resolve through Mica shims when called by PATH name. |
| Antigravity CLI | Pending | Pending | Web adapter now available as `antigravity-cli`; real shim-hit probe report pending | Web runs use `agy --print <prompt> --add-dir <repo> --mode accept-edits --print-timeout 10m`. `cwd` alone is not enough because print mode otherwise uses Antigravity's scratch/project workspace. The first adapter records stdout/stderr as text trace because official docs expose a one-shot prompt flow but not a JSONL event stream. Governance claims still require shim/proxy command evidence. |

## Rule

If an agent does not hit the shims during probe mode, Mica can still observe terminal output, but it cannot honestly claim policy-gated command execution for that agent.
