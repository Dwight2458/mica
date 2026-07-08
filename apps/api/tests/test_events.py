from __future__ import annotations

from fastapi.testclient import TestClient


def test_events_are_written_for_run_and_command_lifecycle(client: TestClient) -> None:
    run = client.post("/api/runs", json={"source": "opencode", "cwd": "C:\\repo"}).json()
    command = client.post(
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
    ).json()

    client.patch(
        f"/api/commands/{command['id']}/finish",
        json={"status": "completed", "exit_code": 0, "duration_ms": 42},
    )
    client.patch(f"/api/runs/{run['id']}/finish")

    response = client.get(f"/api/events?run_id={run['id']}")

    assert response.status_code == 200
    assert [event["event_type"] for event in response.json()] == [
        "run_created",
        "command_started",
        "command_finished",
        "run_completed",
    ]
    assert response.json()[2]["payload"] == {
        "command_line": "git status",
        "command_origin": "external_binary",
        "duration_ms": 42,
        "exit_code": 0,
        "status": "completed",
    }


def test_events_capture_approval_required_and_decision(client: TestClient) -> None:
    run = client.post("/api/runs", json={"source": "opencode", "cwd": "C:\\repo"}).json()
    approval = client.post(
        "/api/approvals",
        json={
            "tool": "git",
            "argv": ["push", "origin", "main"],
            "command_line": "git push origin main",
            "cwd": "C:\\repo",
            "risk_level": "high",
            "reason": "git push may publish code to a remote repository.",
        },
    ).json()
    client.post(
        "/api/commands",
        json={
            "run_id": run["id"],
            "tool": "git",
            "argv": ["push", "origin", "main"],
            "command_line": "git push origin main",
            "cwd": "C:\\repo",
            "risk_level": "high",
            "requires_approval": True,
            "approval_id": approval["id"],
        },
    )
    client.post(
        f"/api/approvals/{approval['id']}/decide",
        json={"decision": "rejected", "resolved_by": "web", "comment": "too risky"},
    )

    response = client.get(f"/api/events?run_id={run['id']}")

    assert response.status_code == 200
    assert [event["event_type"] for event in response.json()] == [
        "run_created",
        "approval_required",
        "approval_rejected",
    ]
    assert response.json()[1]["approval_id"] == approval["id"]
    assert response.json()[2]["payload"] == {"comment": "too risky", "resolved_by": "web"}
