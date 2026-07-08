from __future__ import annotations

from pathlib import Path
from typing import Sequence

import pytest
from fastapi.testclient import TestClient

from app.runners.docker_runner import DockerRunResult
from app.services.docker_policy import load_docker_policy


class FakeDockerRunner:
    captured_run_id: str | None = None

    def run(
        self,
        *,
        workspace: str | Path,
        command: Sequence[str],
        run_id: str | None = None,
        on_output: object | None = None,
    ) -> DockerRunResult:
        self.captured_run_id = run_id
        return DockerRunResult(
            exit_code=0,
            stdout="hello from docker\n",
            stderr="",
            duration_ms=23,
            image="python:3.12-slim",
            workspace=Path(workspace).resolve(),
            network_mode="none",
            command=tuple(command),
        )


class CapturingDockerRunner:
    last_proxy_injection: object | None = None
    last_image: object | None = None
    last_network_mode: object | None = None
    last_run_id: str | None = None

    def __init__(self, **kwargs: object) -> None:
        self.proxy_injection = kwargs.get("proxy_injection")
        self.image = kwargs.get("image")
        self.network_mode = kwargs.get("network_mode")
        CapturingDockerRunner.last_proxy_injection = self.proxy_injection
        CapturingDockerRunner.last_image = self.image
        CapturingDockerRunner.last_network_mode = self.network_mode

    def run(
        self,
        *,
        workspace: str | Path,
        command: Sequence[str],
        run_id: str | None = None,
        on_output: object | None = None,
    ) -> DockerRunResult:
        CapturingDockerRunner.last_run_id = run_id
        return DockerRunResult(
            exit_code=0,
            stdout="proxied docker\n",
            stderr="",
            duration_ms=31,
            image="python:3.12-slim",
            workspace=Path(workspace).resolve(),
            network_mode="none",
            command=tuple(command),
        )


def test_docker_execute_api_records_run_command_and_events(client: TestClient, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runner = FakeDockerRunner()
    client.app.state.docker_runner = runner

    response = client.post(
        "/api/docker/execute",
        json={
            "workspace": str(workspace),
            "command": ["python", "-c", "print('hello from docker')"],
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["run"]["source"] == "docker"
    assert payload["run"]["status"] == "completed"
    assert payload["command"]["command_line"] == "python -c \"print('hello from docker')\""
    assert payload["command"]["exit_code"] == 0
    assert payload["result"]["stdout"] == "hello from docker\n"
    assert payload["result"]["network_mode"] == "none"
    assert runner.captured_run_id == payload["run"]["id"]

    events = client.get(f"/api/events?run_id={payload['run']['id']}").json()
    assert [event["event_type"] for event in events] == [
        "run_created",
        "command_started",
        "policy_decision",
        "command_output",
        "network_evidence",
        "command_finished",
        "run_completed",
    ]
    assert events[3]["payload"] == {
        "command_line": "python -c \"print('hello from docker')\"",
        "stream": "stdout",
        "text": "hello from docker\n",
    }
    assert events[4]["payload"]["network_mode"] == "none"
    assert events[4]["payload"]["network_access"] == "disabled"


def test_docker_execute_api_records_network_policy_decision(
    client: TestClient,
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runner = FakeDockerRunner()
    client.app.state.docker_runner = runner

    response = client.post(
        "/api/docker/execute",
        json={
            "workspace": str(workspace),
            "command": ["python", "--version"],
            "network_mode": "none",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    events = client.get(f"/api/events?run_id={payload['run']['id']}").json()
    policy_events = [event for event in events if event["event_type"] == "policy_decision"]
    assert len(policy_events) == 1
    assert policy_events[0]["payload"] == {
        "policy": "docker-network",
        "decision": "allowed",
        "network_mode": "none",
        "allowed_modes": ["none", "bridge"],
        "allow_host_callback": False,
        "inject_proxy": False,
        "require_host_callback_for_bridge": True,
        "require_proxy_injection_for_bridge": True,
        "reason": "network_mode is allowed by Docker policy",
    }


def test_docker_execute_api_can_enable_proxy_injection(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.routes.docker as docker_route

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(docker_route, "DockerRunner", CapturingDockerRunner)

    response = client.post(
        "/api/docker/execute",
        json={
            "workspace": str(workspace),
            "command": ["git", "status"],
            "image": "mica-python-git:local",
            "inject_proxy": True,
            "api_base_url": "http://host.docker.internal:8000/api",
            "network_mode": "bridge",
            "allow_host_callback": True,
        },
    )

    assert response.status_code == 201
    assert response.json()["result"]["stdout"] == "proxied docker\n"
    injection = CapturingDockerRunner.last_proxy_injection
    assert injection is not None
    assert str(injection.proxy_dir).endswith("proxy")
    assert str(injection.shim_dir).endswith("docker-shims")
    assert str(injection.policy_file).endswith("policies\\command-policy.json") or str(injection.policy_file).endswith(
        "policies/command-policy.json"
    )
    assert injection.api_base_url == "http://host.docker.internal:8000/api"
    assert CapturingDockerRunner.last_image == "mica-python-git:local"
    assert CapturingDockerRunner.last_network_mode == "bridge"
    assert CapturingDockerRunner.last_run_id == response.json()["run"]["id"]


def test_docker_execute_api_rejects_bridge_without_explicit_host_callback(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.routes.docker as docker_route

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(docker_route, "DockerRunner", CapturingDockerRunner)
    CapturingDockerRunner.last_network_mode = None

    response = client.post(
        "/api/docker/execute",
        json={
            "workspace": str(workspace),
            "command": ["git", "status"],
            "network_mode": "bridge",
        },
    )

    assert response.status_code == 400
    assert "allow_host_callback=true" in response.text
    assert CapturingDockerRunner.last_network_mode is None


def test_default_docker_policy_requires_explicit_host_callback_for_bridge() -> None:
    policy = load_docker_policy()

    assert policy.version == 1
    assert policy.network.allowed_modes == ("none", "bridge")
    assert policy.network.require_host_callback_for_bridge is True
    assert policy.network.require_proxy_injection_for_bridge is True


def test_docker_execute_api_rejects_bridge_without_proxy_injection(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.routes.docker as docker_route

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(docker_route, "DockerRunner", CapturingDockerRunner)
    CapturingDockerRunner.last_network_mode = None

    response = client.post(
        "/api/docker/execute",
        json={
            "workspace": str(workspace),
            "command": ["git", "status"],
            "network_mode": "bridge",
            "allow_host_callback": True,
            "inject_proxy": False,
        },
    )

    assert response.status_code == 400
    assert "inject_proxy=true" in response.text
    assert CapturingDockerRunner.last_network_mode is None


def test_docker_execute_api_rejects_network_mode_disallowed_by_policy(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.routes.docker as docker_route

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    policy_path = tmp_path / "docker-policy.json"
    policy_path.write_text(
        '{"version":1,"network":{"allowed_modes":["none"],"require_host_callback_for_bridge":true}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(docker_route, "DockerRunner", CapturingDockerRunner)
    client.app.state.docker_policy_path = policy_path
    CapturingDockerRunner.last_network_mode = None

    try:
        response = client.post(
            "/api/docker/execute",
            json={
                "workspace": str(workspace),
                "command": ["git", "status"],
                "network_mode": "bridge",
                "allow_host_callback": True,
            },
        )
    finally:
        delattr(client.app.state, "docker_policy_path")

    assert response.status_code == 400
    assert "not allowed by Docker policy" in response.text
    assert CapturingDockerRunner.last_network_mode is None
