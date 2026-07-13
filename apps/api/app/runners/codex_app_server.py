from __future__ import annotations

import json
import os
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CodexTurnResult:
    thread_id: str
    turn_id: str | None
    status: str
    text: str
    events: list[dict[str, Any]]


class CodexAppServerClient:
    def __init__(self, executable: str, workspace: str) -> None:
        self.executable = executable
        self.workspace = workspace
        self._next_id = 1
        self._lock = threading.Lock()
        self.process: subprocess.Popen[str] | None = None

    def __enter__(self) -> "CodexAppServerClient":
        env = os.environ.copy()
        repo_root = Path(__file__).resolve().parents[4]
        env.setdefault("MICA_API_BASE_URL", "http://localhost:8000/api")
        env["PYTHONPATH"] = str(repo_root / "apps" / "api")
        self.process = subprocess.Popen(
            [self.executable, "app-server"],
            cwd=self.workspace,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self.process is None:
            return
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()

    def start_or_resume_thread(self, *, thread_id: str | None, cwd: str) -> str:
        if thread_id:
            response, events = self.call("thread/resume", {"id": thread_id, "cwd": cwd})
            return _thread_id_from_response(response, events) or thread_id
        response, events = self.call("thread/start", {"cwd": cwd})
        next_thread_id = _thread_id_from_response(response, events)
        if next_thread_id is None:
            raise RuntimeError(f"Codex app-server did not return a thread id: {response!r}")
        return next_thread_id

    def run_turn(self, *, thread_id: str, prompt: str, cwd: str) -> CodexTurnResult:
        request_id = self._send(
            "turn/start",
            {
                "threadId": thread_id,
                "input": [{"type": "text", "text": prompt}],
                "cwd": cwd,
                "clientUserMessageId": f"mica-{self._next_id}",
            },
        )
        events: list[dict[str, Any]] = []
        text_chunks: list[str] = []
        turn_id: str | None = None
        status = "completed"
        while True:
            message = self._read_message()
            if "method" in message:
                events.append(message)
                method = message.get("method")
                params = message.get("params")
                if isinstance(params, dict):
                    turn = params.get("turn")
                    if isinstance(turn, dict):
                        value = turn.get("id")
                        if isinstance(value, str):
                            turn_id = value
                    if method == "item/agentMessage/delta":
                        delta = params.get("delta")
                        if isinstance(delta, str):
                            text_chunks.append(delta)
                        item = params.get("item")
                        if isinstance(item, dict) and isinstance(item.get("delta"), str):
                            text_chunks.append(item["delta"])
                    elif method == "item/completed":
                        text = _text_from_item(params.get("item"))
                        if text:
                            text_chunks.append(text)
                    elif method == "turn/completed":
                        if isinstance(turn, dict) and isinstance(turn.get("status"), str):
                            status = turn["status"]
                        break
                continue
            if message.get("id") == request_id:
                result = message.get("result")
                if isinstance(result, dict):
                    turn = result.get("turn") if isinstance(result.get("turn"), dict) else result
                    if isinstance(turn, dict):
                        value = turn.get("id")
                        if isinstance(value, str):
                            turn_id = value
                continue
        return CodexTurnResult(
            thread_id=thread_id,
            turn_id=turn_id,
            status=status,
            text="".join(text_chunks).strip(),
            events=events,
        )

    def call(self, method: str, params: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        request_id = self._send(method, params)
        events: list[dict[str, Any]] = []
        while True:
            message = self._read_message()
            if message.get("id") == request_id:
                return message, events
            events.append(message)

    def _send(self, method: str, params: dict[str, Any]) -> int:
        if self.process is None or self.process.stdin is None:
            raise RuntimeError("Codex app-server process is not running.")
        with self._lock:
            request_id = self._next_id
            self._next_id += 1
        payload = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        self.process.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
        self.process.stdin.flush()
        return request_id

    def _read_message(self) -> dict[str, Any]:
        if self.process is None or self.process.stdout is None:
            raise RuntimeError("Codex app-server process is not running.")
        line = self.process.stdout.readline()
        if not line:
            stderr = ""
            if self.process.stderr is not None:
                stderr = self.process.stderr.read()
            raise RuntimeError(f"Codex app-server closed stdout unexpectedly. {stderr}".strip())
        parsed = json.loads(line)
        if not isinstance(parsed, dict):
            raise RuntimeError(f"Codex app-server emitted a non-object message: {parsed!r}")
        if "error" in parsed:
            raise RuntimeError(f"Codex app-server JSON-RPC error: {parsed['error']!r}")
        return parsed


def _thread_id_from_response(response: dict[str, Any], events: list[dict[str, Any]]) -> str | None:
    for payload in [response, *events]:
        result = payload.get("result")
        if isinstance(result, dict):
            thread = result.get("thread")
            if isinstance(thread, dict) and isinstance(thread.get("id"), str):
                return thread["id"]
            if isinstance(result.get("threadId"), str):
                return result["threadId"]
            if isinstance(result.get("id"), str) and str(result.get("id", "")).startswith("thr"):
                return result["id"]
        params = payload.get("params")
        if isinstance(params, dict):
            thread = params.get("thread")
            if isinstance(thread, dict) and isinstance(thread.get("id"), str):
                return thread["id"]
    return None


def _text_from_item(item: object) -> str:
    if not isinstance(item, dict):
        return ""
    for key in ("text", "message", "content"):
        value = item.get(key)
        if isinstance(value, str):
            return value
    parts = item.get("parts")
    if isinstance(parts, list):
        chunks: list[str] = []
        for part in parts:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                chunks.append(part["text"])
        return "".join(chunks)
    return ""
