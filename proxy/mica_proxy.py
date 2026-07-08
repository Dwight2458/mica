from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


APPROVAL_REJECTED_EXIT = 126
APPROVAL_TIMEOUT_EXIT = 124
PROXY_FAILURE_EXIT = 125
DEFAULT_POLICY_PATH = Path(__file__).resolve().parents[1] / "policies" / "command-policy.json"


@dataclass(frozen=True)
class RiskDecision:
    requires_approval: bool
    risk_level: str = "low"
    reason: str = "Command does not match a require_approval policy rule."


@dataclass(frozen=True)
class PolicyRule:
    id: str
    tool: str
    argv_prefix: tuple[str, ...]
    action: str
    risk_level: str
    reason: str


@dataclass(frozen=True)
class CommandPolicy:
    version: int
    rules: tuple[PolicyRule, ...]


def load_policy(path: str | Path) -> CommandPolicy:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    rules = tuple(
        PolicyRule(
            id=str(item["id"]),
            tool=str(item["tool"]).lower(),
            argv_prefix=tuple(str(part).lower() for part in item.get("argv_prefix", [])),
            action=str(item["action"]),
            risk_level=str(item.get("risk_level", "medium")),
            reason=str(item.get("reason", f"Policy rule {item['id']} requires approval.")),
        )
        for item in raw.get("rules", [])
    )
    return CommandPolicy(version=int(raw.get("version", 1)), rules=rules)


def load_default_policy() -> CommandPolicy:
    return load_policy(DEFAULT_POLICY_PATH)


def load_policy_from_env(env: dict[str, str]) -> CommandPolicy:
    configured = env.get("MICA_POLICY_FILE")
    return load_policy(configured) if configured else load_default_policy()


def argv_matches_prefix(argv: list[str], prefix: tuple[str, ...]) -> bool:
    normalized = [item.lower() for item in argv]
    return len(normalized) >= len(prefix) and tuple(normalized[: len(prefix)]) == prefix


def evaluate_risk(tool: str, argv: list[str], policy: CommandPolicy | None = None) -> RiskDecision:
    active_policy = policy or load_default_policy()
    normalized_tool = tool.lower()
    for rule in active_policy.rules:
        if rule.tool != normalized_tool:
            continue
        if not argv_matches_prefix(argv, rule.argv_prefix):
            continue
        if rule.action == "require_approval":
            return RiskDecision(True, rule.risk_level, rule.reason)
    return RiskDecision(False)


def resolve_real_executable(tool: str, env: dict[str, str]) -> Path:
    specific_key = f"MICA_REAL_{tool.upper().replace('-', '_')}"
    configured = env.get(specific_key)
    if configured:
        path = Path(configured)
        if path.exists():
            return path
        raise FileNotFoundError(f"{specific_key} points to a missing executable: {configured}")

    original_path = env.get("MICA_ORIGINAL_PATH")
    if not original_path:
        raise FileNotFoundError("MICA_ORIGINAL_PATH is not set and no tool-specific real executable was provided.")

    resolved = shutil.which(tool, path=original_path)
    if resolved is None:
        raise FileNotFoundError(f"Could not resolve real executable for {tool!r} from MICA_ORIGINAL_PATH.")
    return Path(resolved)


def execute_real_command(executable: str | Path, argv: list[str], env: dict[str, str]) -> int:
    next_env = env.copy()
    next_env["MICA_PROXY_BYPASS"] = "1"
    completed = subprocess.run([str(executable), *argv], env=next_env, check=False)
    return int(completed.returncode)


def record_probe_hit(
    *,
    tool: str,
    argv: list[str],
    executable: Path,
    risk: RiskDecision,
    env: dict[str, str],
) -> None:
    log_path = Path(env.get("MICA_PROBE_LOG", ".mica/probe-events.jsonl"))
    log_path.parent.mkdir(parents=True, exist_ok=True)
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mode": "probe",
        "tool": tool,
        "argv": argv,
        "command_line": build_command_line(tool, argv),
        "cwd": os.getcwd(),
        "real_executable": str(executable),
        "requires_approval": risk.requires_approval,
        "risk_level": risk.risk_level,
        "reason": risk.reason,
    }
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")


class ApprovalClient:
    def __init__(self, api_base_url: str) -> None:
        self.api_base_url = api_base_url.rstrip("/")

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/approvals", payload)

    def get(self, approval_id: str) -> dict[str, Any]:
        return self._request("GET", f"/approvals/{approval_id}")

    def create_command(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/commands", payload)

    def finish_command(self, command_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("PATCH", f"/commands/{command_id}/finish", payload)

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self.api_base_url}{path}",
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))


def build_command_line(tool: str, argv: list[str]) -> str:
    return " ".join([tool, *[shlex.quote(item) for item in argv]])


def get_api_base_url(env: dict[str, str]) -> str:
    return env.get("MICA_API_BASE_URL") or env.get("MICA_API_URL") or "http://localhost:8000/api"


def create_command_record(
    client: ApprovalClient,
    *,
    tool: str,
    argv: list[str],
    risk: RiskDecision,
    approval_id: str | None,
    env: dict[str, str] | None = None,
) -> str | None:
    active_env = env or os.environ
    payload = {
        "run_id": active_env.get("MICA_RUN_ID"),
        "tool": tool,
        "argv": argv,
        "command_line": build_command_line(tool, argv),
        "cwd": os.getcwd(),
        "risk_level": risk.risk_level,
        "requires_approval": risk.requires_approval,
        "approval_id": approval_id,
    }
    try:
        record = client.create_command(payload)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError):
        return None
    return str(record.get("id")) if record.get("id") else None


def finish_command_record(
    client: ApprovalClient,
    command_id: str | None,
    *,
    status: str,
    exit_code: int,
    duration_ms: int,
) -> None:
    if command_id is None:
        return
    try:
        client.finish_command(
            command_id,
            {"status": status, "exit_code": exit_code, "duration_ms": duration_ms},
        )
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError):
        return


def execute_real_command_timed(executable: str | Path, argv: list[str], env: dict[str, str]) -> tuple[int, int]:
    started = time.perf_counter()
    exit_code = execute_real_command(executable, argv, env)
    duration_ms = int((time.perf_counter() - started) * 1000)
    return exit_code, duration_ms


def wait_for_decision(
    client: ApprovalClient,
    approval_id: str,
    *,
    timeout_seconds: float,
    poll_seconds: float,
) -> str:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        approval = client.get(approval_id)
        status = str(approval.get("status"))
        if status in {"approved", "rejected"}:
            return status
        time.sleep(poll_seconds)
    return "timeout"


def run_proxy(tool: str, argv: list[str], env: dict[str, str] | None = None) -> int:
    env = env or os.environ.copy()
    try:
        executable = resolve_real_executable(tool, env)
    except OSError as exc:
        print(f"MICA_PROXY_ERROR: {exc}", file=sys.stderr)
        return PROXY_FAILURE_EXIT

    try:
        policy = load_policy_from_env(env)
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        print(f"MICA_POLICY_ERROR: {exc}", file=sys.stderr)
        return PROXY_FAILURE_EXIT

    risk = evaluate_risk(tool, argv, policy=policy)
    if env.get("MICA_PROXY_MODE") == "probe":
        record_probe_hit(tool=tool, argv=argv, executable=executable, risk=risk, env=env)
        return execute_real_command(executable, argv, env)

    client = ApprovalClient(get_api_base_url(env))

    if not risk.requires_approval or env.get("MICA_PROXY_BYPASS") == "1":
        command_id = create_command_record(client, tool=tool, argv=argv, risk=risk, approval_id=None, env=env)
        exit_code, duration_ms = execute_real_command_timed(executable, argv, env)
        finish_command_record(
            client,
            command_id,
            status="completed" if exit_code == 0 else "failed",
            exit_code=exit_code,
            duration_ms=duration_ms,
        )
        return exit_code

    payload = {
        "tool": tool,
        "argv": argv,
        "command_line": build_command_line(tool, argv),
        "cwd": os.getcwd(),
        "risk_level": risk.risk_level,
        "reason": risk.reason,
    }
    try:
        approval = client.create(payload)
        command_id = create_command_record(
            client,
            tool=tool,
            argv=argv,
            risk=risk,
            approval_id=str(approval["id"]),
            env=env,
        )
        decision = wait_for_decision(
            client,
            str(approval["id"]),
            timeout_seconds=float(env.get("MICA_APPROVAL_TIMEOUT_SECONDS", "300")),
            poll_seconds=float(env.get("MICA_APPROVAL_POLL_SECONDS", "1")),
        )
    except (KeyError, ValueError, urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"MICA_APPROVAL_UNAVAILABLE: {exc}", file=sys.stderr)
        return PROXY_FAILURE_EXIT

    if decision == "approved":
        exit_code, duration_ms = execute_real_command_timed(executable, argv, env)
        finish_command_record(
            client,
            command_id,
            status="completed" if exit_code == 0 else "failed",
            exit_code=exit_code,
            duration_ms=duration_ms,
        )
        return exit_code
    if decision == "rejected":
        print("MICA_APPROVAL_REJECTED", file=sys.stderr)
        finish_command_record(
            client,
            command_id,
            status="rejected",
            exit_code=APPROVAL_REJECTED_EXIT,
            duration_ms=0,
        )
        return APPROVAL_REJECTED_EXIT
    print("MICA_APPROVAL_TIMEOUT", file=sys.stderr)
    finish_command_record(
        client,
        command_id,
        status="timeout",
        exit_code=APPROVAL_TIMEOUT_EXIT,
        duration_ms=0,
    )
    return APPROVAL_TIMEOUT_EXIT


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="mica-proxy")
    parser.add_argument("--tool", required=True)
    parser.add_argument("command_args", nargs=argparse.REMAINDER)
    parsed = parser.parse_args(argv)
    if parsed.command_args[:1] == ["--"]:
        parsed.command_args = parsed.command_args[1:]
    return parsed


def main() -> int:
    args = parse_args(sys.argv[1:])
    return run_proxy(args.tool, list(args.command_args))


if __name__ == "__main__":
    raise SystemExit(main())
