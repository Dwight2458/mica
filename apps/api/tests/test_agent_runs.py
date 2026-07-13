from __future__ import annotations

import os
import sys
import time
from datetime import timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from app.runners.agent_adapters import AntigravityCliAdapter, CodexCliAdapter
from app.models.approval import utcnow
from app.models.enums import AgentSessionStatus
from app.models.run import RunRecord
from app.models.session import AgentSession


def _write_fake_opencode(tmp_path: Path, body: str) -> Path:
    script = tmp_path / "fake_opencode.py"
    script.write_text(body, encoding="utf-8")
    launcher = tmp_path / "opencode.cmd"
    launcher.write_text(f'@echo off\r\n"{sys.executable}" "{script}" %*\r\n', encoding="utf-8")
    return launcher


def _write_fake_codex(tmp_path: Path, body: str) -> Path:
    script = tmp_path / "fake_codex.py"
    script.write_text(body, encoding="utf-8")
    launcher = tmp_path / "codex.cmd"
    launcher.write_text(f'@echo off\r\n"{sys.executable}" "{script}" %*\r\n', encoding="utf-8")
    return launcher


def _write_fake_antigravity(tmp_path: Path, body: str) -> Path:
    script = tmp_path / "fake_antigravity.py"
    script.write_text(body, encoding="utf-8")
    launcher = tmp_path / "agy.cmd"
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


def test_codex_agent_run_starts_cli_and_records_json_events(
    client: TestClient,
    tmp_path: Path,
    monkeypatch,
) -> None:
    launcher = _write_fake_codex(
        tmp_path,
        """
import json
import sys

assert sys.argv[1:4] == ["exec", "--json", "--cd"], sys.argv
assert sys.argv[4] in sys.argv, sys.argv
assert sys.argv[-1] == "Check git status and summarize it.", sys.argv
assert "--skip-git-repo-check" in sys.argv, sys.argv
assert "approval_policy=\\\"never\\\"" in sys.argv, sys.argv
assert "shell_environment_policy.inherit=all" in sys.argv, sys.argv
print(json.dumps({"type": "session_configured", "session_id": "fake-codex-session"}), flush=True)
print(json.dumps({"type": "text", "message": "codex saw prompt: " + sys.argv[-1]}), flush=True)
""".strip(),
    )
    monkeypatch.setenv("MICA_CODEX_PATH", str(launcher))

    response = client.post(
        "/api/agent-runs",
        json={
            "prompt": "Check git status and summarize it.",
            "workspace": str(tmp_path),
            "agent_type": "codex-cli",
            "runner_mode": "local",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    run_id = payload["run"]["id"]
    run = _wait_for_run(client, run_id, "completed")
    assert run["source"] == "codex-cli"
    assert payload["planned_command"][:4] == [str(launcher), "exec", "--json", "--cd"]

    events = client.get(f"/api/events?run_id={run_id}").json()
    assert any(event["payload"].get("raw_event", {}).get("type") == "session_configured" for event in events)
    assert any("codex saw prompt" in event["payload"].get("text", "") for event in events)


def test_antigravity_agent_run_starts_cli_and_records_text_events(
    client: TestClient,
    tmp_path: Path,
    monkeypatch,
) -> None:
    launcher = _write_fake_antigravity(
        tmp_path,
        f"""
import os
import sys

assert sys.argv[1] == "--print", sys.argv
assert sys.argv[2] == "Check git status and summarize it.", sys.argv
assert "--add-dir" in sys.argv, sys.argv
assert sys.argv[sys.argv.index("--add-dir") + 1] == {str(tmp_path)!r}, sys.argv
assert "--mode" in sys.argv, sys.argv
assert sys.argv[sys.argv.index("--mode") + 1] == "accept-edits", sys.argv
assert "--print-timeout" in sys.argv, sys.argv
assert os.getcwd() == {str(tmp_path)!r}, (os.getcwd(), sys.argv)
print("antigravity saw prompt: " + sys.argv[2], flush=True)
""".strip(),
    )
    monkeypatch.setenv("MICA_ANTIGRAVITY_PATH", str(launcher))

    response = client.post(
        "/api/agent-runs",
        json={
            "prompt": "Check git status and summarize it.",
            "workspace": str(tmp_path),
            "agent_type": "antigravity-cli",
            "runner_mode": "local",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    run_id = payload["run"]["id"]
    run = _wait_for_run(client, run_id, "completed")
    assert run["source"] == "antigravity-cli"
    assert payload["planned_command"] == [
        str(launcher),
        "--print",
        "Check git status and summarize it.",
        "--add-dir",
        str(tmp_path),
        "--mode",
        "accept-edits",
        "--print-timeout",
        "10m",
    ]

    events = client.get(f"/api/events?run_id={run_id}").json()
    assert any("antigravity saw prompt" in event["payload"].get("text", "") for event in events)


def test_codex_adapter_prefers_windows_cmd_launcher(tmp_path: Path, monkeypatch) -> None:
    extensionless = tmp_path / "codex"
    extensionless.write_text("not directly executable on Windows", encoding="utf-8")
    launcher = tmp_path / "codex.cmd"
    launcher.write_text("@echo off\r\necho ok\r\n", encoding="utf-8")
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.delenv("MICA_CODEX_PATH", raising=False)

    executable = CodexCliAdapter().find_executable()

    if os.name == "nt":
        assert executable.lower() == str(launcher).lower()
    else:
        assert executable == str(extensionless)


def test_codex_adapter_uses_configurable_sandbox(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MICA_CODEX_SANDBOX", "read-only")

    command = CodexCliAdapter().build_command("codex.cmd", "Say OK.", str(tmp_path))

    assert command[command.index("--sandbox") + 1] == "read-only"


def test_codex_adapter_defaults_to_windows_compatible_sandbox(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("MICA_CODEX_SANDBOX", raising=False)

    command = CodexCliAdapter().build_command("codex.cmd", "Say OK.", str(tmp_path))

    expected = "danger-full-access" if os.name == "nt" else "workspace-write"
    assert command[command.index("--sandbox") + 1] == expected


def test_agent_process_reads_stderr_without_deadlocking(
    client: TestClient,
    tmp_path: Path,
    monkeypatch,
) -> None:
    launcher = _write_fake_opencode(
        tmp_path,
        """
import json
import sys

sys.stderr.write("x" * 200000 + "\\n")
sys.stderr.flush()
print(json.dumps({"type": "text", "part": {"text": "stdout survived stderr flood"}}), flush=True)
""".strip(),
    )
    monkeypatch.setenv("MICA_OPENCODE_PATH", str(launcher))

    response = client.post(
        "/api/agent-runs",
        json={
            "prompt": "Exercise stderr flood.",
            "workspace": str(tmp_path),
            "agent_type": "opencode",
            "runner_mode": "local",
        },
    )

    assert response.status_code == 201
    run_id = response.json()["run"]["id"]
    _wait_for_run(client, run_id, "completed")

    events = client.get(f"/api/events?run_id={run_id}").json()
    assert any(event["payload"].get("stream") == "stderr" for event in events)
    assert any("stdout survived stderr flood" in event["payload"].get("text", "") for event in events)


def test_agent_run_emits_file_changed_while_process_is_still_running(
    client: TestClient,
    tmp_path: Path,
    monkeypatch,
) -> None:
    launcher = _write_fake_opencode(
        tmp_path,
        """
from pathlib import Path
import time

Path("created-before-exit.txt").write_text("hello", encoding="utf-8")
print("file written", flush=True)
time.sleep(2)
""".strip(),
    )
    monkeypatch.setenv("MICA_OPENCODE_PATH", str(launcher))
    monkeypatch.setenv("MICA_WORKSPACE_WATCH_INTERVAL_SECONDS", "0.1")

    response = client.post(
        "/api/agent-runs",
        json={
            "prompt": "Create a file and pause.",
            "workspace": str(tmp_path),
            "agent_type": "opencode",
            "runner_mode": "local",
        },
    )

    assert response.status_code == 201
    run_id = response.json()["run"]["id"]
    deadline = time.time() + 1.5
    file_events: list[dict] = []
    run_payload: dict | None = None
    while time.time() < deadline:
        file_events = [
            event
            for event in client.get(f"/api/events?run_id={run_id}").json()
            if event["event_type"] == "file_changed"
        ]
        run_payload = client.get(f"/api/runs/{run_id}").json()
        if file_events:
            break
        time.sleep(0.05)

    assert file_events
    assert file_events[0]["payload"]["relative_path"] == "created-before-exit.txt"
    assert run_payload is not None
    assert run_payload["status"] == "started"
    _wait_for_run(client, run_id, "completed")


def test_stale_started_agent_run_is_marked_failed_on_read(client: TestClient) -> None:
    created = client.post("/api/runs", json={"source": "antigravity-cli", "cwd": "C:\\repo"})
    assert created.status_code == 201
    run_id = created.json()["id"]

    with client.app.state.database.session_factory() as session:
        run = session.get(RunRecord, run_id)
        assert run is not None
        run.started_at = utcnow() - timedelta(hours=2)
        session.add(run)
        session.commit()

    response = client.get(f"/api/runs/{run_id}")

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    events = client.get(f"/api/events?run_id={run_id}").json()
    assert events[-1]["payload"]["reason"] == "orphaned_agent_process"


def test_native_http_session_run_is_not_marked_as_orphaned_process(client: TestClient) -> None:
    with client.app.state.database.session_factory() as session:
        agent_session = AgentSession(
            title="Native OpenCode session",
            workspace="C:\\repo",
            agent_type="opencode",
            runner_mode="local",
            status=AgentSessionStatus.WAITING_USER_INPUT,
            transport="http",
            backend_url="http://127.0.0.1:4096",
            external_session_id="oc-native-session",
        )
        session.add(agent_session)
        session.commit()

    created = client.post(
        "/api/runs",
        json={"source": "opencode", "cwd": "C:\\repo", "session_id": agent_session.id},
    )
    run_id = created.json()["id"]
    with client.app.state.database.session_factory() as session:
        run = session.get(RunRecord, run_id)
        assert run is not None
        run.started_at = utcnow() - timedelta(hours=2)
        session.add(run)
        session.commit()

    response = client.get(f"/api/runs/{run_id}")

    assert response.status_code == 200
    assert response.json()["status"] == "started"
    events = client.get(f"/api/events?run_id={run_id}").json()
    assert not any(event["payload"].get("reason") == "orphaned_agent_process" for event in events)


def test_codex_adapter_extracts_commands_from_json_events() -> None:
    adapter = CodexCliAdapter()

    assert adapter.extract_command({"type": "exec_command_begin", "cmd": "git status"}) == "git status"
    assert adapter.extract_command({"type": "exec_command_begin", "command": "git status"}) == "git status"
    assert (
        adapter.extract_command(
            {
                "type": "item",
                "item": {
                    "type": "exec_command_call",
                    "command": "git status",
                },
            }
        )
        == "git status"
    )


def test_antigravity_adapter_extracts_commands_from_possible_json_events() -> None:
    adapter = AntigravityCliAdapter()

    assert adapter.extract_command({"type": "tool_use", "command": "git status"}) == "git status"
    assert (
        adapter.extract_command(
            {
                "type": "tool_use",
                "part": {
                    "state": {
                        "input": {
                            "command": "git status",
                        }
                    }
                },
            }
        )
        == "git status"
    )


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


def test_opencode_tool_use_completed_records_completed_agent_command(
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
        "tool": "bash",
        "state": {
            "status": "completed",
            "input": {"command": "if (Test-Path test.txt) { Remove-Item test.txt; \\"deleted\\" }"},
            "output": "deleted\\r\\n",
            "metadata": {"exit": 0, "output": "deleted\\r\\n"}
        }
    }
}), flush=True)
""".strip(),
    )
    monkeypatch.setenv("MICA_OPENCODE_PATH", str(launcher))

    response = client.post(
        "/api/agent-runs",
        json={
            "prompt": "Delete test.txt.",
            "workspace": str(tmp_path),
            "agent_type": "opencode",
            "runner_mode": "local",
        },
    )

    assert response.status_code == 201
    run_id = response.json()["run"]["id"]
    _wait_for_run(client, run_id, "completed")

    commands = client.get(f"/api/commands?run_id={run_id}").json()
    assert len(commands) == 1
    assert commands[0]["command_origin"] == "agent_tool"
    assert commands[0]["status"] == "completed"
    assert commands[0]["exit_code"] == 0
    summary = client.get(f"/api/runs/{run_id}/summary").json()
    assert summary["agent_tool_commands"] == 1
    assert summary["successful_governed_commands"] == 1


def test_codex_exec_command_high_risk_without_proxy_records_unintercepted_warning(
    client: TestClient,
    tmp_path: Path,
    monkeypatch,
) -> None:
    launcher = _write_fake_codex(
        tmp_path,
        """
import json

print(json.dumps({"type": "exec_command_begin", "cmd": "git push origin main"}), flush=True)
""".strip(),
    )
    monkeypatch.setenv("MICA_CODEX_PATH", str(launcher))

    response = client.post(
        "/api/agent-runs",
        json={
            "prompt": "Push changes.",
            "workspace": str(tmp_path),
            "agent_type": "codex-cli",
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
    assert warnings[0]["payload"]["command_line"] == "git push origin main"


def test_codex_command_execution_event_creates_agent_tool_command_record(
    client: TestClient,
    tmp_path: Path,
    monkeypatch,
) -> None:
    launcher = _write_fake_codex(
        tmp_path,
        """
import json

command = "pwsh -Command Get-Content -LiteralPath .\\\\mock.txt"
print(json.dumps({
    "type": "item.started",
    "item": {
        "id": "item_1",
        "type": "command_execution",
        "command": command,
        "status": "in_progress",
        "exit_code": None,
    },
}), flush=True)
print(json.dumps({
    "type": "item.completed",
    "item": {
        "id": "item_1",
        "type": "command_execution",
        "command": command,
        "status": "completed",
        "exit_code": 0,
    },
}), flush=True)
""".strip(),
    )
    monkeypatch.setenv("MICA_CODEX_PATH", str(launcher))

    response = client.post(
        "/api/agent-runs",
        json={
            "prompt": "Read the file.",
            "workspace": str(tmp_path),
            "agent_type": "codex-cli",
            "runner_mode": "local",
        },
    )

    assert response.status_code == 201
    run_id = response.json()["run"]["id"]
    _wait_for_run(client, run_id, "completed")

    commands = client.get(f"/api/commands?run_id={run_id}").json()
    assert len(commands) == 1
    assert commands[0]["command_origin"] == "agent_tool"
    assert commands[0]["status"] == "completed"
    summary = client.get(f"/api/runs/{run_id}/summary").json()
    assert summary["agent_tool_commands"] == 1
    assert summary["governed_commands"] == 1
    assert summary["successful_governed_commands"] == 1


def test_antigravity_json_command_high_risk_without_proxy_records_unintercepted_warning(
    client: TestClient,
    tmp_path: Path,
    monkeypatch,
) -> None:
    launcher = _write_fake_antigravity(
        tmp_path,
        """
import json

print(json.dumps({"type": "tool_use", "command": "git push origin main"}), flush=True)
""".strip(),
    )
    monkeypatch.setenv("MICA_ANTIGRAVITY_PATH", str(launcher))

    response = client.post(
        "/api/agent-runs",
        json={
            "prompt": "Push changes.",
            "workspace": str(tmp_path),
            "agent_type": "antigravity-cli",
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
    assert warnings[0]["payload"]["command_line"] == "git push origin main"


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


def test_agent_run_agents_endpoint_reports_codex_availability(
    client: TestClient,
    tmp_path: Path,
    monkeypatch,
) -> None:
    launcher = _write_fake_codex(tmp_path, "print('ok')")
    monkeypatch.setenv("MICA_CODEX_PATH", str(launcher))

    response = client.get("/api/agent-runs/agents")

    assert response.status_code == 200
    payload = response.json()
    codex = next(agent for agent in payload["agents"] if agent["agent_type"] == "codex-cli")
    assert codex["available"] is True
    assert codex["executable"] == str(launcher)


def test_agent_run_agents_endpoint_reports_antigravity_availability(
    client: TestClient,
    tmp_path: Path,
    monkeypatch,
) -> None:
    launcher = _write_fake_antigravity(tmp_path, "print('ok')")
    monkeypatch.setenv("MICA_ANTIGRAVITY_PATH", str(launcher))

    response = client.get("/api/agent-runs/agents")

    assert response.status_code == 200
    payload = response.json()
    antigravity = next(agent for agent in payload["agents"] if agent["agent_type"] == "antigravity-cli")
    assert antigravity["available"] is True
    assert antigravity["executable"] == str(launcher)
