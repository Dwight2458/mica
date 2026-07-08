# Agent CLI Compatibility Matrix

Mica only claims command governance for an Agent CLI after probe evidence shows that the agent reaches Mica PATH shims.

| Agent CLI | Probe Script | Tested Tools | Evidence Status | Notes |
| --- | --- | --- | --- | --- |
| OpenCode | `scripts/probe-opencode.ps1` | `git`, `npm`, `terraform` | Real local probe previously observed `hit_rate=1.0`; see [opencode-probe-report.md](opencode-probe-report.md) | OpenCode may run extra internal `git` commands for repository inspection and snapshots. |
| Codex CLI | `scripts/probe-codex.ps1` | `git`, `npm`, `terraform` | Real local probe observed `hit_rate=1.0` on 2026-07-07; Web adapter now available as `codex-cli`; see [codex-probe-report.md](codex-probe-report.md) | Probe uses `codex exec -C <repo> <prompt>`. Web runs use `codex exec --json --cd <repo> --sandbox workspace-write --config approval_policy="never" --skip-git-repo-check <prompt>`. Codex launched PowerShell commands, and external binaries still resolved through Mica shims. |
| Antigravity CLI | Pending | Pending | Web adapter now available as `antigravity-cli`; real shim-hit probe report pending | Web runs use `agy -p <prompt> --cwd <repo>`. The first adapter records stdout/stderr as text trace because official docs expose a one-shot prompt flow but not a JSONL event stream. Governance claims still require shim/proxy command evidence. |
| Claude Code | `scripts/probe-claude.ps1` | `git`, `npm`, `terraform` | Script tested with fake CLI; real local probe pending | Uses `claude -p <prompt>`. Do not claim governance until a real probe log shows expected shim hits. |
| Gemini CLI | `scripts/probe-gemini.ps1` | `git`, `npm`, `terraform` | Script tested with fake CLI; real local probe pending | Uses `gemini -p <prompt>`. Do not claim governance until a real probe log shows expected shim hits. |

## Rule

If an agent does not hit the shims during probe mode, Mica can still observe terminal output, but it cannot honestly claim policy-gated command execution for that agent.
