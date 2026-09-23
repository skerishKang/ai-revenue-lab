"""#2916 Claw session-reopen UI contracts.

The Claw manual execute POST and the recent-run cards previously carried no
canonical conversation authority: execute never forwarded the active
``conversation_id``, and a run row whose server-validated
``session.conversation_id`` existed had no way to reopen that saved
conversation. This file guards the UI-only slice that closes both gaps while
keeping the existing owners as the single authority:

- execute forwards EXACTLY the active handle ``conversationState`` already
  owns (string, non-empty), and omits the field entirely when none is active;
  the browser never mints, guesses, or fabricates an id (BROWSER_MINTED=0);
- the execute success path reuses ONLY a server-echoed
  ``result.conversation_id`` to update the store — no echo, no write;
- a run card with a valid projected ``session.conversation_id`` renders one
  extra button whose click reuses the existing owner
  ``openSavedConversation(id)`` (single detail GET, no new route, no second
  session store);
- ``session: null`` / absent / malformed sessions render NO session action
  (RUN_HISTORY_NULL_SESSION_ACTION=0);
- the Chat conversation path (``setConversationId(data.conversation_id)``)
  and the B54 run-card static slice stay byte-compatible (regression=0).

Static string assertions alone do not prove behavior, so this file also runs
a Node harness that executes the REAL app.js against a minimal DOM shim, a
stateful conversation-state spy, and a recording fetch:

- CANONICAL_CONVERSATION_REUSED=PASS
- BROWSER_MINTED_CONVERSATION_ID=0
- CLAW_EXECUTE_ACTIVE_CONVERSATION_FORWARD=PASS
- CLAW_EXECUTE_NO_ACTIVE_CONVERSATION_OMITS_FIELD=PASS
- RUN_HISTORY_SESSION_ACTION=PASS
- RUN_HISTORY_NULL_SESSION_ACTION=0
- EXISTING_OPEN_SAVED_CONVERSATION_REUSED=PASS
- CHAT_CONVERSATION_REGRESSION=0

The slice is presentation-only: no route, store, schema, provider call, or
backend change; fail-closed backend behavior and Chat streaming stay untouched.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "static/app.js"
LOCALE_JS = ROOT / "static/locale.js"
INDEX_HTML = ROOT / "static/index.html"
COPY_TRUTHFUL = ROOT / "tests/test_b54_claw_run_history_copy_truthful.py"

SESSION_KEY = "claw-runs-open-session"
KO_TEXT = "세션 열기"
EN_TEXT = "Open session"


def _app_source() -> str:
    return APP_JS.read_text(encoding="utf-8")


def _locale_table() -> dict[str, dict[str, str]]:
    """Parse the shipped KO/EN copy out of locale.js (no local duplicate)."""
    source = LOCALE_JS.read_text(encoding="utf-8")
    pattern = re.compile(r'"([A-Za-z0-9_\-]+)":\s*"((?:[^"\\]|\\.)*)"')

    def unescape(value: str) -> str:
        out = value.replace('\\"', '"').replace("\\n", "\n").replace("\\t", "\t")
        return out.replace("\\\\", "\\")

    def pairs(block: str) -> dict[str, str]:
        return {key: unescape(value) for key, value in pattern.findall(block)}

    assert "en: {" in source
    ko_part, en_part = source.split("en: {", 1)
    table = {"ko": pairs(ko_part), "en": pairs(en_part)}
    assert table["ko"] and table["en"]
    return table


def _execute_body(app: str) -> str:
    body = app[app.index("async function runClawExecution()") :]
    return body[: body.index("if (clawExecuteButton) {")]


# ── static structural contracts: execute payload ───────────────────────────


def test_execute_payload_forwards_the_active_conversation_exactly_once() -> None:
    app = _app_source()
    body = _execute_body(app)
    # One read of the canonical store, one single payload object, one guarded
    # forward, one serialized body — never an inline object literal that could
    # drift from the guard.
    assert app.count("const activeConversationId = conversationState.getConversationId();") == 1
    assert app.count("const executePayload = {") == 1
    assert app.count("if (typeof activeConversationId === \"string\" && activeConversationId) {") == 1
    assert app.count("executePayload.conversation_id = activeConversationId;") == 1
    assert app.count("body: JSON.stringify(executePayload),") == 1
    # The forward lives inside the single execute entry point, between the
    # sender read and the dispatch.
    assert "const activeConversationId = conversationState.getConversationId();" in body
    assert "executePayload.conversation_id = activeConversationId;" in body
    assert "body: JSON.stringify(executePayload)," in body
    # Payload construction sits after the body guard and before dispatch.
    guard_at = body.index("if (clawRetryRemaining() > 0) return;")
    body_check_at = body.index("if (!body) {")
    payload_at = body.index("const executePayload = {")
    wait_at = body.index("beginClawWait();")
    assert guard_at < body_check_at < payload_at < wait_at
    # Base fields keep their legacy shape so omitting conversation_id leaves
    # byte-identical legacy payloads for consumers that predate this issue.
    for field in (
        "content: body,",
        "channel: channelValue,",
        "action: actionValue,",
        "sender_hint: senderText || null,",
        "tier: selectedProductTier(),",
    ):
        assert field in body, field


def test_execute_omits_the_field_without_an_active_conversation() -> None:
    """The omit path must be structural: no empty-string sentinel, no null field."""
    app = _app_source()
    body = _execute_body(app)
    # Assignment happens only inside the non-empty-string guard — there is no
    # unconditional `conversation_id:` key in the base payload.
    base = body[body.index("const executePayload = {") : body.index("if (typeof activeConversationId")]
    assert "conversation_id" not in base
    assert "executePayload.conversation_id = activeConversationId;" in body


def test_preview_path_stays_free_of_conversation_authority() -> None:
    app = _app_source()
    assert app.count('"/api/claw/manual-intake/preview"') == 1
    assert app.count('fetch("/api/claw/manual-intake/preview"') == 1
    at = app.index('"/api/claw/manual-intake/preview"')
    preview_block = app[at : at + 700]
    assert "conversation_id" not in preview_block
    assert "executePayload" not in preview_block


# ── static structural contracts: success echo ──────────────────────────────


def test_success_echo_reuses_only_the_server_conversation_id() -> None:
    app = _app_source()
    body = _execute_body(app)
    # Exactly one gated write, driven by result.conversation_id only — no
    # fallback to the pre-request id, no local derivation.
    assert app.count("conversationState.setConversationId(result.conversation_id);") == 1
    assert (
        app.count('if (typeof result.conversation_id === "string" && result.conversation_id) {') == 1
    )
    echo_at = body.index("const result = data.result;")
    gate_at = body.index('if (typeof result.conversation_id === "string" && result.conversation_id) {')
    assert echo_at < gate_at
    # The write sits between the gate and the success reveal — never on the
    # error/failure branches below.
    reveal_at = body.index("revealClawCard(result.title, true);")
    assert gate_at < reveal_at


def test_chat_conversation_path_is_unchanged() -> None:
    """Regression=0: the Chat authority writes keep their exact call sites."""
    app = _app_source()
    assert app.count("conversationState.setConversationId(data.conversation_id);") == 2
    assert app.count("conversationState.setConversationId(retryContext.conversationId);") == 1
    # Chat still owns its streaming/completed echo; Claw gained a parallel
    # gated write without touching these.
    assert 'if (typeof data.conversation_id === "string") conversationState.setConversationId(data.conversation_id);' in app


def test_browser_never_mints_a_conversation_id() -> None:
    app = _app_source()
    for token in (
        "randomUUID",
        "Math.random",
        "crypto.",
        '"chat_"',
        "'chat_'",
        "sessionStorage",
        "localStorage",
        "XMLHttpRequest",
    ):
        assert token not in app, token


# ── static structural contracts: run-card session action ───────────────────


def test_session_action_reuses_open_saved_conversation() -> None:
    app = _app_source()
    # One call site, through the existing owner, keyed by the projected handle.
    assert app.count("openSavedConversation(sessionConversationId);") == 1
    assert app.count("async function openSavedConversation(") == 1
    assert app.count('clawT("claw-runs-open-session")') == 1
    assert (
        app.count(
            "const sessionConversationId = run.session && typeof run.session.conversation_id === \"string\" && run.session.conversation_id"
        )
        == 1
    )
    assert app.count("if (sessionBtn) card.appendChild(sessionBtn);") == 1
    # Button is created above the artifact marker and appended below it, so the
    # B54 static slice sees exactly one download button and no open token.
    create_at = app.index('sessionBtn = document.createElement("button");')
    marker_at = app.index('artifactRow.className = "claw-run-card-artifact";')
    append_at = app.index("if (sessionBtn) card.appendChild(sessionBtn);")
    assert create_at < marker_at < append_at
    # Malformed sessions collapse to null before any DOM work.
    guard_at = app.index(
        "const sessionConversationId = run.session && typeof run.session.conversation_id === \"string\" && run.session.conversation_id"
    )
    assert guard_at < create_at


def test_session_action_adds_no_new_route_or_second_store() -> None:
    app = _app_source()
    # The detail GET template keeps exactly its two pre-existing call sites
    # (history-row delete + openSavedConversation); the session action itself
    # contains no fetch at all.
    assert app.count("api/conversations/${encodeURIComponent(id)}") == 2
    create_at = app.index('sessionBtn = document.createElement("button");')
    append_at = app.index("if (sessionBtn) card.appendChild(sessionBtn);")
    session_block = app[create_at:append_at]
    assert "fetch(" not in session_block
    assert "/api/" not in session_block
    assert "sessionStorage" not in session_block and "localStorage" not in session_block
    assert "innerHTML" not in session_block


def test_session_action_stays_b54_static_slice_safe() -> None:
    """Defense in depth: the B54 historical-artifact contract must still hold."""
    app = _app_source()
    card_block = app.split("claw-run-card-artifact", 1)[1].split("function fetchClawRunHistory", 1)[0]
    assert card_block.count('createElement("button")') == 1
    assert "claw-run-card-download" in card_block
    assert not re.search(r"open|preview|reopen", card_block, re.IGNORECASE), card_block


# ── static structural contracts: copy and preserved anchors ────────────────


def test_locale_keys_are_declared_for_both_languages() -> None:
    table = _locale_table()
    assert table["ko"][SESSION_KEY] == KO_TEXT
    table_en = table["en"]
    assert table_en[SESSION_KEY] == EN_TEXT
    locale = LOCALE_JS.read_text(encoding="utf-8")
    ko_block, en_block = locale.split("en: {", 1)
    assert f'"{SESSION_KEY}": "{KO_TEXT}"' in ko_block
    assert f'"{SESSION_KEY}": "{EN_TEXT}"' in en_block


def test_shipped_copy_matches_the_no_locale_fallback() -> None:
    table = _locale_table()
    app = _app_source()
    fallback = [ln.strip() for ln in app.splitlines() if ln.strip().startswith(f'"{SESSION_KEY}":')]
    assert len(fallback) == 1
    assert fallback[0] == f'"{SESSION_KEY}": "{table["en"][SESSION_KEY]}",'
    # Runtime-resolved through clawT, never hardcoded Korean in app.js.
    assert f'clawT("{SESSION_KEY}")' in app
    for line_no, line in enumerate(app.splitlines(), start=1):
        assert not any("가" <= ch <= "힣" for ch in line), f"hardcoded Korean in app.js:{line_no}: {line.strip()}"


def test_b54_harness_exemption_is_pinned() -> None:
    """The scoped exemption is what keeps B54's open-claim scan green."""
    source = COPY_TRUTHFUL.read_text(encoding="utf-8")
    assert 'SESSION_OPEN_KEY = "claw-runs-open-session"' in source
    assert "key !== SESSION_OPEN_KEY" in source


def test_execute_entry_anchors_are_unchanged() -> None:
    app = _app_source()
    # Pre-existing dispatch/anchors this issue must not disturb.
    assert app.count("async function runClawExecution()") == 1
    assert app.count("void runClawExecution();") == 2
    assert app.count("beginClawWait();") == 1
    assert "// explicit retry only after the pre-dispatch cooldown" in app
    assert 'const senderText = (clawSender?.value || "").trim();' in app
    assert app.count('fetch("/api/claw/manual-intake/execute"') == 1
    assert "'tier: selectedProductTier()'" in app or "tier: selectedProductTier()," in app
    # The action is created in JS; index.html gains no new locale-bound node.
    html = INDEX_HTML.read_text(encoding="utf-8")
    assert f'data-locale-key="{SESSION_KEY}"' not in html


# ── behavioral proof via Node harness executing real app.js ────────────────

_HARNESS = r"""
const fs = require("fs");
const vm = require("vm");
const APP = fs.readFileSync(process.argv[2], "utf8");
// SHIPPED copy parsed from locale.js by the Python side — asserted text and
// rendered text are the same strings by construction.
const COPY = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));

function makeEl(tag) {
  const el = {
    tagName: tag, id: "", className: "", textContent: "", hidden: false,
    disabled: false, value: "", children: [], listeners: {}, dataset: {},
    style: {}, scrollTop: 0, scrollHeight: 0, clientHeight: 0,
    options: [], selectedIndex: 0, files: [], parentNode: null,
    classList: { add() {}, remove() {}, contains() { return false; }, toggle() {} },
  };
  el.setAttribute = (k, v) => { el[k] = String(v); if (k.startsWith("data-")) el.dataset[k.slice(5).replace(/-(\w)/g, (m, c) => c.toUpperCase())] = String(v); };
  el.getAttribute = (k) => (k in el ? el[k] : null);
  el.removeAttribute = (k) => { delete el[k]; };
  el.appendChild = (c) => { el.children.push(c); c.parentNode = el; return c; };
  el.prepend = (...cs) => cs.forEach((c) => { el.children.unshift(c); c.parentNode = el; });
  el.append = (...cs) => cs.forEach((c) => el.appendChild(c));
  el.replaceChildren = (...cs) => { el.children = []; cs.forEach((c) => el.appendChild(c)); };
  el.remove = () => { if (el.parentNode) el.parentNode.children = el.parentNode.children.filter((c) => c !== el); };
  el.addEventListener = (t, fn) => { (el.listeners[t] = el.listeners[t] || []).push(fn); };
  el.querySelector = (sel) => el.children.find((c) => c.className && c.className.includes(sel.replace(/^\./, ""))) || null;
  el.querySelectorAll = (sel) => (sel && sel.indexOf("claw-chip") >= 0 ? [] : el.children);
  el.focus = () => { doc.activeElement = el; };
  el.blur = () => { if (doc.activeElement === el) doc.activeElement = null; };
  el.scrollIntoView = () => {};
  el.click = () => (el.listeners.click || []).forEach((fn) => fn({ preventDefault() {}, target: el, key: "" }));
  el.requestSubmit = () => (el.listeners.submit || []).forEach((fn) => fn({ preventDefault() {} }));
  el.matches = () => false;
  return el;
}

const byId = {};
function add(id, tag) { const e = makeEl(tag); e.id = id; byId[id] = e; return e; }
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
  "clawManualForm","clawChannel","clawAction","clawSender","clawResultArea","clawResultPreview",
  "clawResultCard","clawResultEmpty","clawResultKind","clawGenerateBtn","clawExecuteButton","clawResultBadge",
  "clawResultDocx","clawStatus","clawWait","clawArtifactMeta","clawArtifactName","clawArtifactSize",
  "clawResultSuccessNote","clawResultHint","clawExecuteHint","clawApprovedMemory","clawApprovedRefresh",
  "clawApprovedLoading","clawApprovedError","clawApprovedList","clawApprovedEmpty","clawMemoryReview",
  "tasksNavButton","alertsNavButton","clawInbox","clawInboxTitle","clawInboxLoading","clawInboxError",
  "clawInboxEmpty","clawInboxList","clawInboxRetry","clawRunHistory","clawRunHistoryRefresh",
  "clawRunHistoryLoading","clawRunHistoryError","clawRunHistoryList","clawRunHistoryEmpty",
  "clawRetryHint","clawRetryBox","clawRetryCopy","clawRetryButton",
].forEach((id) => add(id, "div"));
byId.clawStatus.hidden = true;
byId.clawWait.hidden = true;
byId.clawRetryHint.hidden = true;
byId.clawRetryBox.hidden = true;
byId.clawRetryButton.disabled = true;
byId.clawResultCard.hidden = true;
byId.clawRunHistoryList.hidden = true;

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

// ── stateful conversation authority spy (#2916) ──
// Harness-planted fixtures: ACTIVE simulates an id the Chat path already
// stored earlier; ECHO and SID are server-side values our fixtures return.
// setCalls records ONLY app-initiated writes, so any value outside the
// fixture set is a browser mint.
const ACTIVE_ID = "conv_active_" + "1".repeat(12);
const ECHO_ID = "conv_echo_" + "7".repeat(12);
const SID = "conv_session_" + "9".repeat(12);
let activeId = null;
const setCalls = [];
const conversationState = {
  reset() { activeId = null; },
  setConversationId(v) { activeId = v; setCalls.push(v); },
  getConversationId() { return activeId; },
  appendMessage() {},
  outboundWithUser: () => [],
  commitAssistant() {},
  setSkill() {},
  getSkill: () => "auto",
};

const requests = [];
function jsonResponse(status, obj) {
  return { ok: status >= 200 && status < 300, status, json: async () => obj };
}

let authenticated = true;
let executeResult = { ok: true, result: { title: "quote", result_text: "ran", artifact: null } };
const ART_OK = "doc_" + "b".repeat(32);
const ART_NULL = "doc_" + "c".repeat(32);
const RUNS = [
  { run_id: "run_valid", channel: "kakao", action: "quote_draft", title: "[KAKAO] quote_draft",
    status: "completed", created_at: "2026-09-23T01:00:00Z", updated_at: "2026-09-23T01:00:00Z",
    result_summary: "valid summary",
    session: { conversation_id: SID },
    artifact: { document_id: ART_OK, filename: "quote.docx", media_type: "application/octet-stream" } },
  { run_id: "run_null_session", channel: "kakao", action: "quote_draft", title: "[KAKAO] null",
    status: "completed", created_at: "2026-09-23T01:01:00Z", updated_at: "2026-09-23T01:01:00Z",
    result_summary: "null session summary",
    session: null,
    artifact: { document_id: ART_NULL, filename: "other.docx", media_type: "application/octet-stream" } },
  { run_id: "run_absent_session", channel: "sms", action: "reply_draft", title: "[SMS] absent",
    status: "completed", created_at: "2026-09-23T01:02:00Z", updated_at: "2026-09-23T01:02:00Z",
    result_summary: "absent session summary",
    artifact: null },
  { run_id: "run_malformed_number", channel: "sms", action: "reply_draft", title: "[SMS] malformed number",
    status: "completed", created_at: "2026-09-23T01:03:00Z", updated_at: "2026-09-23T01:03:00Z",
    result_summary: "malformed number summary",
    session: { conversation_id: 123 },
    artifact: null },
  { run_id: "run_malformed_empty", channel: "sms", action: "reply_draft", title: "[SMS] malformed empty",
    status: "completed", created_at: "2026-09-23T01:04:00Z", updated_at: "2026-09-23T01:04:00Z",
    result_summary: "malformed empty summary",
    session: { conversation_id: "" },
    artifact: null },
  { run_id: "run_malformed_string", channel: "sms", action: "reply_draft", title: "[SMS] malformed string",
    status: "completed", created_at: "2026-09-23T01:05:00Z", updated_at: "2026-09-23T01:05:00Z",
    result_summary: "malformed string summary",
    session: "conv_raw_bypass",
    artifact: null },
];

async function fetchImpl(url, opts) {
  opts = opts || {};
  const method = (opts.method || "GET").toUpperCase();
  requests.push({ url: String(url), method, body: opts.body ? JSON.parse(opts.body) : null });
  const u = String(url);
  if (u.startsWith("/api/auth/status")) return jsonResponse(200, { ready: true, authenticated, user: { name: "owner" }, history_ready: false, project_files_ready: false });
  if (u.startsWith("/api/auth/logout")) return jsonResponse(200, { ok: true });
  if (u.startsWith("/api/projects")) return jsonResponse(200, { projects: [] });
  // Conversation DETAIL must be matched before the list prefix.
  if (u.startsWith("/api/conversations/")) {
    const id = decodeURIComponent(u.slice("/api/conversations/".length));
    return jsonResponse(200, { conversation: { id, messages: [], project_id: null, title: "saved" } });
  }
  if (u.startsWith("/api/conversations")) return jsonResponse(200, { conversations: [] });
  if (u.startsWith("/api/claw/inbox/")) return jsonResponse(200, { ok: true, kind: "tasks", items: [], limit: 20 });
  if (u.startsWith("/api/claw/memory")) return jsonResponse(200, { ok: true, memories: [] });
  if (u.startsWith("/api/claw/runs")) return jsonResponse(200, { ok: true, runs: RUNS });
  if (u.startsWith("/api/claw/manual-intake/execute")) return jsonResponse(200, executeResult);
  return jsonResponse(200, {});
}

let lang = "ko";
function localeText(key, variables) {
  const table = COPY[lang] || COPY.ko;
  const value = table[key] || COPY.ko[key] || key;
  if (!variables || typeof variables !== "object") return value;
  return Object.keys(variables).reduce((out, name) => out.split("{" + name + "}").join(String(variables[name])), value);
}

const sandbox = {
  document: doc,
  fetch: fetchImpl,
  AbortController: class { constructor() { this.signal = {}; } abort() {} },
  URL: { createObjectURL: () => "blob:x", revokeObjectURL() {}, revokeURL() {} },
  setTimeout, clearTimeout, setInterval, clearInterval, console,
  CustomEvent: class {},
  location: { href: "http://localhost/", assign() {} },
  addEventListener() {},
  __padiemLocale: { text: (k, v) => localeText(k, v) },
  PadiemChatLifecycle: { states: { IDLE: "idle", STREAMING: "streaming", COMPLETED: "completed", FAILED: "failed", CANCELLED: "cancelled", TIMED_OUT: "timed_out" }, set() {} },
  PadiemConfirmDialog: { confirm: async () => true },
  PadiemChatTransport: { requestCompleted: async () => ({}), requestStreaming: async () => ({}), readSseEvents: async () => {}, errorFor: () => new Error("x") },
  PadiemChatConversationState: conversationState,
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
vm.runInContext(APP, sandbox, { filename: "app.js" });

function collectButtons(root) {
  const out = [];
  const stack = [...(root.children || [])];
  while (stack.length) {
    const el = stack.shift();
    if (String(el.tagName).toUpperCase() === "BUTTON") out.push(el);
    stack.push(...(el.children || []));
  }
  return out;
}
function collectSessionButtons(root) {
  return collectButtons(root).filter((b) => String(b.className).indexOf("claw-run-card-session") >= 0);
}
function collectText(root) {
  let out = root.textContent || "";
  (root.children || []).forEach((c) => { out += " " + collectText(c); });
  return out;
}
function cardWith(summary) {
  return (byId.clawRunHistoryList.children || []).find((c) => collectText(c).indexOf(summary) >= 0) || null;
}

(async () => {
  const checks = {};
  const fail = (m) => { console.log(JSON.stringify({ ok: false, error: m, requests, checks, setCalls })); process.exit(0); };
  process.on("unhandledRejection", (e) => { console.log(JSON.stringify({ ok: false, error: "unhandledRejection " + String((e && e.stack) || e) })); process.exit(0); });
  process.on("uncaughtException", (e) => { console.log(JSON.stringify({ ok: false, error: "uncaughtException " + String((e && e.stack) || e) })); process.exit(0); });
  const tick = (ms) => new Promise((r) => setTimeout(r, ms));
  const execPosts = () => requests.filter((r) => r.url === "/api/claw/manual-intake/execute" && r.method === "POST");

  await tick(40);

  // Prior Chat state: an active conversation id already in the canonical store
  // (planted by the harness as fixture setup — not via setConversationId).
  activeId = ACTIVE_ID;

  // Open the Claw workspace: owner-scoped runs render once.
  byId.clawNavButton.click();
  await tick(60);
  if (shell.dataset.state !== "claw") fail("CLAW_WORKSPACE_OPEN");

  // ── execute 1: active conversation forwards exactly ──
  byId.messageInput.value = "A업체 견적 요청";
  executeResult = { ok: true, result: { title: "quote", result_text: "ran", artifact: null } };
  byId.clawExecuteButton.click();
  await tick(80);
  if (execPosts().length !== 1) fail("EXECUTE1_NOT_DISPATCHED");
  const body1 = execPosts()[0].body;
  checks.CLAW_EXECUTE_ACTIVE_CONVERSATION_FORWARD =
    !!body1 && body1.conversation_id === ACTIVE_ID;
  if (!checks.CLAW_EXECUTE_ACTIVE_CONVERSATION_FORWARD) {
    fail("CLAW_EXECUTE_ACTIVE_CONVERSATION_FORWARD: " + JSON.stringify(body1));
  }
  const keys1 = Object.keys(body1).sort();
  const expected1 = ["action", "channel", "content", "conversation_id", "sender_hint", "tier"];
  checks.EXECUTE_PAYLOAD_KEYS_EXACT =
    keys1.length === expected1.length && keys1.every((k, i) => k === expected1[i]);
  if (!checks.EXECUTE_PAYLOAD_KEYS_EXACT) fail("EXECUTE_PAYLOAD_KEYS_EXACT: " + JSON.stringify(keys1));
  // No server echo → the store must not be written.
  if (setCalls.length !== 0) fail("NO_ECHO_MUST_NOT_WRITE: " + JSON.stringify(setCalls));

  // ── execute 2: no active conversation → field omitted; echo reused ──
  conversationState.reset();
  if (activeId !== null) fail("RESET_FAILED");
  executeResult = { ok: true, result: { title: "quote", result_text: "ran2", artifact: null, conversation_id: ECHO_ID } };
  byId.clawExecuteButton.click();
  await tick(80);
  if (execPosts().length !== 2) fail("EXECUTE2_NOT_DISPATCHED");
  const body2 = execPosts()[1].body;
  checks.CLAW_EXECUTE_NO_ACTIVE_CONVERSATION_OMITS_FIELD =
    !!body2 && !Object.prototype.hasOwnProperty.call(body2, "conversation_id");
  if (!checks.CLAW_EXECUTE_NO_ACTIVE_CONVERSATION_OMITS_FIELD) {
    fail("CLAW_EXECUTE_NO_ACTIVE_CONVERSATION_OMITS_FIELD: " + JSON.stringify(body2));
  }
  checks.CANONICAL_CONVERSATION_REUSED =
    setCalls.length === 1 && setCalls[0] === ECHO_ID && activeId === ECHO_ID;
  if (!checks.CANONICAL_CONVERSATION_REUSED) {
    fail("CANONICAL_CONVERSATION_REUSED: " + JSON.stringify({ setCalls, activeId }));
  }

  // ── run history: exactly one session action, only on the valid projection ──
  const koOpen = COPY.ko["claw-runs-open-session"];
  const validCard = cardWith("valid summary");
  if (!validCard) fail("VALID_CARD_MISSING");
  const onValid = collectSessionButtons(validCard).length;
  const badSummaries = ["null session summary", "absent session summary", "malformed number summary", "malformed empty summary", "malformed string summary"];
  let stray = 0;
  for (const summary of badSummaries) {
    const card = cardWith(summary);
    if (!card) fail("CARD_MISSING: " + summary);
    stray += collectSessionButtons(card).length;
  }
  checks.RUN_HISTORY_NULL_SESSION_ACTION = stray;
  if (stray !== 0) fail("RUN_HISTORY_NULL_SESSION_ACTION: " + stray);
  const sessionButtons = collectSessionButtons(byId.clawRunHistoryList);
  checks.RUN_HISTORY_SESSION_ACTION =
    sessionButtons.length === 1 &&
    onValid === 1 &&
    sessionButtons[0].textContent === koOpen &&
    String(sessionButtons[0].className).indexOf("claw-run-card-session") >= 0 &&
    String(sessionButtons[0].className).indexOf("claw-run-card-download") >= 0;
  if (!checks.RUN_HISTORY_SESSION_ACTION) {
    fail("RUN_HISTORY_SESSION_ACTION: " + JSON.stringify({ total: sessionButtons.length, onValid, buttons: sessionButtons.map((b) => ({ t: b.textContent, c: b.className })) }));
  }
  // Document action coexists on the same card without merging.
  const validCardButtons = collectButtons(validCard);
  checks.SESSION_AND_DOCUMENT_ACTIONS_COEXIST =
    validCardButtons.filter((b) => String(b.className).indexOf("claw-run-card-session") >= 0).length === 1 &&
    validCardButtons.filter((b) => String(b.className).indexOf("claw-run-card-download") >= 0 && String(b.className).indexOf("claw-run-card-session") < 0).length === 1;
  if (!checks.SESSION_AND_DOCUMENT_ACTIONS_COEXIST) fail("SESSION_AND_DOCUMENT_ACTIONS_COEXIST");

  // ── click the session action: reuse openSavedConversation end to end ──
  const detailBefore = requests.filter((r) => r.method === "GET" && r.url === "/api/conversations/" + SID).length;
  sessionButtons[0].click();
  await tick(80);
  const detailGets = requests.filter((r) => r.method === "GET" && r.url === "/api/conversations/" + SID).length;
  const anyDetailGets = requests.filter((r) => r.url.indexOf("/api/conversations/") === 0 && r.method === "GET");
  checks.EXISTING_OPEN_SAVED_CONVERSATION_REUSED =
    detailBefore === 0 &&
    detailGets === 1 &&
    anyDetailGets.length === 1 &&
    shell.dataset.state === "chat" &&
    activeId === SID &&
    setCalls.length === 2 &&
    setCalls[1] === SID;
  if (!checks.EXISTING_OPEN_SAVED_CONVERSATION_REUSED) {
    fail("EXISTING_OPEN_SAVED_CONVERSATION_REUSED: " + JSON.stringify({ detailGets, detailGetsAll: anyDetailGets.map((r) => r.url), state: shell.dataset.state, activeId, setCalls }));
  }

  // ── browser-minted ids: every id the app touched came from our fixtures ──
  const bodyIds = execPosts().map((r) => (r.body && "conversation_id" in r.body ? r.body.conversation_id : undefined)).filter((v) => v !== undefined);
  const mintedBodies = bodyIds.filter((v) => v !== ACTIVE_ID);
  const mintedSets = setCalls.filter((v) => v !== ECHO_ID && v !== SID);
  checks.BROWSER_MINTED_CONVERSATION_ID = mintedBodies.length + mintedSets.length;
  if (checks.BROWSER_MINTED_CONVERSATION_ID !== 0) {
    fail("BROWSER_MINTED_CONVERSATION_ID: " + JSON.stringify({ bodyIds, setCalls }));
  }

  console.log(JSON.stringify({ ok: true, requests, checks, setCalls, activeId }));
  process.exit(0);
})().catch((e) => { console.log(JSON.stringify({ ok: false, error: String((e && e.stack) || e) })); process.exit(0); });
"""


def _run_harness() -> dict:
    node = shutil.which("node")
    assert node, "node runtime is required for the behavioral harness"
    harness_path = ROOT / "tests" / "_2916_claw_session_reopen_harness.js"
    copy_path = ROOT / "tests" / "_2916_claw_session_reopen_copy.json"
    harness_path.write_text(_HARNESS, encoding="utf-8")
    copy_path.write_text(json.dumps(_locale_table(), ensure_ascii=False), encoding="utf-8")
    try:
        result = subprocess.run(
            [node, str(harness_path), str(APP_JS), str(copy_path)],
            capture_output=True,
            text=True,
            timeout=120,
        )
    finally:
        harness_path.unlink(missing_ok=True)
        copy_path.unlink(missing_ok=True)
    assert result.returncode == 0, f"harness exited {result.returncode}: {result.stderr}"
    line = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else "{}"
    return json.loads(line)


def test_behavioral_harness_passes() -> None:
    payload = _run_harness()
    assert payload.get("ok") is True, f"behavioral harness failed: {payload}"


def test_behavioral_execute_conversation_authority() -> None:
    payload = _run_harness()
    assert payload.get("ok") is True, payload
    checks = payload["checks"]
    for name in (
        "CLAW_EXECUTE_ACTIVE_CONVERSATION_FORWARD",
        "CLAW_EXECUTE_NO_ACTIVE_CONVERSATION_OMITS_FIELD",
        "CANONICAL_CONVERSATION_REUSED",
        "EXECUTE_PAYLOAD_KEYS_EXACT",
    ):
        assert checks.get(name) is True, name
    # Server echo is the only store write from execute; no echo, no write.
    assert payload["setCalls"] and payload["setCalls"][0].startswith("conv_echo_")
    # Forwarded ids in request bodies match the planted active handle only.
    bodies = [r["body"] for r in payload["requests"] if r["url"].endswith("/execute") and r["method"] == "POST"]
    assert len(bodies) == 2
    forwarded = [b["conversation_id"] for b in bodies if b and "conversation_id" in b]
    assert forwarded == ["conv_active_" + "1" * 12], forwarded


def test_behavioral_run_history_session_action() -> None:
    payload = _run_harness()
    assert payload.get("ok") is True, payload
    checks = payload["checks"]
    assert checks.get("RUN_HISTORY_SESSION_ACTION") is True, checks
    assert checks.get("RUN_HISTORY_NULL_SESSION_ACTION") == 0, checks
    assert checks.get("SESSION_AND_DOCUMENT_ACTIONS_COEXIST") is True, checks
    # Rendered button text is the shipped KO copy, not a local duplicate.
    table = _locale_table()
    assert table["ko"]["claw-runs-open-session"] == "세션 열기"


def test_behavioral_open_saved_conversation_reused() -> None:
    payload = _run_harness()
    assert payload.get("ok") is True, payload
    checks = payload["checks"]
    assert checks.get("EXISTING_OPEN_SAVED_CONVERSATION_REUSED") is True, checks
    assert checks.get("BROWSER_MINTED_CONVERSATION_ID") == 0, checks
    # Exactly one detail GET, through the pre-existing owner template.
    detail = [r for r in payload["requests"] if r["method"] == "GET" and r["url"].startswith("/api/conversations/")]
    assert len(detail) == 1, detail
    sid = "conv_session_" + "9" * 12
    assert detail[0]["url"] == f"/api/conversations/{sid}"
    # The store ends on the server-validated handle the click requested.
    assert payload["setCalls"][-1] == sid


def test_behavioral_requests_stay_within_existing_authority() -> None:
    payload = _run_harness()
    assert payload.get("ok") is True, payload

    def norm(url: str) -> str:
        path = url.split("?")[0]
        if path.startswith("/api/conversations/"):
            return "/api/conversations/{id}"
        return path

    urls = {norm(r["url"]) for r in payload["requests"]}
    allowed = {
        "/api/auth/status",
        "/api/auth/logout",
        "/api/projects",
        "/api/conversations",
        "/api/conversations/{id}",
        "/api/claw/runs",
        "/api/claw/memory",
        "/api/claw/inbox/tasks",
        "/api/claw/manual-intake/execute",
    }
    assert urls <= allowed, urls - allowed
    execute_posts = [r for r in payload["requests"] if r["url"] == "/api/claw/manual-intake/execute"]
    assert execute_posts and all(r["method"] == "POST" for r in execute_posts)


if __name__ == "__main__":
    test_execute_payload_forwards_the_active_conversation_exactly_once()
    test_execute_omits_the_field_without_an_active_conversation()
    test_preview_path_stays_free_of_conversation_authority()
    test_success_echo_reuses_only_the_server_conversation_id()
    test_chat_conversation_path_is_unchanged()
    test_browser_never_mints_a_conversation_id()
    test_session_action_reuses_open_saved_conversation()
    test_session_action_adds_no_new_route_or_second_store()
    test_session_action_stays_b54_static_slice_safe()
    test_locale_keys_are_declared_for_both_languages()
    test_shipped_copy_matches_the_no_locale_fallback()
    test_b54_harness_exemption_is_pinned()
    test_execute_entry_anchors_are_unchanged()
    test_behavioral_harness_passes()
    test_behavioral_execute_conversation_authority()
    test_behavioral_run_history_session_action()
    test_behavioral_open_saved_conversation_reused()
    test_behavioral_requests_stay_within_existing_authority()
    print("CLAW_SESSION_REOPEN_UI_TESTS=PASS")
