"""#7297 PR 3 — Claw 화면 Chat direct 경로 전환·공통 기억·실행 기록 필터·showConversation 회귀 시험.

검증 항목:
1. Claw 화면 일반 전송이 Chat direct 경로(`requestStreaming` / `requestCompleted`)를
   타고 `payload.product = "claw"` 이름표만 다르게 전달한다.
2. (a) Custom(BYOK) 선택이 Claw 화면에서도 거부(`custom-chat-only`) 없이 전송된다.
3. (b) 이미지 첨부가 Claw 화면에서도 거부(`claw-image-attachment-unsupported`) 없이
   선택·전송된다.
4. (c) 기억 검토 화면(`#clawMemoryReview`, `#clawApprovedDisclosure`, `#clawApprovedMemory`)이
   Chat과 Claw 활성 대화 모두에서 동작한다.
5. 실행 기록(`#clawRunHistory`) 기본 표시는 도구·PC를 쓴 턴만 보여주고, 일반 대화 턴
   (`action === "general"`, 첨부 산출물 없음)은 `#clawRunHistoryFilter` 토글 시 표시된다.
6. `chat-conversation-module.js`의 `showConversation`이 배열 리터럴로 4개 패널
   (`clawRunHistoryDisclosure`, `clawRunHistory`, `clawApprovedDisclosure`,
   `clawApprovedMemory`)을 순회해 전환 시 `hidden = true` 및 `<details>.open = false`로
   초기화한다(기존 괄호 쉼표 연산자 글자 순회 버그 회귀 방지).
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

# R5 0단계(R-01): 함수 경계는 app.js든 분리 모듈이든 같은 도우미로 찾는다.
from _r5_function_source import combined_source

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
APP_JS = (STATIC / "app.js").read_text(encoding="utf-8")
CONV_JS = (STATIC / "chat-conversation-module.js").read_text(encoding="utf-8")
STREAM_JS = (STATIC / "chat-streaming-module.js").read_text(encoding="utf-8")
HIST_JS = (STATIC / "chat-history-module.js").read_text(encoding="utf-8")
INDEX_HTML = (STATIC / "index.html").read_text(encoding="utf-8")
FRAME_CSS = (STATIC / "shared-six-panel-frame.css").read_text(encoding="utf-8")


def test_show_conversation_iterates_panel_id_array_not_comma_expression() -> None:
    start = CONV_JS.index("function showConversation(")
    end = CONV_JS.index("function addUserMessage(", start)
    body = CONV_JS[start:end]

    # Must use an array literal [...], never the parenthesized comma operator (...)
    assert 'for (const id of ["clawRunHistoryDisclosure", "clawRunHistory",' in body
    assert 'for (const id of ("clawRunHistoryDisclosure"' not in body


def test_claw_custom_and_image_refusals_are_removed_from_ui_modules() -> None:
    # (a) Custom Claw refusal removed from submitPrompt and requestAnswer
    shipped = combined_source()
    submit_start = shipped.index("async function submitPrompt(")
    submit_end = shipped.index("\n  function setSidebarCollapsed(", submit_start)
    submit_body = shipped[submit_start:submit_end]
    assert "custom-chat-only" not in submit_body
    assert "const customSelection = window.PadiemCustomSelection?.get?.();" in STREAM_JS
    assert "!clawGeneralRequest && window.PadiemCustomSelection" not in STREAM_JS

    # (b) Image attachment Claw refusal removed from addAttachmentFiles
    add_start = CONV_JS.index("async function addAttachmentFiles(")
    add_end = CONV_JS.index("\n  function attachmentPayload(", add_start)
    add_body = CONV_JS[add_start:add_end]
    assert "claw-image-attachment-unsupported" not in add_body


def test_run_history_filter_control_and_shared_chat_claw_css_exist() -> None:
    assert 'id="clawRunHistoryFilter"' in INDEX_HTML
    assert 'data-locale-key="claw-runs-filter-tools"' in INDEX_HTML
    assert "window.__padiemClawRunHistoryIncludeGeneral" in HIST_JS
    # #7459: 대표 결정으로 Chat 대화 중 입력창 아래 노출은 제거했다. Claw 일반 화면 규칙만 남는다.
    assert '.app-shell[data-state="chat"] .empty-state[hidden]' not in FRAME_CSS
    assert '.app-shell[data-state="claw"] .claw-workspace[data-view="general"]' in FRAME_CSS


def test_stream_route_projection_tags_action_from_answer_status() -> None:
    # #7297: the default run-history filter hides action="general" runs, so the
    # stream completion must carry the same action tag the JSON route uses —
    # a web-search evidence turn must not be recorded as a general turn and
    # disappear from the default view.
    routes = (ROOT / "app" / "chat_routes.py").read_text(encoding="utf-8")
    stream_tag = 'user_text=latest_user, answer=answer, conversation_id=saved_id, action=("web_search" if done_payload.get("answer_status") == "answered_with_evidence" else "general")'
    assert stream_tag in routes
    json_tag = 'action=(tool_request.tool.id if tool_request else "web_search" if result.get("answer_status") == "answered_with_evidence" else "general")'
    assert json_tag in routes


_NODE_HARNESS = r"""
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const staticDir = process.argv[2];
const convSource = fs.readFileSync(path.join(staticDir, "chat-conversation-module.js"), "utf8");
const histSource = fs.readFileSync(path.join(staticDir, "chat-history-module.js"), "utf8");
const streamSource = fs.readFileSync(path.join(staticDir, "chat-streaming-module.js"), "utf8");

// --- 1. showConversation panel reset regression + image attachment in Claw ---
function makeNode(id, tag = "DIV") {
  const attrs = {};
  return {
    id,
    tagName: tag,
    hidden: false,
    open: true,
    disabled: false,
    textContent: "",
    value: "",
    dataset: {},
    style: {},
    scrollHeight: 40,
    childElementCount: 0,
    children: [],
    listeners: {},
    setAttribute(k, v) { attrs[k] = String(v); },
    getAttribute(k) { return attrs[k] ?? null; },
    removeAttribute(k) { delete attrs[k]; },
    appendChild(c) { this.children.push(c); return c; },
    append(...cs) { cs.forEach((c) => this.appendChild(c)); },
    replaceChildren(...cs) { this.children = cs; },
    addEventListener(k, fn) { (this.listeners[k] ||= []).push(fn); },
    querySelector() { return null; },
    querySelectorAll() { return []; },
    closest() { return null; },
    focus() {},
    scrollIntoView() {},
    remove() {},
    insertBefore(c) { this.children.push(c); return c; },
  };
}

const nodesById = {
  clawRunHistoryDisclosure: makeNode("clawRunHistoryDisclosure", "DETAILS"),
  clawRunHistory: makeNode("clawRunHistory", "SECTION"),
  clawApprovedDisclosure: makeNode("clawApprovedDisclosure", "DETAILS"),
  clawApprovedMemory: makeNode("clawApprovedMemory", "SECTION"),
  clawMemoryReview: makeNode("clawMemoryReview", "SECTION"),
};
const lookedUpIds = [];

const convLive = {
  conversationProduct: "claw",
  PRODUCT_CHAT: "chat",
  PRODUCT_CLAW: "claw",
  ALLOWED_IMAGE_TYPES: new Set(["image/png", "image/jpeg", "image/webp"]),
  inFlight: false,
  attachmentKeyCounter: 0,
  selectedAttachments: [],
  attachmentFileInput: makeNode("attachmentFileInput", "INPUT"),
  attachmentChipList: makeNode("attachmentChipList", "UL"),
  attachmentTray: makeNode("attachmentTray", "DIV"),
  sendButton: makeNode("sendButton", "BUTTON"),
  input: makeNode("input", "TEXTAREA"),
  attachmentButton: makeNode("attachmentButton", "BUTTON"),
  editProjectButton: makeNode("editProjectButton", "BUTTON"),
  exitProjectButton: makeNode("exitProjectButton", "BUTTON"),
  cancelStreamButton: makeNode("cancelStreamButton", "BUTTON"),
  messageList: makeNode("messageList", "DIV"),
  emptyState: makeNode("emptyState", "DIV"),
  shell: { dataset: { state: "claw" } },
  uiT: (k) => k,
  clawT: (k) => k,
  setNote: () => {},
  idleNote: () => "idle",
  formatBytes: (n) => `${n}B`,
  extensionOf: (name) => "." + String(name).split(".").pop(),
  selectImage: async (file) => ({
    type: "image",
    name: file.name,
    mediaType: file.type,
    file,
    byteSize: file.size,
  }),
  switchConversationProduct(next) { convLive.conversationProduct = next; },
  setNavActive() {},
  binaryDocuments: null,
};

const convCtx = {
  document: {
    documentElement: { lang: "ko" },
    getElementById(id) {
      lookedUpIds.push(id);
      return nodesById[id] || null;
    },
    createElement: (t) => makeNode("", String(t).toUpperCase()),
  },
  window: {},
  console,
  URL: { revokeObjectURL() {} },
   Set, Map, Array, Object, String, Number, Boolean, Promise, Error, Date,
};
convCtx.window = convCtx;
vm.createContext(convCtx);
vm.runInContext(convSource, convCtx);
const convApi = convCtx.window.PadiemChatConversationModule.create(convLive);
Object.assign(convLive, convApi);

// Call showConversation({ preserveClaw: false }) -> all 4 panels must be hidden and closed
convApi.showConversation({ preserveClaw: false });
assert.deepEqual(
  lookedUpIds,
  ["clawRunHistoryDisclosure", "clawRunHistory", "clawApprovedDisclosure", "clawApprovedMemory"],
  "showConversation must look up the exact 4 panel IDs, never single characters",
);
for (const id of ["clawRunHistoryDisclosure", "clawRunHistory", "clawApprovedDisclosure", "clawApprovedMemory"]) {
  assert.equal(nodesById[id].hidden, true, `${id} must be hidden after switching to Chat`);
}
assert.equal(nodesById.clawRunHistoryDisclosure.open, false, "clawRunHistoryDisclosure must close on switch");
assert.equal(nodesById.clawApprovedDisclosure.open, false, "clawApprovedDisclosure must close on switch");

// Re-open disclosures in Claw and switch between saved Claw threads -> disclosures close
nodesById.clawRunHistoryDisclosure.open = true;
nodesById.clawApprovedDisclosure.open = true;
convLive.shell.dataset.state = "claw";
convApi.showConversation({ preserveClaw: true, restoreSaved: true });
assert.equal(nodesById.clawRunHistoryDisclosure.open, false, "clawRunHistoryDisclosure closes on saved switch");
assert.equal(nodesById.clawApprovedDisclosure.open, false, "clawApprovedDisclosure closes on saved switch");

// --- 2. Image attachment in Claw + Run history default filter & toggle ---
(async () => {
  convLive.conversationProduct = "claw";
  await convApi.addAttachmentFiles([{ name: "photo.png", type: "image/png", size: 128 }]);
  assert.equal(convLive.selectedAttachments.length, 1);
  assert.equal(Boolean(convLive.selectedAttachments[0].invalid), false, "Claw image must not be marked invalid");
  assert.equal(convLive.selectedAttachments[0].type, "image");

  // Run history filter in chat-history-module.js
  const histLive = {
    clawRunHistory: makeNode("clawRunHistory", "SECTION"),
    clawRunHistoryDisclosure: makeNode("clawRunHistoryDisclosure", "DETAILS"),
    clawRunHistoryExpand: makeNode("clawRunHistoryExpand", "BUTTON"),
    clawRunHistoryError: makeNode("clawRunHistoryError", "P"),
    clawRunHistoryLoading: makeNode("clawRunHistoryLoading", "DIV"),
    clawRunHistoryList: makeNode("clawRunHistoryList", "DIV"),
    clawRunHistoryEmpty: makeNode("clawRunHistoryEmpty", "P"),
    clawRunHistoryPdfControllers: new Set(),
    clawRunHistoryInFlight: false,
    clawRunHistoryLeftSurface: false,
    clawRunHistoryLimit: 10,
    clawRunHistoryVisibilityEpoch: 0,
    pendingClawRunFocusId: "",
    authViewEpoch: 1,
    authState: { authenticated: true, history_ready: true },
    shell: { dataset: { state: "chat" } },
    uiT: (k) => k,
    clawT: (k) => k,
    failureCodeNote: () => null,
    safeLocalUiMessage: (_e, fb) => fb,
    mappedUiError: (m) => new Error(m),
    renderClawRunCard: (run) => {
      const card = makeNode(run.run_id, "DIV");
      card.dataset.runId = run.run_id;
      return card;
    },
    readClawRuns: async () => ({
      response: { ok: true, status: 200 },
      data: {
        ok: true,
        runs: [
          { run_id: "run_general_chat", channel: "web", action: "general", title: "Chat: 안녕", status: "completed", artifact: null },
          { run_id: "run_general_claw", channel: "web", action: "general", title: "Claw: 반가워", status: "completed", artifact: null },
          { run_id: "run_pc_cmd", channel: "web", action: "pc_command", title: "Claw: 내 PC에서 `whoami` 실행해", status: "completed", artifact: null },
          { run_id: "run_web_search", channel: "web", action: "web_search", title: "Chat: 오늘 날씨", status: "completed", artifact: null },
        ],
      },
    }),
  };

  const histCtx = {
    document: {
      createElement: (t) => makeNode("", String(t).toUpperCase()),
      createTextNode: (t) => ({ textContent: t }),
    },
    window: { __padiemClawRunHistoryIncludeGeneral: false },
    console,
    Set, Map, Array, Object, String, Number, Boolean, Promise, Error,
  };
  histCtx.window.window = histCtx.window;
  vm.createContext(histCtx);
  vm.runInContext(histSource, histCtx);
  const histApi = histCtx.window.PadiemChatHistoryModule.create(histLive);

  // Default filter (tools & PC only): only run_pc_cmd and run_web_search appear
  histApi.syncClawRunHistoryVisibility();
  await new Promise((r) => setImmediate(r));
  assert.equal(histLive.clawRunHistory.hidden, false, "run history is visible in active Chat state");
  assert.deepEqual(
    histLive.clawRunHistoryList.children.map((c) => c.dataset.runId),
    ["run_pc_cmd", "run_web_search"],
    "default filter must show only tool/PC turns",
  );

  // Toggle filter to include general conversation turns -> all 4 runs appear
  histCtx.window.__padiemClawRunHistoryIncludeGeneral = true;
  await histApi.loadClawRunHistory({ force: true });
  assert.deepEqual(
    histLive.clawRunHistoryList.children.map((c) => c.dataset.runId),
    ["run_general_chat", "run_general_claw", "run_pc_cmd", "run_web_search"],
    "all runs appear when general filter is enabled",
  );

  // --- 3. Claw streaming & Custom send via Chat direct path ---
  const streamedPayloads = [];
  const streamLive = {
    MESSAGE_LIFECYCLE: { STREAMING: "streaming", COMPLETED: "completed", FAILED: "failed", CANCELLED: "cancelled", TIMED_OUT: "timed_out" },
    activeClawRunId: null,
    activeProject: null,
    activeRequestArticle: null,
    activeRequestCancelReason: null,
    activeRequestController: null,
    inFlight: false,
    lastCompletedAnswerRequest: null,
    conversationEpoch: 1,
    conversationProduct: "claw",
    authState: { authenticated: true },
    projectsReady: false,
    projectFileStatus: null,
    input: makeNode("input", "TEXTAREA"),
    uiT: (k) => k,
    setNote: () => {},
    selectedProductTier: () => "plus",
    addAssistantShell: () => {
      const a = makeNode("art", "ARTICLE");
      const body = makeNode("body", "DIV");
      const content = makeNode("content", "DIV");
      const marker = makeNode("marker", "SMALL");
      a.querySelector = (s) => (s === ".assistant-content" ? content : s === ".assistant-body" ? body : s === "[data-runtime-label]" ? marker : null);
      return a;
    },
    renderTyping: () => {},
    renderAnswer: () => {},
    renderProjectState: () => {},
    renderWebGroundingNotice: () => {},
    renderCancelled: () => {},
    renderError: () => {},
    renderStreamError: () => {},
    revealErrorState: () => {},
    lifecycleForError: () => "failed",
    clawGeneralFailure: () => ({ message: "err", hint: "hint" }),
    handleCustomRequestFailure: () => {},
    openAuthDialog: () => {},
    projectById: () => null,
    loadRecentConversations: () => {},
    loadProjects: () => {},
    invalidateClawRunsRead: () => {},
    updateComposer: () => {},
    attachmentPayload: () => undefined,
    recoverStoredPcResult: async () => false,
    waitForAcceptedPcRun: async () => {},
    conversationState: { setProduct() {}, commitAssistant() {}, setConversationId() {} },
    chatTransport: {
      createCalendarTurnId: () => "cal-7297",
      createChatPcRunId: () => "chat_pcq_" + "a".repeat(32),
      requestCompleted: async () => ({ answer: "ok" }),
      requestClawGeneral: async () => { throw new Error("requestClawGeneral must not be called"); },
      requestStreaming: async (payload) => {
        streamedPayloads.push(payload);
        return { headers: { get: () => "text/event-stream" } };
      },
      readSseEvents: async (_resp, onFrame) => {
        await onFrame({ event: "delta", data: JSON.stringify({ delta: "직행 스트림 응답" }) });
        await onFrame({ event: "done", data: JSON.stringify({ done: true, conversation_id: "chat_" + "b".repeat(32) }) });
      },
      streamErrorMessage: () => "err",
      errorFor: (_d, m) => new Error(m),
    },
  };

  let customActive = null;
  const streamCtx = {
    document: {
      documentElement: { lang: "ko" },
      createElement: (t) => makeNode("", String(t).toUpperCase()),
      createTextNode: (v) => ({ data: String(v || ""), appendData(d) { this.data += d; } }),
    },
    PadiemChatLifecycle: { set() {} },
    window: {
      PadiemChatLifecycle: {
        startTurnClock() {},
        releasePreparingRuntimeLabel() {},
        recordTaskEvent() {},
        renderTaskStatus() {},
        appendStreamDelta(node, d) { node.appendData(d); return true; },
        applyRuntimeLabel() {},
      },
      PadiemTierSelection: { ready: async () => {} },
      PadiemCustomSelection: { get: () => customActive },
    },
    console,
    AbortController, Map, Set, Array, JSON, Promise, Date, Error, TypeError, Number, String, Boolean, Object,
  };
  streamCtx.window.window = streamCtx.window;
  vm.createContext(streamCtx);
  vm.runInContext(streamSource, streamCtx);
  const streamApi = streamCtx.window.PadiemChatStreamingModule.create(streamLive);
  Object.assign(streamLive, streamApi);

  // (A) Standard Claw send -> calls requestStreaming with product: "claw" and pc_run_id
  const okStandard = await streamApi.requestAnswer(
    [{ role: "user", content: "Claw 일반 질문" }],
    "auto",
    null,
    { product: "claw", conversationId: null, project: null },
    true,
    false,
  );
  assert.equal(okStandard, true);
  assert.equal(streamedPayloads.length, 1);
  assert.equal(streamedPayloads[0].product, "claw");
  assert.equal(streamedPayloads[0].tier, "plus");
  assert.equal(streamedPayloads[0].pc_run_id, "chat_pcq_" + "a".repeat(32));

  // (B) Custom (BYOK) Claw send -> calls requestStreaming with product: "claw" and custom field
  customActive = { provider: "slot-p", model: "slot-p/slot-m", reasoning_effort: "medium" };
  const okCustom = await streamApi.requestAnswer(
    [{ role: "user", content: "Claw Custom 질문" }],
    "auto",
    null,
    { product: "claw", conversationId: null, project: null },
    true,
    false,
  );
  assert.equal(okCustom, true);
  assert.equal(streamedPayloads.length, 2);
  assert.equal(streamedPayloads[1].product, "claw");
  assert.equal("tier" in streamedPayloads[1], false);
  assert.equal(
    JSON.stringify(streamedPayloads[1].custom),
    JSON.stringify({ provider: "slot-p", model: "slot-p/slot-m", reasoning_effort: "medium" }),
  );

  console.log(JSON.stringify({ ok: true }));
})().catch((err) => {
  console.error(err);
  process.exit(1);
});
"""


def test_behavioral_claw_direct_ui_and_panel_regressions() -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required")
    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / "harness.js"
        script.write_text(_NODE_HARNESS, encoding="utf-8", newline="\n")
        completed = subprocess.run(
            [node, str(script), str(STATIC)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
        )
    assert completed.returncode == 0, completed.stdout + "\n" + completed.stderr
    assert json.loads(completed.stdout.strip().splitlines()[-1]) == {"ok": True}
