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


def _conv_source() -> str:
    # #7216 R5 step 5a: the conversation area moved into chat-conversation-module.js.
    return APP_PATH.with_name("chat-conversation-module.js").read_text(encoding="utf-8")


def _stream_source() -> str:
    # #7216 R5 step 5b: the streaming area moved into chat-streaming-module.js.
    return APP_PATH.with_name("chat-streaming-module.js").read_text(encoding="utf-8")


def _next_fn_end(source: str, start: int) -> int:
    ends = [i for i in (source.find("\n  function ", start + 1),
                        source.find("\n  async function ", start + 1)) if i != -1]
    return min(ends) if ends else len(source)


def _transport_source() -> str:
    return TRANSPORT_PATH.read_text(encoding="utf-8")


def _run_node(script: str, *args: str) -> str:
    completed = subprocess.run(
        ["node", "-e", script, *args],
        check=True,
        capture_output=True,
        text=True, encoding="utf-8",
    )
    return completed.stdout.strip()


def _run_node_script(script: str, *args: str) -> str:
    """Run a large script from a temp file.

    Windows refuses a command line over ~32K characters (WinError 206), and
    this contract embeds the whole transport source. A script file keeps the
    same Node harness and assertions while staying under that host limit.
    """
    import os
    import tempfile

    handle = tempfile.NamedTemporaryFile(
        "w", suffix=".cjs", delete=False, encoding="utf-8", newline="\n",
    )
    try:
        handle.write(script)
        handle.close()
        completed = subprocess.run(
            ["node", handle.name, *args],
            check=True,
            capture_output=True,
            text=True, encoding="utf-8",
        )
    finally:
        try:
            os.unlink(handle.name)
        except OSError:
            pass
    return completed.stdout.strip()


def _transport_runtime() -> str:
    return "global.window = globalThis;\n" + _transport_source()


def test_text_only_streams_but_attachment_keeps_completed_json() -> None:
    source = _source()
    stream_source = _stream_source()
    transport = _transport_source()
    html = INDEX_PATH.read_text(encoding="utf-8")

    assert "deps.chatTransport.requestStreaming(payload, signal)" in stream_source
    assert "deps.chatTransport.requestCompleted(payload, signal)" in stream_source
    # #7297: Chat and Claw share the completed JSON path for an attachment.
    assert "if (attachments) {" in stream_source
    # Success recording for one-click regenerate keeps the same dispatch
    # shape: completed JSON for attachments, streaming otherwise.
    assert "await deps.requestCompletedAnswer(" in stream_source
    assert "await deps.requestStreamingAnswer(" in stream_source
    assert 'fetch("/api/chat/stream"' in transport
    assert 'fetch("/api/chat"' in transport
    assert '"Accept": "text/event-stream"' in transport
    assert '"Accept": "application/json"' in transport
    assert 'fetch("/api/chat/stream"' not in source
    assert 'fetch("/api/chat"' not in source
    assert 'fetch("/api/chat/stream"' not in stream_source
    assert 'fetch("/api/chat"' not in stream_source
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
const chunks = JSON.parse(process.argv[2]);
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
    result = json.loads(_run_node_script(script, json.dumps(chunks, ensure_ascii=False)))

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
const chunks = JSON.parse(process.argv[2]);
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
    result = json.loads(_run_node_script(script, json.dumps(chunks, ensure_ascii=False)))

    assert result == {"seen": 1, "cancelled": True, "released": True}


def test_stream_state_commits_only_on_done_and_partial_error_is_preserved() -> None:
    source = _stream_source()
    conv = _conv_source()
    stream_start = source.index("  async function requestStreamingAnswer(")
    stream_end = source.index("  async function requestAnswer(", stream_start)
    stream_source = source[stream_start:stream_end]

    assert 'appendStreamDelta?.(answerTextNode, data.delta)' in stream_source
    assert 'deps.renderStreamError(article, message' in stream_source
    assert 'deps.applyStreamDone(article, data, answer' in stream_source
    assert 'messages = outboundMessages.concat' not in stream_source

    done_start = source.index("  function applyStreamDone(")
    done_end = source.index("  async function requestStreamingAnswer(", done_start)
    done_source = source[done_start:done_end]
    assert "deps.conversationState.commitAssistant(outboundMessages, answer);" in done_source
    assert "deps.conversationState.setConversationId(data.conversation_id);" in done_source
    assert "project_files_used" in done_source

    partial_start = _source().index("  function renderStreamError(")
    partial_end = _source().index("  function formatBytes(", partial_start)
    partial_source = _source()[partial_start:partial_end]
    conv_partial_start = conv.index("  function renderStreamError(")
    conv_partial = conv[conv_partial_start:_next_fn_end(conv, conv_partial_start)]
    assert "content.replaceChildren()" not in partial_source
    assert "content.replaceChildren()" not in conv_partial
    assert "content.appendChild(buildRetryBox" in partial_source
    assert "deps.buildRetryBox(" in conv_partial
    assert "content.appendChild(box);" in conv_partial


def test_new_chat_aborts_active_stream_and_epoch_blocks_stale_mutation() -> None:
    source = _conv_source()  # #7216 R5 step 5a
    reset_start = source.index("  function resetConversationView(")
    reset_end = _next_fn_end(source, reset_start)
    reset_source = source[reset_start:reset_end]

    assert "deps.conversationEpoch += 1;" in reset_source
    assert "deps.activeRequestController.abort();" in reset_source
    assert "deps.activeRequestController = null;" in reset_source

    # Chat/Claw separation: the sidebar Chat entry returns to the Chat conversation while the
    # Claw workspace is open, and otherwise starts a new Chat conversation.
    entry_start = source.index("  function resetConversation(")
    entry_end = _next_fn_end(source, entry_start)
    entry_source = source[entry_start:entry_end]
    assert "deps.switchConversationProduct(deps.PRODUCT_CHAT);" in entry_source
    assert "deps.resetConversationView(preserveProject);" in entry_source

    stream = _stream_source()
    request_start = stream.index("  async function requestAnswer(")
    request_end = _next_fn_end(stream, request_start)
    request_source = stream[request_start:request_end]
    assert "const requestEpoch = deps.conversationEpoch;" in request_source
    assert "const controller = new AbortController();" in request_source
    assert 'error.name === "AbortError"' in request_source
    assert "requestEpoch !== deps.conversationEpoch" in request_source
    assert "if (deps.activeRequestController === controller)" in request_source


def test_streamed_browser_path_never_renders_provider_route_details() -> None:
    source = _stream_source()
    stream_start = source.index("  async function requestStreamingAnswer(")
    stream_end = source.index("  async function requestAnswer(", stream_start)
    stream_source = source[stream_start:stream_end]

    assert "route-details" not in stream_source
    assert "provider" not in stream_source
    # Completed/streaming answers keep the brand label only; the repetitive
    # "AI 응답" line is not rendered. The locale key stays for compatibility.
    assert 'textContent = uiT("ai-response")' not in stream_source
    assert 'textContent = deps.uiT("ai-response")' not in stream_source
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
    stream = _stream_source()
    transport = _transport_source()
    assert 'id="cancelStreamButton"' in INDEX_PATH.read_text(encoding="utf-8")
    assert "cancelActiveStream" in source
    assert "cancelActiveStream" in stream
    assert 'deps.activeRequestCancelReason = "user_cancel"' in stream
    assert "deps.renderCancelled(article" in stream
    assert 'textContent = uiT("generation-cancelled")' in source
    assert 'uiT("regenerate")' in source
    locale = LOCALE_PATH.read_text(encoding="utf-8")
    assert '"generation-cancelled": "생성 취소됨"' in locale
    assert '"regenerate": "다시 생성"' in locale
    assert 'retry.textContent = actionLabel' in source
    assert "deps.requestStreamingAnswer(\n        article" in stream
    assert "deps.chatTransport.requestStreaming(payload, signal)" in stream
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
    assert 'deps.cancelStreamButton.hidden = !deps.inFlight' in _conv_source()
    assert 'min-width: 64px' in css
    assert 'min-height: 42px' in css


def test_terminal_error_records_render_before_first_token_without_pc_recovery() -> None:
    """Run the shipped reader, stream consumer and error renderer together."""
    script = _transport_runtime() + r'''
const fs = require("fs");
const vm = require("vm");
const assert = require("node:assert/strict");
// #7216 R5 step 5a/5b: renderStreamError moved into the conversation module;
// the stream consumer moved into the streaming module.
const conv = fs.readFileSync(process.argv[process.argv.length - 1].replace(/app\.js$/, "chat-conversation-module.js"), "utf8");
const streamMod = fs.readFileSync(process.argv[process.argv.length - 1].replace(/app\.js$/, "chat-streaming-module.js"), "utf8");
const streamStart = streamMod.indexOf("  async function requestStreamingAnswer(");
const streamEnd = streamMod.indexOf("\n  function cancelActiveStream(", streamStart);
const renderStart = conv.indexOf("  function renderStreamError(");
const renderEnd = conv.indexOf("\n  function clearAttachment(", renderStart);
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
        `(function(){${conv.slice(renderStart,renderEnd).replace(/deps\./g,"")}\n${streamMod.slice(streamStart,streamEnd).replace(/deps\./g,"")}\nreturn requestStreamingAnswer;})()`, context);
      const result = await consume(article,{},[],null,{pcRunId:"chat_pcq_test"},new AbortController().signal,null);
      assert.equal(result,false); // no throw to requestAnswer's recovery catch
      assert.equal(state,"failed");
      assert.equal(typing.removed,true);
      assert.equal(label,"연결 오류");
      assert.equal(rendered.textContent,"요청 내용을 확인할 수 없습니다. 내용을 확인한 뒤 다시 시도해 주세요.");
      assert.equal(released,true);
      if (!wire.endsWith("eof")) assert.equal(cancelled,true);
    }
  }
  global.fetch = async (url) => url.endsWith("/status")
    ? {ok:true,json:async()=>({orchestration_ready:true,authenticated:true})}
    : {ok:true,headers:new Headers({"content-type":"application/json"}),
       json:async()=>({ok:false,error:{code:"input_schema_rejected",message:"입력이 거부되었습니다."}})};
  await assert.rejects(PadiemChatTransport.requestStreaming({},null), error =>
    error.terminalRecord === true && error.code === "input_schema_rejected" && error.message === "요청 내용을 확인할 수 없습니다. 내용을 확인한 뒤 다시 시도해 주세요.");
  assert.equal(PadiemChatTransport.streamErrorMessage({error:{code:"upstream_timeout"}}),
    "응답 시간이 초과되었습니다. 다시 시도해 주세요.");
  console.log("terminal error records displayed; pending recovery not entered");
})().catch(error=>{console.error(error);process.exit(1);});
'''
    assert "pending recovery not entered" in _run_node_script(script, str(APP_PATH))


def test_plain_korean_error_display_and_reference_code() -> None:
    completed = subprocess.run(
        ["node", str(ROOT / "tests" / "test_plain_korean_error_display.cjs")],
        check=True,
        capture_output=True,
        text=True, encoding="utf-8",
    )
    assert "three error cases" in completed.stdout
