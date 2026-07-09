from __future__ import annotations

from fastapi.testclient import TestClient

from app.models.enums import CommandStatus, RunStatus
from app.schemas.commands import CommandRecordCreate
from app.schemas.runs import RunRecordCreate
from app.services.command_service import CommandService
from app.services.run_service import RunService


def test_run_summary_counts_commands_and_approvals(client: TestClient) -> None:
    run_response = client.post("/api/runs", json={"source": "opencode", "cwd": "C:\\repo"})
    assert run_response.status_code == 201
    run_id = run_response.json()["id"]

    client.post(
        "/api/commands",
        json={
            "run_id": run_id,
            "tool": "git",
            "argv": ["status"],
            "command_line": "git status",
            "cwd": "C:\\repo",
            "risk_level": "low",
            "requires_approval": False,
            "approval_id": None,
        },
    )
    approval_response = client.post(
        "/api/approvals",
        json={
            "tool": "git",
            "argv": ["push", "origin", "main"],
            "command_line": "git push origin main",
            "cwd": "C:\\repo",
            "risk_level": "high",
            "reason": "git push may publish code to a remote repository.",
        },
    )
    client.post(
        "/api/commands",
        json={
            "run_id": run_id,
            "tool": "git",
            "argv": ["push", "origin", "main"],
            "command_line": "git push origin main",
            "cwd": "C:\\repo",
            "risk_level": "high",
            "requires_approval": True,
            "approval_id": approval_response.json()["id"],
        },
    )

    for command in client.get("/api/commands").json():
        status = "completed" if command["command_line"] == "git status" else "rejected"
        exit_code = 0 if status == "completed" else 126
        finish_response = client.patch(
            f"/api/commands/{command['id']}/finish",
            json={"status": status, "exit_code": exit_code, "duration_ms": 25},
        )
        assert finish_response.status_code == 200

    finish_run = client.patch("/api/runs/" + run_id + "/finish")
    assert finish_run.status_code == 200

    summary = client.get("/api/runs/" + run_id + "/summary")
    assert summary.status_code == 200
    assert summary.json() == {
        "run_id": run_id,
        "source": "opencode",
        "status": "failed",
        "cwd": "C:\\repo",
        "total_commands": 2,
        "agent_tool_commands": 0,
        "runtime_internal_commands": 0,
        "governed_commands": 2,
        "successful_governed_commands": 1,
        "successful_commands": 1,
        "failed_commands": 1,
        "approval_count": 1,
        "rejected_count": 1,
        "risky_command_count": 1,
        "total_duration_ms": 50,
        "failure_summary": {
            "failed_command": "git push origin main",
            "exit_code": 126,
            "reason": "Command was rejected or failed.",
            "suggested_next_action": "Review the command, approval decision, and agent prompt before retrying.",
        },
    }


def test_list_runs_returns_recent_runs(client: TestClient) -> None:
    first = client.post("/api/runs", json={"source": "manual", "cwd": "C:\\repo-a"}).json()
    second = client.post("/api/runs", json={"source": "codex", "cwd": "C:\\repo-b"}).json()

    response = client.get("/api/runs")

    assert response.status_code == 200
    assert [run["id"] for run in response.json()] == [second["id"], first["id"]]


def test_finish_with_completed_status_preserves_failed_agent_command(client: TestClient) -> None:
    run_response = client.post("/api/runs", json={"source": "opencode", "cwd": "C:\\repo"})
    assert run_response.status_code == 201
    run_id = run_response.json()["id"]

    command_response = client.post(
        "/api/commands",
        json={
            "run_id": run_id,
            "tool": "git",
            "argv": ["push", "origin", "main"],
            "command_line": "git push origin main",
            "cwd": "C:\\repo",
            "risk_level": "low",
            "requires_approval": False,
            "approval_id": None,
        },
    )
    assert command_response.status_code == 201
    finish_command = client.patch(
        f"/api/commands/{command_response.json()['id']}/finish",
        json={"status": "failed", "exit_code": 2, "duration_ms": 10},
    )
    assert finish_command.status_code == 200

    finish_run = client.patch("/api/runs/" + run_id + "/finish")
    assert finish_run.status_code == 200
    assert finish_run.json()["status"] == "failed"


def test_finish_with_status_completed_preserves_rejected_agent_command(client: TestClient) -> None:
    run_response = client.post("/api/runs", json={"source": "opencode", "cwd": "C:\\repo"})
    assert run_response.status_code == 201
    run_id = run_response.json()["id"]

    command_response = client.post(
        "/api/commands",
        json={
            "run_id": run_id,
            "tool": "git",
            "argv": ["push", "origin", "main"],
            "command_line": "git push origin main",
            "cwd": "C:\\repo",
            "risk_level": "high",
            "requires_approval": True,
            "approval_id": "approval-1",
        },
    )
    assert command_response.status_code == 201
    finish_command = client.patch(
        f"/api/commands/{command_response.json()['id']}/finish",
        json={"status": "rejected", "exit_code": 126, "duration_ms": 10},
    )
    assert finish_command.status_code == 200

    with client.app.state.database.session_factory() as session:
        run = RunService(session).finish_with_status(run_id, status=RunStatus.COMPLETED)
        assert run is not None
        assert run.status == RunStatus.FAILED


def test_finish_with_status_completed_allows_recovered_low_risk_agent_command_failure(client: TestClient) -> None:
    with client.app.state.database.session_factory() as session:
        run = RunService(session).create(RunRecordCreate(source="opencode", cwd="C:\\repo"))
        command = CommandService(session).create(
            CommandRecordCreate(
                run_id=run.id,
                tool="git",
                argv=["log", "--oneline", "-5"],
                command_line="git log --oneline -5",
                cwd="C:\\repo",
                risk_level="low",
                requires_approval=False,
                approval_id=None,
            )
        )
        command.command_origin = "agent_tool"
        CommandService(session).finish(command.id, status=CommandStatus.FAILED, exit_code=128, duration_ms=10)

        finished = RunService(session).finish_with_status(run.id, status=RunStatus.COMPLETED)
        summary = RunService(session).summary(run.id)

        assert finished is not None
        assert summary is not None
        assert finished.status == RunStatus.COMPLETED
        assert summary.status == RunStatus.COMPLETED
        assert summary.agent_tool_commands == 1
        assert summary.failed_commands == 1
        assert summary.failure_summary is None


def test_semicolon_delimited_opencode_tool_command_marks_child_commands_as_agent_tools(client: TestClient) -> None:
    with client.app.state.database.session_factory() as session:
        run = RunService(session).create(RunRecordCreate(source="opencode", cwd="C:\\repo"))
        for command_line in ["git status", "git diff --stat", "git log --oneline -5"]:
            CommandService(session).create(
                CommandRecordCreate(
                    run_id=run.id,
                    tool="git",
                    argv=command_line.split()[1:],
                    command_line=command_line,
                    cwd="C:\\repo",
                    risk_level="low",
                    requires_approval=False,
                    approval_id=None,
                )
            )

        CommandService(session).mark_agent_tool_command(run.id, "git status; git diff --stat; git log --oneline -5")
        summary = RunService(session).summary(run.id)

        assert summary is not None
        assert summary.agent_tool_commands == 3


def test_opencode_tool_command_matching_ignores_single_vs_double_quotes(client: TestClient) -> None:
    with client.app.state.database.session_factory() as session:
        run = RunService(session).create(RunRecordCreate(source="opencode", cwd="C:\\repo"))
        CommandService(session).create(
            CommandRecordCreate(
                run_id=run.id,
                tool="git",
                argv=["commit", "-m", "Add test.txt"],
                command_line="git commit -m 'Add test.txt'",
                cwd="C:\\repo",
                risk_level="low",
                requires_approval=False,
                approval_id=None,
            )
        )

        CommandService(session).mark_agent_tool_command(run.id, 'git commit -m "Add test.txt"')
        summary = RunService(session).summary(run.id)

        assert summary is not None
        assert summary.agent_tool_commands == 1


def test_opencode_runtime_internal_commands_do_not_fail_agent_run(client: TestClient) -> None:
    with client.app.state.database.session_factory() as session:
        run = RunService(session).create(RunRecordCreate(source="opencode", cwd="C:\\repo"))
        runtime = CommandService(session).create(
            CommandRecordCreate(
                run_id=run.id,
                tool="git",
                argv=["remote", "get-url", "origin"],
                command_line="git remote get-url origin",
                cwd="C:\\repo",
                risk_level="low",
                requires_approval=False,
                approval_id=None,
            )
        )
        agent_tool = CommandService(session).create(
            CommandRecordCreate(
                run_id=run.id,
                tool="git",
                argv=["status"],
                command_line="git status",
                cwd="C:\\repo",
                risk_level="low",
                requires_approval=False,
                approval_id=None,
            )
        )
        CommandService(session).mark_agent_tool_command(run.id, "git status")
        CommandService(session).finish(runtime.id, status=CommandStatus.FAILED, exit_code=2, duration_ms=10)
        CommandService(session).finish(agent_tool.id, status=CommandStatus.COMPLETED, exit_code=0, duration_ms=20)
        finished = RunService(session).finish_with_status(run.id, status=RunStatus.COMPLETED)
        summary = RunService(session).summary(run.id)

        assert finished is not None
        assert summary is not None
        assert finished.status == RunStatus.COMPLETED
        assert summary.status == RunStatus.COMPLETED
        assert summary.total_commands == 2
        assert summary.agent_tool_commands == 1
        assert summary.runtime_internal_commands == 1
        assert summary.governed_commands == 1
        assert summary.successful_governed_commands == 1
        assert summary.failed_commands == 0
        assert summary.failure_summary is None


def test_opencode_snapshot_command_is_classified_as_runtime_internal(client: TestClient) -> None:
    with client.app.state.database.session_factory() as session:
        run = RunService(session).create(RunRecordCreate(source="opencode", cwd="C:\\repo"))
        command = CommandService(session).create(
            CommandRecordCreate(
                run_id=run.id,
                tool="git",
                argv=[
                    "--git-dir",
                    "C:\\Users\\24582\\.local\\share\\opencode\\snapshot\\global\\abc",
                    "--work-tree",
                    "C:\\repo",
                    "diff-files",
                ],
                command_line=(
                    "git --git-dir 'C:\\Users\\24582\\.local\\share\\opencode\\snapshot\\global\\abc' "
                    "--work-tree C:\\repo diff-files"
                ),
                cwd="C:\\repo",
                risk_level="low",
                requires_approval=False,
                approval_id=None,
            )
        )

        assert command.command_origin == "runtime_internal"


def test_opencode_housekeeping_git_commands_are_classified_as_runtime_internal(client: TestClient) -> None:
    with client.app.state.database.session_factory() as session:
        run = RunService(session).create(RunRecordCreate(source="opencode", cwd="C:\\repo"))
        command_lines = [
            "git init",
            "git worktree list --porcelain",
            "git -c core.autocrlf=false --git-dir 'C:\\repo\\.git' --work-tree 'C:\\repo' check-ignore --no-index --stdin -z",
        ]
        for command_line in command_lines:
            command = CommandService(session).create(
                CommandRecordCreate(
                    run_id=run.id,
                    tool="git",
                    argv=command_line.split()[1:],
                    command_line=command_line,
                    cwd="C:\\repo",
                    risk_level="low",
                    requires_approval=False,
                    approval_id=None,
                )
            )
            assert command.command_origin == "runtime_internal"


def test_antigravity_git_merge_base_is_classified_as_runtime_internal(client: TestClient) -> None:
    with client.app.state.database.session_factory() as session:
        run = RunService(session).create(RunRecordCreate(source="antigravity-cli", cwd="C:\\repo"))
        command = CommandService(session).create(
            CommandRecordCreate(
                run_id=run.id,
                tool="git",
                argv=["merge-base", "HEAD", "origin/main"],
                command_line="git merge-base HEAD origin/main",
                cwd="C:\\repo",
                risk_level="low",
                requires_approval=False,
                approval_id=None,
            )
        )
        CommandService(session).finish(command.id, status=CommandStatus.FAILED, exit_code=128, duration_ms=20)
        summary = RunService(session).summary(run.id)

        assert command.command_origin == "runtime_internal"
        assert summary is not None
        assert summary.runtime_internal_commands == 1
        assert summary.governed_commands == 0
        assert summary.successful_governed_commands == 0
