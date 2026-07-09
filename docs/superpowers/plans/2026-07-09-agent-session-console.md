# Agent Session Console Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add persistent Agent Sessions so complex tasks can continue across multiple governed agent invocations.

**Architecture:** Introduce `AgentSession` as the long-lived task/conversation object, `SessionMessage` as the human/agent transcript, and keep `RunRecord` as a single CLI invocation with commands, approvals, and trace evidence. Continuing a session creates a new run with transcript context injected into the prompt; one-shot `/runs` remains available.

**Tech Stack:** FastAPI, SQLAlchemy, SQLite, Pydantic, Next.js App Router, React, TypeScript, Tailwind, existing shadcn/Base UI components.

## Global Constraints

- Mica remains an AI Coding Agent Execution Control Plane, not a new agent runtime or a multi-agent collaboration platform.
- Do not copy clowder-ai's multi-agent identity, team, memory, or CVO model.
- Local mode is not a strong sandbox; governance evidence still comes from PATH shim/proxy, command records, approvals, and trace.
- First implementation uses "new CLI invocation per turn with transcript context"; no interactive TTY or daemon resume in this slice.
- Existing `/runs` and `/runs/[id]` must keep working.

---

### Task 1: Session Data Model And API

**Files:**
- Create: `apps/api/app/models/session.py`
- Create: `apps/api/app/schemas/sessions.py`
- Create: `apps/api/app/services/session_service.py`
- Create: `apps/api/app/api/routes/sessions.py`
- Modify: `apps/api/app/models/__init__.py`
- Modify: `apps/api/app/models/enums.py`
- Modify: `apps/api/app/models/run.py`
- Modify: `apps/api/app/schemas/runs.py`
- Modify: `apps/api/app/api/router.py`
- Modify: `apps/api/app/db/session.py`
- Test: `apps/api/tests/test_sessions.py`

**Interfaces:**
- Produces: `SessionService.create(payload: AgentSessionCreate) -> AgentSession`
- Produces: `SessionService.continue_session(session_id: str, payload: SessionContinueRequest, session_factory: sessionmaker | None) -> SessionContinueResult`
- Produces: `GET /api/sessions`, `GET /api/sessions/{id}`, `GET /api/sessions/{id}/messages`, `POST /api/sessions`, `POST /api/sessions/{id}/continue`

- [ ] **Step 1: Write failing tests**

Create `apps/api/tests/test_sessions.py` with tests for creating a session, adding a user message, listing messages, and confirming `RunRecord.session_id` is populated on continue.

- [ ] **Step 2: Add enums**

Add:
```python
class AgentSessionStatus(str, Enum):
    ACTIVE = "active"
    WAITING_USER_INPUT = "waiting_user_input"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class SessionMessageRole(str, Enum):
    USER = "user"
    AGENT = "agent"
    SYSTEM = "system"
```

- [ ] **Step 3: Add models**

Add `AgentSession` with `id`, `title`, `workspace`, `agent_type`, `runner_mode`, `status`, `created_at`, `updated_at`, `last_run_id`, `summary`.
Add `SessionMessage` with `id`, `session_id`, `run_id`, `role`, `content`, `metadata`, `created_at`.
Add nullable `session_id` to `RunRecord`.

- [ ] **Step 4: Add schemas, service, routes**

Expose create/list/detail/messages/continue endpoints. Session creation should persist the first user message and start a run through the existing `AgentRunService`.

- [ ] **Step 5: Verify**

Run: `uv run pytest tests/test_sessions.py -v`
Expected: PASS.

### Task 2: Waiting-For-User State Detection

**Files:**
- Modify: `apps/api/app/runners/agent_adapters.py`
- Modify: `apps/api/app/services/agent_run_service.py`
- Modify: `apps/api/app/services/session_service.py`
- Test: `apps/api/tests/test_sessions.py`
- Test: `apps/api/tests/test_agent_runs.py`

**Interfaces:**
- Produces: `AgentProcessManager` updates a linked session after run exit.
- Produces: heuristic `looks_like_user_input_request(text: str) -> bool`.

- [ ] **Step 1: Write failing test**

Add a test where an agent output containing `Please let me know if you approve this approach` makes the session status `waiting_user_input` when the process exits 0.

- [ ] **Step 2: Implement heuristic**

Recognize lightweight phrases:
```python
"please let me know"
"which approach"
"do you approve"
"if you approve"
"provide more"
"need more information"
"choose one"
```

- [ ] **Step 3: Update process finalization**

When a run linked to a session finishes:
- create agent messages from user-facing output events;
- set session to `waiting_user_input` if the heuristic matches;
- otherwise set it to `completed` for successful runs and `failed` for failed runs;
- keep the run status as the CLI invocation status.

- [ ] **Step 4: Verify**

Run: `uv run pytest tests/test_sessions.py tests/test_agent_runs.py -v`
Expected: PASS.

### Task 3: Frontend Session Console

**Files:**
- Modify: `apps/web/src/lib/api.ts`
- Modify: `apps/web/src/components/app-shell.tsx`
- Create: `apps/web/src/app/sessions/page.tsx`
- Create: `apps/web/src/app/sessions/[id]/page.tsx`
- Test: `apps/api/tests/test_runs_ui_contract.py` or new `apps/api/tests/test_sessions_ui_contract.py`

**Interfaces:**
- Consumes: `GET /api/sessions`, `GET /api/sessions/{id}`, `GET /api/sessions/{id}/messages`, `POST /api/sessions`, `POST /api/sessions/{id}/continue`
- Produces: `/sessions` list/create page and `/sessions/[id]` console page.

- [ ] **Step 1: Add API types**

Add `AgentSession`, `SessionMessage`, `SessionCreateRequest`, and `SessionContinueResponse` types.

- [ ] **Step 2: Add `/sessions` page**

Build a create form with prompt/workspace/agent/mode and a sessions table. Creating a session navigates to `/sessions/{id}`.

- [ ] **Step 3: Add `/sessions/[id]` page**

Build a two-column developer console:
- left: transcript and bottom input;
- right: latest run summary, link to run detail, command/evidence counts.

- [ ] **Step 4: Wire continue**

Submitting a follow-up calls `POST /api/sessions/{id}/continue`, refreshes transcript, and links to the new run.

- [ ] **Step 5: Verify**

Run: `pnpm build:web`
Expected: PASS.

### Task 4: Documentation And Regression

**Files:**
- Modify: `README.md`
- Modify: `docs/project-north-star.md`
- Modify: `docs/architecture.md`

**Interfaces:**
- Produces: documented distinction between Session and Run.

- [ ] **Step 1: Document object model**

Add:
```text
Session = long-lived goal/conversation
Run = one agent CLI invocation
Command = governed external action evidence
```

- [ ] **Step 2: Document MVP limitation**

State that continuation is transcript-injected new process invocation, not true interactive TTY/resume.

- [ ] **Step 3: Verify full suite**

Run:
```powershell
uv run pytest
pnpm build:web
```
Expected: backend tests pass and web build passes.

## Self-Review

- Spec coverage: Covers persistent session, continuation, waiting-user state, UI, and docs.
- Placeholder scan: No TBD/TODO placeholders.
- Type consistency: `AgentSession`, `SessionMessage`, `session_id`, and `waiting_user_input` are used consistently across tasks.

