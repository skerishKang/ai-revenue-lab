from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_PATH = ROOT / "static" / "app.js"
TRANSPORT_PATH = ROOT / "static" / "chat-transport.js"
LIFECYCLE_PATH = ROOT / "static" / "message-lifecycle.js"
INDEX_PATH = ROOT / "static" / "index.html"


def _source() -> str:
    return APP_PATH.read_text(encoding="utf-8")


def _transport_source() -> str:
    return TRANSPORT_PATH.read_text(encoding="utf-8")


def _run_node(script: str, *args: str) -> str:
    completed = subprocess.run(
        ["node", "-e", script, *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _transport_runtime() -> str:
    return "global.window = globalThis;\n" + _transport_source()


def test_text_only_streams_but_attachment_keeps_completed_json() -> None:
    source = _source()
    transport = _transport_source()
    html = INDEX_PATH.read_text(encoding="utf-8")

    assert "chatTransport.requestStreaming(payload, signal)" in source
    assert "chatTransport.requestCompleted(payload, signal)" in source
    assert "if (attachments) {" in source
    assert "return await requestCompletedAnswer(" in source
    assert "return await requestStreamingAnswer(" in source
    assert 'fetch("/api/chat/stream"' in transport
    assert 'fetch("/api/chat"' in transport
    assert '"Accept": "text/event-stream"' in transport
    assert '"Accept": "application/json"' in transport
    assert 'fetch("/api/chat/stream"' not in source
    assert 'fetch("/api/chat"' not in source
    assert html.index('<script src="./document-binary.js"></script>') < html.index('<script src="./chat-transport.js"></script>')
    assert html.index('<script src="./chat-transport.js"></script>') < html.index('<script src="./conversation-state.js"></script>')
    assert html.index('<script src="./conversation-state.js"></script>') < html.index('<script src="./message-lifecycle.js"></script>')
    assert html.index('<script src="./message-lifecycle.js"></script>') < html.index('<script src="./app.js"></script>')
    assert html.index('<script src="./app.js"></script>') < html.index('<script src="./a11y.js"></script>')


def test_sse_parser_accepts_comments_unknown_fields_and_multiline_data() -> None:
    frame = (
        ": keepalive\r\n"
        "event: delta\r\n"
        "id: ignored-extension\r\n"
        "data: {\"delta\":\"첫\"}\r\n"
        "data: {\"extra\":true}\r\n"
    )
    script = _transport_runtime() + "\nconsole.log(JSON.stringify(PadiemChatTransport.parseSseFrame(process.argv[1])));"
    parsed = json.loads(_run_node(script, frame))

    assert parsed == {
        "event": "delta",
        "data": '{"delta":"첫"}\n{"extra":true}',
    }


def test_sse_reader_handles_fragmented_crlf_and_multiple_frames() -> None:
    chunks = [
        "event: delta\r",
        "\ndata: {\"delta\":\"안\"}\r\n\r",
        "\nevent: delta\ndata: {\"delta\":\"녕\"}\n\n",
        ": heartbeat\n\nevent: done\r\ndata: {\"done\":true}\r\n\r\n",
    ]
    script = _transport_runtime() + r'''
const chunks = JSON.parse(process.argv[1]);
const encoder = new TextEncoder();
let index = 0;
let cancelled = false;
let released = false;
const response = {
  body: {
    getReader() {
      return {
        async read() {
          if (index >= chunks.length) return { done: true, value: undefined };
          return { done: false, value: encoder.encode(chunks[index++]) };
        },
        async cancel() { cancelled = true; },
        releaseLock() { released = true; },
      };
    },
  },
};
const events = [];
(async () => {
  await PadiemChatTransport.readSseEvents(response, async (frame) => {
    events.push(frame);
    return false;
  });
  console.log(JSON.stringify({ events, cancelled, released }));
})().catch((error) => { console.error(error); process.exit(1); });
'''
    result = json.loads(_run_node(script, json.dumps(chunks, ensure_ascii=False)))

    assert result["events"] == [
        {"event": "delta", "data": '{"delta":"안"}'},
        {"event": "delta", "data": '{"delta":"녕"}'},
        {"event": "done", "data": '{"done":true}'},
    ]
    assert result["cancelled"] is False
    assert result["released"] is True


def test_sse_reader_cancels_when_consumer_stops_early() -> None:
    chunks = [
        'event: delta\ndata: {"delta":"부분"}\n\n',
        'event: done\ndata: {"done":true}\n\n',
    ]
    script = _transport_runtime() + r'''
const chunks = JSON.parse(process.argv[1]);
const encoder = new TextEncoder();
let index = 0;
let cancelled = false;
let released = false;
const response = {
  body: {
    getReader() {
      return {
        async read() {
          if (index >= chunks.length) return { done: true, value: undefined };
          return { done: false, value: encoder.encode(chunks[index++]) };
        },
        async cancel() { cancelled = true; },
        releaseLock() { released = true; },
      };
    },
  },
};
(async () => {
  let seen = 0;
  await PadiemChatTransport.readSseEvents(response, async () => { seen += 1; return true; });
  console.log(JSON.stringify({ seen, cancelled, released }));
})().catch((error) => { console.error(error); process.exit(1); });
'''
    result = json.loads(_run_node(script, json.dumps(chunks, ensure_ascii=False)))

    assert result == {"seen": 1, "cancelled": True, "released": True}


def test_stream_state_commits_only_on_done_and_partial_error_is_preserved() -> None:
    source = _source()
    stream_start = source.index("  async function requestStreamingAnswer(")
    stream_end = source.index("  async function requestAnswer(", stream_start)
    stream_source = source[stream_start:stream_end]

    assert 'paragraph.textContent = answer;' in stream_source
    assert 'renderStreamError(article, message' in stream_source
    assert 'applyStreamDone(article, data, answer' in stream_source
    assert 'messages = outboundMessages.concat' not in stream_source

    done_start = source.index("  function applyStreamDone(")
    done_end = source.index("  async function requestStreamingAnswer(", done_start)
    done_source = source[done_start:done_end]
    assert "conversationState.commitAssistant(outboundMessages, answer);" in done_source
    assert "conversationState.setConversationId(data.conversation_id);" in done_source
    assert "project_files_used" in done_source

    partial_start = source.index("  function renderStreamError(")
    partial_end = source.index("  function formatBytes(", partial_start)
    partial_source = source[partial_start:partial_end]
    assert "content.replaceChildren()" not in partial_source
    assert "content.appendChild(buildRetryBox" in partial_source


def test_new_chat_aborts_active_stream_and_epoch_blocks_stale_mutation() -> None:
    source = _source()
    reset_start = source.index("  function resetConversation(")
    reset_end = source.index("  function selectProject(", reset_start)
    reset_source = source[reset_start:reset_end]

    assert "conversationEpoch += 1;" in reset_source
    assert "activeRequestController.abort();" in reset_source
    assert "activeRequestController = null;" in reset_source

    request_start = source.index("  async function requestAnswer(")
    request_end = source.index("  async function submitPrompt(", request_start)
    request_source = source[request_start:request_end]
    assert "const requestEpoch = conversationEpoch;" in request_source
    assert "const controller = new AbortController();" in request_source
    assert 'error.name === "AbortError"' in request_source
    assert "requestEpoch !== conversationEpoch" in request_source
    assert "if (activeRequestController === controller)" in request_source


def test_streamed_browser_path_never_renders_provider_route_details() -> None:
    source = _source()
    stream_start = source.index("  async function requestStreamingAnswer(")
    stream_end = source.index("  async function requestAnswer(", stream_start)
    stream_source = source[stream_start:stream_end]

    assert "route-details" not in stream_source
    assert "provider" not in stream_source
    assert 'textContent = "AI 응답"' in stream_source


def test_answer_lifecycle_is_explicit_and_success_actions_are_completed_only() -> None:
    source = _source()
    lifecycle = LIFECYCLE_PATH.read_text(encoding="utf-8")

    assert 'STREAMING: "streaming"' in lifecycle
    assert 'COMPLETED: "completed"' in lifecycle
    assert 'FAILED: "failed"' in lifecycle
    assert 'CANCELLED: "cancelled"' in lifecycle
    assert 'TIMED_OUT: "timed_out"' in lifecycle
    assert 'isCompleted(article)' in lifecycle
    assert '"padiem:message-lifecycle"' in lifecycle
    assert 'bubbles: true' in lifecycle
    assert 'detail: { state }' in lifecycle
    assert 'const MESSAGE_LIFECYCLE = window.PadiemChatLifecycle.states;' in source
    assert 'window.PadiemChatLifecycle = Object.freeze' not in source

    outputs = (APP_PATH.parent / "outputs.js").read_text(encoding="utf-8")
    export = (APP_PATH.parent / "conversation-export.js").read_text(encoding="utf-8")
    assert 'if (!lifecycleApi().isCompleted(article))' in outputs
    assert 'button.hidden = !outputsReady || !eligible' in outputs
    assert 'if (hasIncompleteAssistant()) return [];' in export
    assert 'messageList.addEventListener("padiem:message-lifecycle"' in outputs
    assert 'messageList.addEventListener("padiem:message-lifecycle"' in export


def test_cancel_and_retry_are_product_surface_only_and_preserve_stream_boundary() -> None:
    source = _source()
    transport = _transport_source()
    assert 'id="cancelStreamButton"' in INDEX_PATH.read_text(encoding="utf-8")
    assert "cancelActiveStream" in source
    assert 'activeRequestCancelReason = "user_cancel"' in source
    assert "renderCancelled(article" in source
    assert 'textContent = "생성 취소됨"' in source
    assert '"다시 생성"' in source
    assert 'retry.textContent = actionLabel' in source
    assert "requestStreamingAnswer(article" in source
    assert "chatTransport.requestStreaming(payload, signal)" in source
    assert 'fetch("/api/chat/stream"' in transport


def test_timeout_error_keeps_incomplete_answer_in_fail_closed_states() -> None:
    source = _source()
    assert 'error && error.code === "upstream_timeout"' in source
    assert 'MESSAGE_LIFECYCLE.TIMED_OUT' in source
    assert 'lifecycleForError(error)' in source
    assert 'PadiemChatLifecycle.set(article, lifecycle)' in source
    assert 'PadiemChatLifecycle.set(article, MESSAGE_LIFECYCLE.COMPLETED)' in source


def test_cancel_control_has_mobile_safe_target_and_accessibility_contract() -> None:
    source = _source()
    html = INDEX_PATH.read_text(encoding="utf-8")
    css = (APP_PATH.parent / "padiem-cinematic-chat.css").read_text(encoding="utf-8")
    assert 'aria-label="답변 생성 취소"' in html
    assert 'cancelStreamButton.hidden = !inFlight' in source
    assert 'min-width: 64px' in css
    assert 'min-height: 42px' in css
