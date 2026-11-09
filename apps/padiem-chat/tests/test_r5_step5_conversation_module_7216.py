"""#7216 R5 step 5a — 대화 모듈 계약 (목록·표시·첨부·리셋 19함수).

app.js의 대화 24개 함수가 chat-conversation-module.js로 이동했고, app.js는 같은
이름의 한 줄 전달 함수를 유지한다. 이 시험은 (1) 실제 모듈 본문을 Node vm에서
실행해 동작이 그대로인지, (2) deps getter가 첫 호출 전에 바뀐 클로저 값을
읽는지, (3) setter가 다시 대입하는 변수를 클로저에 쓰는지, (4) app.js가 전달
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
MODULE = (STATIC / "chat-conversation-module.js").read_text(encoding="utf-8")
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
STRICT = (Path(__file__).resolve().parent / "_r5_strict_deps.js").read_text(encoding="utf-8")

NAMES = (
    "attachmentCopy", "showComposerInlineHint", "updateComposer", "showConversation",
    "addUserMessage", "renderAnswer", "renderStreamError", "clearAttachment",
    "attachmentCountLimit", "attachmentTrayNote", "removeAttachmentItem",
    "renderAttachmentChips", "addAttachmentFiles", "attachmentPayload",
    "safeLocalUiMessage", "resetConversationView", "resetConversation",
    "approvalDecisionErrorMessage", "approvedMemoryErrorMessage",
)

MOVED_MARKERS = (
    "deps.conversationEpoch += 1;",
    'deps.activeRequestCancelReason = "conversation_reset";',
    "deps.selectedAttachments = [];",
    "deps.composerInlineHintTimer = window.setTimeout(",
    'window.PadiemChatConversationModule = {',
)


def test_index_loads_the_conversation_module_before_app() -> None:
    assert INDEX.index("./chat-conversation-module.js") < INDEX.index("./app.js")
    assert INDEX.count("./chat-conversation-module.js") == 1


def test_app_keeps_one_line_forwarders_for_every_moved_function() -> None:
    for name in NAMES:
        line = f"function {name}(...a) {{ return conversationModule().{name}(...a); }}"
        assert line in APP, name
        assert APP.count(f"function {name}(") == 1, name
    assert "function conversationModule() {" in APP
    assert "window.PadiemChatConversationModule.create({" in APP


def test_moved_bodies_live_only_in_the_module() -> None:
    for marker in MOVED_MARKERS:
        assert marker in MODULE, marker
    # The definition itself lives only in the module (app.js keeps the forwarder).
    for name in NAMES:
        assert MODULE.count(f"function {name}(") == 1, name


def test_module_exposes_one_factory_and_touches_no_dom_at_load() -> None:
    assert "window.PadiemChatConversationModule = {" in MODULE
    assert "create(deps) {" in MODULE
    assert "document.getElementById" in MODULE
    for name in NAMES:
        assert f"function {name}(" in MODULE, name


def test_deps_count_matches_the_mover_analysis() -> None:
    start = APP.index("window.PadiemChatConversationModule.create({")
    block = APP[start:APP.index("});", start)]
    gets = set(re.findall(r"get (\w+)\(\)", block))
    sets = set(re.findall(r"set (\w+)\(value\)", block))
    assert len(gets) == 68
    # The streaming/bookkeeping reassignments keep their setters.
    assert {"conversationEpoch", "inFlight", "activeRequestController",
            "activeRequestCancelReason", "activeRequestArticle", "activeClawRunId",
            "selectedAttachments", "attachmentKeyCounter", "lastCompletedAnswerRequest"} <= sets


_HARNESS = r"""
const fs = require("fs");
const vm = require("vm");

function makeElement(id) {
  const attrs = {};
  return {
    id, hidden: false, disabled: false, textContent: "", value: "", dataset: {},
    attrs, listeners: {}, shown: 0, closed: 0, focused: 0, childElementCount: 0,
    style: {}, scrollHeight: 40,
    children: [],
    showModal() { this.shown += 1; this.open = true; },
    close() { this.closed += 1; this.open = false; },
    setAttribute(k, v) { attrs[k] = String(v); },
    getAttribute(k) { return attrs[k] === undefined ? null : attrs[k]; },
    removeAttribute(k) { delete attrs[k]; },
    focus() { this.focused += 1; }, select() {},
    addEventListener(name, fn) { (this.listeners[name] ||= []).push(fn); },
    click() { (this.listeners.click || []).forEach((fn) => fn()); },
    replaceChildren(...kids) { this.children = kids; },
    appendChild(x) { this.children.push(x); return x; },
    querySelector() { return null; }, querySelectorAll() { return []; },
    closest() { return null; }, contains() { return true; },
  };
}

const live = {
  conversationProduct: "chat",
  PRODUCT_CHAT: "chat",
  PRODUCT_CLAW: "claw",
  conversationEpoch: 41,
  inFlight: false,
  activeRequestController: null,
  activeRequestCancelReason: null,
  activeRequestArticle: null,
  activeClawRunId: null,
  activeProject: "p1",
  activeProjectFileCount: 2,
  attachmentKeyCounter: 7,
  clawArtifactShownFor: "conv-1",
  composerInlineHintTimer: null,
  lastCompletedAnswerRequest: { stale: true },
  selectedAttachments: [{ name: "a.txt", previewUrl: "blob:1" }, { name: "b.txt", invalid: true }],
  composerInlineHint: makeElement("composerInlineHint"),
  input: makeElement("input"),
  sendButton: makeElement("sendButton"),
  attachmentButton: makeElement("attachmentButton"),
  attachmentChipList: makeElement("attachmentChipList"),
  attachmentFileInput: makeElement("attachmentFileInput"),
  attachmentTray: makeElement("attachmentTray"),
  editProjectButton: makeElement("editProjectButton"),
  exitProjectButton: makeElement("exitProjectButton"),
  cancelStreamButton: makeElement("cancelStreamButton"),
  messageList: makeElement("messageList"),
  emptyState: makeElement("emptyState"),
  shell: { dataset: { state: "home" } },
  authState: { authenticated: true },
  uiT: (key) => key,
  clawT: (key) => key,
  setNote: (m, k) => { live.note = [m, k]; },
  idleNote: () => "idle-note",
  setNavActive: () => { live.navActive = true; },
  closeSidebar: () => { live.sidebarClosed = true; },
  renderProjectState: () => { live.projectState = true; },
  clearClawRecovery: () => { live.clearedRecovery = true; },
  clearClawWait: () => { live.clearedWait = true; },
  switchConversationProduct: (p) => { live.switchTo = p; live.conversationProduct = p; },
  conversationState: { setProduct(p) { live.stateProduct = p; }, reset() { live.stateReset = true; },
                       commitAssistant() {}, setConversationId() {} },
  conversationArtifactContext: { clear() { live.artifactsCleared = true; } },
  accountInitial: () => "K",
  attachmentCapabilities: { copy: (lang) => ({ lang, unsupportedFormat: "unsupported-format" }) },
  fetchCalls: [],
  chatTransport: {
    requestCompleted: async () => { live.completedCalls = (live.completedCalls || 0) + 1; return { answer: "ok" }; },
    requestStreaming: async () => ({ headers: { get: () => "text/event-stream" }, body: {} }),
    readSseEvents: async () => {},
  },
  MESSAGE_LIFECYCLE: { FAILED: "failed", COMPLETED: "completed" },
};
const deps = {};
for (const key of Object.keys(live)) {
  Object.defineProperty(deps, key, {
    get() { return live[key]; },
    set(value) { live[key] = value; },
  });
}

const ctx = {
  document: { documentElement: { lang: "ko" }, createElement: (t) => makeElement(t) },
  console,
  window: {
    clearTimeout: () => {},
    setTimeout: (fn) => { live.timerFn = fn; return 99; },
    PadiemAttachmentCapabilities: undefined,
    PadiemChatLifecycle: undefined,
  },
  fetch: async (...a) => { live.fetchCalls.push(a); return { ok: true, status: 200, json: async () => ({}) }; },
  URL,
  AbortController,
  Map, Set, Array, JSON, Promise, Date, Error, TypeError, Number, String, Boolean, Object,
};
ctx.window.window = ctx.window;
vm.createContext(ctx);
const source = fs.readFileSync(process.argv[2], "utf8");
vm.runInContext(source, ctx, { filename: "chat-conversation-module.js" });
const INTERNAL = ["attachmentCopy", "showComposerInlineHint", "updateComposer", "showConversation",
  "addUserMessage", "renderAnswer", "renderStreamError", "clearAttachment",
  "attachmentCountLimit", "attachmentTrayNote", "removeAttachmentItem",
  "renderAttachmentChips", "addAttachmentFiles", "attachmentPayload",
  "safeLocalUiMessage", "resetConversationView", "resetConversation",
  "approvalDecisionErrorMessage", "approvedMemoryErrorMessage"];
let api;
for (const name of INTERNAL) {
  Object.defineProperty(deps, name, { get() { return api[name]; } });
}
api = ctx.window.PadiemChatConversationModule.create(r5StrictDeps(deps, "step5.deps"));
const results = {};

// 1. attachmentCopy reads the copy for the live document language.
results.copy = api.attachmentCopy();

// 2. attachmentCountLimit defaults to 5, honors a configured cap up to 10.
results.limitDefault = api.attachmentCountLimit();
ctx.window.PadiemAttachmentCapabilities = { maxPerMessage: 99 };
results.limitCapped = api.attachmentCountLimit();
ctx.window.PadiemAttachmentCapabilities = { maxPerMessage: 3 };
results.limitSet = api.attachmentCountLimit();

// 3. safeLocalUiMessage only passes through allowlisted local errors.
const safe = new Error("unsupported-format");
results.safePass = api.safeLocalUiMessage(safe, "fb") === "unsupported-format";
const unsafe = new Error("provider secret");
results.safeBlock = api.safeLocalUiMessage(unsafe, "fb") === "fb";
results.safeFlag = api.safeLocalUiMessage({ uiMessageSafe: true, message: "m" }, "fb") === "m";

// 4. Approval/memory error copy maps status/code to the shipped keys.
results.approval401 = api.approvalDecisionErrorMessage(null, { status: 401 });
results.approval404 = api.approvalDecisionErrorMessage({ error: { code: "approval_not_available" } }, null);
results.approvalOther = api.approvalDecisionErrorMessage(null, null);
results.memoryApproval = api.approvedMemoryErrorMessage({ error: { code: "explicit_approval_required" } }, null);
results.memoryInvalid = api.approvedMemoryErrorMessage({ error: { code: "invalid_proposal" } }, null);

// 5. updateComposer mirrors inFlight onto the composer controls.
api.updateComposer();
results.composerIdle = { input: live.input.disabled, cancelHidden: live.cancelStreamButton.hidden,
  cancelDisabled: live.cancelStreamButton.disabled };
live.inFlight = true;
api.updateComposer();
results.composerBusy = { input: live.input.disabled, attach: live.attachmentButton.disabled,
  cancelHidden: live.cancelStreamButton.hidden, cancelDisabled: live.cancelStreamButton.disabled };
live.inFlight = false;

// 6. Setter contract: the epoch bump and bookkeeping write back into the closure.
live.abortCount = 0;
live.activeRequestController = { abort() { live.abortCount += 1; } };
api.resetConversationView(false);
results.setter = { epoch: live.conversationEpoch, cancelReason: live.activeRequestCancelReason,
  controllerNull: live.activeRequestController === null, aborted: live.abortCount,
  stateReset: live.stateReset, inputCleared: live.input.value === "" };

// 7. Getter contract: an element installed before the call is the one shown.
const late = makeElement("lateHint");
live.composerInlineHint = late;
api.showComposerInlineHint("some-key");
results.getter = { text: late.textContent, hidden: late.hidden };

// 8. clearAttachment writes the emptied selection back through the setter.
live.selectedAttachments = [{ name: "x.txt", previewUrl: "blob:9" }];
api.clearAttachment();
results.cleared = { len: live.selectedAttachments.length, fileValue: live.attachmentFileInput.value };

process.stdout.write(JSON.stringify(results));
"""


def _run_harness() -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not available for the module harness")
    with tempfile.TemporaryDirectory() as tmp:
        harness = Path(tmp) / "harness.js"
        harness.write_text(STRICT + "\n" + _HARNESS, encoding="utf-8", newline="\n")
        completed = subprocess.run(
            [node, str(harness), str(STATIC / "chat-conversation-module.js")],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
        )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


@pytest.fixture(scope="module")
def observed() -> dict:
    return _run_harness()


def test_module_pure_helpers_match_the_closed_over_originals(observed: dict) -> None:
    assert observed["copy"] == {"lang": "ko", "unsupportedFormat": "unsupported-format"}
    assert observed["limitDefault"] == 5
    assert observed["limitCapped"] == 10
    assert observed["limitSet"] == 3
    assert observed["safePass"] is True
    assert observed["safeBlock"] is True
    assert observed["safeFlag"] is True
    assert observed["approval401"] == "claw-error-auth-needed"
    assert observed["approval404"] == "claw-approval-not-available"
    assert observed["approvalOther"] == "claw-approval-error"
    assert observed["memoryApproval"] == "claw-memory-error-approval"
    assert observed["memoryInvalid"] == "claw-memory-error-invalid"


def test_update_composer_mirrors_in_flight(observed: dict) -> None:
    assert observed["composerIdle"] == {"input": False, "cancelHidden": True, "cancelDisabled": True}
    assert observed["composerBusy"] == {"input": True, "attach": True,
                                        "cancelHidden": False, "cancelDisabled": False}


def test_setters_write_the_bookkeeping_back_into_the_closure(observed: dict) -> None:
    assert observed["setter"]["epoch"] == 42
    assert observed["setter"]["cancelReason"] == "conversation_reset"
    assert observed["setter"]["controllerNull"] is True
    assert observed["setter"]["stateReset"] is True
    assert observed["setter"]["inputCleared"] is True
    assert observed["cleared"]["len"] == 0
    assert observed["cleared"]["fileValue"] == ""


def test_getters_read_the_value_changed_before_the_first_call(observed: dict) -> None:
    assert observed["getter"] == {"text": "some-key", "hidden": False}
