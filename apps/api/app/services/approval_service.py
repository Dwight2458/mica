from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.approval import CommandApproval, utcnow
from app.models.command import CommandRecord
from app.models.enums import ApprovalStatus, EventType
from app.schemas.approvals import CommandApprovalCreate
from app.schemas.events import EventCreate
from app.services.event_service import EventService


class ApprovalService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, payload: CommandApprovalCreate) -> CommandApproval:
        approval = CommandApproval(**payload.model_dump())
        self.session.add(approval)
        self.session.commit()
        self.session.refresh(approval)
        return approval

    def list_approvals(self, status: ApprovalStatus | None = None) -> list[CommandApproval]:
        statement = select(CommandApproval).order_by(CommandApproval.created_at.desc())
        if status is not None:
            statement = statement.where(CommandApproval.status == status)
        return list(self.session.scalars(statement))

    def get(self, approval_id: str) -> CommandApproval | None:
        return self.session.get(CommandApproval, approval_id)

    def decide(
        self,
        approval_id: str,
        *,
        decision: ApprovalStatus,
        resolved_by: str,
        comment: str | None,
    ) -> CommandApproval | None:
        approval = self.get(approval_id)
        if approval is None:
            return None
        approval.status = decision
        approval.resolved_at = utcnow()
        approval.resolved_by = resolved_by
        approval.comment = comment
        self.session.add(approval)
        command = self._command_for_approval(approval_id)
        EventService(self.session).create(
            EventCreate(
                run_id=command.run_id if command else None,
                command_id=command.id if command else None,
                approval_id=approval.id,
                event_type=EventType.APPROVAL_APPROVED
                if decision == ApprovalStatus.APPROVED
                else EventType.APPROVAL_REJECTED,
                message=f"Approval {decision.value}: {approval.command_line}",
                payload={"comment": comment, "resolved_by": resolved_by},
            )
        )
        self.session.commit()
        self.session.refresh(approval)
        return approval

    def _command_for_approval(self, approval_id: str) -> CommandRecord | None:
        statement = select(CommandRecord).where(CommandRecord.approval_id == approval_id)
        return self.session.scalars(statement).first()
