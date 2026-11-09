"""#7216 R5 step 3 — real Chromium calls into the moved history forwarders.

app.js keeps one-line forwarders for the 18 recent-conversations-menu functions
that now live in ``chat-history-module.js``. This file injects the REAL module
source and the REAL forwarder lines (extracted from shipped app.js) into a
Chromium page, then calls every forwarder and checks its observable effect.
String presence is not proof; every moved function is exercised in a browser.

Getter contract: the deps object is built from live getters, and the checks
below change the underlying value before the first call (and between calls) to
prove the module reads it at call time, not at create() time.
"""
from __future__ import annotations

import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright  # noqa: E402

STATIC = Path(__file__).resolve().parents[1] / "static"
APP = (STATIC / "app.js").read_text(encoding="utf-8")
STRICT = (Path(__file__).resolve().parent / "_r5_strict_deps.js").read_text(encoding="utf-8")

NAMES = (
    "renderTyping", "clearHistoryUI", "renderHistorySkeleton",
    "renderHistoryLoadFailed", "fetchRecentConversations", "loadRecentConversations",
    "clearHistoryActionStatus", "showHistoryActionStatus", "patchConversation",
    "focusHistoryConversation", "beginConversationRename", "deleteConversation",
    "clearClawRunHistoryPdfPreviews", "setClawRunHistoryStatus",
    "clawRunHistoryErrorMessage", "fetchClawRunHistory", "loadClawRunHistory",
    "syncClawRunHistoryVisibility",
)

HARNESS = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><title>R5 history forwarders</title></head>
<body>
<section id="historySection" hidden><ul id="historyList"></ul><div id="historyEmpty"></div></section>
<div id="historyActionStatus" hidden></div>
<div id="clawRunHistory" hidden>
  <details id="clawRunHistoryDisclosure"><summary>runs</summary></details>
  <button id="clawRunHistoryExpand"></button>
  <div id="clawRunHistoryLoading"></div>
  <div id="clawRunHistoryError"></div>
  <div id="clawRunHistoryList"></div>
  <div id="clawRunHistoryEmpty"></div>
</div>
<input id="messageInput" />
<div class="app-shell" id="shell"></div>
<script src="/static/chat-history-module.js"></script>
<script>
__STRICT__
window.__log = [];
window.__calls = [];
window.__live = {
  historySection: document.getElementById("historySection"),
  historyList: document.getElementById("historyList"),
  historyEmpty: document.getElementById("historyEmpty"),
  historyActionStatus: document.getElementById("historyActionStatus"),
  clawRunHistory: document.getElementById("clawRunHistory"),
  clawRunHistoryDisclosure: document.getElementById("clawRunHistoryDisclosure"),
  clawRunHistoryExpand: document.getElementById("clawRunHistoryExpand"),
  clawRunHistoryError: document.getElementById("clawRunHistoryError"),
  clawRunHistoryLoading: document.getElementById("clawRunHistoryLoading"),
  clawRunHistoryList: document.getElementById("clawRunHistoryList"),
  clawRunHistoryEmpty: document.getElementById("clawRunHistoryEmpty"),
  HISTORY_TITLE_MAX_CHARS: 80,
  authState: { authenticated: true, history_ready: true },
  authViewEpoch: 1,
  shell: document.getElementById("shell"),
  input: document.getElementById("messageInput"),
  conversationState: { getConversationId: () => window.__activeConversationId || "" },
  inFlight: false,
  clawConversationIds: new Set(),
  clawRunHistoryPdfControllers: new Set(),
  historyReadSequence: 0,
  clawConversationLabelsRead: null,
  clawRunHistoryInFlight: false,
  clawRunHistoryLeftSurface: false,
  clawRunHistoryLimit: 10,
  clawRunHistoryVisibilityEpoch: 0,
  pendingClawRunFocusId: "",
  uiT: (key) => key,
  clawT: (key) => key,
  sidebarActionIcon: (name) => { const s = document.createElement("span"); s.dataset.icon = name; return s; },
  openSavedConversation: (id) => { window.__log.push("open:" + id); },
  readClawRuns: (...a) => window.__readClawRuns(...a),
  mappedUiError: (message, data) => Object.assign(new Error(message), { code: data && data.error && data.error.code }),
  safeLocalUiMessage: (error, fallback) => fallback,
  failureCodeNote: (code) => { const s = document.createElement("small"); s.dataset.code = code; return s; },
  renderClawRunCard: (run) => { const d = document.createElement("div"); d.className = "claw-run-card"; d.dataset.runId = run.run_id; return d; },
  resetConversationView: (hard) => { window.__log.push("reset:" + hard); },
  setNote: (message, kind) => { window.__log.push("note:" + message + ":" + (kind || "")); },
  idleNote: () => "idle-note",
};
window.__deps = {};
for (const key of Object.keys(window.__live)) {
  Object.defineProperty(window.__deps, key, {
    get() { return window.__live[key]; },
    set(value) { window.__live[key] = value; },
  });
}
// Argon review of PR #7249 (d): fail fast on any deps read the fake omits.
window.__deps = r5StrictDeps(window.__deps, "step3.history.browser.deps");
window.__readClawRuns = async () => ({ response: { ok: true }, data: { ok: true, runs: [] } });
window.__fetchLog = [];
window.fetch = async (url, options) => {
  window.__fetchLog.push({ url: String(url), options: options || {} });
  return window.__fetchResponse ? window.__fetchResponse(url, options) : { ok: true, status: 200, json: async () => ({}) };
};
window.PadiemConfirmDialog = { confirm: async (spec) => { window.__calls.push(spec); return window.__confirmResult !== false; } };
let __instance = null;
function historyModule() {
  if (!__instance) __instance = window.PadiemChatHistoryModule.create(window.__deps);
  return __instance;
}
__FORWARDERS__
window.__article = () => {
  const article = document.createElement("article");
  const content = document.createElement("div");
  content.className = "assistant-content";
  article.appendChild(content);
  return article;
};
window.__reset = () => {
  window.__log = [];
  window.__calls = [];
  window.__fetchLog = [];
  window.__confirmResult = true;
  window.__activeConversationId = "";
  for (const key of Object.keys(window.__live)) {
    if (key === "clawConversationIds" || key === "clawRunHistoryPdfControllers") window.__live[key].clear();
    else if (key === "historyList" || key === "clawRunHistoryList") window.__live[key].replaceChildren();
  }
  const byId = (id) => document.getElementById(id);
  for (const id of ["historySection", "historyEmpty", "historyActionStatus", "clawRunHistory",
                    "clawRunHistoryExpand", "clawRunHistoryLoading", "clawRunHistoryError", "clawRunHistoryList"]) {
    byId(id).hidden = (id === "historyEmpty" || id === "clawRunHistoryEmpty" || id === "historyList");
  }
  byId("historySection").hidden = true;
  byId("historyEmpty").hidden = true;
  byId("historyActionStatus").hidden = true;
  byId("clawRunHistory").hidden = true;
  byId("clawRunHistoryLoading").hidden = false;
  byId("clawRunHistoryError").hidden = true;
  byId("clawRunHistoryError").textContent = "";
  delete byId("clawRunHistoryError").dataset.state;
  window.__live.authState = { authenticated: true, history_ready: true };
  window.__live.authViewEpoch = 1;
  window.__live.historyReadSequence = 0;
  window.__live.clawConversationLabelsRead = null;
  window.__live.clawRunHistoryInFlight = false;
  window.__live.clawRunHistoryLeftSurface = false;
  window.__live.clawRunHistoryLimit = 10;
  window.__live.clawRunHistoryVisibilityEpoch = 0;
  window.__live.pendingClawRunFocusId = "";
  window.__live.HISTORY_TITLE_MAX_CHARS = 80;
  window.__live.inFlight = false;
  window.__live.shell.dataset.state = "home";
  // A fresh factory per scenario so "before the first call" stays meaningful.
  __instance = null;
};
</script>
</body></html>
"""


def _forwarder_lines() -> str:
    lines = []
    for name in NAMES:
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
    harness = STATIC / "_r5_history_forwarder_harness.html"
    harness.write_text(HARNESS.replace("__STRICT__", STRICT).replace("__FORWARDERS__", _forwarder_lines()),
                       encoding="utf-8", newline="\n")
    server = ThreadingHTTPServer(("127.0.0.1", 0), _StaticHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/static/_r5_history_forwarder_harness.html"
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


# ── per-function forwarder calls (one browser check per moved function) ────


def test_renderTyping_forwarder(browser_page) -> None:
    out = browser_page.evaluate("""() => {
      window.__reset();
      const article = window.__article();
      renderTyping(article);
      const content = article.querySelector(".assistant-content");
      const span = content.children[0];
      return { n: content.children.length, cls: span.className, aria: span.getAttribute("aria-hidden") };
    }""")
    assert out == {"n": 1, "cls": "typing", "aria": "true"}


def test_clearHistoryUI_forwarder(browser_page) -> None:
    out = browser_page.evaluate("""() => {
      window.__reset();
      window.__live.clawConversationIds.add("chat_x");
      window.__live.clawConversationLabelsRead = { epoch: 1, promise: null };
      window.__live.historyList.appendChild(document.createElement("div"));
      window.__live.historySection.hidden = false;
      window.__live.historyEmpty.hidden = false;
      clearHistoryUI();
      return {
        ids: window.__live.clawConversationIds.size,
        labels: window.__live.clawConversationLabelsRead,
        rows: window.__live.historyList.children.length,
        section: window.__live.historySection.hidden,
        empty: window.__live.historyEmpty.hidden,
      };
    }""")
    assert out == {"ids": 0, "labels": None, "rows": 0, "section": True, "empty": True}


def test_renderHistorySkeleton_forwarder(browser_page) -> None:
    out = browser_page.evaluate("""() => {
      window.__reset();
      renderHistorySkeleton();
      const rows = [...window.__live.historyList.children];
      return { n: rows.length, cls: rows.map((r) => r.className),
               section: window.__live.historySection.hidden,
               empty: window.__live.historyEmpty.hidden };
    }""")
    assert out == {"n": 4, "cls": ["history-row history-skeleton"] * 4, "section": False, "empty": True}


def test_renderHistoryLoadFailed_forwarder(browser_page) -> None:
    out = browser_page.evaluate("""async () => {
      window.__reset();
      window.__fetchResponse = () => ({ ok: true, status: 200, json: async () => ({ conversations: [] }) });
      renderHistoryLoadFailed();
      const row = window.__live.historyList.children[0];
      const retry = row.querySelector("button");
      const before = window.__fetchLog.length;
      retry.click();
      await new Promise((r) => setTimeout(r, 0));
      return { cls: row.className, text: row.children[0].textContent,
               retryCls: retry.className, retryText: retry.textContent,
               reloads: window.__fetchLog.length - before };
    }""")
    assert out["cls"] == "history-row history-load-failed"
    assert out["text"] == "history-load-failed"
    assert out["retryCls"] == "history-retry"
    assert out["retryText"] == "history-retry"
    assert out["reloads"] >= 1, "the retry button must re-run the read"


def test_fetchRecentConversations_forwarder(browser_page) -> None:
    out = browser_page.evaluate("""async () => {
      window.__reset();
      window.__fetchResponse = () => ({ ok: true, status: 200,
        json: async () => ({ conversations: [{ id: "chat_1", title: "Alpha" }] }) });
      const data = await fetchRecentConversations();
      return { n: data.conversations.length, url: window.__fetchLog[0].url };
    }""")
    assert out == {"n": 1, "url": "/api/conversations"}


def test_loadRecentConversations_forwarder(browser_page) -> None:
    out = browser_page.evaluate("""async () => {
      window.__reset();
      const clawId = "chat_" + "a".repeat(32);
      window.__fetchResponse = () => ({ ok: true, status: 200, json: async () => ({ conversations: [
        { id: clawId, title: "Alpha" },
        { id: "chat_2", title: "Beta", pinned: true },
      ] }) });
      window.__readClawRuns = async () => ({ response: { ok: true }, data: { ok: true, runs: [
        { channel: "web", action: "general", status: "completed", session: { conversation_id: clawId } },
      ] } });
      await loadRecentConversations();
      if (window.__live.clawConversationLabelsRead) await window.__live.clawConversationLabelsRead.promise;
      const rows = [...window.__live.historyList.children];
      const alpha = rows[0], group = rows[1], beta = rows[2];
      const alphaButton = alpha.querySelector("button");
      return {
        n: rows.length,
        group: group.className + ":" + group.textContent,
        alphaText: alphaButton.textContent,
        betaText: beta.querySelector("button").textContent,
        betaRow: beta.className,
        alphaActions: !!alpha.querySelector("details.history-actions"),
        ids: [...window.__live.clawConversationIds],
        section: window.__live.historySection.hidden,
        empty: window.__live.historyEmpty.hidden,
      };
    }""")
    claw_id = "chat_" + "a" * 32
    assert out["n"] == 3
    assert out["group"] == "history-group-label:conversation-pinned-group"
    assert out["alphaText"] == "Claw · Alpha"
    assert out["betaText"] == "Beta"
    assert out["betaRow"] == "history-row history-row-pinned"
    assert out["alphaActions"] is True
    assert out["ids"] == [claw_id]
    assert out["section"] is False
    # The empty placeholder hides while the list has rows.
    assert out["empty"] is True


def test_clearHistoryActionStatus_forwarder(browser_page) -> None:
    out = browser_page.evaluate("""() => {
      window.__reset();
      showHistoryActionStatus("saved");
      clearHistoryActionStatus();
      return { hidden: window.__live.historyActionStatus.hidden,
               text: window.__live.historyActionStatus.textContent };
    }""")
    assert out == {"hidden": True, "text": ""}


def test_showHistoryActionStatus_forwarder(browser_page) -> None:
    out = browser_page.evaluate("""() => {
      window.__reset();
      showHistoryActionStatus("nope");
      return { hidden: window.__live.historyActionStatus.hidden,
               text: window.__live.historyActionStatus.textContent };
    }""")
    assert out == {"hidden": False, "text": "nope"}


def test_patchConversation_forwarder(browser_page) -> None:
    out = browser_page.evaluate("""async () => {
      window.__reset();
      window.__fetchResponse = (url, options) => ({ ok: true, status: 200, json: async () => ({
        updated: true, conversation: { id: "chat_1", title: "New" } }) });
      const updated = await patchConversation("chat_1", { title: "New" });
      const call = window.__fetchLog[0];
      return { title: updated.title, method: call.options.method,
               body: call.options.body, url: call.url };
    }""")
    assert out["title"] == "New"
    assert out["method"] == "PATCH"
    assert out["body"] == '{"title":"New"}'
    assert out["url"] == "/api/conversations/chat_1"


def test_focusHistoryConversation_forwarder(browser_page) -> None:
    out = browser_page.evaluate("""() => {
      window.__reset();
      window.__live.historySection.hidden = false;
      const row = document.createElement("div");
      row.className = "history-row";
      row.dataset.conversationId = "chat_9";
      const actions = document.createElement("details");
      actions.className = "history-actions";
      const more = document.createElement("summary");
      more.className = "history-more";
      actions.appendChild(more);
      row.appendChild(actions);
      window.__live.historyList.appendChild(row);
      focusHistoryConversation("chat_9");
      return { focused: document.activeElement.className };
    }""")
    assert out == {"focused": "history-more"}


def test_beginConversationRename_forwarder(browser_page) -> None:
    out = browser_page.evaluate("""() => {
      window.__reset();
      const row = document.createElement("div");
      const button = document.createElement("button");
      row.appendChild(button);
      beginConversationRename(row, button, { id: "chat_1", title: "Alpha" });
      const input = row.querySelector("input");
      return { cls: input.className, max: input.maxLength, value: input.value,
               label: input.getAttribute("aria-label"), inRow: row.contains(input) };
    }""")
    assert out == {"cls": "history-rename-input", "max": 80, "value": "Alpha",
                   "label": "conversation-rename-aria", "inRow": True}


def test_deleteConversation_forwarder(browser_page) -> None:
    out = browser_page.evaluate("""async () => {
      window.__reset();
      window.__activeConversationId = "chat_other";
      window.__fetchResponse = () => ({ ok: true, status: 200,
        json: async () => ({ deleted: true, conversation_id: "chat_1" }) });
      await deleteConversation("chat_1", "Alpha");
      const call = window.__fetchLog.find((c) => c.options.method === "DELETE");
      return { confirm: window.__calls.length, title: window.__calls[0].title,
               method: call.options.method, url: call.url, log: window.__log };
    }""")
    assert out["confirm"] == 1
    assert out["title"] == "conversation-delete-title"
    assert out["method"] == "DELETE"
    assert out["url"] == "/api/conversations/chat_1"
    assert out["log"] == ["note:idle-note:"]


def test_clearClawRunHistoryPdfPreviews_forwarder(browser_page) -> None:
    out = browser_page.evaluate("""() => {
      window.__reset();
      const state = { destroyed: 0 };
      window.__live.clawRunHistoryPdfControllers.add({ destroy() { state.destroyed += 1; } });
      clearClawRunHistoryPdfPreviews();
      return { destroyed: state.destroyed, size: window.__live.clawRunHistoryPdfControllers.size };
    }""")
    assert out == {"destroyed": 1, "size": 0}


def test_setClawRunHistoryStatus_forwarder(browser_page) -> None:
    out = browser_page.evaluate("""() => {
      window.__reset();
      setClawRunHistoryStatus("boom", "E42");
      const node = window.__live.clawRunHistoryError;
      const shown = { hidden: node.hidden, text: node.textContent, state: node.dataset.state,
                      code: node.querySelector("small").dataset.code };
      setClawRunHistoryStatus("");
      return { shown, cleared: { hidden: node.hidden, text: node.textContent,
                                 state: node.getAttribute("data-state") } };
    }""")
    assert out["shown"] == {"hidden": False, "text": "boom", "state": "error", "code": "E42"}
    assert out["cleared"] == {"hidden": True, "text": "", "state": None}


def test_clawRunHistoryErrorMessage_forwarder(browser_page) -> None:
    out = browser_page.evaluate("""() => {
      window.__reset();
      return {
        auth: clawRunHistoryErrorMessage({ error: { code: "unauthorized" } }, { status: 401 }),
        other: clawRunHistoryErrorMessage({ error: { code: "boom" } }, { status: 500 }),
      };
    }""")
    assert out == {"auth": "claw-error-auth-needed", "other": "claw-runs-error"}


def test_fetchClawRunHistory_forwarder(browser_page) -> None:
    out = browser_page.evaluate("""async () => {
      window.__reset();
      window.__live.clawRunHistory.hidden = false;
      window.__readClawRuns = async () => ({ response: { ok: true }, data: { ok: true, runs: [
        { run_id: "run_1" }, { run_id: "run_2" },
      ] } });
      await fetchClawRunHistory();
      const list = window.__live.clawRunHistoryList;
      return { cards: [...list.children].map((c) => c.dataset.runId),
               listHidden: list.hidden, loadingHidden: window.__live.clawRunHistoryLoading.hidden };
    }""")
    assert out == {"cards": ["run_1", "run_2"], "listHidden": False, "loadingHidden": True}


def test_loadClawRunHistory_forwarder(browser_page) -> None:
    out = browser_page.evaluate("""async () => {
      window.__reset();
      window.__live.clawRunHistory.hidden = false;
      let calls = 0, sawInFlight = false;
      window.__readClawRuns = async () => {
        calls += 1;
        sawInFlight = window.__live.clawRunHistoryInFlight === true;
        await new Promise((r) => setTimeout(r, 0));
        return { response: { ok: true }, data: { ok: true, runs: [] } };
      };
      const first = loadClawRunHistory();
      const second = loadClawRunHistory();
      await Promise.all([first, second]);
      return { calls, sawInFlight, released: window.__live.clawRunHistoryInFlight === false };
    }""")
    assert out == {"calls": 1, "sawInFlight": True, "released": True}


def test_syncClawRunHistoryVisibility_forwarder(browser_page) -> None:
    out = browser_page.evaluate("""async () => {
      window.__reset();
      let calls = 0;
      window.__readClawRuns = async () => {
        calls += 1;
        return { response: { ok: true }, data: { ok: true, runs: [] } };
      };
      window.__live.shell.dataset.state = "claw";
      syncClawRunHistoryVisibility();
      const shown = { hidden: window.__live.clawRunHistory.hidden, calls };
      await new Promise((r) => setTimeout(r, 0));
      window.__live.shell.dataset.state = "home";
      syncClawRunHistoryVisibility();
      return { shown, after: {
        hidden: window.__live.clawRunHistory.hidden,
        epoch: window.__live.clawRunHistoryVisibilityEpoch,
        limit: window.__live.clawRunHistoryLimit,
      } };
    }""")
    assert out["shown"] == {"hidden": False, "calls": 1}
    assert out["after"] == {"hidden": True, "epoch": 1, "limit": 10}


# ── getter contract (the deps getters read the live closure values) ────────


def test_deps_getters_read_the_value_that_changed_before_the_first_call(browser_page) -> None:
    out = browser_page.evaluate("""() => {
      window.__reset();
      // Swap the list BEFORE the first forwarder call; the module instance is
      // still uncreated, and the effect must land on the new node.
      const replacement = document.createElement("ul");
      window.__live.historyList = replacement;
      renderHistorySkeleton();
      return { rows: replacement.children.length,
               untouched: document.getElementById("historyList").children.length };
    }""")
    assert out == {"rows": 4, "untouched": 0}


def test_deps_setters_write_back_into_the_closure_value(browser_page) -> None:
    out = browser_page.evaluate("""async () => {
      window.__reset();
      window.__live.shell.dataset.state = "claw";
      syncClawRunHistoryVisibility();
      await new Promise((r) => setTimeout(r, 0));
      window.__live.shell.dataset.state = "home";
      syncClawRunHistoryVisibility();
      // The epoch/limit writes go through the deps setters into __live.
      return { epoch: window.__live.clawRunHistoryVisibilityEpoch,
               limit: window.__live.clawRunHistoryLimit };
    }""")
    assert out == {"epoch": 1, "limit": 10}