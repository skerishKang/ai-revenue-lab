"""Chat/Claw separation Chat(B62) / Claw(B54) conversation separation.

Chat and Claw share one conversation panel, but they must never share one
conversation:

* entering Claw must not render the Chat turns,
* returning to Chat must restore the Chat turns,
* a conversation id created by one product must never be sent on the other
  product's request,
* nothing on the server is deleted: the stored conversation records stay.

The proof is a real behavioural run of the shipped ``app.js`` against a
synthetic DOM shim (same Element API as the #4488 harness), plus a direct
run of ``conversation-state.js`` for the per-product slot contract.

The server keeps the single ``b62-chat`` product scope on purpose: the
separation is carried by distinct conversation ids, so no D1 migration and no
scope change is needed.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

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


def test_the_two_products_have_their_own_conversation_slot() -> None:
    state = STATE_JS.read_text(encoding="utf-8")
    assert 'const PRODUCT_IDS = Object.freeze(["chat", "claw"]);' in state
    assert "function resetProduct(product)" in state
    assert "function setProduct(product)" in state
    assert "function getProduct()" in state
    # The plain API keeps working on the active product, so every existing
    # call site stays valid.
    assert "function reset()" in state
    assert "function appendMessage(message, product)" in state
    assert "function outboundWithUser(content, product)" in state
    assert "function commitAssistant(outboundMessages, content, product)" in state
    assert "function getConversationId(product)" in state
    assert "function setConversationId(value, product)" in state
    # No DOM, no network, no model in the turn store.
    for forbidden in ("document.", "fetch(", "AbortController"):
        assert forbidden not in state, forbidden


def test_the_panel_shows_one_product_at_a_time() -> None:
    app = _app_source()
    assert 'const PRODUCT_CHAT = "chat";' in app
    assert 'const PRODUCT_CLAW = "claw";' in app
    assert "function switchConversationProduct(nextProduct)" in app
    switch = _function_body(app, "switchConversationProduct")
    # The current product's turns are parked, not deleted.
    assert "parkProductTurns();" in switch
    assert "restoreProductTurns(target);" in switch
    # The other product's conversation id is never handed to this product.
    assert "conversationState.setProduct?.(target);" in switch
    assert "const hasTurns = messageList.children.length > 0;" in switch
    # The Claw artifact index belongs to the Claw conversation only.
    assert "conversationArtifactContext?.clear?.();" in switch


def test_entering_claw_never_renders_the_chat_turns() -> None:
    app = _app_source()
    general = _function_body(app, "openClawWorkspace")
    assert "switchConversationProduct(PRODUCT_CLAW);" in general
    manual = _function_body(app, "openClawManual")
    assert "switchConversationProduct(PRODUCT_CLAW);" in manual
    # A Chat send shows the Chat conversation.
    show = _function_body(app, "showConversation")
    assert "switchConversationProduct(PRODUCT_CHAT);" in show


def test_a_request_carries_its_own_products_conversation_id() -> None:
    app = _app_source()
    submit = app[app.index("async function submitPrompt("):]
    submit = submit[: submit.index("\n  }")]
    # The lane decides the product, and the id is read from that slot.
    assert "const product = clawGeneralRequest ? PRODUCT_CLAW : PRODUCT_CHAT;" in submit
    assert "conversationState.getConversationId(product)" in submit
    assert "conversationState.setProduct?.(product);" in submit
    # A completion belongs to the product that submitted it.
    assert "conversationState.setProduct?.(contextSnapshot.product);" in app
    # The Claw run result keeps its own Claw conversation.
    assert "conversationState.setConversationId(result.conversation_id, PRODUCT_CLAW);" in app


def test_the_server_keeps_one_product_scope() -> None:
    """The separation is carried by distinct conversation ids.

    ``b62-chat`` stays the shared scope for Chat and Claw, so no D1 migration
    and no schema change is introduced by this fix.
    """
    history = HISTORY_PY.read_text(encoding="utf-8")
    assert 'PRODUCT_SCOPE_CHAT = "b62-chat"' in history
    assert 'KNOWN_PRODUCT_SCOPES = frozenset({PRODUCT_SCOPE_CHAT, PRODUCT_SCOPE_B66})' in history
    assert "PRODUCT_SCOPE_CLAW" not in history


def test_the_chat_entry_restores_the_chat_conversation_from_claw() -> None:
    app = _app_source()
    reset = _function_body(app, "resetConversation")
    assert "switchConversationProduct(PRODUCT_CHAT);" in reset
    assert 'shell.dataset.state = "chat";' in reset
    # Inside the Chat state the same entry still starts a new conversation.
    assert "resetConversationView(preserveProject);" in reset
    # Every other caller resets the view directly, so a sign-out, a project
    # change or a delete always clears the conversation.
    for caller in ("selectProject", "exitProject"):
        assert "resetConversationView(" in _function_body(app, caller)
    assert "resetConversationView(true);" in app


# ── behavioural proof: the real conversation-state.js ─────────────────────────


def test_each_product_keeps_its_own_conversation_id_and_turns() -> None:
    script = f"""
    global.window = {{}};
    require({json.dumps(str(STATE_JS))});
    const state = window.PadiemChatConversationState;
    state.setProduct("chat");
    state.setConversationId("chat_a");
    state.appendMessage({{ role: "user", content: "chat turn" }});
    const chatOutbound = state.outboundWithUser("chat question");
    state.setProduct("claw");
    const clawIdBefore = state.getConversationId();
    const clawOutbound = state.outboundWithUser("claw question");
    state.setConversationId("claw_b");
    state.appendMessage({{ role: "user", content: "claw turn" }});
    const chatIdAfter = state.getConversationId("chat");
    const chatTurns = state.outboundWithUser("chat again", "chat");
state.setProduct("chat");
    const chatTurnsActive = state.outboundWithUser("chat again");
    process.stdout.write(JSON.stringify({{
      clawIdBefore,
      chatIdAfter,
      clawOutboundLength: clawOutbound.length,
      chatOutboundLength: chatOutbound.length,
      chatTurnsLength: chatTurns.length,
      chatTurnsActiveLength: chatTurnsActive.length,
      clawOutboundHasChatTurn: clawOutbound.some((m) => m.content === "chat turn"),
      chatOutboundHasClawTurn: chatOutbound.some((m) => m.content === "claw turn"),
      activeProduct: state.getProduct(),
    }}));
    """
    completed = subprocess.run(
        ["node", "-e", script], check=True, capture_output=True, text=True
    )
    data = json.loads(completed.stdout)
    # The Claw product starts without the Chat conversation id.
    assert data["clawIdBefore"] is None
    # The Chat conversation id survives a visit to Claw.
    assert data["chatIdAfter"] == "chat_a"
    # Each product's outbound history contains only its own turns.
    assert data["clawOutboundLength"] == 1
    assert data["chatOutboundLength"] == 2
    assert data["chatTurnsLength"] == 2
    assert data["chatTurnsActiveLength"] == 2
    assert data["clawOutboundHasChatTurn"] is False
    assert data["chatOutboundHasClawTurn"] is False
    assert data["activeProduct"] == "chat"


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
    hidden: false, disabled: false, open: false, value: "", children: [],
    listeners: {}, dataset: {}, style: {}, scrollTop: 0, scrollHeight: 0,
    clientHeight: 0, options: [], selectedIndex: 0, files: [], parentNode: null,
    classList: { add() {}, remove() {}, contains() { return false; }, toggle() {} },
  };
  el.setAttribute = (k, v) => {
    el[k] = String(v);
    if (k.startsWith("data-")) el.dataset[k.slice(5).replace(/-(\w)/g, (m, c) => c.toUpperCase())] = String(v);
  };
  el.getAttribute = (k) => (k in el ? el[k] : null);
  el.removeAttribute = (k) => { delete el[k]; };
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
  el.querySelector = (sel) => el.children.find((c) => c.className && c.className.includes(sel.replace(/^\./, ""))) || null;
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
    "passwordLoginError","passwordLoginSubmit","googleLoginButton",
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
    getElementById: (id) => byId[id] || null,
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
const jsonResponse = (status, obj) => ({ ok: status >= 200 && status < 300, status, json: async () => obj });
async function fetchImpl(url, opts) {
  opts = opts || {};
  requests.push({ url: String(url), method: (opts.method || "GET").toUpperCase(), body: opts.body ? JSON.parse(opts.body) : null });
  const u = String(url);
  if (u.startsWith("/api/auth/status")) return jsonResponse(200, { ready: true, authenticated: false, user: null, history_ready: false, project_files_ready: false, methods: { password: true, google: false } });
  if (u.startsWith("/api/projects")) return jsonResponse(200, { projects: [] });
  if (u.startsWith("/api/conversations")) return jsonResponse(200, { conversations: [] });
  return jsonResponse(200, {});
}

const sandbox = {
  document: doc, fetch: fetchImpl,
  AbortController: class { constructor() { this.signal = {}; } abort() {} },
  URL: { createObjectURL: () => "blob:x", revokeObjectURL() {}, revokeURL() {} },
  setTimeout, clearTimeout, setInterval, clearInterval, console,
  CustomEvent: class {},
  location: { href: "http://localhost/", assign() {} },
  addEventListener() {},
  __padiemLocale: { text: (k) => k },
  PadiemChatLifecycle: { states: { IDLE: "idle", STREAMING: "streaming", COMPLETED: "completed", FAILED: "failed", CANCELLED: "cancelled", TIMED_OUT: "timed_out" }, set() {} },
  PadiemConfirmDialog: { confirm: async () => true },
  PadiemChatTransport: { requestCompleted: async () => ({}), requestStreaming: async () => ({}), readSseEvents: async () => {}, errorFor: () => new Error("x") },
  PadiemAttachmentCapabilities: {
    limits: { imageBytes: 4194304, textBytes: 98304, textChars: 40000 },
    images: [{ mediaTypes: ["image/jpeg", "image/png", "image/webp"] }],
    textDocuments: [{ mediaTypes: ["text/plain"], extensions: [".txt"] }],
    copy: () => ({ idleNote: "idle", unsupportedFormat: "unsupported", textTooLarge: "too large" }),
  },
  PadiemBinaryDocuments: null,
};
sandbox.window = sandbox;
vm.createContext(sandbox);
vm.runInContext(STATE, sandbox, { filename: "conversation-state.js" });
vm.runInContext(APP, sandbox, { filename: "app.js" });

const state = sandbox.PadiemChatConversationState;

(async () => {
  const checks = {};
  const fail = (m) => { console.log(JSON.stringify({ ok: false, error: m, checks })); process.exit(1); };

  // The Chat product owns a conversation.
  state.setProduct("chat");
  state.setConversationId("chat_" + "a".repeat(32));
  const chatTurn = doc.createElement("article");
  chatTurn.className = "message user-message";
  byId.messageList.appendChild(chatTurn);
  checks.CHAT_TURN_VISIBLE = byId.messageList.children.indexOf(chatTurn) >= 0;

  // Entering Claw parks the Chat turn: the Claw screen shows no Chat turn.
  byId.clawNavButton.click();
  checks.CLAW_STATE = shell.dataset.state === "claw";
  checks.CHAT_TURN_HIDDEN_IN_CLAW = byId.messageList.children.indexOf(chatTurn) < 0;
  checks.CHAT_ID_NOT_IN_CLAW = state.getConversationId("claw") === null;
  checks.CHAT_ID_KEPT = state.getConversationId("chat") === "chat_" + "a".repeat(32);

  // A Claw turn is rendered in the Claw product.
  const clawTurn = doc.createElement("article");
  clawTurn.className = "message user-message";
  byId.messageList.appendChild(clawTurn);
  checks.CLAW_TURN_VISIBLE = byId.messageList.children.indexOf(clawTurn) >= 0;

  // Returning to Chat restores the Chat turn and hides the Claw turn.
  byId.newChatButton.click();
  checks.CHAT_STATE_RESTORED = shell.dataset.state === "chat";
  checks.CHAT_TURN_RESTORED = byId.messageList.children.indexOf(chatTurn) >= 0;
  checks.CLAW_TURN_HIDDEN_IN_CHAT = byId.messageList.children.indexOf(clawTurn) < 0;

  // Neither product's conversation id is the other's.
  checks.IDS_SEPARATE = state.getConversationId("chat") !== state.getConversationId("claw");

  const failed = Object.entries(checks).filter(([, ok]) => !ok).map(([k]) => k);
  if (failed.length) fail("failed checks: " + failed.join(", "));
  console.log(JSON.stringify({ ok: true, checks }));
})();
"""


def test_entering_claw_hides_the_chat_turns_and_returning_restores_them() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        harness = Path(tmp) / "harness.js"
        harness.write_text(_HARNESS, encoding="utf-8")
        completed = subprocess.run(
            ["node", str(harness), str(APP_JS), str(STATE_JS)],
            capture_output=True,
            text=True,
        )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    result = json.loads(completed.stdout)
    assert result["ok"] is True, result
    checks = result["checks"]
    assert checks["CHAT_TURN_VISIBLE"] is True
    assert checks["CLAW_STATE"] is True
    assert checks["CHAT_TURN_HIDDEN_IN_CLAW"] is True
    assert checks["CHAT_ID_NOT_IN_CLAW"] is True
    assert checks["CHAT_ID_KEPT"] is True
    assert checks["CLAW_TURN_VISIBLE"] is True
    assert checks["CHAT_STATE_RESTORED"] is True
    assert checks["CHAT_TURN_RESTORED"] is True
    assert checks["CLAW_TURN_HIDDEN_IN_CHAT"] is True
    assert checks["IDS_SEPARATE"] is True
