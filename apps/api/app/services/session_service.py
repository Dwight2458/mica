from __future__ import annotations

import os
from dataclasses import dataclass
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models.approval import utcnow
from app.models.enums import AgentSessionStatus, EventType, RunStatus, SessionMessageRole
from app.models.event import EventRecord
from app.models.run import RunRecord
from app.models.session import AgentSession, SessionMessage
from app.schemas.agent_runs import AgentRunCreate
from app.schemas.events import EventCreate
from app.schemas.runs import RunRecordCreate
from app.schemas.sessions import AgentSessionCreate, SessionContinueRequest
from app.services.event_service import EventService
from app.services.run_service import RunService


MAX_SESSION_TRANSCRIPT_CHARS = 12_000
MAX_SESSION_MESSAGE_CHARS = 4_000


@dataclass(frozen=True)
class SessionContinueResult:
    session: AgentSession
    run: RunRecord
    message: SessionMessage
    planned_command: list[str]


class SessionService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, payload: AgentSessionCreate, session_factory: sessionmaker | None = None) -> SessionContinueResult:
        title = payload.title or _title_from_prompt(payload.prompt)
        record = AgentSession(
            title=title,
            workspace=payload.workspace,
            agent_type=payload.agent_type,
            runner_mode=payload.runner_mode,
            status=AgentSessionStatus.ACTIVE,
            updated_at=utcnow(),
        )
        self.session.add(record)
        self.session.flush()
        message = self.add_message(record.id, role=SessionMessageRole.USER, content=payload.prompt)
        result = (
            self._start_opencode_http_turn(record, payload.prompt, original_user_message=payload.prompt)
            if payload.agent_type == "opencode"
            else self._start_run(
                record,
                prompt=payload.prompt,
                original_user_message=payload.prompt,
                session_factory=session_factory,
            )
        )
        message.run_id = result.run.id
        self.session.add(message)
        self.session.commit()
        self.session.refresh(record)
        self.session.refresh(message)
        return SessionContinueResult(record, result.run, message, result.planned_command)

    def continue_session(
        self,
        session_id: str,
        payload: SessionContinueRequest,
        session_factory: sessionmaker | None = None,
    ) -> SessionContinueResult | None:
        record = self.get(session_id)
        if record is None:
            return None
        message = self.add_message(
            record.id,
            role=SessionMessageRole.USER,
            content=payload.message,
        )
        result = (
            self._start_opencode_http_turn(record, payload.message, original_user_message=payload.message)
            if record.agent_type == "opencode"
            else self._start_run(
                record,
                prompt=payload.message,
                original_user_message=payload.message,
                session_factory=session_factory,
            )
        )
        message.run_id = result.run.id
        self.session.add(message)
        self.session.commit()
        self.session.refresh(record)
        self.session.refresh(message)
        return SessionContinueResult(record, result.run, message, result.planned_command)

    def list_sessions(self) -> list[AgentSession]:
        statement = select(AgentSession).order_by(AgentSession.updated_at.desc())
        return list(self.session.scalars(statement))

    def get(self, session_id: str) -> AgentSession | None:
        return self.session.get(AgentSession, session_id)

    def list_messages(self, session_id: str) -> list[SessionMessage]:
        statement = select(SessionMessage).where(SessionMessage.session_id == session_id).order_by(SessionMessage.created_at.asc())
        return list(self.session.scalars(statement))

    def add_message(
        self,
        session_id: str,
        *,
        role: SessionMessageRole,
        content: str,
        run_id: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> SessionMessage:
        message = SessionMessage(
            session_id=session_id,
            run_id=run_id,
            role=role,
            content=content,
            message_metadata=metadata or {},
        )
        self.session.add(message)
        self.session.flush()
        return message

    def finalize_run(self, run_id: str, *, status: RunStatus) -> None:
        run = self.session.get(RunRecord, run_id)
        if run is None or run.session_id is None:
            return
        record = self.get(run.session_id)
        if record is None:
            return
        output = self._agent_output_for_run(run_id)
        external_session_id = self._external_session_id_for_run(run_id, record.agent_type)
        if external_session_id and not record.external_session_id:
            record.external_session_id = external_session_id
            record.transport = _transport_for_agent(record.agent_type)
        if output:
            exists = self.session.scalar(
                select(SessionMessage.id).where(
                    SessionMessage.session_id == record.id,
                    SessionMessage.run_id == run_id,
                    SessionMessage.role == SessionMessageRole.AGENT,
                )
            )
            if exists is None:
                self.add_message(
                    record.id,
                    role=SessionMessageRole.AGENT,
                    run_id=run_id,
                    content=output,
                    metadata={"source": "run_output"},
                )
        record.last_run_id = run_id
        record.updated_at = utcnow()
        if status == RunStatus.CANCELLED:
            record.status = AgentSessionStatus.CANCELLED
        elif status == RunStatus.FAILED:
            record.status = AgentSessionStatus.FAILED
        elif _looks_like_user_input_request(output):
            record.status = AgentSessionStatus.WAITING_USER_INPUT
        else:
            record.status = AgentSessionStatus.COMPLETED
        if output:
            record.summary = _summary_from_output(output)
        self.session.add(record)
        self.session.commit()

    def _start_run(
        self,
        record: AgentSession,
        *,
        prompt: str,
        original_user_message: str,
        session_factory: sessionmaker | None,
    ):
        from app.services.agent_run_service import AgentRunService

        record.status = AgentSessionStatus.ACTIVE
        record.updated_at = utcnow()
        self.session.add(record)
        self.session.commit()
        result = AgentRunService(self.session).start(
            AgentRunCreate(
                prompt=prompt,
                workspace=record.workspace,
                agent_type=record.agent_type,
                runner_mode=record.runner_mode,
            ),
            session_factory=session_factory,
            session_id=record.id,
            original_user_message=original_user_message,
            external_session_id=record.external_session_id,
        )
        record.last_run_id = result.run.id
        record.updated_at = utcnow()
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return result

    def _start_opencode_http_turn(
        self,
        record: AgentSession,
        prompt: str,
        *,
        original_user_message: str,
    ):
        from app.runners.agent_adapters import get_adapter
        from app.runners.opencode_server import OpenCodeServerClient, ensure_opencode_backend, extract_text
        from app.services.agent_run_service import AgentRunResult

        executable = ""
        if not os.environ.get("MICA_OPENCODE_SERVER_URL"):
            adapter = get_adapter("opencode")
            executable = adapter.find_executable()
        handle = ensure_opencode_backend(executable, record.workspace)
        client = OpenCodeServerClient(handle.base_url)

        if record.external_session_id is None:
            record.external_session_id = client.create_session(title=record.title)
        record.transport = "http"
        record.backend_url = handle.base_url
        record.status = AgentSessionStatus.ACTIVE
        record.updated_at = utcnow()
        self.session.add(record)
        self.session.commit()

        planned_command = [
            "opencode-http",
            "POST",
            f"{handle.base_url}/session/{record.external_session_id}/message",
        ]
        run = RunService(self.session).create(
            RunRecordCreate(source=record.agent_type, cwd=record.workspace, session_id=record.id)
        )
        EventService(self.session).create(
            EventCreate(
                run_id=run.id,
                event_type=EventType.AGENT_PROMPT,
                message="Agent prompt received.",
                payload={
                    "prompt": prompt,
                    "original_user_message": original_user_message,
                    "session_id": record.id,
                    "external_session_id": record.external_session_id,
                    "agent_type": record.agent_type,
                    "runner_mode": record.runner_mode,
                    "workspace": record.workspace,
                    "transport": "http",
                    "backend_url": handle.base_url,
                },
            )
        )
        EventService(self.session).create(
            EventCreate(
                run_id=run.id,
                event_type=EventType.PLAN_CREATED,
                message="OpenCode HTTP session turn planned.",
                payload={
                    "planned_command": planned_command,
                    "transport": "http",
                    "external_session_id": record.external_session_id,
                },
            )
        )
        self.session.commit()

        try:
            response = client.prompt(record.external_session_id, prompt)
            output = extract_text(response) or "OpenCode HTTP turn completed."
            EventService(self.session).create(
                EventCreate(
                    run_id=run.id,
                    event_type=EventType.COMMAND_OUTPUT,
                    message=output[:500],
                    payload={
                        "stream": "stdout",
                        "text": output,
                        "raw_event": {
                            "type": "text",
                            "message": output,
                            "opencode_response": response,
                            "sessionID": record.external_session_id,
                        },
                    },
                )
            )
            self.session.commit()
            finished_run = RunService(self.session).finish_with_status(run.id, status=RunStatus.COMPLETED)
        except Exception as exc:
            EventService(self.session).create(
                EventCreate(
                    run_id=run.id,
                    event_type=EventType.COMMAND_OUTPUT,
                    message=f"OpenCode HTTP turn failed: {exc}",
                    payload={"stream": "stderr", "text": str(exc)},
                )
            )
            self.session.commit()
            finished_run = RunService(self.session).finish_with_status(run.id, status=RunStatus.FAILED)

        if finished_run is None:
            raise RuntimeError("OpenCode HTTP run could not be finalized.")
        self.finalize_run(finished_run.id, status=finished_run.status)
        self.session.refresh(record)
        return AgentRunResult(
            run=finished_run,
            prompt=prompt,
            agent_type=record.agent_type,
            runner_mode=record.runner_mode,
            planned_command=planned_command,
        )

    def _agent_output_for_run(self, run_id: str) -> str:
        statement = (
            select(EventRecord)
            .where(EventRecord.run_id == run_id, EventRecord.event_type == EventType.COMMAND_OUTPUT)
            .order_by(EventRecord.created_at.asc())
        )
        chunks: list[str] = []
        fallback_chunks: list[str] = []
        for event in self.session.scalars(statement):
            text = _conversation_text_from_event(event)
            if isinstance(text, str) and text.strip():
                chunks.append(text.strip())
                continue
            raw_event = event.payload.get("raw_event")
            fallback_text = event.payload.get("text")
            if not isinstance(raw_event, dict) and isinstance(fallback_text, str) and fallback_text.strip():
                fallback_chunks.append(fallback_text.strip())
        selected_chunks = chunks or fallback_chunks
        return _truncate_text("\n".join(selected_chunks).strip(), MAX_SESSION_MESSAGE_CHARS)

    def _external_session_id_for_run(self, run_id: str, agent_type: str) -> str | None:
        statement = (
            select(EventRecord)
            .where(EventRecord.run_id == run_id, EventRecord.event_type == EventType.COMMAND_OUTPUT)
            .order_by(EventRecord.created_at.asc())
        )
        for event in self.session.scalars(statement):
            raw_event = event.payload.get("raw_event")
            if not isinstance(raw_event, dict):
                continue
            external_id = _external_session_id_from_event(raw_event, agent_type)
            if external_id:
                return external_id
        return None


def _title_from_prompt(prompt: str) -> str:
    normalized = " ".join(prompt.split())
    return normalized[:80] or "Untitled session"


def _summary_from_output(output: str) -> str:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    return lines[-1][:500] if lines else output[:500]


def _conversation_text_from_event(event: EventRecord) -> str | None:
    raw_event = event.payload.get("raw_event")
    if not isinstance(raw_event, dict):
        return None

    event_type = raw_event.get("type")
    if event_type not in {"text", "message", "error"}:
        return None

    message = raw_event.get("message")
    if isinstance(message, str) and message.strip():
        return message

    text = raw_event.get("text")
    if isinstance(text, str) and text.strip():
        return text

    part = raw_event.get("part")
    if isinstance(part, dict):
        part_text = part.get("text")
        if isinstance(part_text, str) and part_text.strip():
            return part_text

    return None


def _external_session_id_from_event(event: dict[str, object], agent_type: str) -> str | None:
    if agent_type == "opencode":
        for key in ("sessionID", "session_id", "sessionId"):
            value = event.get(key)
            if isinstance(value, str) and value:
                return value
        part = event.get("part")
        if isinstance(part, dict):
            for key in ("sessionID", "session_id", "sessionId"):
                value = part.get(key)
                if isinstance(value, str) and value:
                    return value
    if agent_type == "codex-cli":
        for key in ("thread_id", "threadId", "session_id", "session_id"):
            value = event.get(key)
            if isinstance(value, str) and value:
                return value
        item = event.get("item")
        if isinstance(item, dict):
            for key in ("thread_id", "threadId", "session_id"):
                value = item.get(key)
                if isinstance(value, str) and value:
                    return value
    return None


def _transport_for_agent(agent_type: str) -> str:
    if agent_type == "codex-cli":
        return "exec-jsonl"
    if agent_type == "opencode":
        return "cli-session"
    return "process"


def _truncate_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 80].rstrip() + "\n[...truncated for session display...]"


def _looks_like_user_input_request(text: str) -> bool:
    normalized = " ".join(text.lower().split())
    if not normalized:
        return False
    patterns = [
        "please let me know",
        "which approach",
        "do you approve",
        "if you approve",
        "provide more",
        "need more information",
        "choose one",
        "choose a",
        "choose b",
        "select a",
        "select b",
        "prefer another",
    ]
    return any(pattern in normalized for pattern in patterns)
