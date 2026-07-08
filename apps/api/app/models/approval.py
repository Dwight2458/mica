from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import DateTime, Enum as SAEnum, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import ApprovalStatus


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CommandApproval(Base):
    __tablename__ = "command_approvals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    tool: Mapped[str] = mapped_column(String(80), index=True)
    argv: Mapped[list[str]] = mapped_column(JSON)
    command_line: Mapped[str] = mapped_column(Text)
    cwd: Mapped[str] = mapped_column(String(1024))
    risk_level: Mapped[str] = mapped_column(String(40))
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[ApprovalStatus] = mapped_column(
        SAEnum(ApprovalStatus, native_enum=False),
        default=ApprovalStatus.PENDING,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
