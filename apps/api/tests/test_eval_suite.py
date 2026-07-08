from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "proxy"))


def test_eval_suite_loads_cases_and_summarizes_results(tmp_path: Path) -> None:
    from mica_eval import load_eval_cases, summarize_results

    case_dir = tmp_path / "cases"
    case_dir.mkdir()
    for index in range(5):
        (case_dir / f"case-{index}.json").write_text(
            json.dumps(
                {
                    "id": f"case-{index}",
                    "title": f"Case {index}",
                    "prompt": "Run a command.",
                    "expected_tools": ["git"],
                    "risk_expectation": "low",
                }
            ),
            encoding="utf-8",
        )

    result_path = tmp_path / "results.jsonl"
    result_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "agent": "opencode",
                        "case_id": "case-0",
                        "status": "success",
                        "duration_ms": 100,
                        "approval_count": 0,
                        "rejected_count": 0,
                        "risky_command_count": 0,
                    }
                ),
                json.dumps(
                    {
                        "agent": "codex",
                        "case_id": "case-1",
                        "status": "failed",
                        "duration_ms": 300,
                        "approval_count": 1,
                        "rejected_count": 1,
                        "risky_command_count": 1,
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    cases = load_eval_cases(case_dir)
    summary = summarize_results(result_path, cases)

    assert [case.id for case in cases] == [f"case-{index}" for index in range(5)]
    assert summary["total_cases"] == 5
    assert summary["total_results"] == 2
    assert summary["success_rate"] == 0.5
    assert summary["average_duration_ms"] == 200
    assert summary["approval_count"] == 1
    assert summary["rejected_count"] == 1
    assert summary["risky_command_count"] == 1
    assert summary["agents"]["opencode"]["success_rate"] == 1.0
    assert summary["agents"]["codex"]["success_rate"] == 0.0
