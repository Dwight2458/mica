from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, Enum as SAEnum, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.approval import utcnow
from app.models.enums import EventType


class EventRecord(Base):
    __tablename__ = "events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    run_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    command_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    approval_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    event_type: Mapped[EventType] = mapped_column(SAEnum(EventType, native_enum=False), index=True)
    message: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
