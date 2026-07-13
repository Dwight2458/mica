from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from app.api.deps import SessionDep
from app.models.enums import InteractionStatus
from app.schemas.interactions import (
    InteractionDismissRequest,
    InteractionRespondRead,
    InteractionRespondRequest,
    SessionInteractionRead,
)
from app.services.interaction_service import InteractionService

router = APIRouter()


@router.get("/sessions/{session_id}/interactions", response_model=list[SessionInteractionRead])
def list_session_interactions(
    session_id: str,
    session: SessionDep,
    status: InteractionStatus | None = None,
) -> list[SessionInteractionRead]:
    records = InteractionService(session).list_for_session(session_id, status=status)
    return [SessionInteractionRead.model_validate(record) for record in records]


@router.post("/session-interactions/{interaction_id}/respond", response_model=InteractionRespondRead)
def respond_interaction(
    interaction_id: str,
    payload: InteractionRespondRequest,
    session: SessionDep,
    request: Request,
) -> InteractionRespondRead:
    try:
        result = InteractionService(session).respond(
            interaction_id,
            payload,
            session_factory=request.app.state.database.session_factory,
        )
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Interaction not found")
    return result


@router.post("/session-interactions/{interaction_id}/dismiss", response_model=SessionInteractionRead)
def dismiss_interaction(
    interaction_id: str,
    payload: InteractionDismissRequest,
    session: SessionDep,
) -> SessionInteractionRead:
    record = InteractionService(session).dismiss(interaction_id, reason=payload.reason)
    if record is None:
        raise HTTPException(status_code=404, detail="Interaction not found")
    return SessionInteractionRead.model_validate(record)
