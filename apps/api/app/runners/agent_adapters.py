from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.orm import sessionmaker

from app.models.enums import CommandStatus, EventType, RunStatus
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

    def build_command(
        self,
        executable: str,
        prompt: str,
        workspace: str,
        *,
        external_session_id: str | None = None,
    ) -> list[str]:
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


def _windows_runnable_path(path: str) -> str:
    """Prefer a directly runnable Windows launcher over extensionless npm shims."""
    if os.name != "nt":
        return path
    candidate = Path(path)
    if candidate.suffix:
        return path
    for suffix in (".cmd", ".bat", ".exe"):
        sibling = candidate.with_suffix(suffix)
        if sibling.is_file():
            return str(sibling)
    return path


class MockAgentAdapter(AgentAdapter):
    agent_type = "mock-agent"

    def find_executable(self) -> str:
        return "mock-agent"

    def build_command(
        self,
        executable: str,
        prompt: str,
        workspace: str,
        *,
        external_session_id: str | None = None,
    ) -> list[str]:
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
                return _windows_runnable_path(str(path))
            raise FileNotFoundError(f"MICA_OPENCODE_PATH does not point to a file: {configured}")
        found = shutil.which("opencode")
        if found:
            return _windows_runnable_path(found)
        raise FileNotFoundError("OpenCode CLI was not found. Install opencode or set MICA_OPENCODE_PATH.")

    def build_command(
        self,
        executable: str,
        prompt: str,
        workspace: str,
        *,
        external_session_id: str | None = None,
    ) -> list[str]:
        command = [executable, "run", "--auto", "--format", "json", "--dir", workspace]
        if external_session_id:
            command.extend(["--session", external_session_id])
        command.append(prompt)
        return command


class CodexCliAdapter(AgentAdapter):
    agent_type = "codex-cli"

    def find_executable(self) -> str:
        configured = os.environ.get("MICA_CODEX_PATH")
        if configured:
            path = Path(configured)
            if path.is_file():
                return _windows_runnable_path(str(path))
            raise FileNotFoundError(f"MICA_CODEX_PATH does not point to a file: {configured}")
        found = shutil.which("codex")
        if found:
            return _windows_runnable_path(found)
        raise FileNotFoundError("Codex CLI was not found. Install codex or set MICA_CODEX_PATH.")

    def build_command(
        self,
        executable: str,
        prompt: str,
        workspace: str,
        *,
        external_session_id: str | None = None,
    ) -> list[str]:
        sandbox = os.environ.get("MICA_CODEX_SANDBOX") or (
            "danger-full-access" if os.name == "nt" else "workspace-write"
        )
        base = [
            executable,
            "exec",
            "--json",
            "--cd",
            workspace,
            "--sandbox",
            sandbox,
            "--config",
            'approval_policy="never"',
            "--config",
            "shell_environment_policy.inherit=all",
            "--skip-git-repo-check",
        ]
        if external_session_id:
            base.extend(["resume", external_session_id, prompt])
        else:
            base.append(prompt)
        return base

    def extract_command(self, event: dict[str, Any]) -> str | None:
        command = super().extract_command(event)
        if command:
            return command

        for key in ("cmd", "command"):
            value = event.get(key)
            if isinstance(value, str) and value:
                return value

        item = event.get("item")
        if isinstance(item, dict):
            for key in ("cmd", "command"):
                value = item.get(key)
                if isinstance(value, str) and value:
                    return value
            arguments = item.get("arguments")
            if isinstance(arguments, dict):
                value = arguments.get("cmd") or arguments.get("command")
                if isinstance(value, str) and value:
                    return value

        msg = event.get("msg")
        if isinstance(msg, dict):
            for key in ("cmd", "command"):
                value = msg.get(key)
                if isinstance(value, str) and value:
                    return value
        return None


class AntigravityCliAdapter(AgentAdapter):
    agent_type = "antigravity-cli"

    def find_executable(self) -> str:
        configured = os.environ.get("MICA_ANTIGRAVITY_PATH")
        if configured:
            path = Path(configured)
            if path.is_file():
                return _windows_runnable_path(str(path))
            raise FileNotFoundError(f"MICA_ANTIGRAVITY_PATH does not point to a file: {configured}")
        for executable in ("agy", "antigravity", "antigravity-cli"):
            found = shutil.which(executable)
            if found:
                return _windows_runnable_path(found)
        raise FileNotFoundError(
            "Antigravity CLI was not found. Install agy or set MICA_ANTIGRAVITY_PATH."
        )

    def build_command(
        self,
        executable: str,
        prompt: str,
        workspace: str,
        *,
        external_session_id: str | None = None,
    ) -> list[str]:
        timeout = os.environ.get("MICA_ANTIGRAVITY_PRINT_TIMEOUT", "10m")
        return [
            executable,
            "--print",
            prompt,
            "--add-dir",
            workspace,
            "--mode",
            "accept-edits",
            "--print-timeout",
            timeout,
        ]

    def extract_command(self, event: dict[str, Any]) -> str | None:
        command = super().extract_command(event)
        if command:
            return command
        for key in ("cmd", "command"):
            value = event.get(key)
            if isinstance(value, str) and value:
                return value
        item = event.get("item")
        if isinstance(item, dict):
            for key in ("cmd", "command"):
                value = item.get(key)
                if isinstance(value, str) and value:
                    return value
        return None


ADAPTERS: dict[str, type[AgentAdapter]] = {
    MockAgentAdapter.agent_type: MockAgentAdapter,
    OpenCodeAdapter.agent_type: OpenCodeAdapter,
    CodexCliAdapter.agent_type: CodexCliAdapter,
    AntigravityCliAdapter.agent_type: AntigravityCliAdapter,
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
            return True
        with session_factory() as session:
            RunService(session).finish_with_status(run_id, status=RunStatus.CANCELLED)
        return process is not None

    def active_run_ids(self) -> set[str]:
        with self._lock:
            return set(self._processes)

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
        stop_watcher = threading.Event()
        watcher: threading.Thread | None = None
        try:
            initial_snapshot = _snapshot_workspace(workspace)
            watcher = threading.Thread(
                target=self._watch_workspace_changes,
                kwargs={
                    "run_id": run_id,
                    "workspace": workspace,
                    "initial_snapshot": initial_snapshot,
                    "stop_event": stop_watcher,
                    "session_factory": session_factory,
                },
                daemon=True,
            )
            watcher.start()
            process = subprocess.Popen(
                command,
                cwd=workspace,
                env=self._controlled_env(run_id),
                stdin=subprocess.DEVNULL,
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
            stop_watcher.set()
            if watcher is not None:
                watcher.join(timeout=1)
            status = RunStatus.CANCELLED if cancelled else RunStatus.COMPLETED if exit_code == 0 else RunStatus.FAILED
            with session_factory() as session:
                finished_run = RunService(session).finish_with_status(run_id, status=status)
                if finished_run is not None and finished_run.session_id is not None:
                    from app.services.session_service import SessionService

                    SessionService(session).finalize_run(finished_run.id, status=finished_run.status)
        except Exception as exc:
            with self._lock:
                self._processes.pop(run_id, None)
                self._cancelled.discard(run_id)
            stop_watcher.set()
            if watcher is not None:
                watcher.join(timeout=1)
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
                finished_run = RunService(session).finish_with_status(run_id, status=RunStatus.FAILED)
                if finished_run is not None and finished_run.session_id is not None:
                    from app.services.session_service import SessionService

                    SessionService(session).finalize_run(finished_run.id, status=finished_run.status)
        finally:
            stop_watcher.set()
            if watcher is not None:
                watcher.join(timeout=1)

    def _read_streams(
        self,
        run_id: str,
        adapter: AgentAdapter,
        process: subprocess.Popen[str],
        session_factory: sessionmaker,
    ) -> None:
        assert process.stdout is not None
        output_queue: queue.Queue[tuple[str, str | None]] = queue.Queue()
        streams = [("stdout", process.stdout)]
        if process.stderr is not None:
            streams.append(("stderr", process.stderr))

        def read_stream(stream_name: str, pipe: Any) -> None:
            try:
                for line in pipe:
                    output_queue.put((stream_name, line))
            finally:
                output_queue.put((stream_name, None))

        readers = [
            threading.Thread(target=read_stream, args=(stream_name, pipe), daemon=True)
            for stream_name, pipe in streams
        ]
        for reader in readers:
            reader.start()

        finished_readers = 0
        while finished_readers < len(readers):
            stream_name, line = output_queue.get()
            if line is None:
                finished_readers += 1
                continue
            if stream_name == "stdout":
                event = adapter.parse_stdout_line(line)
                if event is not None:
                    self._store_agent_event(run_id, adapter, event, session_factory)
            else:
                self._store_output(run_id, stream_name, line, session_factory)

        for reader in readers:
            reader.join(timeout=1)

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
                status, exit_code = _command_event_status(event)
                CommandService(session).record_agent_tool_event(
                    run_id,
                    command_line=command,
                    cwd=self._event_workspace(run_id, session),
                    status=status,
                    exit_code=exit_code,
                )
        self._record_unintercepted_risk(run_id, adapter, event, session_factory)

    def _event_workspace(self, run_id: str, session: Any) -> str:
        run = RunService(session).get(run_id)
        return run.cwd if run is not None else ""

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

    def _watch_workspace_changes(
        self,
        *,
        run_id: str,
        workspace: str,
        initial_snapshot: dict[str, tuple[int, int]],
        stop_event: threading.Event,
        session_factory: sessionmaker,
    ) -> None:
        previous = initial_snapshot
        interval = float(os.environ.get("MICA_WORKSPACE_WATCH_INTERVAL_SECONDS", "0.5"))
        while not stop_event.wait(interval):
            current = _snapshot_workspace(workspace)
            for relative_path, stat in current.items():
                if relative_path not in previous:
                    self._store_file_changed(run_id, workspace, relative_path, "created", session_factory)
                elif previous[relative_path] != stat:
                    self._store_file_changed(run_id, workspace, relative_path, "modified", session_factory)
            for relative_path in previous:
                if relative_path not in current:
                    self._store_file_changed(run_id, workspace, relative_path, "deleted", session_factory)
            previous = current

    def _store_file_changed(
        self,
        run_id: str,
        workspace: str,
        relative_path: str,
        kind: str,
        session_factory: sessionmaker,
    ) -> None:
        full_path = str(Path(workspace) / relative_path)
        with session_factory() as session:
            EventService(session).create(
                EventCreate(
                    run_id=run_id,
                    event_type=EventType.FILE_CHANGED,
                    message=f"File {kind}: {relative_path}",
                    payload={
                        "kind": kind,
                        "path": full_path,
                        "relative_path": relative_path,
                    },
                )
            )
            session.commit()


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


def _command_event_status(event: dict[str, Any]) -> tuple[CommandStatus | None, int | None]:
    item = event.get("item")
    payload = item if isinstance(item, dict) else event
    part = event.get("part")
    if isinstance(part, dict):
        state = part.get("state")
        if isinstance(state, dict):
            payload = state
    raw_status = payload.get("status")
    status: CommandStatus | None = None
    if raw_status == "completed":
        status = CommandStatus.COMPLETED
    elif raw_status == "failed":
        status = CommandStatus.FAILED
    elif raw_status in {"in_progress", "running", "started"}:
        status = CommandStatus.STARTED
    exit_code = payload.get("exit_code")
    metadata = payload.get("metadata")
    if exit_code is None and isinstance(metadata, dict):
        exit_code = metadata.get("exit")
    return status, exit_code if isinstance(exit_code, int) else None


agent_process_manager = AgentProcessManager()


_SKIPPED_WORKSPACE_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".next",
    ".venv",
    "node_modules",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
}


def _snapshot_workspace(workspace: str, *, max_files: int = 5000) -> dict[str, tuple[int, int]]:
    root = Path(workspace)
    snapshot: dict[str, tuple[int, int]] = {}
    if not root.exists():
        return snapshot
    try:
        iterator = root.rglob("*")
        for path in iterator:
            if len(snapshot) >= max_files:
                break
            try:
                relative_parts = path.relative_to(root).parts
                if any(part in _SKIPPED_WORKSPACE_DIRS for part in relative_parts):
                    continue
                if not path.is_file():
                    continue
                stat = path.stat()
            except (OSError, ValueError):
                continue
            snapshot[str(path.relative_to(root))] = (stat.st_mtime_ns, stat.st_size)
    except OSError:
        return snapshot
    return snapshot
