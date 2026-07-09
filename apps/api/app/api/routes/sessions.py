from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from app.api.deps import SessionDep
from app.schemas.runs import RunRecordRead
from app.schemas.sessions import (
    AgentSessionCreate,
    AgentSessionRead,
    SessionContinueRead,
    SessionContinueRequest,
    SessionMessageRead,
)
from app.services.session_service import SessionService

router = APIRouter()


@router.post("/sessions", response_model=SessionContinueRead, status_code=status.HTTP_201_CREATED)
def create_session(payload: AgentSessionCreate, session: SessionDep, request: Request) -> SessionContinueRead:
    try:
        result = SessionService(session).create(payload, request.app.state.database.session_factory)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return SessionContinueRead(
        session=AgentSessionRead.model_validate(result.session),
        run=RunRecordRead.model_validate(result.run),
        message=SessionMessageRead.model_validate(result.message),
        planned_command=result.planned_command,
    )


@router.get("/sessions", response_model=list[AgentSessionRead])
def list_sessions(session: SessionDep) -> list[AgentSessionRead]:
    records = SessionService(session).list_sessions()
    return [AgentSessionRead.model_validate(record) for record in records]


@router.get("/sessions/{session_id}", response_model=AgentSessionRead)
def get_session(session_id: str, session: SessionDep) -> AgentSessionRead:
    record = SessionService(session).get(session_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return AgentSessionRead.model_validate(record)


@router.get("/sessions/{session_id}/messages", response_model=list[SessionMessageRead])
def list_session_messages(session_id: str, session: SessionDep) -> list[SessionMessageRead]:
    if SessionService(session).get(session_id) is None:
        raise HTTPException(status_code=404, detail="Session not found")
    messages = SessionService(session).list_messages(session_id)
    return [SessionMessageRead.model_validate(message) for message in messages]


@router.post("/sessions/{session_id}/continue", response_model=SessionContinueRead)
def continue_session(
    session_id: str,
    payload: SessionContinueRequest,
    session: SessionDep,
    request: Request,
) -> SessionContinueRead:
    try:
        result = SessionService(session).continue_session(
            session_id,
            payload,
            request.app.state.database.session_factory,
        )
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return SessionContinueRead(
        session=AgentSessionRead.model_validate(result.session),
        run=RunRecordRead.model_validate(result.run),
        message=SessionMessageRead.model_validate(result.message),
        planned_command=result.planned_command,
    )

