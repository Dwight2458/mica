# Runs Detail Layout Design

Date: 2026-07-09

## Context

The current Runs page mixes run creation, run history, evidence, realtime logs, and trace events into one surface. This makes the page technically complete but hard to demo: users must scan unrelated panels to understand what happened in a run.

Mica's product boundary is an AgentOps execution governance layer. The UI should therefore make the execution story clear first, then expose audit evidence and debug detail when needed.

## Decision

Use a split information architecture:

- `/runs`: a run launch and history page.
- `/runs/[id]`: a dedicated run detail page.

This is the chosen direction over a single master-detail page or a drawer-based table. It gives the product enough room to show trace, evidence, logs, approvals, and summaries without turning the list page into a dense control cockpit.

## Product Principles

1. The list page answers: "Which runs exist, and what should I open next?"
2. The detail page answers: "What did this agent do, what was governed, and what evidence supports that?"
3. Runtime internals are not the main narrative. They should be available for debugging but hidden by default.
4. User-facing logs should prioritize agent stdout, assistant text, and tool output over protocol chatter.
5. Evidence should mean governance evidence: commands, approvals, policy decisions, file changes, and failures.

## `/runs` Page

The `/runs` page should contain:

- Start Agent Run panel.
- Recent Runs table.
- Compact run status and health indicators.
- Actions: View, Cancel, Retry when supported.

Table columns:

- Status
- Agent
- Prompt
- Workspace
- Duration
- Governed commands
- Created time
- Actions

The page should not render realtime logs, trace events, or full evidence tables. Selecting a run should navigate to `/runs/[id]`.

## `/runs/[id]` Page

The detail page should contain a persistent run header:

- Status badge
- Agent name
- Prompt
- Workspace path
- Duration
- Governed command count
- Approval count
- Final summary when available

Below the header, use tabs:

- Overview
- Evidence
- Logs
- Trace

### Overview Tab

Purpose: explain the run outcome quickly.

Content:

- Natural-language prompt.
- Final run summary.
- Key metrics: duration, governed commands, approvals, file changes, exit status.
- Failure reason and next action when failed.
- Pending approval callout when waiting.

### Evidence Tab

Purpose: show governance evidence.

Content:

- Command records excluding `runtime_internal` by default.
- Approval records.
- Policy decisions.
- File changes.
- Exit code and stderr for failed commands.

Controls:

- Toggle to show runtime/internal commands.
- Filter by command source: governed, agent_tool, runtime_internal.
- Filter by status: completed, failed, rejected, pending.

### Logs Tab

Purpose: show what a human expects to see from the agent.

Content:

- Agent stdout/stderr.
- Assistant text events.
- Tool output.

Behavior:

- Realtime append using the existing SSE stream.
- Monospace log panel.
- Long lines wrap.
- Empty state when no logs exist.
- No raw JSON protocol events by default.

### Trace Tab

Purpose: provide auditable event replay.

Content:

- High-value normalized events by default.
- Expandable payload per event.
- Command duration and exit code on command completion events.
- Approval required/approved/rejected events.
- Task/run completed or failed events.

Debug behavior:

- Hide `runtime_internal` and low-signal protocol events by default.
- Add a Debug toggle to reveal internal events and raw payloads.

## Component Direction

Extract the current large Runs client component into focused components:

- `StartAgentRunPanel`
- `RunsTable`
- `RunHeader`
- `RunOverview`
- `RunEvidenceTable`
- `RunLogsPanel`
- `RunTraceTimeline`
- `RunApprovalCallout`

The first implementation can keep data fetching local to pages if that is faster, but the UI should be structured so hooks can later be extracted:

- `useRuns`
- `useRunDetail`
- `useRunEvents`
- `useRunCommands`

## Data/API Impact

No backend rewrite is required.

Use existing endpoints:

- `GET /api/runs`
- `GET /api/runs/{id}`
- `GET /api/runs/{id}/summary`
- `GET /api/events?run_id=...`
- `GET /api/events/stream?run_id=...`
- `GET /api/commands?run_id=...`
- `GET /api/approvals?run_id=...` if available, otherwise reuse current approval list and filter client-side as a temporary step.
- `POST /api/agent-runs`
- `POST /api/agent-runs/{id}/cancel`

If an endpoint is missing for run-scoped approvals, add the narrowest route needed rather than reshaping the whole backend.

## UX Notes

- Keep the interface dense and work-focused, like a developer operations tool.
- Do not use a marketing-style hero layout.
- Avoid nested cards.
- Use status colors consistently:
  - created: gray
  - running: blue
  - waiting_approval: yellow
  - completed: green
  - failed: red
  - cancelled: gray
- Keep debug/internal data opt-in.

## Acceptance Criteria

1. `/runs` shows only run launch and run history.
2. Clicking a run opens `/runs/[id]`.
3. `/runs/[id]` shows Overview, Evidence, Logs, and Trace tabs.
4. Logs stream through SSE and append while the run is active.
5. Runtime/internal commands are hidden by default and visible behind a toggle.
6. Evidence tab highlights governed commands and approvals.
7. Trace tab supports payload expansion and debug visibility.
8. Empty states are shown for logs, evidence, and trace.
9. Existing mock-agent, OpenCode, Codex CLI, and Antigravity CLI runs remain usable.
10. `pnpm build:web` and backend tests pass after implementation.

## Non-goals

- No redesign of the backend run/event schema.
- No new agent adapter in this slice.
- No dashboard redesign.
- No eval suite UI.
- No strong sandbox UI beyond current evidence surfaces.

## Open Questions

1. Should Advanced Docker Command remain on `/runs` as a secondary panel, or move to a future dedicated page?
2. Should Retry copy the original prompt and workspace into the form, or immediately create a new run?
3. Should Trace default to chronological timeline or grouped-by-step view?

