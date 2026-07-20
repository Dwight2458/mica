# Session Native Conversation Mirror Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mirror OpenCode's user-visible native conversation in Mica without exposing reasoning or compiling untrusted MDX.

**Architecture:** Normalize OpenCode assistant `text` and `tool` parts into idempotent `SessionMessage` rows keyed through metadata by native message/part IDs. Consume both `/global/event` updates and periodic message snapshots, then render text as safe Markdown/GFM while keeping tool activity collapsed and raw payloads in Run Evidence.

**Tech Stack:** FastAPI, SQLAlchemy, OpenCode HTTP/SSE, Next.js, React, `react-markdown`, `remark-gfm`.

## Global Constraints

- Do not persist or display OpenCode reasoning parts in Conversation.
- Do not compile Agent output as MDX or execute embedded HTML/JSX.
- Keep existing Run Evidence as the raw audit surface.
- Avoid database migrations; use `SessionMessage.message_metadata` for native identifiers.

---

### Task 1: Native part persistence

**Files:** `apps/api/app/services/session_service.py`, `apps/api/tests/test_sessions.py`

- [ ] Add failing tests proving an OpenCode text part preceding a question is immediately visible in Session messages.
- [ ] Add a failing test proving repeated snapshots update one message rather than duplicating it.
- [ ] Persist `text` and `tool` parts with native IDs and update them idempotently; ignore reasoning.
- [ ] Prevent aggregate `run_output` from duplicating native mirrored messages.
- [ ] Run focused and full backend tests.

### Task 2: SSE normalization

**Files:** `apps/api/app/services/session_service.py`, `apps/api/tests/test_sessions.py`

- [ ] Add a failing fake SSE test for `message.part.updated` and `question.asked`.
- [ ] Normalize these events through the same persistence path used by message snapshots.
- [ ] Preserve polling as reconnect/fallback recovery.

### Task 3: Conversation renderer

**Files:** `apps/web/src/components/session-message.tsx`, `apps/web/src/app/sessions/[id]/page.tsx`, `apps/web/src/lib/api.ts`

- [ ] Add frontend contract tests for Markdown/GFM and collapsed tool rendering.
- [ ] Install `react-markdown` and `remark-gfm`.
- [ ] Render headings, lists, tables, links, inline code and fenced code safely; keep tool details collapsed.
- [ ] Refresh Session data on `command_output` SSE events.
- [ ] Run frontend tests, lint and production build.

### Task 4: Recovery and acceptance

- [ ] Backfill missing OpenCode text parts for the affected Session from its native message history.
- [ ] Verify the Prisma Schema appears before “数据模型设计如何？”.
- [ ] Verify no reasoning appears in Conversation and Run Evidence remains available.
- [ ] Run full backend/frontend regression and browser acceptance.
