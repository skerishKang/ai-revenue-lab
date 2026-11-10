"""#7216 R5 step 5b — 스트리밍 모듈 계약 (전송·스트리밍·취소 5함수).

app.js의 스트리밍 구역 5개 함수(requestCompletedAnswer, applyStreamDone,
requestStreamingAnswer, cancelActiveStream, requestAnswer)가
chat-streaming-module.js로 이동했고, app.js는 같은 이름의 한 줄 전달 함수를
유지한다. 이 시험은 (1) 실제 모듈 본문을 Node vm에서 실행해 5개 함수 동작이
그대로인지, (2) deps getter가 첫 호출 전에 바뀐 클로저 값을 읽는지,
(3) setter 7개가 다시 대입하는 변수를 클로저에 쓰는지, (4) app.js가 전달
함수만 남겼고 index.html이 모듈을 app.js보다 먼저 로드하는지를 확인한다.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "static"
APP = (STATIC / "app.js").read_text(encoding="utf-8")
MODULE = (STATIC / "chat-streaming-module.js").read_text(encoding="utf-8")
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
STRICT = (Path(__file__).resolve().parent / "_r5_strict_deps.js").read_text(encoding="utf-8")

NAMES = (
    "requestCompletedAnswer",
    "applyStreamDone",
    "requestStreamingAnswer",
    "cancelActiveStream",
    "requestAnswer",
)

ASYNC_NAMES = {
    "requestCompletedAnswer",
    "requestStreamingAnswer",
    "requestAnswer",
}

MOVED_MARKERS = (
    "deps.activeRequestCancelReason = \"user_cancel\";",
    "deps.activeRequestController = controller;",
    "deps.activeRequestArticle = article;",
    "deps.inFlight = true;",
    "deps.lastCompletedAnswerRequest = {",
    "window.PadiemChatStreamingModule = {",
)


def test_index_loads_the_streaming_module_before_app() -> None:
    assert INDEX.index("./chat-streaming-module.js") < INDEX.index("./app.js")
    assert INDEX.count("./chat-streaming-module.js") == 1


def test_app_keeps_one_line_forwarders_for_every_moved_function() -> None:
    for name in NAMES:
        prefix = "async function" if name in ASYNC_NAMES else "function"
        line = f"{prefix} {name}(...a) {{ return streamingModule().{name}(...a); }}"
        assert line in APP, name
        assert APP.count(f"function {name}(") == 1, name
    assert "function streamingModule() {" in APP
    assert "window.PadiemChatStreamingModule.create({" in APP


def test_moved_bodies_live_only_in_the_module() -> None:
    for marker in MOVED_MARKERS:
        assert marker in MODULE, marker
        assert marker not in APP, marker
    for name in NAMES:
        assert MODULE.count(f"function {name}(") == 1, name


def test_module_exposes_one_factory_and_stays_under_1000_lines() -> None:
    assert "window.PadiemChatStreamingModule = {" in MODULE
    assert "create(deps) {" in MODULE
    assert len(MODULE.splitlines()) <= 1000
    for name in NAMES:
        assert f"function {name}(" in MODULE, name


def test_deps_count_matches_the_mover_analysis() -> None:
    start = APP.index("window.PadiemChatStreamingModule.create({")
    block = APP[start:APP.index("});", start)]
    gets = set(re.findall(r"get (\w+)\(\)", block))
    sets = set(re.findall(r"set (\w+)\(value\)", block))
    assert len(gets) == 43
    assert sets == {
        "activeClawRunId",
        "activeProject",
        "activeRequestArticle",
        "activeRequestCancelReason",
        "activeRequestController",
        "inFlight",
        "lastCompletedAnswerRequest",
    }


_HARNESS = r"""
const fs = require("fs");
const vm = require("vm");

function makeElement(tag) {
  const attrs = {};
  const node = {
    tagName: String(tag || "div").toUpperCase(),
    className: "",
    textContent: "",
    hidden: false,
    disabled: false,
    open: false,
    isConnected: true,
    dataset: {},
    attrs,
    children: [],
    focused: 0,
    scrolled: 0,
    removed: false,
    setAttribute(k, v) { attrs[k] = String(v); },
    getAttribute(k) { return attrs[k] === undefined ? null : attrs[k]; },
    append(...xs) { this.children.push(...xs); },
    appendChild(x) { this.children.push(x); return x; },
    replaceChildren(...xs) { this.children = xs; },
    insertBefore(x) { this.children.unshift(x); return x; },
    remove() { this.removed = true; },
    focus() { this.focused += 1; },
    scrollIntoView() { this.scrolled += 1; },
    querySelector(sel) {
      if (sel === ".assistant-content") return this._content;
      if (sel === ".assistant-body") return this._body;
      if (sel === "[data-runtime-label]") return this._marker;
      if (sel === ".capability-kit-disclosure") return this._disclosure;
      if (sel === ".typing") return this._typing;
      return null;
    },
  };
  return node;
}

function makeArticle() {
  const article = makeElement("article");
  article._content = makeElement("div");
  article._body = makeElement("div");
  article._marker = makeElement("small");
  article._disclosure = makeElement("details");
  article._typing = makeElement("span");
  article._content._typing = article._typing;
  return article;
}

const live = {
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
  inFlight: false,
  lastCompletedAnswerRequest: null,
  conversationEpoch: 10,
  conversationProduct: "chat",
  authState: { authenticated: true },
  projectsReady: true,
  projectFileStatus: makeElement("div"),
  input: makeElement("textarea"),
  notes: [],
  committed: [],
  convIds: [],
  products: [],
  recentLoads: 0,
  projectLoads: 0,
  projectStateRenders: 0,
  composerUpdates: 0,
  runsInvalidated: 0,
  cancelledRenders: 0,
  errorRenders: 0,
  streamErrorRenders: 0,
  customFailures: 0,
  authDialogs: 0,
  sseFrames: [],
  uiT: (k, vars) => (vars && vars.count !== undefined ? `${k}:${vars.count}` : k),
  setNote: (m, k) => { live.notes.push([m, k]); },
  selectedProductTier: () => "plus",
  addAssistantShell: (label, state) => {
    const a = makeArticle();
    a.dataset.shellLabel = label;
    a.dataset.shellState = state;
    return a;
  },
  renderTyping: () => {},
  renderAnswer: (article, data) => { article.dataset.renderedAnswer = data.answer; },
  renderProjectState: () => { live.projectStateRenders += 1; },
  renderWebGroundingNotice: (el, notice) => { if (notice) el.dataset.notice = notice; },
  renderCancelled: () => { live.cancelledRenders += 1; },
  renderError: (_a, msg) => { live.errorRenders += 1; live.lastErrorMsg = msg; },
  renderStreamError: (_a, msg) => { live.streamErrorRenders += 1; live.lastStreamErrorMsg = msg; },
  revealErrorState: () => {},
  lifecycleForError: () => "failed",
  clawGeneralFailure: (code) => ({ message: `claw:${code}`, hint: "hint" }),
  handleCustomRequestFailure: () => { live.customFailures += 1; },
  openAuthDialog: () => { live.authDialogs += 1; },
  projectById: (id) => (id === "proj-1" ? { id: "proj-1", name: "P1" } : null),
  loadRecentConversations: () => { live.recentLoads += 1; },
  loadProjects: () => { live.projectLoads += 1; },
  invalidateClawRunsRead: () => { live.runsInvalidated += 1; },
  updateComposer: () => { live.composerUpdates += 1; },
  attachmentPayload: (items) => (Array.isArray(items) && items.length ? items : null),
  recoverStoredPcResult: async () => false,
  waitForAcceptedPcRun: async () => {},
  conversationState: {
    setProduct(p) { live.products.push(p); },
    commitAssistant(msgs, ans) { live.committed.push([msgs.length, ans]); },
    setConversationId(id) { live.convIds.push(id); },
  },
  chatTransport: {
    createCalendarTurnId: () => "cal-1",
    createChatPcRunId: () => "chat_pcq_1",
    requestCompleted: async (payload) => ({
      answer: "completed-answer",
      conversation_id: "conv-completed",
      project_id: "proj-1",
      receivedTier: payload.tier,
    }),
    requestStreaming: async () => ({
      headers: { get: () => "text/event-stream" },
    }),
    requestClawGeneral: async () => ({
      headers: { get: () => "text/event-stream" },
    }),
    readSseEvents: async (_resp, onFrame) => {
      for (const f of live.sseFrames) {
        if (await onFrame(f)) break;
      }
    },
    streamErrorMessage: () => "stream-error-msg",
    errorFor: (_d, m) => new Error(m),
  },
};

const deps = {};
for (const key of Object.keys(live)) {
  Object.defineProperty(deps, key, {
    get() { return live[key]; },
    set(value) { live[key] = value; },
  });
}

const fetchCalls = [];
const ctx = {
  document: {
    documentElement: { lang: "ko" },
    createElement: (t) => makeElement(t),
    createTextNode: (v) => ({
      data: String(v || ""),
      appendData(d) { this.data += d; },
    }),
  },
  console,
  PadiemChatLifecycle: {
    set(article, state) { article.dataset.lifecycle = state; },
  },
  window: {
    PadiemChatLifecycle: {
      startTurnClock(article) { article.dataset.clockStarted = "true"; },
      releasePreparingRuntimeLabel(article) { article.dataset.releasedPreparing = "true"; },
      recordTaskEvent(article, evt) {
        article.dataset.events = (article.dataset.events ? article.dataset.events + "," : "") + evt;
      },
      renderTaskStatus(article) { article.dataset.taskStatus = "true"; },
      appendStreamDelta(node, delta) { node.appendData(delta); return true; },
      applyRuntimeLabel() {},
    },
    PadiemTierSelection: { ready: async () => {} },
    PadiemCustomSelection: { get: () => null },
    PadiemPcBrowserSurface: { runIdForProgress: () => "run_pc_123" },
  },
  fetch: async (url, opts) => {
    fetchCalls.push({ url, method: opts && opts.method, body: opts && opts.body });
    return { ok: true, json: async () => ({ ok: true }) };
  },
  AbortController,
  Map, Set, Array, JSON, Promise, Date, Error, TypeError, Number, String, Boolean, Object,
};
ctx.window.window = ctx.window;
vm.createContext(ctx);
const source = fs.readFileSync(process.argv[2], "utf8");
vm.runInContext(source, ctx, { filename: "chat-streaming-module.js" });
const INTERNAL = [
  "requestCompletedAnswer",
  "applyStreamDone",
  "requestStreamingAnswer",
  "cancelActiveStream",
  "requestAnswer",
];
let api;
for (const name of INTERNAL) {
  Object.defineProperty(deps, name, { get() { return api[name]; } });
}
api = ctx.window.PadiemChatStreamingModule.create(r5StrictDeps(deps, "step5b.deps"));

(async () => {
  const results = {};

  // 1. Getter check: mutate selectedProductTier and conversationProduct before first call.
  live.selectedProductTier = () => "max";
  live.conversationProduct = "claw";

  // 2. Direct call: requestCompletedAnswer
  const compArticle = makeArticle();
  const compOk = await api.requestCompletedAnswer(
    compArticle,
    { messages: [{ role: "user", content: "hi" }] },
    [{ role: "user", content: "hi" }],
    [],
    { product: "chat", project: null },
    new AbortController().signal,
  );
  results.completed = {
    ok: compOk,
    rendered: compArticle.dataset.renderedAnswer,
    clock: compArticle.dataset.clockStarted,
    project: live.activeProject && live.activeProject.id,
    convId: live.convIds[live.convIds.length - 1],
    products: live.products.slice(-2),
  };

  // 3. Direct call: applyStreamDone
  const doneArticle = makeArticle();
  api.applyStreamDone(
    doneArticle,
    { conversation_id: "conv-stream", project_files_used: 3, notice: "grounding-note" },
    "streamed-answer",
    [{ role: "user", content: "q" }],
    { product: "chat", project: null },
  );
  results.streamDone = {
    lifecycle: doneArticle.dataset.lifecycle,
    released: doneArticle.dataset.releasedPreparing,
    completedAt: Boolean(doneArticle.dataset.completedAt),
    notice: doneArticle._content.dataset.notice,
    refNote: doneArticle._content.children[0] && doneArticle._content.children[0].textContent,
  };

  // 4. Direct call: requestStreamingAnswer
  live.sseFrames = [
    { event: "meta", data: "{}" },
    { event: "delta", data: JSON.stringify({ delta: "안녕" }) },
    { event: "delta", data: JSON.stringify({ delta: "하세요" }) },
    { event: "done", data: JSON.stringify({ done: true, conversation_id: "conv-sse" }) },
  ];
  const streamArticle = makeArticle();
  const streamOk = await api.requestStreamingAnswer(
    streamArticle,
    { messages: [{ role: "user", content: "q" }] },
    [{ role: "user", content: "q" }],
    "auto",
    { product: "chat", project: null },
    new AbortController().signal,
    { clawGeneral: true },
  );
  results.streaming = {
    ok: streamOk,
    lifecycle: streamArticle.dataset.lifecycle,
    answerStarted: streamArticle.dataset.answerStarted,
    clawRunId: live.activeClawRunId,
    text: streamArticle._content.children[0].children[0].data,
  };

  // 5. Direct call: cancelActiveStream (with activeClawRunId set -> posts /api/pc/cancel)
  let aborted = 0;
  live.inFlight = true;
  live.activeRequestController = { abort() { aborted += 1; } };
  live.activeRequestArticle = makeArticle();
  live.activeClawRunId = "run_cancel_1";
  api.cancelActiveStream();
  await new Promise((r) => setImmediate(r));
  results.cancel = {
    reason: live.activeRequestCancelReason,
    aborted,
    fetchUrl: fetchCalls[0] && fetchCalls[0].url,
    runsInvalidated: live.runsInvalidated,
  };
  live.inFlight = false;
  live.activeRequestController = null;
  live.activeRequestArticle = null;
  live.activeClawRunId = null;

  // 6. Direct call: requestAnswer (exercises full lifecycle + setters + cleanup in finally)
  live.sseFrames = [
    { event: "delta", data: JSON.stringify({ delta: "최종답변" }) },
    { event: "done", data: JSON.stringify({ done: true, conversation_id: "conv-final" }) },
  ];
  const answerOk = await api.requestAnswer(
    [{ role: "user", content: "질문" }],
    "auto",
    null,
    { product: "chat", project: null },
    false,
    false,
  );
  results.answer = {
    ok: answerOk,
    inFlightAfter: live.inFlight,
    controllerAfter: live.activeRequestController,
    articleAfter: live.activeRequestArticle,
    lastCompletedRecorded: Boolean(live.lastCompletedAnswerRequest),
    inputFocused: live.input.focused > 0,
  };

  process.stdout.write(JSON.stringify(results));
})().catch((err) => {
  console.error(err);
  process.exit(1);
});
"""


def _run_harness() -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not available for the module harness")
    with tempfile.TemporaryDirectory() as tmp:
        harness = Path(tmp) / "harness.js"
        harness.write_text(STRICT + "\n" + _HARNESS, encoding="utf-8", newline="\n")
        completed = subprocess.run(
            [node, str(harness), str(STATIC / "chat-streaming-module.js")],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
        )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


@pytest.fixture(scope="module")
def observed() -> dict:
    return _run_harness()


def test_request_completed_answer_and_apply_stream_done(observed: dict) -> None:
    assert observed["completed"] == {
        "ok": True,
        "rendered": "completed-answer",
        "clock": "true",
        "project": "proj-1",
        "convId": "conv-completed",
        "products": ["chat", "claw"],
    }
    assert observed["streamDone"] == {
        "lifecycle": "completed",
        "released": "true",
        "completedAt": True,
        "notice": "grounding-note",
        "refNote": "project-files-used:3",
    }


def test_request_streaming_answer_and_cancel_active_stream(observed: dict) -> None:
    assert observed["streaming"] == {
        "ok": True,
        "lifecycle": "completed",
        "answerStarted": "true",
        "clawRunId": "run_pc_123",
        "text": "안녕하세요",
    }
    assert observed["cancel"] == {
        "reason": "user_cancel",
        "aborted": 1,
        "fetchUrl": "/api/pc/cancel",
        "runsInvalidated": 1,
    }


def test_request_answer_sets_and_cleans_up_closure_state(observed: dict) -> None:
    assert observed["answer"] == {
        "ok": True,
        "inFlightAfter": False,
        "controllerAfter": None,
        "articleAfter": None,
        "lastCompletedRecorded": True,
        "inputFocused": True,
    }
