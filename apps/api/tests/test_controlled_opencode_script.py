from __future__ import annotations

import json
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]


class ApprovalStubHandler(BaseHTTPRequestHandler):
    decision = "approved"
    payloads: list[dict[str, Any]] = []
    run_creates: list[dict[str, Any]] = []
    run_finishes: list[str] = []
    command_creates: list[dict[str, Any]] = []
    command_finishes: list[dict[str, Any]] = []

    def do_POST(self) -> None:
        if self.path == "/api/runs":
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            type(self).run_creates.append(payload)
            self._send_json(
                {
                    **payload,
                    "id": "run-1",
                    "status": "started",
                    "started_at": "2026-07-06T00:00:00Z",
                    "finished_at": None,
                },
                status=201,
            )
            return
        if self.path == "/api/commands":
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            type(self).command_creates.append(payload)
            self._send_json(
                {
                    **payload,
                    "id": f"command-{len(type(self).command_creates)}",
                    "status": "waiting_approval" if payload["requires_approval"] else "started",
                    "exit_code": None,
                    "duration_ms": None,
                    "started_at": "2026-07-06T00:00:00Z",
                    "finished_at": None,
                },
                status=201,
            )
            return
        if self.path != "/api/approvals":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        type(self).payloads.append(payload)
        self._send_json(
            {
                **payload,
                "id": "approval-1",
                "status": "pending",
                "created_at": "2026-07-06T00:00:00Z",
                "resolved_at": None,
                "resolved_by": None,
                "comment": None,
            },
            status=201,
        )

    def do_PATCH(self) -> None:
        if self.path == "/api/runs/run-1/finish":
            type(self).run_finishes.append("run-1")
            create_payload = type(self).run_creates[-1]
            self._send_json(
                {
                    **create_payload,
                    "id": "run-1",
                    "status": "completed",
                    "started_at": "2026-07-06T00:00:00Z",
                    "finished_at": "2026-07-06T00:00:01Z",
                }
            )
            return
        if not self.path.startswith("/api/commands/") or not self.path.endswith("/finish"):
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        type(self).command_finishes.append(payload)
        create_payload = type(self).command_creates[-1]
        self._send_json(
            {
                **create_payload,
                "id": self.path.split("/")[3],
                "status": payload["status"],
                "exit_code": payload["exit_code"],
                "duration_ms": payload["duration_ms"],
                "started_at": "2026-07-06T00:00:00Z",
                "finished_at": "2026-07-06T00:00:01Z",
            }
        )

    def do_GET(self) -> None:
        if self.path != "/api/approvals/approval-1":
            self.send_error(404)
            return
        payload = type(self).payloads[-1]
        self._send_json(
            {
                **payload,
                "id": "approval-1",
                "status": type(self).decision,
                "created_at": "2026-07-06T00:00:00Z",
                "resolved_at": "2026-07-06T00:00:01Z",
                "resolved_by": "test",
                "comment": "controlled opencode test",
            }
        )

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _send_json(self, payload: dict[str, Any], *, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def run_with_stubbed_approval(
    tmp_path: Path,
    decision: str,
    *,
    agent_command: str = "git push origin main",
    fake_tool: str = "git",
    policy_file: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    ApprovalStubHandler.decision = decision
    ApprovalStubHandler.payloads = []
    ApprovalStubHandler.run_creates = []
    ApprovalStubHandler.run_finishes = []
    ApprovalStubHandler.command_creates = []
    ApprovalStubHandler.command_finishes = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), ApprovalStubHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    fakebin = tmp_path / "fakebin"
    fakebin.mkdir()
    (fakebin / "opencode.cmd").write_text(
        f'@echo off\r\nif not "%1"=="run" exit /b 9\r\n{agent_command}\r\nexit /b %ERRORLEVEL%\r\n',
        encoding="utf-8",
    )
    (fakebin / f"{fake_tool}.cmd").write_text(
        f"@echo off\r\necho REAL_{fake_tool.upper()} %*\r\nexit /b 0\r\n",
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["PATH"] = f"{fakebin};{env['PATH']}"
    env["MICA_APPROVAL_TIMEOUT_SECONDS"] = "5"
    env["MICA_APPROVAL_POLL_SECONDS"] = "0.05"
    if policy_file is not None:
        env["MICA_POLICY_FILE"] = str(policy_file)

    try:
        return subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(ROOT / "scripts" / "run-controlled-opencode.ps1"),
                "-OpenCodeCommand",
                "opencode",
                "-Prompt",
                "run git push",
                "-ApiBaseUrl",
                f"http://127.0.0.1:{server.server_port}/api",
            ],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_controlled_opencode_approval_mode_allows_approved_git_push(tmp_path: Path) -> None:
    result = run_with_stubbed_approval(tmp_path, "approved")

    assert result.returncode == 0, result.stderr
    assert "REAL_GIT push origin main" in result.stdout
    assert ApprovalStubHandler.payloads[-1]["command_line"] == "git push origin main"
    assert ApprovalStubHandler.payloads[-1]["risk_level"] == "high"
    assert ApprovalStubHandler.command_creates[-1]["requires_approval"] is True
    assert ApprovalStubHandler.command_creates[-1]["approval_id"] == "approval-1"
    assert ApprovalStubHandler.command_finishes[-1]["status"] == "completed"
    assert ApprovalStubHandler.command_finishes[-1]["exit_code"] == 0


def test_controlled_opencode_approval_mode_rejects_git_push(tmp_path: Path) -> None:
    result = run_with_stubbed_approval(tmp_path, "rejected")

    assert result.returncode == 126
    assert "MICA_APPROVAL_REJECTED" in result.stderr
    assert "REAL_GIT push origin main" not in result.stdout
    assert ApprovalStubHandler.payloads[-1]["command_line"] == "git push origin main"
    assert ApprovalStubHandler.command_finishes[-1]["status"] == "rejected"
    assert ApprovalStubHandler.command_finishes[-1]["exit_code"] == 126


def test_controlled_opencode_uses_policy_file_from_environment(tmp_path: Path) -> None:
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(
        json.dumps(
            {
                "version": 1,
                "rules": [
                    {
                        "id": "kubectl-delete",
                        "tool": "kubectl",
                        "argv_prefix": ["delete"],
                        "action": "require_approval",
                        "risk_level": "high",
                        "reason": "kubectl delete can remove cluster resources.",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = run_with_stubbed_approval(
        tmp_path,
        "approved",
        agent_command="kubectl delete pod mica-test",
        fake_tool="kubectl",
        policy_file=policy_path,
    )

    assert result.returncode == 0, result.stderr
    assert "REAL_KUBECTL delete pod mica-test" in result.stdout
    assert ApprovalStubHandler.payloads[-1]["command_line"] == "kubectl delete pod mica-test"
    assert ApprovalStubHandler.payloads[-1]["reason"] == "kubectl delete can remove cluster resources."


def test_controlled_opencode_records_low_risk_command(tmp_path: Path) -> None:
    result = run_with_stubbed_approval(
        tmp_path,
        "approved",
        agent_command="git status",
        fake_tool="git",
    )

    assert result.returncode == 0, result.stderr
    assert "REAL_GIT status" in result.stdout
    assert ApprovalStubHandler.payloads == []
    assert ApprovalStubHandler.command_creates[-1]["command_line"] == "git status"
    assert ApprovalStubHandler.command_creates[-1]["requires_approval"] is False
    assert ApprovalStubHandler.command_finishes[-1]["status"] == "completed"


def test_controlled_opencode_creates_run_and_links_commands(tmp_path: Path) -> None:
    result = run_with_stubbed_approval(
        tmp_path,
        "approved",
        agent_command="git status",
        fake_tool="git",
    )

    assert result.returncode == 0, result.stderr
    assert ApprovalStubHandler.run_creates[-1]["source"] == "opencode"
    assert ApprovalStubHandler.command_creates[-1]["run_id"] == "run-1"
    assert ApprovalStubHandler.run_finishes == ["run-1"]
