"""#2505 Task B: Chat and Claw show and continue ONE conversation.

Owner decision (2026-10-21): Chat and Claw are two screens of one AI product,
and the ten capabilities are shared. The #2505 audit rated history/context
PARTIAL for one reason: the store, the `b62-chat` scope and the search were
already common, but the browser kept a separate conversation id and a separate
turn list per screen, so a thread started on one screen could not be continued
on the other.

This file replaces the earlier separation contract (`test_chat_claw_conversation_
separation.py`, from the #3221-era design that deliberately kept two browser
slots). What is proven now:

* the browser turn store keeps ONE conversation id and ONE turn list;
* opening the other screen keeps the transcript and the id — nothing is parked
  or restored, and nothing is deleted;
* a Claw submit after a Chat turn carries that same conversation id (and the
  reverse), so the lane changes but the thread does not;
* the server has always stored both lanes in one owner-scoped record, so the
  same id is appended from either lane — proven against a store that refuses a
  different product scope.

The proof is the shipped `conversation-state.js` and the shipped `app.js` running
against a synthetic DOM shim (same Element API as the #4488 harness). No model,
provider or Engine is contacted.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from contextlib import contextmanager

from starlette.testclient import TestClient

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.app_factory import create_app
from app.auth import SESSION_COOKIE, create_session_token
from app.config import Settings
from app.history import PRODUCT_SCOPE_CHAT

ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "static/app.js"
STATE_JS = ROOT / "static/conversation-state.js"
HISTORY_PY = ROOT / "app/history.py"


def _app_source() -> str:
    return APP_JS.read_text(encoding="utf-8")


def _function_body(source: str, name: str) -> str:
    start = source.index(f"function {name}(")
    end = source.index("\n  }", start)
    return source[start:end]


# ── static contracts ─────────────────────────────────────────────────────────


def test_the_browser_keeps_one_conversation_for_both_screens() -> None:
    state = STATE_JS.read_text(encoding="utf-8")
    # One store, not one per product.
    assert "const conversation = { messages: [], conversationId: null, skill: \"auto\" };" in state
    assert "PRODUCT_IDS.forEach((id) => resetProduct(id));" not in state
    assert "if (!slots.has(id)) slots.set(id" not in state
    # The plain API every existing call site uses still exists.
    for name in (
        "function reset()",
        "function resetProduct()",
        "function setProduct(product)",
        "function getProduct()",
        "function appendMessage(message)",
        "function outboundWithUser(content)",
        "function commitAssistant(outboundMessages, content)",
        "function getConversationId()",
        "function setConversationId(value)",
    ):
        assert name in state, name
    # No DOM, no network, no model in the turn store.
    for forbidden in ("document.", "fetch(", "AbortController"):
        assert forbidden not in state, forbidden


def test_the_panel_no_longer_parks_one_screen_to_show_the_other() -> None:
    app = _app_source()
    assert "parkProductTurns" not in app
    assert "restoreProductTurns" not in app
    assert "productViews" not in app
    switch = _function_body(app, "switchConversationProduct")
    # The lane changes; the transcript does not.
    assert "conversationState.setProduct?.(target);" in switch
    assert "messageList.replaceChildren()" not in switch
    # The Claw artifact index still follows the Claw screen.
    assert "conversationArtifactContext?.clear?.();" in switch


def test_a_claw_submit_carries_the_chat_conversation_id() -> None:
    app = _app_source()
    submit = app[app.index("async function submitPrompt("):]
    submit = submit[: submit.index("\n  }")]
    # The lane is still decided per submit…
    assert "const product = clawGeneralRequest ? PRODUCT_CLAW : PRODUCT_CHAT;" in submit
    # …and the conversation comes from the one shared store.
    assert "conversationState.getConversationId(product)" in submit
    # A saved thread is loaded into that same store, whichever lane owns it.
    open_saved = _function_body(app, "openSavedConversation")
    assert "conversationState.resetProduct?.(targetProduct);" in open_saved
    assert "conversationState.setConversationId(data.conversation.id, targetProduct);" in open_saved


def test_the_server_still_keeps_one_scoped_record_for_both_lanes() -> None:
    """No schema change: the continuity is one id in one existing scope."""
    history = HISTORY_PY.read_text(encoding="utf-8")
    assert 'PRODUCT_SCOPE_CHAT = "b62-chat"' in history
    assert 'KNOWN_PRODUCT_SCOPES = frozenset({PRODUCT_SCOPE_CHAT, PRODUCT_SCOPE_B66})' in history
    assert "PRODUCT_SCOPE_CLAW" not in history


# ── behavioural proof: the real conversation-state.js ────────────────────────


def test_one_conversation_survives_every_screen_switch() -> None:
    script = f"""
    global.window = {{}};
    require({json.dumps(str(STATE_JS))});
    const state = window.PadiemChatConversationState;
    state.setProduct("chat");
    state.setConversationId("conv_shared");
    state.appendMessage({{ role: "user", content: "chat turn" }});
    const chatOutbound = state.outboundWithUser("chat question");
    // The user opens Claw: the same conversation must still be there.
    state.setProduct("claw");
    const idOnClaw = state.getConversationId();
    const clawOutbound = state.outboundWithUser("claw question");
    state.setConversationId("conv_shared");
    state.appendMessage({{ role: "user", content: "claw turn" }});
    // The user returns to Chat: the same conversation is still there.
    state.setProduct("chat");
    const idBackOnChat = state.getConversationId("chat");
    const chatTurns = state.outboundWithUser("chat again", "chat");
    process.stdout.write(JSON.stringify({{
      idOnClaw,
      idBackOnChat,
      activeProduct: state.getProduct(),
      clawOutboundLength: clawOutbound.length,
      chatOutboundLength: chatOutbound.length,
      chatTurnsLength: chatTurns.length,
      clawSeesChatTurn: clawOutbound.some((m) => m.content === "chat turn"),
      chatSeesClawTurn: chatTurns.some((m) => m.content === "claw turn"),
    }}));
    """
    completed = subprocess.run(
        ["node", "-e", script], check=True, capture_output=True, text=True
    )
    data = json.loads(completed.stdout)
    # One id crosses the switch in both directions.
    assert data["idOnClaw"] == "conv_shared"
    assert data["idBackOnChat"] == "conv_shared"
    assert data["activeProduct"] == "chat"
    # One turn list: the Claw lane sees the Chat turn and appends to it.
    assert data["chatOutboundLength"] == 2
    assert data["clawOutboundLength"] == 2
    assert data["chatTurnsLength"] == 3
    assert data["clawSeesChatTurn"] is True
    assert data["chatSeesClawTurn"] is True


# ── behavioural proof: the real app.js against a DOM shim ────────────────────

_HARNESS = r"""
const fs = require("fs");
const vm = require("vm");
const APP = fs.readFileSync(process.argv[2], "utf8");
const STATE = fs.readFileSync(process.argv[3], "utf8");

let DOC = null;

function makeEl(tag) {
  const el = {
    tagName: String(tag).toUpperCase(), id: "", className: "", textContent: "",
    hidden: false, disabled: false, open: false, children: [], attributes: {},
    listeners: {}, dataset: {}, style: {}, scrollTop: 0, scrollHeight: 0,
    clientHeight: 0, options: [], selectedIndex: 0, files: [], parentNode: null,
    classList: { add() {}, remove() {}, contains() { return false; }, toggle() {} },
  };
  let rawValue = "";
  Object.defineProperty(el, "value", {
    get: () => rawValue,
    set: (v) => {
      rawValue = v;
      (el.listeners.input || []).forEach((fn) => fn({ type: "input", target: el }));
      (el.listeners.change || []).forEach((fn) => fn({ type: "change", target: el }));
    },
  });
  el.setAttribute = (k, v) => {
    el.attributes[k] = String(v);
    el[k] = String(v);
    if (k.startsWith("data-")) el.dataset[k.slice(5).replace(/-(\w)/g, (m, c) => c.toUpperCase())] = String(v);
  };
  el.getAttribute = (k) => (k in el.attributes ? el.attributes[k] : (k in el ? el[k] : null));
  el.removeAttribute = (k) => { delete el.attributes[k]; delete el[k]; };
  el.appendChild = (c) => { el.children.push(c); c.parentNode = el; return c; };
  el.prepend = (...cs) => cs.forEach((c) => { el.children.unshift(c); c.parentNode = el; });
  el.append = (...cs) => cs.forEach((c) => el.appendChild(c));
  el.replaceChildren = (...cs) => { el.children = []; cs.forEach((c) => el.appendChild(c)); };
  el.insertBefore = (node, ref) => {
    const at = el.children.indexOf(ref);
    if (at < 0) el.children.push(node); else el.children.splice(at, 0, node);
    node.parentNode = el;
    return node;
  };
  el.removeChild = (node) => { el.children = el.children.filter((c) => c !== node); return node; };
  el.hasChildNodes = () => el.children.length > 0;
  el.remove = () => { if (el.parentNode) el.parentNode.children = el.parentNode.children.filter((c) => c !== el); };
  el.addEventListener = (t, fn) => { (el.listeners[t] = el.listeners[t] || []).push(fn); };
  el.matchesSelector = (sel) => {
    if (sel.startsWith(".")) return String(el.className).split(/\s+/).includes(sel.slice(1));
    if (sel.startsWith("[")) { const name = sel.slice(1, -1).split("=")[0]; return name in el.attributes; }
    return el.tagName === String(sel).toUpperCase();
  };
  el._synthetic = {};
  el.querySelector = (sel) => {
    const search = (node) => {
      for (const c of node.children || []) {
        if (c && c.matchesSelector && c.matchesSelector(sel)) return c;
        const deeper = search(c);
        if (deeper) return deeper;
      }
      return null;
    };
    const found = search(el);
    if (found) return found;
    if (!el._synthetic[sel]) el._synthetic[sel] = makeEl("div");
    return el._synthetic[sel];
  };
  el.querySelectorAll = (sel) => (sel && sel.indexOf("claw-chip") >= 0 ? [] : el.children);
  el.focus = () => { if (DOC) DOC.activeElement = el; };
  el.blur = () => { if (DOC && DOC.activeElement === el) DOC.activeElement = null; };
  el.scrollIntoView = () => {};
  el.click = () => (el.listeners.click || []).forEach((fn) => fn({ preventDefault() {}, target: el, key: "" }));
  el.requestSubmit = () => (el.listeners.submit || []).forEach((fn) => fn({ preventDefault() {} }));
  el.matches = () => false;
  el.closest = (sel) => {
    const want = String(sel).replace(/^\./, "");
    let node = el;
    while (node) {
      if (node.className && String(node.className).includes(want)) return node;
      node = node.parentNode;
    }
    return null;
  };
  return el;
}

// The two message templates index.html ships; the app clones them.
function makeAssistantArticle() {
  const content = makeEl("div");
  content.className = "assistant-content";
  const label = makeEl("span");
  label.className = "demo-label";
  label.setAttribute("data-runtime-label", "");
  const meta = makeEl("div");
  meta.className = "assistant-meta";
  const product = makeEl("span");
  product.setAttribute("data-assistant-product", "");
  const body = makeEl("div");
  body.className = "assistant-body";
  body.append(meta, content);
  const article = makeEl("article");
  article.className = "message assistant-message";
  article.append(makeEl("div"), body);
  return article;
}

function makeUserArticle() {
  const bubble = makeEl("div");
  bubble.className = "message-bubble";
  const article = makeEl("article");
  article.className = "message user-message";
  article.append(bubble);
  return article;
}

function templateFragment(root) {
  return {
    children: [root],
    querySelector: (sel) => (
      String(root.className || "").includes(String(sel).replace(/^\./, ""))
        ? root
        : root.querySelector(sel)
    ),
  };
}

function makeDom() {
  const byId = {};
  const add = (id, tag) => { const e = makeEl(tag); e.id = id; byId[id] = e; return e; };
  [
    "emptyState","messageList","composerForm","messageInput","sendButton","cancelStreamButton","newChatButton",
    "mobileMenu","mobileClose","sidebarScrim","settingsButton","settingsDialog","settingsCloseButton",
    "attachmentFileInput","attachmentButton","attachmentTray","attachmentThumb","attachmentKind","attachmentName",
    "attachmentSize","removeAttachment","documentStarterButton","runtimeNote","loginButton","accountName",
    "historySection","historyList","historyEmpty","projectsNavButton","projectsBadge","projectsSection",
    "projectsList","projectsEmpty","projectCreateButton","projectBanner","activeProjectName","activeProjectFiles",
    "editProjectButton","exitProjectButton","projectDialog","projectForm","projectDialogTitle","projectDialogClose",
    "projectDialogCancel","projectNameInput","projectInstructionsInput","projectFormError","projectSaveButton",
    "projectFilesPanel","projectFileInput","projectFilesList","projectFilesEmpty","clawNavButton","clawWorkspace",
    "clawManualForm","clawManualEntryButton","clawChannel","clawAction","clawSender","clawResultArea","clawResultPreview",
    "clawResultCard","clawResultEmpty","clawResultKind","clawGenerateBtn","clawExecuteButton","clawResultBadge",
    "clawResultDocx","clawStatus","clawWait","clawArtifactMeta","clawArtifactName","clawArtifactSize",
    "clawResultSuccessNote","clawResultHint","clawExecuteHint","clawApprovedMemory","clawApprovedDisclosure",
    "clawApprovedRefresh","clawApprovedLoading","clawApprovedError","clawApprovedList","clawApprovedEmpty",
    "clawMemoryReview","clawApprovalActions","clawRequestEcho","clawRequestEchoText",
    "tasksNavButton","alertsNavButton","clawInbox","clawInboxTitle","clawInboxLoading","clawInboxError",
    "clawInboxEmpty","clawInboxList","clawInboxRetry","clawRunHistory","clawRunHistoryDisclosure",
    "clawRunHistoryRefresh","clawRunHistoryExpand","clawRunHistoryLoading","clawRunHistoryError",
    "clawRunHistoryList","clawRunHistoryEmpty","clawRetryHint","clawRetryBox","clawRetryCopy","clawRetryButton",
    "authDialog","authDialogClose","passwordLoginForm","passwordLoginIdentifier","passwordLoginPassword",
    "passwordLoginError","passwordLoginSubmit","googleLoginButton","clawModelIdInput",
  ].forEach((id) => add(id, "div"));
  if (byId.messageList) {
    const conversationSection = makeEl("section");
    conversationSection.className = "conversation";
    conversationSection.appendChild(byId.messageList);
  }
  byId.clawApprovedDisclosure.tagName = "DETAILS";
  const shell = add("app-shell", "div");
  shell.dataset = { state: "home" };
  const accountContainer = add("sidebar-account", "div");
  byId.clawChannel.options = [{ textContent: "KakaoTalk" }];
  byId.clawChannel.value = "kakao";
  byId.clawAction.options = [{ textContent: "quote" }];
  byId.clawAction.value = "quote";
  const doc = {
    documentElement: { lang: "ko", classList: { add() {}, remove() {}, contains() { return false; } } },
    body: makeEl("body"),
    activeElement: null,
    getElementById: (id) => {
      if (/Template$/.test(id)) {
        byId.__templates = byId.__templates || {};
        if (!byId.__templates[id]) {
          byId.__templates[id] = makeEl("template");
          byId.__templates[id].content = {
            cloneNode: () => templateFragment(
              id === "assistantMessageTemplate" ? makeAssistantArticle() : makeUserArticle(),
            ),
          };
        }
        return byId.__templates[id];
      }
      return byId[id] || null;
    },
    querySelector: (sel) => (sel === ".app-shell" ? shell : sel === ".sidebar-account" ? accountContainer : null),
    querySelectorAll: () => [],
    createElement: (tag) => makeEl(tag),
    addEventListener() {},
  };
  byId.projectForm.querySelector = () => makeEl("div");
  DOC = doc;
  return { byId, shell, doc };
}

const { byId, shell, doc } = makeDom();
const requests = [];
const clawPayloads = [];
const jsonResponse = (status, obj) => ({ ok: status >= 200 && status < 300, status, json: async () => obj });
async function fetchImpl(url, opts) {
  opts = opts || {};
  requests.push({ url: String(url), method: (opts.method || "GET").toUpperCase() });
  const u = String(url);
  if (u.startsWith("/api/claw/general/capabilities")) {
    return jsonResponse(200, { live_events_available: false });
  }
  if (u.startsWith("/api/claw/general")) {
    const sent = typeof opts.body === "string" ? JSON.parse(opts.body) : {};
    clawPayloads.push(sent);
    return sseResponse("claw answer", sent.conversation_id);
  }
  if (u.startsWith("/api/auth/status")) return jsonResponse(200, { ready: true, authenticated: false, user: null, history_ready: false, project_files_ready: false, methods: { password: true, google: false } });
  if (u.startsWith("/api/projects")) return jsonResponse(200, { projects: [] });
  if (u.startsWith("/api/conversations")) return jsonResponse(200, { conversations: [] });
  return jsonResponse(200, {});
}

const sseResponse = (answer, conversationId) => {
  const text = "event: delta\ndata: " + JSON.stringify({ delta: answer }) + "\n\n"
    + "event: done\ndata: " + JSON.stringify({ done: true, conversation_id: conversationId || "conv_new" }) + "\n\n";
  return {
    ok: true, status: 200,
    headers: { get: () => "text/event-stream" },
    body: {
      getReader() {
        let sent = false;
        return {
          read: async () => (sent ? { done: true } : (sent = true, { done: false, value: new TextEncoder().encode(text) })),
          cancel: async () => {},
          releaseLock() {},
        };
      },
    },
    json: async () => ({}),
  };
};

const sandbox = {
  document: doc, fetch: fetchImpl,
  AbortController: class { constructor() { this.signal = {}; } abort() {} },
  URL: { createObjectURL: () => "blob:x", revokeObjectURL() {}, revokeURL() {} },
  setTimeout, clearTimeout, setInterval, clearInterval, console,
  TextEncoder, TextDecoder,
  CustomEvent: class {},
  location: { href: "http://localhost/", assign() {} },
  addEventListener() {},
  __padiemLocale: { text: (k) => k },
  PadiemChatLifecycle: { states: { IDLE: "idle", STREAMING: "streaming", COMPLETED: "completed", FAILED: "failed", CANCELLED: "cancelled", TIMED_OUT: "timed_out" }, set() {}, recordTaskEvent() {}, renderTaskStatus() {}, releasePreparingRuntimeLabel() {}, applyRuntimeLabel() {} },
  PadiemConfirmDialog: { confirm: async () => true },
  PadiemChatTransport: {
    createCalendarTurnId: () => "turn-1",
    createChatPcRunId: () => null,
    requestCompleted: async () => ({}),
    requestStreaming: async () => sseResponse("streamed answer"),
    readSseEvents: null,
    errorFor: () => new Error("x"),
  },
  PadiemAttachmentCapabilities: {
    limits: { imageBytes: 4194304, textBytes: 98304, textChars: 40000 },
    images: [{ mediaTypes: ["image/jpeg", "image/png", "image/webp"] }],
    textDocuments: [{ mediaTypes: ["text/plain"], extensions: [".txt"] }],
    copy: () => ({ idleNote: "idle", unsupportedFormat: "unsupported", textTooLarge: "too large" }),
  },
  PadiemBinaryDocuments: null,
};
sandbox.window = sandbox;
const TRANSPORT = fs.readFileSync(process.argv[4], "utf8");
vm.createContext(sandbox);
vm.runInContext(STATE, sandbox, { filename: "conversation-state.js" });
vm.runInContext(TRANSPORT, sandbox, { filename: "chat-transport.js" });
sandbox.PadiemChatTransport.readSseEvents = sandbox.PadiemChatTransport.readSseEvents;
vm.runInContext(APP, sandbox, { filename: "app.js" });

(async () => {
  const checks = {};
  const fail = (m) => { console.log(JSON.stringify({ ok: false, error: m, checks })); process.exit(1); };

  // A conversation already exists (started on either screen).
  const state = sandbox.PadiemChatConversationState;
  const CONV = "conv_" + "a".repeat(32);
  state.setProduct("chat");
  state.setConversationId(CONV);
  const chatTurn = doc.createElement("article");
  chatTurn.className = "message user-message";
  byId.messageList.appendChild(chatTurn);
  checks.CHAT_TURN_VISIBLE = byId.messageList.children.indexOf(chatTurn) >= 0;

  // Opening Claw keeps the same turn and the same conversation.
  byId.clawNavButton.click();
  checks.CLAW_STATE = shell.dataset.state === "claw";
  checks.CHAT_TURN_STILL_VISIBLE = byId.messageList.children.indexOf(chatTurn) >= 0;
  checks.SAME_ID_ON_CLAW = state.getConversationId("claw") === CONV;

  // A Claw submit continues that conversation id.
  byId.messageInput.value = "이 대화 이어서 계속해 줘";
  byId.composerForm.requestSubmit();
  await new Promise((resolve) => setTimeout(resolve, 300));
  checks.CLAW_SUBMIT_CARRIED_ID = clawPayloads.length === 1
    && clawPayloads[0].conversation_id === CONV
    && !clawPayloads[0].pc_run_id;
  checks.CLAW_TURN_RENDERED = byId.messageList.children.length > 1;

  // Returning to Chat keeps everything: same transcript, same id.
  byId.newChatButton.click();
  checks.CHAT_STATE = shell.dataset.state === "chat";
  checks.CHAT_TURN_STILL_THERE = byId.messageList.children.indexOf(chatTurn) >= 0;
  checks.SAME_ID_IN_CHAT = state.getConversationId("chat") === CONV;

  const failed = Object.entries(checks).filter(([, ok]) => !ok).map(([k]) => k);
  if (failed.length) fail("failed checks: " + failed.join(", "));
  console.log(JSON.stringify({ ok: true, checks, sent: clawPayloads }));
})();
"""


def _run_harness() -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        harness = Path(tmp) / "harness.js"
        harness.write_text(_HARNESS, encoding="utf-8")
        transport = ROOT / "static/chat-transport.js"
        completed = subprocess.run(
            ["node", str(harness), str(APP_JS), str(STATE_JS), str(transport)],
            capture_output=True,
            text=True,
        )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    return json.loads(completed.stdout)


def test_switching_screens_keeps_the_thread_and_continues_it() -> None:
    result = _run_harness()
    assert result["ok"] is True, result
    checks = result["checks"]
    assert checks["CHAT_TURN_VISIBLE"] is True
    assert checks["CLAW_STATE"] is True
    # The reversal: Claw shows the SAME thread instead of hiding it.
    assert checks["CHAT_TURN_STILL_VISIBLE"] is True
    assert checks["SAME_ID_ON_CLAW"] is True
    # The Claw submit is the same conversation, on the Claw lane.
    assert checks["CLAW_SUBMIT_CARRIED_ID"] is True
    assert checks["CLAW_TURN_RENDERED"] is True
    # Coming back keeps the thread and the id.
    assert checks["CHAT_STATE"] is True
    assert checks["CHAT_TURN_STILL_THERE"] is True
    assert checks["SAME_ID_IN_CHAT"] is True


# ── server: one stored record, appended from both lanes ──────────────────────


SIGNED_IN_USER_ID = "usr_" + "9" * 32


class _InMemoryConversations:
    """The D1 conversation contract both lanes address, without D1.

    `get_conversation` answers only for the signed-in owner and the one
    `b62-chat` scope, which is the whole cross-lane contract: a thread created
    by one lane is readable and appendable by the other.
    """

    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}
        self.appends: list[tuple[str, str]] = []

    async def get_user(self, user_id):
        return None

    async def get_conversation(self, user_id, conversation_id, *, product_scope: str):
        assert product_scope == PRODUCT_SCOPE_CHAT
        if user_id != SIGNED_IN_USER_ID:
            return None
        return self.rows.get(conversation_id)

    async def append_exchange(self, user_id, conversation_id, user_text, assistant_text,
                              project_id=None, *, product_scope: str,
                              assistant_message_id=None):
        assert product_scope == PRODUCT_SCOPE_CHAT
        assert user_id == SIGNED_IN_USER_ID
        if conversation_id is None:
            conversation_id = "chat_" + uuid.uuid4().hex
        row = self.rows.setdefault(
            conversation_id, {"id": conversation_id, "project_id": project_id, "messages": []}
        )
        row["messages"].extend([
            {"role": "user", "content": user_text},
            {"role": "assistant", "content": assistant_text},
        ])
        self.appends.append((conversation_id, user_text))
        return conversation_id

    async def record_claw_run(self, **kwargs):
        return None


class _ClawAdapter:
    # The canonical B54 session lane is what authorizes continuing a stored
    # conversation; it is resolved server-side and patched in `_client`.
    subject_identity_lane = True

    def __init__(self) -> None:
        self.calls = []
        self.runs = []

    async def execute(self, run, **kwargs):
        self.calls.append(kwargs)
        self.runs.append(run)

        class _Projection:
            status = type("S", (), {"value": "completed"})()
            run_id = "run_continuity"

        class _Outcome:
            projection = _Projection()
            answer = "Claw가 이전 대화를 이어서 답했습니다."
            p01_run_id = "p01_continuity"
            p01_event_count = 1

        return _Outcome()


def _bridge() -> SimpleNamespace:
    """The canonical B54 session the route resolves server-side."""
    return SimpleNamespace(
        auth_session=SimpleNamespace(
            subject=SimpleNamespace(subject_id="sub_" + "a" * 32),
            tenant_id="tenant_2505_continuity",
            session_id="sess_2505_continuity",
        )
    )


def _settings() -> Settings:
    return Settings.from_values(
        runtime_mode="mock",
        auth_mode="google",
        public_base_url="https://chat.example.test",
        google_client_id="continuity-test.apps.googleusercontent.com",
        google_client_secret="synthetic-not-real",
        session_secret="synthetic-secret-for-tests-only-not-real",
        session_max_age_seconds=3600,
    )


@contextmanager
def _client(store, adapter):
    settings = _settings()
    app = create_app(settings=settings, history_store=store, claw_p01_adapter=adapter)
    client = TestClient(app, base_url="https://chat.example.test")
    client.cookies.set(
        SESSION_COOKIE,
        create_session_token(settings, SIGNED_IN_USER_ID),
        domain="chat.example.test",
        path="/",
    )
    with client, patch(
        "app.b54_canonical_session.resolve_current_b54_canonical_session",
        new=AsyncMock(return_value=_bridge()),
    ):
        yield client


def test_a_chat_conversation_is_continued_on_the_claw_lane() -> None:
    store = _InMemoryConversations()
    adapter = _ClawAdapter()
    with _client(store, adapter) as client:
        first = client.post(
            "/api/chat",
            json={"messages": [{"role": "user", "content": "첫 질문입니다"}], "tier": "free"},
        )
        assert first.status_code == 200, first.text
        conversation_id = first.json()["conversation_id"]

        second = client.post(
            "/api/claw/general",
            json={
                "messages": [{"role": "user", "content": "이 대화 이어서 계속해 줘"}],
                "conversation_id": conversation_id,
            },
        )
    assert second.status_code == 200, second.text
    # One stored record, appended twice.
    assert set(store.rows) == {conversation_id}
    assert [row[0] for row in store.appends] == [conversation_id, conversation_id]
    # The Claw lane read the SAME thread: the Chat turn is part of the text the
    # Engine receives, built from the owner record rather than the browser.
    assert adapter.runs, "the Claw lane must dispatch to the Engine"
    task = adapter.runs[0].intent.task
    assert "첫 질문입니다" in task
    assert "이 대화 이어서 계속해 줘" in task


def test_a_claw_conversation_is_continued_on_the_chat_lane() -> None:
    store = _InMemoryConversations()
    adapter = _ClawAdapter()
    with _client(store, adapter) as client:
        first = client.post(
            "/api/claw/general",
            json={"messages": [{"role": "user", "content": "Claw에서 시작한 질문"}]},
        )
        assert first.status_code == 200, first.text
        conversation_id = json.loads(
            first.text.split("event: done\ndata: ", 1)[1].strip()
        )["conversation_id"]

        second = client.post(
            "/api/chat",
            json={
                "messages": [{"role": "user", "content": "채팅에서 이어서 물어봅니다"}],
                "tier": "free",
                "conversation_id": conversation_id,
            },
        )
    assert second.status_code == 200, second.text
    assert set(store.rows) == {conversation_id}
    assert [row[0] for row in store.appends] == [conversation_id, conversation_id]
    assert second.json()["conversation_id"] == conversation_id
    # The Chat turn was stored in the same record the Claw lane created.
    assert [m["content"] for m in store.rows[conversation_id]["messages"]][2] == (
        "채팅에서 이어서 물어봅니다"
    )
