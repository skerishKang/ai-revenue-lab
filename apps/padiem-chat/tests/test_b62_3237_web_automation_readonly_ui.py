"""#3237 — Web Claw Automation read-only UI contracts.

Two layers:

1. Static contracts: the sidebar entry, the section and the locale keys exist,
   the read-only API is called, and no create/edit/toggle/run control is
   rendered or requested.
2. A Node harness executing the REAL app.js in a vm DOM shim, proving the
   loading / ready / empty / error / retry states and that the server rows are
   rendered through safe sinks (textContent), never innerHTML.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "static/app.js"
CAPABILITIES_JS = ROOT / "static/attachment-capabilities.js"
INDEX_HTML = ROOT / "static/index.html"
LOCALE_JS = ROOT / "static/locale.js"

RULES_PATH = "/api/claw/automation/rules"


# ── static contracts ───────────────────────────────────────────────────────


def test_sidebar_entry_and_section_exist() -> None:
    html = INDEX_HTML.read_text(encoding="utf-8")
    assert 'id="automationNavButton"' in html
    assert 'data-locale-key="nav-automation"' in html
    assert 'id="clawAutomation"' in html
    assert 'id="clawAutomationList"' in html
    assert 'id="clawAutomationLoading"' in html
    assert 'id="clawAutomationError"' in html
    assert 'id="clawAutomationEmpty"' in html
    assert 'id="clawAutomationRetry"' in html
    # The section is a real labelled region, not a bare div.
    assert 'aria-labelledby="clawAutomationTitle"' in html
    assert 'id="clawAutomationTitle"' in html
    # Status region announces the load outcome.
    assert 'aria-live="polite"' in html


def test_ui_reads_only_the_read_only_endpoint() -> None:
    source = APP_JS.read_text(encoding="utf-8")
    assert f'fetch("{RULES_PATH}"' in source
    # The automation loader must never use a write verb.
    loader = source.split("async function loadClawAutomationRules()")[1].split("\n  }")[0]
    assert "method:" not in loader
    assert RULES_PATH in loader


def test_no_rule_mutation_control_exists_in_the_ui() -> None:
    source = APP_JS.read_text(encoding="utf-8")
    block = source.split("--- #3237 read-only automation rule catalogue")[1]
    block = block.split("if (clawAutomationRetry)")[0]
    for forbidden in (
        "POST",
        "PUT",
        "PATCH",
        "DELETE",
        "set_rule_enabled",
        "createRule",
        "updateRule",
        "deleteRule",
        "runNow",
    ):
        assert forbidden not in block, forbidden
    # The rendered row carries display text only — no interactive control.
    assert "row.append(title, meta);" in block


def test_skill_surface_untouched_and_no_b66_import() -> None:
    source = APP_JS.read_text(encoding="utf-8")
    html = INDEX_HTML.read_text(encoding="utf-8")
    # #3235 Skills work is on HOLD and must not leak into this slice.
    assert "/api/claw/skills" not in source
    assert "claw_skill_routes" not in source
    assert "business-66" not in source
    assert "quote-skill" not in html


def test_locale_keys_exist_in_both_languages() -> None:
    locale = LOCALE_JS.read_text(encoding="utf-8")
    for key in (
        "nav-automation",
        "claw-automation-title",
        "claw-automation-help",
        "claw-automation-loading",
        "claw-automation-error",
        "claw-automation-empty",
        "automation-rule-enabled",
        "automation-rule-disabled",
    ):
        assert f'"{key}"' in locale, key
    # Korean and English tables each define the Automation copy.
    assert locale.count('"nav-automation"') == 2


def test_app_js_never_uses_inner_html() -> None:
    source = APP_JS.read_text(encoding="utf-8")
    assert "innerHTML" not in source
    assert "insertAdjacentHTML" not in source


# ── behavioral proof via Node harness executing real app.js ────────────────

_HARNESS = r"""
const fs = require("fs");
const vm = require("vm");
const APP = fs.readFileSync(process.argv[2], "utf8");
const CAPS = fs.readFileSync(process.argv[3], "utf8");
const FIXTURE = JSON.parse(process.argv[4]);

function makeEl(tag) {
  const el = {
    tagName: tag, id: "", className: "", textContent: "", hidden: false, open: false,
    disabled: false, value: "", children: [], listeners: {}, dataset: {},
    style: {}, scrollTop: 0, scrollHeight: 0, clientHeight: 0,
    options: [], selectedIndex: 0, files: [], parentNode: null,
    classList: { add() {}, remove() {}, contains() { return false; }, toggle() {} },
  };
  el.setAttribute = (k, v) => { el[k] = String(v); };
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
  el.showModal = () => { el.open = true; el.hidden = false; };
  el.close = () => { el.open = false; };
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
  "historySection","historyList","historyEmpty","projectsNavButton","filesNavButton","projectsBadge","projectsSection",
  "projectsList","projectsEmpty","projectCreateButton","projectBanner","activeProjectName","activeProjectFiles",
  "editProjectButton","exitProjectButton","projectDialog","projectForm","projectDialogTitle","projectDialogClose",
  "projectDialogCancel","projectNameInput","projectInstructionsInput","projectFormError","projectSaveButton",
  "projectFilesPanel","projectFileInput","projectFilesList","projectFilesEmpty","projectFileStatus",
  "clawNavButton","clawWorkspace","clawManualForm","clawChannel","clawAction","clawSender","clawRequestText",
  "clawResultArea","clawResultPreview","clawResultCard","clawResultEmpty","clawResultKind","clawGenerateBtn",
  "clawExecuteButton","clawResultBadge","clawResultDocx","clawStatus","clawArtifactMeta",
  "clawArtifactName","clawArtifactSize","clawResultSuccessNote","clawResultHint","clawExecuteHint",
  "clawInbox","clawInboxTitle","clawInboxLoading","clawInboxError","clawInboxEmpty","clawInboxList","clawInboxRetry",
  "automationNavButton","clawAutomation","clawAutomationLoading","clawAutomationError","clawAutomationEmpty",
  "clawAutomationList","clawAutomationRetry",
].forEach((id) => add(id, "div"));
const shell = add("app-shell", "div");
shell.dataset = { state: "home" };
const accountContainer = add("sidebar-account", "div");
byId.clawChannel.options = [{ textContent: "KakaoTalk" }];
byId.clawChannel.value = "kakao";
byId.clawAction.options = [{ textContent: "draft" }];
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

const requests = [];
let ruleCalls = 0;
let failNext = FIXTURE.failFirst;
function jsonResponse(status, obj) { return { ok: status >= 200 && status < 300, status, json: async () => obj }; }
async function fetchImpl(url, opts) {
  opts = opts || {};
  const method = (opts.method || "GET").toUpperCase();
  const u = String(url);
  requests.push({ url: u, method });
  if (u.startsWith("/api/auth/status")) return jsonResponse(200, FIXTURE.auth);
  if (u === FIXTURE.rulesPath) {
    ruleCalls += 1;
    if (failNext) { failNext = false; return jsonResponse(503, { ok: false }); }
    return jsonResponse(200, { ok: true, rules: FIXTURE.rules });
  }
  if (u.startsWith("/api/projects")) return jsonResponse(200, { projects: [] });
  if (u.startsWith("/api/conversations")) return jsonResponse(200, { conversations: [] });
  return jsonResponse(200, {});
}

const sandbox = {
  document: doc,
  fetch: fetchImpl,
  setTimeout, clearTimeout, console,
  CustomEvent: class {},
  location: { href: "http://localhost/", assign() {} },
  addEventListener() {},
  __padiemLocale: { text: (k) => k },
  PadiemChatLifecycle: { states: { IDLE: "idle", STREAMING: "streaming", COMPLETED: "completed", FAILED: "failed", CANCELLED: "cancelled", TIMED_OUT: "timed_out" }, set() {} },
  PadiemConfirmDialog: { confirm: async () => true },
  PadiemChatTransport: { requestCompleted: async () => ({}), requestStreaming: async () => ({}), readSseEvents: async () => {}, errorFor: () => new Error("x") },
  PadiemChatConversationState: { reset() {}, setConversationId() {}, getConversationId() { return null; }, outboundWithUser: () => [], commitAssistant() {}, setSkill() {}, getSkill: () => "auto" },
  FileReader: class { addEventListener() {} },
};
sandbox.window = sandbox;
vm.createContext(sandbox);
// Real dependency order: app.js reads attachment-capabilities.js at load time.
vm.runInContext(CAPS, sandbox, { filename: "attachment-capabilities.js" });
vm.runInContext(APP, sandbox, { filename: "app.js" });

function collectText(root) {
  let out = root.textContent || "";
  (root.children || []).forEach((c) => { out += " " + collectText(c); });
  return out;
}
function rowCount() { return (byId.clawAutomationList.children || []).length; }
function clickAutomationNav() {
  (byId.automationNavButton.listeners.click || []).forEach((fn) => fn({ preventDefault() {} }));
}

(async () => {
  const fail = (m) => { console.log(JSON.stringify({ ok: false, error: m })); process.exit(0); };
  const tick = (ms) => new Promise((r) => setTimeout(r, ms));
  await tick(60);

  // The Automation entry follows the same signed-in gate as Tasks/Alerts.
  // The gate is read from the DOM after auth resolution, not from the fixture.
  const navDisabled = byId.automationNavButton.disabled === true;
  const navAria = byId.automationNavButton.getAttribute("aria-disabled");
  if (FIXTURE.mode === "signed_out") {
    if (!navDisabled) fail("SIGNED_OUT_NAV_ENABLED");
    if (navAria !== "true") fail("SIGNED_OUT_NAV_ARIA_ENABLED");
    // Signed out: the section must not be reachable and no rule is fetched.
    if (ruleCalls !== 0) fail("SIGNED_OUT_RULE_FETCHED");
    console.log(JSON.stringify({ ok: true, rows: 0, ruleCalls }));
    process.exit(0);
  }
  if (navDisabled) fail("SIGNED_IN_NAV_DISABLED");
  if (navAria !== "false") fail("SIGNED_IN_NAV_ARIA_DISABLED");

  if (FIXTURE.mode === "error_then_retry") {
    clickAutomationNav();
    await tick(40);
    if (byId.clawAutomation.hidden !== false) fail("SECTION_NOT_SHOWN");
    if (byId.clawAutomationError.hidden !== false) fail("ERROR_NOT_SHOWN");
    if (rowCount() !== 0) fail("ERROR_MUST_NOT_RENDER_ROWS");
    const before = ruleCalls;
    (byId.clawAutomationRetry.listeners.click || []).forEach((fn) => fn({ preventDefault() {} }));
    await tick(40);
    if (ruleCalls !== before + 1) fail("RETRY_DID_NOT_RELOAD");
    if (rowCount() !== FIXTURE.rules.length) fail("RETRY_ROWS_MISSING:" + rowCount());
    if (byId.clawAutomationError.hidden !== true) fail("ERROR_NOT_CLEARED_AFTER_RETRY");
  } else {
    clickAutomationNav();
    await tick(40);
    if (byId.clawAutomation.hidden !== false) fail("SECTION_NOT_SHOWN");
    if (byId.clawAutomationLoading.hidden !== true) fail("LOADING_NOT_CLEARED");
    if (byId.clawAutomationError.hidden !== true) fail("ERROR_SHOWN_ON_SUCCESS");
    if (FIXTURE.rules.length === 0) {
      if (byId.clawAutomationEmpty.hidden !== false) fail("EMPTY_NOT_SHOWN");
      if (rowCount() !== 0) fail("EMPTY_MUST_HAVE_NO_ROWS");
    } else {
      if (byId.clawAutomationEmpty.hidden !== true) fail("EMPTY_SHOWN_WITH_ROWS");
      if (rowCount() !== FIXTURE.rules.length) fail("ROW_COUNT_WRONG:" + rowCount());
      const text = collectText(byId.clawAutomationList);
      for (const rule of FIXTURE.rules) {
        if (!text.includes(rule.name)) fail("RULE_NAME_MISSING:" + rule.name);
      }
      // A row must be a non-interactive container: no BUTTON inside.
      for (const row of byId.clawAutomationList.children) {
        if (row.tagName === "BUTTON") fail("ROW_IS_A_BUTTON");
        for (const child of row.children || []) {
          if (child.tagName === "BUTTON") fail("ROW_CONTAINS_BUTTON");
        }
      }
    }
  }

  const ruleRequests = requests.filter((r) => r.url === FIXTURE.rulesPath);
  if (ruleRequests.some((r) => r.method !== "GET")) fail("NON_GET_RULE_REQUEST");
  const text = collectText(byId.clawAutomation);
  for (const leak of FIXTURE.forbidden || []) {
    if (text.includes(leak)) fail("LEAKED_IN_DOM:" + leak);
  }
  console.log(JSON.stringify({ ok: true, rows: rowCount(), ruleCalls }));
  process.exit(0);
})().catch((e) => { console.log(JSON.stringify({ ok: false, error: String((e && e.stack) || e) })); });
"""


def _run(mode: str, *, auth: dict, rules: list, fail_first: bool = False, rules_path: str = RULES_PATH) -> dict:
    node = shutil.which("node")
    assert node, "node runtime is required for the behavioral harness"
    harness_path = ROOT / "tests" / f"_b62_3237_ui_harness_{mode}.js"
    harness_path.write_text(_HARNESS, encoding="utf-8")
    fixture = json.dumps(
        {
            "mode": mode,
            "auth": auth,
            "rules": rules,
            "failFirst": fail_first,
            "rulesPath": rules_path,
            "forbidden": ["workspace_id", "execution_intent", "repository_ref", "owner_ref"],
        },
        ensure_ascii=False,
    )
    try:
        result = subprocess.run(
            [node, str(harness_path), str(APP_JS), str(CAPABILITIES_JS), fixture],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(ROOT),
        )
    finally:
        harness_path.unlink(missing_ok=True)
    assert result.returncode == 0, f"harness crashed: {result.stderr[-1500:]}"
    line = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else "{}"
    payload = json.loads(line)
    assert payload.get("ok") is True, f"behavior failed: {payload}"
    return payload


_SIGNED_IN = {
    "ready": True,
    "authenticated": True,
    "user": {"name": "owner"},
    "history_ready": True,
    "project_files_ready": True,
}
_SIGNED_OUT = {
    "ready": True,
    "authenticated": False,
    "user": None,
    "history_ready": False,
    "project_files_ready": False,
}
_RULES = [
    {
        "rule_id": "rule_morning",
        "name": "아침 메모 정리",
        "enabled": True,
        "schedule_kind": "daypart",
        "schedule_expression": "morning",
        "schedule_timezone": "Asia/Seoul",
        "target_source": "memory",
        "output_type": "alert",
        "notification_channels": ["web_alert_inbox"],
    },
    {
        "rule_id": "rule_evening",
        "name": "저녁 보고",
        "enabled": False,
        "schedule_kind": "daypart",
        "schedule_expression": "evening",
        "schedule_timezone": "UTC",
        "target_source": "inbox",
        "output_type": "report",
        "notification_channels": ["web_alert_inbox"],
    },
]


def test_signed_in_ready_state_renders_server_rows() -> None:
    payload = _run("ready", auth=_SIGNED_IN, rules=_RULES)
    assert payload["rows"] == 2


def test_empty_catalogue_state() -> None:
    _run("empty", auth=_SIGNED_IN, rules=[])


def test_error_state_then_explicit_retry() -> None:
    _run("error_then_retry", auth=_SIGNED_IN, rules=_RULES, fail_first=True)


def test_signed_out_entry_stays_disabled() -> None:
    _run("signed_out", auth=_SIGNED_OUT, rules=_RULES)
