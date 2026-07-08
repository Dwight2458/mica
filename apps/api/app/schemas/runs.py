from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.enums import RunStatus


class RunRecordCreate(BaseModel):
    source: str = "manual"
    cwd: str


class RunRecordRead(RunRecordCreate):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: RunStatus
    started_at: datetime
    finished_at: datetime | None


class FailureSummary(BaseModel):
    failed_command: str
    exit_code: int | None
    reason: str
    suggested_next_action: str


class RunSummary(BaseModel):
    run_id: str
    source: str
    status: RunStatus
    cwd: str
    total_commands: int
    agent_tool_commands: int = 0
    runtime_internal_commands: int = 0
    successful_commands: int
    failed_commands: int
    approval_count: int
    rejected_count: int
    risky_command_count: int
    total_duration_ms: int
    failure_summary: FailureSummary | None
