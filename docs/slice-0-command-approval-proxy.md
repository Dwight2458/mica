# Slice 0 Spec: Windows Command Approval Proxy

## Goal

Slice 0 validates Mica's core hypothesis before connecting any real coding agent:

PATH shim plus `mica-proxy` can intercept selected external binary commands, block high-risk operations, create a Web approval, and either execute the real command after approval or fail closed after rejection or timeout.

This slice is the first survival milestone for Mica. It proves policy-gated command execution, not dashboard polish.

## Scope

Implement the smallest Windows-first command approval proxy:

- Python `mica-proxy` module.
- Windows `.cmd` shims for `git`, `npm`, and `terraform`.
- FastAPI approval endpoints backed by SQLite.
- Minimal Next.js approvals page with pending cards and approve/reject actions.
- PowerShell installer script that creates shims, pre-resolves real command paths, and prints a controlled PATH.

Target directory shape:

```text
mica/
  apps/
    api/
    web/
  proxy/
    mica_proxy.py
  shims/
    git.cmd
    npm.cmd
    terraform.cmd
  scripts/
    install-shims.ps1
    probe-path.ps1
```

## Proxy Behavior

`mica-proxy` is invoked by shim files:

```text
python -m mica_proxy --tool <name> -- %*
```

Required behavior:

- Record the full command, args, cwd, timestamp, and tool name.
- Resolve the real executable from a precomputed absolute path or `MICA_ORIGINAL_PATH`.
- Set `MICA_PROXY_BYPASS=1` before executing the real command to prevent shim recursion.
- Low-risk commands execute immediately.
- High-risk commands create a pending approval through the API and block.
- Approved commands execute the real binary.
- Rejected commands print `MICA_APPROVAL_REJECTED` and exit `126`.
- Approval timeout defaults to 300 seconds, prints `MICA_APPROVAL_TIMEOUT`, and exits `124`.
- API unavailable or malformed response fails closed and returns non-zero.
- Stdout, stderr, and exit code from the real command are passed through unchanged.

The current implementation accepts both `MICA_API_BASE_URL` and the earlier Slice 0 name `MICA_API_URL`. `MICA_API_BASE_URL` takes precedence when both are present.

Initial hardcoded risk table:

- `git push`
- `terraform apply`
- `terraform destroy`
- `npm publish`

## API Contract

Slice 0 approvals are command approvals, independent of the existing agent task lifecycle.

Required endpoints:

- `POST /api/approvals`
- `GET /api/approvals`
- `GET /api/approvals/{id}`
- `POST /api/approvals/{id}/decide`

Minimum approval fields:

- `id`
- `status`: `pending`, `approved`, `rejected`
- `tool`
- `argv`
- `command_line`
- `cwd`
- `risk_level`
- `reason`
- `created_at`
- `resolved_at`
- `resolved_by`
- `comment`

The implementation may later merge these records with the existing task approval model, but Slice 0 should stay simple and command-focused.

## UI Contract

The Web UI only needs one approval surface for Slice 0:

- List pending command approvals.
- Show tool, command, cwd, risk, reason, and created time.
- Provide Approve and Reject buttons.
- Refresh after a decision.

The terminal remains the native agent/user interface. Mica is a resident Web control console, not a replacement TUI.

## Install and Probe Scripts

`scripts/install-shims.ps1` should:

- Locate the real `git.exe`, `npm.cmd` or `npm.exe`, and `terraform.exe` before shims are first in PATH.
- Generate shim files in `shims/`.
- Store or print the real executable mapping.
- Print the controlled PATH command that puts `shims/` first while preserving the original PATH in `MICA_ORIGINAL_PATH`.

`scripts/probe-path.ps1` should:

- Show which executable each target command resolves to before and after shim install.
- Detect obvious recursion risk.

## Acceptance Criteria

1. Put `shims/` first in PATH for the current shell.
2. Run `git status`: command is low risk, executes normally, and preserves stdout/stderr/exit code.
3. Run `git push`: command creates a pending approval and blocks in the terminal.
4. Reject in Web UI: terminal prints `MICA_APPROVAL_REJECTED` and exits `126`.
5. Run `git push` again and approve in Web UI: the real `git.exe` runs and output/exit code pass through.
6. SQLite contains the approval record and decision.
7. Use a local bare repository to test `git push`; do not touch a real remote.

## Explicit Non-Goals

- No real AgentAdapter.
- No OpenCode, Codex CLI, Claude Code, or Gemini CLI integration.
- No task/session/trace/SSE/run summary work beyond the minimal approval record.
- No Docker, WSL2, Kubernetes, or remote worker.
- No policy configuration files.
- No broad shim set beyond `git`, `npm`, and `terraform`.
- No claim of reliable PowerShell or cmd built-in interception.

## Engineering Risks

- Shim recursion: always execute the pre-resolved real command path and set `MICA_PROXY_BYPASS=1`.
- False security: if a process calls an absolute executable path or built-in shell command, PATH shim interception is bypassed.
- Output mutation: proxy must preserve stdout, stderr, and exit code or agent runtimes will misbehave.
- Service dependency: approval service downtime must fail closed.
- Agent compatibility: do not connect agents until probe mode confirms commands actually hit shims.
