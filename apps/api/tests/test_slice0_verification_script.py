from __future__ import annotations

import json
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parents[3]


class Slice0StubHandler(BaseHTTPRequestHandler):
    approval_creates: list[dict[str, Any]] = []
    approval_decisions: list[dict[str, Any]] = []
    command_creates: list[dict[str, Any]] = []
    command_finishes: list[dict[str, Any]] = []
    approval_status = "pending"

    def do_POST(self) -> None:
        if self.path == "/api/approvals":
            payload = self._read_json()
            type(self).approval_creates.append(payload)
            type(self).approval_status = "pending"
            self._send_json(
                {
                    **payload,
                    "id": "approval-1",
                    "status": "pending",
                    "created_at": "2026-07-07T00:00:00Z",
                    "resolved_at": None,
                    "resolved_by": None,
                    "comment": None,
                },
                status=201,
            )
            return
        if self.path == "/api/approvals/approval-1/decide":
            payload = self._read_json()
            type(self).approval_decisions.append(payload)
            type(self).approval_status = payload["decision"]
            self._send_json(
                {
                    "id": "approval-1",
                    "status": payload["decision"],
                    "resolved_by": payload.get("resolved_by"),
                    "comment": payload.get("comment"),
                    "created_at": "2026-07-07T00:00:00Z",
                    "resolved_at": "2026-07-07T00:00:01Z",
                }
            )
            return
        if self.path == "/api/commands":
            payload = self._read_json()
            type(self).command_creates.append(payload)
            self._send_json(
                {
                    **payload,
                    "id": f"command-{len(type(self).command_creates)}",
                    "status": "waiting_approval" if payload["requires_approval"] else "started",
                    "exit_code": None,
                    "duration_ms": None,
                    "started_at": "2026-07-07T00:00:00Z",
                    "finished_at": None,
                },
                status=201,
            )
            return
        self.send_error(404)

    def do_PATCH(self) -> None:
        if self.path.startswith("/api/commands/") and self.path.endswith("/finish"):
            payload = self._read_json()
            type(self).command_finishes.append(payload)
            self._send_json(
                {
                    "id": self.path.split("/")[3],
                    "status": payload["status"],
                    "exit_code": payload["exit_code"],
                    "duration_ms": payload["duration_ms"],
                }
            )
            return
        self.send_error(404)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/approvals":
            query = parse_qs(parsed.query)
            if (
                query.get("status", [""])[0] == "pending"
                and type(self).approval_creates
                and type(self).approval_status == "pending"
            ):
                payload = type(self).approval_creates[-1]
                self._send_json(
                    [
                        {
                            **payload,
                            "id": "approval-1",
                            "status": "pending",
                            "created_at": "2026-07-07T00:00:00Z",
                            "resolved_at": None,
                            "resolved_by": None,
                            "comment": None,
                        }
                    ]
                )
                return
            self._send_json([])
            return
        if parsed.path == "/api/approvals/approval-1":
            payload = type(self).approval_creates[-1]
            status = type(self).approval_status
            self._send_json(
                {
                    **payload,
                    "id": "approval-1",
                    "status": status,
                    "created_at": "2026-07-07T00:00:00Z",
                    "resolved_at": "2026-07-07T00:00:01Z" if status != "pending" else None,
                    "resolved_by": "slice0-test" if status != "pending" else None,
                    "comment": "slice0 verification" if status != "pending" else None,
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


def test_verify_slice0_script_checks_low_risk_and_auto_rejects_high_risk(tmp_path: Path) -> None:
    Slice0StubHandler.approval_creates = []
    Slice0StubHandler.approval_decisions = []
    Slice0StubHandler.command_creates = []
    Slice0StubHandler.command_finishes = []
    Slice0StubHandler.approval_status = "pending"
    server = ThreadingHTTPServer(("127.0.0.1", 0), Slice0StubHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    fakebin = tmp_path / "fakebin"
    workdir = tmp_path / "work"
    fakebin.mkdir()
    workdir.mkdir()
    (fakebin / "git.cmd").write_text(
        "@echo off\r\n"
        "if \"%1\"==\"status\" echo REAL_GIT status\r\n"
        "if \"%1\"==\"push\" echo REAL_GIT push %2 %3\r\n"
        "exit /b 0\r\n",
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["PATH"] = f"{fakebin};{env['PATH']}"
    env["MICA_APPROVAL_TIMEOUT_SECONDS"] = "5"
    env["MICA_APPROVAL_POLL_SECONDS"] = "0.05"

    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(ROOT / "scripts" / "verify-slice0.ps1"),
                "-ApiBaseUrl",
                f"http://127.0.0.1:{server.server_port}/api",
                "-WorkDir",
                str(workdir),
                "-SkipRepoSetup",
                "-AutoDecision",
                "rejected",
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

    assert result.returncode == 0, result.stderr
    assert "REAL_GIT status" in result.stdout
    assert "Slice 0 verification passed" in result.stdout
    assert "REAL_GIT push origin main" not in result.stdout
    assert Slice0StubHandler.approval_creates[-1]["command_line"] == "git push origin main"
    assert Slice0StubHandler.approval_decisions[-1]["decision"] == "rejected"
    assert Slice0StubHandler.command_creates[0]["command_line"] == "git status"
    assert Slice0StubHandler.command_creates[1]["command_line"] == "git push origin main"
    assert Slice0StubHandler.command_finishes[-1]["status"] == "rejected"
