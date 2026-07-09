from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import AgentSessionStatus, SessionMessageRole
from app.schemas.runs import RunRecordRead


class AgentSessionCreate(BaseModel):
    prompt: str = Field(min_length=1)
    workspace: str = Field(min_length=1)
    agent_type: str = "mock-agent"
    runner_mode: str = "local"
    title: str | None = None


class SessionContinueRequest(BaseModel):
    message: str = Field(min_length=1)


class AgentSessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    workspace: str
    agent_type: str
    runner_mode: str
    status: AgentSessionStatus
    created_at: datetime
    updated_at: datetime
    last_run_id: str | None
    external_session_id: str | None
    transport: str | None
    backend_url: str | None
    summary: str | None


class SessionMessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    session_id: str
    run_id: str | None
    role: SessionMessageRole
    content: str
    message_metadata: dict[str, object]
    created_at: datetime


class SessionContinueRead(BaseModel):
    session: AgentSessionRead
    run: RunRecordRead
    message: SessionMessageRead
    planned_command: list[str]
