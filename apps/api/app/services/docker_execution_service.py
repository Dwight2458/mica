from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from sqlalchemy.orm import Session

from app.models.command import CommandRecord
from app.models.enums import CommandStatus, EventType
from app.models.run import RunRecord
from app.runners.docker_runner import DockerOutputChunk, DockerRunner, DockerRunResult
from app.schemas.commands import CommandRecordCreate
from app.schemas.events import EventCreate
from app.schemas.runs import RunRecordCreate
from app.services.command_service import CommandService
from app.services.event_service import EventService
from app.services.run_service import RunService


class DockerRunnerProtocol(Protocol):
    def run(
        self,
        *,
        workspace: str | Path,
        command: Sequence[str],
        run_id: str | None = None,
        on_output: object | None = None,
    ) -> DockerRunResult:
        ...


@dataclass(frozen=True)
class DockerExecutionEvidence:
    run: RunRecord
    command: CommandRecord
    result: DockerRunResult


WorkspaceFileSnapshot = dict[str, dict[str, object]]


class DockerExecutionService:
    """Executes a Docker command and records it as Mica run evidence."""

    def __init__(self, session: Session, *, runner: DockerRunnerProtocol | None = None) -> None:
        self.session = session
        self.runner = runner or DockerRunner()

    def execute(
        self,
        *,
        workspace: str | Path,
        command: Sequence[str],
        policy_decision: Mapping[str, Any] | None = None,
    ) -> DockerExecutionEvidence:
        workspace_path = Path(workspace).resolve()
        command_parts = list(command)
        if not command_parts:
            raise ValueError("command must not be empty")
        before_files = self._snapshot_workspace(workspace_path)

        run = RunService(self.session).create(RunRecordCreate(source="docker", cwd=str(workspace_path)))
        command_record = CommandService(self.session).create(
            CommandRecordCreate(
                run_id=run.id,
                tool=command_parts[0],
                argv=command_parts[1:],
                command_line=subprocess.list2cmdline(command_parts),
                cwd=str(workspace_path),
                risk_level="low",
                requires_approval=False,
                approval_id=None,
            )
        )
        if policy_decision is not None:
            self._record_policy_decision(command_record, policy_decision)
        streamed_output = False

        def record_streamed_output(chunk: DockerOutputChunk) -> None:
            nonlocal streamed_output
            streamed_output = True
            self._record_output_chunk(command_record, stream_name=chunk.stream, text=chunk.text)
            self.session.commit()

        result = self.runner.run(
            workspace=workspace_path,
            command=command_parts,
            run_id=run.id,
            on_output=record_streamed_output,
        )
        after_files = self._snapshot_workspace(workspace_path)
        if not streamed_output:
            self._record_output(command_record, result)
        self._record_file_changes(command_record, before=before_files, after=after_files)
        self._record_network_evidence(command_record, result)
        status = CommandStatus.COMPLETED if result.exit_code == 0 else CommandStatus.FAILED
        finished_command = CommandService(self.session).finish(
            command_record.id,
            status=status,
            exit_code=result.exit_code,
            duration_ms=result.duration_ms,
        )
        finished_run = RunService(self.session).finish(run.id)
        if finished_command is None or finished_run is None:
            raise RuntimeError("docker execution evidence could not be finalized")

        return DockerExecutionEvidence(run=finished_run, command=finished_command, result=result)

    def _record_output(self, command_record: CommandRecord, result: DockerRunResult) -> None:
        for stream_name, text in (("stdout", result.stdout), ("stderr", result.stderr)):
            if not text:
                continue
            self._record_output_chunk(command_record, stream_name=stream_name, text=text)

    def _record_output_chunk(self, command_record: CommandRecord, *, stream_name: str, text: str) -> None:
        EventService(self.session).create(
            EventCreate(
                run_id=command_record.run_id,
                command_id=command_record.id,
                event_type=EventType.COMMAND_OUTPUT,
                message=f"{stream_name} output from {command_record.command_line}.",
                payload={
                    "command_line": command_record.command_line,
                    "stream": stream_name,
                    "text": text,
                },
            )
            )

    def _record_policy_decision(self, command_record: CommandRecord, policy_decision: Mapping[str, Any]) -> None:
        EventService(self.session).create(
            EventCreate(
                run_id=command_record.run_id,
                command_id=command_record.id,
                event_type=EventType.POLICY_DECISION,
                message=f"Policy decision for {command_record.command_line}.",
                payload=dict(policy_decision),
            )
        )

    def _record_network_evidence(self, command_record: CommandRecord, result: DockerRunResult) -> None:
        network_access = "disabled" if result.network_mode == "none" else "host-reachable"
        EventService(self.session).create(
            EventCreate(
                run_id=command_record.run_id,
                command_id=command_record.id,
                event_type=EventType.NETWORK_EVIDENCE,
                message=f"Docker network mode: {result.network_mode}.",
                payload={
                    "command_line": command_record.command_line,
                    "network_mode": result.network_mode,
                    "network_access": network_access,
                    "host_callback_required": result.network_mode == "bridge",
                    "boundary": "Network evidence records Docker network mode only; it is not packet capture or a firewall proof.",
                },
            )
        )

    def _snapshot_workspace(self, workspace_path: Path) -> WorkspaceFileSnapshot:
        files: WorkspaceFileSnapshot = {}
        if not workspace_path.exists():
            return files
        for path in sorted(workspace_path.rglob("*")):
            if not path.is_file():
                continue
            relative_path = path.relative_to(workspace_path).as_posix()
            files[relative_path] = {
                "size": path.stat().st_size,
                "sha256": self._sha256(path),
            }
        return files

    def _record_file_changes(
        self,
        command_record: CommandRecord,
        *,
        before: WorkspaceFileSnapshot,
        after: WorkspaceFileSnapshot,
    ) -> None:
        paths = sorted(set(before) | set(after), key=lambda path: (self._change_order(before.get(path), after.get(path)), path))
        for relative_path in paths:
            before_file = before.get(relative_path)
            after_file = after.get(relative_path)
            if before_file == after_file:
                continue
            if before_file is None:
                change_type = "created"
            elif after_file is None:
                change_type = "deleted"
            else:
                change_type = "modified"
            EventService(self.session).create(
                EventCreate(
                    run_id=command_record.run_id,
                    command_id=command_record.id,
                    event_type=EventType.FILE_CHANGED,
                    message=f"{change_type} {relative_path}.",
                    payload={
                        "command_line": command_record.command_line,
                        "path": relative_path,
                        "change_type": change_type,
                        "before": before_file,
                        "after": after_file,
                    },
                )
            )

    def _change_order(self, before_file: dict[str, object] | None, after_file: dict[str, object] | None) -> int:
        if before_file is None:
            return 0
        if after_file is None:
            return 2
        return 1

    def _sha256(self, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
