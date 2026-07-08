# Mica AgentOps Project Guardrails

These instructions are durable project guidance for agents working in this repository.

## Product North Star

Mica AgentOps is an AI Coding Agent Execution Control Plane. It is an execution governance layer for local or remote coding agents, not a new coding agent runtime and not a multi-agent team product.

The core job of Mica is to make coding-agent execution controllable, observable, approvable, auditable, and evaluable.

## Stay Inside This Boundary

- Prefer Agent CLI adapters before direct LLM API integrations. Codex CLI, OpenCode, Claude Code, Gemini CLI, and custom shell agents should be treated as runtimes that Mica supervises.
- Do not turn Mica into a generic multi-agent collaboration layer. Avoid features centered on agent personalities, team culture, shared memory, cross-model debate, or CVO-style workflows unless the user explicitly re-scopes the product.
- Treat MCP as a tool and resource provider path, not the default protocol for connecting agent runtimes.
- Keep UI and data modeling focused on runs, commands, approvals, traces, policies, summaries, metrics, and evals.

## Core Differentiator

Mica should differentiate through policy-gated command execution:

- Route tasks to an AgentAdapter.
- Spawn or connect to the selected agent runtime.
- Inject workspace, policy, skills, and controlled environment.
- Normalize raw agent output into trace events.
- Gate external binary commands before execution through PATH shims and command proxy when enforcement is available.
- Record evidence for approvals, command output, file changes, failures, summaries, and eval metrics.

If Mica only reads stdout after a CLI has already executed dangerous work, it is observation, not governance. The roadmap should move toward sandbox, command proxy, PATH shim, restricted shell, secret guard, network policy, and file-system policy.

## Honest Local-Mode Boundaries

- MVP governance covers external binary commands reached through PATH shims, such as git, npm, terraform, kubectl, curl, and similar tools.
- Do not claim reliable interception of PowerShell or cmd built-ins such as Remove-Item, del, rmdir, or cd. They do not resolve through PATH.
- Scanning `powershell -Command` or `cmd /c` strings is best-effort detection only, not a reliable security boundary.
- Local mode is not a strong sandbox. It provides policy checks, approvals, and audit evidence, but cannot stop malicious absolute-path execution, direct library calls, or hostile child processes.
- Strong isolation belongs to later Docker, WSL2, or remote worker layers.

## Adapter Direction

Use a layered adapter model:

- L0 Process Adapter: spawn child process, controlled cwd/env, streaming stdout/stderr, exit code, timeout, cancellation.
- L1 Structured Stream Adapter: parse JSONL, NDJSON, event streams, and tool-call output into normalized Mica events.
- L2 RPC or HTTP Adapter: connect to daemon, socket, HTTP, or WebSocket APIs when the agent provides them.
- L3 MCP Tool Provider: expose tools and resources to agents, separate from agent runtime connection.

The internal target interface is AgentAdapter with start_run, stream_events, send_input, approve, reject, and cancel semantics.

## Near-Term Priorities

After the current MVP, prioritize:

1. Slice 0: Windows Command Approval Proxy with PATH shims, before connecting any real agent.
2. Slice 1: Probe real Agent CLIs, starting with OpenCode, to verify shim hit rate before trusting governance claims.
3. Slice 2: Productize policy, command records, trace, SSE, summaries, and run models.
4. Slice 3: Cross-agent evals and stronger isolation through Docker, WSL2, or remote workers.
