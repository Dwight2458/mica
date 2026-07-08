from __future__ import annotations

import subprocess
from dataclasses import dataclass

from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm import Session

from app.models.enums import CommandStatus, EventType
from app.models.run import RunRecord
from app.runners.agent_adapters import agent_process_manager, get_adapter
from app.schemas.agent_runs import AgentRunCreate
from app.schemas.commands import CommandRecordCreate
from app.schemas.events import EventCreate
from app.schemas.runs import RunRecordCreate
from app.services.command_service import CommandService
from app.services.event_service import EventService
from app.services.run_service import RunService


@dataclass(frozen=True)
class AgentRunResult:
    run: RunRecord
    prompt: str
    agent_type: str
    runner_mode: str
    planned_command: list[str]


class AgentRunService:
    """Creates a natural-language Agent Run.

    The first implementation is intentionally a deterministic mock agent. It proves
    the product shape: prompt in, run/plan/command/trace out. Real CLI adapters can
    replace the planner/executor without changing the Web entrypoint.
    """

    def __init__(self, session: Session) -> None:
        self.session = session

    def start(self, payload: AgentRunCreate, session_factory: sessionmaker | None = None) -> AgentRunResult:
        adapter = get_adapter(payload.agent_type)
        executable = adapter.find_executable()
        planned_command = adapter.build_command(executable, payload.prompt, payload.workspace)
        run = RunService(self.session).create(RunRecordCreate(source=payload.agent_type, cwd=payload.workspace))
        self._record_agent_prompt(run.id, payload)
        self._record_plan(run.id, planned_command)
        if payload.agent_type != "mock-agent":
            if session_factory is None:
                raise ValueError("session_factory is required for real agent runs.")
            agent_process_manager.start(
                run_id=run.id,
                adapter=adapter,
                command=planned_command,
                workspace=payload.workspace,
                session_factory=session_factory,
            )
            self.session.refresh(run)
            return AgentRunResult(
                run=run,
                prompt=payload.prompt,
                agent_type=payload.agent_type,
                runner_mode=payload.runner_mode,
                planned_command=planned_command,
            )

        command = CommandService(self.session).create(
            CommandRecordCreate(
                run_id=run.id,
                tool=planned_command[0],
                argv=planned_command[1:],
                command_line=subprocess.list2cmdline(planned_command),
                cwd=payload.workspace,
                risk_level="low",
                requires_approval=False,
                approval_id=None,
            )
        )
        EventService(self.session).create(
            EventCreate(
                run_id=run.id,
                command_id=command.id,
                event_type=EventType.COMMAND_OUTPUT,
                message=f"Mock agent output for {command.command_line}.",
                payload={
                    "command_line": command.command_line,
                    "stream": "stdout",
                    "text": f"mock-agent planned and completed: {command.command_line}\n",
                },
            )
        )
        self.session.commit()
        CommandService(self.session).finish(command.id, status=CommandStatus.COMPLETED, exit_code=0, duration_ms=1)
        finished_run = RunService(self.session).finish(run.id)
        if finished_run is None:
            raise RuntimeError("Agent run could not be finalized.")
        return AgentRunResult(
            run=finished_run,
            prompt=payload.prompt,
            agent_type=payload.agent_type,
            runner_mode=payload.runner_mode,
            planned_command=planned_command,
        )

    def _record_agent_prompt(self, run_id: str, payload: AgentRunCreate) -> None:
        EventService(self.session).create(
            EventCreate(
                run_id=run_id,
                event_type=EventType.AGENT_PROMPT,
                message="Agent prompt received.",
                payload={
                    "prompt": payload.prompt,
                    "agent_type": payload.agent_type,
                    "runner_mode": payload.runner_mode,
                    "workspace": payload.workspace,
                },
            )
        )
        self.session.commit()

    def _record_plan(self, run_id: str, planned_command: list[str]) -> None:
        EventService(self.session).create(
            EventCreate(
                run_id=run_id,
                event_type=EventType.PLAN_CREATED,
                message="Mock agent plan created.",
                payload={"planned_command": planned_command},
            )
        )
        self.session.commit()
