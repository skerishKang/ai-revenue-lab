"""#4488 CLAW2 — synthetic-fixture, keyboard and accessibility state transitions.

Scope (CENTRAL handoff 2026-10-14): CLAW2 adds **additional verification in a
separate test file** for the Claw approval / approved-memory / re-login
surfaces. This file deliberately does **not** re-implement the already-passing
1440/1920/820/390 layout, Glass-theme or 44px touch-target coverage (see
``test_3933_claw_focus_ui_layout``, ``test_4488_claw_automation_touch_accessibility``)
and it does **not** create any real customer approval event. Every fixture
below is an explicitly synthetic, obviously-fake value; nothing here writes to
a store, provider, route or backend.

Why a separate file: ``test_4488_claw_disclosure_parity.py`` binds the *source
contract* of the two disclosure fixes, and ``test_claw_session_reopen_ui.py``
binds conversation-authority behaviour. Neither exercises the **state
machine** of the approval decision surface or the approved-memory surface
across an auth loss. That transition is what this file proves.

Three surfaces, each verified two ways — a static structural contract and a
real behavioural run of the shipped ``app.js`` against a DOM shim:

* **approval** (``#clawApprovalActions``): rendered pending controls, the
  single-flight decision guard, the busy/aria-disabled transition, the success
  and error terminal states, and the exact decision payload.
* **memory** (``#clawApprovedMemory`` / ``#clawApprovedDisclosure``): the
  authenticated-and-in-Claw visibility gate, the list/detail transitions, and
  the detail-open disclosure transition.
* **re-login**: what survives an auth loss. Every other session-scoped Claw
  surface (inbox, automation, run history, approved memory) is explicitly
  torn down in ``applyAuthState`` with a "#3237 / #4488 must not outlive the
  session" comment.
* **async session transition**: a decision POST begun before the logout whose
  response lands afterwards. Synchronous teardown cannot cover this — the
  response resolves into a *newer* session generation, and
  ``applyImmediateApprovalDecision`` mutates the DOM before its first await.
  The decision therefore captures a monotonic session generation and re-checks
  it after every await, mirroring the run-history visibility epoch.

The generated Node harness and its fixture are written to a private temporary
directory rather than to fixed paths in the source tree, so concurrent pytest
invocations, sharded runs and parallel worktrees cannot collide.

Keyboard access is asserted structurally where the browser owns the behaviour
(native ``<button>`` / ``<details>``+``<summary>`` elements, which are
focusable and Enter/Space-activatable by construction) rather than being
faked with ``div`` + click handlers.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "static/app.js"
INDEX_HTML = ROOT / "static/index.html"

# Obviously-synthetic fixtures. Never presented as, or derived from, a real
# customer approval.
SYNTHETIC_RUN_ID = "run_" + "5" * 24
SYNTHETIC_MEMORY_ID = "mem_" + "7" * 32
SYNTHETIC_MEMORY_NAME = "SYNTHETIC-FIXTURE-NOT-A-CUSTOMER-RECORD"


def _app_source() -> str:
    return APP_JS.read_text(encoding="utf-8")


def _html_source() -> str:
    return INDEX_HTML.read_text(encoding="utf-8")


def _logout_block(app: str) -> str:
    start = app.index("if (!authenticated) {")
    end = app.index("window.PadiemClawPdfPreview?.revokeAll?.()", start)
    return app[start:end]


def _approval_renderer(app: str) -> str:
    start = app.index("function renderClawApprovalControls")
    end = app.index("async function applyImmediateApprovalDecision", start)
    return app[start:end]


# ── static contracts: the approval decision surface ──────────────────────────


def test_approval_controls_are_real_buttons_for_keyboard_activation() -> None:
    """A decision surface must be operable by keyboard, not click-only.

    ``document.createElement("button")`` is focusable and Enter/Space-activated
    by the browser; a ``div`` with a click listener is not. The renderer must
    therefore create native buttons and type them explicitly.
    """
    body = _approval_renderer(_app_source())
    assert body.count('createElement("button")') == 2, "approve and deny must both be native buttons"
    assert body.count('type = "button"') == 2, "an untyped button inside a form submits it"
    assert 'createElement("div")' not in body
    # No inline on* handlers: activation stays with the native element.
    assert "onclick" not in body
    assert "tabindex" not in body.lower()


def test_the_approval_status_is_a_polite_live_region() -> None:
    """Screen readers must be told about pending/error without stealing focus."""
    body = _approval_renderer(_app_source())
    assert 'status.setAttribute("role", "status")' in body
    assert 'status.setAttribute("aria-live", "polite")' in body
    # It must start silent and only announce on an actual transition.
    assert "status.hidden = true" in body
    assert 'status.dataset.state = "pending"' in body
    assert 'status.dataset.state = "error"' in body
    # Success clears the announced state rather than leaving a stale message.
    assert "status.removeAttribute(\"data-state\")" in body


def test_the_approval_decision_is_single_flight() -> None:
    """A double click must not send two decisions for one run."""
    body = _approval_renderer(_app_source())
    assert "if (clawApprovalInFlight) return;" in body
    assert body.index("if (clawApprovalInFlight) return;") < body.index("clawApprovalInFlight = true;")
    # The flag is released on every terminal path.
    assert "finally {" in body and "clawApprovalInFlight = false;" in body


def test_the_approval_busy_state_is_exposed_to_assistive_tech() -> None:
    """``disabled`` alone is not reliably announced; ``aria-disabled`` is set too."""
    app = _app_source()
    start = app.index("function setApprovalControlsBusy")
    body = app[start : app.index("\n  }", start)]
    assert 'String(child.tagName || "").toUpperCase() === "BUTTON"' in body
    assert "child.disabled = busy;" in body
    assert 'child.setAttribute("aria-disabled", String(busy));' in body
    # Busy is applied on entry and released in the same finally block.
    renderer = _approval_renderer(app)
    assert "setApprovalControlsBusy(container, true);" in renderer
    assert "setApprovalControlsBusy(container, false);" in renderer


def test_the_approval_decision_payload_carries_only_server_run_id_and_decision() -> None:
    """The browser decides *what* to answer, never *which* run it answers for."""
    body = _approval_renderer(_app_source())
    assert '"POST"' in body
    assert '"claw/approvals/decision"' in body or "/api/claw/approvals/decision" in body
    assert "body: JSON.stringify({ run_id: runId, decision })" in body
    # No browser-minted identifier reaches the decision request.
    for token in ("randomUUID", "Math.random", "localStorage", "sessionStorage"):
        assert token not in body, token


def test_the_approval_surface_is_a_labelled_group() -> None:
    html = _html_source()
    assert 'id="clawApprovalActions" role="group"' in html
    assert 'data-locale-aria-label="claw-approval-actions-aria"' in html
    # The container ships hidden: no approval UI before a real pending run.
    assert re.search(r'id="clawApprovalActions"[^>]*hidden', html)


# ── static contracts: the approved-memory surface ────────────────────────────


def test_the_memory_disclosure_is_a_native_keyboard_disclosure() -> None:
    """``<details>``/``<summary>`` is the only keyboard-operable disclosure.

    A ``div`` toggled by a click listener would leave the surface unreachable
    by keyboard, and ``aria-expanded`` bookkeeping would have to be hand-rolled.
    """
    html = _html_source()
    start = html.index('id="clawApprovedDisclosure"')
    opening_tag = html[html.rindex("<", 0, start) : html.index(">", start) + 1]
    assert opening_tag.startswith("<details"), opening_tag
    assert "hidden" in opening_tag, "the disclosure must not be visible before an owner session"
    summary = html.index("<summary", start)
    assert html.index("</details>", summary) > summary
    # The caret is decorative and must not be announced.
    assert 'class="claw-disclosure-caret" aria-hidden="true"' in html
    # The disclosure must not contain the approval decision surface.
    end = html.index("</details>", start)
    assert "clawApprovalActions" not in html[start:end]


def test_the_memory_panel_is_labelled_by_its_own_heading() -> None:
    html = _html_source()
    assert 'id="clawApprovedMemory" aria-labelledby="clawApprovedMemoryTitle"' in html
    assert 'id="clawApprovedMemoryTitle"' in html
    # Async states are announced: loading is polite, failure is an alert.
    assert 'id="clawApprovedLoading"' in html and 'role="status" aria-live="polite"' in html
    assert re.search(r'id="clawApprovedError"[^>]*role="alert"', html)


def test_the_memory_visibility_gate_requires_an_owner_session_in_claw() -> None:
    """The panel is owner-gated: anonymous and non-Claw views never load it."""
    app = _app_source()
    start = app.index("function syncApprovedMemoryVisibility")
    body = app[start : app.index("\n  }", start)]
    assert "authState.authenticated === true" in body
    assert 'shell.dataset.state === "claw"' in body
    assert 'clawWorkspace?.dataset.view !== "inbox"' in body
    assert "clawApprovedMemory.hidden = !show;" in body
    assert "if (clawApprovedDisclosure) clawApprovedDisclosure.hidden = !show;" in body
    # Loading only ever happens behind the gate.
    assert "if (show) loadApprovedMemoryList();" in body


# ── behavioural proof: real app.js against a synthetic-fixture DOM shim ──────

_HARNESS = r"""
const fs = require("fs");
const vm = require("vm");
const APP = fs.readFileSync(process.argv[2], "utf8");
const FIX = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));

// Set by makeDom(); the element helpers below are created before the document
// exists but only ever dereference it when focus()/blur() are actually called.
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
    "clawManualForm","clawChannel","clawAction","clawSender","clawResultArea","clawResultPreview",
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
  // Shipped markup defaults this file depends on.
  byId.clawApprovedDisclosure.tagName = "DETAILS";
  byId.clawApprovedDisclosure.hidden = true;
  byId.clawApprovedMemory.hidden = true;
  byId.clawApprovedList.hidden = true;
  byId.clawApprovedError.hidden = true;
  byId.clawApprovalActions.hidden = true;
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
  DOC = doc;
  return { byId, shell, doc };
}

function makeConversationState() {
  let activeId = null;
  return {
    reset() { activeId = null; },
    setConversationId(v) { activeId = v; },
    getConversationId() { return activeId; },
    appendMessage() {}, outboundWithUser: () => [], commitAssistant() {},
    setSkill() {}, getSkill: () => "auto",
  };
}

function boot(state) {
  const { byId, shell, doc } = makeDom();
  const requests = [];
  const fixture = {
    authenticated: true,
    memories: [],
    memoryDetail: null,
    executeResult: { ok: true, result: { title: "quote", result_text: "ran", artifact: null } },
    decision: { ok: true, result: { run_id: FIX.runId, status: "completed", result_text: "approved" } },
    decisionPending: null,
  };
  const jsonResponse = (status, obj) => ({ ok: status >= 200 && status < 300, status, json: async () => obj });

  async function fetchImpl(url, opts) {
    opts = opts || {};
    const method = (opts.method || "GET").toUpperCase();
    requests.push({ url: String(url), method, body: opts.body ? JSON.parse(opts.body) : null });
    const u = String(url);
    if (u.startsWith("/api/auth/status")) return jsonResponse(200, { ready: true, authenticated: fixture.authenticated, user: { name: "owner" }, history_ready: false, project_files_ready: false, methods: { password: true, google: false } });
    if (u.startsWith("/api/auth/logout")) { fixture.authenticated = false; return jsonResponse(200, { ok: true }); }
    if (u.startsWith("/api/auth/password/login")) { fixture.authenticated = true; return jsonResponse(200, { ok: true, user: { name: "owner" } }); }
    if (u.startsWith("/api/projects")) return jsonResponse(200, { projects: [] });
    if (u.startsWith("/api/conversations/")) { const id = decodeURIComponent(u.slice("/api/conversations/".length)); return jsonResponse(200, { conversation: { id, messages: [], project_id: null, title: "saved" } }); }
    if (u.startsWith("/api/conversations")) return jsonResponse(200, { conversations: [] });
    if (u.startsWith("/api/claw/memory/")) return jsonResponse(200, { ok: true, memory: fixture.memoryDetail });
    if (u.startsWith("/api/claw/memory")) return jsonResponse(200, { ok: true, memories: fixture.memories });
    if (u.startsWith("/api/claw/approvals/decision")) {
      if (fixture.decisionPending) { await fixture.decisionPending; }
      return jsonResponse(200, fixture.decision);
    }
    if (u.startsWith("/api/claw/inbox/")) return jsonResponse(200, { ok: true, kind: "tasks", items: [], limit: 20 });
    if (u.startsWith("/api/claw/runs")) return jsonResponse(200, { ok: true, runs: [] });
    if (u.startsWith("/api/claw/manual-intake/execute")) return jsonResponse(200, fixture.executeResult);
    return jsonResponse(200, {});
  }

  const conversationState = makeConversationState();
  const sandbox = {
    document: doc, fetch: fetchImpl,
    AbortController: class { constructor() { this.signal = {}; } abort() {} },
    URL: { createObjectURL: () => "blob:x", revokeObjectURL() {}, revokeURL() {} },
    setTimeout, clearTimeout, setInterval, clearInterval, console,
    CustomEvent: class {},
    location: { href: "http://localhost/", assign() {} },
    addEventListener() {},
    __padiemLocale: { text: (k, v) => k },
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
  return { byId, shell, doc, requests, fixture, conversationState };
}

const tick = (ms) => new Promise((r) => setTimeout(r, ms));
// Buttons are frequently nested one level down (e.g. inside an actions row),
// so walk the subtree rather than only the direct children.
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
function buttonsOf(el) { return collectButtons(el); }
function approvalButtons(byId) { return collectButtons(byId.clawApprovalActions); }
function decisionPosts(requests) {
  return requests.filter((r) => r.method === "POST" && r.url === "/api/claw/approvals/decision");
}

(async () => {
  const checks = {};
  const fail = (m) => { console.log(JSON.stringify({ ok: false, error: m, checks })); process.exit(0); };
  process.on("unhandledRejection", (e) => { console.log(JSON.stringify({ ok: false, error: "unhandledRejection " + String((e && e.stack) || e) })); process.exit(0); });
  process.on("uncaughtException", (e) => { console.log(JSON.stringify({ ok: false, error: "uncaughtException " + String((e && e.stack) || e) })); process.exit(0); });

  // ── session A ──
  const A = boot();
  await tick(40);
  if (A.shell.dataset.state !== "home") fail("A_INITIAL_STATE: " + A.shell.dataset.state);

  // Approved-memory: owner session + Claw entry → panel and disclosure shown.
  A.fixture.memories = [{ memory_id: FIX.memoryId, memory_type: "preference", name: FIX.memoryName, note: "synthetic", status: "approved", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z" }];
  A.fixture.memoryDetail = { memory_id: FIX.memoryId, memory_type: "preference", name: FIX.memoryName, note: "synthetic", source_channel: "kakao", status: "approved", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z" };
  A.byId.clawNavButton.click();
  await tick(80);
  checks.MEMORY_PANEL_SHOWN_IN_CLAW =
    A.byId.clawApprovedMemory.hidden === false && A.byId.clawApprovedDisclosure.hidden === false;
  if (!checks.MEMORY_PANEL_SHOWN_IN_CLAW) fail("MEMORY_PANEL_SHOWN_IN_CLAW");
  const memoryCards = A.byId.clawApprovedList.children.filter((c) => String(c.className).indexOf("claw-approved-card") >= 0);
  checks.MEMORY_LIST_RENDERED = memoryCards.length === 1;
  if (!checks.MEMORY_LIST_RENDERED) fail("MEMORY_LIST_RENDERED");

  // Keyboard disclosure: a detail opens the wrapper (run-history focus parity).
  checks.MEMORY_DISCLOSURE_CLOSED_BEFORE = A.byId.clawApprovedDisclosure.open === false;
  if (!checks.MEMORY_DISCLOSURE_CLOSED_BEFORE) fail("MEMORY_DISCLOSURE_CLOSED_BEFORE");
  const detailBtn = buttonsOf(memoryCards[0]).find((b) => String(b.className).indexOf("claw-approved-action") >= 0);
  if (!detailBtn) fail("MEMORY_DETAIL_BUTTON_MISSING");
  detailBtn.click();
  await tick(80);
  checks.MEMORY_DETAIL_OPENS_DISCLOSURE =
    A.byId.clawApprovedDisclosure.open === true &&
    A.byId.clawApprovedList.children.some((c) => String(c.className).indexOf("claw-approved-detail") >= 0);
  if (!checks.MEMORY_DETAIL_OPENS_DISCLOSURE) fail("MEMORY_DETAIL_OPENS_DISCLOSURE");

  // ── approval: render, single-flight, terminal states ──
  A.fixture.executeResult = { ok: true, result: { title: "quote", status: "waiting_approval", approval_required: true, request_id: FIX.runId } };
  A.byId.messageInput.value = "SYNTHETIC approval fixture";
  A.byId.clawExecuteButton.click();
  await tick(80);
  const approve = approvalButtons(A.byId).find((b) => String(b.className).indexOf("claw-approval-approve") >= 0);
  const deny = approvalButtons(A.byId).find((b) => String(b.className).indexOf("claw-approval-deny") >= 0);
  checks.APPROVAL_CONTROLS_RENDERED =
    A.byId.clawApprovalActions.hidden === false && !!approve && !!deny;
  if (!checks.APPROVAL_CONTROLS_RENDERED) fail("APPROVAL_CONTROLS_RENDERED: " + JSON.stringify({ hidden: A.byId.clawApprovalActions.hidden, n: approvalButtons(A.byId).length }));
  const statusEl = A.byId.clawApprovalActions.children.find((c) => String(c.className).indexOf("claw-approval-status") >= 0);
  checks.APPROVAL_STATUS_SILENT_UNTIL_ACTION = !!statusEl && statusEl.hidden === true && statusEl.getAttribute("role") === "status";
  if (!checks.APPROVAL_STATUS_SILENT_UNTIL_ACTION) fail("APPROVAL_STATUS_SILENT_UNTIL_ACTION");

  // Hold the decision open so the in-flight state is observable, then double-click.
  let release = null;
  A.fixture.decisionPending = new Promise((r) => { release = r; });
  approve.click();
  approve.click();
  await tick(30);
  checks.APPROVAL_BUSY_DISABLES_BOTH = approve.disabled === true && deny.disabled === true &&
    approve.getAttribute("aria-disabled") === "true" && deny.getAttribute("aria-disabled") === "true";
  if (!checks.APPROVAL_BUSY_DISABLES_BOTH) fail("APPROVAL_BUSY_DISABLES_BOTH");
  checks.APPROVAL_SINGLE_FLIGHT = decisionPosts(A.requests).length === 1;
  if (!checks.APPROVAL_SINGLE_FLIGHT) fail("APPROVAL_SINGLE_FLIGHT: " + decisionPosts(A.requests).length);
  const post = decisionPosts(A.requests)[0];
  checks.APPROVAL_DECISION_PAYLOAD =
    !!post.body && post.body.run_id === FIX.runId && post.body.decision === "approve" &&
    Object.keys(post.body).sort().join(",") === "decision,run_id";
  if (!checks.APPROVAL_DECISION_PAYLOAD) fail("APPROVAL_DECISION_PAYLOAD: " + JSON.stringify(post.body));
  release();
  await tick(80);
  // A resolved decision clears the surface outright rather than leaving
  // detached, still-busy controls behind.
  checks.APPROVAL_SUCCESS_CLEARS_CONTROLS =
    A.byId.clawApprovalActions.hidden === true && A.byId.clawApprovalActions.children.length === 0;
  if (!checks.APPROVAL_SUCCESS_CLEARS_CONTROLS) fail("APPROVAL_SUCCESS_CLEARS_CONTROLS");

  // Re-arm a pending approval, then take the error branch.
  A.byId.clawExecuteButton.click();
  await tick(80);
  const approve2 = approvalButtons(A.byId).find((b) => String(b.className).indexOf("claw-approval-approve") >= 0);
  A.fixture.decision = { ok: false, error: { code: "approval_conflict" } };
  approve2.click();
  await tick(80);
  const statusEl2 = A.byId.clawApprovalActions.children.find((c) => String(c.className).indexOf("claw-approval-status") >= 0);
  checks.APPROVAL_ERROR_STATE = !!statusEl2 && statusEl2.hidden === false && statusEl2.dataset.state === "error";
  if (!checks.APPROVAL_ERROR_STATE) fail("APPROVAL_ERROR_STATE");
  // A failed decision keeps the controls so the owner can retry, and must
  // release the busy state (otherwise the surface is permanently disabled).
  const deny2 = approvalButtons(A.byId).find((b) => String(b.className).indexOf("claw-approval-deny") >= 0);
  checks.APPROVAL_BUSY_RELEASED_ON_ERROR =
    !!deny2 && approve2.disabled === false &&
    approve2.getAttribute("aria-disabled") === "false" && deny2.disabled === false;
  if (!checks.APPROVAL_BUSY_RELEASED_ON_ERROR) fail("APPROVAL_BUSY_RELEASED_ON_ERROR");

  // ── re-login: what survives an auth loss ──
  A.fixture.decision = { ok: true, result: { run_id: FIX.runId, status: "completed", result_text: "approved" } };
  A.byId.clawExecuteButton.click();
  await tick(80);
  checks.APPROVAL_PENDING_BEFORE_LOGOUT = A.byId.clawApprovalActions.hidden === false &&
    approvalButtons(A.byId).length === 2;
  if (!checks.APPROVAL_PENDING_BEFORE_LOGOUT) fail("APPROVAL_PENDING_BEFORE_LOGOUT");

  A.byId.loginButton.click();
  await tick(80);
  checks.LOGOUT_HIDES_WORKSPACE = A.shell.dataset.state === "home";
  if (!checks.LOGOUT_HIDES_WORKSPACE) fail("LOGOUT_HIDES_WORKSPACE: " + A.shell.dataset.state);
  checks.LOGOUT_CLEARS_MEMORY_SURFACE =
    A.byId.clawApprovedMemory.hidden === true &&
    A.byId.clawApprovedDisclosure.hidden === true &&
    A.byId.clawApprovedDisclosure.open === false &&
    A.byId.clawApprovedList.children.length === 0;
  if (!checks.LOGOUT_CLEARS_MEMORY_SURFACE) fail("LOGOUT_CLEARS_MEMORY_SURFACE");
  // The decision surface must not outlive the session either.
  checks.LOGOUT_CLEARS_PENDING_APPROVAL =
    A.byId.clawApprovalActions.hidden === true && A.byId.clawApprovalActions.children.length === 0;
  checks.APPROVAL_SURVIVING_CHILDREN = A.byId.clawApprovalActions.children.length;
  checks.APPROVAL_SURVIVING_HIDDEN = A.byId.clawApprovalActions.hidden;

  // A genuine in-page re-login: same SPA, same module state, new session
  // generation (no page reload, so nothing is reset by re-parsing the DOM).
  async function reLogin() {
    A.byId.passwordLoginIdentifier.value = "owner";
    A.byId.passwordLoginPassword.value = "synthetic-not-a-real-credential";
    A.byId.passwordLoginForm.requestSubmit();
    await tick(120);
  }

  await reLogin();
  A.byId.clawNavButton.click();
  await tick(80);
  checks.RELOGIN_STALE_APPROVAL_VISIBLE =
    A.byId.clawApprovalActions.hidden === false && approvalButtons(A.byId).length > 0;

  // ── async session transition: a decision that outlives its session ──
  // Start a decision, log out while the POST is still pending, then let the
  // previous session's response land. It must not repaint anything.
  async function staleDecisionCycle(lateResult) {
    await reLogin();
    A.byId.clawNavButton.click();
    await tick(60);
    A.fixture.decisionPending = null;
    A.fixture.decision = { ok: true, result: { run_id: FIX.runId, status: "waiting_approval", approval_required: true } };
    // Logout resets the conversation (and with it the composer), so the body
    // must be re-seeded before each dispatch.
    A.byId.messageInput.value = "SYNTHETIC stale-cycle request";
    A.byId.clawExecuteButton.click();
    await tick(80);
    const btn = approvalButtons(A.byId).find((b) => String(b.className).indexOf("claw-approval-approve") >= 0);
    if (!btn) {
      fail("STALE_CYCLE_APPROVE_MISSING " + JSON.stringify({
        shellState: A.shell.dataset.state,
        approvalsHidden: A.byId.clawApprovalActions.hidden,
        approvalsChildren: A.byId.clawApprovalActions.children.length,
        execPosts: A.requests.filter((r) => r.url === "/api/claw/manual-intake/execute").length,
        loginPosts: A.requests.filter((r) => r.url.indexOf("/api/auth/password/login") === 0).length,
        statusCalls: A.requests.filter((r) => r.url.indexOf("/api/auth/status") === 0).length,
        lastUrls: A.requests.slice(-6).map((r) => r.method + " " + r.url),
      }));
    }
    // Hold the decision open, then log out mid-flight.
    let release = null;
    A.fixture.decisionPending = new Promise((r) => { release = r; });
    A.fixture.decision = lateResult;
    const posts = decisionPosts(A.requests).length;
    btn.click();
    await tick(30);
    const dispatched = decisionPosts(A.requests).length === posts + 1;
    const busyWhilePending = btn.disabled === true;
    A.byId.loginButton.click();
    await tick(80);
    const previewAtLogout = A.byId.clawResultPreview.textContent;
    const areaStateAtLogout = A.byId.clawResultArea.dataset.clawState;
    const runsAtLogout = A.requests.filter((r) => r.url.indexOf("/api/claw/runs") === 0).length;
    const clearedAtLogout =
      A.byId.clawApprovalActions.hidden === true && A.byId.clawApprovalActions.children.length === 0;
    release();
    await tick(150);
    return {
      dispatched,
      busyWhilePending,
      clearedAtLogout,
      stayedHidden: A.byId.clawApprovalActions.hidden === true,
      children: A.byId.clawApprovalActions.children.length,
      previewBefore: previewAtLogout,
      previewAfter: A.byId.clawResultPreview.textContent,
      repainted:
        A.byId.clawResultPreview.textContent !== previewAtLogout ||
        A.byId.clawResultArea.dataset.clawState !== areaStateAtLogout,
      historyRefetched:
        A.requests.filter((r) => r.url.indexOf("/api/claw/runs") === 0).length !== runsAtLogout,
    };
  }

  const lateWaiting = await staleDecisionCycle({
    ok: true, result: { run_id: FIX.runId, status: "waiting_approval", approval_required: true },
  });
  checks.ASYNC_WAITING_DISPATCHED = lateWaiting.dispatched && lateWaiting.busyWhilePending;
  checks.ASYNC_WAITING_STAYS_HIDDEN =
    lateWaiting.clearedAtLogout && lateWaiting.stayedHidden && lateWaiting.children === 0;
  checks.ASYNC_WAITING_CHILDREN = lateWaiting.children;
  checks.ASYNC_WAITING_NO_REPAINT = !lateWaiting.repainted;
  checks.ASYNC_WAITING_NO_HISTORY_REFETCH = !lateWaiting.historyRefetched;

  const lateDone = await staleDecisionCycle({
    ok: true, result: { run_id: FIX.runId, status: "completed", result_text: "STALE-SESSION-RESULT-MUST-NOT-APPEAR" },
  });
  checks.ASYNC_COMPLETED_STAYS_HIDDEN =
    lateDone.clearedAtLogout && lateDone.stayedHidden && lateDone.children === 0;
  checks.ASYNC_COMPLETED_NO_REPAINT = !lateDone.repainted;
  checks.ASYNC_COMPLETED_PREVIEW_BEFORE = lateDone.previewBefore;
  checks.ASYNC_COMPLETED_PREVIEW_AFTER = lateDone.previewAfter;

  const lateError = await staleDecisionCycle({ ok: false, error: { code: "approval_conflict" } });
  checks.ASYNC_ERROR_STAYS_HIDDEN =
    lateError.clearedAtLogout && lateError.stayedHidden && lateError.children === 0;
  checks.ASYNC_ERROR_NO_REPAINT = !lateError.repainted;

  // The single-flight flag must not be left stuck by the stale promise: the
  // next session has to be able to decide at all.
  await reLogin();
  A.fixture.decisionPending = null;
  A.fixture.decision = { ok: true, result: { run_id: FIX.runId, status: "completed", result_text: "approved" } };
  A.byId.clawNavButton.click();
  await tick(60);
  A.byId.messageInput.value = "SYNTHETIC next-session request";
  A.byId.clawExecuteButton.click();
  await tick(80);
  const approveNext = approvalButtons(A.byId).find((b) => String(b.className).indexOf("claw-approval-approve") >= 0);
  checks.CURRENT_SESSION_CONTROLS_USABLE = !!approveNext && approveNext.disabled === false;
  const postsBeforeNext = decisionPosts(A.requests).length;
  if (approveNext) approveNext.click();
  await tick(120);
  checks.CURRENT_SESSION_DECISION_DISPATCHED =
    decisionPosts(A.requests).length === postsBeforeNext + 1;
  checks.CURRENT_SESSION_DECISION_CLEARED =
    A.byId.clawApprovalActions.hidden === true && A.byId.clawApprovalActions.children.length === 0;

  console.log(JSON.stringify({ ok: true, checks }));
  process.exit(0);
})().catch((e) => { console.log(JSON.stringify({ ok: false, error: String((e && e.stack) || e) })); process.exit(0); });
"""


@lru_cache(maxsize=1)
def _run_harness() -> dict:
    node = shutil.which("node")
    assert node, "node runtime is required for the behavioural harness"
    fixture = json.dumps(
        {"runId": SYNTHETIC_RUN_ID, "memoryId": SYNTHETIC_MEMORY_ID, "memoryName": SYNTHETIC_MEMORY_NAME}
    )
    # The generated harness and its fixture are written to a private temporary
    # directory, never to a fixed path inside the source tree: concurrent
    # pytest invocations, sharded runs and parallel worktrees would otherwise
    # collide on the same filename (and could race each other's unlink).
    with tempfile.TemporaryDirectory(prefix="claw2-4488-") as tmp:
        harness_path = Path(tmp) / "harness.js"
        fixture_path = Path(tmp) / "fixture.json"
        harness_path.write_text(_HARNESS, encoding="utf-8")
        fixture_path.write_text(fixture, encoding="utf-8")
        result = subprocess.run(
            [node, str(harness_path), str(APP_JS), str(fixture_path)],
            capture_output=True,
            text=True,
            timeout=120,
        )
    assert result.returncode == 0, f"harness exited {result.returncode}: {result.stderr}"
    line = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else "{}"
    return json.loads(line)


def test_behavioural_harness_passes() -> None:
    payload = _run_harness()
    assert payload.get("ok") is True, f"behavioural harness failed: {payload}"


def test_behavioural_approval_state_transitions() -> None:
    payload = _run_harness()
    assert payload.get("ok") is True, payload
    checks = payload["checks"]
    for name in (
        "APPROVAL_CONTROLS_RENDERED",
        "APPROVAL_STATUS_SILENT_UNTIL_ACTION",
        "APPROVAL_BUSY_DISABLES_BOTH",
        "APPROVAL_SINGLE_FLIGHT",
        "APPROVAL_DECISION_PAYLOAD",
        "APPROVAL_SUCCESS_CLEARS_CONTROLS",
        "APPROVAL_ERROR_STATE",
        "APPROVAL_BUSY_RELEASED_ON_ERROR",
    ):
        assert checks.get(name) is True, f"{name}: {checks}"


def test_behavioural_memory_state_transitions() -> None:
    payload = _run_harness()
    assert payload.get("ok") is True, payload
    checks = payload["checks"]
    for name in (
        "MEMORY_PANEL_SHOWN_IN_CLAW",
        "MEMORY_LIST_RENDERED",
        "MEMORY_DISCLOSURE_CLOSED_BEFORE",
        "MEMORY_DETAIL_OPENS_DISCLOSURE",
    ):
        assert checks.get(name) is True, f"{name}: {checks}"


def test_behavioural_relogin_tears_down_the_session() -> None:
    """An auth loss must not leave a decision surface behind for the next session."""
    payload = _run_harness()
    assert payload.get("ok") is True, payload
    checks = payload["checks"]
    assert checks.get("LOGOUT_HIDES_WORKSPACE") is True, checks
    assert checks.get("LOGOUT_CLEARS_MEMORY_SURFACE") is True, checks
    assert checks.get("LOGOUT_CLEARS_PENDING_APPROVAL") is True, (
        "a pending approval decision surface outlived the session: "
        f"hidden={checks.get('APPROVAL_SURVIVING_HIDDEN')} "
        f"children={checks.get('APPROVAL_SURVIVING_CHILDREN')}"
    )
    assert checks.get("RELOGIN_STALE_APPROVAL_VISIBLE") is False, (
        "re-entering Claw after an auth loss re-showed a previous session's approval controls"
    )


def test_the_decision_captures_a_session_generation_before_awaiting() -> None:
    """The guard must be captured pre-await and re-checked after every await."""
    body = _approval_renderer(_app_source())
    assert "const decisionEpoch = clawApprovalEpoch;" in body
    assert body.index("const decisionEpoch = clawApprovalEpoch;") < body.index("await fetch(")
    # Both the success and the error branch re-verify the generation.
    assert body.count("decisionEpoch !== clawApprovalEpoch") == 2
    # The finally is generation-guarded, so a stale promise cannot release the
    # busy state that belongs to a newer session's controls.
    assert "if (decisionEpoch === clawApprovalEpoch) {" in body


def test_auth_transitions_invalidate_the_approval_generation() -> None:
    app = _app_source()
    assert "let clawApprovalEpoch = 0;" in app
    assert app.count("function invalidateClawApprovalSession()") == 1
    assert app.count("function noteClawApprovalSession(") == 1
    # Auth loss and an account switch funnel through one invalidation point,
    # called from the single auth-state projection.
    assert app.count("noteClawApprovalSession(authenticated);") == 1
    note = app.index("function noteClawApprovalSession")
    note_body = app[note : app.index("\n  }", note)]
    assert "token !== clawApprovalSessionToken" in note_body
    assert "invalidateClawApprovalSession();" in note_body
    # Invalidation bumps the generation and releases the shared single-flight
    # flag, otherwise the next session could never decide.
    inv = app.index("function invalidateClawApprovalSession")
    inv_body = app[inv : app.index("\n  }", inv)]
    assert "clawApprovalEpoch += 1;" in inv_body
    assert "clawApprovalInFlight = false;" in inv_body


def test_the_harness_writes_no_fixed_path_into_the_source_tree() -> None:
    """Concurrent pytest runs must not collide on a shared temporary filename."""
    source = Path(__file__).read_text(encoding="utf-8")
    assert "tempfile.TemporaryDirectory" in source
    for stem in ("harness.js", "fixture.json"):
        fixed = "_4488_claw_state_transitions_" + stem
        assert fixed not in source, fixed
    # ...and no generated artifact is left behind in the test tree.
    leftovers = [p.name for p in (ROOT / "tests").glob("_4488_claw_state_transitions*")]
    assert leftovers == [], leftovers


def test_behavioural_async_decision_cannot_outlive_its_session() -> None:
    """A decision that lands after logout must not repaint the next session.

    The synchronous logout cleanup alone is not sufficient: a POST begun before
    the logout resolves afterwards, and `applyImmediateApprovalDecision` mutates
    the DOM *before* its first await. The session-generation guard is what makes
    the late response inert.
    """
    payload = _run_harness()
    assert payload.get("ok") is True, payload
    checks = payload["checks"]
    for name in (
        "ASYNC_WAITING_DISPATCHED",
        "ASYNC_WAITING_STAYS_HIDDEN",
        "ASYNC_WAITING_NO_REPAINT",
        "ASYNC_WAITING_NO_HISTORY_REFETCH",
    ):
        assert checks.get(name) is True, f"{name}: {checks}"
    assert checks.get("ASYNC_WAITING_CHILDREN") == 0, checks
    # A late terminal result must not repaint the result preview either.
    assert checks.get("ASYNC_COMPLETED_STAYS_HIDDEN") is True, checks
    assert checks.get("ASYNC_COMPLETED_NO_REPAINT") is True, checks
    assert checks.get("ASYNC_COMPLETED_PREVIEW_BEFORE") == checks.get("ASYNC_COMPLETED_PREVIEW_AFTER"), checks
    # ...and neither must a late failure.
    assert checks.get("ASYNC_ERROR_STAYS_HIDDEN") is True, checks
    assert checks.get("ASYNC_ERROR_NO_REPAINT") is True, checks


def test_behavioural_current_session_remains_usable() -> None:
    """The stale promise must not wedge the single-flight flag for the next session."""
    payload = _run_harness()
    assert payload.get("ok") is True, payload
    checks = payload["checks"]
    assert checks.get("CURRENT_SESSION_CONTROLS_USABLE") is True, checks
    assert checks.get("CURRENT_SESSION_DECISION_DISPATCHED") is True, checks
    assert checks.get("CURRENT_SESSION_DECISION_CLEARED") is True, checks


if __name__ == "__main__":
    test_approval_controls_are_real_buttons_for_keyboard_activation()
    test_the_approval_status_is_a_polite_live_region()
    test_the_approval_decision_is_single_flight()
    test_the_approval_busy_state_is_exposed_to_assistive_tech()
    test_the_approval_decision_payload_carries_only_server_run_id_and_decision()
    test_the_approval_surface_is_a_labelled_group()
    test_the_memory_disclosure_is_a_native_keyboard_disclosure()
    test_the_memory_panel_is_labelled_by_its_own_heading()
    test_the_memory_visibility_gate_requires_an_owner_session_in_claw()
    test_the_decision_captures_a_session_generation_before_awaiting()
    test_auth_transitions_invalidate_the_approval_generation()
    test_the_harness_writes_no_fixed_path_into_the_source_tree()
    test_behavioural_harness_passes()
    test_behavioural_approval_state_transitions()
    test_behavioural_memory_state_transitions()
    test_behavioural_relogin_tears_down_the_session()
    test_behavioural_async_decision_cannot_outlive_its_session()
    test_behavioural_current_session_remains_usable()
    print("CLAW2_4488_STATE_TRANSITIONS=PASS")
