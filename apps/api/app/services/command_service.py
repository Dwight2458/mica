from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.approval import utcnow
from app.models.command import CommandRecord
from app.models.enums import CommandStatus, EventType
from app.models.run import RunRecord
from app.schemas.commands import CommandRecordCreate
from app.schemas.events import EventCreate
from app.services.event_service import EventService


class CommandService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, payload: CommandRecordCreate) -> CommandRecord:
        status = CommandStatus.WAITING_APPROVAL if payload.requires_approval else CommandStatus.STARTED
        data = payload.model_dump()
        data["command_origin"] = self._classify_origin(payload)
        record = CommandRecord(**data, status=status)
        self.session.add(record)
        self.session.flush()
        if record.requires_approval:
            EventService(self.session).create(
                EventCreate(
                    run_id=record.run_id,
                    command_id=record.id,
                    approval_id=record.approval_id,
                    event_type=EventType.APPROVAL_REQUIRED,
                    message=f"Approval required for {record.command_line}.",
                    payload={
                        "command_line": record.command_line,
                        "reason": "Command matched a require_approval policy rule.",
                        "risk_level": record.risk_level,
                        "command_origin": record.command_origin,
                    },
                )
            )
        else:
            EventService(self.session).create(
                EventCreate(
                    run_id=record.run_id,
                    command_id=record.id,
                event_type=EventType.COMMAND_STARTED,
                message=f"Command started: {record.command_line}",
                payload={
                    "command_line": record.command_line,
                    "risk_level": record.risk_level,
                    "command_origin": record.command_origin,
                },
            )
            )
        self.session.commit()
        self.session.refresh(record)
        return record

    def list_records(self, *, run_id: str | None = None) -> list[CommandRecord]:
        statement = select(CommandRecord).order_by(CommandRecord.started_at.desc())
        if run_id is not None:
            statement = select(CommandRecord).where(CommandRecord.run_id == run_id).order_by(CommandRecord.started_at.asc())
        return list(self.session.scalars(statement))

    def get(self, record_id: str) -> CommandRecord | None:
        return self.session.get(CommandRecord, record_id)

    def finish(self, record_id: str, *, status: CommandStatus, exit_code: int, duration_ms: int) -> CommandRecord | None:
        record = self.get(record_id)
        if record is None:
            return None
        record.status = status
        record.exit_code = exit_code
        record.duration_ms = duration_ms
        record.finished_at = utcnow()
        self.session.add(record)
        EventService(self.session).create(
            EventCreate(
                run_id=record.run_id,
                command_id=record.id,
                approval_id=record.approval_id,
                event_type=EventType.COMMAND_FINISHED,
                message=f"Command finished: {record.command_line}",
                payload={
                    "command_line": record.command_line,
                    "duration_ms": duration_ms,
                    "exit_code": exit_code,
                    "status": status.value,
                    "command_origin": record.command_origin,
                },
            )
        )
        self.session.commit()
        self.session.refresh(record)
        return record

    def mark_agent_tool_command(self, run_id: str, command_line: str) -> CommandRecord | None:
        marked: CommandRecord | None = None
        for candidate in _agent_tool_command_candidates(command_line):
            record = self._find_matching_command(run_id, candidate)
            if record is None:
                continue
            record.command_origin = "agent_tool"
            self.session.add(record)
            marked = record
        self.session.commit()
        if marked is not None:
            self.session.refresh(marked)
        return marked

    def record_agent_tool_event(
        self,
        run_id: str,
        *,
        command_line: str,
        cwd: str,
        status: CommandStatus | None,
        exit_code: int | None,
        duration_ms: int = 0,
    ) -> CommandRecord | None:
        marked = self.mark_agent_tool_command(run_id, command_line)
        if marked is not None:
            if status in {CommandStatus.COMPLETED, CommandStatus.FAILED} and marked.finished_at is None:
                return self.finish(
                    marked.id,
                    status=status,
                    exit_code=exit_code if exit_code is not None else (0 if status == CommandStatus.COMPLETED else -1),
                    duration_ms=duration_ms,
                )
            return marked

        record = self._find_synthetic_agent_tool_command(run_id, command_line)
        if record is None:
            tool, argv = _split_command_line(command_line)
            record = self.create(
                CommandRecordCreate(
                    run_id=run_id,
                    tool=tool,
                    argv=argv,
                    command_line=command_line,
                    cwd=cwd,
                    command_origin="agent_tool",
                    risk_level="low",
                    requires_approval=False,
                    approval_id=None,
                )
            )

        if status in {CommandStatus.COMPLETED, CommandStatus.FAILED} and record.finished_at is None:
            finished = self.finish(
                record.id,
                status=status,
                exit_code=exit_code if exit_code is not None else (0 if status == CommandStatus.COMPLETED else -1),
                duration_ms=duration_ms,
            )
            return finished
        return record

    def _find_matching_command(self, run_id: str, command_line: str) -> CommandRecord | None:
        exact_statement = (
            select(CommandRecord)
            .where(CommandRecord.run_id == run_id, CommandRecord.command_line == command_line)
            .order_by(CommandRecord.started_at.desc())
            .limit(1)
        )
        exact = self.session.scalars(exact_statement).first()
        if exact is not None:
            return exact

        normalized = _normalize_for_agent_match(command_line)
        statement = select(CommandRecord).where(CommandRecord.run_id == run_id).order_by(CommandRecord.started_at.desc())
        for record in self.session.scalars(statement):
            if _normalize_for_agent_match(record.command_line) == normalized:
                return record
        return None

    def _find_synthetic_agent_tool_command(self, run_id: str, command_line: str) -> CommandRecord | None:
        normalized = _normalize_for_agent_match(command_line)
        statement = (
            select(CommandRecord)
            .where(CommandRecord.run_id == run_id, CommandRecord.command_origin == "agent_tool")
            .order_by(CommandRecord.started_at.desc())
        )
        for record in self.session.scalars(statement):
            if _normalize_for_agent_match(record.command_line) == normalized:
                return record
        return None

    def _classify_origin(self, payload: CommandRecordCreate) -> str:
        if payload.command_origin != "external_binary":
            return payload.command_origin
        if payload.run_id is None:
            return payload.command_origin
        run = self.session.get(RunRecord, payload.run_id)
        if run is None:
            return payload.command_origin
        if _is_agent_runtime_command(run.source, payload.command_line):
            return "runtime_internal"
        return payload.command_origin


def _is_agent_runtime_command(source: str, command_line: str) -> bool:
    normalized = " ".join(command_line.lower().split())
    if source not in {"opencode", "antigravity-cli"}:
        return False
    if ".local\\share\\opencode\\snapshot" in normalized or ".local/share/opencode/snapshot" in normalized:
        return True
    if source == "opencode" and normalized in {"git init", "git worktree list --porcelain"}:
        return True
    if source == "opencode" and (
        " check-ignore " in normalized
        or " diff-files " in normalized
        or " ls-files " in normalized
        or " write-tree" in normalized
        or " diff --" in normalized
        or " add --all" in normalized
    ):
        return True
    runtime_prefixes = (
        "git rev-parse",
        "git remote get-url",
        "git rev-list",
        "git --no-optional-locks",
        "git merge-base",
    )
    return normalized.startswith(runtime_prefixes)


def _agent_tool_command_candidates(command_line: str) -> list[str]:
    candidates: list[str] = []
    for candidate in [command_line, *re.split(r"\s*(?:;|&&|\|\|)\s*", command_line)]:
        normalized = candidate.strip()
        if normalized and normalized not in candidates:
            candidates.append(normalized)
    return candidates


def _normalize_for_agent_match(command_line: str) -> str:
    return " ".join(command_line.replace('"', "'").split())


def _split_command_line(command_line: str) -> tuple[str, list[str]]:
    stripped = command_line.strip()
    if not stripped:
        return "unknown", []
    if stripped[0] in {"'", '"'}:
        quote = stripped[0]
        end = stripped.find(quote, 1)
        if end > 0:
            tool = stripped[1:end]
            rest = stripped[end + 1 :].strip()
            return tool, rest.split() if rest else []
    parts = stripped.split()
    return parts[0], parts[1:]
