"""#3270 — Web bounded edit (name + schedule): UI contracts (static + behavioral).

1. Static structural contracts over the real markup, stylesheet, locale tables
   and app.js source: the edit form exists with the four editable fields, is
   hidden by default, carries ko/en copy, meets the touch/focus contract, posts
   exactly the four keys, never pre-fills anything outside the safe projection,
   and claims nothing about live execution.

2. A Node harness executing the REAL app.js with a recording fetch:

- ELIGIBLE_ROW_EDIT_VISIBLE / QUARANTINED_ROW_EDIT_ABSENT;
- EDIT_FORM_PREFILL (name/kind/expression/timezone) + focus on open;
- PATCH_EXACT_PATH / PATCH_EXACT_4_KEYS / PATCH_NO_AUTHORITY_FIELDS;
- NO_OPTIMISTIC_EDIT, SUCCESS_RELOAD, form close + focus restore;
- FAILURE_FORM_PRESERVED + bounded messages (403/409), no reload;
- CANCEL_CLOSES_FORM + CANCEL_FOCUS_RESTORE;
- SINGLE_FLIGHT_ONE_PATCH; EN locale copy.
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

EDIT_FORM_IDS = (
    "clawAutomationEditForm",
    "clawAutomationEditName",
    "clawAutomationEditKind",
    "clawAutomationEditDaypartField",
    "clawAutomationEditDaypart",
    "clawAutomationEditIntervalField",
    "clawAutomationEditInterval",
    "clawAutomationEditCronField",
    "clawAutomationEditCron",
    "clawAutomationEditTimezone",
    "clawAutomationEditStatus",
    "clawAutomationEditSubmit",
    "clawAutomationEditCancel",
)

EDIT_LOCALE_KEYS = (
    "claw-automation-edit-button",
    "claw-automation-edit-summary",
    "claw-automation-edit-hint",
    "claw-automation-edit-cancel",
    "claw-automation-edit-submit",
    "claw-automation-edit-saved",
    "claw-automation-edit-invalid",
    "claw-automation-edit-failed",
)


def _app_source() -> str:
    return APP_JS.read_text(encoding="utf-8")


def _html_source() -> str:
    return INDEX_HTML.read_text(encoding="utf-8")


# ── static structural contracts ────────────────────────────────────────────


def test_edit_form_is_declared_hidden_with_only_the_editable_fields() -> None:
    html = _html_source()
    for token in EDIT_FORM_IDS:
        assert f'id="{token}"' in html, token
    form = html.split('id="clawAutomationEditForm"', 1)[1].split("</form>", 1)[0]
    assert "hidden" in form.split(">", 1)[0]
    # name + schedule kind + the kind-aware expression controls + timezone.
    for field in ('name="name"', 'name="schedule_kind"', 'name="daypart"', 'name="interval"', 'name="cron"', 'name="schedule_timezone"'):
        assert field in form, field
    for forbidden in ("task", "execution_intent", "owner_ref", "enabled", "target_source"):
        assert f'name="{forbidden}"' not in form, forbidden


def test_edit_status_is_aria_live_and_locales_cover_every_key() -> None:
    html = _html_source()
    assert 'id="clawAutomationEditStatus"' in html
    assert 'aria-live="polite"' in html
    locale = LOCALE_JS.read_text(encoding="utf-8")
    ko = locale.split("ko: {", 1)[1].split("en: {", 1)[0]
    en = locale.split("en: {", 1)[1]
    for key in EDIT_LOCALE_KEYS:
        assert f'"{key}"' in ko, key
        assert f'"{key}"' in en, key


def test_edit_control_meets_touch_and_focus_contract() -> None:
    css = WORKSPACE_CSS.read_text(encoding="utf-8")
    block = css.split(".claw-automation-rule-edit {", 1)[1].split("}", 1)[0]
    assert "min-height: 44px" in block
    assert ":focus-visible" in css


def test_edit_patch_payload_is_exactly_the_four_editable_fields() -> None:
    js = _app_source()
    block = js.split("#3270 bounded edit (name + schedule only)", 1)[1].split(
        "#3262 owner-gated enable/disable", 1
    )[0]
    assert 'method: "PATCH"' in block
    keys = [k for k in ("name", "schedule_kind", "schedule_expression", "schedule_timezone") if f"{k}:" in block]
    assert sorted(keys) == sorted(["name", "schedule_kind", "schedule_expression", "schedule_timezone"])
    for forbidden in ("task:", "execution_intent:", "owner_ref:", "enabled:", "target_source:"):
        assert forbidden not in block, forbidden
    # Prefill reads only projected display fields.
    assert "rule.name" in block and "rule.schedule_kind" in block
    assert "rule.schedule_expression" in block and "rule.schedule_timezone" in block
    assert "rule.execution_intent" not in block


def test_edit_never_claims_live_execution() -> None:
    js = _app_source()
    html = _html_source()
    locale = LOCALE_JS.read_text(encoding="utf-8")
    for overclaim in (
        "자동 실행이 시작되었습니다",
        "scheduler activated",
        "running automatically now",
        "Production scheduler activated",
    ):
        assert overclaim not in js
        assert overclaim not in html
        assert overclaim not in locale
    assert 'id="clawAutomationSchedulerNote"' in html


def test_edit_button_is_rendered_only_in_the_canonical_branch() -> None:
    js = _app_source()
    render = js.split("function renderClawAutomationRules", 1)[1].split(
        "async function loadClawAutomationRules", 1
    )[0]
    assert "claw-automation-rule-edit" in render
    assert render.index("background_eligible !== true") < render.index("claw-automation-rule-edit")


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
  "clawAutomationEditForm","clawAutomationEditName","clawAutomationEditKind",
  "clawAutomationEditDaypartField","clawAutomationEditDaypart","clawAutomationEditIntervalField",
  "clawAutomationEditInterval","clawAutomationEditCronField","clawAutomationEditCron",
  "clawAutomationEditTimezone","clawAutomationEditStatus","clawAutomationEditSubmit","clawAutomationEditCancel",
].forEach((id) => add(id, "div"));

byId.clawAutomation.hidden = true;
byId.clawAutomationToggleStatus.hidden = true;
byId.clawAutomationCreateStatus.hidden = true;
byId.clawAutomationEditForm.hidden = true;
byId.clawAutomationEditStatus.hidden = true;
byId.clawAutomationCreateKind.value = "daypart";
byId.clawAutomationCreateDaypart.value = "morning";
byId.clawAutomationCreateTarget.value = "memory";
byId.clawAutomationCreateOutput.value = "alert";
byId.clawAutomationEditKind.value = "daypart";
byId.clawAutomationEditDaypart.value = "morning";

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
const CANONICAL_OFF = Object.assign({}, CANONICAL_ON, { rule_id: "rule_off", name: "저녁 요약", enabled: false, schedule_expression: "evening" });
const QUARANTINED = {
  rule_id: "rule_legacy", name: "구규칙", enabled: true,
  authority_status: "legacy_quarantined", background_eligible: false,
  schedule_kind: "daypart", schedule_expression: "morning",
  schedule_timezone: "UTC", target_source: "memory",
  output_type: "alert", notification_channels: ["web_alert_inbox"],
};

let listRules = [CANONICAL_ON, CANONICAL_OFF, QUARANTINED];
let patchResponse = () => jsonResponse(200, { ok: true, rule: CANONICAL_ON });

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
  if (u.startsWith("/api/claw/automation/rules/") && u.endsWith("/enabled")) return patchResponse();
  if (u.startsWith("/api/claw/automation/rules/") && method === "PATCH") return patchResponse();
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
    "claw-automation-edit-button": "수정",
    "claw-automation-toggle-saved": "규칙 설정을 변경했습니다.",
    "claw-automation-toggle-forbidden": "워크스페이스 소유자만 변경할 수 있습니다.",
    "claw-automation-toggle-not-found": "해당 자동화 규칙을 사용할 수 없습니다.",
    "claw-automation-toggle-not-mutable": "이 규칙은 변경할 수 없습니다.",
    "claw-automation-toggle-not-ready": "이 규칙은 실행 준비가 되지 않아 켤 수 없습니다.",
    "claw-automation-toggle-invalid": "요청을 확인해 주세요. 변경되지 않았습니다.",
    "claw-automation-toggle-failed": "규칙 상태를 변경하지 못했습니다.",
    "claw-automation-edit-saved": "규칙을 수정했습니다.",
    "claw-automation-edit-invalid": "입력 값을 확인해 주세요. 변경되지 않았습니다.",
    "claw-automation-edit-failed": "규칙을 수정하지 못했습니다.",
    "automation-rule-setting": "규칙 설정", "automation-rule-on": "켜짐",
  },
  en: {
    "claw-automation-loading": "Loading automation rules…",
    "claw-automation-rule-turn-off": "Turn off", "claw-automation-rule-turn-on": "Turn on",
    "claw-automation-edit-button": "Edit",
    "claw-automation-toggle-saved": "Rule setting changed.",
    "claw-automation-toggle-forbidden": "Only the workspace owner can change rules.",
    "claw-automation-toggle-not-found": "That automation rule is not available.",
    "claw-automation-toggle-not-mutable": "This rule cannot be changed.",
    "claw-automation-toggle-not-ready": "This rule is not execution-ready and cannot be turned on.",
    "claw-automation-toggle-invalid": "Check the request. Nothing changed.",
    "claw-automation-toggle-failed": "Could not change the rule state.",
    "claw-automation-edit-saved": "Rule updated.",
    "claw-automation-edit-invalid": "Check the input values. Nothing changed.",
    "claw-automation-edit-failed": "Could not update the rule.",
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
const listGets = () => requests.filter((r) => r.url.startsWith("/api/claw/automation/rules") && r.method === "GET");
const edits = () => requests.filter((r) => r.method === "PATCH" && !r.url.endsWith("/enabled"));
const rowFor = (ruleId) => byId.clawAutomationList.children.find((row) => row.dataset && row.dataset.ruleId === ruleId) || null;
const editButtonFor = (ruleId) => {
  const row = rowFor(ruleId);
  if (!row) return null;
  return row.children.find((n) => n.dataset && n.dataset.ruleEditRuleId === ruleId) || null;
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

  checks.ELIGIBLE_ROW_EDIT_VISIBLE = !!editButtonFor("rule_on") && !!editButtonFor("rule_off");
  checks.QUARANTINED_ROW_EDIT_ABSENT = editButtonFor("rule_legacy") === null;
  checks.EDIT_FORM_HIDDEN_INITIALLY = byId.clawAutomationEditForm.hidden === true;

  editButtonFor("rule_on").click();
  await tick(5);
  checks.EDIT_FORM_OPENS = byId.clawAutomationEditForm.hidden === false;
  checks.EDIT_FORM_PREFILL_NAME = byId.clawAutomationEditName.value === "아침 요약";
  checks.EDIT_FORM_PREFILL_KIND = byId.clawAutomationEditKind.value === "daypart";
  checks.EDIT_FORM_PREFILL_EXPRESSION = byId.clawAutomationEditDaypart.value === "morning";
  checks.EDIT_FORM_PREFILL_TIMEZONE = byId.clawAutomationEditTimezone.value === "UTC";
  checks.EDIT_FORM_FOCUS_NAME = doc.activeElement === byId.clawAutomationEditName;

  // Submit -> PATCH with exactly four keys; nothing changes locally first.
  requests.length = 0;
  const rowBefore = rowFor("rule_on").children.map((c) => c.textContent).join("|");
  patchResponse = () => new Promise((r) => setTimeout(() => r(jsonResponse(200, { ok: true, rule: CANONICAL_ON })), 30));
  byId.clawAutomationEditName.value = "저녁 요약";
  byId.clawAutomationEditDaypart.value = "evening";
  byId.clawAutomationEditTimezone.value = "UTC";
  byId.clawAutomationEditForm.requestSubmit();
  await tick(5);
  checks.NO_OPTIMISTIC_EDIT = rowFor("rule_on").children.map((c) => c.textContent).join("|") === rowBefore;
  await tick(60);
  const patch = edits()[0];
  checks.PATCH_EXACT_PATH = !!patch && patch.url === "/api/claw/automation/rules/rule_on";
  checks.PATCH_EXACT_4_KEYS = !!patch && JSON.stringify(Object.keys(patch.body).sort()) === JSON.stringify(["name","schedule_expression","schedule_kind","schedule_timezone"]);
  checks.PATCH_NO_AUTHORITY_FIELDS = !!patch && !Object.keys(patch.body).some((k) => ["task","execution_intent","owner_ref","enabled","target_source","output_type","notification_channels","workspace_id","canonical_subject_id"].includes(k));
  checks.SUCCESS_RELOAD = listGets().length === 1;
  checks.SUCCESS_FORM_CLOSED = byId.clawAutomationEditForm.hidden === true;
  checks.SUCCESS_FOCUS_RESTORE = doc.activeElement === editButtonFor("rule_on");

  // 403: the form keeps its values; rows unchanged; bounded message.
  requests.length = 0;
  editButtonFor("rule_off").click();
  await tick(5);
  byId.clawAutomationEditName.value = "바뀌지 않은 이름";
  patchResponse = () => jsonResponse(403, { ok: false, error: { code: "owner_role_required", message: "denied" } });
  byId.clawAutomationEditForm.requestSubmit();
  await tick(30);
  checks.FAILURE_FORM_PRESERVED = byId.clawAutomationEditForm.hidden === false && byId.clawAutomationEditName.value === "바뀌지 않은 이름";
  checks.FAILURE_BOUNDED_MESSAGE = byId.clawAutomationEditStatus.textContent === COPY.ko["claw-automation-toggle-forbidden"];
  checks.FAILURE_NO_RELOAD = listGets().length === 0;

  // 409 not execution-ready: bounded message, values kept.
  patchResponse = () => jsonResponse(409, { ok: false, error: { code: "automation_rule_not_execution_ready", message: "no" } });
  byId.clawAutomationEditForm.requestSubmit();
  await tick(30);
  checks.NOT_READY_MESSAGE = byId.clawAutomationEditStatus.textContent === COPY.ko["claw-automation-toggle-not-ready"];
  checks.NOT_READY_FORM_PRESERVED = byId.clawAutomationEditForm.hidden === false;

  // Cancel: closes the form and returns focus to that row's Edit button.
  byId.clawAutomationEditCancel.click();
  await tick(5);
  checks.CANCEL_CLOSES_FORM = byId.clawAutomationEditForm.hidden === true;
  checks.CANCEL_FOCUS_RESTORE = doc.activeElement === editButtonFor("rule_off");

  // Single flight: a double submit issues exactly one PATCH.
  requests.length = 0;
  editButtonFor("rule_off").click();
  await tick(5);
  patchResponse = () => new Promise((r) => setTimeout(() => r(jsonResponse(200, { ok: true, rule: CANONICAL_OFF })), 30));
  byId.clawAutomationEditForm.requestSubmit();
  byId.clawAutomationEditForm.requestSubmit();
  await tick(60);
  checks.SINGLE_FLIGHT_ONE_PATCH = edits().length === 1;

  // Locale switch re-renders the bounded copy.
  lang = "en";
  patchResponse = () => jsonResponse(400, { ok: false, error: { code: "unexpected_field", message: "no" } });
  editButtonFor("rule_on").click();
  await tick(5);
  byId.clawAutomationEditForm.requestSubmit();
  await tick(30);
  checks.EN_LOCALE_EDIT_INVALID = byId.clawAutomationEditStatus.textContent === COPY.en["claw-automation-edit-invalid"];

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
    harness_path = ROOT / "tests" / "_claw_automation_edit_harness.js"
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


def test_behavioral_edit_journey() -> None:
    payload = _run_harness()
    assert payload.get("ok") is True, payload
    for name in (
        "ELIGIBLE_ROW_EDIT_VISIBLE",
        "QUARANTINED_ROW_EDIT_ABSENT",
        "EDIT_FORM_HIDDEN_INITIALLY",
        "EDIT_FORM_OPENS",
        "EDIT_FORM_PREFILL_NAME",
        "EDIT_FORM_PREFILL_KIND",
        "EDIT_FORM_PREFILL_EXPRESSION",
        "EDIT_FORM_PREFILL_TIMEZONE",
        "EDIT_FORM_FOCUS_NAME",
        "NO_OPTIMISTIC_EDIT",
        "PATCH_EXACT_PATH",
        "PATCH_EXACT_4_KEYS",
        "PATCH_NO_AUTHORITY_FIELDS",
        "SUCCESS_RELOAD",
        "SUCCESS_FORM_CLOSED",
        "SUCCESS_FOCUS_RESTORE",
        "FAILURE_FORM_PRESERVED",
        "FAILURE_BOUNDED_MESSAGE",
        "FAILURE_NO_RELOAD",
        "NOT_READY_MESSAGE",
        "NOT_READY_FORM_PRESERVED",
        "CANCEL_CLOSES_FORM",
        "CANCEL_FOCUS_RESTORE",
        "SINGLE_FLIGHT_ONE_PATCH",
        "EN_LOCALE_EDIT_INVALID",
    ):
        assert payload["checks"].get(name) is True, name