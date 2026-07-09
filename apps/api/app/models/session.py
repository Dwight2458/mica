from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, Enum as SAEnum, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.approval import utcnow
from app.models.enums import AgentSessionStatus, SessionMessageRole


class AgentSession(Base):
    __tablename__ = "agent_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    title: Mapped[str] = mapped_column(String(240))
    workspace: Mapped[str] = mapped_column(String(1024))
    agent_type: Mapped[str] = mapped_column(String(80), index=True)
    runner_mode: Mapped[str] = mapped_column(String(40), default="local")
    status: Mapped[AgentSessionStatus] = mapped_column(
        SAEnum(AgentSessionStatus, native_enum=False),
        default=AgentSessionStatus.ACTIVE,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    last_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    external_session_id: Mapped[str | None] = mapped_column(String(240), nullable=True, index=True)
    transport: Mapped[str | None] = mapped_column(String(80), nullable=True)
    backend_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)


class SessionMessage(Base):
    __tablename__ = "session_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    session_id: Mapped[str] = mapped_column(String(36), index=True)
    run_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    role: Mapped[SessionMessageRole] = mapped_column(SAEnum(SessionMessageRole, native_enum=False), index=True)
    content: Mapped[str] = mapped_column(Text)
    message_metadata: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
