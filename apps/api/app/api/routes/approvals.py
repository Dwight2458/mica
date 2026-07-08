from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.api.deps import SessionDep
from app.models.enums import ApprovalStatus
from app.schemas.approvals import ApprovalDecision, CommandApprovalCreate, CommandApprovalRead
from app.services.approval_service import ApprovalService

router = APIRouter()


@router.post("/approvals", response_model=CommandApprovalRead, status_code=status.HTTP_201_CREATED)
def create_approval(payload: CommandApprovalCreate, session: SessionDep) -> CommandApprovalRead:
    approval = ApprovalService(session).create(payload)
    return CommandApprovalRead.model_validate(approval)


@router.get("/approvals", response_model=list[CommandApprovalRead])
def list_approvals(session: SessionDep, status: ApprovalStatus | None = None) -> list[CommandApprovalRead]:
    approvals = ApprovalService(session).list_approvals(status)
    return [CommandApprovalRead.model_validate(approval) for approval in approvals]


@router.get("/approvals/{approval_id}", response_model=CommandApprovalRead)
def get_approval(approval_id: str, session: SessionDep) -> CommandApprovalRead:
    approval = ApprovalService(session).get(approval_id)
    if approval is None:
        raise HTTPException(status_code=404, detail="Approval not found")
    return CommandApprovalRead.model_validate(approval)


@router.post("/approvals/{approval_id}/decide", response_model=CommandApprovalRead)
def decide_approval(approval_id: str, payload: ApprovalDecision, session: SessionDep) -> CommandApprovalRead:
    if payload.decision == ApprovalStatus.PENDING:
        raise HTTPException(status_code=422, detail="Decision must be approved or rejected")
    approval = ApprovalService(session).decide(
        approval_id,
        decision=payload.decision,
        resolved_by=payload.resolved_by,
        comment=payload.comment,
    )
    if approval is None:
        raise HTTPException(status_code=404, detail="Approval not found")
    return CommandApprovalRead.model_validate(approval)
