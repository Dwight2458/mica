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


class DockerDemoCaptureStubHandler(BaseHTTPRequestHandler):
    pending = False
    approval_decisions: list[dict[str, Any]] = []
    docker_executes: list[dict[str, Any]] = []

    def do_POST(self) -> None:
        if self.path == "/api/docker/execute":
            payload = self._read_json()
            type(self).docker_executes.append(payload)
            type(self).pending = True
            deadline = time.monotonic() + 5
            while type(self).pending and time.monotonic() < deadline:
                time.sleep(0.05)
            self._send_json(
                {
                    "run": {
                        "id": "run-demo",
                        "source": "docker",
                        "cwd": payload["workspace"],
                        "status": "failed",
                        "started_at": "2026-07-07T00:00:00Z",
                        "finished_at": "2026-07-07T00:00:02Z",
                    },
                    "command": {
                        "id": "command-wrapper",
                        "run_id": "run-demo",
                        "tool": "docker",
                        "argv": payload["command"],
                        "command_line": "git push origin main",
                        "cwd": payload["workspace"],
                        "risk_level": "low",
                        "requires_approval": False,
                        "approval_id": None,
                        "status": "failed",
                        "exit_code": 126,
                        "duration_ms": 2000,
                        "started_at": "2026-07-07T00:00:00Z",
                        "finished_at": "2026-07-07T00:00:02Z",
                    },
                    "result": {
                        "exit_code": 126,
                        "stdout": "demo stdout\n",
                        "stderr": "MICA_APPROVAL_REJECTED\n",
                        "duration_ms": 2000,
                        "image": payload["image"],
                        "workspace": payload["workspace"],
                        "network_mode": payload["network_mode"],
                        "command": payload["command"],
                    },
                },
                status=201,
            )
            return
        if self.path == "/api/approvals/approval-demo/decide":
            payload = self._read_json()
            type(self).approval_decisions.append(payload)
            type(self).pending = False
            self._send_json({"id": "approval-demo", "status": payload["decision"]})
            return
        self.send_error(404)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if parsed.path == "/api/approvals":
            if query.get("status", [""])[0] == "pending" and type(self).pending:
                self._send_json(
                    [
                        {
                            "id": "approval-demo",
                            "tool": "git",
                            "argv": ["push", "origin", "main"],
                            "command_line": "git push origin main",
                            "cwd": "/workspace",
                            "risk_level": "high",
                            "reason": "git push may publish code to a remote repository.",
                            "status": "pending",
                            "created_at": "2026-07-07T00:00:01Z",
                            "resolved_at": None,
                            "resolved_by": None,
                            "comment": None,
                        }
                    ]
                )
                return
            self._send_json(
                [
                    {
                        "id": "approval-demo",
                        "tool": "git",
                        "argv": ["push", "origin", "main"],
                        "command_line": "git push origin main",
                        "cwd": "/workspace",
                        "risk_level": "high",
                        "reason": "git push may publish code to a remote repository.",
                        "status": "rejected",
                        "created_at": "2026-07-07T00:00:01Z",
                        "resolved_at": "2026-07-07T00:00:02Z",
                        "resolved_by": "mica-docker-approval-probe",
                        "comment": "auto rejected from Docker approval probe",
                    }
                ]
            )
            return
        if parsed.path == "/api/commands":
            assert query["run_id"] == ["run-demo"]
            self._send_json(
                [
                    {
                        "id": "command-wrapper",
                        "run_id": "run-demo",
                        "tool": "docker",
                        "command_line": "docker run mica-python-git:local git push origin main",
                        "cwd": "/host-workspace",
                        "risk_level": "low",
                        "requires_approval": False,
                        "approval_id": None,
                        "status": "failed",
                        "exit_code": 126,
                        "duration_ms": 2000,
                        "started_at": "2026-07-07T00:00:00Z",
                        "finished_at": "2026-07-07T00:00:02Z",
                    },
                    {
                        "id": "command-inner",
                        "run_id": "run-demo",
                        "tool": "git",
                        "command_line": "git push origin main",
                        "cwd": "/workspace",
                        "risk_level": "high",
                        "requires_approval": True,
                        "approval_id": "approval-demo",
                        "status": "rejected",
                        "exit_code": 126,
                        "duration_ms": 1200,
                        "started_at": "2026-07-07T00:00:01Z",
                        "finished_at": "2026-07-07T00:00:02Z",
                    },
                ]
            )
            return
        if parsed.path == "/api/events":
            assert query["run_id"] == ["run-demo"]
            self._send_json(
                [
                    {
                        "id": "event-1",
                        "run_id": "run-demo",
                        "command_id": None,
                        "approval_id": None,
                        "event_type": "run_created",
                        "message": "Docker run created",
                        "payload": {},
                        "created_at": "2026-07-07T00:00:00Z",
                    },
                    {
                        "id": "event-2",
                        "run_id": "run-demo",
                        "command_id": "command-inner",
                        "approval_id": "approval-demo",
                        "event_type": "approval_rejected",
                        "message": "Approval rejected",
                        "payload": {"decision": "rejected"},
                        "created_at": "2026-07-07T00:00:02Z",
                    },
                ]
            )
            return
        if parsed.path == "/api/runs/run-demo/summary":
            self._send_json(
                {
                    "run_id": "run-demo",
                    "source": "docker",
                    "status": "failed",
                    "cwd": "/host-workspace",
                    "total_commands": 2,
                    "successful_commands": 0,
                    "failed_commands": 2,
                    "approval_count": 1,
                    "rejected_count": 1,
                    "risky_command_count": 1,
                    "total_duration_ms": 2000,
                    "failure_summary": {
                        "failed_command": "git push origin main",
                        "exit_code": 126,
                        "reason": "Approval rejected.",
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


def test_capture_docker_demo_writes_markdown_report(tmp_path: Path) -> None:
    DockerDemoCaptureStubHandler.pending = False
    DockerDemoCaptureStubHandler.approval_decisions = []
    DockerDemoCaptureStubHandler.docker_executes = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), DockerDemoCaptureStubHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    report_path = tmp_path / "docker-demo.md"
    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(ROOT / "scripts" / "capture-docker-demo.ps1"),
                "-ApiBaseUrl",
                f"http://127.0.0.1:{server.server_port}/api",
                "-ContainerApiBaseUrl",
                f"http://127.0.0.1:{server.server_port}/api",
                "-WorkDir",
                str(tmp_path / "workspace"),
                "-ReportPath",
                str(report_path),
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
    assert payload["run_id"] == "run-demo"
    assert payload["report_path"] == str(report_path)
    assert payload["command_count"] == 2
    assert payload["event_count"] == 2
    assert payload["approval_count"] == 1
    assert DockerDemoCaptureStubHandler.docker_executes[0]["allow_host_callback"] is True
    assert report_path.exists()

    report = report_path.read_text(encoding="utf-8")
    assert "# Mica Docker Demo Capture" in report
    assert "git push origin main" in report
    assert f"http://127.0.0.1:{server.server_port}/api" in report
    assert "$ApiBaseUrl" not in report
    assert "Allow host callback: `True`" in report
    assert "approval_rejected" in report
    assert "MICA_APPROVAL_REJECTED" in report
    assert "Local PATH shim mode is not a strong security sandbox." in report
