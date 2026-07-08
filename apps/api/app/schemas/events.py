from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import EventType


class EventCreate(BaseModel):
    run_id: str | None = None
    command_id: str | None = None
    approval_id: str | None = None
    event_type: EventType
    message: str
    payload: dict[str, Any] = Field(default_factory=dict)


class EventRead(EventCreate):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
