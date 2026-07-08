from __future__ import annotations

import os
import sys
import urllib.error
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "proxy"))


def test_proxy_policy_flags_initial_high_risk_commands() -> None:
    from mica_proxy import evaluate_risk

    risky = [
        ("git", ["push"]),
        ("terraform", ["apply"]),
        ("terraform", ["destroy"]),
        ("npm", ["publish"]),
    ]

    for tool, argv in risky:
        decision = evaluate_risk(tool, argv)
        assert decision.requires_approval
        assert decision.risk_level == "high"

    assert not evaluate_risk("git", ["status"]).requires_approval


def test_proxy_policy_can_be_loaded_from_json_file(tmp_path: Path) -> None:
    from mica_proxy import evaluate_risk, load_policy

    policy_path = tmp_path / "command-policy.json"
    policy_path.write_text(
        """
{
  "version": 1,
  "rules": [
    {
      "id": "kubectl-delete",
      "tool": "kubectl",
      "argv_prefix": ["delete"],
      "action": "require_approval",
      "risk_level": "high",
      "reason": "kubectl delete can remove cluster resources."
    }
  ]
}
""".strip(),
        encoding="utf-8",
    )

    policy = load_policy(policy_path)
    decision = evaluate_risk("kubectl", ["delete", "pod", "mica-test"], policy=policy)

    assert decision.requires_approval
    assert decision.risk_level == "high"
    assert decision.reason == "kubectl delete can remove cluster resources."
    assert not evaluate_risk("kubectl", ["get", "pods"], policy=policy).requires_approval


def test_proxy_uses_default_policy_file_for_existing_rules() -> None:
    from mica_proxy import evaluate_risk, load_default_policy

    policy = load_default_policy()

    assert evaluate_risk("git", ["push", "origin", "main"], policy=policy).requires_approval
    assert evaluate_risk("terraform", ["apply"], policy=policy).requires_approval
    assert evaluate_risk("terraform", ["destroy"], policy=policy).requires_approval
    assert evaluate_risk("npm", ["publish"], policy=policy).requires_approval
    assert evaluate_risk("kubectl", ["delete", "pod", "mica-test"], policy=policy).requires_approval


def test_proxy_resolves_real_executable_from_tool_specific_env(tmp_path: Path) -> None:
    from mica_proxy import resolve_real_executable

    real_git = tmp_path / "git.exe"
    real_git.write_text("", encoding="utf-8")

    env = {"MICA_REAL_GIT": str(real_git)}

    assert resolve_real_executable("git", env) == real_git


def test_proxy_resolves_real_executable_from_original_path(tmp_path: Path) -> None:
    from mica_proxy import resolve_real_executable

    real_git = tmp_path / "git.cmd"
    real_git.write_text("@echo off\r\n", encoding="utf-8")
    env = {
        "MICA_ORIGINAL_PATH": str(tmp_path),
        "PATHEXT": os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD"),
    }

    assert resolve_real_executable("git", env) == real_git


def test_proxy_executes_real_command_and_returns_exit_code() -> None:
    from mica_proxy import execute_real_command

    code = execute_real_command(
        sys.executable,
        ["-c", "import sys; print('mica-out'); print('mica-err', file=sys.stderr); sys.exit(7)"],
        os.environ.copy(),
    )

    assert code == 7


def test_proxy_accepts_legacy_api_url_environment_variable() -> None:
    from mica_proxy import get_api_base_url

    assert get_api_base_url({"MICA_API_URL": "http://127.0.0.1:8765/api"}) == "http://127.0.0.1:8765/api"
    assert (
        get_api_base_url(
            {
                "MICA_API_URL": "http://127.0.0.1:8765/api",
                "MICA_API_BASE_URL": "http://localhost:8000/api",
            }
        )
        == "http://localhost:8000/api"
    )


def test_command_record_includes_run_id_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    from mica_proxy import RiskDecision, create_command_record

    class FakeClient:
        payload: dict[str, object] | None = None

        def create_command(self, payload: dict[str, object]) -> dict[str, str]:
            self.payload = payload
            return {"id": "command-1"}

    monkeypatch.setenv("MICA_RUN_ID", "run-1")
    client = FakeClient()

    command_id = create_command_record(
        client,  # type: ignore[arg-type]
        tool="git",
        argv=["status"],
        risk=RiskDecision(False),
        approval_id=None,
    )

    assert command_id == "command-1"
    assert client.payload is not None
    assert client.payload["run_id"] == "run-1"


def test_proxy_times_out_pending_approval_without_executing_command(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import mica_proxy

    real_git = tmp_path / "git.cmd"
    real_git.write_text("@echo off\r\nexit /b 0\r\n", encoding="utf-8")
    finishes: list[dict[str, object]] = []

    class PendingApprovalClient:
        def __init__(self, api_base_url: str) -> None:
            self.api_base_url = api_base_url

        def create(self, payload: dict[str, object]) -> dict[str, str]:
            return {"id": "approval-1"}

        def get(self, approval_id: str) -> dict[str, str]:
            return {"id": approval_id, "status": "pending"}

        def create_command(self, payload: dict[str, object]) -> dict[str, str]:
            return {"id": "command-1"}

        def finish_command(self, command_id: str, payload: dict[str, object]) -> dict[str, object]:
            finishes.append({"id": command_id, **payload})
            return {"id": command_id, **payload}

    def fail_if_executed(*_args: object, **_kwargs: object) -> tuple[int, int]:
        raise AssertionError("real command must not execute before approval")

    monkeypatch.setattr(mica_proxy, "ApprovalClient", PendingApprovalClient)
    monkeypatch.setattr(mica_proxy, "execute_real_command_timed", fail_if_executed)

    exit_code = mica_proxy.run_proxy(
        "git",
        ["push", "origin", "main"],
        {
            "MICA_REAL_GIT": str(real_git),
            "MICA_APPROVAL_TIMEOUT_SECONDS": "0.01",
            "MICA_APPROVAL_POLL_SECONDS": "0.001",
        },
    )

    assert exit_code == 124
    assert finishes[-1]["status"] == "timeout"
    assert finishes[-1]["exit_code"] == 124


def test_proxy_fails_closed_when_approval_api_is_unavailable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import mica_proxy

    real_git = tmp_path / "git.cmd"
    real_git.write_text("@echo off\r\nexit /b 0\r\n", encoding="utf-8")

    class UnavailableApprovalClient:
        def __init__(self, api_base_url: str) -> None:
            self.api_base_url = api_base_url

        def create(self, payload: dict[str, object]) -> dict[str, str]:
            raise urllib.error.URLError("api down")

    def fail_if_executed(*_args: object, **_kwargs: object) -> tuple[int, int]:
        raise AssertionError("real command must not execute when approval API is unavailable")

    monkeypatch.setattr(mica_proxy, "ApprovalClient", UnavailableApprovalClient)
    monkeypatch.setattr(mica_proxy, "execute_real_command_timed", fail_if_executed)

    exit_code = mica_proxy.run_proxy(
        "git",
        ["push", "origin", "main"],
        {"MICA_REAL_GIT": str(real_git)},
    )

    assert exit_code == 125
