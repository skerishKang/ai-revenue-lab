from pathlib import Path


STATIC = Path(__file__).resolve().parents[1] / "static"


def test_browser_stream_requests_ndjson_by_default_and_has_runtime_off_switch():
    transport = (STATIC / "chat-transport.js").read_text(encoding="utf-8")
    assert 'return window.PADIEM_CHAT_ORCHESTRATION_STREAM !== false;' in transport
    assert '"Accept": "application/x-ndjson"' in transport
    assert 'JSON.stringify({ ...(payload || {}), stream: 1 })' in transport
    assert 'orchestrationStreamingEnabled()\n        ? await requestOrchestrationStream' in transport


def test_progress_projection_uses_closed_labels_and_never_renders_event_payloads():
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    lifecycle = (STATIC / "message-lifecycle.js").read_text(encoding="utf-8")
    assert 'frame.event === "orchestration_event"' in app
    assert 'const stage = stageForOrchestrationKind[kind];' in app
    assert 'event.message' not in app
    assert 'question_checked: Object.freeze' in lifecycle
    assert 'tool_started: Object.freeze' in lifecycle
    assert 'pc_work: Object.freeze' in lifecycle


def test_thought_summary_is_collapsible_and_sensitive_content_is_projected():
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    css = (STATIC / "capability-presentation.css").read_text(encoding="utf-8")
    assert 'details.className = "orchestration-thought-summary"' in app
    assert 'paragraph.textContent = summaryText' in app
    assert r"[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}" in app
    assert "workspaces|opt|private|Volumes|srv|root" in app
    assert "[질문 내용 생략]" in app
    assert "token|password|secret" in app
    assert "[비밀 값 숨김]" in app
    assert "[내부 ID 숨김]" in app
    assert "[파일 경로 숨김]" in app
    assert ".orchestration-thought-summary > summary" in css


def test_answer_inherits_status_font_and_rich_code_keeps_monospace():
    styles = (STATIC / "styles.css").read_text(encoding="utf-8")
    code_styles = (STATIC / "rich-response.css").read_text(encoding="utf-8")
    assert ".assistant-content { color: #2f3037; font-family: inherit;" in styles
    assert 'font: 0.88rem/1.62 ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace;' in code_styles
