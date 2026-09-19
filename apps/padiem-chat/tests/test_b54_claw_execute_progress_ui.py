"""B54 Claw in-flight elapsed wait contracts (#2763).

The Claw execute POST is one synchronous browser request. No server-side
progress, phase, or completion-percentage source exists, and B54 owns no
cancellation authority, so the only truthful in-flight affordance is local
wait state: elapsed time plus two bounded long-wait reassurances.

Guarded here:

- the elapsed readout appears only after a short bounded grace delay and only
  reports a clock value (never a bar, percentage, or invented phase);
- exactly one timer per dispatched request, started by explicit user dispatch;
- no network activity of any kind while waiting (no polling, no re-dispatch);
- the live region is written at most at the two bounded thresholds plus one
  locale switch each, never once per tick;
- success / pre-dispatch 429 / ambiguous 502 / network failure / auth loss /
  navigation all clear the wait, and a cleared wait never returns.

Static assertions alone do not prove behavior, so this file also runs a Node
harness that executes the REAL app.js against a minimal DOM shim, a recording
fetch, and a deterministic virtual clock:

- IMMEDIATE_RUNNING_NO_ELAPSED_CLAIM=PASS
- ONE_TIMER_PER_DISPATCH=PASS
- ELAPSED_HIDDEN_WITHIN_GRACE=PASS
- ELAPSED_APPEARS_WITHOUT_NETWORK=PASS
- WAIT_STAYS_LOCAL_AND_BOUNDED=PASS
- BOUNDED_LIVE_ANNOUNCEMENTS=PASS
- NO_PER_SECOND_STATUS_CHURN=PASS
- LOCALE_SWITCH_PRESERVES_ELAPSED=PASS
- SUCCESS_CLEARS_WAIT=PASS
- CLEARED_WAIT_NEVER_RETURNS=PASS
- RETRY_AFTER_HANDOFF_CLEARS_WAIT=PASS
- AMBIGUOUS_FAILURE_CLEARS_WAIT=PASS
- NETWORK_FAILURE_CLEARS_WAIT=PASS
- INBOX_NAVIGATION_CLEARS_WAIT=PASS
- AUTH_LOSS_CLEARS_WAIT=PASS
- STALE_COMPLETION_CANNOT_RESTART_WAIT=PASS
- EXECUTE_POST_COUNT_MATCHES_USER_ACTIONS=PASS
- NO_FABRICATED_COPY=PASS

The slice is presentation-only: no route, store, schema, provider call, server
policy change, fake progress, polling, auto-retry, or cancel authority.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "static/app.js"
INDEX_HTML = ROOT / "static/index.html"
LOCALE_JS = ROOT / "static/locale.js"
WORKSPACE_CSS = ROOT / "static/claw-workspace.css"

WAIT_KEYS = (
    "claw-wait-elapsed",
    "claw-wait-long",
    "claw-wait-very-long",
)

FORBIDDEN_PROGRESS_TOKENS = (
    "%",
    "percent",
    "progress",
    "phase",
    "stage",
    "analyzing",
    "finalizing",
    "almost done",
    "queued",
    "sandbox",
)


def _app_source() -> str:
    return APP_JS.read_text(encoding="utf-8")


def _wait_block() -> str:
    app = _app_source()
    assert "── In-flight elapsed wait (#2763)" in app
    return app.split("── In-flight elapsed wait (#2763)", 1)[1].split("function clearClawArtifact", 1)[0]


# ── static structural contracts ────────────────────────────────────────────


def test_wait_surface_is_declared_inside_the_claw_form() -> None:
    html = INDEX_HTML.read_text(encoding="utf-8")
    line = [ln for ln in html.splitlines() if 'id="clawWait"' in ln]
    assert len(line) == 1, "exactly one elapsed wait node"
    assert 'role="timer"' in line[0]
    # A ticking clock must not chatter through a live region: role=timer is
    # implicitly aria-live off and the surface states that explicitly.
    assert 'aria-live="off"' in line[0]
    assert 'aria-live="polite"' not in line[0]
    assert "hidden" in line[0]
    # It sits between the canonical status region and the recovery hint, inside
    # the Claw manual form.
    status_at = html.index('id="clawStatus"')
    wait_at = html.index('id="clawWait"')
    hint_at = html.index('id="clawRetryHint"')
    form_at = html.index('id="clawManualForm"')
    assert form_at < status_at < wait_at < hint_at
    assert html.count('id="clawWait"') == 1


def test_wait_is_local_elapsed_state_only() -> None:
    block = _wait_block()
    # One ticker, fixed thresholds, and a documented grace delay.
    assert block.count("setInterval(") == 1
    assert "const CLAW_WAIT_TICK_MS = 1000;" in block
    assert "const CLAW_WAIT_REVEAL_MS = 3000;" in block
    assert "const CLAW_WAIT_LONG_SECONDS = 10;" in block
    assert "const CLAW_WAIT_VERY_LONG_SECONDS = 30;" in block
    # The ticker is presentation-only: no request, no dispatch, no run-history
    # polling, no HTML injection.
    assert "fetch(" not in block
    assert "runClawExecution" not in block
    assert "claw/runs" not in block
    assert "innerHTML" not in block
    for token in ("XMLHttpRequest", "sendBeacon", "EventSource", "localStorage", "sessionStorage", "location.reload"):
        assert token not in block, token
    # A clock value is the only thing reported.
    assert 'clawT("claw-wait-elapsed", { seconds: elapsed })' in block
    assert "clawWaitElapsedSeconds()" in block


def test_exactly_one_explicit_dispatch_path_starts_the_wait() -> None:
    app = _app_source()
    assert app.count("async function runClawExecution()") == 1
    assert app.count("beginClawWait();") == 1
    assert app.count("function beginClawWait()") == 1
    execute_body = app[app.index("async function runClawExecution()"):]
    execute_body = execute_body[: execute_body.index("if (clawExecuteButton) {")]
    # The timer starts only after the single-flight and cooldown guards, and only
    # for a payload the form actually accepted.
    guard = execute_body.index("if (clawRetryRemaining() > 0) return;")
    body_check = execute_body.index("if (!body) {")
    start = execute_body.index("beginClawWait();")
    assert guard < body_check < start
    assert 'const body = (input.value || "").trim();' in execute_body


def test_wait_timer_lifecycle_is_closed() -> None:
    app = _app_source()
    # Definition plus exactly five teardown call sites: dispatch, success/failure
    # finally, home reset, auth loss, inbox navigation.
    assert app.count("function clearClawWait()") == 1
    assert app.count("clearClawWait();") == 5
    finally_block = app[app.index("    } finally {\n      // The owning request always tears its wait timer down"):]
    finally_block = finally_block[: finally_block.index("setClawButtonsBusy(false);")]
    assert "clearClawWait();" in finally_block
    reset = app[app.index("function resetConversation("):]
    reset = reset[: reset.index("function selectProject(")]
    assert "clearClawWait();" in reset
    auth = app[app.index("if (!authenticated) {"):]
    auth = auth[: auth.index("const sessionState")]
    assert "clearClawWait();" in auth
    inbox = app[app.index("function openClawInbox(kind)"):]
    inbox = inbox[: inbox.index("function openClawWorkspace(")]
    assert "clearClawWait();" in inbox
    # Teardown only ever stops: it cannot start a timer, so a late completion
    # cannot resurrect a cleared wait.
    teardown = app[app.index("function clearClawWait()"):]
    teardown = teardown[: teardown.index("function ", 10)]
    assert "setInterval" not in teardown
    assert "beginClawWait" not in teardown


def test_wait_copy_makes_no_progress_claim() -> None:
    locale = LOCALE_JS.read_text(encoding="utf-8")
    app = _app_source()
    locale_lines = [ln for ln in locale.splitlines() if any(f'"{key}"' in ln for key in WAIT_KEYS)]
    assert len(locale_lines) == 6  # three keys in each language
    for line in locale_lines:
        lowered = line.lower()
        for token in FORBIDDEN_PROGRESS_TOKENS:
            assert token not in lowered, f"{token!r} in Claw wait copy: {line.strip()}"
    fallback_lines = [
        ln
        for ln in app.splitlines()
        if any(ln.strip().startswith(f'"{key}":') for key in WAIT_KEYS)
    ]
    assert len(fallback_lines) == 3
    for line in fallback_lines:
        lowered = line.lower()
        for token in FORBIDDEN_PROGRESS_TOKENS:
            assert token not in lowered, f"{token!r} in Claw wait fallback copy: {line.strip()}"
    # Only the clock readout carries a runtime value in either path, so the
    # threshold copy reads the same whether or not the locale bundle loaded.
    assert sum("{seconds}" in ln for ln in fallback_lines) == 1
    assert "{seconds}" in [ln for ln in fallback_lines if '"claw-wait-elapsed"' in ln][0]


def test_wait_announcements_are_bounded_to_two_thresholds() -> None:
    block = _wait_block()
    # Stage copy is applied only when a threshold is newly crossed, and the copy
    # itself carries no elapsed value, so the polite region is never rewritten
    # once per tick.
    assert "if (stage > clawWaitAnnouncedStage) {" in block
    assert "clawWaitAnnouncedStage = stage;" in block
    stage_copy = block[block.index("function applyClawWaitStageCopy()"):]
    stage_copy = stage_copy[: stage_copy.index("// Presentation only.")]
    assert "clawWaitAnnouncedStage < 1" in stage_copy
    assert "seconds" not in stage_copy
    assert 'clawWaitStageKey(clawWaitAnnouncedStage)' in stage_copy
    assert "clawWaitStageFor(elapsed)" in block
    assert "elapsedSeconds >= CLAW_WAIT_VERY_LONG_SECONDS" in block
    assert "elapsedSeconds >= CLAW_WAIT_LONG_SECONDS" in block


def test_wait_does_not_add_routes_or_touch_the_server() -> None:
    app = _app_source()
    assert app.count('"/api/claw/manual-intake/execute"') == 1
    assert app.count('fetch("/api/claw/manual-intake/execute"') == 1
    # The run-history route keeps exactly one consumer (the #2746 surface) and is
    # never used as a progress channel.
    assert app.count('fetch("/api/claw/runs') == 1
    block = _wait_block()
    assert "/api/" not in block


def test_locale_keys_are_declared_for_both_languages() -> None:
    locale = LOCALE_JS.read_text(encoding="utf-8")
    ko_block = locale.split("en: {", 1)[0]
    en_block = locale.split("en: {", 1)[1]
    for key in WAIT_KEYS:
        assert f'"{key}"' in ko_block, key
        assert f'"{key}"' in en_block, key
    # The clock copy is the only wait string with a runtime value, and it uses a
    # named variable rather than string concatenation.
    for block in (ko_block, en_block):
        line = [ln for ln in block.splitlines() if '"claw-wait-elapsed"' in ln][0]
        assert "{seconds}" in line
    app = _app_source()
    for key in WAIT_KEYS:
        assert f'"{key}"' in app  # English fallback copy for the non-locale path


def test_wait_roles_inherit_shared_tokens() -> None:
    css = WORKSPACE_CSS.read_text(encoding="utf-8")
    block = css.split("#2763 in-flight elapsed wait", 1)[-1].split("/* ── #2760 execute recovery", 1)[0]
    assert block
    assert "var(--text)" in block
    assert "var(--line)" in block
    assert "var(--accent-soft)" in block
    assert "--claw-" not in block
    assert 'html[data-theme="padiem-glass"]' not in block
    # Hidden outside the Claw shell state, like every other Claw-only node.
    assert '.app-shell:not([data-state="claw"]) .claw-wait,' in css


def test_runtime_copy_stays_locale_driven() -> None:
    app = _app_source()
    for line_no, line in enumerate(app.splitlines(), start=1):
        assert not any("\uac00" <= ch <= "\ud7a3" for ch in line), f"hardcoded Korean in app.js:{line_no}: {line.strip()}"


# ── behavioral proof via Node harness executing real app.js ─────────────────

_HARNESS = r"""
const fs = require("fs");
const vm = require("vm");
const realSetTimeout = setTimeout;
const APP = fs.readFileSync(process.argv[2], "utf8");

// ── deterministic virtual clock: every app timer is driven explicitly ──
let now = 1750000000000;
const timers = new Map();
let timerSeq = 0;
function vSetTimer(fn, ms, repeat) {
  const delay = Math.max(0, Number(ms) || 0);
  const id = ++timerSeq;
  timers.set(id, { fn, ms: delay, due: now + delay, repeat });
  return id;
}
function vClearTimer(id) { timers.delete(id); }
function activeTimers() { return timers.size; }
function advance(ms) {
  const target = now + ms;
  let guard = 0;
  for (;;) {
    let pick = null;
    for (const entry of timers) {
      if (entry[1].due <= target && (!pick || entry[1].due < pick[1].due)) pick = entry;
    }
    if (!pick) break;
    if (++guard > 20000) throw new Error("timer storm");
    now = pick[1].due;
    if (pick[1].repeat) pick[1].due = now + pick[1].ms;
    else timers.delete(pick[0]);
    pick[1].fn();
  }
  now = target;
}

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
  "clawResultOpen","clawResultDocx","clawStatus","clawWait","clawArtifactMeta","clawArtifactName","clawArtifactSize",
  "clawResultSuccessNote","clawResultHint","clawExecuteHint","clawApprovedMemory","clawApprovedRefresh",
  "clawApprovedLoading","clawApprovedError","clawApprovedList","clawApprovedEmpty","clawMemoryReview",
  "tasksNavButton","alertsNavButton","clawInbox","clawInboxTitle","clawInboxLoading","clawInboxError",
  "clawInboxEmpty","clawInboxList","clawInboxRetry","clawRunHistory","clawRunHistoryRefresh",
  "clawRunHistoryLoading","clawRunHistoryError","clawRunHistoryList","clawRunHistoryEmpty",
  "clawRetryHint","clawRetryBox","clawRetryCopy","clawRetryButton",
].forEach((id) => add(id, "div"));

// Mirror the declared markup: these nodes start hidden.
byId.clawStatus.hidden = true;
byId.clawWait.hidden = true;
byId.clawRetryHint.hidden = true;
byId.clawRetryBox.hidden = true;
byId.clawRetryButton.disabled = true;
byId.clawRetryButton.textContent = "다시 시도";
byId.clawResultCard.hidden = true;

// Record every write to the canonical polite status region so "bounded
// announcements, never once per tick" is measured rather than asserted.
let statusValue = "";
const statusWrites = [];
Object.defineProperty(byId.clawStatus, "textContent", {
  get() { return statusValue; },
  set(v) { const next = String(v); if (next !== statusValue) { statusValue = next; statusWrites.push(next); } },
});

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
    "claw-status-execute-running": "실행 중... 잠시만 기다려 주세요.",
    "claw-status-execute-success": "실행이 완료되었습니다.",
    "claw-wait-elapsed": "경과 {seconds}초",
    "claw-wait-long": "아직 실행 중입니다. 결과가 준비되면 이 화면에 표시됩니다.",
    "claw-wait-very-long": "예상보다 오래 걸리고 있습니다. 실행은 계속 진행 중이며 자동으로 다시 보내지 않습니다.",
    "claw-error-rate-limited": "요청이 잠시 많습니다. 잠시 후 다시 시도해 주세요.",
    "claw-error-generic": "실행 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.",
    "claw-retry-waiting": "요청이 잠시 제한되었습니다. {seconds}초 후 다시 시도할 수 있습니다. 자동으로 전송되지는 않습니다.",
    "claw-retry-ready": "지금 다시 시도할 수 있습니다. 전송되는 내용은 현재 양식에 보이는 값입니다.",
    "claw-error-check-runs": "이미 실행이 시작되었을 수 있습니다. 자동으로 다시 실행하지 않았습니다. ‘최근 실행 기록’에서 결과를 먼저 확인해 주세요.",
  },
  en: {
    "claw-status-execute-running": "Running... please wait a moment.",
    "claw-status-execute-success": "Done.",
    "claw-wait-elapsed": "Elapsed {seconds}s",
    "claw-wait-long": "Still running. The result will appear here when it is ready.",
    "claw-wait-very-long": "This is taking longer than usual. The request is still running and nothing is sent twice.",
    "claw-error-rate-limited": "Too many requests right now. Please try again shortly.",
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
  Date: { now: () => now },
  AbortController: class { constructor() { this.signal = {}; } abort() {} },
  URL: { createObjectURL: () => "blob:x", revokeObjectURL() {}, revokeURL() {} },
  setTimeout: (fn, ms) => vSetTimer(fn, ms, false),
  clearTimeout: (id) => vClearTimer(id),
  setInterval: (fn, ms) => vSetTimer(fn, ms, true),
  clearInterval: (id) => vClearTimer(id),
  console,
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

  // Anonymous timers are never left pending at the end of the run; advance()
  // resolves those the app owns. Real macrotasks let the fetch promise chain
  // settle without touching the virtual clock.
  const flush = async () => { for (let i = 0; i < 12; i++) await new Promise((r) => realSetTimeout(r, 0)); };
  const execPosts = () => requests.filter((r) => r.url === "/api/claw/manual-intake/execute" && r.method === "POST");
  const runHistoryGets = () => requests.filter((r) => r.url.indexOf("/api/claw/runs") === 0);
  const knownCopy = new Set([].concat(Object.values(COPY.ko), Object.values(COPY.en)));
  const elapsedCopy = (code, seconds) => COPY[code]["claw-wait-elapsed"].split("{seconds}").join(String(seconds));
  // Any request issued inside a wait window would break the local-only claim,
  // so every wait window snapshots and re-checks the whole traffic picture.
  const snapshot = () => ({ reqs: requests.length, runs: runHistoryGets().length, posts: execPosts().length });
  const unchanged = (s) => requests.length === s.reqs && runHistoryGets().length === s.runs && execPosts().length === s.posts;
  let expectedPosts = 0;

  await flush();
  byId.clawNavButton.click();
  await flush();
  if (shell.dataset.state !== "claw") fail("CLAW_WORKSPACE_OPEN");
  byId.messageInput.value = "A업체 견적 요청 — 품목 20개";

  // ── case 1: one slow execute, one truthful wait timer ──
  let settle = null;
  executeCall = () => new Promise((res) => { settle = res; });
  const seqBefore = timerSeq;
  expectedPosts += 1;
  byId.clawExecuteButton.click();
  await flush();
  checks.ONE_TIMER_PER_DISPATCH = timerSeq - seqBefore === 1 && activeTimers() === 1;
  if (!checks.ONE_TIMER_PER_DISPATCH) fail("ONE_TIMER_PER_DISPATCH: " + (timerSeq - seqBefore) + " / " + activeTimers());
  checks.IMMEDIATE_RUNNING_NO_ELAPSED_CLAIM =
    execPosts().length === 1 &&
    byId.clawWait.hidden === true &&
    byId.clawWait.textContent === "" &&
    byId.clawStatus.textContent === COPY.ko["claw-status-execute-running"];
  if (!checks.IMMEDIATE_RUNNING_NO_ELAPSED_CLAIM) {
    fail("IMMEDIATE_RUNNING_NO_ELAPSED_CLAIM: " + JSON.stringify({ hidden: byId.clawWait.hidden, status: byId.clawStatus.textContent }));
  }

  advance(1000);
  checks.ELAPSED_HIDDEN_WITHIN_GRACE = byId.clawWait.hidden === true && byId.clawWait.textContent === "";
  if (!checks.ELAPSED_HIDDEN_WITHIN_GRACE) fail("ELAPSED_HIDDEN_WITHIN_GRACE: " + byId.clawWait.textContent);

  const waitWindow = snapshot();
  advance(2000);
  checks.ELAPSED_APPEARS_WITHOUT_NETWORK =
    byId.clawWait.hidden === false &&
    byId.clawWait.textContent === elapsedCopy("ko", 3) &&
    unchanged(waitWindow);
  if (!checks.ELAPSED_APPEARS_WITHOUT_NETWORK) fail("ELAPSED_APPEARS_WITHOUT_NETWORK: " + byId.clawWait.textContent);

  advance(7000);
  checks.LONG_WAIT_ANNOUNCED_AT_THRESHOLD =
    byId.clawWait.textContent === elapsedCopy("ko", 10) &&
    byId.clawStatus.textContent === COPY.ko["claw-wait-long"];
  if (!checks.LONG_WAIT_ANNOUNCED_AT_THRESHOLD) fail("LONG_WAIT_ANNOUNCED_AT_THRESHOLD: " + byId.clawStatus.textContent);

  advance(20000);
  checks.VERY_LONG_WAIT_ANNOUNCED_AT_THRESHOLD =
    byId.clawWait.textContent === elapsedCopy("ko", 30) &&
    byId.clawStatus.textContent === COPY.ko["claw-wait-very-long"];
  if (!checks.VERY_LONG_WAIT_ANNOUNCED_AT_THRESHOLD) fail("VERY_LONG_WAIT_ANNOUNCED_AT_THRESHOLD: " + byId.clawStatus.textContent);

  advance(30000);
  checks.WAIT_STAYS_LOCAL_AND_BOUNDED =
    byId.clawWait.textContent === elapsedCopy("ko", 60) &&
    byId.clawStatus.textContent === COPY.ko["claw-wait-very-long"] &&
    unchanged(waitWindow) &&
    activeTimers() === 1;
  if (!checks.WAIT_STAYS_LOCAL_AND_BOUNDED) {
    fail("WAIT_STAYS_LOCAL_AND_BOUNDED: " + JSON.stringify({ text: byId.clawWait.textContent, requests: requests.length - waitWindow.reqs, timers: activeTimers() }));
  }
  checks.BOUNDED_LIVE_ANNOUNCEMENTS = statusWrites.length === 3;
  if (!checks.BOUNDED_LIVE_ANNOUNCEMENTS) fail("BOUNDED_LIVE_ANNOUNCEMENTS: " + JSON.stringify(statusWrites));

  lang = "en";
  emitWindow("padiem:localechange");
  checks.LOCALE_SWITCH_PRESERVES_ELAPSED =
    byId.clawWait.textContent === elapsedCopy("en", 60) &&
    byId.clawStatus.textContent === COPY.en["claw-wait-very-long"] &&
    activeTimers() === 1;
  if (!checks.LOCALE_SWITCH_PRESERVES_ELAPSED) fail("LOCALE_SWITCH_PRESERVES_ELAPSED: " + byId.clawWait.textContent + " / " + byId.clawStatus.textContent);
  lang = "ko";
  emitWindow("padiem:localechange");
  advance(1000);
  checks.ELAPSED_CONTINUES_AFTER_LOCALE_SWITCH =
    byId.clawWait.textContent === elapsedCopy("ko", 61) &&
    byId.clawStatus.textContent === COPY.ko["claw-wait-very-long"] &&
    unchanged(waitWindow);
  if (!checks.ELAPSED_CONTINUES_AFTER_LOCALE_SWITCH) fail("ELAPSED_CONTINUES_AFTER_LOCALE_SWITCH: " + byId.clawWait.textContent);
  // 61 ticks produced exactly three wait-region writes plus one per locale switch.
  checks.NO_PER_SECOND_STATUS_CHURN = statusWrites.length === 5;
  if (!checks.NO_PER_SECOND_STATUS_CHURN) fail("NO_PER_SECOND_STATUS_CHURN: " + JSON.stringify(statusWrites));

  const beforeSuccess = execPosts().length;
  settle(jsonResponse(200, { ok: true, result: { title: "quote", result_text: "ran", artifact: null } }));
  await flush();
  checks.SUCCESS_CLEARS_WAIT =
    byId.clawWait.hidden === true &&
    byId.clawWait.textContent === "" &&
    activeTimers() === 0 &&
    byId.clawStatus.textContent === COPY.ko["claw-status-execute-success"] &&
    byId.clawResultCard.hidden === false;
  if (!checks.SUCCESS_CLEARS_WAIT) fail("SUCCESS_CLEARS_WAIT: " + JSON.stringify({ hidden: byId.clawWait.hidden, timers: activeTimers() }));
  advance(30000);
  checks.CLEARED_WAIT_NEVER_RETURNS =
    byId.clawWait.hidden === true && activeTimers() === 0 && execPosts().length === beforeSuccess;
  if (!checks.CLEARED_WAIT_NEVER_RETURNS) fail("CLEARED_WAIT_NEVER_RETURNS");

  // ── case 2: a pre-dispatch 429 hands the wait off to the cooldown ──
  settle = null;
  executeCall = () => new Promise((res) => { settle = res; });
  expectedPosts += 1;
  byId.clawExecuteButton.click();
  await flush();
  const denialWindow = snapshot();
  advance(4000);
  checks.WAIT_VISIBLE_BEFORE_PRE_DISPATCH_DENIAL =
    byId.clawWait.hidden === false && byId.clawWait.textContent === elapsedCopy("ko", 4) && activeTimers() === 1 && unchanged(denialWindow);
  if (!checks.WAIT_VISIBLE_BEFORE_PRE_DISPATCH_DENIAL) fail("WAIT_VISIBLE_BEFORE_PRE_DISPATCH_DENIAL: " + byId.clawWait.textContent);
  settle(jsonResponse(429, { ok: false, error: { code: "rate_limited" } }, { "Retry-After": "20" }));
  await flush();
  checks.RETRY_AFTER_HANDOFF_CLEARS_WAIT =
    byId.clawWait.hidden === true &&
    byId.clawWait.textContent === "" &&
    activeTimers() === 1 &&
    byId.clawRetryBox.hidden === false &&
    byId.clawRetryCopy.textContent.indexOf("20초") >= 0 &&
    byId.clawStatus.textContent === COPY.ko["claw-error-rate-limited"];
  if (!checks.RETRY_AFTER_HANDOFF_CLEARS_WAIT) {
    fail("RETRY_AFTER_HANDOFF_CLEARS_WAIT: " + JSON.stringify({ hidden: byId.clawWait.hidden, timers: activeTimers(), retry: byId.clawRetryCopy.textContent }));
  }
  advance(20000);
  checks.WAIT_DOES_NOT_SURVIVE_THE_HANDOFF = activeTimers() === 0 && byId.clawWait.hidden === true;
  if (!checks.WAIT_DOES_NOT_SURVIVE_THE_HANDOFF) fail("WAIT_DOES_NOT_SURVIVE_THE_HANDOFF: " + activeTimers());

  // ── case 3: a 502 is ambiguous, so the wait becomes Recent-runs guidance ──
  settle = null;
  executeCall = () => new Promise((res) => { settle = res; });
  expectedPosts += 1;
  byId.clawExecuteButton.click();
  await flush();
  const ambiguousWindow = snapshot();
  advance(11000);
  checks.LONG_WAIT_COPY_BEFORE_AMBIGUOUS_FAILURE =
    unchanged(ambiguousWindow) &&
    byId.clawStatus.textContent === COPY.ko["claw-wait-long"] && byId.clawWait.textContent === elapsedCopy("ko", 11);
  if (!checks.LONG_WAIT_COPY_BEFORE_AMBIGUOUS_FAILURE) fail("LONG_WAIT_COPY_BEFORE_AMBIGUOUS_FAILURE: " + byId.clawStatus.textContent);
  settle(jsonResponse(502, { ok: false, error: { code: "engine_execution_failed" } }));
  await flush();
  const after502 = execPosts().length;
  checks.AMBIGUOUS_FAILURE_CLEARS_WAIT =
    byId.clawWait.hidden === true &&
    activeTimers() === 0 &&
    byId.clawRetryHint.hidden === false &&
    byId.clawStatus.textContent === COPY.ko["claw-error-generic"];
  if (!checks.AMBIGUOUS_FAILURE_CLEARS_WAIT) fail("AMBIGUOUS_FAILURE_CLEARS_WAIT: " + JSON.stringify({ hidden: byId.clawWait.hidden, timers: activeTimers() }));
  advance(20000);
  checks.NO_REPLAY_AFTER_AMBIGUOUS_FAILURE = execPosts().length === after502 && byId.clawWait.hidden === true;
  if (!checks.NO_REPLAY_AFTER_AMBIGUOUS_FAILURE) fail("NO_REPLAY_AFTER_AMBIGUOUS_FAILURE");

  // ── case 4: a browser network failure is ambiguous too ──
  let rejectPending = null;
  executeCall = () => new Promise((_, rej) => { rejectPending = rej; });
  expectedPosts += 1;
  byId.messageInput.value = "네트워크 오류 확인";
  byId.clawExecuteButton.click();
  await flush();
  const networkWindow = snapshot();
  advance(4000);
  if (byId.clawWait.hidden !== false) fail("WAIT_NOT_VISIBLE_BEFORE_NETWORK_FAILURE");
  if (!unchanged(networkWindow)) fail("NETWORK_WAIT_WINDOW_IS_LOCAL");
  rejectPending(new Error("network down"));
  await flush();
  const afterNetwork = execPosts().length;
  checks.NETWORK_FAILURE_CLEARS_WAIT =
    byId.clawWait.hidden === true &&
    activeTimers() === 0 &&
    byId.clawRetryHint.hidden === false &&
    byId.clawStatus.textContent === COPY.ko["claw-error-generic"] &&
    byId.messageInput.value === "네트워크 오류 확인";
  if (!checks.NETWORK_FAILURE_CLEARS_WAIT) fail("NETWORK_FAILURE_CLEARS_WAIT: " + JSON.stringify({ hidden: byId.clawWait.hidden, timers: activeTimers() }));
  advance(10000);
  if (execPosts().length !== afterNetwork) fail("NETWORK_FAILURE_REPLAYED");

  // ── case 5: leaving the form for the inbox clears the wait ──
  byId.messageInput.value = "이동 중 실행 확인";
  settle = null;
  executeCall = () => new Promise((res) => { settle = res; });
  expectedPosts += 1;
  byId.clawExecuteButton.click();
  await flush();
  const navWindow = snapshot();
  advance(4000);
  checks.WAIT_VISIBLE_BEFORE_NAVIGATION =
    byId.clawWait.hidden === false && activeTimers() === 1 && unchanged(navWindow);
  if (!checks.WAIT_VISIBLE_BEFORE_NAVIGATION) fail("WAIT_VISIBLE_BEFORE_NAVIGATION");
  byId.tasksNavButton.click();
  await flush();
  checks.INBOX_NAVIGATION_CLEARS_WAIT = byId.clawWait.hidden === true && activeTimers() === 0;
  if (!checks.INBOX_NAVIGATION_CLEARS_WAIT) fail("INBOX_NAVIGATION_CLEARS_WAIT: " + activeTimers());
  settle(jsonResponse(200, { ok: true, result: { title: "quote", result_text: "late", artifact: null } }));
  await flush();
  advance(3000);
  byId.clawNavButton.click();
  await flush();
  advance(3000);
  checks.NAV_CLEARED_WAIT_STAYS_CLEARED = byId.clawWait.hidden === true && activeTimers() === 0 && byId.clawWait.textContent === "";
  if (!checks.NAV_CLEARED_WAIT_STAYS_CLEARED) fail("NAV_CLEARED_WAIT_STAYS_CLEARED: " + activeTimers());
  // A cleared wait no longer blocks a fresh explicit dispatch.
  settle = null;
  executeCall = () => new Promise((res) => { settle = res; });
  expectedPosts += 1;
  byId.messageInput.value = "다시 실행";
  byId.clawExecuteButton.click();
  await flush();
  checks.NAVIGATION_RELEASES_WAIT = execPosts().length === expectedPosts && activeTimers() === 1;
  if (!checks.NAVIGATION_RELEASES_WAIT) fail("NAVIGATION_RELEASES_WAIT");

  // ── case 6: auth loss tears down the wait that is still in flight from the
  //            fresh dispatch above, and the late completion cannot restart it ──
  const authWindow = snapshot();
  advance(4000);
  checks.WAIT_VISIBLE_BEFORE_AUTH_LOSS =
    byId.clawWait.hidden === false && activeTimers() === 1 && unchanged(authWindow);
  if (!checks.WAIT_VISIBLE_BEFORE_AUTH_LOSS) fail("WAIT_VISIBLE_BEFORE_AUTH_LOSS");
  authenticated = false;
  byId.loginButton.click();
  await flush();
  checks.AUTH_LOSS_CLEARS_WAIT = byId.clawWait.hidden === true && activeTimers() === 0;
  if (!checks.AUTH_LOSS_CLEARS_WAIT) fail("AUTH_LOSS_CLEARS_WAIT: " + activeTimers());
  settle(jsonResponse(200, { ok: true, result: { title: "quote", result_text: "late", artifact: null } }));
  await flush();
  advance(5000);
  checks.STALE_COMPLETION_CANNOT_RESTART_WAIT =
    byId.clawWait.hidden === true && activeTimers() === 0 && byId.clawWait.textContent === "";
  if (!checks.STALE_COMPLETION_CANNOT_RESTART_WAIT) fail("STALE_COMPLETION_CANNOT_RESTART_WAIT: " + activeTimers());

  // ── whole-journey invariants ──
  checks.EXECUTE_POST_COUNT_MATCHES_USER_ACTIONS = execPosts().length === expectedPosts;
  if (!checks.EXECUTE_POST_COUNT_MATCHES_USER_ACTIONS) {
    fail("EXECUTE_POST_COUNT_MATCHES_USER_ACTIONS: " + execPosts().length + " != " + expectedPosts);
  }
  // Every byte the user saw came from declared copy: no invented stage, no
  // completion estimate, no fabricated phase.
  checks.NO_FABRICATED_COPY = statusWrites.every((w) => knownCopy.has(w)) &&
    statusWrites.every((w) => w.indexOf("%") < 0 && !/percent|progress|phase|stage|analyzing|finalizing|sandbox/i.test(w));
  if (!checks.NO_FABRICATED_COPY) fail("NO_FABRICATED_COPY: " + JSON.stringify(statusWrites));
  // Run history is only ever read while opening the workspace, never as a
  // progress channel: every wait window above proved zero new traffic.
  checks.NO_RUN_HISTORY_POLLING_DURING_WAIT = runHistoryGets().length <= 4 && byId.clawWait.hidden === true;
  if (!checks.NO_RUN_HISTORY_POLLING_DURING_WAIT) fail("NO_RUN_HISTORY_POLLING_DURING_WAIT: " + runHistoryGets().length);

  console.log(JSON.stringify({ ok: true, requests, checks, statusWrites }));
  process.exit(0);
})().catch((e) => { console.log(JSON.stringify({ ok: false, error: String((e && e.stack) || e) })); process.exit(0); });
"""


def _run_harness() -> dict:
    node = shutil.which("node")
    assert node, "node runtime is required for the behavioral harness"
    harness_path = ROOT / "tests" / "_b54_claw_execute_progress_harness.js"
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


def test_behavioral_elapsed_wait_journey() -> None:
    payload = _run_harness()
    assert payload.get("ok") is True, payload
    checks = payload["checks"]
    for name in (
        "ONE_TIMER_PER_DISPATCH",
        "IMMEDIATE_RUNNING_NO_ELAPSED_CLAIM",
        "ELAPSED_HIDDEN_WITHIN_GRACE",
        "ELAPSED_APPEARS_WITHOUT_NETWORK",
        "LONG_WAIT_ANNOUNCED_AT_THRESHOLD",
        "VERY_LONG_WAIT_ANNOUNCED_AT_THRESHOLD",
        "WAIT_STAYS_LOCAL_AND_BOUNDED",
        "BOUNDED_LIVE_ANNOUNCEMENTS",
        "NO_PER_SECOND_STATUS_CHURN",
        "LOCALE_SWITCH_PRESERVES_ELAPSED",
        "ELAPSED_CONTINUES_AFTER_LOCALE_SWITCH",
        "SUCCESS_CLEARS_WAIT",
        "CLEARED_WAIT_NEVER_RETURNS",
        "WAIT_VISIBLE_BEFORE_PRE_DISPATCH_DENIAL",
        "RETRY_AFTER_HANDOFF_CLEARS_WAIT",
        "WAIT_DOES_NOT_SURVIVE_THE_HANDOFF",
        "LONG_WAIT_COPY_BEFORE_AMBIGUOUS_FAILURE",
        "AMBIGUOUS_FAILURE_CLEARS_WAIT",
        "NO_REPLAY_AFTER_AMBIGUOUS_FAILURE",
        "NETWORK_FAILURE_CLEARS_WAIT",
        "WAIT_VISIBLE_BEFORE_NAVIGATION",
        "INBOX_NAVIGATION_CLEARS_WAIT",
        "NAV_CLEARED_WAIT_STAYS_CLEARED",
        "NAVIGATION_RELEASES_WAIT",
        "WAIT_VISIBLE_BEFORE_AUTH_LOSS",
        "AUTH_LOSS_CLEARS_WAIT",
        "STALE_COMPLETION_CANNOT_RESTART_WAIT",
        "EXECUTE_POST_COUNT_MATCHES_USER_ACTIONS",
        "NO_FABRICATED_COPY",
        "NO_RUN_HISTORY_POLLING_DURING_WAIT",
    ):
        assert checks.get(name) is True, name
    # The clock is the only rendered wait value, and it always carries a unit.
    writes = payload["statusWrites"]
    assert writes, writes
    assert all("%" not in w for w in writes)
    assert not any(re.search(r"\d+\s*(?:경과|Elapsed)", w) for w in writes)


def test_behavioral_wait_stays_within_existing_authority() -> None:
    payload = _run_harness()
    assert payload.get("ok") is True, payload
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
    execute_posts = [r for r in payload["requests"] if r["url"] == "/api/claw/manual-intake/execute"]
    assert execute_posts and all(r["method"] == "POST" for r in execute_posts)


if __name__ == "__main__":
    test_wait_surface_is_declared_inside_the_claw_form()
    test_wait_is_local_elapsed_state_only()
    test_exactly_one_explicit_dispatch_path_starts_the_wait()
    test_wait_timer_lifecycle_is_closed()
    test_wait_copy_makes_no_progress_claim()
    test_wait_announcements_are_bounded_to_two_thresholds()
    test_wait_does_not_add_routes_or_touch_the_server()
    test_locale_keys_are_declared_for_both_languages()
    test_wait_roles_inherit_shared_tokens()
    test_runtime_copy_stays_locale_driven()
    test_behavioral_harness_passes()
    test_behavioral_elapsed_wait_journey()
    test_behavioral_wait_stays_within_existing_authority()
    print("B54_CLAW_EXECUTE_PROGRESS_UI_TESTS=PASS")
