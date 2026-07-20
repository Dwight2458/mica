from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import InteractionKind, InteractionSource, InteractionStatus
from app.schemas.runs import RunRecordRead
from app.schemas.sessions import AgentSessionRead, SessionMessageRead


class InteractionOption(BaseModel):
    id: str
    label: str
    value: str


class SessionInteractionCreate(BaseModel):
    session_id: str
    run_id: str | None = None
    adapter: str
    kind: InteractionKind
    source: InteractionSource
    prompt: str = Field(min_length=1)
    options: list[dict[str, Any]] = Field(default_factory=list)
    external_id: str | None = None


class SessionInteractionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    session_id: str
    run_id: str | None
    adapter: str
    kind: InteractionKind
    source: InteractionSource
    prompt: str
    options: list[dict[str, Any]]
    status: InteractionStatus
    external_id: str | None
    response_payload: dict[str, Any] | None
    created_at: datetime
    resolved_at: datetime | None


class InteractionRespondRequest(BaseModel):
    response: str = Field(min_length=1)
    option_id: str | None = None
    answers: list[list[str]] | None = None
    remember: bool = False


class InteractionDismissRequest(BaseModel):
    reason: str | None = None


class InteractionRespondRead(BaseModel):
    interaction: SessionInteractionRead
    session: AgentSessionRead | None = None
    run: RunRecordRead | None = None
    message: SessionMessageRead | None = None
    planned_command: list[str] = Field(default_factory=list)
    action: Literal["continued_session", "responded_permission", "responded_native_interaction", "dismissed"]
