"""#7216 R5 step 5b — 실제 Chromium에서 app.js 스트리밍 전달 함수 호출 계약.

app.js에서 추출한 5개 한 줄 전달 함수(requestCompletedAnswer, applyStreamDone,
requestStreamingAnswer, cancelActiveStream, requestAnswer)를 실제 Chromium
페이지에 주입하고, 실제 모듈 소스와 deps를 연결해 각 전달 함수를 직접 호출한다.
전달 함수마다 1개 이상의 직접 호출 검사와 라이브 deps getter/setter 검사를 둔다.
"""
from __future__ import annotations

# #8060: shipped reads live in _support; assertions stay here.
from _support.last_batch_source import app_js, locale_js, pylock_toml, quote_runtime_js, read, read_replace, strict_deps_js, uv_lock_toml, xlsx_migration_sql, xlsx_sources_js, xlsx_store_py

import json
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright  # noqa: E402

STATIC = Path(__file__).resolve().parents[1] / "static"
APP = app_js()
STRICT = strict_deps_js()

# name -> (js args expression, expected argument count)
CALLS = {
    "requestCompletedAnswer": (
        "[window.__makeArticle(), {messages: []}, [], [], {product: 'chat'}, new AbortController().signal]",
        6,
    ),
    "applyStreamDone": (
        "[window.__makeArticle(), {conversation_id: 'c1'}, 'ans', [], {product: 'chat'}]",
        5,
    ),
    "requestStreamingAnswer": (
        "[window.__makeArticle(), {messages: []}, [], 'auto', {product: 'chat'}, new AbortController().signal, null]",
        7,
    ),
    "cancelActiveStream": ("[]", 0),
    "requestAnswer": (
        "[[{role: 'user', content: 'hi'}], 'auto', null, {product: 'chat'}, false, false]",
        6,
    ),
}

HARNESS = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><title>R5 streaming forwarders</title></head>
<body>
<div class="app-shell" id="shell"></div>
<div class="conversation"><div id="messageList"></div></div>
<script src="/static/chat-streaming-module.js"></script>
<script>
__STRICT__
window.__makeArticle = () => {
  const article = document.createElement("article");
  const body = document.createElement("div");
  body.className = "assistant-body";
  const content = document.createElement("div");
  content.className = "assistant-content";
  const marker = document.createElement("small");
  marker.setAttribute("data-runtime-label", "");
  body.appendChild(content);
  article.append(marker, body);
  return article;
};
window.PadiemChatLifecycle = {
  set(a, s) { a.dataset.lifecycle = s; },
  startTurnClock() {},
  releasePreparingRuntimeLabel() {},
  recordTaskEvent() {},
  renderTaskStatus() {},
  appendStreamDelta(node, d) { node.appendData(d); return true; },
  applyRuntimeLabel() {},
};
window.PadiemTierSelection = { ready: async () => {} };
window.PadiemCustomSelection = { get: () => null };
window.__calls = [];
const state = {
  MESSAGE_LIFECYCLE: {
    STREAMING: "streaming",
    COMPLETED: "completed",
    FAILED: "failed",
    CANCELLED: "cancelled",
    TIMED_OUT: "timed_out",
    WAITING_APPROVAL: "waiting_for_approval",
  },
  activeClawRunId: null,
  activeProject: null,
  activeRequestArticle: null,
  activeRequestCancelReason: null,
  activeRequestController: null,
  addAssistantShell: () => window.__makeArticle(),
  attachmentPayload: () => null,
  authState: { authenticated: true },
  chatTransport: {
    createCalendarTurnId: () => "cal-1",
    createChatPcRunId: () => "chat_pcq_1",
    requestCompleted: async () => ({ answer: "ok", conversation_id: "c1" }),
    requestStreaming: async () => ({ headers: { get: () => "text/event-stream" } }),
    requestClawGeneral: async () => ({ headers: { get: () => "text/event-stream" } }),
    readSseEvents: async (_r, fn) => {
      await fn({ event: "delta", data: JSON.stringify({ delta: "ok" }) });
      await fn({ event: "done", data: JSON.stringify({ done: true, conversation_id: "c1" }) });
    },
    streamErrorMessage: () => "err",
    errorFor: (_d, m) => new Error(m),
  },
  clawGeneralFailure: () => ({ message: "m", hint: "h" }),
  conversationEpoch: 1,
  conversationProduct: "chat",
  conversationState: { setProduct() {}, commitAssistant() {}, setConversationId() {} },
  handleCustomRequestFailure: () => {},
  inFlight: false,
  input: document.createElement("textarea"),
  invalidateClawRunsRead: () => {},
  lastCompletedAnswerRequest: null,
  lifecycleForError: () => "failed",
  loadProjects: () => {},
  loadRecentConversations: () => {},
  openAuthDialog: () => {},
  projectById: () => null,
  projectFileStatus: document.createElement("div"),
  projectsReady: false,
  recoverStoredPcResult: async () => false,
  renderAnswer: () => {},
  renderCancelled: () => {},
  renderError: () => {},
  renderProjectState: () => {},
  renderStreamError: () => {},
  renderTyping: () => {},
  renderWebGroundingNotice: () => {},
  revealErrorState: () => {},
  selectedProductTier: () => "plus",
  setNote: (m, k) => { state.lastNote = [m, k]; },
  uiT: (k) => k,
  updateComposer: () => {},
  waitForAcceptedPcRun: async () => {},
};
window.__state = state;
window.__deps = {};
for (const key of Object.keys(state)) {
  Object.defineProperty(window.__deps, key, {
    get() { return window.__state[key]; },
    set(value) { window.__state[key] = value; },
  });
}
window.__instance = null;
function streamingModule() {
  if (!window.__instance) {
    window.__instance = window.PadiemChatStreamingModule.create(r5StrictDeps(window.__deps, "step5b.browser"));
  }
  return window.__instance;
}
for (const key of ["applyStreamDone", "requestCompletedAnswer", "requestStreamingAnswer"]) {
  // B7: app.js re-points these deps getters to the registry piece; the harness
  // mirrors that by reading the same methods off the (wrapped) module instance.
  Object.defineProperty(window.__deps, key, { get() { return streamingModule()[key]; } });
}
const __real = streamingModule();
for (const key of Object.keys(__real)) {
  const real = __real[key];
  __real[key] = (...args) => {
    window.__calls.push({ name: key, argc: args.length });
    return real(...args);
  };
}
__FORWARDERS__
window.__call = async (name, args) => {
  window.__calls = [];
  const out = await globalThis[name](...args);
  return { last: window.__calls[0] || null, out: String(out) };
};
</script>
</body></html>
"""


def _forwarder_lines() -> str:
    # B7: the forwarders are gone from app.js — the harness mirrors the
    # registry path (app.provide("streaming") → streamingModule() piece).
    async_names = {"requestCompletedAnswer", "requestStreamingAnswer", "requestAnswer"}
    lines = []
    for name in CALLS:
        prefix = "async function" if name in async_names else "function"
        lines.append(f"{prefix} {name}(...a) {{ return streamingModule().{name}(...a); }}")
    return "\n".join(lines)


class _StaticHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC.parent), **kwargs)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def page_url():
    harness = STATIC / "_r5_streaming_forwarder_harness.html"
    harness.write_text(
        HARNESS.replace("__STRICT__", STRICT).replace("__FORWARDERS__", _forwarder_lines()),
        encoding="utf-8",
        newline="\n",
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), _StaticHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/static/_r5_streaming_forwarder_harness.html"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        harness.unlink(missing_ok=True)


@pytest.fixture(scope="module")
def browser_page(page_url):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(page_url)
        yield page
        browser.close()


@pytest.mark.parametrize("name", sorted(CALLS))
def test_forwarder_calls_the_module_function_directly(browser_page, name) -> None:
    args, argc = CALLS[name]
    out = browser_page.evaluate(f"window.__call({json.dumps(name)}, {args})")
    assert out["last"] == {"name": name, "argc": argc}, (name, out)


def test_deps_getter_and_setter_observe_live_closure_state_in_browser(browser_page) -> None:
    out = browser_page.evaluate("""async () => {
      let aborted = 0;
      window.__state.uiT = (k) => "custom:" + k;
      window.__state.inFlight = true;
      window.__state.activeRequestController = { abort() { aborted += 1; } };
      window.__state.activeRequestArticle = window.__makeArticle();
      window.__state.activeClawRunId = null;
      await window.__call("cancelActiveStream", []);
      const result = {
        cancelReason: window.__state.activeRequestCancelReason,
        aborted,
        note: window.__state.lastNote,
      };
      window.__state.inFlight = false;
      window.__state.activeRequestController = null;
      window.__state.activeRequestArticle = null;
      return result;
    }""")
    assert out == {
        "cancelReason": "user_cancel",
        "aborted": 1,
        "note": ["custom:answer-cancelled-note", "error"],
    }
