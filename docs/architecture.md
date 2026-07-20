# Mica AgentOps Architecture

## Positioning

Mica is an AI Coding Agent Execution Control Plane. It governs command execution around existing local or remote Agent CLIs; it does not reimplement an agent and does not provide a multi-agent team collaboration layer.

The current implementation has Slice 0 and Slice 1 working, and is productizing Slice 2 with command policies, command records, run records, and controlled OpenCode approval mode.

## Slice 0 Runtime

```text
terminal or agent CLI
  -> PATH shim, for example git.cmd
  -> python -m mica_proxy --tool git -- <args>
  -> risk policy
  -> low risk: execute real git.exe
  -> high risk: create command approval
  -> Web approve/reject
  -> approved: execute real command
  -> rejected: exit 126
  -> timeout: exit 124
```

The terminal or native Agent TUI remains the execution surface. Mica is a resident Web control console.

## Components

- `proxy/mica_proxy.py`: command proxy invoked by shims.
- `shims/*.cmd`: Windows PATH shims for selected tools.
- `scripts/install-shims.ps1`: resolves real executables and generates shims.
- `scripts/probe-path.ps1`: shows command resolution before and after shims.
- `apps/api`: FastAPI approval API with SQLAlchemy and SQLite.
- `apps/web`: Next.js approval, run, and command audit console.

## Command Approval Data Model

Command approval records are stored in `command_approvals`.

Fields:

- `id`
- `tool`
- `argv`
- `command_line`
- `cwd`
- `risk_level`
- `reason`
- `status`
- `created_at`
- `resolved_at`
- `resolved_by`
- `comment`

These records are independent of the older task/step approval model. The current product path is command-first rather than task-first.

## Command Record Data Model

Command records are stored in `command_records`.

Fields:

- `id`
- `run_id`
- `tool`
- `argv`
- `command_line`
- `cwd`
- `risk_level`
- `requires_approval`
- `approval_id`
- `status`
- `exit_code`
- `duration_ms`
- `started_at`
- `finished_at`

Statuses:

- `started`
- `waiting_approval`
- `completed`
- `failed`
- `rejected`
- `timeout`

The proxy writes command records on a best-effort basis. It does not capture stdout or stderr yet because stdout/stderr must continue to stream directly to the Agent CLI.

## Run Record Data Model

Run records are stored in `runs`.

Fields:

- `id`
- `session_id`
- `source`
- `cwd`
- `status`
- `started_at`
- `finished_at`

Statuses:

- `started`
- `completed`
- `failed`

Controlled launchers such as `scripts/run-controlled-opencode.ps1` create a run before spawning the Agent CLI, set `MICA_RUN_ID`, and finish the run after the child process exits. Command records include `run_id` when the environment variable is present.

Run summary is computed from linked command records. It includes total commands, successful commands, failed commands, approvals, rejected commands, risky commands, total command duration, and a small failure summary for the first failed, rejected, or timed-out command.

## Agent Session Data Model

Agent sessions are stored in `agent_sessions`.

Fields:

- `id`
- `title`
- `workspace`
- `agent_type`
- `runner_mode`
- `status`
- `created_at`
- `updated_at`
- `last_run_id`
- `summary`

Session messages are stored in `session_messages`.

Fields:

- `id`
- `session_id`
- `run_id`
- `role`
- `content`
- `message_metadata`
- `created_at`

The Session is the persistent goal, display message stream, and native Agent session/thread handle. The Run is still one Agent CLI invocation. This distinction lets Mica support multi-turn tasks while preserving its AgentOps boundary: each turn remains linked to run, command, approval, and trace evidence.

Mica must not reconstruct Agent state from its own transcript. OpenCode Session turns use the OpenCode server-first HTTP API: Mica starts or reuses `opencode serve`, creates a native OpenCode session with `POST /session`, and sends each turn with the OpenCode session API. Codex has two supported Session transports: the stable default path uses the captured Codex thread id through `codex exec resume`, and the opt-in native path uses `codex app-server` over stdio JSON-RPC. In app-server mode Mica calls `thread/start` or `thread/resume`, sends a turn with `turn/start`, stores the native Codex thread id, and writes streamed app-server events into Mica trace evidence.

Codex app-server improves native thread continuity, but it is not the same as attaching to an old terminal process. Agent conversation/thread state is native; transient shell process state is not guaranteed to resume.

## Event Record Data Model

Event records are stored in `events`.

Fields:

- `id`
- `run_id`
- `command_id`
- `approval_id`
- `event_type`
- `message`
- `payload`
- `created_at`

Current event types:

- `run_created`
- `command_started`
- `command_finished`
- `approval_required`
- `approval_approved`
- `approval_rejected`
- `run_completed`
- `run_failed`

Events are written by the service layer in the same transaction as the state change that produced them. The `/runs` page uses these events as the first trace view and subscribes to the SSE stream for updates.

## API

- `POST /api/approvals`: create a pending command approval.
- `GET /api/approvals`: list approvals, optionally filtered by `status`.
- `GET /api/approvals/{id}`: read one approval.
- `POST /api/approvals/{id}/decide`: approve or reject a pending command.
- `POST /api/commands`: create a command record.
- `GET /api/commands`: list command records.
- `GET /api/commands/{id}`: read one command record.
- `PATCH /api/commands/{id}/finish`: finish a command record with status, exit code, and duration.
- `POST /api/runs`: create a run record.
- `GET /api/runs`: list run records.
- `GET /api/runs/{id}`: read one run record.
- `PATCH /api/runs/{id}/finish`: finish a run based on linked command outcomes.
- `GET /api/runs/{id}/summary`: compute a run summary and failure summary.
- `POST /api/sessions`: create a persistent agent session and start its first run.
- `GET /api/sessions`: list agent sessions.
- `GET /api/sessions/{id}`: read one agent session.
- `GET /api/sessions/{id}/messages`: list display messages captured from user turns and Agent output.
- `POST /api/sessions/{id}/continue`: append a user message and start the next governed run.
- `GET /api/events`: list trace events, optionally filtered by `run_id`.
- `GET /api/events/stream`: stream trace events with SSE, optionally filtered by `run_id`.

Only `approved` and `rejected` are valid decisions.

## Risk Policy

Mica proxy loads command policy from JSON. By default it reads `policies/command-policy.json`; a run can override that with `MICA_POLICY_FILE`.

Each rule contains:

- `id`: stable rule identifier
- `tool`: external binary name, such as `git` or `kubectl`
- `argv_prefix`: argv prefix that must match, such as `["push"]`
- `action`: currently `require_approval`
- `risk_level`: currently informational for the approval card
- `reason`: human-readable explanation recorded with the approval

Default high-risk rules currently cover:

- `git push`
- `terraform apply`
- `terraform destroy`
- `npm publish`
- `kubectl delete`

Low-risk commands pass through immediately. Custom policy only has effect when the command reaches a Mica shim.

## Proxy Guarantees

The proxy must:

- Execute the pre-resolved real executable path.
- Set `MICA_PROXY_BYPASS=1` before executing the real command.
- Preserve stdout, stderr, and exit code.
- Return `126` for rejected approvals.
- Return `124` for approval timeout.
- Fail closed if the API is unavailable or returns malformed data.

## Local-Mode Boundaries

PATH shims only govern external binaries that resolve through PATH. They do not reliably intercept PowerShell or cmd built-ins such as `Remove-Item`, `del`, `rmdir`, or `cd`.

Local mode is not a strong sandbox. Absolute paths, direct library calls, and hostile child processes can bypass this interception layer. Docker, WSL2, or remote workers are the future strong-isolation boundary.

## Future Adapter Path

AgentAdapter work must come after probe mode proves that a real Agent CLI hits the shims. The supported adapter track is OpenCode, Codex CLI, Antigravity CLI, and custom command runners.

MCP remains a tool/resource provider path, not the default protocol for connecting Agent runtimes.

## Slice 1 Probe Mode

Probe mode is enabled with `MICA_PROXY_MODE=probe`. In this mode, shims still invoke `mica-proxy`, but high-risk commands are not blocked and no approval records are created. Instead, the proxy writes JSONL hit events to `MICA_PROBE_LOG` and executes the real command.

`mica_probe` summarizes those JSONL events into a per-tool hit matrix. `scripts/probe-opencode.ps1` applies this to OpenCode using `opencode run --auto` and fixed commands for `git`, `npm`, and `terraform`.

Probe totals are intentionally command-observability counts, not prompt-command counts. A real Agent CLI can run extra external commands for setup, repository scanning, or snapshots; the Slice 1 decision point is whether the expected tools are observed through Mica's shims.

## Controlled OpenCode Approval Mode

`scripts/run-controlled-opencode.ps1` is the first approval-mode Agent CLI entrypoint. It runs `opencode run --auto` with:

- `shims/` prepended to PATH
- the original PATH preserved in `MICA_ORIGINAL_PATH`
- `MICA_PROXY_MODE` cleared so high-risk commands create approvals
- `MICA_API_BASE_URL` pointed at the local API
- `MICA_RUN_ID` set after the script creates a run record

This keeps OpenCode's native CLI behavior intact while Mica governs external binary commands that traverse PATH. It does not make Local mode a hard sandbox; absolute-path execution or direct library calls remain outside this control layer.
