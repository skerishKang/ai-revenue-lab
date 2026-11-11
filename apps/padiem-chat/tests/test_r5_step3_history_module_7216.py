"""#7216 R5 step 3 — recent-conversations-menu module contract.

app.js의 최근 대화 메뉴 18개 함수가 chat-history-module.js로 이동했고, app.js는
같은 이름의 한 줄 전달 함수를 유지한다. 이 시험은 (1) 실제 모듈 본문을 Node vm
에서 실행해 동작이 그대로인지, (2) deps getter가 첫 호출 전에 바뀐 클로저 값을
읽는지, (3) setter가 다시 대입하는 변수를 클로저에 쓰는지, (4) app.js가 전달
함수만 남겼고 index.html이 모듈을 app.js보다 먼저 로드하는지를 확인한다.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from html.parser import HTMLParser
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "static"
APP = (STATIC / "app.js").read_text(encoding="utf-8")
MODULE = (STATIC / "chat-history-module.js").read_text(encoding="utf-8")
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")

NAMES = (
    "renderTyping", "clearHistoryUI", "renderHistorySkeleton",
    "renderHistoryLoadFailed", "fetchRecentConversations", "loadRecentConversations",
    "clearHistoryActionStatus", "showHistoryActionStatus", "patchConversation",
    "focusHistoryConversation", "beginConversationRename", "deleteConversation",
    "clearClawRunHistoryPdfPreviews", "setClawRunHistoryStatus",
    "clawRunHistoryErrorMessage", "fetchClawRunHistory", "loadClawRunHistory",
    "syncClawRunHistoryVisibility",
)

# Bodies that must exist in the module and nowhere else.
MOVED_MARKERS = (
    'row.className = "history-row history-skeleton";',
    'row.className = "history-row history-load-failed";',
    'input.className = "history-rename-input";',
    "verifiedClawIds.add(run.session.conversation_id);",
    'className = "history-group-label"',
    'typing.className = "typing";',
    "deps.clawRunHistoryVisibilityEpoch += 1;",
    "clearClawRunHistoryPdfPreviews();",
)


class _ScriptSrcParser(HTMLParser):
    """index.html의 script src 순서를 문자열 위치가 아니라 마크업에서 읽는다."""

    def __init__(self) -> None:
        super().__init__()
        self.srcs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "script":
            return
        for name, value in attrs:
            if name == "src" and value:
                self.srcs.append(value)


def test_index_loads_the_history_module_before_app() -> None:
    # R2(#7186): 소스 문자열 위치 대신 실제 script 로드 순서를 판정한다.
    parser = _ScriptSrcParser()
    parser.feed(INDEX)
    order = parser.srcs
    assert order.count("./chat-history-module.js") == 1
    assert order.index("./chat-history-module.js") < order.index("./app.js")


def test_app_keeps_one_line_forwarders_for_every_moved_function() -> None:
    """구조 계약: app.js는 같은 이름의 전달 함수만 남긴다(R5 B1).

    모듈 함수 자체의 동작은 behavior harness가 직접 호출해 증명한다. 이 시험은
    app.js 호출부 호환(이름·인자 전달)이라는 구조 계약이라 유지한다.
    """
    for name in NAMES:
        line = f"function {name}(...a) {{ return historyModule().{name}(...a); }}"
        assert line in APP, name
        assert APP.count(f"function {name}(") == 1, name
    assert "function historyModule() {" in APP
    assert "window.PadiemChatHistoryModule.create({" in APP


def test_moved_bodies_live_only_in_the_module() -> None:
    """구조 계약: 이동한 본문이 app.js에 다시 생기지 않는다.

    R2(#7186): 긍정 동작(스켈레톤·실패 행·이름 변경 입력·고정 그룹·Claw 라벨·
    타자 표시)은 _MENU_HARNESS가 실제 실행으로 증명한다. 여기서는 이중 소유를
    막는 부정 계약만 남긴다.
    """
    for marker in MOVED_MARKERS:
        assert marker not in APP, marker


def test_module_exposes_one_factory_and_touches_no_dom_at_load() -> None:
    """구조 경계: 전역 팩토리 하나, 로드 시 DOM 조회 없음(R5 모듈 경계).

    18개 함수의 존재와 호출 가능성은 두 harness가 직접 호출해 증명한다.
    """
    assert "window.PadiemChatHistoryModule = {" in MODULE
    assert "create(deps) {" in MODULE
    # One global factory only; no DOM lookup at load time.
    assert "document.getElementById" not in MODULE
    for name in NAMES:
        assert f"function {name}(" in MODULE, name


STRICT = (Path(__file__).resolve().parent / "_r5_strict_deps.js").read_text(encoding="utf-8")

_HARNESS = r"""
const fs = require("fs");
const vm = require("vm");

function makeElement(id) {
  const attrs = {};
  return {
    id, hidden: false, disabled: false, textContent: "", value: "",
    className: "", maxLength: 0, dataset: {}, children: [], listeners: {},
    setAttribute(k, v) { attrs[k] = String(v); this[k] = v; },
    getAttribute(k) { return attrs[k] === undefined ? null : attrs[k]; },
    removeAttribute(k) { delete attrs[k]; },
    appendChild(child) { this.children.push(child); child.isConnected = true; return child; },
    append(...nodes) { nodes.forEach((n) => this.appendChild(n)); },
    replaceChildren(...nodes) { this.children = []; nodes.forEach((n) => this.appendChild(n)); },
    replaceWith() {}, replaceChild(next, old) {
      const at = this.children.indexOf(old);
      if (at >= 0) this.children[at] = next;
    },
    addEventListener(name, fn) { (this.listeners[name] ||= []).push(fn); },
    click() { (this.listeners.click || []).forEach((fn) => fn()); },
    querySelectorAll() { return []; }, querySelector() { return null; },
    focus() { this.focused = (this.focused || 0) + 1; }, select() {},
  };
}

const document = {
  createElement(tag) { return makeElement(tag); },
  createTextNode(text) { return { nodeType: 3, textContent: text }; },
};

const live = {
  historySection: makeElement("historySection"),
  historyList: makeElement("historyList"),
  historyEmpty: makeElement("historyEmpty"),
  historyActionStatus: makeElement("historyActionStatus"),
  clawRunHistory: makeElement("clawRunHistory"),
  clawRunHistoryDisclosure: makeElement("clawRunHistoryDisclosure"),
  clawRunHistoryExpand: makeElement("clawRunHistoryExpand"),
  clawRunHistoryError: makeElement("clawRunHistoryError"),
  clawRunHistoryLoading: makeElement("clawRunHistoryLoading"),
  clawRunHistoryList: makeElement("clawRunHistoryList"),
  clawRunHistoryEmpty: makeElement("clawRunHistoryEmpty"),
  HISTORY_TITLE_MAX_CHARS: 80,
  authState: { authenticated: true, history_ready: true },
  authViewEpoch: 3,
  shell: { dataset: { state: "claw" } },
  input: makeElement("messageInput"),
  conversationState: { getConversationId: () => live.activeConversationId || "" },
  activeConversationId: "",
  inFlight: false,
  clawConversationIds: new Set(),
  clawRunHistoryPdfControllers: new Set(),
  historyReadSequence: 0,
  clawConversationLabelsRead: null,
  clawRunHistoryInFlight: false,
  clawRunHistoryLeftSurface: true,
  clawRunHistoryLimit: 30,
  clawRunHistoryVisibilityEpoch: 0,
  pendingClawRunFocusId: "",
  uiT: (key) => key,
  clawT: (key) => key,
  sidebarActionIcon: (name) => ({ icon: name }),
  openSavedConversation: (id) => { live.opened = id; },
  readClawRuns: (...a) => live.readClawRunsImpl(...a),
  readClawRunsImpl: async () => ({ response: { ok: true }, data: { ok: true, runs: [] } }),
  fetchCalls: [],
  fetchImpl: async () => ({ ok: true, status: 200, json: async () => ({}) }),
  mappedUiError: (message, data) => Object.assign(new Error(message), { code: data && data.error && data.error.code }),
  safeLocalUiMessage: (error, fallback) => fallback,
  failureCodeNote: () => null,
  renderClawRunCard: (run) => { const el = makeElement("card"); el.dataset.runId = run.run_id; return el; },
  resetConversationView: (hard) => { live.reset = hard; },
  setNote: (message, kind) => { live.note = [message, kind]; },
  idleNote: () => "idle",
};
const deps = {};
for (const key of Object.keys(live)) {
  Object.defineProperty(deps, key, {
    get() { return live[key]; },
    set(value) { live[key] = value; },
  });
}

const ctx = {
  document, console,
  window: { PadiemSharedTooltip: null, PadiemConfirmDialog: { confirm: async () => true } },
  fetch: async (...a) => { live.fetchCalls.push(a); return live.fetchImpl(...a); },
  Map, Set, Array, JSON, Promise, Date, Error, encodeURIComponent, String, Object,
};
ctx.window.window = ctx.window;
vm.createContext(ctx);
const source = fs.readFileSync(process.argv[2], "utf8");
vm.runInContext(source, ctx, { filename: "chat-history-module.js" });
const api = ctx.window.PadiemChatHistoryModule.create(r5StrictDeps(deps, "step3.history.deps"));
const results = {};

// 1. skeleton: 4 rows, section shown, empty hidden (before/after reads live deps).
api.renderHistorySkeleton();
results.skeleton = { rows: live.historyList.children.length,
  cls: live.historyList.children[0].className,
  section: live.historySection.hidden, empty: live.historyEmpty.hidden };

// 2. status helpers keep the same node contract.
api.showHistoryActionStatus("kept");
const shown = { hidden: live.historyActionStatus.hidden, text: live.historyActionStatus.textContent };
api.clearHistoryActionStatus();
results.status = { shown, cleared: { hidden: live.historyActionStatus.hidden,
  text: live.historyActionStatus.textContent } };

// 3. clearHistoryUI is still the signed-out cleanup: ids, labels, list, flags.
live.clawConversationIds.add("chat_x");
live.clawConversationLabelsRead = { epoch: 1 };
api.clearHistoryUI();
results.clear = { ids: live.clawConversationIds.size,
  labels: live.clawConversationLabelsRead,
  section: live.historySection.hidden, empty: live.historyEmpty.hidden };

// 4. patchConversation sends the two reviewed fields and validates the answer.
live.fetchImpl = async () => ({ ok: true, status: 200,
  json: async () => ({ updated: true, conversation: { id: "chat_1", title: "New" } }) });
api.patchConversation("chat_1", { title: "New" }).then((conversation) => {
  results.patch = { title: conversation.title,
    url: live.fetchCalls[0][0], method: live.fetchCalls[0][1].method,
    body: live.fetchCalls[0][1].body };
  phase2();
});

function phase2() {
  // 5. the run-history error copy is keyed, never a raw message.
  results.copy = {
    auth: api.clawRunHistoryErrorMessage({ error: { code: "unauthorized" } }, { status: 401 }),
    other: api.clawRunHistoryErrorMessage({}, { status: 500 }),
  };

  // 6. setClawRunHistoryStatus shows and clears the same node.
  api.setClawRunHistoryStatus("boom", "E42");
  const shown2 = { hidden: live.clawRunHistoryError.hidden, text: live.clawRunHistoryError.textContent,
    state: live.clawRunHistoryError.dataset.state };
  api.setClawRunHistoryStatus("");
  results.runStatus = { shown2, cleared: live.clawRunHistoryError.hidden };

  // 7. the PDF previews are destroyed before the list is dropped.
  let destroyed = 0;
  live.clawRunHistoryPdfControllers.add({ destroy() { destroyed += 1; } });
  api.clearClawRunHistoryPdfPreviews();
  results.pdf = { destroyed, size: live.clawRunHistoryPdfControllers.size };

  // 8. Getter contract: the element replaced BEFORE the first call wins.
  const replacement = makeElement("lateHistoryList");
  live.historyList = replacement;
  api.renderHistorySkeleton();
  results.getter = { rows: replacement.children.length };

  // 9. Getter contract 2: a constant changed before the first call is used.
  live.HISTORY_TITLE_MAX_CHARS = 12;
  const row = makeElement("row");
  row.replaceChild = () => {};
  api.beginConversationRename(row, makeElement("button"), { id: "chat_1", title: "Alpha" });
  results.maxLength = row.children.length ? null : live.createdInput && live.createdInput.maxLength;
  document.createElement = ((orig) => (tag) => {
    const node = orig(tag);
    if (tag === "input") live.createdInput = node;
    return node;
  })(document.createElement);
  api.beginConversationRename(row, makeElement("button"), { id: "chat_1", title: "Alpha" });
  results.maxLength = live.createdInput.maxLength;

  // 10. Setter contract: visibility bookkeeping writes back into the closure.
  live.clawRunHistory.hidden = false;
  live.shell.dataset.state = "home";
  live.clawRunHistoryLimit = 30;
  live.clawRunHistoryVisibilityEpoch = 5;
  api.syncClawRunHistoryVisibility();
  results.setter = { epoch: live.clawRunHistoryVisibilityEpoch,
    limit: live.clawRunHistoryLimit, left: live.clawRunHistoryLeftSurface };

  process.stdout.write(JSON.stringify(results));
}
"""

def _run_harness() -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not available for the module harness")
    with tempfile.TemporaryDirectory() as tmp:
        harness = Path(tmp) / "harness.js"
        harness.write_text(STRICT + "\n" + _HARNESS, encoding="utf-8", newline="\n")
        completed = subprocess.run(
            [node, str(harness), str(STATIC / "chat-history-module.js")],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
        )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


@pytest.fixture(scope="module")
def observed() -> dict:
    return _run_harness()


def test_module_behavior_matches_the_closed_over_originals(observed: dict) -> None:
    assert observed["skeleton"] == {"rows": 4, "cls": "history-row history-skeleton",
                                    "section": False, "empty": True}
    assert observed["status"] == {
        "shown": {"hidden": False, "text": "kept"},
        "cleared": {"hidden": True, "text": ""},
    }
    assert observed["clear"] == {"ids": 0, "labels": None, "section": True, "empty": True}
    assert observed["patch"] == {"title": "New", "url": "/api/conversations/chat_1",
                                 "method": "PATCH", "body": '{"title":"New"}'}
    assert observed["copy"] == {"auth": "claw-error-auth-needed", "other": "claw-runs-error"}
    assert observed["runStatus"]["shown2"] == {"hidden": False, "text": "boom", "state": "error"}
    assert observed["runStatus"]["cleared"] is True
    assert observed["pdf"] == {"destroyed": 1, "size": 0}


def test_getters_read_the_value_changed_before_the_first_call(observed: dict) -> None:
    # The rows must land on the list node installed before the first call of
    # renderHistorySkeleton against the live deps object.
    assert observed["getter"] == {"rows": 4}
    # And the rename input takes the cap constant as it reads it at call time.
    assert observed["maxLength"] == 12


def test_setters_write_the_bookkeeping_back_into_the_closure(observed: dict) -> None:
    assert observed["setter"] == {"epoch": 6, "limit": 10, "left": True}


_MENU_HARNESS = r"""
const fs = require("fs");
const vm = require("vm");

function makeElement(tag) {
  const node = {
    tagName: String(tag || "div").toUpperCase(), parentNode: null, isConnected: false,
    id: "", className: "", textContent: "", value: "", type: "",
    hidden: false, disabled: false, open: false, maxLength: 0,
    dataset: {}, children: [], listeners: {}, attrs: {},
    setAttribute(k, v) { this.attrs[k] = String(v); this[k] = v; },
    getAttribute(k) { return this.attrs[k] === undefined ? null : this.attrs[k]; },
    removeAttribute(k) { delete this.attrs[k]; delete this[k]; },
    appendChild(child) { child.parentNode = this; child.isConnected = true; this.children.push(child); return child; },
    append(...nodes) { nodes.forEach((n) => this.appendChild(n)); },
    replaceChildren(...nodes) {
      this.children.forEach((c) => { c.parentNode = null; c.isConnected = false; });
      this.children = [];
      nodes.forEach((n) => this.appendChild(n));
    },
    replaceChild(next, old) {
      const at = this.children.indexOf(old);
      if (at >= 0) { this.children[at] = next; next.parentNode = this; next.isConnected = true; }
      return old;
    },
    replaceWith(next) { if (this.parentNode) this.parentNode.replaceChild(next, this); },
    addEventListener(name, fn) { (this.listeners[name] ||= []).push(fn); },
    click() { return Promise.all((this.listeners.click || []).map((fn) => fn())).then(() => undefined); },
    focus() { this.focused = (this.focused || 0) + 1; },
    select() {},
    querySelectorAll(sel) { return descendants(this).filter((n) => matches(n, sel)); },
    querySelector(sel) { return descendants(this).find((n) => matches(n, sel)) || null; },
  };
  return node;
}

function descendants(root) {
  const out = [];
  const walk = (node) => (node.children || []).forEach((child) => { out.push(child); walk(child); });
  walk(root);
  return out;
}

function matches(node, selector) {
  const found = String(selector).match(/^([a-zA-Z]*)((?:\.[\w-]+)*)(\[open\])?$/);
  if (!found) return false;
  const [, tag, classes, attr] = found;
  if (tag && node.tagName !== tag.toUpperCase()) return false;
  const names = String(node.className || "").split(/\s+/).filter(Boolean);
  for (const name of (classes || "").split(".").filter(Boolean)) {
    if (!names.includes(name)) return false;
  }
  if (attr && node.open !== true) return false;
  return true;
}

const document = {
  createElement(tag) { return makeElement(tag); },
  createTextNode(text) { return { nodeType: 3, textContent: String(text) }; },
};

const live = {
  historyList: makeElement("historyList"),
  historySection: makeElement("historySection"),
  historyEmpty: makeElement("historyEmpty"),
  historyActionStatus: makeElement("historyActionStatus"),
  authState: { authenticated: true, history_ready: true },
  authViewEpoch: 3,
  historyReadSequence: 0,
  clawConversationIds: new Set(),
  clawConversationLabelsRead: null,
  inFlight: false,
  HISTORY_TITLE_MAX_CHARS: 80,
  conversationState: { getConversationId: () => live.activeConversationId || "" },
  activeConversationId: "",
  input: makeElement("messageInput"),
  note: null,
  reset: null,
  opened: null,
  uiT: (key, params) => (params && params.title ? key + ":" + params.title : key),
  sidebarActionIcon: (name) => ({ icon: name }),
  openSavedConversation: (id) => { live.opened = id; },
  readClawRuns: async () => ({ response: { ok: true }, data: { ok: true, runs: [] } }),
  resetConversationView: (hard) => { live.reset = hard; },
  setNote: (message, kind) => { live.note = [message, kind]; },
  idleNote: () => "idle",
};
const deps = {};
for (const key of Object.keys(live)) {
  Object.defineProperty(deps, key, { get() { return live[key]; }, set(value) { live[key] = value; } });
}

const requests = [];
let confirmAnswer = true;
let confirmArgs = null;
let current = [
  { id: "chat_pin", title: "\uace0\uc815 \ub300\ud654", pinned: true },
  { id: "chat_free", title: "\ubcf4\ud1b5 \ub300\ud654", pinned: false },
  { id: "chat_tool", title: "\uc678\ubd80 AI \ub3c4\uad6c \uc694\uccad: x", pinned: false },
];
let fetchImpl = async () => ({ ok: true, status: 200, json: async () => ({ conversations: [] }) });
const recordingFetch = async (url, init) => {
  const method = String((init && init.method) || "GET").toUpperCase();
  const body = init && init.body ? JSON.parse(init.body) : null;
  requests.push({ url: String(url), method, body, headers: (init && init.headers) || {}, cache: init && init.cache });
  return fetchImpl(url, init);
};

function installResponses() {
  fetchImpl = async (url, init) => {
    const method = String((init && init.method) || "GET").toUpperCase();
    const id = decodeURIComponent(String(url).split("/").pop());
    if (method === "PATCH") {
      const target = current.find((c) => c.id === id);
      Object.assign(target, JSON.parse(init.body));
      return { ok: true, status: 200, json: async () => ({ updated: true, conversation: Object.assign({}, target) }) };
    }
    if (method === "DELETE") {
      current = current.filter((c) => c.id !== id);
      return { ok: true, status: 200, json: async () => ({ deleted: true, conversation_id: id }) };
    }
    return { ok: true, status: 200, json: async () => ({ conversations: current.map((c) => Object.assign({}, c)) }) };
  };
}

const ctx = {
  document, console, Map, Set, Date, Error, JSON, Promise, String, Object,
  encodeURIComponent, setTimeout,
  window: {
    PadiemSharedTooltip: null,
    PadiemConfirmDialog: {
      confirm: async (args) => { confirmArgs = args; return confirmAnswer; },
    },
  },
  fetch: recordingFetch,
};
ctx.window.window = ctx.window;
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[2], "utf8"), ctx, { filename: "chat-history-module.js" });
const api = ctx.window.PadiemChatHistoryModule.create(r5StrictDeps(deps, "menu.history.deps"));
const flush = () => new Promise((resolve) => setTimeout(resolve, 0));
const rowOf = (id) => live.historyList.children.find((n) => n.dataset && n.dataset.conversationId === id) || null;
const menuOf = (id) => { const row = rowOf(id); return row ? row.querySelector(".history-actions-menu") : null; };
const buttonOf = (id, selector) => { const row = rowOf(id); return row ? row.querySelector(selector) : null; };

(async () => {
  const out = {};
  installResponses();

  // A. recent list + pinned group + menu controls + tool-request group
  await api.loadRecentConversations();
  const pinnedRow = rowOf("chat_pin");
  const freeRow = rowOf("chat_free");
  out.list = {
    group: (live.historyList.children.find((n) => n.className === "history-group-label") || {}).textContent,
    pinnedClass: pinnedRow && pinnedRow.className,
    freeClass: freeRow && freeRow.className,
    items: ["chat_pin", "chat_free"].map((id) => (buttonOf(id, ".history-item") || {}).textContent),
    more: (pinnedRow && pinnedRow.querySelector(".history-more") || {}).attrs,
    menuClass: (menuOf("chat_pin") || {}).className,
    rename: {
      className: (buttonOf("chat_pin", ".history-menu-rename") || {}).className,
      aria: (buttonOf("chat_pin", ".history-menu-rename") || {}).attrs,
      text: (buttonOf("chat_pin", ".history-menu-rename") || {}).children.filter((n) => n.nodeType === 3).map((n) => n.textContent),
    },
    pin: {
      aria: (buttonOf("chat_pin", ".history-menu-pin") || {}).attrs,
      text: (buttonOf("chat_pin", ".history-menu-pin") || {}).children.filter((n) => n.nodeType === 3).map((n) => n.textContent),
    },
    freePinAria: (buttonOf("chat_free", ".history-menu-pin") || {}).attrs,
    remove: {
      className: (buttonOf("chat_pin", ".history-menu-delete") || {}).className,
      aria: (buttonOf("chat_pin", ".history-menu-delete") || {}).attrs,
      text: (buttonOf("chat_pin", ".history-menu-delete") || {}).children.filter((n) => n.nodeType === 3).map((n) => n.textContent),
    },
    toolGroup: (() => {
      const group = live.historyList.querySelector(".history-tool-requests");
      return group ? { className: group.className, summary: group.querySelector(".history-tool-requests-summary").textContent } : null;
    })(),
  };

  // B. pin click sends exactly {pinned: true} and reloads the canonical list
  requests.length = 0;
  await buttonOf("chat_free", ".history-menu-pin").click();
  out.pin = {
    patch: requests.find((r) => r.method === "PATCH"),
    reloads: requests.filter((r) => r.method === "GET" && r.url === "/api/conversations").length,
    pinnedClass: (rowOf("chat_free") || {}).className,
  };

  // C. rename in place: input contract, collapse on Enter, PATCH body, reload
  requests.length = 0;
  api.beginConversationRename(rowOf("chat_pin"), buttonOf("chat_pin", ".history-item"),
    { id: "chat_pin", title: "\uace0\uc815 \ub300\ud654", pinned: true });
  const input = rowOf("chat_pin").querySelector(".history-rename-input");
  out.rename = {
    className: input && input.className,
    value: input && input.value,
    maxLength: input && input.maxLength,
    aria: input && input.attrs,
  };
  input.value = "  \ubc14\ub014   \uc774\ub984 ";
  (input.listeners.keydown || []).forEach((fn) => fn({ key: "Enter", preventDefault() {}, stopPropagation() {} }));
  for (let i = 0; i < 8; i += 1) await flush();
  out.rename.patch = requests.find((r) => r.method === "PATCH");
  out.rename.title = (buttonOf("chat_pin", ".history-item") || {}).textContent;

  // D. delete: cancel sends nothing, confirm sends DELETE and resets the view
  requests.length = 0;
  confirmAnswer = false;
  await api.deleteConversation("chat_free", "\ubcf4\ud1b5 \ub300\ud654");
  out.deleteCancelled = { requests: requests.length, args: confirmArgs };
  requests.length = 0;
  confirmAnswer = true;
  live.activeConversationId = "chat_free";
  await api.deleteConversation("chat_free", "\ubcf4\ud1b5 \ub300\ud654");
  out.delete = {
    request: requests.find((r) => r.method === "DELETE"),
    reset: live.reset,
    note: live.note,
    rows: live.historyList.children.filter((n) => n.dataset && n.dataset.conversationId === "chat_free").length,
  };

  // E. a failed load is one honest retry row, never an empty list
  fetchImpl = async () => { throw new Error("down"); };
  await api.loadRecentConversations();
  const failed = live.historyList.children[0];
  out.loadFailed = {
    className: failed && failed.className,
    retry: failed && failed.querySelector(".history-retry") ? failed.querySelector(".history-retry").textContent : null,
  };

  // F. typing marker keeps its class and stays out of the accessibility tree
  const article = makeElement("article");
  const content = makeElement("div");
  content.className = "assistant-content";
  article.appendChild(content);
  api.renderTyping(article);
  out.typing = { className: content.children[0].className, ariaHidden: content.children[0].attrs };

  // G. a verified Claw run labels the row without granting any authority
  const clawId = "chat_" + "a".repeat(32);
  live.clawConversationIds.clear();
  installResponses();
  current = [{ id: clawId, title: "Claw \ub300\ud654", pinned: false }];
  live.readClawRuns = async () => ({ response: { ok: true }, data: { ok: true, runs: [{
    channel: "web", action: "general", title: "Claw: x", status: "completed",
    session: { conversation_id: clawId } }] } });
  await api.loadRecentConversations();
  await live.clawConversationLabelsRead.promise;
  out.clawLabel = (buttonOf(clawId, ".history-item") || {}).textContent;

  process.stdout.write(JSON.stringify(out));
})().catch((error) => {
  process.stdout.write(JSON.stringify({ error: String((error && error.stack) || error) }));
  process.exitCode = 1;
});
"""


def _run_menu_harness() -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not available for the module harness")
    with tempfile.TemporaryDirectory() as tmp:
        harness = Path(tmp) / "menu_harness.js"
        harness.write_text(STRICT + "\n" + _MENU_HARNESS, encoding="utf-8", newline="\n")
        completed = subprocess.run(
            [node, str(harness), str(STATIC / "chat-history-module.js")],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
        )
    assert completed.returncode == 0, completed.stderr + completed.stdout
    return json.loads(completed.stdout)


@pytest.fixture(scope="module")
def menu() -> dict:
    return _run_menu_harness()


def test_recent_menu_rows_and_controls_are_rendered(menu: dict) -> None:
    assert "error" not in menu, menu
    observed = menu["list"]
    assert observed["group"] == "conversation-pinned-group"
    assert observed["pinnedClass"] == "history-row history-row-pinned"
    assert observed["freeClass"] == "history-row"
    assert observed["items"] == ["\uace0\uc815 \ub300\ud654", "\ubcf4\ud1b5 \ub300\ud654"]
    assert observed["more"]["aria-label"] == "manage: \uace0\uc815 \ub300\ud654"
    assert observed["menuClass"] == "history-actions-menu"
    assert observed["rename"]["className"] == "history-menu-action history-menu-rename"
    assert observed["rename"]["aria"]["aria-label"] == "conversation-rename-aria:\uace0\uc815 \ub300\ud654"
    assert observed["rename"]["text"] == ["conversation-rename"]
    assert observed["pin"]["aria"]["aria-label"] == "conversation-unpin-aria:\uace0\uc815 \ub300\ud654"
    assert observed["pin"]["text"] == ["conversation-unpin"]
    assert observed["freePinAria"]["aria-label"] == "conversation-pin-aria:\ubcf4\ud1b5 \ub300\ud654"
    assert observed["remove"]["className"] == "history-delete history-menu-delete"
    assert observed["remove"]["aria"]["aria-label"] == "conversation-delete-aria:\uace0\uc815 \ub300\ud654"
    assert observed["remove"]["text"] == ["delete"]
    assert observed["toolGroup"] == {
        "className": "history-tool-requests",
        "summary": "history-tool-request-group",
    }


def test_pin_click_sends_the_boolean_and_reloads(menu: dict) -> None:
    observed = menu["pin"]
    assert observed["patch"] == {
        "url": "/api/conversations/chat_free",
        "method": "PATCH",
        "body": {"pinned": True},
        "headers": {"Accept": "application/json", "Content-Type": "application/json"},
        "cache": "no-store",
    }
    assert observed["reloads"] >= 1
    assert observed["pinnedClass"] == "history-row history-row-pinned"


def test_rename_input_and_patch_keep_the_title_contract(menu: dict) -> None:
    observed = menu["rename"]
    assert observed["className"] == "history-rename-input"
    assert observed["value"] == "\uace0\uc815 \ub300\ud654"
    assert observed["maxLength"] == 80
    assert observed["aria"]["aria-label"] == "conversation-rename-aria:\uace0\uc815 \ub300\ud654"
    assert observed["aria"]["enterkeyhint"] == "done"
    assert observed["patch"]["url"] == "/api/conversations/chat_pin"
    assert observed["patch"]["method"] == "PATCH"
    # Enter collapses inner whitespace and trims before the PATCH.
    assert observed["patch"]["body"] == {"title": "\ubc14\ub014 \uc774\ub984"}
    assert observed["title"] == "\ubc14\ub014 \uc774\ub984"


def test_delete_requires_confirmation_and_stays_owner_scoped(menu: dict) -> None:
    cancelled = menu["deleteCancelled"]
    assert cancelled["requests"] == 0
    assert cancelled["args"] == {
        "title": "conversation-delete-title",
        "message": "conversation-delete-message:\ubcf4\ud1b5 \ub300\ud654",
        "cancelLabel": "cancel",
        "confirmLabel": "delete",
    }
    deleted = menu["delete"]
    assert deleted["request"] == {
        "url": "/api/conversations/chat_free",
        "method": "DELETE",
        "body": None,
        "headers": {"Accept": "application/json"},
        "cache": "no-store",
    }
    assert deleted["reset"] is True
    assert deleted["rows"] == 0


def test_failed_load_and_typing_keep_the_old_dom_contract(menu: dict) -> None:
    assert menu["loadFailed"] == {
        "className": "history-row history-load-failed",
        "retry": "history-retry",
    }
    assert menu["typing"] == {"className": "typing", "ariaHidden": {"aria-hidden": "true"}}


def test_verified_claw_run_labels_the_row(menu: dict) -> None:
    assert menu["clawLabel"] == "Claw \u00b7 Claw \ub300\ud654"