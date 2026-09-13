"""#2341 — Claw task/alert inbox UI behavioral contracts.

Static string assertions alone do not prove behavior, so this file also runs a
Node harness that executes the REAL app.js against a minimal DOM shim with a
recording fetch. The harness proves actual click -> request behavior:

- INBOX_READS_BOUNDED_ENDPOINTS=PASS (GET /api/claw/tasks + /api/claw/alerts)
- STATUS_POST_BEFORE_EXPLICIT_CLICK=0
- TASK_STATUS_UPDATE_CALLS_STATUS_ENDPOINT=PASS
- ALERT_STATUS_UPDATE_CALLS_STATUS_ENDPOINT=PASS
- POST_UPDATE_VISIBLE_REFRESH=PASS
- ACCESSIBLE_LOADING_ERROR_RETRY=PASS
- EMPTY_STATE=PASS
- SENSITIVE_FIELD_DOM_PROJECTION=0
- BACKGROUND_EXECUTION_CLAIM=0
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "static/app.js"
INDEX_HTML = ROOT / "static/index.html"
CSS = ROOT / "static/claw-workspace.css"
LOCALE_JS = ROOT / "static/locale.js"


def _app_source() -> str:
    return APP_JS.read_text(encoding="utf-8")


# ── static structural contracts ────────────────────────────────────────────


def test_html_has_inbox_surfaces() -> None:
    html = INDEX_HTML.read_text(encoding="utf-8")
    for element_id in (
        'id="clawInbox"',
        'id="clawInboxRefresh"',
        'id="clawInboxLoading"',
        'id="clawInboxError"',
        'id="clawInboxErrorMessage"',
        'id="clawInboxRetry"',
        'id="clawInboxBody"',
        'id="clawInboxTasks"',
        'id="clawInboxAlerts"',
    ):
        assert element_id in html, element_id


def test_inbox_uses_the_accessible_state_quartet() -> None:
    html = INDEX_HTML.read_text(encoding="utf-8")
    inbox = html[html.index('id="clawInbox"') : html.index('class="claw-disabled-controls"')]
    assert 'role="status"' in inbox and 'aria-live="polite"' in inbox
    assert 'role="alert"' in inbox
    assert 'data-locale-key="claw-inbox-empty"' in inbox
    assert 'data-locale-key="claw-inbox-retry"' in inbox
    assert 'data-locale-aria-label="claw-inbox-refresh-aria"' in inbox


def test_endpoints_are_wired() -> None:
    source = _app_source()
    assert '"/api/claw/tasks"' in source
    assert '"/api/claw/alerts"' in source
    assert "/status`" in source


def test_no_background_or_transport_tokens() -> None:
    source = _app_source()
    for token in (
        "EventSource",
        "WebSocket",
        "ServiceWorker",
        "Notification(",
        "navigator.sendBeacon",
        "setInterval",
        "cron",
        "MutationObserver",
        "localStorage",
        "sessionStorage",
        "indexedDB",
    ):
        assert token not in source, token


def test_nav_buttons_are_wired_and_start_disabled() -> None:
    html = INDEX_HTML.read_text(encoding="utf-8")
    assert 'id="tasksNavButton"' in html and 'id="alertsNavButton"' in html
    assert 'id="tasksNavButton" type="button" disabled aria-disabled="true"' in html
    assert 'id="alertsNavButton" type="button" disabled aria-disabled="true"' in html
    source = _app_source()
    assert 'getElementById("tasksNavButton")' in source
    assert 'getElementById("alertsNavButton")' in source
    assert "syncInboxNavAvailability" in source


def test_no_sensitive_field_projection_in_renderers() -> None:
    source = _app_source()
    for leaked in ("workspace_id", "member_id", "source_id", "linked_ref", "visible_to_members"):
        assert leaked not in source, leaked


def test_keyboard_focusable_and_visible_outline() -> None:
    css = CSS.read_text(encoding="utf-8")
    assert ".claw-inbox-action:focus-visible" in css
    assert ".claw-inbox-retry:focus-visible" in css
    assert ".claw-inbox-group:focus-visible" in css


def test_inbox_surfaces_reuse_shared_theme_tokens() -> None:
    css = CSS.read_text(encoding="utf-8")
    start = css.index("/* ── Task / alert inbox")
    end = css.index("/* ── Mobile: single column", start)
    inbox = css[start:end]
    # No theme-specific palette of its own; inherits the shared roles.
    assert "html[data-theme=" not in inbox
    assert "var(--danger-surface)" in inbox
    assert "var(--danger-border)" in inbox
    assert "var(--success-surface)" in inbox
    assert "var(--success-border)" in inbox


def test_hidden_containers_have_explicit_display_overrides() -> None:
    # An author `display` rule outranks the UA `[hidden]` rule, so every
    # container this module toggles needs its own override.
    css = CSS.read_text(encoding="utf-8")
    for selector in (".claw-inbox[hidden]", ".claw-inbox-error[hidden]", ".claw-inbox-body[hidden]", ".claw-inbox-list[hidden]"):
        assert selector in css, selector


def test_locale_keys_exist_in_both_locales() -> None:
    source = LOCALE_JS.read_text(encoding="utf-8")
    ko = source[source.index("ko: {") : source.index("en: {")]
    en_start = source.index("en: {")
    en = source[en_start : source.index("\n    }", en_start)]
    pattern = r'"(claw-inbox-[^"]+|claw-task-status-[^"]+|claw-alert-status-[^"]+|claw-alert-severity-[^"]+|claw-alert-kind-[^"]+)":'
    keys = sorted(set(__import__("re").findall(pattern, ko)))
    assert keys
    assert set(keys) == set(__import__("re").findall(pattern, en))
    for key in keys:
        assert f'"{key}":' in en, key


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
  el.querySelectorAll = () => el.children;
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
  "clawManualForm","clawChannel","clawAction","clawSender","clawRequestText","clawResultArea","clawResultPreview",
  "clawResultCard","clawResultEmpty","clawResultKind","clawGenerateBtn","clawExecuteButton","clawResultBadge",
  "clawResultOpen","clawResultDocx","clawStatus","clawArtifactMeta","clawArtifactName","clawArtifactSize",
  "clawResultSuccessNote","clawResultHint","clawExecuteHint","clawApprovedMemory","clawApprovedRefresh",
  "clawApprovedLoading","clawApprovedError","clawApprovedList","clawApprovedEmpty","clawMemoryReview",
  "clawInbox","clawInboxRefresh","clawInboxLoading","clawInboxError","clawInboxErrorMessage","clawInboxRetry",
  "clawInboxBody","clawInboxTasks","clawInboxTasksEmpty","clawInboxAlerts","clawInboxAlertsEmpty",
  "clawInboxTasksGroup","clawInboxAlertsGroup","tasksNavButton","alertsNavButton",
].forEach((id) => add(id, "div"));
const shell = add("app-shell", "div");
shell.dataset = { state: "home" };
const accountContainer = add("sidebar-account", "div");
byId.clawChannel.options = [{ textContent: "KakaoTalk" }];
byId.clawChannel.value = "kakao";
byId.clawAction.options = [{ textContent: "견적서 초안" }];
byId.clawAction.value = "quote";
// The shim cannot read the HTML attributes, so seed the shipped initial state.
["clawInbox","clawInboxLoading","clawInboxError","clawInboxBody","clawInboxTasks","clawInboxTasksEmpty",
 "clawInboxAlerts","clawInboxAlertsEmpty","clawApprovedMemory","clawMemoryReview"].forEach((id) => { byId[id].hidden = true; });

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
function jsonResponse(status, obj) { return { ok: status >= 200 && status < 300, status, json: async () => obj }; }
let taskState = { tasks: [] };
let alertState = { alerts: [] };
async function fetchImpl(url, opts) {
  opts = opts || {};
  const method = (opts.method || "GET").toUpperCase();
  requests.push({ url: String(url), method, body: opts.body ? JSON.parse(opts.body) : null });
  const u = String(url);
  if (u.startsWith("/api/auth/status")) return jsonResponse(200, { ready: true, authenticated: true, user: { name: "owner" }, history_ready: false, project_files_ready: false });
  if (u.startsWith("/api/projects")) return jsonResponse(200, { projects: [] });
  if (u.startsWith("/api/conversations")) return jsonResponse(200, { conversations: [] });
  if (u.startsWith("/api/claw/tasks") && u.endsWith("/status")) {
    const id = u.split("/")[4];
    const next = JSON.parse(opts.body).status;
    taskState = { tasks: taskState.tasks.map((t) => (t.task_id === id ? { ...t, status: next } : t)) };
    return jsonResponse(200, { ok: true, task: taskState.tasks.find((t) => t.task_id === id) });
  }
  if (u.startsWith("/api/claw/alerts") && u.endsWith("/status")) {
    const id = u.split("/")[4];
    const next = JSON.parse(opts.body).status;
    alertState = { alerts: alertState.alerts.map((a) => (a.alert_id === id ? { ...a, status: next } : a)) };
    return jsonResponse(200, { ok: true, alert: alertState.alerts.find((a) => a.alert_id === id) });
  }
  if (u.startsWith("/api/claw/tasks")) return jsonResponse(200, { ok: true, tasks: taskState.tasks });
  if (u.startsWith("/api/claw/alerts")) return jsonResponse(200, { ok: true, alerts: alertState.alerts });
  if (u.startsWith("/api/claw/memory")) return jsonResponse(200, { ok: true, memories: [] });
  return jsonResponse(200, {});
}

const sandbox = {
  document: doc,
  fetch: fetchImpl,
  AbortController: class { constructor() { this.signal = {}; } abort() {} },
  URL: { createObjectURL: () => "blob:x", revokeURL() {} },
  setTimeout, clearTimeout, console,
  CustomEvent: class {},
  location: { href: "http://localhost/", assign() {} },
  addEventListener() {},
  __padiemLocale: { text: (k) => ({
    "claw-task-status-open": "열림",
    "claw-task-status-done": "완료",
    "claw-task-status-cancelled": "취소됨",
    "claw-alert-status-active": "표시 중",
    "claw-alert-status-dismissed": "숨김",
    "claw-alert-severity-warn": "주의",
    "claw-alert-kind-followup_due": "후속 일정",
    "claw-inbox-created": "생성",
    "claw-inbox-due": "마감",
    "claw-inbox-mark-done": "완료로 표시",
    "claw-inbox-reopen": "다시 열기",
    "claw-inbox-cancel-task": "취소로 표시",
    "claw-inbox-dismiss-alert": "숨기기",
    "claw-inbox-restore-alert": "다시 표시",
    "claw-inbox-error-unavailable": "작업/알림 목록을 사용할 수 없습니다.",
    "claw-inbox-error-generic": "작업/알림을 처리할 수 없습니다.",
  }[k] || k) },
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

function findButton(root, text) {
  const stack = [...(root.children || [])];
  while (stack.length) {
    const el = stack.shift();
    if (String(el.tagName).toUpperCase() === "BUTTON" && el.textContent === text) return el;
    stack.push(...(el.children || []));
  }
  return null;
}
function collectText(root) {
  let out = root.textContent || "";
  (root.children || []).forEach((c) => { out += " " + collectText(c); });
  return out;
}

(async () => {
  const fail = (m) => { console.log(JSON.stringify({ ok: false, error: m, requests })); process.exit(0); };
  const tick = (ms) => new Promise((r) => setTimeout(r, ms));
  await tick(40);

  const listCalls = (prefix) => requests.filter((r) => r.method === "GET" && r.url.startsWith(prefix)).length;
  const statusCalls = (prefix) => requests.filter((r) => r.method === "POST" && r.url.startsWith(prefix) && r.url.endsWith("/status")).length;

  // 0) Anonymous shell must not fetch the inbox yet.
  if (listCalls("/api/claw/tasks") !== 0) fail("INBOX_FETCHED_BEFORE_CLAW_SHELL");

  // 1) Open the Claw workspace -> bounded reads happen, no status POST.
  byId.clawNavButton.click();
  await tick(60);
  if (listCalls("/api/claw/tasks") < 1) fail("TASKS_LIST_NOT_FETCHED");
  if (listCalls("/api/claw/alerts") < 1) fail("ALERTS_LIST_NOT_FETCHED");
  if (statusCalls("/api/claw/tasks") !== 0) fail("STATUS_POST_BEFORE_EXPLICIT_CLICK");
  if (statusCalls("/api/claw/alerts") !== 0) fail("ALERT_STATUS_POST_BEFORE_EXPLICIT_CLICK");
  if (byId.clawInbox.hidden !== false) fail("INBOX_NOT_REVEALED_IN_CLAW_SHELL");
  if (byId.clawInboxLoading.hidden !== true) fail("LOADING_NOT_CLEARED");

  // 2) Empty state is accessible and explicit.
  if (byId.clawInboxTasksEmpty.hidden !== false) fail("TASK_EMPTY_STATE_MISSING");
  if (byId.clawInboxAlertsEmpty.hidden !== false) fail("ALERT_EMPTY_STATE_MISSING");

  // 3) Populated render -> title + localized status badge.
  taskState = { tasks: [{ task_id: "task-1", title: "Follow up with A vendor", status: "open", due_date: "2026-09-30", created_at: "2026-09-12T09:00:00Z" }] };
  alertState = { alerts: [{ alert_id: "alert-1", kind: "followup_due", severity: "warn", title: "Quote follow-up is due", status: "active", created_at: "2026-09-12T10:00:00Z" }] };
  byId.clawInboxRefresh.click();
  await tick(60);
  const taskText = collectText(byId.clawInboxTasks);
  const alertText = collectText(byId.clawInboxAlerts);
  if (taskText.indexOf("Follow up with A vendor") < 0) fail("TASK_TITLE_NOT_RENDERED");
  if (taskText.indexOf("열림") < 0) fail("TASK_STATUS_BADGE_NOT_LOCALIZED");
  if (taskText.indexOf("마감") < 0) fail("TASK_DUE_DATE_NOT_RENDERED");
  if (alertText.indexOf("Quote follow-up is due") < 0) fail("ALERT_TITLE_NOT_RENDERED");
  if (alertText.indexOf("후속 일정") < 0) fail("ALERT_KIND_NOT_LOCALIZED");
  if (alertText.indexOf("주의") < 0) fail("ALERT_SEVERITY_NOT_LOCALIZED");

  // 4) Explicit task status click -> POST status -> visible refresh.
  const markDone = findButton(byId.clawInboxTasks, "완료로 표시");
  if (!markDone) fail("TASK_STATUS_BUTTON_MISSING");
  const taskPostsBefore = statusCalls("/api/claw/tasks");
  const listsBefore = listCalls("/api/claw/tasks");
  markDone.click();
  await tick(80);
  if (statusCalls("/api/claw/tasks") !== taskPostsBefore + 1) fail("TASK_STATUS_ENDPOINT_NOT_CALLED");
  const taskPost = requests.filter((r) => r.method === "POST" && r.url.endsWith("/status") && r.url.startsWith("/api/claw/tasks")).pop();
  if (!taskPost || taskPost.url !== "/api/claw/tasks/task-1/status") fail("TASK_STATUS_URL_INVALID");
  if (!taskPost.body || taskPost.body.status !== "done") fail("TASK_STATUS_BODY_INVALID");
  if (listCalls("/api/claw/tasks") <= listsBefore) fail("POST_UPDATE_VISIBLE_REFRESH");
  if (collectText(byId.clawInboxTasks).indexOf("완료") < 0) fail("POST_UPDATE_NOT_RENDERED");

  // 5) Explicit alert dismiss -> POST status -> visible refresh.
  const dismiss = findButton(byId.clawInboxAlerts, "숨기기");
  if (!dismiss) fail("ALERT_STATUS_BUTTON_MISSING");
  dismiss.click();
  await tick(80);
  const alertPost = requests.filter((r) => r.method === "POST" && r.url.endsWith("/status") && r.url.startsWith("/api/claw/alerts")).pop();
  if (!alertPost || alertPost.url !== "/api/claw/alerts/alert-1/status") fail("ALERT_STATUS_URL_INVALID");
  if (!alertPost.body || alertPost.body.status !== "dismissed") fail("ALERT_STATUS_BODY_INVALID");
  if (collectText(byId.clawInboxAlerts).indexOf("숨김") < 0) fail("ALERT_POST_UPDATE_NOT_RENDERED");

  // 6) Accessible error + retry.
  const realFetch = sandbox.fetch;
  sandbox.fetch = async (url, opts) => {
    if (String(url).startsWith("/api/claw/tasks")) return jsonResponse(500, { error: { code: "claw_task_alert_read_failed" } });
    return realFetch(url, opts);
  };
  byId.clawInboxRefresh.click();
  await tick(60);
  const errored = byId.clawInboxError.hidden === false && byId.clawInboxErrorMessage.textContent.length > 0;
  if (!errored) fail("ERROR_STATE_NOT_RENDERED");
  if (byId.clawInboxBody.hidden !== true) fail("ERROR_STATE_LEFT_STALE_BODY_VISIBLE");
  sandbox.fetch = realFetch;
  const retryBtn = byId.clawInboxRetry;
  if (!retryBtn) fail("RETRY_BUTTON_MISSING");
  retryBtn.click();
  await tick(60);
  if (byId.clawInboxError.hidden !== true) fail("RETRY_DID_NOT_RECOVER");
  if (byId.clawInboxBody.hidden !== false) fail("RETRY_DID_NOT_RESTORE_BODY");

  // 7) Nav buttons enable only for a signed-in owner.
  if (byId.tasksNavButton.disabled !== false) fail("TASKS_NAV_NOT_ENABLED");
  if (byId.alertsNavButton.disabled !== false) fail("ALERTS_NAV_NOT_ENABLED");
  byId.tasksNavButton.click();
  await tick(20);
  if (shell.dataset.state !== "claw") fail("TASKS_NAV_DID_NOT_OPEN_CLAW");

  // 8) No internal identifiers ever reach the DOM.
  const dom = collectText(byId.clawInbox);
  ["workspace_id", "member_id", "source_id", "linked_ref", "visible_to_members", "undefined"].forEach((leak) => {
    if (dom.indexOf(leak) >= 0) fail("SENSITIVE_FIELD_DOM_PROJECTION:" + leak);
  });

  console.log(JSON.stringify({ ok: true, requests }));
})().catch((e) => { console.log(JSON.stringify({ ok: false, error: String((e && e.stack) || e) })); });
"""


def _run_harness() -> dict:
    node = shutil.which("node")
    assert node, "node runtime is required for the behavioral harness"
    harness_path = ROOT / "tests" / "_b62_2341_behavior_harness.js"
    harness_path.write_text(_HARNESS, encoding="utf-8")
    try:
        result = subprocess.run(
            [node, str(harness_path), str(APP_JS)],
            capture_output=True,
            text=True,
            timeout=60,
        )
    finally:
        harness_path.unlink(missing_ok=True)
    assert result.returncode == 0, f"harness exited {result.returncode}: {result.stderr}"
    line = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else "{}"
    return json.loads(line)


def test_behavioral_harness_passes() -> None:
    payload = _run_harness()
    assert payload.get("ok") is True, f"behavioral harness failed: {payload}"


def test_behavioral_reads_are_bounded_and_scoped() -> None:
    payload = _run_harness()
    assert payload.get("ok") is True, payload
    reads = [
        r
        for r in payload["requests"]
        if r["method"] == "GET" and r["url"] in ("/api/claw/tasks", "/api/claw/alerts")
    ]
    assert {r["url"] for r in reads} == {"/api/claw/tasks", "/api/claw/alerts"}
    # No owner/workspace identifier is ever placed on the query string.
    for request in reads:
        assert "workspace" not in request["url"]
        assert "owner" not in request["url"]


def test_behavioral_status_updates_use_declared_enums_only() -> None:
    payload = _run_harness()
    assert payload.get("ok") is True, payload
    writes = [r for r in payload["requests"] if r["method"] == "POST" and r["url"].endswith("/status")]
    assert len(writes) == 2
    assert {r["body"]["status"] for r in writes} == {"done", "dismissed"}


if __name__ == "__main__":
    test_html_has_inbox_surfaces()
    test_inbox_uses_the_accessible_state_quartet()
    test_endpoints_are_wired()
    test_no_background_or_transport_tokens()
    test_nav_buttons_are_wired_and_start_disabled()
    test_no_sensitive_field_projection_in_renderers()
    test_keyboard_focusable_and_visible_outline()
    test_inbox_surfaces_reuse_shared_theme_tokens()
    test_hidden_containers_have_explicit_display_overrides()
    test_locale_keys_exist_in_both_locales()
    test_behavioral_harness_passes()
    test_behavioral_reads_are_bounded_and_scoped()
    test_behavioral_status_updates_use_declared_enums_only()
    print("B62_TASK_ALERT_INBOX_UI_TESTS=PASS")
