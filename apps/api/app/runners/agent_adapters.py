from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.orm import sessionmaker

from app.models.enums import EventType, RunStatus
from app.schemas.events import EventCreate
from app.services.command_service import CommandService
from app.services.event_service import EventService
from app.services.run_service import RunService


@dataclass(frozen=True)
class AgentAvailability:
    agent_type: str
    available: bool
    executable: str | None
    reason: str | None


class AgentAdapter:
    agent_type = "unknown"

    def find_executable(self) -> str:
        raise NotImplementedError

    def build_command(self, executable: str, prompt: str, workspace: str) -> list[str]:
        raise NotImplementedError

    def parse_stdout_line(self, line: str) -> dict[str, Any] | None:
        text = line.rstrip("\r\n")
        if not text:
            return None
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return {"type": "text", "part": {"text": text}}
        if isinstance(parsed, dict):
            return parsed
        return {"type": "text", "part": {"text": text}}

    def extract_command(self, event: dict[str, Any]) -> str | None:
        part = event.get("part")
        if not isinstance(part, dict):
            return None
        state = part.get("state")
        if not isinstance(state, dict):
            return None
        input_payload = state.get("input")
        if not isinstance(input_payload, dict):
            return None
        command = input_payload.get("command")
        return command if isinstance(command, str) and command else None

    def availability(self) -> AgentAvailability:
        try:
            executable = self.find_executable()
        except FileNotFoundError as exc:
            return AgentAvailability(self.agent_type, False, None, str(exc))
        return AgentAvailability(self.agent_type, True, executable, None)


class MockAgentAdapter(AgentAdapter):
    agent_type = "mock-agent"

    def find_executable(self) -> str:
        return "mock-agent"

    def build_command(self, executable: str, prompt: str, workspace: str) -> list[str]:
        normalized = prompt.lower()
        if "git" in normalized and "status" in normalized:
            return ["git", "status", "--short"]
        if "list" in normalized and ("file" in normalized or "workspace" in normalized):
            return ["python", "-c", "import os; print('\\n'.join(sorted(os.listdir('.'))))"]
        return ["python", "-c", "print('mock-agent received the task')"]


class OpenCodeAdapter(AgentAdapter):
    agent_type = "opencode"

    def find_executable(self) -> str:
        configured = os.environ.get("MICA_OPENCODE_PATH")
        if configured:
            path = Path(configured)
            if path.is_file():
                return str(path)
            raise FileNotFoundError(f"MICA_OPENCODE_PATH does not point to a file: {configured}")
        found = shutil.which("opencode")
        if found:
            return found
        raise FileNotFoundError("OpenCode CLI was not found. Install opencode or set MICA_OPENCODE_PATH.")

    def build_command(self, executable: str, prompt: str, workspace: str) -> list[str]:
        return [executable, "run", "--auto", "--format", "json", "--dir", workspace, prompt]


ADAPTERS: dict[str, type[AgentAdapter]] = {
    MockAgentAdapter.agent_type: MockAgentAdapter,
    OpenCodeAdapter.agent_type: OpenCodeAdapter,
}


def list_agent_availability() -> list[AgentAvailability]:
    return [adapter_type().availability() for adapter_type in ADAPTERS.values()]


def get_adapter(agent_type: str) -> AgentAdapter:
    adapter_type = ADAPTERS.get(agent_type)
    if adapter_type is None:
        raise ValueError(f"Unsupported agent_type: {agent_type}")
    return adapter_type()


class AgentProcessManager:
    def __init__(self) -> None:
        self._processes: dict[str, subprocess.Popen[str]] = {}
        self._cancelled: set[str] = set()
        self._lock = threading.Lock()

    def start(
        self,
        *,
        run_id: str,
        adapter: AgentAdapter,
        command: list[str],
        workspace: str,
        session_factory: sessionmaker,
    ) -> None:
        thread = threading.Thread(
            target=self._run_background,
            kwargs={
                "run_id": run_id,
                "adapter": adapter,
                "command": command,
                "workspace": workspace,
                "session_factory": session_factory,
            },
            daemon=True,
        )
        thread.start()

    def cancel(self, run_id: str, session_factory: sessionmaker) -> bool:
        with self._lock:
            process = self._processes.get(run_id)
            self._cancelled.add(run_id)
        if process is not None:
            self._terminate_process_tree(process)
        with session_factory() as session:
            RunService(session).finish_with_status(run_id, status=RunStatus.CANCELLED)
        return process is not None

    def _run_background(
        self,
        *,
        run_id: str,
        adapter: AgentAdapter,
        command: list[str],
        workspace: str,
        session_factory: sessionmaker,
    ) -> None:
        process: subprocess.Popen[str] | None = None
        try:
            process = subprocess.Popen(
                command,
                cwd=workspace,
                env=self._controlled_env(run_id),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            with self._lock:
                self._processes[run_id] = process
            self._read_streams(run_id, adapter, process, session_factory)
            exit_code = process.wait()
            with self._lock:
                cancelled = run_id in self._cancelled
                self._processes.pop(run_id, None)
                self._cancelled.discard(run_id)
            status = RunStatus.CANCELLED if cancelled else RunStatus.COMPLETED if exit_code == 0 else RunStatus.FAILED
            with session_factory() as session:
                RunService(session).finish_with_status(run_id, status=status)
        except Exception as exc:
            with self._lock:
                self._processes.pop(run_id, None)
                self._cancelled.discard(run_id)
            with session_factory() as session:
                EventService(session).create(
                    EventCreate(
                        run_id=run_id,
                        event_type=EventType.COMMAND_OUTPUT,
                        message=f"Agent process failed: {exc}",
                        payload={"stream": "stderr", "text": str(exc)},
                    )
                )
                session.commit()
                RunService(session).finish_with_status(run_id, status=RunStatus.FAILED)

    def _read_streams(
        self,
        run_id: str,
        adapter: AgentAdapter,
        process: subprocess.Popen[str],
        session_factory: sessionmaker,
    ) -> None:
        assert process.stdout is not None
        for line in process.stdout:
            event = adapter.parse_stdout_line(line)
            if event is None:
                continue
            self._store_agent_event(run_id, adapter, event, session_factory)
        if process.stderr is not None:
            stderr = process.stderr.read()
            if stderr:
                self._store_output(run_id, "stderr", stderr, session_factory)

    def _store_agent_event(
        self,
        run_id: str,
        adapter: AgentAdapter,
        event: dict[str, Any],
        session_factory: sessionmaker,
    ) -> None:
        text = _event_text(event)
        with session_factory() as session:
            EventService(session).create(
                EventCreate(
                    run_id=run_id,
                    event_type=EventType.COMMAND_OUTPUT,
                    message=text or f"{adapter.agent_type} emitted {event.get('type', 'event')}",
                    payload={"stream": "stdout", "text": text, "raw_event": event},
                )
            )
            session.commit()
            command = adapter.extract_command(event)
            if command:
                CommandService(session).mark_agent_tool_command(run_id, command)
        self._record_unintercepted_risk(run_id, adapter, event, session_factory)

    def _store_output(self, run_id: str, stream: str, text: str, session_factory: sessionmaker) -> None:
        with session_factory() as session:
            EventService(session).create(
                EventCreate(
                    run_id=run_id,
                    event_type=EventType.COMMAND_OUTPUT,
                    message=f"Agent {stream}: {text[:160]}",
                    payload={"stream": stream, "text": text},
                )
            )
            session.commit()

    def _record_unintercepted_risk(
        self,
        run_id: str,
        adapter: AgentAdapter,
        event: dict[str, Any],
        session_factory: sessionmaker,
    ) -> None:
        if event.get("type") != "tool_use":
            return
        command = adapter.extract_command(event)
        if not command:
            return
        reason = _high_risk_reason(command)
        if reason is None:
            return
        with session_factory() as session:
            existing = [
                item
                for item in EventService(session).list_events(run_id=run_id)
                if item.event_type == EventType.POLICY_DECISION
                and item.payload.get("decision") == "unintercepted"
                and item.payload.get("command_line") == command
            ]
            if existing:
                return
            EventService(session).create(
                EventCreate(
                    run_id=run_id,
                    event_type=EventType.POLICY_DECISION,
                    message=f"Unintercepted high-risk command observed: {command}",
                    payload={
                        "decision": "unintercepted",
                        "command_line": command,
                        "risk_level": "high",
                        "reason": reason,
                    },
                )
            )
            session.commit()

    def _controlled_env(self, run_id: str) -> dict[str, str]:
        env = os.environ.copy()
        repo_root = Path(__file__).resolve().parents[4]
        shim_dir = str(repo_root / "shims")
        original_path = env.get("MICA_ORIGINAL_PATH") or env.get("PATH", "")
        env["PATH"] = f"{shim_dir}{os.pathsep}{original_path}"
        env["MICA_ORIGINAL_PATH"] = original_path
        env["MICA_RUN_ID"] = run_id
        env.setdefault("MICA_API_BASE_URL", "http://localhost:8000/api")
        env["PYTHONPATH"] = str(repo_root / "apps" / "api")
        return env

    def _terminate_process_tree(self, process: subprocess.Popen[str]) -> None:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            return
        process.kill()


def _event_text(event: dict[str, Any]) -> str:
    if isinstance(event.get("message"), str):
        return event["message"]
    part = event.get("part")
    if isinstance(part, dict) and isinstance(part.get("text"), str):
        return part["text"]
    return json.dumps(event, ensure_ascii=False)


def _high_risk_reason(command: str) -> str | None:
    normalized = " ".join(command.lower().split())
    patterns = {
        "rm -rf": "recursive force removal",
        "sudo": "privileged command",
        "git push": "remote repository write",
        "terraform apply": "infrastructure mutation",
        "terraform destroy": "infrastructure destruction",
        "kubectl delete": "cluster resource deletion",
        "curl | sh": "remote script execution",
        "wget | sh": "remote script execution",
        "npm publish": "package publishing",
    }
    for pattern, reason in patterns.items():
        if pattern in normalized:
            return reason
    return None


agent_process_manager = AgentProcessManager()
