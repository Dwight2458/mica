from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.enums import ApprovalStatus


class CommandApprovalCreate(BaseModel):
    tool: str
    argv: list[str]
    command_line: str
    cwd: str
    risk_level: str
    reason: str


class CommandApprovalRead(CommandApprovalCreate):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: ApprovalStatus
    created_at: datetime
    resolved_at: datetime | None
    resolved_by: str | None
    comment: str | None


class ApprovalDecision(BaseModel):
    decision: ApprovalStatus
    resolved_by: str = "local-user"
    comment: str | None = None
