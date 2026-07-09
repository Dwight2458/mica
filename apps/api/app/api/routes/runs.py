from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.api.deps import SessionDep
from app.runners.agent_adapters import agent_process_manager
from app.schemas.runs import RunRecordCreate, RunRecordRead, RunSummary
from app.services.run_service import RunService

router = APIRouter()


@router.post("/runs", response_model=RunRecordRead, status_code=status.HTTP_201_CREATED)
def create_run(payload: RunRecordCreate, session: SessionDep) -> RunRecordRead:
    run = RunService(session).create(payload)
    return RunRecordRead.model_validate(run)


@router.get("/runs", response_model=list[RunRecordRead])
def list_runs(session: SessionDep) -> list[RunRecordRead]:
    service = RunService(session)
    service.mark_orphaned_started_runs(active_run_ids=agent_process_manager.active_run_ids())
    runs = service.list_runs()
    return [RunRecordRead.model_validate(run) for run in runs]


@router.get("/runs/{run_id}", response_model=RunRecordRead)
def get_run(run_id: str, session: SessionDep) -> RunRecordRead:
    service = RunService(session)
    service.mark_orphaned_started_runs(active_run_ids=agent_process_manager.active_run_ids())
    run = service.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return RunRecordRead.model_validate(run)


@router.patch("/runs/{run_id}/finish", response_model=RunRecordRead)
def finish_run(run_id: str, session: SessionDep) -> RunRecordRead:
    run = RunService(session).finish(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return RunRecordRead.model_validate(run)


@router.get("/runs/{run_id}/summary", response_model=RunSummary)
def get_run_summary(run_id: str, session: SessionDep) -> RunSummary:
    summary = RunService(session).summary(run_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return summary
