from __future__ import annotations

import json
import os
import socket
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class OpenCodeBackendHandle:
    base_url: str
    managed: bool


_BACKENDS: dict[str, tuple[OpenCodeBackendHandle, subprocess.Popen[str]]] = {}


class OpenCodeServerClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/global/health")

    def create_session(self, *, title: str) -> str:
        payload = self._request("POST", "/session", {"title": title})
        session_id = _extract_id(payload)
        if session_id is None:
            raise RuntimeError(f"OpenCode server did not return a session id: {payload!r}")
        return session_id

    def prompt(self, session_id: str, text: str) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/session/{session_id}/message",
            {"parts": [{"type": "text", "text": text}]},
        )

    def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=300) as response:
            raw = response.read()
        if not raw:
            return {}
        parsed = json.loads(raw.decode("utf-8"))
        return parsed if isinstance(parsed, dict) else {"value": parsed}


def ensure_opencode_backend(executable: str, workspace: str) -> OpenCodeBackendHandle:
    configured = os.environ.get("MICA_OPENCODE_SERVER_URL")
    if configured:
        handle = OpenCodeBackendHandle(configured.rstrip("/"), managed=False)
        OpenCodeServerClient(handle.base_url).health()
        return handle

    key = str(Path(workspace).resolve())
    existing = _BACKENDS.get(key)
    if existing is not None:
        handle, process = existing
        if process.poll() is None:
            return handle
        _BACKENDS.pop(key, None)

    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    process = subprocess.Popen(
        [executable, "serve", "--port", str(port), "--hostname", "127.0.0.1"],
        cwd=workspace,
        env=_server_env(),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    handle = OpenCodeBackendHandle(base_url, managed=True)
    _wait_for_health(handle, process)
    _BACKENDS[key] = (handle, process)
    return handle


def _wait_for_health(handle: OpenCodeBackendHandle, process: subprocess.Popen[str]) -> None:
    client = OpenCodeServerClient(handle.base_url)
    deadline = time.time() + 20
    last_error: Exception | None = None
    while time.time() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"OpenCode server exited early with code {process.returncode}")
        try:
            client.health()
            return
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            last_error = exc
            time.sleep(0.2)
    raise RuntimeError(f"OpenCode server did not become healthy: {last_error}")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _server_env() -> dict[str, str]:
    env = os.environ.copy()
    repo_root = Path(__file__).resolve().parents[4]
    shim_dir = str(repo_root / "shims")
    original_path = env.get("MICA_ORIGINAL_PATH") or env.get("PATH", "")
    env["MICA_ORIGINAL_PATH"] = original_path
    env["PATH"] = f"{shim_dir}{os.pathsep}{original_path}"
    env.setdefault("MICA_API_BASE_URL", "http://localhost:8000/api")
    return env


def extract_text(response: dict[str, Any]) -> str:
    chunks: list[str] = []
    _collect_text(response, chunks)
    return "\n".join(chunk.strip() for chunk in chunks if chunk.strip()).strip()


def _collect_text(value: Any, chunks: list[str]) -> None:
    if isinstance(value, dict):
        if value.get("type") == "text" and isinstance(value.get("text"), str):
            chunks.append(value["text"])
        for key in ("message", "content", "output"):
            text = value.get(key)
            if isinstance(text, str):
                chunks.append(text)
        for key in ("parts", "children", "value"):
            nested = value.get(key)
            if isinstance(nested, list | dict):
                _collect_text(nested, chunks)
    elif isinstance(value, list):
        for item in value:
            _collect_text(item, chunks)


def _extract_id(payload: dict[str, Any]) -> str | None:
    for key in ("id", "sessionID", "sessionId", "session_id"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    session = payload.get("session")
    if isinstance(session, dict):
        return _extract_id(session)
    return None
