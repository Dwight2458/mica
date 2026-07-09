from __future__ import annotations

import json
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parents[3]


class DockerApprovalProbeStubHandler(BaseHTTPRequestHandler):
    docker_executes: list[dict[str, Any]] = []
    approval_decisions: list[dict[str, Any]] = []
    pending = False

    def do_POST(self) -> None:
        if self.path == "/api/docker/execute":
            payload = self._read_json()
            type(self).docker_executes.append(payload)
            type(self).pending = True
            deadline = time.monotonic() + 5
            while type(self).pending and time.monotonic() < deadline:
                time.sleep(0.05)
            decision = type(self).approval_decisions[-1]["decision"] if type(self).approval_decisions else "timeout"
            exit_code = 126 if decision == "rejected" else 0
            self._send_json(
                {
                    "run": {
                        "id": "run-1",
                        "source": "docker",
                        "cwd": payload["workspace"],
                        "status": "failed" if exit_code else "completed",
                        "started_at": "2026-07-07T00:00:00Z",
                        "finished_at": "2026-07-07T00:00:01Z",
                    },
                    "command": {
                        "id": "command-1",
                        "run_id": "run-1",
                        "tool": "git",
                        "argv": ["push", "origin", "main"],
                        "command_line": "git push origin main",
                        "cwd": payload["workspace"],
                        "risk_level": "high",
                        "requires_approval": True,
                        "approval_id": "approval-1",
                        "status": "rejected" if exit_code else "completed",
                        "exit_code": exit_code,
                        "duration_ms": 25,
                        "started_at": "2026-07-07T00:00:00Z",
                        "finished_at": "2026-07-07T00:00:01Z",
                    },
                    "result": {
                        "exit_code": exit_code,
                        "stdout": "",
                        "stderr": "MICA_APPROVAL_REJECTED\n" if exit_code else "",
                        "duration_ms": 25,
                        "image": payload["image"],
                        "workspace": payload["workspace"],
                        "network_mode": "none",
                        "command": payload["command"],
                    },
                },
                status=201,
            )
            return
        if self.path == "/api/approvals/approval-1/decide":
            payload = self._read_json()
            type(self).approval_decisions.append(payload)
            type(self).pending = False
            self._send_json(
                {
                    "id": "approval-1",
                    "tool": "git",
                    "argv": ["push", "origin", "main"],
                    "command_line": "git push origin main",
                    "cwd": "C:\\workspace",
                    "risk_level": "high",
                    "reason": "git push may publish code to a remote repository.",
                    "status": payload["decision"],
                    "created_at": "2026-07-07T00:00:00Z",
                    "resolved_at": "2026-07-07T00:00:01Z",
                    "resolved_by": payload.get("resolved_by"),
                    "comment": payload.get("comment"),
                }
            )
            return
        self.send_error(404)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/approvals":
            query = parse_qs(parsed.query)
            if query.get("status", [""])[0] == "pending" and type(self).pending:
                self._send_json(
                    [
                        {
                            "id": "approval-1",
                            "tool": "git",
                            "argv": ["push", "origin", "main"],
                            "command_line": "git push origin main",
                            "cwd": "C:\\workspace",
                            "risk_level": "high",
                            "reason": "git push may publish code to a remote repository.",
                            "status": "pending",
                            "created_at": "2026-07-07T00:00:00Z",
                            "resolved_at": None,
                            "resolved_by": None,
                            "comment": None,
                        }
                    ]
                )
                return
            if "status" not in query and type(self).approval_decisions:
                decision = type(self).approval_decisions[-1]
                self._send_json(
                    [
                        {
                            "id": "approval-old",
                            "tool": "git",
                            "argv": ["push", "origin", "main"],
                            "command_line": "git push origin main",
                            "cwd": "/workspace",
                            "risk_level": "high",
                            "reason": "older approval record.",
                            "status": "approved",
                            "created_at": "2026-07-06T00:00:00Z",
                            "resolved_at": "2026-07-06T00:00:01Z",
                            "resolved_by": "fixture",
                            "comment": "older fixture record",
                        },
                        {
                            "id": "approval-1",
                            "tool": "git",
                            "argv": ["push", "origin", "main"],
                            "command_line": "git push origin main",
                            "cwd": "/workspace",
                            "risk_level": "high",
                            "reason": "git push may publish code to a remote repository.",
                            "status": decision["decision"],
                            "created_at": "2026-07-07T00:00:00Z",
                            "resolved_at": "2026-07-07T00:00:01Z",
                            "resolved_by": decision.get("resolved_by"),
                            "comment": decision.get("comment"),
                        }
                    ]
                )
                return
            self._send_json([])
            return
        if parsed.path == "/api/runs/run-1/summary":
            self._send_json(
                {
                    "run_id": "run-1",
                    "source": "docker",
                    "status": "failed",
                    "cwd": "C:\\workspace",
                    "total_commands": 2,
                    "governed_commands": 2,
                    "successful_governed_commands": 0,
                    "successful_commands": 0,
                    "failed_commands": 2,
                    "approval_count": 1,
                    "rejected_count": 1,
                    "risky_command_count": 1,
                    "total_duration_ms": 50,
                    "failure_summary": {
                        "failed_command": "git push origin main",
                        "exit_code": 126,
                        "reason": "Command was rejected or failed.",
                        "suggested_next_action": "Review the approval decision.",
                    },
                }
            )
            return
        self.send_error(404)

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _send_json(self, payload: Any, *, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def test_verify_docker_approval_probe_auto_rejects_pending_approval(tmp_path: Path) -> None:
    DockerApprovalProbeStubHandler.docker_executes = []
    DockerApprovalProbeStubHandler.approval_decisions = []
    DockerApprovalProbeStubHandler.pending = False
    server = ThreadingHTTPServer(("127.0.0.1", 0), DockerApprovalProbeStubHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(ROOT / "scripts" / "verify-docker-approval-probe.ps1"),
                "-ApiBaseUrl",
                f"http://127.0.0.1:{server.server_port}/api",
                "-WorkDir",
                str(tmp_path / "workspace"),
                "-Image",
                "mica-python-git:local",
                "-AutoDecision",
                "rejected",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
    finally:
        server.shutdown()
        server.server_close()

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "completed"
    assert payload["docker_exit_code"] == 126
    assert payload["allow_host_callback"] is True
    assert payload["approval_id"] == "approval-1"
    assert payload["approval_status"] == "rejected"
    assert payload["run_summary"]["total_commands"] == 2
    assert payload["run_summary"]["approval_count"] == 1
    assert payload["run_summary"]["rejected_count"] == 1
    assert DockerApprovalProbeStubHandler.docker_executes[0]["inject_proxy"] is True
    assert DockerApprovalProbeStubHandler.docker_executes[0]["image"] == "mica-python-git:local"
    assert DockerApprovalProbeStubHandler.docker_executes[0]["command"] == ["git", "push", "origin", "main"]
    assert DockerApprovalProbeStubHandler.docker_executes[0]["network_mode"] == "bridge"
    assert DockerApprovalProbeStubHandler.docker_executes[0]["allow_host_callback"] is True
    assert (
        DockerApprovalProbeStubHandler.docker_executes[0]["api_base_url"]
        == "http://host.docker.internal:8000/api"
    )
    assert DockerApprovalProbeStubHandler.approval_decisions[0]["decision"] == "rejected"
