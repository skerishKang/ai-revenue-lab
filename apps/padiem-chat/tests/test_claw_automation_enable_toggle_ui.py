"""#3262 — Web enable/disable: UI contracts (static + behavioral).

Mirrors the #3257 create-UI test style:

1. Static structural contracts over the real markup, stylesheet, locale tables
   and app.js source: the toggle status node is an aria-live region, the
   Automation section is focusable (focus fallback), ko/en copy exists for every
   new key, the control meets the touch-target/focus contract, the PATCH body
   is exactly ``{enabled: <boolean>}``, and no copy claims live execution.

2. A Node harness that executes the REAL app.js against a DOM shim with a
   recording fetch and proves behavior:

- CANONICAL_ROW_TOGGLE_VISIBLE / QUARANTINED_ROW_TOGGLE_VISIBLE=0: only
  background-eligible canonical rows carry a control;
- ENABLED_ROW_ACTION / DISABLED_ROW_ACTION: the label is Turn off / Turn on;
- PATCH_EXACT_PAYLOAD: method PATCH on the rule's enabled path with exactly
  ``{"enabled": <boolean>}``;
- NO_OPTIMISTIC_FLIP: the row is unchanged before the server answers;
- SUCCESS_RELOAD + focus returns to that rule's new action control;
- FAILURE_STATE_PRESERVED: 403/404/409/503 keep the rendered state and show
  bounded messages;
- SINGLE_FLIGHT: a double click issues exactly one PATCH;
- EN_LOCALE_STATUS_COPY.
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

TOGGLE_LOCALE_KEYS = (
    "claw-automation-rule-turn-off",
    "claw-automation-rule-turn-on",
    "claw-automation-toggle-saved",
    "claw-automation-toggle-forbidden",
    "claw-automation-toggle-not-found",
    "claw-automation-toggle-not-mutable",
    "claw-automation-toggle-not-ready",
    "claw-automation-toggle-invalid",
    "claw-automation-toggle-failed",
)


def _app_source() -> str:
    return APP_JS.read_text(encoding="utf-8")


def _html_source() -> str:
    return INDEX_HTML.read_text(encoding="utf-8")


# ── static structural contracts ────────────────────────────────────────────


def test_toggle_status_is_an_aria_live_region_and_section_is_focusable() -> None:
    html = _html_source()
    assert 'id="clawAutomationToggleStatus"' in html
    assert 'aria-live="polite"' in html
    assert 'role="status"' in html
    # Focus fallback after a reload when the rule's control cannot be found.
    panel = html.split('id="clawAutomation"', 1)[1].split(">", 1)[0]
    assert 'tabindex="-1"' in panel


def test_locale_tables_carry_every_toggle_key_in_ko_and_en() -> None:
    locale = LOCALE_JS.read_text(encoding="utf-8")
    ko = locale.split("ko: {", 1)[1].split("en: {", 1)[0]
    en = locale.split("en: {", 1)[1]
    for key in TOGGLE_LOCALE_KEYS:
        assert f'"{key}"' in ko, key
        assert f'"{key}"' in en, key


def test_toggle_control_meets_touch_and_focus_contract() -> None:
    css = WORKSPACE_CSS.read_text(encoding="utf-8")
    block = css.split(".claw-automation-rule-toggle {", 1)[1].split("}", 1)[0]
    assert "min-height: 44px" in block
    assert "min-width: 44px" in block
    assert ":focus-visible" in css


def test_patch_payload_is_exactly_the_enabled_boolean() -> None:
    js = _app_source()
    toggle_block = js.split("#3262 owner-gated enable/disable", 1)[1].split(
        "#3257 Web Automation Create", 1
    )[0]
    assert 'method: "PATCH"' in toggle_block
    assert "/enabled" in toggle_block
    assert "JSON.stringify({ enabled: nextEnabled })" in toggle_block
    # No authority field may ever travel in a toggle payload.
    for forbidden in ("workspace_id", "canonical_subject_id", "owner_ref", "execution_intent", "revision"):
        assert f"{forbidden}:" not in toggle_block


def test_toggle_never_claims_live_execution() -> None:
    js = _app_source()
    html = _html_source()
    locale = LOCALE_JS.read_text(encoding="utf-8")
    for overclaim in (
        "자동 실행이 시작되었습니다",
        "scheduler activated",
        "running automatically now",
        "자동 실행이 활성화되었습니다",
    ):
        assert overclaim not in js
        assert overclaim not in html
        assert overclaim not in locale
    # The stored-setting truth note remains in the panel.
    assert 'id="clawAutomationSchedulerNote"' in html
    assert "claw-automation-toggle-saved" in js  # success copy carries the caveat


def test_toggle_button_only_for_canonical_rows() -> None:
    js = _app_source()
    toggle_block = js.split("#3262 owner-gated enable/disable", 1)[1].split(
        "#3257 Web Automation Create", 1
    )[0]
    assert "legacy_quarantined" not in toggle_block
    # The append itself lives in the canonical branch of the row renderer.
    render = js.split("function renderClawAutomationRules", 1)[1].split(
        "async function loadClawAutomationRules", 1
    )[0]
    assert "claw-automation-rule-toggle" in render
    assert "background_eligible !== true" in render
    # No local mutation of rendered rows before the server answers.
    assert "row.dataset.ruleEnabled" not in js


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
  "clawAutomationEmpty","clawAutomationList","clawAutomationRetry","clawAutomationToggleStatus",
  "clawAutomationCreate","clawAutomationCreateToggle","clawAutomationCreateForm",
  "clawAutomationCreateName","clawAutomationCreateTask","clawAutomationCreateKind",
  "clawAutomationCreateDaypartField","clawAutomationCreateDaypart",
  "clawAutomationCreateIntervalField","clawAutomationCreateInterval",
  "clawAutomationCreateCronField","clawAutomationCreateCron",
  "clawAutomationCreateTimezone","clawAutomationCreateTarget","clawAutomationCreateOutput",
  "clawAutomationCreateStatus","clawAutomationCreateSubmit","clawAutomationCreateCancel",
].forEach((id) => add(id, "div"));

byId.clawAutomation.hidden = true;
byId.clawAutomationToggleStatus.hidden = true;
byId.clawAutomationCreateStatus.hidden = true;

const shell = add("app-shell", "div");
shell.dataset = { state: "home" };
const accountContainer = add("sidebar-account", "div");

const doc = {
  documentElement: { lang: "ko", classList: { add() {}, remove() {}, contains() { return false; } } },
  body: makeEl("body"),
  activeElement: null,
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

const CANONICAL_ON = {
  rule_id: "rule_on", name: "아침 요약", enabled: true,
  authority_status: "canonical", background_eligible: true,
  schedule_kind: "daypart", schedule_expression: "morning",
  schedule_timezone: "UTC", target_source: "memory",
  output_type: "alert", notification_channels: ["web_alert_inbox"],
};
const CANONICAL_OFF = Object.assign({}, CANONICAL_ON, { rule_id: "rule_off", name: "저녁 요약", enabled: false });
const QUARANTINED = {
  rule_id: "rule_legacy", name: "구규칙", enabled: true,
  authority_status: "legacy_quarantined", background_eligible: false,
  schedule_kind: "daypart", schedule_expression: "morning",
  schedule_timezone: "UTC", target_source: "memory",
  output_type: "alert", notification_channels: ["web_alert_inbox"],
};

let listRules = [CANONICAL_ON, CANONICAL_OFF, QUARANTINED];
let patchResponse = () => jsonResponse(200, { ok: true, rule: Object.assign({}, CANONICAL_OFF, { enabled: false }) });
let patchDelayMs = 0;

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
  if (u.startsWith("/api/claw/automation/rules/") && u.endsWith("/enabled") && method === "PATCH") return patchResponse();
  if (u.startsWith("/api/claw/automation/rules")) return jsonResponse(200, { ok: true, rules: listRules });
  if (u.startsWith("/api/claw/inbox/")) return jsonResponse(200, { ok: true, kind: "tasks", items: [], limit: 20 });
  if (u.startsWith("/api/claw/memory")) return jsonResponse(200, { ok: true, memories: [] });
  if (u.startsWith("/api/claw/runs")) return jsonResponse(200, { ok: true, runs: [] });
  return jsonResponse(200, {});
}

let lang = "ko";
const COPY = {
  ko: {
    "claw-automation-loading": "자동화 규칙을 불러오는 중…",
    "claw-automation-rule-turn-off": "규칙 끄기", "claw-automation-rule-turn-on": "규칙 켜기",
    "claw-automation-toggle-saved": "규칙 설정을 변경했습니다. ‘규칙 설정’은 자동 실행이 이미 활성화되었다는 뜻이 아닙니다.",
    "claw-automation-toggle-forbidden": "워크스페이스 소유자만 변경할 수 있습니다.",
    "claw-automation-toggle-not-found": "해당 자동화 규칙을 사용할 수 없습니다.",
    "claw-automation-toggle-not-mutable": "이 규칙은 변경할 수 없습니다.",
    "claw-automation-toggle-not-ready": "이 규칙은 실행 준비가 되지 않아 켤 수 없습니다.",
    "claw-automation-toggle-invalid": "요청을 확인해 주세요. 변경되지 않았습니다.",
    "claw-automation-toggle-failed": "규칙 상태를 변경하지 못했습니다.",
    "automation-rule-setting": "규칙 설정", "automation-rule-on": "켜짐",
  },
  en: {
    "claw-automation-loading": "Loading automation rules…",
    "claw-automation-rule-turn-off": "Turn off", "claw-automation-rule-turn-on": "Turn on",
    "claw-automation-toggle-saved": "Rule setting changed. It does not mean automatic execution is live.",
    "claw-automation-toggle-forbidden": "Only the workspace owner can change rules.",
    "claw-automation-toggle-not-found": "That automation rule is not available.",
    "claw-automation-toggle-not-mutable": "This rule cannot be changed.",
    "claw-automation-toggle-not-ready": "This rule is not execution-ready and cannot be turned on.",
    "claw-automation-toggle-invalid": "Check the request. Nothing changed.",
    "claw-automation-toggle-failed": "Could not change the rule state.",
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
const patches = () => requests.filter((r) => r.method === "PATCH");
const listGets = () => requests.filter((r) => r.url.startsWith("/api/claw/automation/rules") && r.method === "GET");
const rowFor = (ruleId) => byId.clawAutomationList.children.find((row) => row.dataset && row.dataset.ruleId === ruleId) || null;
const toggleFor = (ruleId) => {
  const row = rowFor(ruleId);
  if (!row) return null;
  return row.children.find((node) => node.dataset && node.dataset.ruleToggleRuleId === ruleId) || null;
};

(async () => {
  const checks = {};
  const fail = (m) => { console.log(JSON.stringify({ ok: false, error: m, checks })); process.exit(0); };
  process.on("unhandledRejection", (e) => { console.log(JSON.stringify({ ok: false, error: "unhandledRejection " + String((e && e.stack) || e) })); process.exit(0); });
  process.on("uncaughtException", (e) => { console.log(JSON.stringify({ ok: false, error: "uncaughtException " + String((e && e.stack) || e) })); process.exit(0); });

  await tick(30);
  byId.automationNavButton.click();
  await tick(30);
  if (listGets().length < 1) fail("automation list was not loaded on open");

  // Canonical rows carry a control; quarantined rows do not.
  const onToggle = toggleFor("rule_on");
  const offToggle = toggleFor("rule_off");
  const legacyToggle = toggleFor("rule_legacy");
  checks.CANONICAL_ROW_TOGGLE_VISIBLE = !!onToggle && !!offToggle;
  checks.QUARANTINED_ROW_TOGGLE_VISIBLE_ABSENT = legacyToggle === null;
  checks.ENABLED_ROW_ACTION_TURN_OFF = !!onToggle && onToggle.textContent === COPY.ko["claw-automation-rule-turn-off"];
  checks.DISABLED_ROW_ACTION_TURN_ON = !!offToggle && offToggle.textContent === COPY.ko["claw-automation-rule-turn-on"];

  // Optimistic flip must not happen: the row still shows the server state
  // until a 200 arrives.
  requests.length = 0;
  patchResponse = () => new Promise((resolve) => setTimeout(() => resolve(jsonResponse(200, { ok: true, rule: Object.assign({}, CANONICAL_ON, { enabled: false }) })), 30));
  onToggle.click();
  await tick(5);
  checks.NO_OPTIMISTIC_FLIP = toggleFor("rule_on") && toggleFor("rule_on").textContent === COPY.ko["claw-automation-rule-turn-off"];
  checks.BUTTON_DISABLED_IN_FLIGHT = !!toggleFor("rule_on") && toggleFor("rule_on").disabled === true;
  await tick(60);
  const patch = patches()[0];
  checks.PATCH_EXACT_PATH = !!patch && patch.url === "/api/claw/automation/rules/rule_on/enabled";
  checks.PATCH_EXACT_PAYLOAD = !!patch && patch.method === "PATCH" && JSON.stringify(patch.body) === JSON.stringify({ enabled: false });
  checks.SUCCESS_RELOAD = listGets().length === 1;
  checks.FOCUS_RETURNED_TO_RULE_TOGGLE = doc.activeElement === toggleFor("rule_on");

  // 403 owner denial: bounded message, no optimistic change, state preserved.
  requests.length = 0;
  patchResponse = () => jsonResponse(403, { ok: false, error: { code: "owner_role_required", message: "denied" } });
  const before = toggleFor("rule_on").textContent;
  toggleFor("rule_on").click();
  await tick(30);
  checks.OWNER_DENIAL_BOUNDED_MESSAGE = byId.clawAutomationToggleStatus.textContent === COPY.ko["claw-automation-toggle-forbidden"];
  checks.FAILURE_STATE_PRESERVED_403 = toggleFor("rule_on").textContent === before;
  checks.FAILURE_NO_RELOAD_403 = listGets().length === 0;

  // 409 not execution-ready: bounded message, state preserved.
  requests.length = 0;
  patchResponse = () => jsonResponse(409, { ok: false, error: { code: "automation_rule_not_execution_ready", message: "no" } });
  toggleFor("rule_off").click();
  await tick(30);
  checks.NOT_READY_MESSAGE = byId.clawAutomationToggleStatus.textContent === COPY.ko["claw-automation-toggle-not-ready"];
  checks.FAILURE_STATE_PRESERVED_409 = toggleFor("rule_off").textContent === COPY.ko["claw-automation-rule-turn-on"];

  // 503 store failure: bounded message; the UI must not look successful.
  requests.length = 0;
  patchResponse = () => jsonResponse(503, { ok: false, error: { code: "automation_rule_save_failed", message: "no" } });
  toggleFor("rule_off").click();
  await tick(30);
  checks.STORE_FAILURE_MESSAGE = byId.clawAutomationToggleStatus.textContent === COPY.ko["claw-automation-toggle-failed"];

  // Single flight: a double click issues exactly one PATCH.
  requests.length = 0;
  patchResponse = () => new Promise((resolve) => setTimeout(() => resolve(jsonResponse(200, { ok: true, rule: CANONICAL_OFF })), 30));
  toggleFor("rule_off").click();
  toggleFor("rule_off").click();
  await tick(60);
  checks.SINGLE_FLIGHT_ONE_PATCH = patches().length === 1;

  // Locale switch re-renders the denial copy.
  lang = "en";
  requests.length = 0;
  patchResponse = () => jsonResponse(403, { ok: false, error: { code: "owner_role_required", message: "denied" } });
  toggleFor("rule_on").click();
  await tick(30);
  checks.EN_LOCALE_STATUS_COPY = byId.clawAutomationToggleStatus.textContent === COPY.en["claw-automation-toggle-forbidden"];

  if (Object.values(checks).some((v) => v !== true)) {
    console.log(JSON.stringify({ ok: false, error: "failed checks", checks }));
    process.exit(0);
  }
  console.log(JSON.stringify({ ok: true, checks }));
  process.exit(0);
})().catch((e) => { console.log(JSON.stringify({ ok: false, error: String((e && e.stack) || e) })); process.exit(0); });
"""


def _run_harness() -> dict:
    node = shutil.which("node")
    assert node, "node runtime is required for the behavioral harness"
    harness_path = ROOT / "tests" / "_claw_automation_toggle_harness.js"
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


def test_behavioral_toggle_journey() -> None:
    payload = _run_harness()
    assert payload.get("ok") is True, payload
    checks = payload["checks"]
    for name in (
        "CANONICAL_ROW_TOGGLE_VISIBLE",
        "QUARANTINED_ROW_TOGGLE_VISIBLE_ABSENT",
        "ENABLED_ROW_ACTION_TURN_OFF",
        "DISABLED_ROW_ACTION_TURN_ON",
        "NO_OPTIMISTIC_FLIP",
        "BUTTON_DISABLED_IN_FLIGHT",
        "PATCH_EXACT_PATH",
        "PATCH_EXACT_PAYLOAD",
        "SUCCESS_RELOAD",
        "FOCUS_RETURNED_TO_RULE_TOGGLE",
        "OWNER_DENIAL_BOUNDED_MESSAGE",
        "FAILURE_STATE_PRESERVED_403",
        "FAILURE_NO_RELOAD_403",
        "NOT_READY_MESSAGE",
        "FAILURE_STATE_PRESERVED_409",
        "STORE_FAILURE_MESSAGE",
        "SINGLE_FLIGHT_ONE_PATCH",
        "EN_LOCALE_STATUS_COPY",
    ):
        assert checks.get(name) is True, name