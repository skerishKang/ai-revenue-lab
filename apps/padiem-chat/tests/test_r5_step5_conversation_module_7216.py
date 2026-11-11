"""#7216 R5 step 5a — 대화 모듈 계약 (목록·표시·첨부·리셋 19함수).

app.js의 대화 구역 19개 함수가 chat-conversation-module.js로 이동했고, app.js는
같은 이름의 한 줄 전달 함수를 유지한다. #7186 R2: 원문 줄·모양을 고정하던 문자열
검사를 실행 검사로 바꾼다. 이 시험은 (1) 실제 모듈 본문을 Node vm에서 실행해
showConversation·addUserMessage·renderAnswer·renderStreamError·resetConversation
과 첨부 도우미의 반환값·DOM·aria·locale 키를 직접 확인하고, (2) deps getter가
첫 호출 전에 바뀐 클로저 값을 읽는지, (3) setter가 다시 대입하는 변수를 클로저에
쓰는지, (4) app.js의 전달 함수를 실행해 모듈 위임과 인자 전달을 확인하고,
(5) app.js의 실제 deps 블록을 실행해 getter/setter 표면과 라이브 읽기·쓰기를
확인하며, (6) index.html이 모듈을 app.js보다 먼저 로드하는지(HTMLParser)
확인한다.
"""
from __future__ import annotations

from html.parser import HTMLParser
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

# 전달 함수가 받는 인자 수 — 브라우저 실행 시험(test_r5_step5_conversation_browser_7216)
# 의 CALLS 계약과 같은 표면이다.
FORWARDER_ARG_COUNTS = {
    "attachmentCopy": 0,
    "showComposerInlineHint": 1,
    "updateComposer": 0,
    "showConversation": 1,
    "addUserMessage": 1,
    "renderAnswer": 2,
    "renderStreamError": 2,
    "clearAttachment": 0,
    "attachmentCountLimit": 0,
    "attachmentTrayNote": 0,
    "removeAttachmentItem": 1,
    "renderAttachmentChips": 0,
    "addAttachmentFiles": 1,
    "attachmentPayload": 1,
    "safeLocalUiMessage": 2,
    "resetConversationView": 1,
    "resetConversation": 1,
    "approvalDecisionErrorMessage": 2,
    "approvedMemoryErrorMessage": 2,
}

# app.js deps 블록이 노출하는 표면(이동 분석). 실행으로 읽기·쓰기를 검증한다.
DEPS_SETTERS = (
    "activeClawRunId", "activeProject", "activeProjectFileCount",
    "activeRequestArticle", "activeRequestCancelReason", "activeRequestController",
    "attachmentKeyCounter", "clawArtifactShownFor", "composerInlineHintTimer",
    "conversationEpoch", "inFlight", "lastCompletedAnswerRequest",
    "selectedAttachments",
)


class _ScriptSources(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.sources: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "script":
            return
        source = dict(attrs).get("src")
        if source:
            self.sources.append(source)


def _script_sources(html: str) -> list[str]:
    parser = _ScriptSources()
    parser.feed(html)
    return parser.sources


def _function_block(source: str, name: str) -> str:
    """Return a function declaration without pinning its whitespace or order."""
    match = re.search(rf"function\s+{re.escape(name)}\s*\(", source)
    assert match, f"{name} function not found"
    start = match.start()
    index = source.index("{", match.end())
    depth = 0
    quote = ""
    while index < len(source):
        char = source[index]
        if quote:
            if char == "\\":
                index += 2
                continue
            if char == quote:
                quote = ""
        elif char in "\"'`":
            quote = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start:index + 1]
        index += 1
    raise AssertionError(f"unbalanced function body for {name}")


def _run_node(script: str) -> dict:
    node = shutil.which("node")
    assert node, "node runtime is required"
    result = subprocess.run(
        [node, "-e", script], capture_output=True, text=True, encoding="utf-8", timeout=30
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_index_loads_the_conversation_module_before_app() -> None:
    sources = _script_sources(INDEX)
    assert sources.count("./chat-conversation-module.js") == 1
    assert sources.index("./chat-conversation-module.js") < sources.index("./app.js")


def test_moved_bodies_live_only_in_the_module() -> None:
    # 소유 구조 계약(#7186 R2 4단계와 같다): 옮겨진 본문은 모듈에만 살아 있고
    # app.js에는 각 이름의 정의가 전달 함수 하나뿐이다. 원문 모양이 아니라
    # "어디에 살아 있는지"를 검사한다.
    for marker in MOVED_MARKERS:
        assert marker in MODULE, marker
    for name in NAMES:
        assert MODULE.count(f"function {name}(") == 1, name
        assert APP.count(f"function {name}(") == 1, name


def test_app_forwarders_delegate_every_moved_function() -> None:
    # 포워더의 정확한 한 줄 문자열을 찾지 않고, app.js에서 추출한 전달 함수를
    # 실행해 같은 이름의 모듈 메서드로 같은 인자를 그대로 넘기는지 확인한다.
    blocks = "\n".join(_function_block(APP, name) for name in NAMES)
    export = ", ".join(NAMES)
    payload = _run_node(f"""
const blocks = {json.dumps(blocks)};
const names = {json.dumps(list(NAMES))};
const counts = {json.dumps(FORWARDER_ARG_COUNTS)};
const api = new Function("conversationModule", blocks + "\\nreturn {{{export}}};")(() => fake);
const fake = {{}};
for (const name of names) {{
  fake[name] = (...args) => ({{ name, args }});
}}
const rows = names.map((name) => {{
  const args = Array.from({{ length: counts[name] }}, (_, i) => "a" + i);
  const out = api[name](...args);
  return [name, out.name, out.args];
}});
console.log(JSON.stringify(rows));
""")
    expected = [
        [name, name, [f"a{i}" for i in range(FORWARDER_ARG_COUNTS[name])]]
        for name in NAMES
    ]
    assert payload == expected


def test_module_loads_one_factory_and_touches_no_dom_at_load() -> None:
    # 로드 시점에는 DOM에 손대지 않고 팩토리 하나만 노출한다. 문자열 존재 검사 대신
    # DOM 접촉을 세는 프록시 document로 모듈을 실제 로드해 확인한다.
    payload = _run_node(f"""
const fs = require("fs");
const vm = require("vm");
const domTouches = [];
const document = new Proxy({{}}, {{
  get(target, prop) {{ domTouches.push(String(prop)); return () => null; }},
}});
const window = {{}};
const ctx = {{ document, window, console }};
vm.createContext(ctx);
const source = fs.readFileSync({json.dumps(str(STATIC / 'chat-conversation-module.js'))}, "utf8");
vm.runInContext(source, ctx, {{ filename: "chat-conversation-module.js" }});
const moduleGlobal = window.PadiemChatConversationModule;
console.log(JSON.stringify({{
  factoryExposed: Boolean(moduleGlobal) && typeof moduleGlobal.create === "function",
  domTouchesAtLoad: domTouches.length,
}}));
""")
    assert payload == {"factoryExposed": True, "domTouchesAtLoad": 0}


def test_deps_wiring_reads_and_writes_the_live_closure() -> None:
    # deps 개수를 세는 대신 app.js의 실제 deps 블록을 실행한다. getter는 클로저
    # 값을 호출 시점에 읽고, setter는 대입을 클로저 변수에 써야 하며, 표면(이름
    # 집합)은 이동 분석과 정확히 같아야 한다 — deps 이름 집합이 모듈이 만질 수
    # 있는 표면이므로 개수 세기보다 강한 계약이다.
    factory = _function_block(APP, "conversationModule")
    gets = sorted(set(re.findall(r"get (\w+)\(\)", factory)))
    sets = sorted(set(re.findall(r"set (\w+)\(value\)", factory)))
    decls = "\n".join([f"let {name};" for name in gets] + ["let conversationModuleInstance;"])
    reads_setup = "\n".join(f"{name} = {json.dumps(f'r-{name}')};" for name in gets)
    writes_setup = "\n".join(f"captured.{name} = {json.dumps(f'w-{name}')};" for name in sets)
    writes_check = "\n".join(f"writes.{name} = {name} === {json.dumps(f'w-{name}')};" for name in sets)
    payload = _run_node(f"""
const window = {{}};
let captured = null;
window.PadiemChatConversationModule = {{
  create(deps) {{ captured = deps; return {{}}; }},
}};
{decls}
{factory}
conversationModule();
const names = Object.getOwnPropertyNames(captured);
const descriptors = {{}};
for (const name of names) {{
  const d = Object.getOwnPropertyDescriptor(captured, name);
  descriptors[name] = (d.get ? "g" : "") + (d.set ? "s" : "");
}}
// 라이브 읽기: 클로저 값을 sentinel로 바꾸면 getter가 그 값을 반환한다.
{reads_setup}
const reads = {{}};
for (const name of names) {{
  if (descriptors[name].includes("g")) reads[name] = captured[name];
}}
// 라이브 쓰기: deps setter에 대입하면 클로저 변수가 바뀐다.
const writes = {{}};
{writes_setup}
{writes_check}
console.log(JSON.stringify({{ descriptors, reads, writes }}));
""")
    assert payload["descriptors"] == {
        name: ("gs" if name in sets else "g") for name in gets
    }
    assert payload["reads"] == {name: f"r-{name}" for name in gets}
    assert payload["writes"] == {name: True for name in sets}


_HARNESS = r"""
const fs = require("fs");
const vm = require("vm");

function makeElement(id) {
  const attrs = {};
  return {
    id, hidden: false, disabled: false, textContent: "", value: "", dataset: {},
    attrs, listeners: {}, shown: 0, closed: 0, focused: 0, childElementCount: 0,
    style: {}, scrollHeight: 40, className: "",
    children: [],
    showModal() { this.shown += 1; this.open = true; },
    close() { this.closed += 1; this.open = false; },
    setAttribute(k, v) { attrs[k] = String(v); },
    getAttribute(k) { return attrs[k] === undefined ? null : attrs[k]; },
    removeAttribute(k) { delete attrs[k]; },
    focus() { this.focused += 1; }, select() {},
    addEventListener(name, fn) { (this.listeners[name] ||= []).push(fn); },
    click() { (this.listeners.click || []).forEach((fn) => fn()); },
    dispatchEvent(ev) { (this.listeners[ev && ev.type] || []).forEach((fn) => fn(ev)); return true; },
    replaceChildren(...kids) { this.children = kids; this.childElementCount = kids.length; },
    appendChild(x) { this.children.push(x); this.childElementCount = this.children.length; return x; },
    append(...kids) { kids.forEach((k) => this.appendChild(k)); },
    remove() { this.removed = (this.removed || 0) + 1; },
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
  accountName: { textContent: "Kim", hidden: false },
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
  formatBytes: (n) => `fb-${n}`,
  formatClockTime: () => "ct-12:00",
  extensionOf: (name) => name.slice(name.lastIndexOf(".")),
  ALLOWED_IMAGE_TYPES: new Set(["image/png"]),
  selectImage: async () => ({ type: "image", name: "shot.png", mediaType: "image/png", file: {} }),
  readDocumentFile: async () => ({ type: "document", name: "doc.txt", mediaType: "text/plain", text: "d" }),
  binaryDocuments: {
    headerFamily: async () => "zip",
    canRead: () => true,
    read: async () => ({ type: "document", name: "b.hwpx", mediaType: "application/hwp+zip", text: "z" }),
    hwpxMedia: "application/hwp+zip",
  },
  renderWebGroundingNotice: (content, notice, metadata) => { groundingCalls.push([notice, metadata]); },
  buildRetryBox: (...a) => {
    retryBoxCalls.push({ message: a[0], retries: a[2], skill: a[3], context: a[5], clawGeneral: a[6] });
    const box = makeElement("retryBox");
    retryBoxes.push(box);
    return box;
  },
  failureStatusLabel: (lifecycle) => `status-${lifecycle}`,
  failureCodeNote: (code, label) => makeElement("codeNote"),
  revealErrorState: (article) => revealedArticles.push(article),
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

const domRegistry = {};
const sharedCalls = [], clipboardCalls = [], tooltipBound = [];
const lifecycleSets = [], lifecycleLabels = [];
const memoryReviewRenders = [], memoryReviewSyncs = [];
const motionResets = [];
const voiceSyncs = [], composerResizes = [];
const pendingTimers = [];
const groundingCalls = [], retryBoxCalls = [], revealedArticles = [], retryBoxes = [];
let editInputEvents = 0;
const ctx = {
  document: {
    documentElement: { lang: "ko" },
    createElement: (t) => makeElement(t),
    getElementById: (id) => domRegistry[id] || null,
  },
  console,
  navigator: { clipboard: { writeText: async (t) => { clipboardCalls.push(t); } } },
  Event,
  setTimeout: (fn) => { pendingTimers.push(fn); return pendingTimers.length; },
  clearTimeout: () => {},
  PadiemChatLifecycle: {
    set: (article, state) => { lifecycleSets.push([article && article.id, state]); },
    applyRuntimeLabel: (article, label, kind) => { lifecycleLabels.push([label, kind]); },
  },
  window: {
    clearTimeout: () => {},
    setTimeout: (fn) => { pendingTimers.push(fn); return pendingTimers.length; },
    PadiemSharedTooltip: { bind: (frag) => tooltipBound.push(frag) },
    PadiemChatMemoryReview: {
      render: (proposals) => memoryReviewRenders.push(proposals),
      sync: () => memoryReviewSyncs.push(1),
    },
    __padiemConversationMotion: { reset: () => motionResets.push(1), resume: () => {} },
    PadiemVoiceMenu: { syncPrimaryAction: () => voiceSyncs.push(1) },
    PadiemConversationComposer: { resizeTextarea: (input, opts) => { composerResizes.push(opts); } },
    PadiemAnswerCopy: { copyText: async (t) => { sharedCalls.push(t); return true; } },
  },
  fetch: async (...a) => { live.fetchCalls.push(a); return { ok: true, status: 200, json: async () => ({}) }; },
  URL,
  AbortController,
  Map, Set, Array, JSON, Promise, Date, Error, TypeError, Number, String, Boolean, Object,
};
ctx.window.window = ctx.window;
ctx.window.PadiemChatLifecycle = ctx.PadiemChatLifecycle;
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
const tick = () => new Promise((resolve) => setTimeout(resolve, 0));

async function main() {

// 1. attachmentCopy reads the copy for the live document language.
results.copy = api.attachmentCopy();

// 2. attachmentCountLimit defaults to 5, honors a configured cap up to 10.
results.limitDefault = api.attachmentCountLimit();
ctx.window.PadiemAttachmentCapabilities = { maxPerMessage: 99 };
results.limitCapped = api.attachmentCountLimit();
ctx.window.PadiemAttachmentCapabilities = { maxPerMessage: 3 };
results.limitSet = api.attachmentCountLimit();
ctx.window.PadiemAttachmentCapabilities = undefined;

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

// 9. showConversation keeps the owner-accepted inline first turn (landing).
const convPanel = makeElement("conversationPanel");
live.messageList.closest = () => convPanel;
function freshClawPanels() {
  const panels = {};
  for (const id of ["clawRunHistoryDisclosure", "clawRunHistory",
                    "clawApprovedDisclosure", "clawApprovedMemory", "clawMemoryReview"]) {
    const node = makeElement(id);
    node.hidden = false;
    node.open = true;
    node.tagName = id.endsWith("Disclosure") ? "DETAILS" : "DIV";
    node.destroyed = 0;
    node.replaceChildren = (...kids) => { node.destroyed += 1; node.children = kids; };
    domRegistry[id] = node;
    panels[id] = node;
  }
  return panels;
}
freshClawPanels();
live.shell.dataset.state = "home";
live.emptyState.hidden = false;
live.messageList.childElementCount = 0;
live.messageList.hidden = true;
live.navActive = false;
api.showConversation();
results.showLanding = {
  thread: convPanel.dataset.continuousThread,
  emptyHidden: live.emptyState.hidden,
  listHidden: live.messageList.hidden,
  state: live.shell.dataset.state,
  switched: live.switchTo,
  nav: live.navActive,
  panelsHidden: ["clawRunHistoryDisclosure", "clawRunHistory",
                 "clawApprovedDisclosure", "clawApprovedMemory"]
    .map((id) => domRegistry[id].hidden),
  detailsClosed: ["clawRunHistoryDisclosure", "clawApprovedDisclosure"]
    .map((id) => domRegistry[id].open === false),
  runsDestroyed: domRegistry.clawRunHistory.destroyed,
};

// 10. An ongoing thread keeps the landing frame without the hero rule alone.
convPanel.dataset.continuousThread = "true";
live.emptyState.hidden = true;
live.messageList.childElementCount = 3;
api.showConversation();
results.showContinuing = {
  thread: convPanel.dataset.continuousThread,
  emptyHidden: live.emptyState.hidden,
  listHidden: live.messageList.hidden,
};

// 11. A used surface without the thread flag leaves the landing state.
delete convPanel.dataset.continuousThread;
live.emptyState.hidden = false;
api.showConversation();
results.showUsedSurface = {
  thread: convPanel.dataset.continuousThread || null,
  emptyHidden: live.emptyState.hidden,
  listHidden: live.messageList.hidden,
};

// 12. A saved conversation reopens without the hero; Claw stays Claw.
live.shell.dataset.state = "claw";
convPanel.dataset.continuousThread = "true";
live.emptyState.hidden = false;
live.switchTo = null;
freshClawPanels();
api.showConversation({ preserveClaw: true, restoreSaved: true });
results.showRestored = {
  thread: convPanel.dataset.continuousThread || null,
  emptyHidden: live.emptyState.hidden,
  listHidden: live.messageList.hidden,
  state: live.shell.dataset.state,
  switched: live.switchTo,
  detailsClosed: ["clawRunHistoryDisclosure", "clawApprovedDisclosure"]
    .map((id) => domRegistry[id].open === false),
};

// 13. A Claw -> Chat switch hides the stale disclosures without destroying runs.
live.shell.dataset.state = "claw";
live.switchTo = null;
const panels = freshClawPanels();
api.showConversation({ preserveClaw: false });
results.showChatSwitch = {
  state: live.shell.dataset.state,
  switched: live.switchTo,
  product: live.conversationProduct,
  panelsHidden: ["clawRunHistoryDisclosure", "clawRunHistory",
                 "clawApprovedDisclosure", "clawApprovedMemory"]
    .map((id) => panels[id].hidden),
  detailsClosed: ["clawRunHistoryDisclosure", "clawApprovedDisclosure"]
    .map((id) => panels[id].open === false),
  runsDestroyed: panels.clawRunHistory.destroyed,
};

// 14. addUserMessage renders the approved turn: bubble, chip, avatar, stamps,
//     locale keys and aria labels.
function makeFragment() {
  const bubble = makeElement("bubble");
  const chip = makeElement("chip");
  const avatar = makeElement("avatar");
  const clock = makeElement("clock");
  const copyBtn = makeElement("copyBtn");
  const editBtn = makeElement("editBtn");
  const fragment = makeElement("fragment");
  fragment.querySelector = (selector) => ({
    ".message-bubble": bubble,
    ".user-profile-chip": chip,
    ".user-avatar": avatar,
    ".user-action-time": clock,
    ".user-action-copy": copyBtn,
    ".user-action-edit": editBtn,
  }[selector] || null);
  fragment.nodes = { bubble, chip, avatar, clock, copyBtn, editBtn };
  return fragment;
}
domRegistry.userMessageTemplate = { content: { cloneNode: () => makeFragment() } };
live.messageList.children = [];
live.accountName = { textContent: "Kim", hidden: false };
const liveFragment = makeFragment();
domRegistry.userMessageTemplate.content.cloneNode = () => liveFragment;
api.addUserMessage("안녕", [
  { type: "image", name: "photo.png", byteSize: 7 },
  { type: "document", name: "a.pdf", byteSize: 9 },
], {});
results.userMessage = {
  bubble: liveFragment.nodes.bubble.textContent,
  metas: liveFragment.nodes.bubble.children.map((meta) => meta.textContent),
  chip: liveFragment.nodes.chip.textContent,
  avatar: liveFragment.nodes.avatar.textContent,
  stamp: liveFragment.nodes.clock.textContent,
  datetimeIso: !Number.isNaN(Date.parse(liveFragment.nodes.clock.getAttribute("datetime"))),
  stampTooltip: liveFragment.nodes.clock.getAttribute("data-padiem-tooltip"),
  copyAria: liveFragment.nodes.copyBtn.getAttribute("aria-label"),
  copyTooltip: liveFragment.nodes.copyBtn.getAttribute("data-padiem-tooltip"),
  editTooltip: liveFragment.nodes.editBtn.getAttribute("data-padiem-tooltip"),
  boundToTooltip: tooltipBound.includes(liveFragment),
  appended: live.messageList.children.includes(liveFragment),
};

// 15. Copy prefers the shared clipboard path (#4488); the fallback stays only
//     when the shared script is unavailable.
liveFragment.nodes.copyBtn.click();
await tick();
const copied = {
  shared: sharedCalls.slice(),
  clipboard: clipboardCalls.slice(),
  flash: liveFragment.nodes.copyBtn.textContent,
};
while (pendingTimers.length) pendingTimers.shift()();
copied.restored = liveFragment.nodes.copyBtn.textContent;
delete ctx.window.PadiemAnswerCopy;
sharedCalls.length = 0;
clipboardCalls.length = 0;
const fallbackFragment = makeFragment();
domRegistry.userMessageTemplate.content.cloneNode = () => fallbackFragment;
api.addUserMessage("fallback", null, {});
fallbackFragment.nodes.copyBtn.click();
await tick();
copied.fallbackClipboard = clipboardCalls.slice();
copied.fallbackShared = sharedCalls.slice();
ctx.window.PadiemAnswerCopy = { copyText: async (t) => { sharedCalls.push(t); return true; } };
results.userMessageCopy = copied;

// 16. Edit re-fills the composer input through the live deps.
const editFragment = makeFragment();
domRegistry.userMessageTemplate.content.cloneNode = () => editFragment;
api.addUserMessage("edit-me", null, {});
live.input.focused = 0;
live.input.addEventListener("input", () => { editInputEvents += 1; });
editFragment.nodes.editBtn.click();
results.userMessageEdit = {
  input: live.input.value,
  focused: live.input.focused,
  inputEvent: editInputEvents,
};

// 17. A hidden account drops the chip; a restored turn invents no stamp.
const hiddenAccountFragment = makeFragment();
domRegistry.userMessageTemplate.content.cloneNode = () => hiddenAccountFragment;
live.accountName = { textContent: "Kim", hidden: true };
api.addUserMessage("no-chip", null, {});
const restoredFragment = makeFragment();
domRegistry.userMessageTemplate.content.cloneNode = () => restoredFragment;
api.addUserMessage("restored", null, { restored: true });
results.userMessageVariants = {
  chipRemoved: hiddenAccountFragment.nodes.chip.removed,
  restoredClockRemoved: restoredFragment.nodes.clock.removed,
  restoredStamp: restoredFragment.nodes.clock.textContent,
};

// 18. renderAnswer renders the answer paragraph, notes and runtime label.
function makeArticle() {
  const article = makeElement("article");
  const content = makeElement("content");
  const label = makeElement("runtimeLabel");
  article.querySelector = (selector) => ({
    ".assistant-content": content,
    "[data-runtime-label]": label,
  }[selector] || null);
  article.nodes = { content, label };
  return article;
}
const plain = makeArticle();
api.renderAnswer(plain, { answer: "답변", notice: "n1", metadata: { m: 1 } });
const decorated = makeArticle();
api.renderAnswer(decorated, {
  answer: "mock 답변", runtime: "mock", project_files_used: 3,
  skill: { id: "translate", title: "Translate" },
  memory_proposals: [{ id: "p1" }],
});
results.renderAnswer = {
  plainParagraph: plain.nodes.content.children.map((node) => node.textContent),
  plainLabel: plain.nodes.label.textContent,
  plainLifecycle: lifecycleSets[lifecycleSets.length - 1],
  grounding: groundingCalls[0],
  decoratedParagraph: decorated.nodes.content.children
    .filter((node) => node.className !== "reference-note").map((node) => node.textContent),
  referenceNote: decorated.nodes.content.children
    .filter((node) => node.className === "reference-note").map((node) => node.textContent),
  decoratedLabel: decorated.nodes.label.textContent,
  proposals: memoryReviewRenders[memoryReviewRenders.length - 1],
};

// 19. renderStreamError replaces the typing indicator with the retry box.
const failed = makeArticle();
const typing = { removed: 0, remove() { this.removed += 1; } };
failed.nodes.content.querySelector = (selector) => selector === ".typing" ? typing : null;
api.renderStreamError(failed, "m1", ["r1"], "skill1", "ctx1");
const clawFailed = makeArticle();
clawFailed.nodes.content.querySelector = () => null;
api.renderStreamError(clawFailed, "m2", ["r2"], null, "ctx2", true, "failed", { f: 1 }, "E-X");
results.renderStreamError = {
  typingRemoved: typing.removed,
  statusLabel: failed.nodes.label.textContent,
  boxAppended: failed.nodes.content.children.length,
  codeNoteAppended: retryBoxes[0].children
    .filter((node) => node.id === "codeNote").length,
  lifecycle: lifecycleSets[lifecycleSets.length - 1],
  revealed: revealedArticles.includes(failed),
  clawNoNote: retryBoxes[1].children
    .filter((node) => node.id === "codeNote").length,
  retryArgs: retryBoxCalls[0],
};

// 20. resetConversationView clears the shared surface without touching records.
live.conversationEpoch = 41;
live.activeRequestController = { abort() { live.abortCount += 1; } };
live.abortCount = 0;
live.inFlight = true;
live.activeClawRunId = "run-1";
live.clawArtifactShownFor = "conv-9";
live.selectedAttachments = [{ name: "y.txt", previewUrl: "blob:2" }];
live.messageList.children = [makeElement("m1"), makeElement("m2")];
live.messageList.hidden = false;
convPanel.dataset.continuousThread = "true";
const clawPanels2 = freshClawPanels();
live.input.value = "draft";
live.stateProduct = null;
live.stateReset = false;
memoryReviewSyncs.length = 0;
motionResets.length = 0;
api.resetConversationView(true);
results.resetView = {
  epoch: live.conversationEpoch,
  cancelReason: live.activeRequestCancelReason,
  aborted: live.abortCount,
  controllerNull: live.activeRequestController === null,
  clawRunIdNull: live.activeClawRunId === null,
  inFlight: live.inFlight,
  stateProduct: live.stateProduct,
  stateReset: live.stateReset,
  messages: live.messageList.children.length,
  listHidden: live.messageList.hidden,
  thread: convPanel.dataset.continuousThread || null,
  artifactShownFor: live.clawArtifactShownFor,
  artifactsCleared: live.artifactsCleared,
  emptyHidden: live.emptyState.hidden,
  state: live.shell.dataset.state,
  clawPanelsHidden: ["clawRunHistoryDisclosure", "clawRunHistory",
                     "clawApprovedDisclosure", "clawApprovedMemory", "clawMemoryReview"]
    .map((id) => (domRegistry[id] || makeElement("missing")).hidden),
  motionReset: motionResets.length,
  recoveryCleared: live.clearedRecovery,
  waitCleared: live.clearedWait,
  nav: live.navActive,
  inputCleared: live.input.value === "",
  projectRendered: live.projectState,
  sidebarClosed: live.sidebarClosed,
  inputFocused: live.input.focused,
};

// 21. resetConversation on the Claw screen switches product without a reset.
live.conversationProduct = "claw";
live.shell.dataset.state = "claw";
live.switchTo = null;
const epochBefore = live.conversationEpoch;
api.resetConversation(true);
results.resetFromClaw = {
  switched: live.switchTo,
  product: live.conversationProduct,
  state: live.shell.dataset.state,
  epochUnchanged: live.conversationEpoch === epochBefore,
};
// 21b. The ordinary path resets the view.
api.resetConversation(true);
results.resetOrdinary = { epoch: live.conversationEpoch };

// 22. renderAttachmentChips renders one chip per file with locale-keyed aria.
const chipItems = [
  { key: "att-1", type: "image", name: "photo.png", byteSize: 7 },
  { key: "att-2", type: "document", name: "report.pdf", byteSize: 99 },
  { key: "att-3", type: "document", name: "broken.txt", invalid: true, error: "empty-document" },
];
live.selectedAttachments = chipItems;
live.inFlight = true;
api.renderAttachmentChips();
const chips = live.attachmentChipList.children;
results.chips = {
  trayVisible: live.attachmentTray.hidden === false,
  count: chips.length,
  icons: chips.map((chip) => chip.children[0].textContent),
  invalidClasses: chips.map((chip) => chip.className.includes("attachment-chip-invalid")),
  names: chips.map((chip) => chip.children[1].children[0].textContent),
  details: chips.map((chip) => chip.children[1].children[1].textContent),
  removeAria: chips.map((chip) => chip.children[2].getAttribute("aria-label")),
  removeLocaleKey: chips.map((chip) => chip.children[2].getAttribute("data-locale-aria-label")),
  removeDisabled: chips.map((chip) => chip.children[2].disabled),
};
// 제거 버튼은 모듈의 removeAttachmentItem으로 연결된다.
live.inFlight = false;
chips[0].children[2].click();
results.chipRemoval = {
  removedKey: live.selectedAttachments[0] && live.selectedAttachments[0].key,
  remaining: live.selectedAttachments.length,
  rerendered: live.attachmentChipList.children.length,
};
// 빈 선택은 트레이를 숨긴다.
live.selectedAttachments = [];
api.renderAttachmentChips();
results.chipsEmpty = { trayHidden: live.attachmentTray.hidden, chips: live.attachmentChipList.children.length };

// 23. attachmentPayload builds the request-body attachments array.
results.payload = {
  emptyUndefined: api.attachmentPayload(undefined) === undefined,
  noneUndefined: api.attachmentPayload([]) === undefined,
  invalidOnlyUndefined: api.attachmentPayload([{ key: "att-9", invalid: true, name: "x" }]) === undefined,
  fileId: api.attachmentPayload([{ key: "att-4", fileId: "f-1" }]),
  file: api.attachmentPayload([{ key: "att-5", type: "image", name: "p.png",
    mediaType: "image/png", file: { bytes: 1 } }]),
  text: api.attachmentPayload([{ key: "att-6", type: "document", name: "d.txt",
    mediaType: "text/plain", text: "hello" }]),
  mixedFiltersInvalid: api.attachmentPayload([
    { key: "att-7", invalid: true, name: "bad" },
    { key: "att-8", fileId: "f-2" },
  ]),
};

// 24. attachmentTrayNote keys follow the actual media type.
results.trayNote = {
  empty: api.attachmentTrayNote(),
  hwpxMediaType: (live.selectedAttachments = [{ mediaType: "application/hwp+zip" }], api.attachmentTrayNote()),
  hwpxName: (live.selectedAttachments = [{ name: "doc.hwpx" }], api.attachmentTrayNote()),
  image: (live.selectedAttachments = [{ type: "image" }], api.attachmentTrayNote()),
  document: (live.selectedAttachments = [{ type: "document" }], api.attachmentTrayNote()),
};

// 25. addAttachmentFiles refuses per chip: count limit, legacy hwp, raw-single.
ctx.window.PadiemAttachmentCapabilities = { maxPerMessage: 2 };
live.selectedAttachments = [
  { key: "att-a", type: "document", name: "1.txt", text: "1" },
  { key: "att-b", type: "document", name: "2.txt", text: "2" },
];
await api.addAttachmentFiles([{ name: "3.txt", type: "text/plain", size: 3 }]);
const limitAttempt = live.selectedAttachments[live.selectedAttachments.length - 1];
live.selectedAttachments = [{ key: "att-a", type: "document", name: "1.txt", text: "1" }];
live.binaryDocuments.headerFamily = async () => "ole";
await api.addAttachmentFiles([{ name: "legacy.hwp", type: "", size: 10 }]);
const hwpAttempt = live.selectedAttachments[live.selectedAttachments.length - 1];
await api.addAttachmentFiles([{ name: "shot.png", type: "image/png", size: 11 }]);
const rawMixed = live.selectedAttachments[live.selectedAttachments.length - 1];
live.selectedAttachments = [];
await api.addAttachmentFiles([{ name: "shot.png", type: "image/png", size: 11 }]);
const imageAlone = live.selectedAttachments[0];
ctx.window.PadiemAttachmentCapabilities = undefined;
results.attachRefusals = {
  limitError: limitAttempt.error,
  limitInvalid: limitAttempt.invalid === true,
  hwpError: hwpAttempt.error,
  hwpInvalid: hwpAttempt.invalid === true,
  rawSingleError: rawMixed.error,
  rawSingleInvalid: rawMixed.invalid === true,
  imageValid: imageAlone && imageAlone.invalid !== true,
  imageType: imageAlone && imageAlone.type,
  fileInputCleared: live.attachmentFileInput.value === "",
};

process.stdout.write(JSON.stringify(results));
}

main().catch((error) => { console.error(error); process.exit(1); });
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


def test_show_conversation_keeps_the_first_turn_landing(observed: dict) -> None:
    # 첫 턴은 히어로를 그대로 둔다(소유 결정 2026-10-15). 대화 불러오기가
    # continuousThread를 남기고, 사용 중 화면은 랜딩을 해제한다.
    landing = observed["showLanding"]
    assert landing["thread"] == "true"
    assert landing["emptyHidden"] is False
    assert landing["listHidden"] is False
    assert landing["state"] == "chat"
    assert landing["switched"] == "chat"
    assert landing["nav"] is True
    assert landing["panelsHidden"] == [True, True, True, True]
    assert landing["detailsClosed"] == [True, True]
    assert landing["runsDestroyed"] == 0
    assert observed["showContinuing"] == {"thread": "true", "emptyHidden": False, "listHidden": False}
    assert observed["showUsedSurface"] == {"thread": None, "emptyHidden": True, "listHidden": False}


def test_show_conversation_reopens_saved_and_resets_stale_claw_disclosures(observed: dict) -> None:
    # 저장 대화 재열기는 히어로 없이 열고, Claw 화면은 유지하며 두 DETAILS만 닫는다.
    restored = observed["showRestored"]
    assert restored["thread"] is None
    assert restored["emptyHidden"] is True
    assert restored["listHidden"] is False
    assert restored["state"] == "claw"
    assert restored["switched"] is None
    assert restored["detailsClosed"] == [True, True]
    # Claw -> Chat 전환은 패널 4개를 숨기고 DETAILS를 닫지만 서버 소유 기록은
    # 지우지 않는다(replaceChildren 호출 0).
    switched = observed["showChatSwitch"]
    assert switched["state"] == "chat"
    assert switched["switched"] == "chat"
    assert switched["product"] == "chat"
    assert switched["panelsHidden"] == [True, True, True, True]
    assert switched["detailsClosed"] == [True, True]
    assert switched["runsDestroyed"] == 0


def test_add_user_message_renders_the_approved_turn(observed: dict) -> None:
    rendered = observed["userMessage"]
    assert rendered["bubble"] == "안녕"
    assert rendered["metas"] == ["attachment-photo · photo.png · fb-7",
                                 "attachment-document · a.pdf · fb-9"]
    assert rendered["chip"] == "Kim"
    assert rendered["avatar"] == "K"
    assert rendered["stamp"] == "ct-12:00"
    assert rendered["datetimeIso"] is True
    assert rendered["stampTooltip"] == "ct-12:00"
    assert rendered["copyAria"] == "answer-copy"
    assert rendered["copyTooltip"] == "answer-copy"
    assert rendered["boundToTooltip"] is True
    assert rendered["appended"] is True


def test_user_message_edit_refills_the_composer(observed: dict) -> None:
    edit = observed["userMessageEdit"]
    assert edit == {"input": "edit-me", "focused": 1, "inputEvent": 1}


def test_user_message_variants_drop_chip_and_stamp(observed: dict) -> None:
    variants = observed["userMessageVariants"]
    assert variants["chipRemoved"] == 1
    assert variants["restoredClockRemoved"] == 1
    assert variants["restoredStamp"] == ""


def test_user_message_copy_prefers_the_shared_clipboard_path(observed: dict) -> None:
    # #4488: 공유 클립보드 경로가 우선이고, 레거시 경로는 공유 스크립트가 없을
    # 때만 폴백으로 남는다. 문자열 순서 대신 호출을 기록해 검사한다.
    copied = observed["userMessageCopy"]
    assert copied["shared"] == ["안녕"]
    assert copied["clipboard"] == []
    assert copied["flash"] == "✓"
    assert copied["restored"] == ""
    assert copied["fallbackClipboard"] == ["fallback"]
    assert copied["fallbackShared"] == []


def test_render_answer_renders_paragraph_notes_and_runtime_label(observed: dict) -> None:
    answer = observed["renderAnswer"]
    assert answer["plainParagraph"] == ["답변"]
    assert answer["plainLabel"] == ""
    assert answer["plainLifecycle"] == ["article", "completed"]
    assert answer["grounding"] == ["n1", {"m": 1}]
    assert answer["decoratedParagraph"] == ["mock 답변"]
    assert answer["referenceNote"] == ["project-files-used"]
    assert answer["decoratedLabel"] == "mock-response · Translate"
    assert answer["proposals"] == [{"id": "p1"}]


def test_render_stream_error_replaces_typing_with_retry_box(observed: dict) -> None:
    failure = observed["renderStreamError"]
    assert failure["typingRemoved"] == 1
    assert failure["statusLabel"] == "status-failed"
    assert failure["boxAppended"] >= 1
    assert failure["codeNoteAppended"] == 1
    assert failure["lifecycle"] == ["article", "failed"]
    assert failure["revealed"] is True
    assert failure["clawNoNote"] == 0
    assert failure["retryArgs"] == {"message": "m1", "retries": ["r1"], "skill": "skill1",
                                    "context": "ctx1", "clawGeneral": False}


def test_reset_conversation_view_clears_the_shared_surface(observed: dict) -> None:
    reset = observed["resetView"]
    assert reset["epoch"] == 42
    assert reset["cancelReason"] == "conversation_reset"
    assert reset["aborted"] == 1
    assert reset["controllerNull"] is True
    assert reset["clawRunIdNull"] is True
    assert reset["inFlight"] is False
    assert reset["stateProduct"] == "chat"
    assert reset["stateReset"] is True
    assert reset["messages"] == 0
    assert reset["listHidden"] is True
    assert reset["thread"] is None
    assert reset["artifactShownFor"] == ""
    assert reset["artifactsCleared"] is True
    assert reset["emptyHidden"] is False
    assert reset["state"] == "home"
    assert reset["clawPanelsHidden"] == [True, True, True, True, True]
    assert reset["motionReset"] == 1
    assert reset["recoveryCleared"] is True
    assert reset["waitCleared"] is True
    assert reset["nav"] is True
    assert reset["inputCleared"] is True
    assert reset["projectRendered"] is True
    assert reset["sidebarClosed"] is True
    assert reset["inputFocused"] >= 1


def test_reset_conversation_switches_claw_to_chat_without_resetting(observed: dict) -> None:
    from_claw = observed["resetFromClaw"]
    assert from_claw == {"switched": "chat", "product": "chat", "state": "chat",
                         "epochUnchanged": True}
    assert observed["resetOrdinary"] == {"epoch": 43}


def test_attachment_chips_render_locale_keys_and_wire_removal(observed: dict) -> None:
    chips = observed["chips"]
    assert chips["trayVisible"] is True
    assert chips["count"] == 3
    assert chips["icons"] == ["IMG", "PDF", "TXT"]
    assert chips["invalidClasses"] == [False, False, True]
    assert chips["names"] == ["photo.png", "report.pdf", "broken.txt"]
    assert chips["details"] == ["fb-7", "fb-99", "empty-document"]
    assert chips["removeAria"] == ["attachment-remove"] * 3
    assert chips["removeLocaleKey"] == ["attachment-remove"] * 3
    assert chips["removeDisabled"] == [True, True, True]
    removal = observed["chipRemoval"]
    assert removal["removedKey"] == "att-2"
    assert removal["remaining"] == 2
    assert removal["rerendered"] == 2
    assert observed["chipsEmpty"] == {"trayHidden": True, "chips": 0}


def test_attachment_payload_builds_the_request_body(observed: dict) -> None:
    payload = observed["payload"]
    assert payload["emptyUndefined"] is True
    assert payload["noneUndefined"] is True
    assert payload["invalidOnlyUndefined"] is True
    assert payload["fileId"] == [{"type": "file", "file_id": "f-1"}]
    assert payload["file"] == [{"type": "image", "name": "p.png",
                                "media_type": "image/png", "file": {"bytes": 1}}]
    assert payload["text"] == [{"type": "document", "name": "d.txt",
                                "media_type": "text/plain", "text": "hello"}]
    assert payload["mixedFiltersInvalid"] == [{"type": "file", "file_id": "f-2"}]


def test_attachment_tray_note_follows_the_media_type(observed: dict) -> None:
    assert observed["trayNote"] == {
        "empty": "idle-note",
        "hwpxMediaType": "attachment-hwpx-note",
        "hwpxName": "attachment-hwpx-note",
        "image": "attachment-image-note",
        "document": "attachment-document-note",
    }


def test_add_attachment_files_refuse_per_chip(observed: dict) -> None:
    refusals = observed["attachRefusals"]
    assert refusals["limitError"] == "attachment-count-limit"
    assert refusals["limitInvalid"] is True
    assert refusals["hwpError"] == "hwp-legacy-guidance"
    assert refusals["hwpInvalid"] is True
    assert refusals["rawSingleError"] == "attachment-raw-single"
    assert refusals["rawSingleInvalid"] is True
    assert refusals["imageValid"] is True
    assert refusals["imageType"] == "image"
    assert refusals["fileInputCleared"] is True
