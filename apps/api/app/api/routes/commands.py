from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.api.deps import SessionDep
from app.schemas.commands import CommandRecordCreate, CommandRecordFinish, CommandRecordRead
from app.services.command_service import CommandService

router = APIRouter()


@router.post("/commands", response_model=CommandRecordRead, status_code=status.HTTP_201_CREATED)
def create_command(payload: CommandRecordCreate, session: SessionDep) -> CommandRecordRead:
    record = CommandService(session).create(payload)
    return CommandRecordRead.model_validate(record)


@router.get("/commands", response_model=list[CommandRecordRead])
def list_commands(session: SessionDep, run_id: str | None = None) -> list[CommandRecordRead]:
    records = CommandService(session).list_records(run_id=run_id)
    return [CommandRecordRead.model_validate(record) for record in records]


@router.get("/commands/{record_id}", response_model=CommandRecordRead)
def get_command(record_id: str, session: SessionDep) -> CommandRecordRead:
    record = CommandService(session).get(record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Command record not found")
    return CommandRecordRead.model_validate(record)


@router.patch("/commands/{record_id}/finish", response_model=CommandRecordRead)
def finish_command(record_id: str, payload: CommandRecordFinish, session: SessionDep) -> CommandRecordRead:
    record = CommandService(session).finish(
        record_id,
        status=payload.status,
        exit_code=payload.exit_code,
        duration_ms=payload.duration_ms,
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Command record not found")
    return CommandRecordRead.model_validate(record)
