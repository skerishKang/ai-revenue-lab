from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_PATH = ROOT / "static" / "app.js"
TRANSPORT_PATH = ROOT / "static" / "chat-transport.js"
LIFECYCLE_PATH = ROOT / "static" / "message-lifecycle.js"
INDEX_PATH = ROOT / "static" / "index.html"
LOCALE_PATH = ROOT / "static" / "locale.js"


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
    # #2505: Chat keeps the completed JSON path for an attachment; the same
    # guard now also keeps a Claw attachment on its own P01 lane.
    assert "if (attachments && !clawGeneralRequest) {" in source
    # Success recording for one-click regenerate keeps the same dispatch
    # shape: completed JSON for attachments, streaming otherwise.
    assert "await requestCompletedAnswer(" in source
    assert "await requestStreamingAnswer(" in source
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
    reset_start = source.index("  function resetConversationView(")
    reset_end = source.index("  function resetConversation(", reset_start)
    reset_source = source[reset_start:reset_end]

    assert "conversationEpoch += 1;" in reset_source
    assert "activeRequestController.abort();" in reset_source
    assert "activeRequestController = null;" in reset_source

    # Chat/Claw separation: the sidebar Chat entry returns to the Chat conversation while the
    # Claw workspace is open, and otherwise starts a new Chat conversation.
    entry_start = source.index("  function resetConversation(")
    entry_end = source.index("  function selectProject(", entry_start)
    entry_source = source[entry_start:entry_end]
    assert "switchConversationProduct(PRODUCT_CHAT);" in entry_source
    assert "resetConversationView(preserveProject);" in entry_source

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
    # Completed/streaming answers keep the brand label only; the repetitive
    # "AI 응답" line is not rendered. The locale key stays for compatibility.
    assert 'textContent = uiT("ai-response")' not in stream_source
    assert '"ai-response": "AI 응답"' in LOCALE_PATH.read_text(encoding="utf-8")


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
    # #4462 CTO follow-up: copy/download stay completed-only while the
    # per-answer save entry stays hidden with the removed saved-answers list.
    assert 'button.hidden = !outputsReady || !eligible' not in outputs
    assert 'save.hidden = true' in outputs
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
    assert 'textContent = uiT("generation-cancelled")' in source
    assert 'uiT("regenerate")' in source
    locale = LOCALE_PATH.read_text(encoding="utf-8")
    assert '"generation-cancelled": "생성 취소됨"' in locale
    assert '"regenerate": "다시 생성"' in locale
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


def test_terminal_error_records_render_before_first_token_without_pc_recovery() -> None:
    """Run the shipped reader, stream consumer and error renderer together."""
    script = _transport_runtime() + r'''
const fs = require("fs");
const vm = require("vm");
const assert = require("node:assert/strict");
const app = fs.readFileSync(process.argv[1], "utf8");
const streamStart = app.indexOf("  async function requestStreamingAnswer(");
const streamEnd = app.indexOf("\n  function cancelActiveStream(", streamStart);
const renderStart = app.indexOf("  function renderStreamError(");
const renderEnd = app.indexOf("\n  function renderCancelled(", renderStart);
(async () => {
  for (const wire of ["sse", "message", "ndjson", "ndjson-eof"]) {
    for (const message of ["드라이브 입력을 확인해 주세요. <script>unsafe()</script>", ""]) {
      const record = JSON.stringify({ok:false,error:{code:"input_schema_rejected",message}});
      const bytes = wire.startsWith("ndjson") ? record + (wire.endsWith("eof") ? "" : "\n")
        : `${wire === "sse" ? "event: error\n" : ""}data: ${record}\n\n`;
      let reads = 0, cancelled = false, released = false, rendered, state, label;
      const response = {
        ok:true,
        headers: new Headers({"content-type":wire.startsWith("ndjson") ? "application/x-ndjson" : "text/event-stream"}),
        body: {getReader: () => ({
          async read() {
            reads++;
            if (reads === 1) return {value:new TextEncoder().encode(bytes.slice(0, 9)),done:false};
            if (reads === 2) return {value:new TextEncoder().encode(bytes.slice(9)),done:false};
            if (wire.endsWith("eof")) return {done:true};
            throw Error("reader must stop immediately after the refusal");
          },
          async cancel() {cancelled=true;}, releaseLock() {released=true;},
        })},
      };
      global.fetch = async (url) => {
        if (url === "/api/orchestration/status") return {ok:true,json:async()=>({orchestration_ready:true,authenticated:true})};
        if (url === "/api/orchestration") return response;
        throw Error("terminal refusal must not poll pending-result: " + url);
      };
      const typing = {remove() {this.removed=true;}};
      const content = {querySelector:()=>typing,appendChild(box){rendered=box;}};
      const marker = {};
      const article = {querySelector:(selector)=>selector === ".assistant-content" ? content : marker};
      const lifecycle = {FAILED:"failed",TIMED_OUT:"timed_out"};
      const context = {
        window: {PadiemChatLifecycle:{applyRuntimeLabel:(article,text)=>{label=text;}}},
        chatTransport:PadiemChatTransport,
        PadiemChatLifecycle:{set:(article,value)=>{state=value;}},
        MESSAGE_LIFECYCLE:lifecycle,
        uiT:key=>key,
        failureStatusLabel:()=>"연결 오류",
        buildRetryBox:(message)=>({textContent:message}),
        failureCodeNote:()=>null,
        revealErrorState:()=>{},
        lifecycleForError:()=>lifecycle.FAILED,
        fetch:()=>{throw Error("terminal refusal must not poll pending-result");},
      };
      const consume = vm.runInNewContext(
        `(function(){${app.slice(renderStart,renderEnd)}\n${app.slice(streamStart,streamEnd)}\nreturn requestStreamingAnswer;})()`, context);
      const result = await consume(article,{},[],null,{pcRunId:"chat_pcq_test"},new AbortController().signal,null);
      assert.equal(result,false); // no throw to requestAnswer's recovery catch
      assert.equal(state,"failed");
      assert.equal(typing.removed,true);
      assert.equal(label,"연결 오류");
      assert.equal(rendered.textContent,message || "요청을 처리하지 못했습니다 (input_schema_rejected). 다시 시도해 주세요.");
      assert.equal(released,true);
      if (!wire.endsWith("eof")) assert.equal(cancelled,true);
    }
  }
  global.fetch = async (url) => url.endsWith("/status")
    ? {ok:true,json:async()=>({orchestration_ready:true,authenticated:true})}
    : {ok:true,headers:new Headers({"content-type":"application/json"}),
       json:async()=>({ok:false,error:{code:"input_schema_rejected",message:"입력이 거부되었습니다."}})};
  await assert.rejects(PadiemChatTransport.requestStreaming({},null), error =>
    error.terminalRecord === true && error.code === "input_schema_rejected" && error.message === "입력이 거부되었습니다.");
  assert.equal(PadiemChatTransport.streamErrorMessage({error:{code:"upstream_timeout"}}),
    "응답 시간이 초과되었습니다. 다시 시도해 주세요.");
  console.log("terminal error records displayed; pending recovery not entered");
})().catch(error=>{console.error(error);process.exit(1);});
'''
    assert "pending recovery not entered" in _run_node(script, str(APP_PATH))
