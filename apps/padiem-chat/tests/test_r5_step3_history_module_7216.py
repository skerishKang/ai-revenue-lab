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


def test_index_loads_the_history_module_before_app() -> None:
    assert INDEX.index("./chat-history-module.js") < INDEX.index("./app.js")
    assert INDEX.count("./chat-history-module.js") == 1


def test_app_keeps_one_line_forwarders_for_every_moved_function() -> None:
    for name in NAMES:
        line = f"function {name}(...a) {{ return historyModule().{name}(...a); }}"
        assert line in APP, name
        assert APP.count(f"function {name}(") == 1, name
    assert "function historyModule() {" in APP
    assert "window.PadiemChatHistoryModule.create({" in APP


def test_moved_bodies_live_only_in_the_module() -> None:
    for marker in MOVED_MARKERS:
        assert marker in MODULE, marker
        assert marker not in APP, marker


def test_module_exposes_one_factory_and_touches_no_dom_at_load() -> None:
    assert "window.PadiemChatHistoryModule = {" in MODULE
    assert "create(deps) {" in MODULE
    # One global factory only; no DOM lookup at load time.
    assert "document.getElementById" not in MODULE
    for name in NAMES:
        assert f"function {name}(" in MODULE, name


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
const api = ctx.window.PadiemChatHistoryModule.create(deps);
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
        harness.write_text(_HARNESS, encoding="utf-8", newline="\n")
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