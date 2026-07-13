from __future__ import annotations

import json
import re
from dataclasses import dataclass
from hashlib import sha1
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models.approval import utcnow
from app.models.enums import (
    AgentSessionStatus,
    EventType,
    InteractionKind,
    InteractionSource,
    InteractionStatus,
    RunStatus,
    SessionMessageRole,
)
from app.models.interaction import SessionInteraction
from app.models.run import RunRecord
from app.models.session import AgentSession, SessionMessage
from app.schemas.events import EventCreate
from app.schemas.interactions import (
    InteractionRespondRead,
    InteractionRespondRequest,
    SessionInteractionCreate,
)
from app.schemas.runs import RunRecordRead
from app.schemas.sessions import AgentSessionRead, SessionContinueRead, SessionContinueRequest, SessionMessageRead
from app.services.event_service import EventService


@dataclass(frozen=True)
class InteractionDraft:
    kind: InteractionKind
    source: InteractionSource
    prompt: str
    options: list[dict[str, str]]
    external_id: str | None = None


class InteractionService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_for_session(
        self,
        session_id: str,
        *,
        status: InteractionStatus | None = None,
    ) -> list[SessionInteraction]:
        statement = (
            select(SessionInteraction)
            .where(SessionInteraction.session_id == session_id)
            .order_by(SessionInteraction.created_at.asc(), SessionInteraction.id.asc())
        )
        if status is not None:
            statement = statement.where(SessionInteraction.status == status)
        return list(self.session.scalars(statement))

    def pending_for_session(self, session_id: str) -> list[SessionInteraction]:
        return self.list_for_session(session_id, status=InteractionStatus.PENDING)

    def get(self, interaction_id: str) -> SessionInteraction | None:
        return self.session.get(SessionInteraction, interaction_id)

    def create(self, payload: SessionInteractionCreate) -> SessionInteraction:
        existing = self._existing_pending(payload)
        if existing is not None:
            if payload.source == InteractionSource.NATIVE:
                existing.prompt = payload.prompt
                existing.options = payload.options
                self.session.flush()
            return existing
        interaction = SessionInteraction(**payload.model_dump())
        self.session.add(interaction)
        self.session.flush()
        EventService(self.session).create(
            EventCreate(
                run_id=interaction.run_id,
                event_type=EventType.INTERACTION_REQUIRED,
                message=f"{interaction.kind.value} interaction required.",
                payload={
                    "interaction_id": interaction.id,
                    "session_id": interaction.session_id,
                    "kind": interaction.kind.value,
                    "source": interaction.source.value,
                    "prompt": interaction.prompt,
                    "options": interaction.options,
                    "external_id": interaction.external_id,
                },
            )
        )
        return interaction

    def create_from_agent_output(
        self,
        record: AgentSession,
        *,
        run_id: str,
        output: str,
    ) -> SessionInteraction | None:
        draft = detect_interaction(output)
        if draft is None:
            return None
        external_id = draft.external_id or _heuristic_external_id(run_id, output)
        return self.create(
            SessionInteractionCreate(
                session_id=record.id,
                run_id=run_id,
                adapter=record.agent_type,
                kind=draft.kind,
                source=draft.source,
                prompt=draft.prompt,
                options=draft.options,
                external_id=external_id,
            )
        )

    def create_native_permission(
        self,
        record: AgentSession,
        *,
        run_id: str | None,
        permission_id: str,
        prompt: str,
        options: list[dict[str, str]] | None = None,
    ) -> SessionInteraction:
        return self.create(
            SessionInteractionCreate(
                session_id=record.id,
                run_id=run_id,
                adapter=record.agent_type,
                kind=InteractionKind.PERMISSION,
                source=InteractionSource.NATIVE,
                prompt=prompt,
                options=options
                or [
                    {"id": "allow", "label": "Approve", "value": "allow"},
                    {"id": "deny", "label": "Reject", "value": "deny"},
                ],
                external_id=permission_id,
            )
        )

    def create_native_question(
        self,
        record: AgentSession,
        *,
        run_id: str,
        request: dict[str, Any],
    ) -> SessionInteraction | None:
        request_id = request.get("id")
        questions = request.get("questions")
        if not isinstance(request_id, str) or not isinstance(questions, list) or not questions:
            return None
        normalized_questions = [question for question in questions if isinstance(question, dict)]
        if not normalized_questions:
            return None
        first_prompt = normalized_questions[0].get("question")
        if not isinstance(first_prompt, str) or not first_prompt.strip():
            return None
        options: list[dict[str, Any]] = []
        for question_index, question in enumerate(normalized_questions):
            question_text = question.get("question")
            if not isinstance(question_text, str) or not question_text.strip():
                continue
            multiple = question.get("multiple") is True
            raw_options = question.get("options")
            if not isinstance(raw_options, list):
                continue
            for option_index, option in enumerate(raw_options):
                if not isinstance(option, dict):
                    continue
                label = option.get("label")
                if not isinstance(label, str) or not label:
                    continue
                normalized: dict[str, Any] = {
                    "id": f"{question_index + 1}:{option_index + 1}",
                    "label": label,
                    "value": label,
                    "question_index": question_index,
                    "question": question_text,
                    "multiple": multiple,
                }
                header = question.get("header")
                if isinstance(header, str) and header:
                    normalized["header"] = header
                description = option.get("description")
                if isinstance(description, str) and description:
                    normalized["description"] = description
                options.append(normalized)
        prompt = (
            first_prompt
            if len(normalized_questions) == 1
            else f"OpenCode needs answers to {len(normalized_questions)} questions."
        )
        return self.create(
            SessionInteractionCreate(
                session_id=record.id,
                run_id=run_id,
                adapter=record.agent_type,
                kind=InteractionKind.CHOICE if options else InteractionKind.TEXT,
                source=InteractionSource.NATIVE,
                prompt=prompt,
                options=options,
                external_id=request_id,
            )
        )

    def respond(
        self,
        interaction_id: str,
        payload: InteractionRespondRequest,
        *,
        session_factory: sessionmaker | None,
    ) -> InteractionRespondRead | None:
        interaction = self.get(interaction_id)
        if interaction is None:
            return None
        if interaction.status != InteractionStatus.PENDING:
            return InteractionRespondRead(
                interaction=SessionInteractionReadCompat.model_validate(interaction),
                action="responded_permission" if interaction.kind == InteractionKind.PERMISSION else "continued_session",
            )
        response_payload: dict[str, Any] = {
            "response": payload.response,
            "option_id": payload.option_id,
            "answers": payload.answers,
            "remember": payload.remember,
        }
        if self._is_native_opencode_question(interaction):
            answered_natively = self._respond_native_question(interaction, payload)
            interaction.status = InteractionStatus.RESPONDED
            interaction.response_payload = response_payload
            interaction.resolved_at = utcnow()
            self.session.add(interaction)
            self._record_responded_event(interaction)
            if answered_natively:
                self.session.add(
                    SessionMessage(
                        session_id=interaction.session_id,
                        run_id=interaction.run_id,
                        role=SessionMessageRole.USER,
                        content=_native_answer_message(payload),
                        message_metadata={
                            "source": "native_interaction_response",
                            "interaction_id": interaction.id,
                        },
                    )
                )
                record = self.session.get(AgentSession, interaction.session_id)
                if record is not None:
                    remaining = self.session.scalar(
                        select(SessionInteraction.id)
                        .where(
                            SessionInteraction.session_id == interaction.session_id,
                            SessionInteraction.status == InteractionStatus.PENDING,
                            SessionInteraction.id != interaction.id,
                        )
                        .limit(1)
                    )
                    record.status = (
                        AgentSessionStatus.WAITING_USER_INPUT
                        if remaining is not None
                        else AgentSessionStatus.ACTIVE
                    )
                    record.updated_at = utcnow()
                    self.session.add(record)
            self.session.commit()
            self.session.refresh(interaction)
            if answered_natively:
                linked_run = self.session.get(RunRecord, interaction.run_id) if interaction.run_id else None
                if linked_run is None or linked_run.status != RunStatus.STARTED:
                    if session_factory is None:
                        raise ValueError("session_factory is required to reattach an OpenCode session turn.")
                    from app.services.session_service import SessionService

                    SessionService(self.session).reattach_opencode_http_turn(
                        interaction.session_id,
                        session_factory=session_factory,
                    )
                return InteractionRespondRead(
                    interaction=SessionInteractionReadCompat.model_validate(interaction),
                    action="responded_native_interaction",
                )
            if not answered_natively:
                if session_factory is None:
                    raise ValueError("session_factory is required to recover a lost native question.")
                from app.services.session_service import SessionService

                continued = SessionService(self.session).continue_session(
                    interaction.session_id,
                    SessionContinueRequest(message=payload.response),
                    session_factory,
                )
                if continued is not None:
                    return InteractionRespondRead(
                        interaction=SessionInteractionReadCompat.model_validate(interaction),
                        session=AgentSessionRead.model_validate(continued.session),
                        run=RunRecordRead.model_validate(continued.run),
                        message=SessionMessageRead.model_validate(continued.message),
                        planned_command=continued.planned_command,
                        action="continued_session",
                    )
            self._refresh_session_status(interaction.session_id)
            self.session.commit()
            return InteractionRespondRead(
                interaction=SessionInteractionReadCompat.model_validate(interaction),
                action="responded_native_interaction",
            )
        if interaction.kind == InteractionKind.PERMISSION:
            self._respond_native_permission(interaction, payload)
            interaction.status = InteractionStatus.RESPONDED
            interaction.response_payload = response_payload
            interaction.resolved_at = utcnow()
            self.session.add(interaction)
            self._record_responded_event(interaction)
            self._refresh_session_status(interaction.session_id)
            self.session.commit()
            self.session.refresh(interaction)
            return InteractionRespondRead(
                interaction=SessionInteractionReadCompat.model_validate(interaction),
                action="responded_permission",
            )

        interaction.status = InteractionStatus.RESPONDED
        interaction.response_payload = response_payload
        interaction.resolved_at = utcnow()
        self.session.add(interaction)
        self._record_responded_event(interaction)
        self.session.commit()
        self.session.refresh(interaction)

        if session_factory is None:
            raise ValueError("session_factory is required to continue a session from an interaction.")
        from app.services.session_service import SessionService

        continued = SessionService(self.session).continue_session(
            interaction.session_id,
            SessionContinueRequest(message=payload.response),
            session_factory,
        )
        if continued is None:
            return InteractionRespondRead(
                interaction=SessionInteractionReadCompat.model_validate(interaction),
                action="continued_session",
            )
        return InteractionRespondRead(
            interaction=SessionInteractionReadCompat.model_validate(interaction),
            session=AgentSessionRead.model_validate(continued.session),
            run=RunRecordRead.model_validate(continued.run),
            message=SessionMessageRead.model_validate(continued.message),
            planned_command=continued.planned_command,
            action="continued_session",
        )

    def dismiss(self, interaction_id: str, *, reason: str | None = None) -> SessionInteraction | None:
        interaction = self.get(interaction_id)
        if interaction is None:
            return None
        if interaction.status == InteractionStatus.PENDING:
            interaction.status = InteractionStatus.DISMISSED
            interaction.response_payload = {"reason": reason} if reason else {}
            interaction.resolved_at = utcnow()
            self.session.add(interaction)
            EventService(self.session).create(
                EventCreate(
                    run_id=interaction.run_id,
                    event_type=EventType.INTERACTION_DISMISSED,
                    message=f"{interaction.kind.value} interaction dismissed.",
                    payload={
                        "interaction_id": interaction.id,
                        "session_id": interaction.session_id,
                        "reason": reason,
                    },
                )
            )
            self._refresh_session_status(interaction.session_id)
            self.session.commit()
            self.session.refresh(interaction)
        return interaction

    def _existing_pending(self, payload: SessionInteractionCreate) -> SessionInteraction | None:
        statement = select(SessionInteraction).where(
            SessionInteraction.session_id == payload.session_id,
            SessionInteraction.kind == payload.kind,
            SessionInteraction.source == payload.source,
            SessionInteraction.external_id == payload.external_id,
        )
        if payload.source != InteractionSource.NATIVE or payload.external_id is None:
            statement = statement.where(SessionInteraction.status == InteractionStatus.PENDING)
        return self.session.scalar(statement)

    def _record_responded_event(self, interaction: SessionInteraction) -> None:
        EventService(self.session).create(
            EventCreate(
                run_id=interaction.run_id,
                event_type=EventType.INTERACTION_RESPONDED,
                message=f"{interaction.kind.value} interaction responded.",
                payload={
                    "interaction_id": interaction.id,
                    "session_id": interaction.session_id,
                    "kind": interaction.kind.value,
                    "source": interaction.source.value,
                    "response_payload": interaction.response_payload,
                },
            )
        )

    def _respond_native_permission(
        self,
        interaction: SessionInteraction,
        payload: InteractionRespondRequest,
    ) -> None:
        if interaction.adapter != "opencode" or not interaction.external_id:
            return
        record = self.session.get(AgentSession, interaction.session_id)
        if record is None or not record.external_session_id or not record.backend_url:
            return
        from app.runners.opencode_server import OpenCodeServerClient

        response = _permission_response(payload.response)
        OpenCodeServerClient(record.backend_url).respond_permission(
            record.external_session_id,
            interaction.external_id,
            response=response,
            remember=payload.remember,
        )

    def _is_native_opencode_question(self, interaction: SessionInteraction) -> bool:
        return (
            interaction.adapter == "opencode"
            and interaction.source == InteractionSource.NATIVE
            and interaction.kind in {InteractionKind.CHOICE, InteractionKind.TEXT}
            and bool(interaction.external_id)
        )

    def _respond_native_question(
        self,
        interaction: SessionInteraction,
        payload: InteractionRespondRequest,
    ) -> bool:
        import urllib.error

        record = self.session.get(AgentSession, interaction.session_id)
        if record is None or not record.backend_url or not interaction.external_id:
            return False
        from app.runners.opencode_server import OpenCodeServerClient

        try:
            OpenCodeServerClient(record.backend_url).respond_question(
                interaction.external_id,
                answers=payload.answers or [[payload.response]],
            )
        except urllib.error.HTTPError as exc:
            if exc.code not in {404, 410}:
                raise
            return False
        except (OSError, urllib.error.URLError):
            return False
        return True

    def _refresh_session_status(self, session_id: str) -> None:
        from app.services.session_service import SessionService

        SessionService(self.session).refresh_interaction_status(session_id)


def detect_interaction(output: str) -> InteractionDraft | None:
    structured = _detect_structured_interaction(output)
    if structured is not None:
        return structured
    choice = _detect_choice_interaction(output)
    if choice is not None:
        return choice
    if _looks_like_text_request(output):
        return InteractionDraft(
            kind=InteractionKind.TEXT,
            source=InteractionSource.HEURISTIC,
            prompt=_short_prompt(output),
            options=[],
        )
    return None


def _detect_structured_interaction(output: str) -> InteractionDraft | None:
    candidates = [output, *_json_code_blocks(output)]
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if not isinstance(parsed, dict):
            continue
        raw = parsed.get("mica_interaction")
        if not isinstance(raw, dict):
            continue
        kind = raw.get("kind")
        prompt = raw.get("prompt")
        if kind not in {item.value for item in InteractionKind} or not isinstance(prompt, str):
            continue
        options = _structured_options(raw.get("options"))
        return InteractionDraft(
            kind=InteractionKind(kind),
            source=InteractionSource.STRUCTURED,
            prompt=prompt,
            options=options,
            external_id=raw.get("id") if isinstance(raw.get("id"), str) else None,
        )
    return None


def _detect_choice_interaction(output: str) -> InteractionDraft | None:
    options = _choice_options(output)
    if len(options) < 2:
        return None
    if not _looks_like_choice_request(output):
        return None
    return InteractionDraft(
        kind=InteractionKind.CHOICE,
        source=InteractionSource.HEURISTIC,
        prompt=_choice_prompt(output, options),
        options=options,
    )


def _json_code_blocks(output: str) -> list[str]:
    return re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", output, flags=re.DOTALL | re.IGNORECASE)


def _structured_options(raw_options: object) -> list[dict[str, str]]:
    if not isinstance(raw_options, list):
        return []
    options: list[dict[str, str]] = []
    for index, item in enumerate(raw_options):
        if not isinstance(item, dict):
            continue
        option_id = item.get("id")
        label = item.get("label")
        value = item.get("value")
        if not isinstance(option_id, str):
            option_id = str(index + 1)
        if not isinstance(label, str):
            label = str(value or option_id)
        if not isinstance(value, str):
            value = label
        options.append({"id": option_id, "label": label, "value": value})
    return options


def _choice_options(output: str) -> list[dict[str, str]]:
    options: list[dict[str, str]] = []
    patterns = [
        re.compile(r"^\s*[-*]?\s*(?:\*\*)?([A-Z])(?:\*\*)?[\).:：、]\s*(.+?)\s*$"),
        re.compile(r"^\s*[-*]?\s*(\d+)[\).:：、]\s*(.+?)\s*$"),
    ]
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        for pattern in patterns:
            match = pattern.match(stripped)
            if not match:
                continue
            option_id, label = match.groups()
            clean_label = _strip_markdown(label)
            if clean_label and not any(option["id"].lower() == option_id.lower() for option in options):
                options.append({"id": option_id, "label": clean_label[:160], "value": option_id})
            break
    return options[:8]


def _looks_like_choice_request(output: str) -> bool:
    normalized = " ".join(output.lower().split())
    patterns = [
        "choose",
        "which approach",
        "which option",
        "select",
        "你选哪个",
        "选择",
        "倾向哪个",
        "哪种",
        "哪个",
    ]
    return any(pattern in normalized for pattern in patterns)


def _looks_like_text_request(output: str) -> bool:
    normalized = " ".join(output.lower().split())
    patterns = [
        "please choose",
        "please provide",
        "please let me know",
        "if you approve",
        "prefer another",
        "provide more",
        "need more information",
        "could you provide",
        "tell me more",
        "请提供",
        "补充",
        "更多信息",
    ]
    return any(pattern in normalized for pattern in patterns)


def _choice_prompt(output: str, options: list[dict[str, str]]) -> str:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    option_ids = {option["id"].lower() for option in options}
    prompt_lines = []
    for line in lines:
        if re.match(r"^\s*[-*]?\s*(?:\*\*)?([A-Z]|\d+)(?:\*\*)?[\).:：、]", line):
            continue
        prompt_lines.append(_strip_markdown(line))
    return _short_prompt("\n".join(prompt_lines) or output)


def _short_prompt(output: str) -> str:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    text = "\n".join(lines[-4:] if len(lines) > 4 else lines)
    return text[:1000] or output[:1000]


def _strip_markdown(value: str) -> str:
    value = value.strip()
    value = re.sub(r"^\*\*(.*?)\*\*", r"\1", value)
    value = value.replace("**", "").strip()
    return value


def _heuristic_external_id(run_id: str, output: str) -> str:
    digest = sha1(output.encode("utf-8")).hexdigest()[:16]
    return f"heuristic:{run_id}:{digest}"


def _permission_response(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in {"approve", "approved", "allow", "allowed", "yes", "y"}:
        return "allow"
    return "deny"


def _native_answer_message(payload: InteractionRespondRequest) -> str:
    if not payload.answers:
        return payload.response
    return "\n".join(
        f"{index + 1}. {', '.join(answer)}"
        for index, answer in enumerate(payload.answers)
    )


# Local alias to avoid importing the route schema at module import time in older tests.
from app.schemas.interactions import SessionInteractionRead as SessionInteractionReadCompat
