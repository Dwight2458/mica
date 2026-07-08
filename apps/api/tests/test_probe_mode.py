from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "proxy"))


def test_shim_probe_mode_records_hit_and_executes_real_command(tmp_path: Path) -> None:
    real_git = tmp_path / "real-git.cmd"
    real_git.write_text("@echo off\r\necho REAL_GIT %*\r\nexit /b 0\r\n", encoding="utf-8")
    log_path = tmp_path / "probe.jsonl"

    env = os.environ.copy()
    env["MICA_REAL_GIT"] = str(real_git)
    env["MICA_PROXY_MODE"] = "probe"
    env["MICA_PROBE_LOG"] = str(log_path)

    result = subprocess.run(
        [str(ROOT / "shims" / "git.cmd"), "push", "origin", "main"],
        env=env,
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "REAL_GIT push origin main" in result.stdout

    events = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert len(events) == 1
    assert events[0]["tool"] == "git"
    assert events[0]["argv"] == ["push", "origin", "main"]
    assert events[0]["requires_approval"] is True
    assert events[0]["risk_level"] == "high"


def test_probe_summary_reports_expected_tool_hit_matrix(tmp_path: Path) -> None:
    from mica_probe import summarize_probe_log

    log_path = tmp_path / "probe.jsonl"
    log_path.write_text(
        "\n".join(
            [
                json.dumps({"tool": "git", "argv": ["status"], "requires_approval": False}),
                json.dumps({"tool": "npm", "argv": ["-v"], "requires_approval": False}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    summary = summarize_probe_log(log_path, ["git", "npm", "terraform"])

    assert summary["total_hits"] == 2
    assert summary["tools"]["git"]["hit"] is True
    assert summary["tools"]["npm"]["hit"] is True
    assert summary["tools"]["terraform"]["hit"] is False
    assert summary["hit_rate"] == 2 / 3
