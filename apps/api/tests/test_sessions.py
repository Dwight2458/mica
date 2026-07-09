from __future__ import annotations

import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient


def _write_fake_agent(tmp_path: Path, name: str, body: str) -> Path:
    script = tmp_path / f"fake_{name}.py"
    script.write_text(body, encoding="utf-8")
    launcher = tmp_path / f"{name}.cmd"
    launcher.write_text(f'@echo off\r\n"{sys.executable}" "{script}" %*\r\n', encoding="utf-8")
    return launcher


def _wait_for_session(client: TestClient, session_id: str, *statuses: str) -> dict:
    deadline = time.time() + 5
    while time.time() < deadline:
        payload = client.get(f"/api/sessions/{session_id}").json()
        if payload["status"] in statuses:
            return payload
        time.sleep(0.05)
    raise AssertionError(f"Session {session_id} did not reach {statuses}")


def _start_fake_opencode_server(response_text: str = "Need choice.") -> tuple[str, dict[str, Any], ThreadingHTTPServer]:
    state: dict[str, Any] = {"requests": [], "response_text": response_text}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/global/health":
                self._json({"healthy": True, "version": "fake"})
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
            if self.path == "/session/oc-session-123/message":
                self._json(
                    {
                        "id": "assistant-message-1",
                        "parts": [{"type": "text", "text": state["response_text"]}],
                    }
                )
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
        messages = client.get(f"/api/sessions/{session_id}/messages").json()
        continued_user_message = messages[-2]
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
        assert state["requests"][1]["path"] == "/session/oc-session-123/message"
        assert state["requests"][1]["body"]["parts"] == [{"type": "text", "text": "Plan a browser game."}]
        assert state["requests"][2]["body"]["parts"] == [{"type": "text", "text": "A"}]
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
