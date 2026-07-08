from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.enums import CommandStatus


class CommandRecordCreate(BaseModel):
    run_id: str | None = None
    tool: str
    argv: list[str]
    command_line: str
    cwd: str
    command_origin: str = "external_binary"
    risk_level: str
    requires_approval: bool
    approval_id: str | None = None


class CommandRecordFinish(BaseModel):
    status: CommandStatus
    exit_code: int
    duration_ms: int


class CommandRecordRead(CommandRecordCreate):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: CommandStatus
    exit_code: int | None
    duration_ms: int | None
    started_at: datetime
    finished_at: datetime | None
