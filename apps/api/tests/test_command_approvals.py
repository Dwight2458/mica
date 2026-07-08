from __future__ import annotations

from fastapi.testclient import TestClient


def create_command_approval(client: TestClient) -> dict:
    response = client.post(
        "/api/approvals",
        json={
            "tool": "git",
            "argv": ["push", "origin", "main"],
            "command_line": "git push origin main",
            "cwd": "C:\\repo",
            "risk_level": "high",
            "reason": "git push requires human approval",
        },
    )
    assert response.status_code == 201
    return response.json()


def test_command_approval_can_be_created_listed_and_read(client: TestClient) -> None:
    approval = create_command_approval(client)

    assert approval["status"] == "pending"
    assert approval["tool"] == "git"
    assert approval["argv"] == ["push", "origin", "main"]
    assert approval["command_line"] == "git push origin main"
    assert approval["cwd"] == "C:\\repo"
    assert approval["risk_level"] == "high"
    assert approval["reason"] == "git push requires human approval"

    pending = client.get("/api/approvals?status=pending").json()
    assert [item["id"] for item in pending] == [approval["id"]]

    fetched = client.get(f"/api/approvals/{approval['id']}").json()
    assert fetched["id"] == approval["id"]


def test_command_approval_decision_updates_status_and_resolver(client: TestClient) -> None:
    approval = create_command_approval(client)

    response = client.post(
        f"/api/approvals/{approval['id']}/decide",
        json={"decision": "approved", "resolved_by": "web", "comment": "local bare repo test"},
    )

    assert response.status_code == 200
    decided = response.json()
    assert decided["status"] == "approved"
    assert decided["resolved_by"] == "web"
    assert decided["comment"] == "local bare repo test"
    assert decided["resolved_at"] is not None


def test_rejecting_command_approval_is_persisted(client: TestClient) -> None:
    approval = create_command_approval(client)

    response = client.post(
        f"/api/approvals/{approval['id']}/decide",
        json={"decision": "rejected", "resolved_by": "web", "comment": "too risky"},
    )

    assert response.status_code == 200
    decided = response.json()
    assert decided["status"] == "rejected"
    assert client.get(f"/api/approvals/{approval['id']}").json()["status"] == "rejected"
