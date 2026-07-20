from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.approval import utcnow
from app.models.command import CommandRecord
from app.models.enums import CommandStatus, EventType, RunStatus
from app.models.run import RunRecord
from app.models.session import AgentSession
from app.schemas.events import EventCreate
from app.schemas.runs import FailureSummary, RunRecordCreate, RunSummary
from app.services.event_service import EventService


FAILED_COMMAND_STATUSES = {CommandStatus.FAILED, CommandStatus.REJECTED, CommandStatus.TIMEOUT}


class RunService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, payload: RunRecordCreate) -> RunRecord:
        run = RunRecord(**payload.model_dump(), started_at=self._next_started_at())
        self.session.add(run)
        self.session.flush()
        EventService(self.session).create(
            EventCreate(
                run_id=run.id,
                event_type=EventType.RUN_CREATED,
                message=f"Run created from {run.source}.",
                payload={"source": run.source, "cwd": run.cwd},
            )
        )
        self.session.commit()
        self.session.refresh(run)
        return run

    def list_runs(self) -> list[RunRecord]:
        statement = select(RunRecord).order_by(RunRecord.started_at.desc())
        return list(self.session.scalars(statement))

    def mark_orphaned_started_runs(
        self,
        *,
        active_run_ids: set[str],
        max_age: timedelta = timedelta(minutes=60),
    ) -> list[RunRecord]:
        now = _as_utc_naive(utcnow())
        cutoff = now - max_age
        statement = select(RunRecord).where(RunRecord.status == RunStatus.STARTED)
        marked: list[RunRecord] = []
        for run in self.session.scalars(statement):
            if run.id in active_run_ids:
                continue
            if run.session_id:
                agent_session = self.session.get(AgentSession, run.session_id)
                if agent_session is not None and agent_session.transport in {"http", "app-server-stdio"}:
                    continue
            if _as_utc_naive(run.started_at) > cutoff:
                continue
            run.status = RunStatus.FAILED
            run.finished_at = utcnow()
            self.session.add(run)
            EventService(self.session).create(
                EventCreate(
                    run_id=run.id,
                    event_type=EventType.RUN_FAILED,
                    message="Run failed because the agent process is no longer active.",
                    payload={"status": "failed", "reason": "orphaned_agent_process"},
                )
            )
            marked.append(run)
        if marked:
            self.session.commit()
            for run in marked:
                self.session.refresh(run)
        return marked

    def get(self, run_id: str) -> RunRecord | None:
        return self.session.get(RunRecord, run_id)

    def finish(self, run_id: str) -> RunRecord | None:
        run = self.get(run_id)
        if run is None:
            return None
        commands = self.commands_for_run(run_id)
        status = RunStatus.FAILED if self._failed_commands(commands) else RunStatus.COMPLETED
        return self.finish_with_status(run_id, status=status)

    def finish_with_status(self, run_id: str, *, status: RunStatus) -> RunRecord | None:
        run = self.get(run_id)
        if run is None:
            return None
        if run.finished_at is not None:
            return run
        commands = self.commands_for_run(run_id)
        if status == RunStatus.COMPLETED and self._blocking_failed_commands(commands):
            status = RunStatus.FAILED
        run.status = status
        run.finished_at = utcnow()
        self.session.add(run)
        EventService(self.session).create(
            EventCreate(
                run_id=run.id,
                event_type=EventType.RUN_FAILED
                if run.status in {RunStatus.FAILED, RunStatus.CANCELLED}
                else EventType.RUN_COMPLETED,
                message=f"Run {run.status.value}.",
                payload={"status": run.status.value},
            )
        )
        self.session.commit()
        self.session.refresh(run)
        return run

    def commands_for_run(self, run_id: str) -> list[CommandRecord]:
        statement = select(CommandRecord).where(CommandRecord.run_id == run_id).order_by(CommandRecord.started_at.asc())
        return list(self.session.scalars(statement))

    def summary(self, run_id: str) -> RunSummary | None:
        run = self.get(run_id)
        if run is None:
            return None
        commands = self.commands_for_run(run_id)
        governed_commands = [command for command in commands if command.command_origin != "runtime_internal"]
        failed_commands = self._failed_commands(commands)
        failure = failed_commands[0] if run.status in {RunStatus.FAILED, RunStatus.CANCELLED} and failed_commands else None
        return RunSummary(
            run_id=run.id,
            source=run.source,
            status=run.status,
            cwd=run.cwd,
            total_commands=len(commands),
            agent_tool_commands=sum(1 for command in commands if command.command_origin == "agent_tool"),
            runtime_internal_commands=sum(1 for command in commands if command.command_origin == "runtime_internal"),
            governed_commands=len(governed_commands),
            successful_governed_commands=sum(
                1 for command in governed_commands if command.status == CommandStatus.COMPLETED
            ),
            successful_commands=sum(1 for command in commands if command.status == CommandStatus.COMPLETED),
            failed_commands=len(failed_commands),
            approval_count=sum(1 for command in commands if command.approval_id is not None),
            rejected_count=sum(1 for command in commands if command.status == CommandStatus.REJECTED),
            risky_command_count=sum(1 for command in commands if command.requires_approval),
            total_duration_ms=sum(command.duration_ms or 0 for command in commands),
            failure_summary=self._failure_summary(failure),
        )

    def _failed_commands(self, commands: list[CommandRecord]) -> list[CommandRecord]:
        return [
            command
            for command in commands
            if command.status in FAILED_COMMAND_STATUSES
            and (command.command_origin != "runtime_internal" or command.requires_approval)
        ]

    def _blocking_failed_commands(self, commands: list[CommandRecord]) -> list[CommandRecord]:
        return [
            command
            for command in self._failed_commands(commands)
            if command.requires_approval or command.status in {CommandStatus.REJECTED, CommandStatus.TIMEOUT}
        ]

    def _failure_summary(self, command: CommandRecord | None) -> FailureSummary | None:
        if command is None:
            return None
        return FailureSummary(
            failed_command=command.command_line,
            exit_code=command.exit_code,
            reason="Command was rejected or failed.",
            suggested_next_action="Review the command, approval decision, and agent prompt before retrying.",
        )

    def _next_started_at(self) -> datetime:
        now = utcnow()
        latest = self.session.scalar(select(RunRecord.started_at).order_by(RunRecord.started_at.desc()).limit(1))
        if latest is None:
            return now
        comparable_now = _as_utc_naive(now)
        comparable_latest = _as_utc_naive(latest)
        if comparable_latest >= comparable_now:
            return comparable_latest.replace(tzinfo=timezone.utc) + timedelta(microseconds=1)
        return now


def _as_utc_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)
