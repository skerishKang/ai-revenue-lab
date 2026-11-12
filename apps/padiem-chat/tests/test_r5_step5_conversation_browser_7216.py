"""#7216 R5 step 5a — 실제 Chromium에서 app.js 대화 전달 함수 호출 계약.

app.js에서 추출한 19개 한 줄 전달 함수를 실제 Chromium 페이지에 주입하고, 실제
모듈 소스와 deps를 연결해 각 전달 함수를 직접 호출한다. 전달 함수마다 1개 이상의
호출 검사와 라이브 deps getter 검사를 둔다. 문자열 검사가 아니라 실행 검사다.
"""
from __future__ import annotations

import json
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright  # noqa: E402

STATIC = Path(__file__).resolve().parents[1] / "static"
APP = (STATIC / "app.js").read_text(encoding="utf-8")
STRICT = (Path(__file__).resolve().parent / "_r5_strict_deps.js").read_text(encoding="utf-8")

# name -> (js args expression, expected argument count)
CALLS = {
    "attachmentCopy": ("[]", 0),
    "showComposerInlineHint": ('["some-key"]', 1),
    "updateComposer": ("[]", 0),
    "showConversation": ("[{}]", 1),
    "addUserMessage": ('["hi"]', 1),
    "renderAnswer": ("[{querySelector: () => document.createElement('div')}, {answer: 'a'}]", 2),
    "renderStreamError": ("[{querySelector: () => document.createElement('div')}, 'm']", 2),
    "clearAttachment": ("[]", 0),
    "attachmentCountLimit": ("[]", 0),
    "attachmentTrayNote": ("[]", 0),
    "removeAttachmentItem": ("[{}]", 1),
    "renderAttachmentChips": ("[]", 0),
    "addAttachmentFiles": ("[[]]", 1),
    "attachmentPayload": ("[[]]", 1),
    "safeLocalUiMessage": ("[null, 'fb']", 2),
    "resetConversationView": ("[true]", 1),
    "resetConversation": ("[true]", 1),
    "approvalDecisionErrorMessage": ("[null, {status: 401}]", 2),
    "approvedMemoryErrorMessage": ("[null, null]", 2),
}

HARNESS = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><title>R5 conversation forwarders</title></head>
<body>
<div class="app-shell" id="shell"></div>
<div class="conversation"><div id="messageList"></div></div>
<template id="userMessageTemplate"><div class="message-bubble"></div></template>
<script src="/static/chat-conversation-module.js"></script>
<script>
__STRICT__
const el = (id) => {
  const node = document.getElementById(id) || document.createElement("div");
  if (id && !node.id) node.id = id;
  node.value = node.value || "";
  return node;
};
window.PadiemChatLifecycle = { set() {}, recordTaskEvent() {}, applyRuntimeLabel() {} };
window.__calls = [];
const state = {
  conversationProduct: "chat", PRODUCT_CHAT: "chat", PRODUCT_CLAW: "claw",
  conversationEpoch: 0, inFlight: false, activeRequestController: null,
  activeRequestCancelReason: null, activeRequestArticle: null, activeClawRunId: null,
  activeProject: null, activeProjectFileCount: 0, attachmentKeyCounter: 0,
  clawArtifactShownFor: "", composerInlineHintTimer: null,
  lastCompletedAnswerRequest: null, selectedAttachments: [],
  conversationArtifactContext: { clear() {} },
  conversationState: { setProduct() {}, reset() {}, commitAssistant() {}, setConversationId() {} },
  shell: document.getElementById("shell"), messageList: document.getElementById("messageList"),
  emptyState: el("emptyState"), input: el("input"), sendButton: el("sendButton"),
  attachmentButton: el("attachmentButton"), attachmentChipList: el("attachmentChipList"),
  attachmentFileInput: el("attachmentFileInput"), attachmentTray: el("attachmentTray"),
  editProjectButton: el("editProjectButton"), exitProjectButton: el("exitProjectButton"),
  cancelStreamButton: el("cancelStreamButton"), composerInlineHint: el("composerInlineHint"),
  authState: { authenticated: true }, uiT: (k) => k, clawT: (k) => k,
  setNote: () => {}, idleNote: () => "idle", setNavActive: () => {},
  closeSidebar: () => {}, renderProjectState: () => {}, clearClawRecovery: () => {},
  clearClawWait: () => {}, switchConversationProduct: (p) => {},
  accountInitial: () => "K", attachmentCapabilities: { copy: () => ({ unsupportedFormat: "unsupported-format" }) },
  renderWebGroundingNotice: () => {}, failureStatusLabel: () => "x", renderTyping: () => {},
  buildRetryBox: () => document.createElement("div"), failureCodeNote: () => null,
  revealErrorState: () => {}, formatBytes: () => "f", formatClockTime: () => "12:00",
  extensionOf: () => "", form: el("form"), accountName: el("accountName"),
  binaryDocuments: null, ALLOWED_IMAGE_TYPES: [], readDocumentFile: async () => ({}),
  selectImage: async () => ({}), exitProject: () => {},
  MESSAGE_LIFECYCLE: { FAILED: "failed", COMPLETED: "completed" },
  chatTransport: { requestCompleted: async () => ({ answer: "ok" }) },
  fetch: async () => ({ ok: true, status: 200, json: async () => ({}) }),
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
function conversationModule() {
  if (!window.__instance) window.__instance = window.PadiemChatConversationModule.create(window.__deps);
  return window.__instance;
}
for (const key of ["attachmentCopy", "attachmentCountLimit", "attachmentPayload",
  "attachmentTrayNote", "clearAttachment", "renderAttachmentChips", "renderStreamError",
  "resetConversationView", "updateComposer"]) {
  Object.defineProperty(window.__deps, key, { get() { return window.__instance[key]; } });
}
// Spy: every direct forwarder call must reach the same-named module function
// with the same arguments.
const __real = conversationModule();
for (const key of Object.keys(__real)) {
  const real = __real[key];
  __real[key] = (...args) => {
    window.__calls.push({ name: key, argc: args.length });
    return real(...args);
  };
}
__FORWARDERS__
window.__call = async (name, args) => {
  window.PadiemChatLifecycle = { set() {}, recordTaskEvent() {}, applyRuntimeLabel() {} };
window.__calls = [];
  const out = await globalThis[name](...args);
  return { last: window.__calls[0] || null, out: String(out) };
};
</script>
</body></html>
"""


def _forwarder_lines() -> str:
    lines = []
    for name in CALLS:
        marker = f"function {name}(...a) {{"
        line = next(line.strip() for line in APP.splitlines() if marker in line)
        lines.append(line)
    return "\n".join(lines)


class _StaticHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC.parent), **kwargs)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def page_url():
    harness = STATIC / "_r5_conversation_forwarder_harness.html"
    harness.write_text(HARNESS.replace("__STRICT__", STRICT).replace("__FORWARDERS__", _forwarder_lines()),
                       encoding="utf-8", newline="\n")
    server = ThreadingHTTPServer(("127.0.0.1", 0), _StaticHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/static/_r5_conversation_forwarder_harness.html"
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


def test_forwarder_update_composer_reflects_in_flight(browser_page) -> None:
    out = browser_page.evaluate("""async () => {
      window.__state.inFlight = true;
      await window.__call("updateComposer", []);
      const busy = window.__state.input.disabled;
      window.__state.inFlight = false;
      await window.__call("updateComposer", []);
      return { busy, idle: window.__state.input.disabled === false };
    }""")
    assert out == {"busy": True, "idle": True}


def test_forwarder_reset_bumps_the_epoch_through_the_setter(browser_page) -> None:
    out = browser_page.evaluate("""async () => {
      window.__state.conversationEpoch = 20;
      await window.__call("resetConversation", [true]);
      return { epoch: window.__state.conversationEpoch };
    }""")
    assert out == {"epoch": 21}


def test_deps_getter_reads_the_hint_changed_before_the_first_call(browser_page) -> None:
    out = browser_page.evaluate("""async () => {
      const late = document.createElement("div");
      late.id = "lateHint";
      document.body.appendChild(late);
      window.__state.composerInlineHint = late;
      await window.__call("showComposerInlineHint", ["late-key"]);
      return { text: late.textContent, hidden: late.hidden === false };
    }""")
    assert out == {"text": "late-key", "hidden": True}
