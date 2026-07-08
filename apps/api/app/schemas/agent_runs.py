from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.runs import RunRecordRead


class AgentRunCreate(BaseModel):
    prompt: str = Field(min_length=1)
    workspace: str = Field(min_length=1)
    agent_type: str = "mock-agent"
    runner_mode: str = "local"


class AgentRunRead(BaseModel):
    run: RunRecordRead
    prompt: str
    agent_type: str
    runner_mode: str
    planned_command: list[str]


class AgentAvailabilityRead(BaseModel):
    agent_type: str
    available: bool
    executable: str | None = None
    reason: str | None = None


class AgentListRead(BaseModel):
    agents: list[AgentAvailabilityRead]
