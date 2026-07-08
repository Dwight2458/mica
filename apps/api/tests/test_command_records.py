from __future__ import annotations

from fastapi.testclient import TestClient


def create_command_record(client: TestClient) -> dict:
    response = client.post(
        "/api/commands",
        json={
            "tool": "git",
            "argv": ["status"],
            "command_line": "git status",
            "cwd": "C:\\repo",
            "risk_level": "low",
            "requires_approval": False,
            "approval_id": None,
        },
    )
    assert response.status_code == 201
    return response.json()


def test_command_record_can_be_created_listed_and_read(client: TestClient) -> None:
    record = create_command_record(client)

    assert record["status"] == "started"
    assert record["tool"] == "git"
    assert record["argv"] == ["status"]
    assert record["command_line"] == "git status"
    assert record["requires_approval"] is False
    assert record["approval_id"] is None
    assert record["exit_code"] is None
    assert record["duration_ms"] is None

    listed = client.get("/api/commands").json()
    assert [item["id"] for item in listed] == [record["id"]]

    fetched = client.get(f"/api/commands/{record['id']}").json()
    assert fetched["id"] == record["id"]


def test_command_record_can_be_finished(client: TestClient) -> None:
    record = create_command_record(client)

    response = client.patch(
        f"/api/commands/{record['id']}/finish",
        json={"status": "completed", "exit_code": 0, "duration_ms": 42},
    )

    assert response.status_code == 200
    finished = response.json()
    assert finished["status"] == "completed"
    assert finished["exit_code"] == 0
    assert finished["duration_ms"] == 42
    assert finished["finished_at"] is not None


def test_command_record_can_reference_approval(client: TestClient) -> None:
    approval_response = client.post(
        "/api/approvals",
        json={
            "tool": "git",
            "argv": ["push", "origin", "main"],
            "command_line": "git push origin main",
            "cwd": "C:\\repo",
            "risk_level": "high",
            "reason": "git push can publish local changes to a remote repository.",
        },
    )
    approval = approval_response.json()

    response = client.post(
        "/api/commands",
        json={
            "tool": "git",
            "argv": ["push", "origin", "main"],
            "command_line": "git push origin main",
            "cwd": "C:\\repo",
            "risk_level": "high",
            "requires_approval": True,
            "approval_id": approval["id"],
        },
    )

    assert response.status_code == 201
    record = response.json()
    assert record["approval_id"] == approval["id"]
    assert record["requires_approval"] is True


def test_command_records_can_be_filtered_by_run_id(client: TestClient) -> None:
    first_run = client.post("/api/runs", json={"source": "docker", "cwd": "C:\\repo-a"}).json()
    second_run = client.post("/api/runs", json={"source": "docker", "cwd": "C:\\repo-b"}).json()

    first_command = client.post(
        "/api/commands",
        json={
            "run_id": first_run["id"],
            "tool": "docker",
            "argv": ["run", "image"],
            "command_line": "docker run image",
            "cwd": "C:\\repo-a",
            "risk_level": "low",
            "requires_approval": False,
            "approval_id": None,
        },
    ).json()
    client.post(
        "/api/commands",
        json={
            "run_id": second_run["id"],
            "tool": "git",
            "argv": ["status"],
            "command_line": "git status",
            "cwd": "C:\\repo-b",
            "risk_level": "low",
            "requires_approval": False,
            "approval_id": None,
        },
    )

    response = client.get(f"/api/commands?run_id={first_run['id']}")

    assert response.status_code == 200
    assert [record["id"] for record in response.json()] == [first_command["id"]]
