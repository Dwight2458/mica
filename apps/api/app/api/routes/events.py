from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.api.deps import SessionDep
from app.schemas.events import EventRead
from app.services.event_service import EventService, format_sse_event

router = APIRouter()


@router.get("/events", response_model=list[EventRead])
def list_events(session: SessionDep, run_id: str | None = None) -> list[EventRead]:
    events = EventService(session).list_events(run_id=run_id)
    return [EventRead.model_validate(event) for event in events]


@router.get("/events/stream")
def stream_events(session: SessionDep, run_id: str | None = None, replay: bool = False) -> StreamingResponse:
    async def generate() -> AsyncIterator[str]:
        sent_ids: set[str] = set()
        while True:
            session.expire_all()
            events = EventService(session).list_events(run_id=run_id)
            for event in events:
                if event.id in sent_ids:
                    continue
                sent_ids.add(event.id)
                yield format_sse_event(event)
            if replay:
                return
            yield ": heartbeat\n\n"
            await asyncio.sleep(0.5)

    return StreamingResponse(generate(), media_type="text/event-stream")
