from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from app.api.deps import SessionDep
from app.runners.agent_adapters import list_agent_availability
from app.schemas.agent_runs import AgentAvailabilityRead, AgentListRead, AgentRunCreate, AgentRunRead
from app.schemas.runs import RunRecordRead
from app.services.agent_run_service import AgentRunService

router = APIRouter()


@router.get("/agent-runs/agents", response_model=AgentListRead)
def list_agents() -> AgentListRead:
    return AgentListRead(
        agents=[AgentAvailabilityRead(**availability.__dict__) for availability in list_agent_availability()]
    )


@router.post("/agent-runs", response_model=AgentRunRead, status_code=status.HTTP_201_CREATED)
def start_agent_run(payload: AgentRunCreate, session: SessionDep, request: Request) -> AgentRunRead:
    try:
        result = AgentRunService(session).start(payload, request.app.state.database.session_factory)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return AgentRunRead(
        run=RunRecordRead.model_validate(result.run),
        prompt=result.prompt,
        agent_type=result.agent_type,
        runner_mode=result.runner_mode,
        planned_command=result.planned_command,
    )


@router.post("/agent-runs/{run_id}/cancel", response_model=RunRecordRead)
def cancel_agent_run(run_id: str, session: SessionDep, request: Request) -> RunRecordRead:
    try:
        run = AgentRunService(session).cancel(
            run_id,
            session_factory=request.app.state.database.session_factory,
        )
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return RunRecordRead.model_validate(run)
