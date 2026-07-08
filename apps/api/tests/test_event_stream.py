from __future__ import annotations

from fastapi.testclient import TestClient


def test_event_stream_replays_existing_events_as_sse(client: TestClient) -> None:
    run = client.post("/api/runs", json={"source": "opencode", "cwd": "C:\\repo"}).json()
    client.post(
        "/api/commands",
        json={
            "run_id": run["id"],
            "tool": "git",
            "argv": ["status"],
            "command_line": "git status",
            "cwd": "C:\\repo",
            "risk_level": "low",
            "requires_approval": False,
            "approval_id": None,
        },
    )

    response = client.get(f"/api/events/stream?run_id={run['id']}&replay=true")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: run_created" in response.text
    assert "event: command_started" in response.text
    assert '"command_line":"git status"' in response.text
