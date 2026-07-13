from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, Enum as SAEnum, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.approval import utcnow
from app.models.enums import InteractionKind, InteractionSource, InteractionStatus


class SessionInteraction(Base):
    __tablename__ = "session_interactions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    session_id: Mapped[str] = mapped_column(String(36), index=True)
    run_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    adapter: Mapped[str] = mapped_column(String(80), index=True)
    kind: Mapped[InteractionKind] = mapped_column(SAEnum(InteractionKind, native_enum=False), index=True)
    source: Mapped[InteractionSource] = mapped_column(SAEnum(InteractionSource, native_enum=False), index=True)
    prompt: Mapped[str] = mapped_column(Text)
    options: Mapped[list[dict[str, object]]] = mapped_column(JSON, default=list)
    status: Mapped[InteractionStatus] = mapped_column(
        SAEnum(InteractionStatus, native_enum=False),
        default=InteractionStatus.PENDING,
        index=True,
    )
    external_id: Mapped[str | None] = mapped_column(String(240), nullable=True, index=True)
    response_payload: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
