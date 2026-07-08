from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

import json

from app.models.approval import utcnow
from app.models.event import EventRecord
from app.schemas.events import EventCreate


class EventService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, payload: EventCreate) -> EventRecord:
        event = EventRecord(**payload.model_dump(), created_at=self._next_created_at())
        self.session.add(event)
        self.session.flush()
        return event

    def list_events(self, *, run_id: str | None = None) -> list[EventRecord]:
        statement = select(EventRecord).order_by(EventRecord.created_at.asc(), EventRecord.id.asc())
        if run_id is not None:
            statement = statement.where(EventRecord.run_id == run_id)
        return list(self.session.scalars(statement))

    def _next_created_at(self) -> datetime:
        now = utcnow()
        latest = self.session.scalar(select(EventRecord.created_at).order_by(EventRecord.created_at.desc()).limit(1))
        if latest is None:
            return now
        comparable_now = _as_utc_naive(now)
        comparable_latest = _as_utc_naive(latest)
        if comparable_latest >= comparable_now:
            return comparable_latest.replace(tzinfo=timezone.utc) + timedelta(microseconds=1)
        return now


def format_sse_event(event: EventRecord) -> str:
    payload = {
        "id": event.id,
        "run_id": event.run_id,
        "command_id": event.command_id,
        "approval_id": event.approval_id,
        "event_type": event.event_type.value,
        "message": event.message,
        "payload": event.payload,
        "created_at": event.created_at.isoformat(),
    }
    data = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    return f"id: {event.id}\nevent: {event.event_type.value}\ndata: {data}\n\n"


def _as_utc_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)
