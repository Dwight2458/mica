# Mica AgentOps Project North Star

## Definition

Mica AgentOps is an AI Coding Agent Execution Control Plane.

It is the execution governance layer for local or remote coding agents. It is not a new coding agent runtime, and it is not a generic multi-agent team collaboration product.

The ideal execution loop is:

```text
user task
  -> Mica session / task
  -> selected AgentAdapter
  -> spawned or connected Agent CLI / runtime
  -> injected workspace / policy / skills / env
  -> normalized events / approvals / trace
  -> execution report and eval data
```

## Control Plane Responsibilities

Mica owns the governance around execution:

- Routing: choose which agent or runner handles a task.
- Scheduling: start, pause, resume, cancel, and retry runs.
- Policy: detect or enforce high-risk commands, path restrictions, secret access, and approval rules.
- Observability: capture stdout, stderr, tool calls, file changes, approvals, durations, and failures.
- Audit: record who created a task, who approved actions, what ran, and what artifacts were produced.
- Evaluation: measure success rate, duration, approval count, risky operation count, cost, and failure reasons.

Mica may supervise local processes in the MVP, so it has runtime-manager behavior. The product boundary is still execution governance, not agent intelligence.

## Session vs Run

Mica uses a layered object model:

```text
Session = long-lived coding goal, display messages, and native Agent session/thread handle
Run = one Agent CLI invocation inside a Session
Command = governed external action evidence
Approval = human gate for risky actions
Trace/Event = auditable execution record
```

This lets complex tasks continue across multiple Agent CLI invocations without turning Mica into a generic chat or multi-agent team product. The Session Console is an execution-governance interface: it collects user input, records agent questions and answers, and links each turn to run evidence.

Mica must not rebuild Agent state from its own transcript. The transcript is for display and audit. OpenCode Session continuation uses the native server HTTP API and OpenCode session id; Codex continuation uses the Codex thread id. TTY control is a separate observation/takeover layer, not the primary session-resume mechanism.

## Difference From Multi-Agent Team Platforms

Mica should stay narrower than AI team or multi-agent collaboration systems.

| Dimension | Team collaboration platforms | Mica AgentOps |
| --- | --- | --- |
| Primary problem | How agents collaborate as a team | How agent execution is governed |
| Core object | Agent team, mission, memory | Session, run, command, approval, trace, eval |
| Safety model | SOP, team rules, collaboration discipline | Policy enforcement, sandbox, command proxy, approval |
| UI emphasis | Team messages, routing, hub, collaboration | Execution chain, risk actions, evidence, postmortem |
| Resume value | Multi-agent platform | AgentOps / DevOps execution governance platform |

Mica should not drift toward agent personalities, team culture, cross-model debate, shared memory, or CVO-style workflows unless the product is intentionally re-scoped.

## Agent Runtime Integration Strategy

The first real integration path should be local Agent CLI supervision, not direct LLM API calls.

### L0 Process Adapter

The base layer spawns a child process:

```text
subprocess spawn
cwd = workspace
env = controlled env
stdin = optional
stdout / stderr = streaming
exit_code = recorded
cancel = kill process tree
timeout = enforced
```

This should support OpenCode, Codex CLI, Antigravity CLI, and custom shell agents.

### L1 Structured Stream Adapter

When a CLI supports JSONL, NDJSON, stream-json, or event streams, Mica should parse those events into normalized internal events:

- assistant_message
- plan_created
- plan_updated
- tool_call_started
- tool_call_finished
- command_started
- command_output
- command_finished
- file_changed
- approval_required
- run_completed
- run_failed

The purpose of normalization is Trace, Approval, Audit, Metrics, Eval, and Replay, not just chat display.

### L2 RPC / HTTP Adapter

If an agent exposes a daemon, socket, HTTP API, or WebSocket API, Mica should connect to it through the same adapter semantics:

```python
class AgentAdapter:
    async def start_run(self, request: AgentRunRequest) -> AgentRunHandle:
        ...

    async def stream_events(self, run_id: str) -> AsyncIterator[AgentEvent]:
        ...

    async def send_input(self, run_id: str, message: str) -> None:
        ...

    async def approve(self, run_id: str, approval_id: str) -> None:
        ...

    async def reject(self, run_id: str, approval_id: str) -> None:
        ...

    async def cancel(self, run_id: str) -> None:
        ...
```

### L3 MCP Tool Provider

MCP is best treated as a tool and resource provider path, not the default agent runtime connection path:

```text
Mica schedules Agent
Agent uses Tools
Tools may come from MCP servers
```

## Policy-Gated Agent Execution

Mica's defensible differentiator is policy-gated command execution:

> Mica should not merely show what an agent did. It should stop key external commands before they happen when enforcement is available, explain the risk, wait for human approval, record the evidence, and turn the run into eval data.

Soft control is useful early:

- Parse agent output.
- Detect planned high-risk operations.
- Create approval records.
- Pause when the agent exposes the action before execution.

Soft control is not enough if the CLI executes commands internally before Mica sees them.

Hard control is the long-term value:

- Sandbox provider.
- Command proxy.
- PATH shim.
- Restricted shell.
- Tool-call proxy.
- Secret guard.
- Network policy.
- File-system policy.

Target policy examples:

- `rm -rf` enters approval or is denied.
- `.env`, secret, token, and key file access is approved or denied.
- `git push`, `terraform apply`, and `kubectl delete` enter approval.
- Workspace escape is denied.
- Dangerous Docker or system cleanup commands require approval.

## Honest Local-Mode Boundaries

The MVP command proxy can only govern commands that flow through its interception path.

- PATH shims can intercept external binaries such as `git`, `npm`, `curl`, `terraform`, and `kubectl`.
- PATH shims do not reliably intercept PowerShell or cmd built-ins such as `Remove-Item`, `del`, `rmdir`, or `cd`.
- `powershell -Command` and `cmd /c` strings can be scanned as best-effort policy signals, but this is not a reliable enforcement boundary.
- Local mode is not a strong security sandbox. It provides policy checks, human approval, and audit evidence, but cannot stop malicious absolute-path execution, direct library calls, or hostile child processes.
- Strong isolation belongs to Docker, WSL2, or remote worker layers.

## Current Truth

The current implementation is focused on Slice 0. It provides command approvals, a Python proxy, Windows shims, and a minimal approval console.

Slice 0 still must be validated manually with local command execution:

- `git status` should pass through normally.
- `git push` against a local bare repository should block on Web approval.
- Reject should return exit code `126`.
- Approve should execute the real `git.exe` with stdout, stderr, and exit code preserved.
- API downtime or approval timeout should fail closed.

Only after this command proxy path is proven should Mica claim progress on real Agent CLI governance.
