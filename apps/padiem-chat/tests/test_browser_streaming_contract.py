from __future__ import annotations

import json
import subprocess
from pathlib import Path


APP_PATH = Path(__file__).resolve().parents[1] / "static" / "app.js"


def _source() -> str:
    return APP_PATH.read_text(encoding="utf-8")


def _stream_helpers() -> str:
    source = _source()
    start = source.index("  function parseSseFrame(frame) {")
    end = source.index("  function formatBytes(bytes) {")
    return source[start:end]


def _run_node(script: str, *args: str) -> str:
    completed = subprocess.run(
        ["node", "-e", script, *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def test_text_only_streams_but_attachment_keeps_completed_json() -> None:
    source = _source()

    assert 'fetch("/api/chat/stream"' in source
    assert 'fetch("/api/chat"' in source
    assert "if (attachments) {" in source
    assert "return await requestCompletedAnswer(" in source
    assert "return await requestStreamingAnswer(" in source
    assert '"Accept": "text/event-stream"' in source
    assert '"Accept": "application/json"' in source


def test_sse_parser_accepts_comments_unknown_fields_and_multiline_data() -> None:
    helpers = _stream_helpers()
    frame = (
        ": keepalive\r\n"
        "event: delta\r\n"
        "id: ignored-extension\r\n"
        "data: {\"delta\":\"첫\"}\r\n"
        "data: {\"extra\":true}\r\n"
    )
    script = helpers + "\nconsole.log(JSON.stringify(parseSseFrame(process.argv[1])));"
    parsed = json.loads(_run_node(script, frame))

    assert parsed == {
        "event": "delta",
        "data": '{"delta":"첫"}\n{"extra":true}',
    }


def test_sse_reader_handles_fragmented_crlf_and_multiple_frames() -> None:
    helpers = _stream_helpers()
    chunks = [
        "event: delta\r",
        "\ndata: {\"delta\":\"안\"}\r\n\r",
        "\nevent: delta\ndata: {\"delta\":\"녕\"}\n\n",
        ": heartbeat\n\nevent: done\r\ndata: {\"done\":true}\r\n\r\n",
    ]
    script = helpers + r'''
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
  await readSseEvents(response, async (frame) => {
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
    helpers = _stream_helpers()
    chunks = [
        'event: delta\ndata: {"delta":"부분"}\n\n',
        'event: done\ndata: {"done":true}\n\n',
    ]
    script = helpers + r'''
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
  await readSseEvents(response, async () => { seen += 1; return true; });
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
    assert 'messages = outboundMessages.concat([{ role: "assistant", content: answer }]).slice(-20);' in done_source
    assert "conversation_id" in done_source
    assert "project_files_used" in done_source

    partial_start = source.index("  function renderStreamError(")
    partial_end = source.index("  function parseSseFrame(", partial_start)
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
