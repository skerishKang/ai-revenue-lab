"""B54 Claw pre-dispatch execute recovery contracts (#2760).

The server already emits `Retry-After` on the UsageGate's pre-dispatch 429
(`app/claw_routes.py::_usage_denied_response`) and the browser discarded it,
mapping every 429 to one generic copy. This file guards the recovery slice that
consumes that existing header without inventing retry authority.

Safety distinction under test:

- pre-dispatch 429 + bounded numeric Retry-After -> localized cooldown, then an
  explicit user retry (never a timer-driven POST);
- ambiguous failures (network error, 502/503/504) -> guidance to check Recent
  runs, never a retry affordance and never a hidden second POST;
- input/auth/storage/limit denials -> existing bounded copy, no retry state.

Static assertions alone do not prove behavior, so this file also runs a Node
harness that executes the REAL app.js against a minimal DOM shim with a
recording fetch:

- RETRY_AFTER_VISIBLE_COOLDOWN=PASS
- NO_RETRY_POST_DURING_COUNTDOWN=PASS
- EXPLICIT_RETRY_AFTER_COOLDOWN_SINGLE_POST=PASS
- DOUBLE_CLICK_SINGLE_FLIGHT=PASS
- MISSING_RETRY_AFTER_NO_COUNTDOWN_CLAIM=PASS
- MALFORMED_ZERO_NEGATIVE_RETRY_AFTER_FAILS_CLOSED=PASS
- HUGE_RETRY_AFTER_IS_BOUNDED=PASS
- AMBIGUOUS_FAILURE_SAFE_RETRY_CLAIM=NO
- NO_AUTOMATIC_POST_AFTER_AMBIGUOUS_FAILURE=PASS
- PRE_DISPATCH_503_IS_NOT_AMBIGUOUS=PASS
- NETWORK_FAILURE_IS_AMBIGUOUS_AND_NOT_REPLAYED=PASS
- AUTH_FAILURE_IS_GUIDANCE_NOT_RETRY=PASS
- RETRY_TARGET_IS_VISIBLE_FORM=PASS
- NAVIGATION_CLEARS_RETRY_STATE=PASS
- AUTH_LOSS_CLEARS_RETRY_STATE=PASS
- LOCALE_CHANGE_RERENDERS_COOLDOWN_COPY=PASS
- EXECUTE_POST_COUNT_MATCHES_USER_ACTIONS=PASS

The slice is presentation-only: no route, store, schema, provider call, server
policy change, auto-retry, or Engine/P01 retry semantics are introduced.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "static/app.js"
INDEX_HTML = ROOT / "static/index.html"
LOCALE_JS = ROOT / "static/locale.js"
WORKSPACE_CSS = ROOT / "static/claw-workspace.css"
CLAW_ROUTES = ROOT / "app/claw_routes.py"

RECOVERY_KEYS = (
    "claw-btn-retry",
    "claw-retry-waiting",
    "claw-retry-ready",
    "claw-error-check-runs",
)

EXECUTE_ROUTE = '"/api/claw/manual-intake/execute"'


def _app_source() -> str:
    return APP_JS.read_text(encoding="utf-8")


# ── static structural contracts ────────────────────────────────────────────


def test_recovery_surface_is_declared_inside_the_claw_form() -> None:
    html = INDEX_HTML.read_text(encoding="utf-8")
    for token in (
        'id="clawRetryHint"',
        'id="clawRetryBox"',
        'id="clawRetryCopy"',
        'id="clawRetryButton"',
    ):
        assert token in html
    # The retry action is an explicit button, never a form submit, and it starts
    # hidden and disabled: nothing can be sent until the cooldown expires.
    assert (
        '<button type="button" class="claw-retry-button" id="clawRetryButton"'
        ' data-locale-key="claw-btn-retry" disabled aria-disabled="true">' in html
    )
    assert html.count("<h1") == 1
    assert 'id="clawRetryBox" hidden' in html
    assert 'id="clawRetryHint" hidden' in html


def test_consumes_the_existing_retry_after_header_without_new_authority() -> None:
    app = _app_source()
    assert 'headers.get("Retry-After")' in app
    assert 'response.status === 429 ? clawRetryAfterFromResponse(response)' in app
    # Exactly one execute POST target survives the refactor.
    assert app.count(EXECUTE_ROUTE) == 1
    assert app.count('fetch("/api/claw/manual-intake/execute"') == 1
    # The server contract that produces the header is unchanged and untouched.
    routes = CLAW_ROUTES.read_text(encoding="utf-8")
    assert 'headers["Retry-After"] = str(decision.retry_after_seconds)' in routes
    assert "async def _usage_gate_denial(request: Request)" in routes


def test_retry_after_parsing_is_closed_and_bounded() -> None:
    app = _app_source()
    assert "function parseClawRetryAfter(value)" in app
    assert "const CLAW_RETRY_AFTER_MAX_SECONDS = 900;" in app
    assert 'if (!/^[0-9]+$/.test(raw)) return null;' in app
    assert "if (!Number.isFinite(seconds) || seconds < 1) return null;" in app
    assert "return Math.min(seconds, CLAW_RETRY_AFTER_MAX_SECONDS);" in app
    # No HTML/copy injection: the parsed integer is only ever used as a number.
    assert "innerHTML" not in app


def test_no_automatic_or_timer_driven_execution() -> None:
    app = _app_source()
    # Both the primary button and the retry button funnel through one function.
    assert app.count("void runClawExecution();") == 2
    assert app.count("async function runClawExecution()") == 1
    # The cooldown ticker only re-renders copy and control state.
    ticker = app[app.index("clawRetryTimer = setInterval("):]
    ticker = ticker[: ticker.index("}, 1000);")]
    assert "fetch(" not in ticker
    assert "runClawExecution" not in ticker
    # No hidden POST path: no XHR stream and no background flush of the form.
    for token in ("XMLHttpRequest", "sendBeacon", "keepalive", "location.reload", "localStorage", "sessionStorage"):
        assert token not in app
    # A cooldown strictly gates the single execute entry point.
    assert "if (clawRetryRemaining() > 0) return; // explicit retry only after the pre-dispatch cooldown" in app
    assert "const blocked = busy || clawRetryRemaining() > 0;" in app


def test_ambiguous_failures_get_guidance_instead_of_a_retry_affordance() -> None:
    app = _app_source()
    assert "function isAmbiguousClawFailure(data, response)" in app
    assert 'return status === 502 || code === "engine_execution_failed";' in app
    assert "else if (isAmbiguousClawFailure(data, response)) showClawAmbiguousRecoveryHint();" in app
    assert "showClawAmbiguousRecoveryHint();" in app.split("} catch {", 1)[1]
    # Closed allowlist: no other bounded failure on this route may claim that a
    # dispatch possibly happened. Pre-dispatch denials and post-run persistence
    # failures keep their own bounded copy and never enter recovery state.
    classifier = app[app.index("function isAmbiguousClawFailure"):]
    classifier = classifier[: classifier.index("\n  }")]
    for code in (
        "rate_limited",
        "quota_exhausted",
        "service_limit_reached",
        "auth_required",
        "workspace_scope_unavailable",
        "workspace_storage_unavailable",
        "artifact_storage_failed",
        "artifact_generation_failed",
        "live_abuse_gate_unavailable",
        "engine_not_configured",
        "tier_unavailable",
        "run_history_write_failed",
    ):
        assert code not in classifier, code
    # The keyed classifier never enumerates status codes that are not ambiguous.
    assert "CLAW_RETRY_FAILURE_CODES" not in app


def test_retry_target_is_the_visible_form_not_a_hidden_snapshot() -> None:
    app = _app_source()
    # The payload is rebuilt from the live form inside the shared entry point,
    # so no snapshot variable exists to replay.
    assert "clawRetryPayload" not in app
    assert "clawRetrySnapshot" not in app
    body = app[app.index("async function runClawExecution()"):]
    body = body[: body.index("if (clawExecuteButton) {")]
    assert "const body = (input.value || \"\").trim();" in body
    assert "const channelValue = clawChannel?.value || \"other\";" in body
    assert "const senderText = (clawSender?.value || \"\").trim();" in body
    # The user's request text is preserved on failure: nothing clears the input.
    assert "input.value = \"\";" not in body


def test_auth_loss_and_navigation_clear_recovery_state() -> None:
    app = _app_source()
    assert "clearClawRecovery({ syncControls: true });" in app
    # auth loss
    auth_block = app[app.index("if (!authenticated) {"):]
    auth_block = auth_block[: auth_block.index("const sessionState")]
    assert "clearClawRecovery({ syncControls: true });" in auth_block
    # home navigation and Claw inbox navigation
    assert "// Leaving for home drops any pending Claw execute recovery timer/state." in app
    assert "// Inbox navigation leaves the manual form: drop the pending recovery timer/state." in app


def test_locale_keys_are_declared_for_both_languages() -> None:
    locale = LOCALE_JS.read_text(encoding="utf-8")
    ko_block = locale.split("en: {", 1)[0]
    en_block = locale.split("en: {", 1)[1]
    for key in RECOVERY_KEYS:
        assert f'"{key}"' in ko_block, key
        assert f'"{key}"' in en_block, key
    html = INDEX_HTML.read_text(encoding="utf-8")
    app = _app_source()
    assert 'data-locale-key="claw-btn-retry"' in html
    # Runtime-resolved keys go through the Claw locale helper, with the seconds
    # value passed as a variable rather than concatenated into a key.
    assert 'clawT("claw-retry-waiting", { seconds: remaining })' in app
    assert 'clawT("claw-retry-ready")' in app
    assert 'clawT("claw-error-check-runs")' in app
    for key in RECOVERY_KEYS:
        assert f'"{key}"' in app  # English fallback copy for the non-locale path


def test_runtime_copy_stays_locale_driven() -> None:
    app = _app_source()
    for line_no, line in enumerate(app.splitlines(), start=1):
        assert not any("\uac00" <= ch <= "\ud7a3" for ch in line), f"hardcoded Korean in app.js:{line_no}: {line.strip()}"


def test_recovery_roles_inherit_shared_tokens() -> None:
    css = WORKSPACE_CSS.read_text(encoding="utf-8")
    block = css.split("#2760 execute recovery", 1)[-1].split(".claw-result[data-claw-state", 1)[0]
    assert block
    assert "var(--text)" in block
    assert "var(--muted)" in block
    assert "var(--line)" in block
    assert "var(--card-bg)" in block
    assert "var(--accent)" in block
    assert "var(--accent-soft)" in block
    assert "var(--accent-contrast)" in block
    assert "--claw-" not in block
    assert 'html[data-theme="padiem-glass"]' not in block
    assert "min-height: 44px" in block
    assert "@media (max-width: 920px)" in block
    # Hidden outside the Claw shell state, like every other Claw-only node.
    assert '.app-shell:not([data-state="claw"]) .claw-retry,' in css
    assert '.app-shell:not([data-state="claw"]) .claw-recovery-hint,' in css


# ── behavioral proof via Node harness executing real app.js ─────────────────

_HARNESS = r"""
const fs = require("fs");
const vm = require("vm");
const APP = fs.readFileSync(process.argv[2], "utf8");

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
  "clawResultDocx","clawStatus","clawArtifactMeta","clawArtifactName","clawArtifactSize",
  "clawResultSuccessNote","clawResultHint","clawExecuteHint","clawApprovedMemory","clawApprovedRefresh",
  "clawApprovedLoading","clawApprovedError","clawApprovedList","clawApprovedEmpty","clawMemoryReview",
  "tasksNavButton","alertsNavButton","clawInbox","clawInboxTitle","clawInboxLoading","clawInboxError",
  "clawInboxEmpty","clawInboxList","clawInboxRetry","clawRunHistory","clawRunHistoryRefresh",
  "clawRunHistoryLoading","clawRunHistoryError","clawRunHistoryList","clawRunHistoryEmpty",
  "clawRetryHint","clawRetryBox","clawRetryCopy","clawRetryButton",
].forEach((id) => add(id, "div"));

// Mirror the declared markup: the recovery nodes start hidden/disabled.
byId.clawRetryHint.hidden = true;
byId.clawRetryBox.hidden = true;
byId.clawRetryButton.disabled = true;
byId.clawRetryButton.textContent = "다시 시도";

const shell = add("app-shell", "div");
shell.dataset = { state: "home" };
const accountContainer = add("sidebar-account", "div");
byId.clawChannel.options = [{ textContent: "KakaoTalk" }];
byId.clawChannel.value = "kakao";
byId.clawAction.options = [{ textContent: "quote" }];
byId.clawAction.value = "quote";
byId.clawRunHistoryList.hidden = true;

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

const requests = [];
function jsonResponse(status, obj, headers) {
  const map = headers || {};
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: {
      get(name) {
        const key = Object.keys(map).find((n) => n.toLowerCase() === String(name).toLowerCase());
        return key === undefined ? null : map[key];
      },
    },
    json: async () => obj,
  };
}

let authenticated = true;
let executeCall = () => jsonResponse(200, { ok: true, result: { title: "quote", result_text: "ran", artifact: null } });

async function fetchImpl(url, opts) {
  opts = opts || {};
  const method = (opts.method || "GET").toUpperCase();
  requests.push({ url: String(url), method, body: opts.body ? JSON.parse(opts.body) : null });
  const u = String(url);
  if (u.startsWith("/api/auth/status")) return jsonResponse(200, { ready: true, authenticated, user: { name: "owner" }, history_ready: false, project_files_ready: false });
  if (u.startsWith("/api/auth/logout")) return jsonResponse(200, { ok: true });
  if (u.startsWith("/api/projects")) return jsonResponse(200, { projects: [] });
  if (u.startsWith("/api/conversations")) return jsonResponse(200, { conversations: [] });
  if (u.startsWith("/api/claw/inbox/")) return jsonResponse(200, { ok: true, kind: "tasks", items: [], limit: 20 });
  if (u.startsWith("/api/claw/memory")) return jsonResponse(200, { ok: true, memories: [] });
  if (u.startsWith("/api/claw/runs")) return jsonResponse(200, { ok: true, runs: [] });
  if (u.startsWith("/api/claw/manual-intake/execute")) return executeCall();
  return jsonResponse(200, {});
}

// Locale shim with a switchable language so the localechange contract is real.
let lang = "ko";
const COPY = {
  ko: {
    "claw-btn-retry": "다시 시도",
    "claw-retry-waiting": "요청이 잠시 제한되었습니다. {seconds}초 후 다시 시도할 수 있습니다. 자동으로 전송되지는 않습니다.",
    "claw-retry-ready": "지금 다시 시도할 수 있습니다. 전송되는 내용은 현재 양식에 보이는 값입니다.",
    "claw-error-check-runs": "이미 실행이 시작되었을 수 있습니다. 자동으로 다시 실행하지 않았습니다. ‘최근 실행 기록’에서 결과를 먼저 확인해 주세요.",
    "claw-error-rate-limited": "요청이 잠시 많습니다. 잠시 후 다시 시도해 주세요.",
    "claw-error-auth-needed": "다시 로그인해 주세요.",
    "claw-error-auth-unavailable": "이 워크스페이스에서는 로그인 상태를 확인할 수 없어 기능을 사용할 수 없습니다.",
    "claw-status-execute-running": "실행 중...",
    "claw-status-execute-success": "실행이 완료되었습니다.",
    "claw-error-generic": "실행 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.",
  },
  en: {
    "claw-btn-retry": "Try again",
    "claw-retry-waiting": "Requests are temporarily limited. You can try again in {seconds}s. Nothing is sent automatically.",
    "claw-retry-ready": "You can try again now. Sending uses what is currently in the form.",
    "claw-error-check-runs": "A run may already have started. Nothing was re-run automatically — check Recent runs first.",
    "claw-error-rate-limited": "Too many requests right now. Please try again shortly.",
    "claw-error-auth-needed": "Please sign in again to continue.",
    "claw-error-auth-unavailable": "This feature isn't available because the workspace sign-in state can't be verified.",
    "claw-status-execute-running": "Running...",
    "claw-status-execute-success": "Done.",
    "claw-error-generic": "Something went wrong. Please try again shortly.",
  },
};
function localeText(key, variables) {
  const table = COPY[lang] || COPY.ko;
  const value = table[key] || COPY.ko[key] || key;
  if (!variables || typeof variables !== "object") return value;
  return Object.keys(variables).reduce((out, name) => out.split("{" + name + "}").join(String(variables[name])), value);
}

const winListeners = {};
const sandbox = {
  document: doc,
  fetch: fetchImpl,
  AbortController: class { constructor() { this.signal = {}; } abort() {} },
  URL: { createObjectURL: () => "blob:x", revokeObjectURL() {}, revokeURL() {} },
  setTimeout, clearTimeout, setInterval, clearInterval, console,
  CustomEvent: class {},
  location: { href: "http://localhost/", assign() {} },
  addEventListener: (type, fn) => { (winListeners[type] = winListeners[type] || []).push(fn); },
  __padiemLocale: { text: (key, variables) => localeText(key, variables) },
  PadiemChatLifecycle: { states: { IDLE: "idle", STREAMING: "streaming", COMPLETED: "completed", FAILED: "failed", CANCELLED: "cancelled", TIMED_OUT: "timed_out" }, set() {} },
  PadiemConfirmDialog: { confirm: async () => true },
  PadiemChatTransport: { requestCompleted: async () => ({}), requestStreaming: async () => ({}), readSseEvents: async () => {}, errorFor: () => new Error("x") },
  PadiemChatConversationState: { reset() {}, setConversationId() {}, getConversationId() { return null; }, outboundWithUser: () => [], commitAssistant() {}, setSkill() {}, getSkill: () => "auto" },
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

const emitWindow = (type) => (winListeners[type] || []).forEach((fn) => fn({ type }));

(async () => {
  const checks = {};
  const fail = (m) => { console.log(JSON.stringify({ ok: false, error: m, requests, checks })); process.exit(0); };
  process.on("unhandledRejection", (e) => { console.log(JSON.stringify({ ok: false, error: "unhandledRejection " + String((e && e.stack) || e) })); process.exit(0); });
  process.on("uncaughtException", (e) => { console.log(JSON.stringify({ ok: false, error: "uncaughtException " + String((e && e.stack) || e) })); process.exit(0); });
  const tick = (ms) => new Promise((r) => setTimeout(r, ms));
  const execPosts = () => requests.filter((r) => r.url === "/api/claw/manual-intake/execute" && r.method === "POST");
  const lastExec = () => execPosts()[execPosts().length - 1];
  // Every dispatched execute POST is accounted for by exactly one user action.
  let expectedPosts = 0;
  await tick(40);

  byId.clawNavButton.click();
  await tick(40);
  if (shell.dataset.state !== "claw") fail("CLAW_WORKSPACE_OPEN");
  byId.messageInput.value = "A업체 견적 요청 — 품목 20개";

  // 1) Pre-dispatch 429 with Retry-After: 3 -> visible localized cooldown.
  executeCall = () => jsonResponse(429, { ok: false, error: { code: "rate_limited" } }, { "Retry-After": "3" });
  expectedPosts += 1;
  byId.clawExecuteButton.click();
  await tick(80);
  checks.RETRY_AFTER_VISIBLE_COOLDOWN =
    execPosts().length === 1 &&
    byId.clawRetryBox.hidden === false &&
    byId.clawRetryCopy.textContent.indexOf("3초") >= 0 &&
    byId.clawRetryButton.disabled === true &&
    byId.clawRetryButton.getAttribute("aria-disabled") === "true" &&
    byId.clawExecuteButton.disabled === true &&
    byId.clawRetryHint.hidden === true;
  if (!checks.RETRY_AFTER_VISIBLE_COOLDOWN) fail("RETRY_AFTER_VISIBLE_COOLDOWN: " + byId.clawRetryCopy.textContent);

  // 2) Nothing may POST while the cooldown runs, even via a forced click.
  const during = execPosts().length;
  byId.clawRetryButton.click();
  byId.clawExecuteButton.click();
  await tick(120);
  checks.NO_RETRY_POST_DURING_COUNTDOWN = execPosts().length === during;
  if (!checks.NO_RETRY_POST_DURING_COUNTDOWN) fail("NO_RETRY_POST_DURING_COUNTDOWN");

  // 3) After the cooldown the explicit retry is enabled and fires exactly one POST.
  await tick(3300);
  checks.RETRY_READY_AFTER_COOLDOWN =
    byId.clawRetryButton.disabled === false &&
    byId.clawRetryCopy.textContent.indexOf("지금 다시 시도") >= 0 &&
    byId.clawExecuteButton.disabled === false;
  if (!checks.RETRY_READY_AFTER_COOLDOWN) fail("RETRY_READY_AFTER_COOLDOWN: " + byId.clawRetryCopy.textContent);

  executeCall = () => jsonResponse(200, { ok: true, result: { title: "quote", result_text: "ran", artifact: null } });
  const beforeRetry = execPosts().length;
  expectedPosts += 1;
  byId.clawRetryButton.click();
  await tick(80);
  checks.EXPLICIT_RETRY_AFTER_COOLDOWN_SINGLE_POST = execPosts().length === beforeRetry + 1;
  if (!checks.EXPLICIT_RETRY_AFTER_COOLDOWN_SINGLE_POST) fail("EXPLICIT_RETRY_AFTER_COOLDOWN_SINGLE_POST");
  // A successful run clears the recovery surface.
  checks.RECOVERY_CLEARED_ON_SUCCESS = byId.clawRetryBox.hidden === true && byId.clawRetryHint.hidden === true;
  if (!checks.RECOVERY_CLEARED_ON_SUCCESS) fail("RECOVERY_CLEARED_ON_SUCCESS");

  // 4) Rapid double click stays single-flight.
  executeCall = () => jsonResponse(429, { ok: false, error: { code: "rate_limited" } }, { "Retry-After": "2" });
  const beforeDouble = execPosts().length;
  expectedPosts += 1;
  byId.clawExecuteButton.click();
  await tick(60);
  await tick(2300);
  const beforePair = execPosts().length;
  expectedPosts += 1;
  byId.clawRetryButton.click();
  byId.clawRetryButton.click();
  await tick(80);
  checks.DOUBLE_CLICK_SINGLE_FLIGHT = execPosts().length === beforePair + 1 && beforePair === beforeDouble + 1;
  if (!checks.DOUBLE_CLICK_SINGLE_FLIGHT) fail("DOUBLE_CLICK_SINGLE_FLIGHT");
  await tick(2300); // let the retry's own 429 cooldown expire before the next case

  // 5) Missing Retry-After -> safe rate-limit copy, no fabricated countdown.
  executeCall = () => jsonResponse(429, { ok: false, error: { code: "rate_limited" } });
  expectedPosts += 1;
  byId.clawExecuteButton.click();
  await tick(80);
  checks.MISSING_RETRY_AFTER_NO_COUNTDOWN_CLAIM =
    byId.clawRetryBox.hidden === true &&
    byId.clawRetryCopy.textContent === "" &&
    byId.clawRetryHint.hidden === true &&
    byId.clawStatus.hidden === false &&
    byId.clawStatus.textContent === COPY.ko["claw-error-rate-limited"] &&
    byId.clawExecuteButton.disabled === false;
  if (!checks.MISSING_RETRY_AFTER_NO_COUNTDOWN_CLAIM) fail("MISSING_RETRY_AFTER_NO_COUNTDOWN_CLAIM: " + byId.clawStatus.textContent);

  // 6) Malformed / zero / negative values also make no countdown claim.
  const badHeaders = ["Wed, 21 Oct 2015 07:28:00 GMT", "0", "-5", "1.5", "  ", "1e3"];
  for (const value of badHeaders) {
    executeCall = () => jsonResponse(429, { ok: false, error: { code: "rate_limited" } }, { "Retry-After": value });
    expectedPosts += 1;
    byId.clawExecuteButton.click();
    await tick(60);
    if (byId.clawRetryBox.hidden !== true || byId.clawRetryButton.disabled !== true) fail("MALFORMED_RETRY_AFTER_FAILS_CLOSED: " + value);
  }
  checks.MALFORMED_ZERO_NEGATIVE_RETRY_AFTER_FAILS_CLOSED = byId.clawRetryBox.hidden === true;

  // 7) An unreasonably large value is clamped to the documented ceiling.
  executeCall = () => jsonResponse(429, { ok: false, error: { code: "rate_limited" } }, { "Retry-After": "99999" });
  expectedPosts += 1;
  byId.clawExecuteButton.click();
  await tick(60);
  checks.HUGE_RETRY_AFTER_IS_BOUNDED =
    byId.clawRetryBox.hidden === false &&
    byId.clawRetryCopy.textContent.indexOf("900") >= 0 &&
    byId.clawRetryCopy.textContent.indexOf("99999") < 0 &&
    byId.clawRetryButton.disabled === true;
  if (!checks.HUGE_RETRY_AFTER_IS_BOUNDED) fail("HUGE_RETRY_AFTER_IS_BOUNDED: " + byId.clawRetryCopy.textContent);

  // 8) Editing the form during the cooldown must not replay a hidden payload:
  //    the retry rebuilds the request from the visible form.
  byId.messageInput.value = "B업체 발주 요청 — 품목 3개";
  byId.clawChannel.value = "sms";
  byId.clawAction.value = "order";
  byId.clawSender.value = "B상사";
  byId.clawRetryButton.click(); // still inside the clamped cooldown: no POST
  const beforeEditRetry = execPosts().length;
  await tick(120);
  if (execPosts().length !== beforeEditRetry) fail("EDIT_DURING_COOLDOWN_POSTED");
  checks.NAV_EDIT_DURING_COOLDOWN_NO_POST = true;
  // The clamped cooldown is long, so prove the target contract on a fresh cycle.
  byId.tasksNavButton.click();
  await tick(60);
  byId.clawNavButton.click();
  await tick(60);
  executeCall = () => jsonResponse(429, { ok: false, error: { code: "rate_limited" } }, { "Retry-After": "2" });
  byId.messageInput.value = "B업체 발주 요청 — 품목 3개";
  expectedPosts += 1;
  byId.clawExecuteButton.click();
  await tick(80);
  await tick(2300);
  const beforeFormRetry = execPosts().length;
  expectedPosts += 1;
  byId.clawRetryButton.click();
  await tick(80);
  const sent = lastExec();
  checks.RETRY_TARGET_IS_VISIBLE_FORM =
    execPosts().length === beforeFormRetry + 1 &&
    sent.body.content === "B업체 발주 요청 — 품목 3개" &&
    sent.body.channel === "sms" &&
    sent.body.action === "order" &&
    sent.body.sender_hint === "B상사";
  if (!checks.RETRY_TARGET_IS_VISIBLE_FORM) fail("RETRY_TARGET_IS_VISIBLE_FORM: " + JSON.stringify(sent && sent.body));

  await tick(2300); // the previous retry returned its own 2s cooldown

  // 9) Navigation clears the pending recovery timer/state.
  executeCall = () => jsonResponse(429, { ok: false, error: { code: "rate_limited" } }, { "Retry-After": "30" });
  expectedPosts += 1;
  byId.clawExecuteButton.click();
  await tick(80);
  if (byId.clawRetryBox.hidden !== false) fail("COOLDOWN_NOT_VISIBLE_BEFORE_NAV");
  byId.tasksNavButton.click();
  await tick(60);
  checks.NAVIGATION_CLEARS_RETRY_STATE = byId.clawRetryBox.hidden === true && byId.clawRetryButton.disabled === true;
  if (!checks.NAVIGATION_CLEARS_RETRY_STATE) fail("NAVIGATION_CLEARS_RETRY_STATE");
  byId.clawNavButton.click();
  await tick(60);
  // The cleared cooldown must not be resurrected by returning to the form.
  if (byId.clawRetryBox.hidden !== true || byId.clawRetryButton.disabled !== true) fail("NAV_CLEAR_DID_NOT_PERSIST");
  // A cleared cooldown no longer blocks an explicit new dispatch.
  const beforeAfterNav = execPosts().length;
  expectedPosts += 1;
  byId.clawExecuteButton.click();
  await tick(80);
  checks.NAVIGATION_RELEASES_COOLDOWN = execPosts().length === beforeAfterNav + 1 && byId.clawRetryBox.hidden === false;
  if (!checks.NAVIGATION_RELEASES_COOLDOWN) fail("NAVIGATION_RELEASES_COOLDOWN");

  // 10) A locale switch re-renders the runtime countdown copy.
  executeCall = () => jsonResponse(429, { ok: false, error: { code: "rate_limited" } }, { "Retry-After": "30" });
  byId.tasksNavButton.click();
  await tick(40);
  byId.clawNavButton.click();
  await tick(40);
  expectedPosts += 1;
  byId.clawExecuteButton.click();
  await tick(80);
  if (byId.clawRetryBox.hidden !== false) fail("LOCALE_CASE_COOLDOWN_NOT_VISIBLE");
  const koCopy = byId.clawRetryCopy.textContent;
  lang = "en";
  emitWindow("padiem:localechange");
  checks.LOCALE_CHANGE_RERENDERS_COOLDOWN_COPY =
    koCopy !== byId.clawRetryCopy.textContent &&
    /try again in \d+s/.test(byId.clawRetryCopy.textContent) &&
    byId.clawRetryCopy.textContent.indexOf("초") < 0 &&
    byId.clawRetryCopy.textContent.indexOf("{") < 0;
  if (!checks.LOCALE_CHANGE_RERENDERS_COOLDOWN_COPY) fail("LOCALE_CHANGE_RERENDERS_COOLDOWN_COPY: " + byId.clawRetryCopy.textContent);
  lang = "ko";
  emitWindow("padiem:localechange");

  // 11) Auth loss clears retry state and never fires an execute POST.
  const beforeAuth = execPosts().length;
  authenticated = false;
  byId.loginButton.click();
  await tick(150);
  if (byId.clawRetryBox.hidden !== true) fail("AUTH_LOSS_COOLDOWN_STILL_VISIBLE");
  checks.AUTH_LOSS_CLEARS_RETRY_STATE =
    byId.clawRetryBox.hidden === true && byId.clawRetryButton.disabled === true && execPosts().length === beforeAuth;
  if (!checks.AUTH_LOSS_CLEARS_RETRY_STATE) fail("AUTH_LOSS_CLEARS_RETRY_STATE");

  // 12) 401 is guidance, not retry.
  authenticated = true;
  byId.clawNavButton.click();
  await tick(60);
  executeCall = () => jsonResponse(401, { ok: false, error: { code: "auth_required" } });
  byId.messageInput.value = "다시 로그인 확인";
  expectedPosts += 1;
  byId.clawExecuteButton.click();
  await tick(80);
  checks.AUTH_FAILURE_IS_GUIDANCE_NOT_RETRY =
    byId.clawRetryBox.hidden === true &&
    byId.clawRetryHint.hidden === true &&
    byId.clawStatus.textContent === COPY.ko["claw-error-auth-needed"];
  if (!checks.AUTH_FAILURE_IS_GUIDANCE_NOT_RETRY) fail("AUTH_FAILURE_IS_GUIDANCE_NOT_RETRY: " + byId.clawStatus.textContent);

  // 13) 502 is ambiguous: guidance only, no retry affordance, no hidden replay.
  executeCall = () => jsonResponse(502, { ok: false, error: { code: "engine_execution_failed" } });
  expectedPosts += 1;
  byId.clawExecuteButton.click();
  await tick(80);
  const after502 = execPosts().length;
  checks.AMBIGUOUS_FAILURE_SAFE_RETRY_CLAIM =
    byId.clawRetryHint.hidden === false &&
    byId.clawRetryHint.textContent.indexOf("최근 실행 기록") >= 0 &&
    byId.clawRetryBox.hidden === true &&
    byId.clawRetryButton.disabled === true &&
    byId.messageInput.value === "다시 로그인 확인";
  if (!checks.AMBIGUOUS_FAILURE_SAFE_RETRY_CLAIM) fail("AMBIGUOUS_FAILURE_SAFE_RETRY_CLAIM: " + byId.clawRetryHint.textContent);
  await tick(1500);
  checks.NO_AUTOMATIC_POST_AFTER_AMBIGUOUS_FAILURE = execPosts().length === after502;
  if (!checks.NO_AUTOMATIC_POST_AFTER_AMBIGUOUS_FAILURE) fail("NO_AUTOMATIC_POST_AFTER_AMBIGUOUS_FAILURE");

  // 14) A pre-dispatch 503 (workspace scope/storage/identity) is not ambiguous:
  //     it keeps its own bounded copy and makes no run-replay claim.
  executeCall = () => jsonResponse(503, { ok: false, error: { code: "workspace_scope_unavailable" } });
  expectedPosts += 1;
  byId.clawExecuteButton.click();
  await tick(80);
  checks.PRE_DISPATCH_503_IS_NOT_AMBIGUOUS =
    execPosts().length === after502 + 1 &&
    byId.clawRetryHint.hidden === true &&
    byId.clawRetryBox.hidden === true &&
    byId.clawStatus.textContent === COPY.ko["claw-error-auth-unavailable"];
  if (!checks.PRE_DISPATCH_503_IS_NOT_AMBIGUOUS) fail("PRE_DISPATCH_503_IS_NOT_AMBIGUOUS: " + byId.clawStatus.textContent);

  // 15) A network failure is ambiguous too: hint, no replay, text preserved.
  const beforeNetwork = execPosts().length;
  byId.messageInput.value = "네트워크 오류 확인";
  executeCall = () => { throw new Error("network down"); };
  expectedPosts += 1;
  byId.clawExecuteButton.click();
  await tick(80);
  const afterNetwork = execPosts().length;
  checks.NETWORK_FAILURE_IS_AMBIGUOUS_AND_NOT_REPLAYED =
    byId.clawRetryHint.hidden === false &&
    byId.clawRetryBox.hidden === true &&
    byId.clawStatus.textContent === COPY.ko["claw-error-generic"] &&
    byId.messageInput.value === "네트워크 오류 확인" &&
    afterNetwork === beforeNetwork + 1;
  if (!checks.NETWORK_FAILURE_IS_AMBIGUOUS_AND_NOT_REPLAYED) fail("NETWORK_FAILURE_IS_AMBIGUOUS_AND_NOT_REPLAYED");
  await tick(1500);
  if (execPosts().length !== afterNetwork) fail("NETWORK_FAILURE_REPLAYED");

  // No dispatched execute POST exists that no user action asked for.
  checks.EXECUTE_POST_COUNT_MATCHES_USER_ACTIONS = execPosts().length === expectedPosts;
  if (!checks.EXECUTE_POST_COUNT_MATCHES_USER_ACTIONS) {
    fail("EXECUTE_POST_COUNT_MATCHES_USER_ACTIONS: " + execPosts().length + " != " + expectedPosts);
  }

  console.log(JSON.stringify({ ok: true, requests, checks }));
  process.exit(0);
})().catch((e) => { console.log(JSON.stringify({ ok: false, error: String((e && e.stack) || e) })); process.exit(0); });
"""


def _run_harness() -> dict:
    node = shutil.which("node")
    assert node, "node runtime is required for the behavioral harness"
    harness_path = ROOT / "tests" / "_b54_claw_execute_retry_harness.js"
    harness_path.write_text(_HARNESS, encoding="utf-8")
    try:
        result = subprocess.run(
            [node, str(harness_path), str(APP_JS)],
            capture_output=True,
            text=True,
            timeout=120,
        )
    finally:
        harness_path.unlink(missing_ok=True)
    assert result.returncode == 0, f"harness exited {result.returncode}: {result.stderr}"
    line = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else "{}"
    return json.loads(line)


def test_behavioral_harness_passes() -> None:
    payload = _run_harness()
    assert payload.get("ok") is True, f"behavioral harness failed: {payload}"


def test_behavioral_execute_recovery_journey() -> None:
    payload = _run_harness()
    assert payload.get("ok") is True, payload
    checks = payload["checks"]
    for name in (
        "RETRY_AFTER_VISIBLE_COOLDOWN",
        "NO_RETRY_POST_DURING_COUNTDOWN",
        "RETRY_READY_AFTER_COOLDOWN",
        "EXPLICIT_RETRY_AFTER_COOLDOWN_SINGLE_POST",
        "RECOVERY_CLEARED_ON_SUCCESS",
        "DOUBLE_CLICK_SINGLE_FLIGHT",
        "MISSING_RETRY_AFTER_NO_COUNTDOWN_CLAIM",
        "MALFORMED_ZERO_NEGATIVE_RETRY_AFTER_FAILS_CLOSED",
        "HUGE_RETRY_AFTER_IS_BOUNDED",
        "NAV_EDIT_DURING_COOLDOWN_NO_POST",
        "EXECUTE_POST_COUNT_MATCHES_USER_ACTIONS",
        "RETRY_TARGET_IS_VISIBLE_FORM",
        "NAVIGATION_CLEARS_RETRY_STATE",
        "NAVIGATION_RELEASES_COOLDOWN",
        "LOCALE_CHANGE_RERENDERS_COOLDOWN_COPY",
        "AUTH_LOSS_CLEARS_RETRY_STATE",
        "AUTH_FAILURE_IS_GUIDANCE_NOT_RETRY",
        "AMBIGUOUS_FAILURE_SAFE_RETRY_CLAIM",
        "NO_AUTOMATIC_POST_AFTER_AMBIGUOUS_FAILURE",
        "PRE_DISPATCH_503_IS_NOT_AMBIGUOUS",
        "NETWORK_FAILURE_IS_AMBIGUOUS_AND_NOT_REPLAYED",
    ):
        assert checks.get(name) is True, name


def test_behavioral_execute_posts_stay_within_existing_authority() -> None:
    payload = _run_harness()
    assert payload.get("ok") is True, payload
    execute_posts = [r for r in payload["requests"] if r["url"] == "/api/claw/manual-intake/execute"]
    assert execute_posts, "no execute POST recorded"
    assert all(r["method"] == "POST" for r in execute_posts)
    # Every recorded request targets an existing route: no new endpoint appears.
    allowed = {
        "/api/auth/status",
        "/api/auth/logout",
        "/api/projects",
        "/api/conversations",
        "/api/claw/runs",
        "/api/claw/memory",
        "/api/claw/inbox/tasks",
        "/api/claw/manual-intake/execute",
    }
    urls = {r["url"].split("?")[0] for r in payload["requests"]}
    assert urls <= allowed, urls - allowed
    # Retry never doubles the dispatch: every dispatched execute POST is
    # accounted for by exactly one explicit user action in the harness.
    assert payload["checks"].get("EXECUTE_POST_COUNT_MATCHES_USER_ACTIONS") is True


if __name__ == "__main__":
    test_recovery_surface_is_declared_inside_the_claw_form()
    test_consumes_the_existing_retry_after_header_without_new_authority()
    test_retry_after_parsing_is_closed_and_bounded()
    test_no_automatic_or_timer_driven_execution()
    test_ambiguous_failures_get_guidance_instead_of_a_retry_affordance()
    test_retry_target_is_the_visible_form_not_a_hidden_snapshot()
    test_auth_loss_and_navigation_clear_recovery_state()
    test_locale_keys_are_declared_for_both_languages()
    test_runtime_copy_stays_locale_driven()
    test_recovery_roles_inherit_shared_tokens()
    test_behavioral_harness_passes()
    test_behavioral_execute_recovery_journey()
    test_behavioral_execute_posts_stay_within_existing_authority()
    print("B54_CLAW_EXECUTE_RETRY_UI_TESTS=PASS")
