from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from hashlib import sha1
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models.approval import utcnow
from app.models.enums import (
    AgentSessionStatus,
    EventType,
    InteractionSource,
    InteractionStatus,
    RunStatus,
    SessionMessageRole,
)
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
            self._start_opencode_http_turn(
                record,
                payload.prompt,
                original_user_message=payload.prompt,
                session_factory=session_factory,
            )
            if payload.agent_type == "opencode"
            else self._start_codex_app_server_turn(
                record,
                payload.prompt,
                original_user_message=payload.prompt,
                session_factory=session_factory,
            )
            if payload.agent_type == "codex-cli" and _use_codex_app_server()
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
            self._start_opencode_http_turn(
                record,
                payload.message,
                original_user_message=payload.message,
                session_factory=session_factory,
            )
            if record.agent_type == "opencode"
            else self._start_codex_app_server_turn(
                record,
                payload.message,
                original_user_message=payload.message,
                session_factory=session_factory,
            )
            if record.agent_type == "codex-cli" and _use_codex_app_server()
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
            agent_messages = self.session.scalars(
                select(SessionMessage).where(
                    SessionMessage.session_id == record.id,
                    SessionMessage.run_id == run_id,
                    SessionMessage.role == SessionMessageRole.AGENT,
                )
            )
            has_run_output = any(
                message.message_metadata.get("source") == "run_output"
                for message in agent_messages
            )
            has_native_text = any(
                message.message_metadata.get("source") == "opencode_message_part"
                and message.message_metadata.get("part_type") == "text"
                for message in agent_messages
            )
            if not has_run_output and not has_native_text:
                self.add_message(
                    record.id,
                    role=SessionMessageRole.AGENT,
                    run_id=run_id,
                    content=output,
                    metadata={"source": "run_output"},
                )
            from app.services.interaction_service import InteractionService

            InteractionService(self.session).create_from_agent_output(record, run_id=run_id, output=output)
        if record.last_run_id not in {None, run_id}:
            self.session.commit()
            return
        record.last_run_id = run_id
        record.updated_at = utcnow()
        if status == RunStatus.CANCELLED:
            record.status = AgentSessionStatus.CANCELLED
        elif status == RunStatus.FAILED:
            record.status = AgentSessionStatus.FAILED
        elif self._has_pending_interaction(record.id):
            record.status = AgentSessionStatus.WAITING_USER_INPUT
        else:
            record.status = AgentSessionStatus.COMPLETED
        if output:
            record.summary = _summary_from_output(output)
        self.session.add(record)
        self.session.commit()

    def refresh_interaction_status(self, session_id: str) -> None:
        record = self.get(session_id)
        if record is None:
            return
        if self._has_pending_interaction(session_id):
            record.status = AgentSessionStatus.WAITING_USER_INPUT
        elif record.status == AgentSessionStatus.WAITING_USER_INPUT:
            run = self.session.get(RunRecord, record.last_run_id) if record.last_run_id else None
            record.status = (
                AgentSessionStatus.ACTIVE
                if run is not None and run.status == RunStatus.STARTED
                else AgentSessionStatus.COMPLETED
            )
        record.updated_at = utcnow()
        self.session.add(record)

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

    def _start_codex_app_server_turn(
        self,
        record: AgentSession,
        prompt: str,
        *,
        original_user_message: str,
        session_factory: sessionmaker | None,
    ):
        from app.runners.agent_adapters import get_adapter
        from app.services.agent_run_service import AgentRunResult

        if session_factory is None:
            raise ValueError("session_factory is required for Codex app-server session turns.")

        adapter = get_adapter("codex-cli")
        executable = adapter.find_executable()
        record.status = AgentSessionStatus.ACTIVE
        record.transport = "app-server-stdio"
        record.updated_at = utcnow()
        self.session.add(record)
        self.session.commit()

        planned_command = [executable, "app-server"]
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
                    "transport": "app-server-stdio",
                },
            )
        )
        EventService(self.session).create(
            EventCreate(
                run_id=run.id,
                event_type=EventType.PLAN_CREATED,
                message="Codex app-server session turn planned.",
                payload={
                    "planned_command": planned_command,
                    "transport": "app-server-stdio",
                    "external_session_id": record.external_session_id,
                },
            )
        )
        self.session.commit()

        worker = threading.Thread(
            target=_complete_codex_app_server_turn,
            kwargs={
                "session_factory": session_factory,
                "run_id": run.id,
                "session_id": record.id,
                "executable": executable,
                "workspace": record.workspace,
                "external_thread_id": record.external_session_id,
                "prompt": prompt,
            },
            daemon=True,
        )
        worker.start()
        record.last_run_id = run.id
        record.updated_at = utcnow()
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return AgentRunResult(
            run=run,
            prompt=prompt,
            agent_type=record.agent_type,
            runner_mode=record.runner_mode,
            planned_command=planned_command,
        )

    def _start_opencode_http_turn(
        self,
        record: AgentSession,
        prompt: str,
        *,
        original_user_message: str,
        session_factory: sessionmaker | None,
    ):
        from app.runners.agent_adapters import get_adapter
        from app.runners.opencode_server import OpenCodeServerClient, ensure_opencode_backend
        from app.services.agent_run_service import AgentRunResult

        if session_factory is None:
            raise ValueError("session_factory is required for OpenCode HTTP session turns.")

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

        external_session_id = record.external_session_id
        if external_session_id is None:
            raise RuntimeError("OpenCode HTTP session id was not initialized.")
        worker = threading.Thread(
            target=_complete_opencode_http_turn,
            kwargs={
                "session_factory": session_factory,
                "run_id": run.id,
                "base_url": handle.base_url,
                "external_session_id": external_session_id,
                "prompt": prompt,
            },
            daemon=True,
        )
        record.last_run_id = run.id
        record.updated_at = utcnow()
        self.session.add(record)
        self.session.commit()
        worker.start()
        self.session.refresh(record)
        return AgentRunResult(
            run=run,
            prompt=prompt,
            agent_type=record.agent_type,
            runner_mode=record.runner_mode,
            planned_command=planned_command,
        )

    def reattach_opencode_http_turn(
        self,
        session_id: str,
        *,
        session_factory: sessionmaker,
    ) -> RunRecord:
        record = self.get(session_id)
        if record is None or record.transport != "http" or not record.backend_url or not record.external_session_id:
            raise ValueError("OpenCode HTTP session is not available for reattachment.")
        run = RunService(self.session).create(
            RunRecordCreate(source=record.agent_type, cwd=record.workspace, session_id=record.id)
        )
        EventService(self.session).create(
            EventCreate(
                run_id=run.id,
                event_type=EventType.PLAN_CREATED,
                message="Reattached to the active OpenCode HTTP session turn.",
                payload={
                    "transport": "http",
                    "reattached": True,
                    "external_session_id": record.external_session_id,
                    "backend_url": record.backend_url,
                },
            )
        )
        record.last_run_id = run.id
        record.status = AgentSessionStatus.ACTIVE
        record.updated_at = utcnow()
        self.session.add(record)
        self.session.commit()

        worker = threading.Thread(
            target=_complete_opencode_http_monitor,
            kwargs={
                "session_factory": session_factory,
                "run_id": run.id,
                "base_url": record.backend_url,
                "external_session_id": record.external_session_id,
            },
            daemon=True,
        )
        worker.start()
        self.session.refresh(run)
        return run

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
            if (
                not isinstance(raw_event, dict)
                and event.payload.get("stream") == "stdout"
                and isinstance(fallback_text, str)
                and fallback_text.strip()
            ):
                fallback_chunks.append(fallback_text.strip())
        if chunks:
            selected = chunks[-1] if self.session.get(RunRecord, run_id).source == "codex-cli" else "\n".join(chunks)
        else:
            selected = "\n".join(fallback_chunks)
        return _truncate_text(selected.strip(), MAX_SESSION_MESSAGE_CHARS)

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

    def _has_pending_interaction(self, session_id: str) -> bool:
        from app.models.interaction import SessionInteraction

        return (
            self.session.scalar(
                select(SessionInteraction.id)
                .where(
                    SessionInteraction.session_id == session_id,
                    SessionInteraction.status == InteractionStatus.PENDING,
                )
                .limit(1)
            )
            is not None
        )


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
        if event_type != "item.completed":
            return None
        item = raw_event.get("item")
        if not isinstance(item, dict) or item.get("type") not in {"agent_message", "assistant_message"}:
            return None
        for key in ("text", "message", "content"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return value
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


def _use_codex_app_server() -> bool:
    return os.environ.get("MICA_CODEX_SESSION_TRANSPORT", "").strip().lower() in {
        "app-server",
        "app-server-stdio",
        "native",
    }


def _complete_codex_app_server_turn(
    *,
    session_factory: sessionmaker,
    run_id: str,
    session_id: str,
    executable: str,
    workspace: str,
    external_thread_id: str | None,
    prompt: str,
) -> None:
    from app.runners.codex_app_server import CodexAppServerClient

    with session_factory() as session:
        try:
            with CodexAppServerClient(executable, workspace) as client:
                thread_id = client.start_or_resume_thread(thread_id=external_thread_id, cwd=workspace)
                result = client.run_turn(thread_id=thread_id, prompt=prompt, cwd=workspace)

            record = session.get(AgentSession, session_id)
            if record is not None:
                record.external_session_id = result.thread_id
                record.transport = "app-server-stdio"
                record.status = AgentSessionStatus.ACTIVE
                record.updated_at = utcnow()
                session.add(record)

            for event in result.events:
                EventService(session).create(
                    EventCreate(
                        run_id=run_id,
                        event_type=EventType.COMMAND_OUTPUT,
                        message=_codex_app_server_event_message(event),
                        payload={
                            "stream": "stdout",
                            "text": _codex_app_server_event_text(event),
                            "raw_event": event,
                            "transport": "app-server-stdio",
                            "thread_id": result.thread_id,
                            "turn_id": result.turn_id,
                        },
                    )
                )

            if result.text:
                EventService(session).create(
                    EventCreate(
                        run_id=run_id,
                        event_type=EventType.COMMAND_OUTPUT,
                        message=result.text[:500],
                        payload={
                            "stream": "stdout",
                            "text": result.text,
                            "raw_event": {
                                "type": "text",
                                "message": result.text,
                                "thread_id": result.thread_id,
                                "turn_id": result.turn_id,
                                "transport": "app-server-stdio",
                            },
                        },
                    )
                )
            session.commit()
            terminal_status = RunStatus.COMPLETED if result.status not in {"failed", "error", "cancelled", "interrupted"} else RunStatus.FAILED
            finished_run = RunService(session).finish_with_status(run_id, status=terminal_status)
        except Exception as exc:
            EventService(session).create(
                EventCreate(
                    run_id=run_id,
                    event_type=EventType.COMMAND_OUTPUT,
                    message=f"Codex app-server turn failed: {exc}",
                    payload={"stream": "stderr", "text": str(exc), "transport": "app-server-stdio"},
                )
            )
            session.commit()
            finished_run = RunService(session).finish_with_status(run_id, status=RunStatus.FAILED)

        if finished_run is not None:
            SessionService(session).finalize_run(finished_run.id, status=finished_run.status)


def _codex_app_server_event_message(event: dict[str, object]) -> str:
    method = event.get("method")
    if isinstance(method, str):
        text = _codex_app_server_event_text(event)
        return text[:500] if text else f"Codex app-server event: {method}"
    return "Codex app-server event."


def _codex_app_server_event_text(event: dict[str, object]) -> str:
    params = event.get("params")
    if not isinstance(params, dict):
        return ""
    delta = params.get("delta")
    if isinstance(delta, str):
        return delta
    item = params.get("item")
    if isinstance(item, dict):
        for key in ("text", "message", "content", "delta"):
            value = item.get(key)
            if isinstance(value, str):
                return value
    return ""


def _complete_opencode_http_turn(
    *,
    session_factory: sessionmaker,
    run_id: str,
    base_url: str,
    external_session_id: str,
    prompt: str,
) -> None:
    import urllib.error

    from app.runners.opencode_server import (
        OpenCodeServerClient,
        assistant_message_id,
        extract_latest_assistant_text,
        extract_text,
    )

    timeout = _opencode_turn_timeout()
    with session_factory() as session:
        try:
            client = OpenCodeServerClient(base_url)
            response: dict[str, object] | None = None
            baseline_messages = client.messages(external_session_id)
            _, baseline_message = extract_latest_assistant_text(baseline_messages)
            baseline_message_id = assistant_message_id(baseline_message)
            seen_part_states = _opencode_part_state_keys(baseline_messages)
            try:
                client.prompt_async(external_session_id, prompt, timeout=30)
            except urllib.error.HTTPError as exc:
                if exc.code not in {404, 405}:
                    raise
                response = client.prompt(external_session_id, prompt, timeout=timeout)
                output = extract_text(response) or "OpenCode HTTP turn completed."
                raw_message = response
            else:
                response = _wait_for_opencode_session_idle(
                    client,
                    external_session_id,
                    baseline_message_id=baseline_message_id,
                    seen_part_states=seen_part_states,
                    timeout=timeout,
                    db_session=session,
                    run_id=run_id,
                )
                output, raw_message = extract_latest_assistant_text(client.messages(external_session_id))
                if not output:
                    output = "OpenCode HTTP turn completed."
                    raw_message = response
            EventService(session).create(
                EventCreate(
                    run_id=run_id,
                    event_type=EventType.COMMAND_OUTPUT,
                    message=output[:500],
                    payload={
                        "stream": "stdout",
                        "text": output,
                        "raw_event": {
                            "type": "text",
                            "message": output,
                            "opencode_response": raw_message,
                            "sessionID": external_session_id,
                        },
                    },
                )
            )
            session.commit()
            finished_run = RunService(session).finish_with_status(run_id, status=RunStatus.COMPLETED)
        except Exception as exc:
            EventService(session).create(
                EventCreate(
                    run_id=run_id,
                    event_type=EventType.COMMAND_OUTPUT,
                    message=f"OpenCode HTTP turn failed: {exc}",
                    payload={"stream": "stderr", "text": str(exc)},
                )
            )
            session.commit()
            finished_run = RunService(session).finish_with_status(run_id, status=RunStatus.FAILED)

        if finished_run is not None:
            SessionService(session).finalize_run(finished_run.id, status=finished_run.status)


def _opencode_turn_timeout() -> float | None:
    value = os.environ.get("MICA_OPENCODE_TURN_TIMEOUT_SECONDS", "7200").strip().lower()
    if value in {"", "0", "none", "disabled"}:
        return None
    return float(value)


def _wait_for_opencode_session_idle(
    client,
    external_session_id: str,
    *,
    baseline_message_id: str | None,
    seen_part_states: set[str],
    timeout: float | None,
    db_session: Session,
    run_id: str,
) -> dict[str, object]:
    import socket
    import time
    import urllib.error

    from app.runners.opencode_server import (
        assistant_message_completed,
        assistant_message_id,
        extract_latest_assistant_text,
    )

    deadline = None if timeout is None else time.time() + timeout
    paused_for_user_input = False
    last_event: dict[str, object] = {}
    stream_supported = True
    questions_supported = True
    while True:
        messages = client.messages(external_session_id)
        _record_opencode_message_updates(
            db_session,
            run_id=run_id,
            external_session_id=external_session_id,
            messages=messages,
            seen_part_states=seen_part_states,
        )
        if questions_supported:
            try:
                _record_native_question_interactions(
                    db_session,
                    run_id=run_id,
                    external_session_id=external_session_id,
                    requests=client.questions(),
                )
            except urllib.error.HTTPError as exc:
                if exc.code not in {404, 405}:
                    raise
                questions_supported = False

        from app.models.interaction import SessionInteraction

        has_pending_interaction = db_session.scalar(
            select(SessionInteraction.id)
            .where(
                SessionInteraction.run_id == run_id,
                SessionInteraction.status == InteractionStatus.PENDING,
            )
            .limit(1)
        ) is not None
        if has_pending_interaction:
            paused_for_user_input = True
            deadline = None
        elif paused_for_user_input:
            paused_for_user_input = False
            deadline = None if timeout is None else time.time() + timeout

        _, latest_message = extract_latest_assistant_text(messages)
        latest_message_id = assistant_message_id(latest_message)
        session_busy = False
        try:
            status_payload = client.session_status()
            session_busy = _opencode_session_is_busy(status_payload, external_session_id)
        except urllib.error.HTTPError as exc:
            if exc.code not in {404, 405}:
                raise
        if (
            latest_message_id is not None
            and latest_message_id != baseline_message_id
            and assistant_message_completed(latest_message)
            and not session_busy
        ):
            return {
                "type": "session.idle",
                "sessionID": external_session_id,
                "source": "completed_assistant_message",
            }

        if deadline is not None and time.time() > deadline:
            raise TimeoutError("OpenCode event stream timed out waiting for session idle")

        if not stream_supported:
            time.sleep(0.2)
            continue

        stream_timeout = 1.0 if deadline is None else max(0.1, min(1.0, deadline - time.time()))
        try:
            for event in client.stream_events(timeout=stream_timeout):
                last_event = event
                session_id = _event_session_id(event)
                if session_id and session_id != external_session_id:
                    continue
                if _record_opencode_stream_event(
                    db_session,
                    run_id=run_id,
                    external_session_id=external_session_id,
                    event=event,
                    seen_part_states=seen_part_states,
                ):
                    continue
                if _event_is_permission_request(event):
                    _record_native_permission_interaction(
                        db_session,
                        run_id=run_id,
                        external_session_id=external_session_id,
                        event=event,
                    )
                    continue
                if _event_is_session_idle(event):
                    return event
                if deadline is not None and time.time() > deadline:
                    raise TimeoutError("OpenCode event stream timed out waiting for session idle")
        except urllib.error.HTTPError as exc:
            if exc.code not in {404, 405}:
                raise
            stream_supported = False
        except (TimeoutError, socket.timeout, urllib.error.URLError):
            continue


def _complete_opencode_http_monitor(
    *,
    session_factory: sessionmaker,
    run_id: str,
    base_url: str,
    external_session_id: str,
) -> None:
    from app.runners.opencode_server import OpenCodeServerClient, extract_latest_assistant_text

    with session_factory() as session:
        try:
            client = OpenCodeServerClient(base_url)
            messages = client.messages(external_session_id)
            seen_part_states = _opencode_part_state_keys(messages)
            output, latest_message = extract_latest_assistant_text(messages)
            status_payload = client.session_status()
            if _opencode_session_is_busy(status_payload, external_session_id):
                baseline_message_id = _latest_completed_opencode_message_id(messages)
                _wait_for_opencode_session_idle(
                    client,
                    external_session_id,
                    baseline_message_id=baseline_message_id,
                    seen_part_states=seen_part_states,
                    timeout=_opencode_turn_timeout(),
                    db_session=session,
                    run_id=run_id,
                )
                output, latest_message = extract_latest_assistant_text(client.messages(external_session_id))
            output = output or "OpenCode HTTP session turn completed."
            EventService(session).create(
                EventCreate(
                    run_id=run_id,
                    event_type=EventType.COMMAND_OUTPUT,
                    message=output[:500],
                    payload={
                        "stream": "stdout",
                        "text": output,
                        "raw_event": {
                            "type": "text",
                            "message": output,
                            "opencode_response": latest_message,
                            "sessionID": external_session_id,
                            "reattached": True,
                        },
                    },
                )
            )
            session.commit()
            finished_run = RunService(session).finish_with_status(run_id, status=RunStatus.COMPLETED)
        except Exception as exc:
            EventService(session).create(
                EventCreate(
                    run_id=run_id,
                    event_type=EventType.COMMAND_OUTPUT,
                    message=f"OpenCode HTTP reattach failed: {exc}",
                    payload={"stream": "stderr", "text": str(exc), "reattached": True},
                )
            )
            session.commit()
            finished_run = RunService(session).finish_with_status(run_id, status=RunStatus.FAILED)

        if finished_run is not None:
            SessionService(session).finalize_run(finished_run.id, status=finished_run.status)


def _latest_completed_opencode_message_id(messages: list[dict[str, object]]) -> str | None:
    from app.runners.opencode_server import assistant_message_completed, assistant_message_id

    for message in reversed(messages):
        if assistant_message_completed(message):
            return assistant_message_id(message)
    return None


def _opencode_part_state_keys(messages: list[dict[str, object]]) -> set[str]:
    keys: set[str] = set()
    for message in messages:
        info = message.get("info")
        message_id = info.get("id") if isinstance(info, dict) else None
        parts = message.get("parts")
        if not isinstance(parts, list):
            continue
        for index, part in enumerate(parts):
            if not isinstance(part, dict):
                continue
            keys.add(_opencode_part_state_key(message_id, part, index))
    return keys


def _opencode_part_state_key(message_id: object, part: dict[str, object], index: int) -> str:
    part_id = part.get("id")
    if part.get("type") == "text":
        text = part.get("text")
        digest = sha1(text.encode("utf-8")).hexdigest() if isinstance(text, str) else ""
        return f"{message_id or 'message'}:{part_id or index}:text:{digest}"
    state = part.get("state")
    status = state.get("status") if isinstance(state, dict) else None
    return f"{message_id or 'message'}:{part_id or index}:{status or ''}"


def _record_opencode_message_updates(
    session: Session,
    *,
    run_id: str,
    external_session_id: str,
    messages: list[dict[str, object]],
    seen_part_states: set[str],
) -> None:
    record = session.scalar(
        select(AgentSession).where(
            AgentSession.external_session_id == external_session_id,
            AgentSession.agent_type == "opencode",
        )
    )
    if record is None:
        return
    native_messages = {
        (
            message.message_metadata.get("external_message_id"),
            message.message_metadata.get("external_part_id"),
        ): message
        for message in session.scalars(
            select(SessionMessage).where(
                SessionMessage.session_id == record.id,
                SessionMessage.role == SessionMessageRole.AGENT,
            )
        )
        if message.message_metadata.get("source") == "opencode_message_part"
    }
    created = False
    for message in messages:
        info = message.get("info")
        if not isinstance(info, dict) or info.get("role") != "assistant":
            continue
        message_id = info.get("id")
        parts = message.get("parts")
        if not isinstance(parts, list):
            continue
        for index, part in enumerate(parts):
            if not isinstance(part, dict):
                continue
            key = _opencode_part_state_key(message_id, part, index)
            if key in seen_part_states:
                continue
            seen_part_states.add(key)
            part_type = part.get("type")
            if part_type == "text":
                text = part.get("text")
                if not isinstance(text, str) or not text.strip():
                    continue
                _upsert_opencode_session_message(
                    session,
                    native_messages=native_messages,
                    session_id=record.id,
                    run_id=run_id,
                    message_id=message_id,
                    part=part,
                    content=text,
                    metadata={"part_type": "text"},
                )
                EventService(session).create(
                    EventCreate(
                        run_id=run_id,
                        event_type=EventType.COMMAND_OUTPUT,
                        message=text[:500],
                        payload={
                            "stream": "stdout",
                            "text": text,
                            "raw_event": {
                                "type": "opencode_message_part",
                                "sessionID": external_session_id,
                                "messageID": message_id,
                                "part": part,
                            },
                        },
                    )
                )
                created = True
            elif part_type == "tool":
                tool = part.get("tool")
                state = part.get("state")
                status = state.get("status") if isinstance(state, dict) else None
                title = state.get("title") if isinstance(state, dict) else None
                summary = title if isinstance(title, str) and title else f"OpenCode tool {tool or 'unknown'} {status or 'updated'}."
                _upsert_opencode_session_message(
                    session,
                    native_messages=native_messages,
                    session_id=record.id,
                    run_id=run_id,
                    message_id=message_id,
                    part=part,
                    content=summary,
                    metadata={
                        "part_type": "tool",
                        "tool_name": tool,
                        "tool_status": status,
                        "tool_title": title,
                    },
                )
                EventService(session).create(
                    EventCreate(
                        run_id=run_id,
                        event_type=EventType.COMMAND_OUTPUT,
                        message=summary,
                        payload={
                            "stream": "agent",
                            "text": summary,
                            "raw_event": {
                                "type": "tool_use",
                                "sessionID": external_session_id,
                                "messageID": message_id,
                                "part": part,
                            },
                        },
                    )
                )
                created = True
    if created:
        session.commit()


def _upsert_opencode_session_message(
    session: Session,
    *,
    native_messages: dict[tuple[object, object], SessionMessage],
    session_id: str,
    run_id: str,
    message_id: object,
    part: dict[str, object],
    content: str,
    metadata: dict[str, object],
) -> None:
    part_id = part.get("id")
    key = (message_id, part_id)
    message = native_messages.get(key)
    message_metadata = {
        "source": "opencode_message_part",
        "external_message_id": message_id,
        "external_part_id": part_id,
        **metadata,
    }
    if message is None:
        message = SessionMessage(
            session_id=session_id,
            run_id=run_id,
            role=SessionMessageRole.AGENT,
            content=content,
            message_metadata=message_metadata,
        )
        session.add(message)
        native_messages[key] = message
        return
    message.content = content
    message.run_id = run_id
    message.message_metadata = message_metadata
    session.add(message)


def _record_opencode_stream_event(
    session: Session,
    *,
    run_id: str,
    external_session_id: str,
    event: dict[str, object],
    seen_part_states: set[str],
) -> bool:
    event_type = event.get("type")
    properties = event.get("properties")
    if not isinstance(properties, dict):
        return False
    if event_type == "message.part.updated":
        part = properties.get("part")
        if not isinstance(part, dict):
            return False
        part_session_id = part.get("sessionID") or part.get("sessionId") or part.get("session_id")
        if part_session_id != external_session_id:
            return False
        message_id = part.get("messageID") or part.get("messageId") or part.get("message_id")
        _record_opencode_message_updates(
            session,
            run_id=run_id,
            external_session_id=external_session_id,
            messages=[{"info": {"id": message_id, "role": "assistant"}, "parts": [part]}],
            seen_part_states=seen_part_states,
        )
        return True
    if event_type == "question.asked":
        _record_native_question_interactions(
            session,
            run_id=run_id,
            external_session_id=external_session_id,
            requests=[properties],
        )
        return True
    return False


def _record_native_question_interactions(
    session: Session,
    *,
    run_id: str,
    external_session_id: str,
    requests: list[dict[str, object]],
) -> None:
    from app.models.interaction import SessionInteraction

    record = session.scalar(
        select(AgentSession).where(
            AgentSession.external_session_id == external_session_id,
            AgentSession.agent_type == "opencode",
        )
    )
    if record is None:
        return
    created = False
    from app.services.interaction_service import InteractionService

    for request in requests:
        session_id = request.get("sessionID") or request.get("sessionId") or request.get("session_id")
        if session_id != external_session_id:
            continue
        request_id = request.get("id")
        if isinstance(request_id, str):
            existing = session.scalar(
                select(SessionInteraction.id).where(
                    SessionInteraction.session_id == record.id,
                    SessionInteraction.source == InteractionSource.NATIVE,
                    SessionInteraction.external_id == request_id,
                )
            )
            if existing is not None:
                continue
        interaction = InteractionService(session).create_native_question(record, run_id=run_id, request=request)
        created = (
            interaction is not None and interaction.status == InteractionStatus.PENDING
        ) or created
        if interaction is not None:
            session.add(
                SessionMessage(
                    session_id=record.id,
                    run_id=run_id,
                    role=SessionMessageRole.AGENT,
                    content=_opencode_question_message(request),
                    message_metadata={
                        "source": "native_interaction",
                        "interaction_id": interaction.id,
                    },
                )
            )
    if created:
        record.status = AgentSessionStatus.WAITING_USER_INPUT
        record.updated_at = utcnow()
        session.add(record)
        session.commit()


def _opencode_session_is_busy(payload: dict[str, object], external_session_id: str) -> bool:
    status = payload.get(external_session_id)
    if not isinstance(status, dict):
        return False
    return status.get("type") in {"busy", "retry"}


def _opencode_question_message(request: dict[str, object]) -> str:
    questions = request.get("questions")
    if not isinstance(questions, list):
        return "OpenCode needs user input."
    blocks: list[str] = []
    for question_index, question in enumerate(questions):
        if not isinstance(question, dict):
            continue
        prompt = question.get("question")
        if not isinstance(prompt, str):
            continue
        lines = [f"{question_index + 1}. {prompt}"]
        options = question.get("options")
        if isinstance(options, list):
            for option_index, option in enumerate(options):
                if isinstance(option, dict) and isinstance(option.get("label"), str):
                    lines.append(f"   {option_index + 1}) {option['label']}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) or "OpenCode needs user input."


def _event_session_id(event: dict[str, object]) -> str | None:
    for key in ("sessionID", "sessionId", "session_id"):
        value = event.get(key)
        if isinstance(value, str):
            return value
    properties = event.get("properties")
    if isinstance(properties, dict):
        for key in ("sessionID", "sessionId", "session_id"):
            value = properties.get(key)
            if isinstance(value, str):
                return value
    return None


def _event_is_session_idle(event: dict[str, object]) -> bool:
    event_type = event.get("type")
    if event_type == "session.idle":
        return True
    properties = event.get("properties")
    return isinstance(properties, dict) and properties.get("type") == "session.idle"


def _event_is_permission_request(event: dict[str, object]) -> bool:
    event_type = str(event.get("type") or "")
    return "permission" in event_type and any(word in event_type for word in ("ask", "request"))


def _record_native_permission_interaction(
    session: Session,
    *,
    run_id: str,
    external_session_id: str,
    event: dict[str, object],
) -> None:
    record = session.scalar(
        select(AgentSession).where(
            AgentSession.external_session_id == external_session_id,
            AgentSession.agent_type == "opencode",
        )
    )
    if record is None:
        return
    permission_id = _event_permission_id(event)
    if permission_id is None:
        return
    from app.services.interaction_service import InteractionService

    InteractionService(session).create_native_permission(
        record,
        run_id=run_id,
        permission_id=permission_id,
        prompt=_event_permission_prompt(event),
    )
    record.status = AgentSessionStatus.WAITING_USER_INPUT
    record.updated_at = utcnow()
    session.add(record)
    session.commit()


def _event_permission_id(event: dict[str, object]) -> str | None:
    for key in ("permissionID", "permissionId", "permission_id", "id"):
        value = event.get(key)
        if isinstance(value, str) and value:
            return value
    properties = event.get("properties")
    if isinstance(properties, dict):
        for key in ("permissionID", "permissionId", "permission_id", "id"):
            value = properties.get(key)
            if isinstance(value, str) and value:
                return value
    return None


def _event_permission_prompt(event: dict[str, object]) -> str:
    for key in ("prompt", "message", "title", "description"):
        value = event.get(key)
        if isinstance(value, str) and value:
            return value
    properties = event.get("properties")
    if isinstance(properties, dict):
        for key in ("prompt", "message", "title", "description"):
            value = properties.get(key)
            if isinstance(value, str) and value:
                return value
    return "OpenCode requests permission to continue."
