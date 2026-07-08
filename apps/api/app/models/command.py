from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Enum as SAEnum, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.approval import utcnow
from app.models.enums import CommandStatus


class CommandRecord(Base):
    __tablename__ = "command_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    run_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    tool: Mapped[str] = mapped_column(String(80), index=True)
    argv: Mapped[list[str]] = mapped_column(JSON)
    command_line: Mapped[str] = mapped_column(Text)
    cwd: Mapped[str] = mapped_column(String(1024))
    command_origin: Mapped[str] = mapped_column(String(40), default="external_binary", index=True)
    risk_level: Mapped[str] = mapped_column(String(40))
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    approval_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    status: Mapped[CommandStatus] = mapped_column(
        SAEnum(CommandStatus, native_enum=False),
        default=CommandStatus.STARTED,
        index=True,
    )
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
