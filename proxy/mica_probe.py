from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load_probe_events(log_path: Path) -> list[dict[str, Any]]:
    if not log_path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in log_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            events.append(json.loads(line))
    return events


def summarize_probe_log(log_path: Path, expected_tools: list[str]) -> dict[str, Any]:
    events = load_probe_events(log_path)
    tools: dict[str, dict[str, Any]] = {}
    for tool in expected_tools:
        hits = [event for event in events if event.get("tool") == tool]
        tools[tool] = {
            "hit": bool(hits),
            "hit_count": len(hits),
            "commands": [" ".join([str(hit.get("tool")), *map(str, hit.get("argv", []))]) for hit in hits],
        }
    hit_count = sum(1 for item in tools.values() if item["hit"])
    return {
        "log_path": str(log_path),
        "expected_tools": expected_tools,
        "total_hits": len(events),
        "hit_tools": hit_count,
        "hit_rate": hit_count / len(expected_tools) if expected_tools else 0,
        "tools": tools,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="mica-probe")
    parser.add_argument("--log", required=True, type=Path)
    parser.add_argument("--expect", required=True, help="Comma-separated tools, e.g. git,npm,terraform")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    expected_tools = [item.strip() for item in args.expect.split(",") if item.strip()]
    print(json.dumps(summarize_probe_log(args.log, expected_tools), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
