from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from app.db.session import Database
from app.models.enums import EventType, RunStatus
from app.runners.docker_runner import DockerRunResult
from app.services.docker_execution_service import DockerExecutionService
from app.services.event_service import EventService
from app.services.run_service import RunService


class FakeDockerRunner:
    captured_run_id: str | None = None

    def __init__(self, *, network_mode: str = "none") -> None:
        self.network_mode = network_mode

    def run(
        self,
        *,
        workspace: str | Path,
        command: list[str],
        run_id: str | None = None,
        on_output: object | None = None,
    ) -> DockerRunResult:
        self.captured_run_id = run_id
        return DockerRunResult(
            exit_code=0,
            stdout="Python 3.12.0\n",
            stderr="",
            duration_ms=17,
            image="python:3.12-slim",
            workspace=Path(workspace).resolve(),
            network_mode=self.network_mode,
            command=tuple(command),
        )


def make_session(tmp_path: Path) -> Session:
    database = Database(f"sqlite:///{tmp_path / 'mica.db'}")
    database.init_db()
    return database.session_factory()


def test_docker_execution_creates_run_command_events_and_summary(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session = make_session(tmp_path)

    try:
        evidence = DockerExecutionService(session, runner=FakeDockerRunner()).execute(
            workspace=workspace,
            command=["python", "--version"],
        )

        assert evidence.result.stdout == "Python 3.12.0\n"
        assert isinstance(evidence.run.id, str)
        assert evidence.run.id
        assert evidence.command.exit_code == 0
        assert evidence.run.status == RunStatus.COMPLETED
        assert evidence.run.cwd == str(workspace.resolve())

        events = EventService(session).list_events(run_id=evidence.run.id)
        assert [event.event_type for event in events] == [
            EventType.RUN_CREATED,
            EventType.COMMAND_STARTED,
            "command_output",
            EventType.NETWORK_EVIDENCE,
            EventType.COMMAND_FINISHED,
            EventType.RUN_COMPLETED,
        ]
        assert events[2].payload == {
            "command_line": "python --version",
            "stream": "stdout",
            "text": "Python 3.12.0\n",
        }
        assert events[3].event_type == EventType.NETWORK_EVIDENCE
        assert events[3].payload == {
            "command_line": "python --version",
            "network_mode": "none",
            "network_access": "disabled",
            "host_callback_required": False,
            "boundary": "Network evidence records Docker network mode only; it is not packet capture or a firewall proof.",
        }
        assert events[4].payload == {
            "command_line": "python --version",
            "command_origin": "external_binary",
            "duration_ms": 17,
            "exit_code": 0,
            "status": "completed",
        }

        summary = RunService(session).summary(evidence.run.id)
        assert summary is not None
        assert summary.status == RunStatus.COMPLETED
        assert summary.total_commands == 1
        assert summary.successful_commands == 1
        assert summary.total_duration_ms == 17
    finally:
        session.close()


def test_docker_execution_records_policy_decision_event(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session = make_session(tmp_path)

    try:
        evidence = DockerExecutionService(session, runner=FakeDockerRunner()).execute(
            workspace=workspace,
            command=["python", "--version"],
            policy_decision={
                "policy": "docker-network",
                "decision": "allowed",
                "network_mode": "none",
            },
        )

        events = EventService(session).list_events(run_id=evidence.run.id)
        assert [event.event_type for event in events] == [
            EventType.RUN_CREATED,
            EventType.COMMAND_STARTED,
            EventType.POLICY_DECISION,
            EventType.COMMAND_OUTPUT,
            EventType.NETWORK_EVIDENCE,
            EventType.COMMAND_FINISHED,
            EventType.RUN_COMPLETED,
        ]
        assert events[2].payload == {
            "policy": "docker-network",
            "decision": "allowed",
            "network_mode": "none",
        }
    finally:
        session.close()


def test_docker_execution_records_bridge_network_evidence(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session = make_session(tmp_path)

    try:
        evidence = DockerExecutionService(session, runner=FakeDockerRunner(network_mode="bridge")).execute(
            workspace=workspace,
            command=["git", "status"],
        )

        network_events = [
            event for event in EventService(session).list_events(run_id=evidence.run.id)
            if event.event_type == EventType.NETWORK_EVIDENCE
        ]
        assert len(network_events) == 1
        assert network_events[0].payload["network_mode"] == "bridge"
        assert network_events[0].payload["network_access"] == "host-reachable"
        assert network_events[0].payload["host_callback_required"] is True
    finally:
        session.close()


class StreamingFakeDockerRunner:
    def run(
        self,
        *,
        workspace: str | Path,
        command: list[str],
        run_id: str | None = None,
        on_output: object | None = None,
    ) -> DockerRunResult:
        from app.runners.docker_runner import DockerOutputChunk

        if callable(on_output):
            on_output(DockerOutputChunk(stream="stdout", text="first\n"))
            on_output(DockerOutputChunk(stream="stdout", text="second\n"))
        return DockerRunResult(
            exit_code=0,
            stdout="first\nsecond\n",
            stderr="",
            duration_ms=25,
            image="python:3.12-slim",
            workspace=Path(workspace).resolve(),
            network_mode="none",
            command=tuple(command),
        )


def test_docker_execution_writes_streamed_output_events_before_command_finished(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session = make_session(tmp_path)

    try:
        evidence = DockerExecutionService(session, runner=StreamingFakeDockerRunner()).execute(
            workspace=workspace,
            command=["python", "-c", "print('slow')"],
        )

        events = EventService(session).list_events(run_id=evidence.run.id)
        assert [event.event_type for event in events] == [
            EventType.RUN_CREATED,
            EventType.COMMAND_STARTED,
            EventType.COMMAND_OUTPUT,
            EventType.COMMAND_OUTPUT,
            EventType.NETWORK_EVIDENCE,
            EventType.COMMAND_FINISHED,
            EventType.RUN_COMPLETED,
        ]
        assert events[2].payload["text"] == "first\n"
        assert events[3].payload["text"] == "second\n"
    finally:
        session.close()


class FileChangingFakeDockerRunner:
    def run(
        self,
        *,
        workspace: str | Path,
        command: list[str],
        run_id: str | None = None,
        on_output: object | None = None,
    ) -> DockerRunResult:
        workspace_path = Path(workspace)
        (workspace_path / "created.txt").write_bytes(b"new evidence\n")
        (workspace_path / "modified.txt").write_bytes(b"after\n")
        (workspace_path / "deleted.txt").unlink()
        return DockerRunResult(
            exit_code=0,
            stdout="changed files\n",
            stderr="",
            duration_ms=42,
            image="python:3.12-slim",
            workspace=workspace_path.resolve(),
            network_mode="none",
            command=tuple(command),
        )


def test_docker_execution_records_workspace_file_change_events(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "unchanged.txt").write_bytes(b"same\n")
    (workspace / "modified.txt").write_bytes(b"before\n")
    (workspace / "deleted.txt").write_bytes(b"remove me\n")
    session = make_session(tmp_path)

    try:
        evidence = DockerExecutionService(session, runner=FileChangingFakeDockerRunner()).execute(
            workspace=workspace,
            command=["python", "-c", "change files"],
        )

        file_events = [
            event for event in EventService(session).list_events(run_id=evidence.run.id)
            if event.event_type == EventType.FILE_CHANGED
        ]
        assert [event.payload["change_type"] for event in file_events] == ["created", "modified", "deleted"]
        assert [event.payload["path"] for event in file_events] == [
            "created.txt",
            "modified.txt",
            "deleted.txt",
        ]
        assert file_events[0].payload["after"]["size"] == 13
        assert file_events[1].payload["before"]["sha256"] != file_events[1].payload["after"]["sha256"]
        assert file_events[2].payload["before"]["size"] == 10
        assert file_events[2].payload["after"] is None
    finally:
        session.close()


def test_docker_execution_passes_run_id_to_runner_for_inner_proxy_records(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session = make_session(tmp_path)
    runner = FakeDockerRunner()

    try:
        evidence = DockerExecutionService(session, runner=runner).execute(
            workspace=workspace,
            command=["git", "push", "origin", "main"],
        )

        assert runner.captured_run_id == evidence.run.id
    finally:
        session.close()
