from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class EvalCase:
    id: str
    title: str
    prompt: str
    expected_tools: tuple[str, ...]
    risk_expectation: str


def load_eval_cases(case_dir: Path) -> list[EvalCase]:
    cases: list[EvalCase] = []
    for path in sorted(case_dir.glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        cases.append(
            EvalCase(
                id=str(raw["id"]),
                title=str(raw["title"]),
                prompt=str(raw["prompt"]),
                expected_tools=tuple(str(tool) for tool in raw.get("expected_tools", [])),
                risk_expectation=str(raw.get("risk_expectation", "unknown")),
            )
        )
    return cases


def load_result_rows(result_path: Path) -> list[dict[str, Any]]:
    if not result_path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in result_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def summarize_results(result_path: Path, cases: list[EvalCase]) -> dict[str, Any]:
    rows = load_result_rows(result_path)
    return {
        "total_cases": len(cases),
        "total_results": len(rows),
        **_aggregate_rows(rows),
        "agents": _summarize_agents(rows),
    }


def _aggregate_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "success_rate": 0,
            "average_duration_ms": 0,
            "approval_count": 0,
            "rejected_count": 0,
            "risky_command_count": 0,
        }
    return {
        "success_rate": sum(1 for row in rows if row.get("status") == "success") / len(rows),
        "average_duration_ms": round(sum(int(row.get("duration_ms", 0)) for row in rows) / len(rows)),
        "approval_count": sum(int(row.get("approval_count", 0)) for row in rows),
        "rejected_count": sum(int(row.get("rejected_count", 0)) for row in rows),
        "risky_command_count": sum(int(row.get("risky_command_count", 0)) for row in rows),
    }


def _summarize_agents(rows: list[dict[str, Any]]) -> dict[str, Any]:
    agents = sorted({str(row.get("agent", "unknown")) for row in rows})
    return {agent: {"total_results": len(agent_rows), **_aggregate_rows(agent_rows)} for agent in agents for agent_rows in [[row for row in rows if row.get("agent") == agent]]}


def render_markdown_report(summary: dict[str, Any]) -> str:
    lines = [
        "# Mica Eval Report",
        "",
        f"- Total cases: {summary['total_cases']}",
        f"- Total results: {summary['total_results']}",
        f"- Success rate: {summary['success_rate']:.2f}",
        f"- Average duration: {summary['average_duration_ms']} ms",
        f"- Approval count: {summary['approval_count']}",
        f"- Rejected count: {summary['rejected_count']}",
        f"- Risky command count: {summary['risky_command_count']}",
        "",
        "## Agents",
        "",
        "| Agent | Results | Success Rate | Avg Duration | Approvals | Rejected | Risky Commands |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for agent, metrics in summary["agents"].items():
        lines.append(
            f"| {agent} | {metrics['total_results']} | {metrics['success_rate']:.2f} | "
            f"{metrics['average_duration_ms']} ms | {metrics['approval_count']} | "
            f"{metrics['rejected_count']} | {metrics['risky_command_count']} |"
        )
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="mica-eval")
    parser.add_argument("--cases", required=True, type=Path)
    parser.add_argument("--results", required=True, type=Path)
    parser.add_argument("--format", choices=["json", "markdown"], default="json")
    parser.add_argument("--out", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = summarize_results(args.results, load_eval_cases(args.cases))
    rendered = (
        render_markdown_report(summary)
        if args.format == "markdown"
        else json.dumps(summary, indent=2, ensure_ascii=False)
    )
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered, encoding="utf-8")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
