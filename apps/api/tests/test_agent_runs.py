from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from fastapi.testclient import TestClient


def _write_fake_opencode(tmp_path: Path, body: str) -> Path:
    script = tmp_path / "fake_opencode.py"
    script.write_text(body, encoding="utf-8")
    launcher = tmp_path / "opencode.cmd"
    launcher.write_text(f'@echo off\r\n"{sys.executable}" "{script}" %*\r\n', encoding="utf-8")
    return launcher


def _wait_for_run(client: TestClient, run_id: str, *statuses: str) -> dict:
    deadline = time.time() + 5
    while time.time() < deadline:
        payload = client.get(f"/api/runs/{run_id}").json()
        if payload["status"] in statuses:
            return payload
        time.sleep(0.05)
    raise AssertionError(f"Run {run_id} did not reach {statuses}")


def test_agent_run_accepts_natural_language_prompt_and_records_trace(client: TestClient) -> None:
    response = client.post(
        "/api/agent-runs",
        json={
            "prompt": "Check git status and summarize uncommitted changes.",
            "workspace": "C:\\repo",
            "agent_type": "mock-agent",
            "runner_mode": "local",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["run"]["source"] == "mock-agent"
    assert payload["run"]["cwd"] == "C:\\repo"
    assert payload["run"]["status"] == "completed"
    assert payload["prompt"] == "Check git status and summarize uncommitted changes."
    assert payload["agent_type"] == "mock-agent"
    assert payload["runner_mode"] == "local"
    assert payload["planned_command"] == ["git", "status", "--short"]

    commands = client.get(f"/api/commands?run_id={payload['run']['id']}").json()
    assert len(commands) == 1
    assert commands[0]["command_line"] == "git status --short"
    assert commands[0]["status"] == "completed"

    events = client.get(f"/api/events?run_id={payload['run']['id']}").json()
    assert [event["event_type"] for event in events] == [
        "run_created",
        "agent_prompt",
        "plan_created",
        "command_started",
        "command_output",
        "command_finished",
        "run_completed",
    ]
    assert events[1]["payload"]["prompt"] == "Check git status and summarize uncommitted changes."
    assert events[2]["payload"]["planned_command"] == ["git", "status", "--short"]
    assert "mock-agent planned" in events[4]["payload"]["text"]


def test_opencode_agent_run_starts_real_cli_and_records_json_events(
    client: TestClient,
    tmp_path: Path,
    monkeypatch,
) -> None:
    launcher = _write_fake_opencode(
        tmp_path,
        """
import json
import sys

print(json.dumps({"type": "thread.started", "sessionID": "fake-session"}), flush=True)
print(json.dumps({"type": "text", "part": {"text": "agent saw prompt: " + sys.argv[-1]}}), flush=True)
""".strip(),
    )
    monkeypatch.setenv("MICA_OPENCODE_PATH", str(launcher))

    response = client.post(
        "/api/agent-runs",
        json={
            "prompt": "Check git status and summarize it.",
            "workspace": str(tmp_path),
            "agent_type": "opencode",
            "runner_mode": "local",
        },
    )

    assert response.status_code == 201
    run_id = response.json()["run"]["id"]
    run = _wait_for_run(client, run_id, "completed")
    assert run["source"] == "opencode"

    events = client.get(f"/api/events?run_id={run_id}").json()
    event_types = [event["event_type"] for event in events]
    assert "agent_prompt" in event_types
    assert "plan_created" in event_types
    assert "command_output" in event_types
    assert "run_completed" in event_types
    assert any(event["payload"].get("raw_event", {}).get("type") == "thread.started" for event in events)
    assert any("agent saw prompt" in event["payload"].get("text", "") for event in events)


def test_opencode_agent_run_marks_failed_on_nonzero_exit(
    client: TestClient,
    tmp_path: Path,
    monkeypatch,
) -> None:
    launcher = _write_fake_opencode(
        tmp_path,
        """
import json
import sys

print(json.dumps({"type": "error", "message": "model quota failed"}), flush=True)
print("stderr failure", file=sys.stderr, flush=True)
sys.exit(7)
""".strip(),
    )
    monkeypatch.setenv("MICA_OPENCODE_PATH", str(launcher))

    response = client.post(
        "/api/agent-runs",
        json={
            "prompt": "Do a failing run.",
            "workspace": str(tmp_path),
            "agent_type": "opencode",
            "runner_mode": "local",
        },
    )

    assert response.status_code == 201
    run_id = response.json()["run"]["id"]
    run = _wait_for_run(client, run_id, "failed")
    assert run["status"] == "failed"

    events = client.get(f"/api/events?run_id={run_id}").json()
    assert any(event["event_type"] == "command_output" and event["payload"].get("stream") == "stderr" for event in events)
    assert events[-1]["event_type"] == "run_failed"


def test_opencode_tool_use_high_risk_without_proxy_records_unintercepted_warning(
    client: TestClient,
    tmp_path: Path,
    monkeypatch,
) -> None:
    launcher = _write_fake_opencode(
        tmp_path,
        """
import json

print(json.dumps({
    "type": "tool_use",
    "part": {
        "tool": "shell",
        "state": {
            "status": "completed",
            "input": {"command": "git push origin main"}
        }
    }
}), flush=True)
""".strip(),
    )
    monkeypatch.setenv("MICA_OPENCODE_PATH", str(launcher))

    response = client.post(
        "/api/agent-runs",
        json={
            "prompt": "Push changes.",
            "workspace": str(tmp_path),
            "agent_type": "opencode",
            "runner_mode": "local",
        },
    )

    assert response.status_code == 201
    run_id = response.json()["run"]["id"]
    _wait_for_run(client, run_id, "completed")

    events = client.get(f"/api/events?run_id={run_id}").json()
    warnings = [
        event
        for event in events
        if event["event_type"] == "policy_decision"
        and event["payload"].get("decision") == "unintercepted"
    ]
    assert len(warnings) == 1
    assert "git push origin main" in warnings[0]["payload"]["command_line"]


def test_opencode_run_can_be_cancelled(client: TestClient, tmp_path: Path, monkeypatch) -> None:
    launcher = _write_fake_opencode(
        tmp_path,
        """
import time

print("started", flush=True)
time.sleep(10)
""".strip(),
    )
    monkeypatch.setenv("MICA_OPENCODE_PATH", str(launcher))

    response = client.post(
        "/api/agent-runs",
        json={
            "prompt": "Long running task.",
            "workspace": str(tmp_path),
            "agent_type": "opencode",
            "runner_mode": "local",
        },
    )
    assert response.status_code == 201
    run_id = response.json()["run"]["id"]

    cancel = client.post(f"/api/agent-runs/{run_id}/cancel")

    assert cancel.status_code == 200
    run = _wait_for_run(client, run_id, "cancelled")
    assert run["status"] == "cancelled"
    time.sleep(0.2)
    events = client.get(f"/api/events?run_id={run_id}").json()
    terminal_events = [event for event in events if event["event_type"] in {"run_completed", "run_failed"}]
    assert len(terminal_events) == 1


def test_agent_run_agents_endpoint_reports_opencode_availability(
    client: TestClient,
    tmp_path: Path,
    monkeypatch,
) -> None:
    launcher = _write_fake_opencode(tmp_path, "print('ok')")
    monkeypatch.setenv("MICA_OPENCODE_PATH", str(launcher))

    response = client.get("/api/agent-runs/agents")

    assert response.status_code == 200
    payload = response.json()
    assert payload["agents"][0]["agent_type"] == "mock-agent"
    opencode = next(agent for agent in payload["agents"] if agent["agent_type"] == "opencode")
    assert opencode["available"] is True
    assert opencode["executable"] == str(launcher)
