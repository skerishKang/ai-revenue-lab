from pathlib import Path


STATIC = Path(__file__).resolve().parents[1] / "static"


def test_browser_stream_requests_ndjson_by_default_and_has_runtime_off_switch():
    transport = (STATIC / "chat-transport.js").read_text(encoding="utf-8")
    assert 'return window.PADIEM_CHAT_ORCHESTRATION_STREAM !== false;' in transport
    assert '"Accept": "application/x-ndjson"' in transport
    assert 'body: JSON.stringify(payload || {})' in transport
    assert 'stream: 1' not in transport
    assert 'orchestrationStreamingEnabled()\n        ? await requestOrchestrationStream' in transport


def test_progress_projection_uses_closed_labels_and_never_renders_event_payloads():
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    stream = (STATIC / "chat-streaming-module.js").read_text(encoding="utf-8")
    lifecycle = (STATIC / "message-lifecycle.js").read_text(encoding="utf-8")
    server = (STATIC.parent / "app" / "orchestration_stream.py").read_text(encoding="utf-8")
    assert 'frame.event === "orchestration_event"' in stream
    assert 'frame.event === "progress"' in stream
    assert 'recordProgressFrame?.(article, value)' in stream
    assert 'value.type !== "progress"' in lifecycle
    assert 'type: "progress", sequence: value.sequence, label: value.label' in lifecycle
    assert '"run_started"' in server
    assert '"pc_progress", "heartbeat"' in server
    assert 'const stage = stageForOrchestrationKind[kind];' in stream
    assert 'event.message' not in app
    assert 'event.message' not in stream
    assert 'question_checked: Object.freeze' in lifecycle
    assert 'tool_started: Object.freeze' in lifecycle
    assert 'pc_work: Object.freeze' in lifecycle


def test_thought_summary_is_collapsible_and_sensitive_content_is_projected():
    stream = (STATIC / "chat-streaming-module.js").read_text(encoding="utf-8")
    css = (STATIC / "capability-presentation.css").read_text(encoding="utf-8")
    assert 'details.className = "orchestration-thought-summary"' in stream
    assert 'paragraph.textContent = summaryText' in stream
    assert r"[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}" in stream
    assert "A-Za-z]:[\\\\/]" in stream
    assert "replace(/(^|" in stream
    assert "[user prompt omitted]" in stream
    assert "token|password|secret" in stream
    assert "[secret redacted]" in stream
    assert "[internal ID redacted]" in stream
    assert "[file path redacted]" in stream
    assert ".orchestration-thought-summary > summary" in css


def test_answer_inherits_status_font_and_rich_code_keeps_monospace():
    styles = (STATIC / "styles.css").read_text(encoding="utf-8")
    code_styles = (STATIC / "rich-response.css").read_text(encoding="utf-8")
    assert ".assistant-content { color: #2f3037; font-family: inherit;" in styles
    assert 'font: 0.88rem/1.62 ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace;' in code_styles
