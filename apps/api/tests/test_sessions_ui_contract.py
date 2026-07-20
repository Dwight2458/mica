from __future__ import annotations

from pathlib import Path


def test_sessions_page_exposes_persistent_session_create_form() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    source = (repo_root / "apps" / "web" / "src" / "app" / "sessions" / "page.tsx").read_text(encoding="utf-8")

    assert "Start Agent Session" in source
    assert 'apiRequest<SessionContinueResponse>("/sessions"' in source
    assert 'name="prompt"' in source
    assert 'name="agent_type"' in source
    assert 'name="runner_mode"' in source
    assert "Recent Sessions" in source
    assert "router.push(`/sessions/${encodeURIComponent(result.session.id)}`)" in source


def test_session_detail_page_exposes_continue_console_and_run_evidence_link() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    source = (repo_root / "apps" / "web" / "src" / "app" / "sessions" / "[id]" / "page.tsx").read_text(
        encoding="utf-8"
    )

    assert "Conversation" in source
    assert "Continue Session" in source
    assert "Latest Run" in source
    assert "Open Evidence" in source
    assert 'apiRequest<SessionContinueResponse>(`/sessions/${encodeURIComponent(sessionId)}/continue`' in source
    assert "Session keeps the goal, display messages, and native agent handle." in source
    assert "Run keeps one Agent CLI invocation and its governance evidence." in source
    assert "Continuation uses the agent" in source
    assert "native session/thread id when available." in source


def test_session_conversation_uses_safe_markdown_and_collapsed_tool_activity() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    page_source = (repo_root / "apps" / "web" / "src" / "app" / "sessions" / "[id]" / "page.tsx").read_text(
        encoding="utf-8"
    )
    component_source = (repo_root / "apps" / "web" / "src" / "components" / "session-message.tsx").read_text(
        encoding="utf-8"
    )

    assert "<SessionMessageView" in page_source
    assert "ReactMarkdown" in component_source
    assert "remarkGfm" in component_source
    assert "<details" in component_source
    assert "part_type" in component_source
    assert "dangerouslySetInnerHTML" not in component_source
