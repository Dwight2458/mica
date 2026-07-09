from __future__ import annotations

from pathlib import Path


def test_runs_page_exposes_interactive_agent_run_form() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    source = (repo_root / "apps" / "web" / "src" / "app" / "runs" / "page.tsx").read_text(encoding="utf-8")

    assert "Start Agent Run" in source
    assert 'apiRequest<AgentRunResponse>("/agent-runs"' in source
    assert "router.push(`/runs/${encodeURIComponent(result.run.id)}`)" in source
    assert 'name="prompt"' in source
    assert 'name="agent_type"' in source
    assert 'name="runner_mode"' in source
    assert "Advanced Docker command" in source
    assert 'apiRequest<DockerExecuteResponse>("/docker/execute"' in source
    assert 'name="workspace"' in source
    assert 'name="command"' in source
    assert 'name="image"' in source
    assert 'name="network_mode"' in source
    assert 'name="inject_proxy"' in source


def test_runs_page_does_not_poll_forever_after_runs_finish() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    source = (repo_root / "apps" / "web" / "src" / "app" / "runs" / "page.tsx").read_text(encoding="utf-8")
    detail_source = (
        repo_root / "apps" / "web" / "src" / "app" / "runs" / "[id]" / "page.tsx"
    ).read_text(encoding="utf-8")

    assert "hasActiveRuns" in source
    assert 'run.status === "started"' in source
    assert "if (!hasActiveRuns) return" in source
    assert 'if (run?.status !== "started") return' in detail_source
    assert "window.setInterval(() => void refresh(), 2000)" in detail_source
    assert "new EventSource" in detail_source


def test_run_detail_page_separates_runtime_internal_trace_events() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    source = (repo_root / "apps" / "web" / "src" / "app" / "runs" / "[id]" / "page.tsx").read_text(
        encoding="utf-8"
    )

    assert "showRuntimeInternal" in source
    assert "commandOriginById" in source
    assert "eventCommandOrigin(event)" in source
    assert '!== "runtime_internal"' in source
    assert "Debug events" in source
    assert "Payload" in source
