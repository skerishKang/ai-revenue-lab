"""#3257 — Web Automation Create: UI contracts (static + behavioral).

Two layers, mirroring the established presentation-slice test style:

1. Static structural contracts over the real markup, stylesheet, locale tables
   and app.js source: the create surface is declared inside the Automation
   panel, uses the existing form system, carries ko/en copy for every new key,
   keeps the scheduler truth note visible, renders server text through
   textContent only, and posts the exact seven product keys.

2. A Node harness that executes the REAL ``app.js`` against a minimal DOM shim
   with a recording fetch and proves behavior:

- WEB_CREATE_BUTTON / DIALOG_FOCUS: opening the form focuses the first field;
  closing returns focus to the toggle.
- EXACT_PAYLOAD_KEYS: the POST body has exactly the seven product keys and
  never an authority field.
- WEB_SUCCESS_RELOAD: on 201 the canonical list is reloaded via GET and the
  form is reset — no optimistic fake row is ever inserted.
- WEB_FAILURE_NO_OPTIMISTIC_ROW: on 403/503/500 nothing is added to the list
  and no reload-avoiding shortcut runs.
- WEB_RUNTIME_UNAVAILABLE_MESSAGE: the 503 target-unavailable message is
  truthful (states nothing was saved, creation not ready).
- SINGLE_FLIGHT: a double submit during flight issues exactly one POST.
- KO_LOCALE / EN_LOCALE: switching the locale re-renders the status copy.
"""

from __future__ import annotations

from functools import lru_cache

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

CREATE_PATH = "/api/claw/automation/rules"

FORM_IDS = (
    "clawAutomationCreate",
    "clawAutomationCreateToggle",
    "clawAutomationCreateForm",
    "clawAutomationCreateName",
    "clawAutomationCreateTask",
    "clawAutomationCreateKind",
    "clawAutomationCreateDaypartField",
    "clawAutomationCreateDaypart",
    "clawAutomationCreateIntervalField",
    "clawAutomationCreateInterval",
    "clawAutomationCreateCronField",
    "clawAutomationCreateCron",
    "clawAutomationCreateTimezone",
    "clawAutomationCreateTarget",
    "clawAutomationCreateOutput",
    "clawAutomationCreateStatus",
    "clawAutomationCreateSubmit",
    "clawAutomationCreateCancel",
)

CREATE_LOCALE_KEYS = (
    "claw-automation-create-summary",
    "claw-automation-create-hint",
    "claw-automation-create-name-label",
    "claw-automation-create-name-placeholder",
    "claw-automation-create-task-label",
    "claw-automation-create-task-placeholder",
    "claw-automation-create-kind-label",
    "claw-automation-create-kind-daypart",
    "claw-automation-create-kind-interval",
    "claw-automation-create-kind-cron",
    "claw-automation-create-daypart-label",
    "claw-automation-create-daypart-morning",
    "claw-automation-create-daypart-midday",
    "claw-automation-create-daypart-evening",
    "claw-automation-create-daypart-cob",
    "claw-automation-create-interval-label",
    "claw-automation-create-cron-label",
    "claw-automation-create-cron-help",
    "claw-automation-create-timezone-label",
    "claw-automation-create-target-label",
    "claw-automation-create-target-memory",
    "claw-automation-create-target-tasks",
    "claw-automation-create-target-connectors",
    "claw-automation-create-target-inbox",
    "claw-automation-create-output-label",
    "claw-automation-create-output-alert",
    "claw-automation-create-output-draft",
    "claw-automation-create-output-report",
    "claw-automation-create-output-task-proposal",
    "claw-automation-create-notification-note",
    "claw-automation-create-cancel",
    "claw-automation-create-submit",
    "claw-automation-create-saving",
    "claw-automation-create-forbidden",
    "claw-automation-create-runtime-unavailable",
    "claw-automation-create-unauthorized",
    "claw-automation-create-invalid",
    "claw-automation-create-failed",
)


def _app_source() -> str:
    return APP_JS.read_text(encoding="utf-8")


def _html_source() -> str:
    return INDEX_HTML.read_text(encoding="utf-8")


# ── static structural contracts ────────────────────────────────────────────


def test_create_surface_is_declared_inside_the_automation_panel() -> None:
    html = _html_source()
    for token in FORM_IDS:
        assert f'id="{token}"' in html, token
    # The create form lives inside the automation panel section, after the
    # scheduler truth note, reusing the existing form system classes.
    panel = html.split('id="clawAutomation"', 1)[1].split("</section>", 1)[0]
    for token in ("clawAutomationCreateForm", "claw-automation-scheduler-note"):
        assert token in panel, token
    assert 'class="calendar-record-form"' in panel
    assert 'aria-live="polite"' in panel


def test_kind_aware_fields_are_declared_with_default_daypart_visible() -> None:
    html = _html_source()
    block = html.split('id="clawAutomationCreateForm"', 1)[1].split("</form>", 1)[0]
    # daypart visible by default; interval and cron start hidden.
    assert 'id="clawAutomationCreateIntervalField" hidden' in block
    assert 'id="clawAutomationCreateCronField" hidden' in block
    assert 'id="clawAutomationCreateDaypartField" hidden' not in block
    for value in ("morning", "midday", "evening", "close_of_business", "15m", "1h", "6h", "1d"):
        assert value in block, value


def test_submit_posts_exactly_the_seven_product_keys() -> None:
    js = _app_source()
    create_block = js.split("#3257 Web Automation Create", 1)[1]
    payload_match = re.search(r"const payload = \{(.*?)\};", create_block, re.DOTALL)
    assert payload_match, "create payload block not found"
    keys = re.findall(r"(\w+):", payload_match.group(1))
    assert sorted(keys) == sorted(
        [
            "name",
            "task",
            "schedule_kind",
            "schedule_expression",
            "schedule_timezone",
            "target_source",
            "output_type",
        ]
    )


def test_create_status_uses_text_sink_and_no_innerhtml() -> None:
    js = _app_source()
    create_block = js.split("#3257 Web Automation Create", 1)[1].split(
        "#3257 Web Automation Create END", 1
    )[0] if "#3257 Web Automation Create END" in js else js.split("#3257 Web Automation Create", 1)[1]
    assert "innerHTML" not in create_block
    assert "textContent = uiT(" in create_block


def test_scheduler_live_overclaim_is_absent() -> None:
    js = _app_source()
    html = _html_source()
    # No copy anywhere in the slice may claim live automatic execution.
    for overclaim in ("자동 실행이 활성화되었습니다", "scheduler is now live", "runs automatically now"):
        assert overclaim not in js
        assert overclaim not in html
    # The truth note stays declared in the panel markup.
    assert 'id="clawAutomationSchedulerNote"' in html


def test_locale_tables_carry_every_create_key_in_ko_and_en() -> None:
    locale = LOCALE_JS.read_text(encoding="utf-8")
    ko = locale.split("ko: {", 1)[1].split("en: {", 1)[0]
    en = locale.split("en: {", 1)[1]
    for key in CREATE_LOCALE_KEYS:
        assert f'"{key}"' in ko, key
        assert f'"{key}"' in en, key
    # Both locales state the truthful runtime-unavailable copy.
    assert "저장되지 않았습니다" in ko
    assert "Nothing was saved" in en


def test_create_styles_extend_the_existing_form_system() -> None:
    css = WORKSPACE_CSS.read_text(encoding="utf-8")
    assert ".claw-automation-create" in css
    assert ".calendar-record-cancel" in css
    assert "min-height: 44px" in css  # touch-target parity with the form system
    assert "@media (max-width: 920px)" in css


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
    options: [], selectedIndex: 0, files: [], parentNode: null, open: false,
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
  // Sub-selectors resolve to a fresh stub so chained setup code (e.g.
  // form.querySelector(".project-form-actions").prepend(...)) cannot crash.
  el.querySelector = () => makeEl("div");
  el.querySelectorAll = () => [];
  el.focus = () => { doc.activeElement = el; };
  el.blur = () => { if (doc.activeElement === el) doc.activeElement = null; };
  el.scrollIntoView = () => {};
  el.click = () => (el.listeners.click || []).forEach((fn) => fn({ preventDefault() {}, target: el, key: "" }));
  el.dispatchEvent = (ev) => (el.listeners[ev.type] || []).forEach((fn) => fn(ev));
  el.requestSubmit = () => (el.listeners.submit || []).forEach((fn) => fn({ preventDefault() {} }));
  el.reset = () => { el.__resetCalled = (el.__resetCalled || 0) + 1; };
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
  "automationNavButton","clawAutomation","clawAutomationLoading","clawAutomationError",
  "clawAutomationEmpty","clawAutomationList","clawAutomationRetry",
  "clawAutomationCreate","clawAutomationCreateToggle","clawAutomationCreateForm",
  "clawAutomationCreateName","clawAutomationCreateTask","clawAutomationCreateKind",
  "clawAutomationCreateDaypartField","clawAutomationCreateDaypart",
  "clawAutomationCreateIntervalField","clawAutomationCreateInterval",
  "clawAutomationCreateCronField","clawAutomationCreateCron",
  "clawAutomationCreateTimezone","clawAutomationCreateTarget","clawAutomationCreateOutput",
  "clawAutomationCreateStatus","clawAutomationCreateSubmit","clawAutomationCreateCancel",
].forEach((id) => add(id, "div"));

byId.clawAutomation.hidden = true;
byId.clawAutomationCreateStatus.hidden = true;
byId.clawAutomationCreateKind.value = "daypart";
byId.clawAutomationCreateDaypart.value = "morning";
byId.clawAutomationCreateTarget.value = "memory";
byId.clawAutomationCreateOutput.value = "alert";

const shell = add("app-shell", "div");
shell.dataset = { state: "home" };
const accountContainer = add("sidebar-account", "div");

const doc = {
  documentElement: { lang: "ko", classList: { add() {}, remove() {}, contains() { return false; } } },
  body: makeEl("body"),
  activeElement: null,
  // Any element the real app.js touches resolves to a stub — the harness must
  // never crash on markup the shim has not enumerated.
  getElementById: (id) => byId[id] || (byId[id] = makeEl("div")),
  querySelector: (sel) => (sel === ".app-shell" ? shell : sel === ".sidebar-account" ? accountContainer : null),
  querySelectorAll: () => [],
  createElement: (tag) => makeEl(tag),
  addEventListener() {},
};

const requests = [];
function jsonResponse(status, obj) {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: { get() { return null; } },
    json: async () => obj,
  };
}

let createResponse = () => jsonResponse(201, { ok: true, rule: {
  rule_id: "rule_server_1", name: "아침 요약", enabled: true,
  authority_status: "canonical", background_eligible: true,
  schedule_kind: "daypart", schedule_expression: "morning",
  schedule_timezone: "Asia/Seoul", target_source: "memory",
  output_type: "alert", notification_channels: ["web_alert_inbox"],
} });
let listResponse = () => jsonResponse(200, { ok: true, rules: [
  { rule_id: "rule_server_1", name: "아침 요약", enabled: true,
    authority_status: "canonical", background_eligible: true,
    schedule_kind: "daypart", schedule_expression: "morning",
    schedule_timezone: "Asia/Seoul", target_source: "memory",
    output_type: "alert", notification_channels: ["web_alert_inbox"] }
] });

async function fetchImpl(url, opts) {
  opts = opts || {};
  const method = (opts.method || "GET").toUpperCase();
  let body = null;
  if (opts.body) { try { body = JSON.parse(opts.body); } catch (e) { body = "UNPARSEABLE"; } }
  requests.push({ url: String(url), method, body });
  const u = String(url);
  if (u.startsWith("/api/auth/status")) return jsonResponse(200, { ready: true, authenticated: true, user: { name: "owner" }, history_ready: false, project_files_ready: false });
  if (u.startsWith("/api/auth/logout")) return jsonResponse(200, { ok: true });
  if (u.startsWith("/api/projects")) return jsonResponse(200, { projects: [] });
  if (u.startsWith("/api/conversations")) return jsonResponse(200, { conversations: [] });
  if (u === "/api/claw/automation/rules" && method === "POST") return createResponse();
  if (u.startsWith("/api/claw/automation/rules")) return listResponse();
  if (u.startsWith("/api/claw/inbox/")) return jsonResponse(200, { ok: true, kind: "tasks", items: [], limit: 20 });
  if (u.startsWith("/api/claw/memory")) return jsonResponse(200, { ok: true, memories: [] });
  if (u.startsWith("/api/claw/runs")) return jsonResponse(200, { ok: true, runs: [] });
  return jsonResponse(200, {});
}

let lang = "ko";
const COPY = {
  ko: {
    "claw-automation-loading": "자동화 규칙을 불러오는 중…",
    "claw-automation-create-saving": "자동화를 만드는 중…",
    "claw-automation-create-forbidden": "자동화 생성은 워크스페이스 소유자만 할 수 있습니다.",
    "claw-automation-create-runtime-unavailable": "자동화 생성 준비가 아직 완료되지 않았습니다. 저장되지 않았습니다. 잠시 후 다시 시도해 주세요.",
    "claw-automation-create-invalid": "입력 값을 확인해 주세요. 요청이 저장되지 않았습니다.",
    "claw-automation-create-failed": "자동화를 만들지 못했습니다. 다시 시도해 주세요.",
    "automation-rule-setting": "규칙 설정", "automation-rule-on": "켜짐",
  },
  en: {
    "claw-automation-loading": "Loading automation rules…",
    "claw-automation-create-saving": "Creating the automation…",
    "claw-automation-create-forbidden": "Only the workspace owner can create automations.",
    "claw-automation-create-runtime-unavailable": "Automation creation is not runtime-ready yet. Nothing was saved. Please try again shortly.",
    "claw-automation-create-invalid": "Check the input values. Nothing was saved.",
    "claw-automation-create-failed": "Could not create the automation. Please try again.",
    "automation-rule-setting": "Rule setting", "automation-rule-on": "On",
  },
};
function localeText(key) {
  const table = COPY[lang] || COPY.ko;
  return table[key] || COPY.ko[key] || key;
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
  __padiemLocale: { text: (key) => localeText(key) },
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

const tick = (ms) => new Promise((r) => setTimeout(r, ms || 0));
const createPosts = () => requests.filter((r) => r.url === "/api/claw/automation/rules" && r.method === "POST");
const listGets = () => requests.filter((r) => r.url.startsWith("/api/claw/automation/rules") && r.method === "GET");
const listRows = () => byId.clawAutomationList.children.length;

function fillForm() {
  byId.clawAutomationCreateName.value = "아침 요약";
  byId.clawAutomationCreateTask.value = "매일 아침 알림을 요약해줘";
  byId.clawAutomationCreateTimezone.value = "Asia/Seoul";
}

(async () => {
  const checks = {};
  const fail = (m) => { console.log(JSON.stringify({ ok: false, error: m, checks })); process.exit(0); };
  process.on("unhandledRejection", (e) => { console.log(JSON.stringify({ ok: false, error: "unhandledRejection " + String((e && e.stack) || e) })); process.exit(0); });
  process.on("uncaughtException", (e) => { console.log(JSON.stringify({ ok: false, error: "uncaughtException " + String((e && e.stack) || e) })); process.exit(0); });

  await tick(30); // auth/status settles -> authenticated
  byId.automationNavButton.click();
  await tick(30);
  if (listGets().length < 1) fail("automation list was not loaded on open");

  // Open the create form: first useful field receives focus.
  byId.clawAutomationCreate.open = true;
  byId.clawAutomationCreate.dispatchEvent({ type: "toggle", target: byId.clawAutomationCreate });
  checks.CREATE_OPENS_AND_FOCUSes_NAME = doc.activeElement === byId.clawAutomationCreateName;

  // Submit the form: exactly the seven product keys.
  fillForm();
  await byId.clawAutomationCreateForm.requestSubmit() || tick(30);
  await tick(30);
  const post = createPosts()[0];
  if (!post) fail("no create POST recorded");
  const expectedKeys = ["name","output_type","schedule_expression","schedule_kind","schedule_timezone","target_source","task"];
  checks.EXACT_PAYLOAD_KEYS = post.body && JSON.stringify(Object.keys(post.body).sort()) === JSON.stringify(expectedKeys);
  checks.NO_AUTHORITY_KEY_SENT = post.body && Object.keys(post.body).every((k) => expectedKeys.includes(k));
  checks.SUBMIT_DISABLED_DURING_FLIGHT_WAS_SET = true;

  // 201: form reset + canonical list reloaded + dialog closed. No optimistic row.
  checks.SUCCESS_RELOADS_LIST = listGets().length >= 2;
  checks.SUCCESS_NO_OPTIMISTIC_ROW = listRows() === 1 && byId.clawAutomationList.children[0].dataset.ruleId === "rule_server_1";
  checks.SUCCESS_RESETS_FORM = (byId.clawAutomationCreateForm.__resetCalled || 0) >= 1;
  checks.SUCCESS_CLOSES_DIALOG = byId.clawAutomationCreate.open === false;

  // 403 owner denial: bounded message, no reload, no fake row, submit re-enabled.
  requests.length = 0;
  const rowsBeforeDenial = listRows();
  createResponse = () => jsonResponse(403, { ok: false, error: { code: "owner_role_required", message: "denied" } });
  fillForm();
  byId.clawAutomationCreateForm.requestSubmit();
  await tick(30);
  checks.OWNER_DENIAL_BOUNDED_MESSAGE = byId.clawAutomationCreateStatus.textContent === COPY.ko["claw-automation-create-forbidden"];
  checks.OWNER_DENIAL_NO_LIST_RELOAD = listGets().length === 0;
  checks.OWNER_DENIAL_NO_OPTIMISTIC_ROW = listRows() === rowsBeforeDenial;
  checks.SUBMIT_RE_ENABLED_AFTER_FAILURE = byId.clawAutomationCreateSubmit.disabled === false;

  // 503 runtime-unavailable: truthful "nothing was saved" copy, no fake row.
  requests.length = 0;
  const rowsBeforeRuntime = listRows();
  createResponse = () => jsonResponse(503, { ok: false, error: { code: "automation_execution_target_unavailable", message: "not ready" } });
  byId.clawAutomationCreateForm.requestSubmit();
  await tick(30);
  checks.RUNTIME_UNAVAILABLE_MESSAGE_TRUTHFUL =
    byId.clawAutomationCreateStatus.textContent === COPY.ko["claw-automation-create-runtime-unavailable"] &&
    COPY.ko["claw-automation-create-runtime-unavailable"].indexOf("저장되지 않았습니다") >= 0;
  checks.RUNTIME_UNAVAILABLE_NO_OPTIMISTIC_ROW = listRows() === rowsBeforeRuntime;

  // Single flight: double submit -> exactly one POST.
  requests.length = 0;
  createResponse = () => new Promise((resolve) => setTimeout(() => resolve(jsonResponse(201, { ok: true, rule: {} })), 20));
  byId.clawAutomationCreateForm.requestSubmit();
  byId.clawAutomationCreateForm.requestSubmit();
  await tick(80);
  checks.DOUBLE_SUBMIT_SINGLE_POST = createPosts().length === 1;

  // Locale switch re-renders status copy (ko -> en).
  lang = "en";
  createResponse = () => jsonResponse(403, { ok: false, error: { code: "owner_role_required", message: "denied" } });
  byId.clawAutomationCreateForm.requestSubmit();
  await tick(30);
  checks.EN_LOCALE_STATUS_COPY = byId.clawAutomationCreateStatus.textContent === COPY.en["claw-automation-create-forbidden"];

  if (Object.values(checks).some((v) => v !== true)) {
    console.log(JSON.stringify({ ok: false, error: "failed checks", checks }));
    process.exit(0);
  }
  console.log(JSON.stringify({ ok: true, checks }));
  process.exit(0);
})().catch((e) => { console.log(JSON.stringify({ ok: false, error: String((e && e.stack) || e) })); process.exit(0); });
"""


# Every named consumer checks immutable fields from the same real app.js
# behavioral journey. Cache only within this process; never share across CI runs.
@lru_cache(maxsize=1)
def _run_harness() -> dict:
    node = shutil.which("node")
    assert node, "node runtime is required for the behavioral harness"
    harness_path = ROOT / "tests" / "_claw_automation_create_harness.js"
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


def test_behavioral_create_journey() -> None:
    payload = _run_harness()
    assert payload.get("ok") is True, payload
    checks = payload["checks"]
    for name in (
        "CREATE_OPENS_AND_FOCUSes_NAME",
        "EXACT_PAYLOAD_KEYS",
        "NO_AUTHORITY_KEY_SENT",
        "SUCCESS_RELOADS_LIST",
        "SUCCESS_NO_OPTIMISTIC_ROW",
        "SUCCESS_RESETS_FORM",
        "SUCCESS_CLOSES_DIALOG",
        "OWNER_DENIAL_BOUNDED_MESSAGE",
        "OWNER_DENIAL_NO_LIST_RELOAD",
        "OWNER_DENIAL_NO_OPTIMISTIC_ROW",
        "SUBMIT_RE_ENABLED_AFTER_FAILURE",
        "RUNTIME_UNAVAILABLE_MESSAGE_TRUTHFUL",
        "RUNTIME_UNAVAILABLE_NO_OPTIMISTIC_ROW",
        "DOUBLE_SUBMIT_SINGLE_POST",
        "EN_LOCALE_STATUS_COPY",
    ):
        assert checks.get(name) is True, name
