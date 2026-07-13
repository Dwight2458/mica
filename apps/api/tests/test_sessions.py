from __future__ import annotations

import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.models.approval import utcnow
from app.models.enums import AgentSessionStatus, InteractionKind, InteractionSource, RunStatus
from app.models.run import RunRecord
from app.models.session import AgentSession
from app.runners.opencode_server import assistant_message_completed
from app.services.interaction_service import InteractionService
from app.services import session_service as session_service_module
from app.services.session_service import _record_opencode_message_updates


def _write_fake_agent(tmp_path: Path, name: str, body: str) -> Path:
    script = tmp_path / f"fake_{name}.py"
    script.write_text(body, encoding="utf-8")
    launcher = tmp_path / f"{name}.cmd"
    launcher.write_text(f'@echo off\r\n"{sys.executable}" "{script}" %*\r\n', encoding="utf-8")
    return launcher


def _write_fake_codex_app_server(tmp_path: Path) -> tuple[Path, Path]:
    calls_path = tmp_path / "codex_app_server_calls.jsonl"
    script = tmp_path / "fake_codex_app_server.py"
    script.write_text(
        f"""
import json
import pathlib
import sys

calls_path = pathlib.Path({str(calls_path)!r})

def emit(payload):
    print(json.dumps(payload), flush=True)

for raw in sys.stdin:
    request = json.loads(raw)
    method = request.get("method")
    calls_path.write_text(calls_path.read_text(encoding="utf-8") + json.dumps(request) + "\\n" if calls_path.exists() else json.dumps(request) + "\\n", encoding="utf-8")
    if method == "thread/start":
        emit({{"jsonrpc": "2.0", "method": "thread/started", "params": {{"thread": {{"id": "thr-app-1", "status": "idle"}}}}}})
        emit({{"jsonrpc": "2.0", "id": request["id"], "result": {{"thread": {{"id": "thr-app-1", "status": "idle"}}}}}})
    elif method == "thread/resume":
        emit({{"jsonrpc": "2.0", "id": request["id"], "result": {{"thread": {{"id": request["params"].get("id"), "status": "idle"}}}}}})
    elif method == "turn/start":
        emit({{"jsonrpc": "2.0", "id": request["id"], "result": {{"turn": {{"id": "turn-1", "status": "inProgress"}}}}}})
        emit({{"jsonrpc": "2.0", "method": "turn/started", "params": {{"turn": {{"id": "turn-1", "status": "inProgress"}}}}}})
        emit({{"jsonrpc": "2.0", "method": "item/agentMessage/delta", "params": {{"delta": "Codex app-server answer."}}}})
        emit({{"jsonrpc": "2.0", "method": "turn/completed", "params": {{"turn": {{"id": "turn-1", "status": "completed"}}}}}})
    else:
        emit({{"jsonrpc": "2.0", "id": request["id"], "error": {{"code": -32601, "message": "unknown method"}}}})
""".strip(),
        encoding="utf-8",
    )
    launcher = tmp_path / "codex.cmd"
    launcher.write_text(f'@echo off\r\n"{sys.executable}" "{script}" %*\r\n', encoding="utf-8")
    return launcher, calls_path


def _wait_for_session(client: TestClient, session_id: str, *statuses: str) -> dict:
    deadline = time.time() + 5
    payload: dict[str, Any] = {}
    while time.time() < deadline:
        payload = client.get(f"/api/sessions/{session_id}").json()
        if payload["status"] in statuses:
            return payload
        time.sleep(0.05)
    raise AssertionError(f"Session {session_id} did not reach {statuses}; last payload: {payload}")


def _wait_for_request_count(state: dict[str, Any], count: int) -> None:
    deadline = time.time() + 5
    while time.time() < deadline:
        if len(state["requests"]) >= count:
            return
        time.sleep(0.05)
    raise AssertionError(f"OpenCode fake server only received {len(state['requests'])} requests, expected {count}")


def _start_fake_opencode_server(
    response_text: str = "Need choice.",
    *,
    response_delay: float = 0,
    async_events: list[dict[str, Any]] | None = None,
    event_stream_hold_seconds: float = 0,
) -> tuple[str, dict[str, Any], ThreadingHTTPServer]:
    state: dict[str, Any] = {
        "requests": [],
        "response_text": response_text,
        "permission_decisions": [],
        "prompt_count": 0,
    }

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/global/health":
                self._json({"healthy": True, "version": "fake"})
                return
            if self.path == "/global/event" and async_events is not None:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                for event in async_events:
                    encoded = f"event: {event.get('type', 'message')}\ndata: {json.dumps(event)}\n\n".encode("utf-8")
                    self.wfile.write(encoded)
                    self.wfile.flush()
                if event_stream_hold_seconds:
                    time.sleep(event_stream_hold_seconds)
                return
            if self.path == "/session/status":
                self._json({})
                return
            if self.path == "/session/oc-session-123/message":
                if state["prompt_count"] == 0:
                    self._json([])
                    return
                waiting_for_permission = any(
                    "permission" in str(event.get("type", "")) for event in (async_events or [])
                )
                self._json(
                    [
                        {
                            "info": {
                                "id": f"assistant-message-{state['prompt_count']}",
                                "role": "assistant",
                                "time": {"completed": None if waiting_for_permission else 123456},
                                "finish": None if waiting_for_permission else "stop",
                            },
                            "parts": [{"type": "text", "text": state["response_text"]}],
                        }
                    ]
                )
                return
            self.send_error(404)

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length else b"{}"
            body = json.loads(raw.decode("utf-8"))
            state["requests"].append({"path": self.path, "body": body})
            if self.path == "/session":
                self._json({"id": "oc-session-123", "title": body.get("title")})
                return
            if self.path == "/session/oc-session-123/prompt_async" and async_events is not None:
                state["prompt_count"] += 1
                self._json({"ok": True})
                return
            if self.path == "/session/oc-session-123/message":
                state["prompt_count"] += 1
                if response_delay:
                    time.sleep(response_delay)
                self._json(
                    {
                        "id": "assistant-message-1",
                        "parts": [{"type": "text", "text": state["response_text"]}],
                    }
                )
                return
            if self.path == "/session/oc-session-123/permissions/perm-123":
                state["permission_decisions"].append(body)
                self._json({"ok": True})
                return
            self.send_error(404)

        def log_message(self, format: str, *args: object) -> None:
            return

        def _json(self, payload: dict[str, Any]) -> None:
            encoded = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}"
    return url, state, server


def _start_fake_opencode_question_server(
    questions: list[dict[str, Any]] | None = None,
) -> tuple[str, dict[str, Any], ThreadingHTTPServer]:
    questions = questions or [
        {
            "question": "Which product shape should we build?",
            "header": "Product shape",
            "options": [
                {"label": "Personal tool", "description": "A local single-user tool"},
                {"label": "Web product", "description": "A multi-user web application"},
            ],
        }
    ]
    question = {
        "id": "que-native-123",
        "sessionID": "oc-question-session",
        "questions": questions,
        "tool": {"messageID": "assistant-question", "callID": "call-question"},
    }
    state: dict[str, Any] = {"aborts": 0, "answered": False, "replies": [], "prompted": False}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/global/health":
                self._json({"healthy": True, "version": "fake"})
                return
            if self.path == "/session/status":
                self._json({} if state["answered"] else {"oc-question-session": {"type": "busy"}})
                return
            if self.path == "/question":
                self._json([] if state["answered"] else [question])
                return
            if self.path == "/global/event":
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                event = {
                    "type": "question.asked",
                    "properties": question,
                }
                self.wfile.write(f"data: {json.dumps(event)}\n\n".encode("utf-8"))
                self.wfile.flush()
                return
            if self.path == "/session/oc-question-session/message":
                if not state["prompted"]:
                    self._json([])
                    return
                messages = [
                    {
                        "info": {
                            "id": "assistant-planning",
                            "role": "assistant",
                            "time": {"created": 1, "completed": 2},
                            "finish": "tool-calls",
                        },
                        "parts": [
                            {"id": "text-planning", "type": "text", "text": "I will inspect the project first."},
                            {
                                "id": "tool-todo",
                                "type": "tool",
                                "tool": "todowrite",
                                "state": {"status": "completed", "input": {"todos": ["Inspect", "Implement"]}},
                            },
                            {"id": "step-planning", "type": "step-finish", "reason": "tool-calls"},
                        ],
                    }
                ]
                if state["answered"]:
                    messages.append(
                        {
                            "info": {
                                "id": "assistant-final",
                                "role": "assistant",
                                "time": {"created": 5, "completed": 6},
                                "finish": "stop",
                            },
                            "parts": [
                                {"id": "text-final", "type": "text", "text": "Implementation complete."},
                                {"id": "step-final", "type": "step-finish", "reason": "stop"},
                            ],
                        }
                    )
                else:
                    messages.append(
                        {
                            "info": {"id": "assistant-question", "role": "assistant", "time": {"created": 3}},
                            "parts": [
                                {"id": "text-question", "type": "text", "text": "I need one product decision."},
                                {
                                    "id": "tool-question",
                                    "type": "tool",
                                    "tool": "question",
                                    "state": {
                                        "status": "running",
                                        "input": {"questions": question["questions"]},
                                    },
                                },
                            ],
                        }
                    )
                self._json(messages)
                return
            self.send_error(404)

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            if self.path == "/session":
                self._json({"id": "oc-question-session"})
                return
            if self.path == "/session/oc-question-session/prompt_async":
                state["prompted"] = True
                self._json({"ok": True})
                return
            if self.path == "/session/oc-question-session/abort":
                state["aborts"] += 1
                self._json(True)
                return
            if self.path == "/question/que-native-123/reply":
                state["replies"].append(body)
                state["answered"] = True
                self._json(True)
                return
            self.send_error(404)

        def log_message(self, format: str, *args: object) -> None:
            return

        def _json(self, payload: object) -> None:
            encoded = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{server.server_port}", state, server


def test_create_session_starts_first_run_and_records_user_message(client: TestClient) -> None:
    response = client.post(
        "/api/sessions",
        json={
            "prompt": "Check git status.",
            "workspace": "C:\\repo",
            "agent_type": "mock-agent",
            "runner_mode": "local",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["session"]["title"] == "Check git status."
    assert payload["session"]["last_run_id"] == payload["run"]["id"]
    assert payload["run"]["session_id"] == payload["session"]["id"]
    assert payload["message"]["role"] == "user"
    assert payload["message"]["content"] == "Check git status."

    messages = client.get(f"/api/sessions/{payload['session']['id']}/messages").json()
    assert [message["role"] for message in messages] == ["user", "agent"]
    assert "mock-agent planned" in messages[1]["content"]


def test_continue_session_creates_followup_run_without_rebuilding_transcript(client: TestClient, tmp_path: Path) -> None:
    created = client.post(
        "/api/sessions",
        json={
            "prompt": "Check git status.",
            "workspace": str(tmp_path),
            "agent_type": "mock-agent",
            "runner_mode": "local",
        },
    ).json()
    session_id = created["session"]["id"]

    continued = client.post(
        f"/api/sessions/{session_id}/continue",
        json={"message": "Now list workspace files."},
    )

    assert continued.status_code == 200
    payload = continued.json()
    assert payload["session"]["id"] == session_id
    assert payload["run"]["id"] != created["run"]["id"]
    assert payload["run"]["session_id"] == session_id
    messages = client.get(f"/api/sessions/{session_id}/messages").json()
    assert [message["role"] for message in messages] == ["user", "agent", "user", "agent"]
    assert messages[2]["content"] == "Now list workspace files."

    events = client.get(f"/api/events?run_id={payload['run']['id']}").json()
    prompt_event = next(event for event in events if event["event_type"] == "agent_prompt")
    assert prompt_event["payload"]["prompt"] == "Now list workspace files."
    assert "Transcript:" not in prompt_event["payload"]["prompt"]
    assert prompt_event["payload"]["original_user_message"] == "Now list workspace files."


def test_opencode_session_continue_uses_native_session_id_without_context_file(
    client: TestClient,
    tmp_path: Path,
    monkeypatch,
) -> None:
    url, state, server = _start_fake_opencode_server()
    monkeypatch.setenv("MICA_OPENCODE_SERVER_URL", url)

    try:
        created = client.post(
            "/api/sessions",
            json={
                "prompt": "Plan a browser game.",
                "workspace": str(tmp_path),
                "agent_type": "opencode",
                "runner_mode": "local",
            },
        ).json()
        session_id = created["session"]["id"]
        session_payload = client.get(f"/api/sessions/{session_id}").json()
        assert session_payload["external_session_id"] == "oc-session-123"
        assert session_payload["transport"] == "http"
        assert session_payload["backend_url"] == url

        continued = client.post(
            f"/api/sessions/{session_id}/continue",
            json={"message": "A"},
        )

        assert continued.status_code == 200
        _wait_for_request_count(state, 5)
        _wait_for_session(client, session_id, "completed", "waiting_user_input")
        continued_user_message = continued.json()["message"]
        assert continued_user_message["content"] == "A"
        assert "context_file" not in continued_user_message["message_metadata"]

        events = client.get(f"/api/events?run_id={continued.json()['run']['id']}").json()
        prompt_event = next(event for event in events if event["event_type"] == "agent_prompt")
        prompt = prompt_event["payload"]["prompt"]
        plan_event = next(event for event in events if event["event_type"] == "plan_created")
        assert prompt == "A"
        assert "Transcript:" not in prompt
        assert plan_event["payload"]["transport"] == "http"
        assert "--session" not in plan_event["payload"]["planned_command"]
        assert state["requests"][0]["path"] == "/session"
        assert state["requests"][1]["path"] == "/session/oc-session-123/prompt_async"
        assert state["requests"][2]["path"] == "/session/oc-session-123/message"
        assert state["requests"][2]["body"]["parts"] == [{"type": "text", "text": "Plan a browser game."}]
        assert state["requests"][3]["path"] == "/session/oc-session-123/prompt_async"
        assert state["requests"][4]["body"]["parts"] == [{"type": "text", "text": "A"}]
    finally:
        server.shutdown()


def test_opencode_session_turn_runs_in_background_without_marking_timeout(
    client: TestClient,
    tmp_path: Path,
    monkeypatch,
) -> None:
    url, state, server = _start_fake_opencode_server("Done after slow work.", response_delay=0.5)
    monkeypatch.setenv("MICA_OPENCODE_SERVER_URL", url)

    try:
        started = time.perf_counter()
        response = client.post(
            "/api/sessions",
            json={
                "prompt": "Implement a larger task.",
                "workspace": str(tmp_path),
                "agent_type": "opencode",
                "runner_mode": "local",
            },
        )
        elapsed = time.perf_counter() - started

        assert response.status_code == 201
        assert elapsed < 0.4
        payload = response.json()
        assert payload["run"]["status"] == "started"

        session_payload = _wait_for_session(client, payload["session"]["id"], "completed")
        assert session_payload["summary"] == "Done after slow work."
        run = client.get(f"/api/runs/{payload['run']['id']}").json()
        assert run["status"] == "completed"
        assert state["requests"][1]["path"] == "/session/oc-session-123/prompt_async"
        assert state["requests"][2]["path"] == "/session/oc-session-123/message"
    finally:
        server.shutdown()


def test_opencode_session_idle_event_finalizes_async_turn(
    client: TestClient,
    tmp_path: Path,
    monkeypatch,
) -> None:
    url, state, server = _start_fake_opencode_server(
        "Async turn done.",
        async_events=[{"type": "session.idle", "sessionID": "oc-session-123"}],
    )
    monkeypatch.setenv("MICA_OPENCODE_SERVER_URL", url)

    try:
        response = client.post(
            "/api/sessions",
            json={
                "prompt": "Use async OpenCode.",
                "workspace": str(tmp_path),
                "agent_type": "opencode",
                "runner_mode": "local",
            },
        )

        assert response.status_code == 201
        payload = response.json()
        session_payload = _wait_for_session(client, payload["session"]["id"], "completed")
        assert session_payload["summary"] == "Async turn done."
        run = client.get(f"/api/runs/{payload['run']['id']}").json()
        assert run["status"] == "completed"
        assert state["requests"][1]["path"] == "/session/oc-session-123/prompt_async"
    finally:
        server.shutdown()


def test_opencode_async_turn_recovers_when_idle_event_was_missed(
    client: TestClient,
    tmp_path: Path,
    monkeypatch,
) -> None:
    url, _, server = _start_fake_opencode_server(
        "Completed before the event subscriber connected.",
        async_events=[],
        event_stream_hold_seconds=2,
    )
    monkeypatch.setenv("MICA_OPENCODE_SERVER_URL", url)

    try:
        response = client.post(
            "/api/sessions",
            json={
                "prompt": "Finish quickly.",
                "workspace": str(tmp_path),
                "agent_type": "opencode",
                "runner_mode": "local",
            },
        )

        assert response.status_code == 201
        payload = response.json()
        assert payload["session"]["last_run_id"] == payload["run"]["id"]
        started = time.perf_counter()
        session_payload = _wait_for_session(client, payload["session"]["id"], "completed")
        assert time.perf_counter() - started < 1
        assert session_payload["summary"] == "Completed before the event subscriber connected."
    finally:
        server.shutdown()


def test_opencode_tool_call_message_is_not_a_completed_turn() -> None:
    message = {
        "info": {
            "id": "assistant-tool-call",
            "role": "assistant",
            "time": {"created": 1, "completed": 2},
            "finish": "tool-calls",
        },
        "parts": [{"type": "step-finish", "reason": "tool-calls"}],
    }

    assert assistant_message_completed(message) is False


def test_opencode_native_question_waits_for_input_and_records_runtime_evidence(
    client: TestClient,
    tmp_path: Path,
    monkeypatch,
) -> None:
    url, _, server = _start_fake_opencode_question_server()
    monkeypatch.setenv("MICA_OPENCODE_SERVER_URL", url)

    try:
        response = client.post(
            "/api/sessions",
            json={
                "prompt": "Build a product.",
                "workspace": str(tmp_path),
                "agent_type": "opencode",
                "runner_mode": "local",
            },
        )

        assert response.status_code == 201
        payload = response.json()
        session_id = payload["session"]["id"]
        session_payload = _wait_for_session(client, session_id, "waiting_user_input")
        run = client.get(f"/api/runs/{payload['run']['id']}").json()
        interactions = client.get(f"/api/sessions/{session_id}/interactions?status=pending").json()
        events = client.get(f"/api/events?run_id={payload['run']['id']}").json()
        messages = client.get(f"/api/sessions/{session_id}/messages").json()

        assert session_payload["status"] == "waiting_user_input"
        assert run["status"] == "started"
        assert len(interactions) == 1
        assert interactions[0]["kind"] == "choice"
        assert interactions[0]["source"] == "native"
        assert interactions[0]["external_id"] == "que-native-123"
        assert [option["label"] for option in interactions[0]["options"]] == ["Personal tool", "Web product"]
        assert any(event["payload"].get("raw_event", {}).get("type") == "opencode_message_part" for event in events)
        assert any(event["payload"].get("raw_event", {}).get("type") == "tool_use" for event in events)
        assert any(message["content"] == "I will inspect the project first." for message in messages)
        mirrored = next(message for message in messages if message["content"] == "I will inspect the project first.")
        assert mirrored["message_metadata"]["source"] == "opencode_message_part"
        assert mirrored["message_metadata"]["part_type"] == "text"
    finally:
        server.shutdown()


def test_opencode_message_parts_are_upserted_and_reasoning_is_not_mirrored(
    client: TestClient,
    tmp_path: Path,
) -> None:
    with client.app.state.database.session_factory() as db:
        record = AgentSession(
            title="Native mirror",
            workspace=str(tmp_path),
            agent_type="opencode",
            runner_mode="local",
            status=AgentSessionStatus.ACTIVE,
            external_session_id="oc-mirror-session",
            transport="http",
        )
        db.add(record)
        db.flush()
        run = RunRecord(source="opencode", cwd=str(tmp_path), session_id=record.id)
        db.add(run)
        db.commit()
        session_id = record.id
        run_id = run.id

        seen: set[str] = set()
        _record_opencode_message_updates(
            db,
            run_id=run_id,
            external_session_id="oc-mirror-session",
            messages=[
                {
                    "info": {"id": "assistant-1", "role": "assistant"},
                    "parts": [
                        {"id": "text-1", "type": "text", "text": "## Data model\n\nDraft"},
                        {"id": "reasoning-1", "type": "reasoning", "text": "private chain of thought"},
                        {
                            "id": "tool-1",
                            "type": "tool",
                            "tool": "question",
                            "state": {"status": "pending", "input": {}},
                        },
                    ],
                }
            ],
            seen_part_states=seen,
        )
        _record_opencode_message_updates(
            db,
            run_id=run_id,
            external_session_id="oc-mirror-session",
            messages=[
                {
                    "info": {"id": "assistant-1", "role": "assistant"},
                    "parts": [
                        {"id": "text-1", "type": "text", "text": "## Data model\n\nFinal schema"},
                        {
                            "id": "tool-1",
                            "type": "tool",
                            "tool": "question",
                            "state": {"status": "completed", "title": "Asked 1 question"},
                        },
                    ],
                }
            ],
            seen_part_states=seen,
        )

    messages = client.get(f"/api/sessions/{session_id}/messages").json()
    native_messages = [message for message in messages if message["message_metadata"].get("source") == "opencode_message_part"]
    assert len(native_messages) == 2
    text_message = next(message for message in native_messages if message["message_metadata"]["part_type"] == "text")
    tool_message = next(message for message in native_messages if message["message_metadata"]["part_type"] == "tool")
    assert text_message["content"] == "## Data model\n\nFinal schema"
    assert tool_message["message_metadata"]["tool_status"] == "completed"
    assert "private chain of thought" not in [message["content"] for message in messages]


def test_opencode_sse_message_part_update_is_mirrored(
    client: TestClient,
    tmp_path: Path,
) -> None:
    with client.app.state.database.session_factory() as db:
        record = AgentSession(
            title="SSE mirror",
            workspace=str(tmp_path),
            agent_type="opencode",
            runner_mode="local",
            status=AgentSessionStatus.ACTIVE,
            external_session_id="oc-sse-session",
            transport="http",
        )
        db.add(record)
        db.flush()
        run = RunRecord(source="opencode", cwd=str(tmp_path), session_id=record.id)
        db.add(run)
        db.commit()
        session_id = record.id

        handled = session_service_module._record_opencode_stream_event(
            db,
            run_id=run.id,
            external_session_id="oc-sse-session",
            event={
                "type": "message.part.updated",
                "properties": {
                    "part": {
                        "id": "text-sse-1",
                        "messageID": "assistant-sse-1",
                        "sessionID": "oc-sse-session",
                        "type": "text",
                        "text": "## Prisma Schema\n\n```prisma\nmodel User {}\n```",
                    }
                },
            },
            seen_part_states=set(),
        )

    messages = client.get(f"/api/sessions/{session_id}/messages").json()
    assert handled is True
    assert messages[-1]["content"].startswith("## Prisma Schema")


def test_opencode_native_question_response_continues_same_run(
    client: TestClient,
    tmp_path: Path,
    monkeypatch,
) -> None:
    url, state, server = _start_fake_opencode_question_server()
    monkeypatch.setenv("MICA_OPENCODE_SERVER_URL", url)

    try:
        created = client.post(
            "/api/sessions",
            json={
                "prompt": "Build a product.",
                "workspace": str(tmp_path),
                "agent_type": "opencode",
                "runner_mode": "local",
            },
        ).json()
        session_id = created["session"]["id"]
        _wait_for_session(client, session_id, "waiting_user_input")
        interaction = client.get(f"/api/sessions/{session_id}/interactions?status=pending").json()[0]

        response = client.post(
            f"/api/session-interactions/{interaction['id']}/respond",
            json={"response": "Personal tool", "option_id": "Personal tool"},
        )

        assert response.status_code == 200
        assert response.json()["action"] == "responded_native_interaction"
        completed = _wait_for_session(client, session_id, "completed")
        runs = [run for run in client.get("/api/runs?limit=200").json() if run["session_id"] == session_id]
        messages = client.get(f"/api/sessions/{session_id}/messages").json()
        assert completed["last_run_id"] == created["run"]["id"]
        assert len(runs) == 1
        assert runs[0]["status"] == "completed"
        assert state["replies"] == [{"answers": [["Personal tool"]]}]
        assert messages[-1]["content"] == "Implementation complete."
    finally:
        server.shutdown()


def test_opencode_native_question_pauses_active_turn_timeout(
    client: TestClient,
    tmp_path: Path,
    monkeypatch,
) -> None:
    url, _, server = _start_fake_opencode_question_server()
    monkeypatch.setenv("MICA_OPENCODE_SERVER_URL", url)
    monkeypatch.setenv("MICA_OPENCODE_TURN_TIMEOUT_SECONDS", "0.2")

    try:
        created = client.post(
            "/api/sessions",
            json={
                "prompt": "Build a product.",
                "workspace": str(tmp_path),
                "agent_type": "opencode",
                "runner_mode": "local",
            },
        ).json()
        session_id = created["session"]["id"]
        run_id = created["run"]["id"]
        _wait_for_session(client, session_id, "waiting_user_input")

        time.sleep(0.35)

        assert client.get(f"/api/sessions/{session_id}").json()["status"] == "waiting_user_input"
        assert client.get(f"/api/runs/{run_id}").json()["status"] == "started"
    finally:
        server.shutdown()


def test_opencode_native_answer_reattaches_when_linked_run_is_terminal(
    client: TestClient,
    tmp_path: Path,
    monkeypatch,
) -> None:
    url, state, server = _start_fake_opencode_question_server()
    monkeypatch.setenv("MICA_OPENCODE_SERVER_URL", url)

    try:
        created = client.post(
            "/api/sessions",
            json={
                "prompt": "Build a product.",
                "workspace": str(tmp_path),
                "agent_type": "opencode",
                "runner_mode": "local",
            },
        ).json()
        session_id = created["session"]["id"]
        original_run_id = created["run"]["id"]
        _wait_for_session(client, session_id, "waiting_user_input")
        interaction = client.get(f"/api/sessions/{session_id}/interactions?status=pending").json()[0]
        with client.app.state.database.session_factory() as db:
            run = db.get(RunRecord, original_run_id)
            assert run is not None
            run.status = RunStatus.FAILED
            run.finished_at = utcnow()
            db.add(run)
            db.commit()

        response = client.post(
            f"/api/session-interactions/{interaction['id']}/respond",
            json={"response": "Personal tool", "option_id": "1:1"},
        )

        assert response.status_code == 200
        completed = _wait_for_session(client, session_id, "completed")
        runs = [run for run in client.get("/api/runs").json() if run["session_id"] == session_id]
        assert len(runs) == 2
        assert completed["last_run_id"] != original_run_id
        assert next(run for run in runs if run["id"] == completed["last_run_id"])["status"] == "completed"
        assert state["replies"] == [{"answers": [["Personal tool"]]}]
        assert [request for request in state.get("requests", []) if request["path"].endswith("prompt_async")] == []
    finally:
        server.shutdown()


def test_opencode_http_session_cancel_aborts_native_runtime(
    client: TestClient,
    tmp_path: Path,
    monkeypatch,
) -> None:
    url, state, server = _start_fake_opencode_question_server()
    monkeypatch.setenv("MICA_OPENCODE_SERVER_URL", url)

    try:
        created = client.post(
            "/api/sessions",
            json={
                "prompt": "Build a product.",
                "workspace": str(tmp_path),
                "agent_type": "opencode",
                "runner_mode": "local",
            },
        ).json()
        session_id = created["session"]["id"]
        run_id = created["run"]["id"]
        _wait_for_session(client, session_id, "waiting_user_input")

        response = client.post(f"/api/agent-runs/{run_id}/cancel")

        assert response.status_code == 200
        assert response.json()["status"] == "cancelled"
        assert state["aborts"] == 1
        assert client.get(f"/api/sessions/{session_id}").json()["status"] == "cancelled"
    finally:
        server.shutdown()


def test_opencode_native_question_batches_all_questions_and_persists_conversation(
    client: TestClient,
    tmp_path: Path,
    monkeypatch,
) -> None:
    questions = [
        {
            "question": "Which product shape?",
            "header": "Product",
            "options": [
                {"label": "Personal tool", "description": "Local use"},
                {"label": "Web product", "description": "Public web app"},
            ],
        },
        {
            "question": "Should accounts be required?",
            "header": "Accounts",
            "multiple": True,
            "options": [
                {"label": "Require accounts", "description": "Persist history"},
                {"label": "No accounts", "description": "Anonymous use"},
                {"label": "Guest upgrade", "description": "Start anonymous, upgrade later"},
            ],
        },
    ]
    url, state, server = _start_fake_opencode_question_server(questions)
    monkeypatch.setenv("MICA_OPENCODE_SERVER_URL", url)

    try:
        created = client.post(
            "/api/sessions",
            json={
                "prompt": "Build a product.",
                "workspace": str(tmp_path),
                "agent_type": "opencode",
                "runner_mode": "local",
            },
        ).json()
        session_id = created["session"]["id"]
        _wait_for_session(client, session_id, "waiting_user_input")
        interaction = client.get(f"/api/sessions/{session_id}/interactions?status=pending").json()[0]

        assert {option.get("question_index") for option in interaction["options"]} == {0, 1}
        account_options = [option for option in interaction["options"] if option.get("question_index") == 1]
        assert account_options
        assert all(option.get("multiple") is True for option in account_options)
        messages = client.get(f"/api/sessions/{session_id}/messages").json()
        assert "Which product shape?" in messages[-1]["content"]
        assert "Should accounts be required?" in messages[-1]["content"]

        response = client.post(
            f"/api/session-interactions/{interaction['id']}/respond",
            json={
                "response": "Personal tool; No accounts, Guest upgrade",
                "answers": [["Personal tool"], ["No accounts", "Guest upgrade"]],
            },
        )

        assert response.status_code == 200
        assert state["replies"] == [
            {"answers": [["Personal tool"], ["No accounts", "Guest upgrade"]]}
        ]
        messages = client.get(f"/api/sessions/{session_id}/messages").json()
        answer_message = next(message for message in reversed(messages) if message["role"] == "user")
        assert "Personal tool" in answer_message["content"]
        assert "No accounts" in answer_message["content"]
        assert "Guest upgrade" in answer_message["content"]
    finally:
        server.shutdown()


def test_opencode_native_question_falls_back_to_new_turn_when_request_was_lost(
    client: TestClient,
    tmp_path: Path,
    monkeypatch,
) -> None:
    url, state, server = _start_fake_opencode_server(
        "Recovered on a follow-up turn.",
        async_events=[{"type": "session.idle", "sessionID": "oc-session-123"}],
    )
    monkeypatch.setenv("MICA_OPENCODE_SERVER_URL", url)

    try:
        with client.app.state.database.session_factory() as db:
            record = AgentSession(
                title="Recover native question",
                workspace=str(tmp_path),
                agent_type="opencode",
                runner_mode="local",
                status=AgentSessionStatus.WAITING_USER_INPUT,
                external_session_id="oc-session-123",
                backend_url=url,
                transport="http",
            )
            db.add(record)
            db.flush()
            interaction = InteractionService(db).create_native_question(
                record,
                run_id="lost-run",
                request={
                    "id": "que-lost",
                    "sessionID": "oc-session-123",
                    "questions": [
                        {
                            "question": "Choose a product shape.",
                            "options": [{"label": "Personal tool", "description": "Local use"}],
                        }
                    ],
                },
            )
            db.commit()
            session_id = record.id
            interaction_id = interaction.id

        response = client.post(
            f"/api/session-interactions/{interaction_id}/respond",
            json={"response": "Personal tool", "option_id": "1"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["action"] == "continued_session"
        assert payload["run"]["session_id"] == session_id
        _wait_for_request_count(state, 2)
        assert [request["path"] for request in state["requests"]] == [
            "/question/que-lost/reply",
            "/session/oc-session-123/prompt_async",
        ]
        _wait_for_session(client, session_id, "completed")
    finally:
        server.shutdown()


def test_replayed_native_question_refreshes_multiple_metadata(client: TestClient, tmp_path: Path) -> None:
    with client.app.state.database.session_factory() as db:
        record = AgentSession(
            title="Refresh native question",
            workspace=str(tmp_path),
            agent_type="opencode",
            runner_mode="local",
            status=AgentSessionStatus.WAITING_USER_INPUT,
        )
        db.add(record)
        db.flush()
        service = InteractionService(db)
        first = service.create_native_question(
            record,
            run_id="run-question-refresh",
            request={
                "id": "que-refresh",
                "questions": [
                    {
                        "question": "Which features?",
                        "options": [{"label": "Tests"}, {"label": "Docs"}],
                    }
                ],
            },
        )
        replayed = service.create_native_question(
            record,
            run_id="run-question-refresh",
            request={
                "id": "que-refresh",
                "questions": [
                    {
                        "question": "Which features?",
                        "multiple": True,
                        "options": [{"label": "Tests"}, {"label": "Docs"}],
                    }
                ],
            },
        )

        assert replayed is not None
        assert first is not None
        assert replayed.id == first.id
        assert all(option.get("multiple") is True for option in replayed.options)


def test_opencode_permission_event_creates_native_interaction(
    client: TestClient,
    tmp_path: Path,
    monkeypatch,
) -> None:
    url, _, server = _start_fake_opencode_server(
        "Waiting on permission.",
        async_events=[
            {
                "type": "permission.request",
                "sessionID": "oc-session-123",
                "permissionID": "perm-123",
                "message": "Allow bash command?",
            }
        ],
    )
    monkeypatch.setenv("MICA_OPENCODE_SERVER_URL", url)
    monkeypatch.setenv("MICA_OPENCODE_TURN_TIMEOUT_SECONDS", "0.2")

    try:
        response = client.post(
            "/api/sessions",
            json={
                "prompt": "Trigger permission.",
                "workspace": str(tmp_path),
                "agent_type": "opencode",
                "runner_mode": "local",
            },
        )

        assert response.status_code == 201
        session_id = response.json()["session"]["id"]
        _wait_for_session(client, session_id, "waiting_user_input")
        interactions = client.get(f"/api/sessions/{session_id}/interactions?status=pending").json()
        assert interactions[0]["kind"] == "permission"
        assert interactions[0]["source"] == "native"
        assert interactions[0]["external_id"] == "perm-123"
    finally:
        server.shutdown()


def test_codex_session_continue_uses_exec_resume_without_rebuilding_transcript(
    client: TestClient,
    tmp_path: Path,
    monkeypatch,
) -> None:
    launcher = _write_fake_agent(
        tmp_path,
        "codex",
        """
import json

print(json.dumps({"type": "thread.started", "thread_id": "codex-thread-123"}), flush=True)
print(json.dumps({"type": "text", "message": "Need choice."}), flush=True)
""".strip(),
    )
    monkeypatch.setenv("MICA_CODEX_PATH", str(launcher))
    created = client.post(
        "/api/sessions",
        json={
            "prompt": "Build a snake game.",
            "workspace": str(tmp_path),
            "agent_type": "codex-cli",
            "runner_mode": "local",
        },
    ).json()
    session_id = created["session"]["id"]
    _wait_for_session(client, session_id, "completed")
    session_payload = client.get(f"/api/sessions/{session_id}").json()
    assert session_payload["external_session_id"] == "codex-thread-123"

    continued = client.post(f"/api/sessions/{session_id}/continue", json={"message": "A"})

    assert continued.status_code == 200
    events = client.get(f"/api/events?run_id={continued.json()['run']['id']}").json()
    prompt_event = next(event for event in events if event["event_type"] == "agent_prompt")
    plan_event = next(event for event in events if event["event_type"] == "plan_created")
    assert prompt_event["payload"]["prompt"] == "A"
    assert "Transcript:" not in prompt_event["payload"]["prompt"]
    planned_command = plan_event["payload"]["planned_command"]
    assert "resume" in planned_command
    assert "codex-thread-123" in planned_command


def test_codex_app_server_session_starts_thread_and_records_streamed_text(
    client: TestClient,
    tmp_path: Path,
    monkeypatch,
) -> None:
    launcher, calls_path = _write_fake_codex_app_server(tmp_path)
    monkeypatch.setenv("MICA_CODEX_PATH", str(launcher))
    monkeypatch.setenv("MICA_CODEX_SESSION_TRANSPORT", "app-server")

    response = client.post(
        "/api/sessions",
        json={
            "prompt": "Use native Codex app-server.",
            "workspace": str(tmp_path),
            "agent_type": "codex-cli",
            "runner_mode": "local",
        },
    )

    assert response.status_code == 201
    session_id = response.json()["session"]["id"]
    session_payload = _wait_for_session(client, session_id, "completed")
    assert session_payload["external_session_id"] == "thr-app-1"
    assert session_payload["transport"] == "app-server-stdio"
    assert session_payload["summary"] == "Codex app-server answer."

    messages = client.get(f"/api/sessions/{session_id}/messages").json()
    assert messages[-1]["role"] == "agent"
    assert messages[-1]["content"] == "Codex app-server answer."

    events = client.get(f"/api/events?run_id={response.json()['run']['id']}").json()
    raw_event_types = [
        event["payload"].get("raw_event", {}).get("method")
        for event in events
        if isinstance(event["payload"].get("raw_event"), dict)
    ]
    assert "turn/started" in raw_event_types
    assert "item/agentMessage/delta" in raw_event_types
    calls = [json.loads(line) for line in calls_path.read_text(encoding="utf-8").splitlines()]
    assert [call["method"] for call in calls] == ["thread/start", "turn/start"]


def test_codex_app_server_continue_resumes_native_thread(
    client: TestClient,
    tmp_path: Path,
    monkeypatch,
) -> None:
    launcher, calls_path = _write_fake_codex_app_server(tmp_path)
    monkeypatch.setenv("MICA_CODEX_PATH", str(launcher))
    monkeypatch.setenv("MICA_CODEX_SESSION_TRANSPORT", "app-server")

    created = client.post(
        "/api/sessions",
        json={
            "prompt": "First turn.",
            "workspace": str(tmp_path),
            "agent_type": "codex-cli",
            "runner_mode": "local",
        },
    ).json()
    session_id = created["session"]["id"]
    _wait_for_session(client, session_id, "completed")

    continued = client.post(f"/api/sessions/{session_id}/continue", json={"message": "Second turn."})

    assert continued.status_code == 200
    _wait_for_session(client, session_id, "completed")
    calls = [json.loads(line) for line in calls_path.read_text(encoding="utf-8").splitlines()]
    methods = [call["method"] for call in calls]
    assert methods == ["thread/start", "turn/start", "thread/resume", "turn/start"]
    resume_call = calls[2]
    assert resume_call["params"]["id"] == "thr-app-1"
    second_turn = calls[3]
    assert second_turn["params"]["threadId"] == "thr-app-1"
    assert second_turn["params"]["input"] == [{"type": "text", "text": "Second turn."}]


def test_agent_request_for_more_input_marks_session_waiting_user_input(
    client: TestClient,
    tmp_path: Path,
    monkeypatch,
) -> None:
    launcher = _write_fake_agent(
        tmp_path,
        "agy",
        """
print("I recommend Approach 1.")
print("Please let me know if you approve this approach or prefer another one!", flush=True)
""".strip(),
    )
    monkeypatch.setenv("MICA_ANTIGRAVITY_PATH", str(launcher))

    response = client.post(
        "/api/sessions",
        json={
            "prompt": "Write a snake game.",
            "workspace": str(tmp_path),
            "agent_type": "antigravity-cli",
            "runner_mode": "local",
        },
    )

    assert response.status_code == 201
    session_id = response.json()["session"]["id"]
    session_payload = _wait_for_session(client, session_id, "waiting_user_input")
    assert session_payload["status"] == "waiting_user_input"
    assert session_payload["last_run_id"] == response.json()["run"]["id"]
    run = client.get(f"/api/runs/{response.json()['run']['id']}").json()
    assert run["status"] == "completed"

    messages = client.get(f"/api/sessions/{session_id}/messages").json()
    assert messages[-1]["role"] == "agent"
    assert "Please let me know" in messages[-1]["content"]


def test_session_transcript_uses_assistant_text_not_raw_structured_events(
    client: TestClient,
    tmp_path: Path,
    monkeypatch,
) -> None:
    url, _, server = _start_fake_opencode_server("Please choose A or B.")
    monkeypatch.setenv("MICA_OPENCODE_SERVER_URL", url)

    try:
        response = client.post(
            "/api/sessions",
            json={
                "prompt": "Build a snake game.",
                "workspace": str(tmp_path),
                "agent_type": "opencode",
                "runner_mode": "local",
            },
        )

        assert response.status_code == 201
        session_id = response.json()["session"]["id"]
        _wait_for_session(client, session_id, "waiting_user_input")

        messages = client.get(f"/api/sessions/{session_id}/messages").json()
        agent_message = messages[-1]["content"]
        assert agent_message == "Please choose A or B."
        assert "<skill_content>" not in agent_message
        assert "runtime internals" not in agent_message

        continued = client.post(f"/api/sessions/{session_id}/continue", json={"message": "A"})
        assert continued.status_code == 200
        events = client.get(f"/api/events?run_id={continued.json()['run']['id']}").json()
        prompt_event = next(event for event in events if event["event_type"] == "agent_prompt")
        assert prompt_event["payload"]["prompt"] == "A"
    finally:
        server.shutdown()


def test_heuristic_choice_output_creates_pending_interaction(client: TestClient, tmp_path: Path, monkeypatch) -> None:
    launcher = _write_fake_agent(
        tmp_path,
        "agy",
        """
print("Which approach do you prefer?")
print("A. Browser Canvas")
print("B. Terminal UI", flush=True)
""".strip(),
    )
    monkeypatch.setenv("MICA_ANTIGRAVITY_PATH", str(launcher))

    response = client.post(
        "/api/sessions",
        json={
            "prompt": "Build a snake game.",
            "workspace": str(tmp_path),
            "agent_type": "antigravity-cli",
            "runner_mode": "local",
        },
    )

    assert response.status_code == 201
    session_id = response.json()["session"]["id"]
    _wait_for_session(client, session_id, "waiting_user_input")
    interactions = client.get(f"/api/sessions/{session_id}/interactions?status=pending").json()
    assert len(interactions) == 1
    assert interactions[0]["kind"] == "choice"
    assert interactions[0]["source"] == "heuristic"
    assert [option["id"] for option in interactions[0]["options"]] == ["A", "B"]


def test_respond_choice_interaction_continues_session(client: TestClient, tmp_path: Path, monkeypatch) -> None:
    launcher = _write_fake_agent(
        tmp_path,
        "agy",
        """
import sys
prompt = sys.argv[-1] if len(sys.argv) > 1 else ""
if prompt == "B":
    print("Terminal UI selected. Done.", flush=True)
else:
    print("Which approach do you prefer?")
    print("A. Browser Canvas")
    print("B. Terminal UI", flush=True)
""".strip(),
    )
    monkeypatch.setenv("MICA_ANTIGRAVITY_PATH", str(launcher))
    created = client.post(
        "/api/sessions",
        json={
            "prompt": "Build a snake game.",
            "workspace": str(tmp_path),
            "agent_type": "antigravity-cli",
            "runner_mode": "local",
        },
    ).json()
    session_id = created["session"]["id"]
    _wait_for_session(client, session_id, "waiting_user_input")
    interaction = client.get(f"/api/sessions/{session_id}/interactions?status=pending").json()[0]

    response = client.post(
        f"/api/session-interactions/{interaction['id']}/respond",
        json={"response": "B", "option_id": "B"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["action"] == "continued_session"
    assert payload["interaction"]["status"] == "responded"
    messages = client.get(f"/api/sessions/{session_id}/messages").json()
    assert messages[-1]["role"] == "user"
    assert messages[-1]["content"] == "B"


def test_respond_native_opencode_permission_calls_permission_endpoint(
    client: TestClient,
    tmp_path: Path,
    monkeypatch,
) -> None:
    url, state, server = _start_fake_opencode_server()
    monkeypatch.setenv("MICA_OPENCODE_SERVER_URL", url)

    try:
        with client.app.state.database.session_factory() as db:
            record = AgentSession(
                title="Permission test",
                workspace=str(tmp_path),
                agent_type="opencode",
                runner_mode="local",
                external_session_id="oc-session-123",
                backend_url=url,
                transport="http",
            )
            db.add(record)
            db.flush()
            interaction = InteractionService(db).create_native_permission(
                record,
                run_id=None,
                permission_id="perm-123",
                prompt="Allow bash command?",
            )
            db.commit()
            interaction_id = interaction.id

        response = client.post(
            f"/api/session-interactions/{interaction_id}/respond",
            json={"response": "approve", "remember": True},
        )

        assert response.status_code == 200
        assert state["permission_decisions"] == [{"response": "allow", "remember": True}]
        payload = response.json()
        assert payload["interaction"]["kind"] == "permission"
        assert payload["interaction"]["source"] == "native"
        assert payload["interaction"]["status"] == "responded"
    finally:
        server.shutdown()


def test_codex_session_transcript_keeps_text_messages_and_drops_runtime_events(
    client: TestClient,
    tmp_path: Path,
    monkeypatch,
) -> None:
    launcher = _write_fake_agent(
        tmp_path,
        "codex",
        """
import json

print(json.dumps({"type": "session_configured", "session_id": "fake-codex"}), flush=True)
print(json.dumps({"type": "exec_command_begin", "cmd": "git status --short"}), flush=True)
print(json.dumps({"type": "text", "message": "Codex answer: implementation complete."}), flush=True)
""".strip(),
    )
    monkeypatch.setenv("MICA_CODEX_PATH", str(launcher))

    response = client.post(
        "/api/sessions",
        json={
            "prompt": "Build a snake game.",
            "workspace": str(tmp_path),
            "agent_type": "codex-cli",
            "runner_mode": "local",
        },
    )

    assert response.status_code == 201
    session_id = response.json()["session"]["id"]
    _wait_for_session(client, session_id, "completed")

    messages = client.get(f"/api/sessions/{session_id}/messages").json()
    agent_message = messages[-1]["content"]
    assert agent_message == "Codex answer: implementation complete."
    assert "session_configured" not in agent_message
    assert "exec_command_begin" not in agent_message


def test_codex_session_uses_final_agent_message_instead_of_stderr_and_runtime_noise(
    client: TestClient,
    tmp_path: Path,
    monkeypatch,
) -> None:
    launcher = _write_fake_agent(
        tmp_path,
        "codex",
        """
import json
import sys

print("runtime warning " * 400, file=sys.stderr, flush=True)
print(json.dumps({"type": "thread.started", "thread_id": "codex-thread-1"}), flush=True)
print(json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "Working on it."}}), flush=True)
print(json.dumps({"type": "item.completed", "item": {"type": "command_execution", "command": "git status"}}), flush=True)
print(json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "Final answer: tank game created."}}), flush=True)
print(json.dumps({"type": "turn.completed", "usage": {"input_tokens": 100, "output_tokens": 20}}), flush=True)
""".strip(),
    )
    monkeypatch.setenv("MICA_CODEX_PATH", str(launcher))

    response = client.post(
        "/api/sessions",
        json={
            "prompt": "Build a tank game.",
            "workspace": str(tmp_path),
            "agent_type": "codex-cli",
            "runner_mode": "local",
        },
    )

    assert response.status_code == 201
    session_id = response.json()["session"]["id"]
    session_payload = _wait_for_session(client, session_id, "completed")
    messages = client.get(f"/api/sessions/{session_id}/messages").json()

    assert messages[-1]["content"] == "Final answer: tank game created."
    assert session_payload["summary"] == "Final answer: tank game created."
