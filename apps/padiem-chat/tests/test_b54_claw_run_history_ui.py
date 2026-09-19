"""B54 Claw recent-run presentation contracts.

The owner-scoped, bounded run-history route (``GET /api/claw/runs``, #2317) had
no browser consumer: a Claw execution wrote history (with its artifact
reference) but the surface was unreachable after reload. This file guards the
presentation slice that consumes that existing route.

Static string assertions alone do not prove behavior, so this file also runs a
Node harness that executes the REAL app.js against a minimal DOM shim with a
recording fetch. The harness proves actual behavior:

- RUN_HISTORY_NOT_FETCHED_OUTSIDE_CLAW=PASS
- RUN_HISTORY_FETCHED_ON_CLAW_OPEN=PASS
- RUN_HISTORY_SINGLE_FLIGHT=PASS
- RUN_CARD_RENDERS_SUMMARY_AND_ARTIFACT=PASS
- RUN_HISTORY_EMPTY_STATE=PASS
- RUN_HISTORY_ERROR_RETRY=PASS
- ARTIFACT_REDOWNLOAD_REUSES_BOUNDED_ROUTE=PASS
- RUN_HISTORY_HIDDEN_IN_INBOX_VIEW=PASS
- SENSITIVE_FIELD_DOM_PROJECTION=0

The slice is presentation-only: no run/history truth is minted in the browser,
and no new route, store, schema, or provider call is introduced.
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
APP_FACTORY = ROOT / "app/app_factory.py"

RUN_HISTORY_KEYS = (
    "claw-runs-title",
    "claw-runs-kicker",
    "claw-runs-tagline",
    "claw-runs-refresh-aria",
    "claw-runs-loading",
    "claw-runs-empty",
    "claw-runs-error",
    "claw-runs-download",
    "claw-runs-status-completed",
)


def _app_source() -> str:
    return APP_JS.read_text(encoding="utf-8")


# ── static structural contracts ────────────────────────────────────────────


def test_run_history_surface_is_declared_inside_the_claw_workspace() -> None:
    html = INDEX_HTML.read_text(encoding="utf-8")
    for token in (
        'id="clawRunHistory"',
        'id="clawRunHistoryRefresh"',
        'id="clawRunHistoryLoading"',
        'id="clawRunHistoryError"',
        'id="clawRunHistoryList"',
        'id="clawRunHistoryEmpty"',
    ):
        assert token in html
    # The workspace-level heading must stay an h2: the shell keeps one h1.
    assert 'class="claw-workspace-title" id="clawRunHistoryTitle"' in html
    assert html.count("<h1") == 1
    # The surface is owner-scoped and starts hidden.
    assert 'id="clawRunHistory" aria-labelledby="clawRunHistoryTitle" hidden' in html


def test_accessible_loading_error_empty_and_refresh_states() -> None:
    html = INDEX_HTML.read_text(encoding="utf-8")
    assert 'id="clawRunHistoryLoading"' in html and 'role="status"' in html
    assert 'id="clawRunHistoryError"' in html and 'role="alert"' in html
    assert 'id="clawRunHistoryRefresh"' in html
    app = _app_source()
    assert 'setClawRunHistoryStatus("")' in app
    assert 'clawRunHistoryError.dataset.state = "error";' in app
    assert 'clawRunHistoryError.removeAttribute("data-state");' in app


def test_consumes_the_existing_owner_scoped_route_without_new_authority() -> None:
    app = _app_source()
    assert 'fetch("/api/claw/runs?limit=10"' in app
    # Reuses the single bounded artifact route rather than a second download path.
    assert "/api/claw/manual-intake/artifact/" in app
    assert app.count("/api/claw/manual-intake/artifact/") == 1
    routes = CLAW_ROUTES.read_text(encoding="utf-8")
    assert "async def claw_runs_history(request: Request)" in routes
    factory = APP_FACTORY.read_text(encoding="utf-8")
    # Reuses the existing route registration unchanged: no second run route.
    assert factory.count('/api/claw/runs"') == 1
    assert 'Route("/api/claw/runs", claw_runs_history, methods=["GET"])' in factory


def test_presentation_does_not_mint_run_truth_in_the_browser() -> None:
    app = _app_source()
    # No local persistence, no interception, no client-side identity/authority.
    for token in ("localStorage", "sessionStorage", "indexedDB", "cookieStore", "caches.open", "MutationObserver", "window.fetch ="):
        assert token not in app
    for token in ("user_id", "workspace_id", "tenant_id"):
        assert token not in app
    # The client never derives run status: unknown tokens stay raw, never "completed".
    assert "function clawRunStatusLabel(status)" in app
    assert "return text === key ? raw : text;" in app


def test_single_flight_and_visibility_guards_are_present() -> None:
    app = _app_source()
    assert "let clawRunHistoryInFlight = false;" in app
    assert "if (clawRunHistoryInFlight) return;" in app
    # Unguarded fetch is only reachable through the single-flight wrapper.
    assert app.count("await fetchClawRunHistory();") == 1
    assert 'const show = authState.authenticated === true' in app
    assert 'clawWorkspace?.dataset.view !== "inbox"' in app


def test_auth_loss_clears_rendered_run_history_dom() -> None:
    app = _app_source()
    assert 'const runHistoryList = document.getElementById("clawRunHistoryList");' in app
    assert "if (runHistoryList) runHistoryList.replaceChildren();" in app
    assert "if (runHistory) runHistory.hidden = true;" in app


def test_locale_keys_are_declared_for_both_languages() -> None:
    locale = LOCALE_JS.read_text(encoding="utf-8")
    ko_block = locale.split("en: {", 1)[0]
    en_block = locale.split("en: {", 1)[1]
    for key in RUN_HISTORY_KEYS:
        assert f'"{key}"' in ko_block, key
        assert f'"{key}"' in en_block, key
    html = INDEX_HTML.read_text(encoding="utf-8")
    app = _app_source()
    # Statically bound keys must be referenced by the panel markup.
    for key in ("claw-runs-kicker", "claw-runs-title", "claw-runs-tagline", "claw-runs-loading", "claw-runs-empty"):
        assert f'data-locale-key="{key}"' in html, key
    assert 'data-locale-aria-label="claw-runs-refresh-aria"' in html
    # Runtime-resolved keys must be resolved through the Claw locale helper.
    for key in ("claw-runs-error", "claw-runs-download"):
        assert f'clawT("{key}")' in app, key
    # Status is resolved by suffix so it never falls back to invented copy.
    assert "claw-runs-status-" in app
    assert '"claw-runs-status-completed"' in app


def test_runtime_copy_stays_locale_driven() -> None:
    app = _app_source()
    for line_no, line in enumerate(app.splitlines(), start=1):
        assert not any("\uac00" <= ch <= "\ud7a3" for ch in line), f"hardcoded Korean in app.js:{line_no}: {line.strip()}"
    for key in ("claw-runs-empty", "claw-runs-error", "claw-runs-download", "claw-runs-status-completed"):
        assert f'"{key}"' in app  # English fallback copy for the non-locale path


def test_theme_roles_inherit_shared_tokens() -> None:
    css = WORKSPACE_CSS.read_text(encoding="utf-8")
    block = css.split("#2317 recent-run presentation", 1)[-1]
    assert block != css
    assert "var(--text)" in block
    assert "var(--muted)" in block
    assert "var(--line)" in block
    assert "var(--card-bg)" in block
    assert "var(--accent)" in block
    assert "var(--accent-soft)" in block
    assert "--claw-" not in block
    assert 'html[data-theme="padiem-glass"]' not in block
    assert "min-height: 44px" in block
    assert "@media (max-width: 920px)" in block
    # Hidden outside the Claw shell state, like every other Claw-only node.
    assert '.app-shell:not([data-state="claw"]) .claw-run-history,' in css


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
].forEach((id) => add(id, "div"));
const shell = add("app-shell", "div");
shell.dataset = { state: "home" };
const accountContainer = add("sidebar-account", "div");
byId.clawChannel.options = [{ textContent: "KakaoTalk" }];
byId.clawChannel.value = "kakao";
byId.clawAction.options = [{ textContent: "quote" }];
byId.clawAction.value = "quote";
byId.clawRunHistoryList.hidden = true;

const ARTIFACT_ID = "doc_" + "a".repeat(32);
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
let runState = { runs: [
  { run_id: "run_1", channel: "kakao", action: "quote_draft", title: "[KAKAO] quote_draft: A업체", status: "completed",
    created_at: "2026-09-19T01:00:00Z", updated_at: "2026-09-19T01:00:00Z", result_summary: "견적 요약",
    artifact: { document_id: ARTIFACT_ID, filename: "quote.docx", media_type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document" } },
] };
let runsStatus = 200;
let authenticated = true;

async function fetchImpl(url, opts) {
  opts = opts || {};
  const method = (opts.method || "GET").toUpperCase();
  requests.push({ url: String(url), method, body: opts.body ? JSON.parse(opts.body) : null });
  const u = String(url);
  if (u.startsWith("/api/auth/status")) return jsonResponse(200, { ready: true, authenticated, user: { name: "owner" }, history_ready: false, project_files_ready: false });
  if (u.startsWith("/api/projects")) return jsonResponse(200, { projects: [] });
  if (u.startsWith("/api/conversations")) return jsonResponse(200, { conversations: [] });
  if (u.startsWith("/api/claw/inbox/")) return jsonResponse(200, { ok: true, kind: "tasks", items: [], limit: 20 });
  if (u.startsWith("/api/claw/memory")) return jsonResponse(200, { ok: true, memories: [] });
  if (u.startsWith("/api/claw/runs")) {
    if (runsStatus !== 200) return jsonResponse(runsStatus, { ok: false, error: { code: "run_history_read_failed" } });
    return jsonResponse(200, { ok: true, runs: runState.runs });
  }
  if (u.startsWith("/api/claw/manual-intake/artifact/")) {
    return { ok: true, status: 200, json: async () => ({}), blob: async () => ({ size: 3, type: "application/octet-stream" }) };
  }
  return jsonResponse(200, {});
}

const sandbox = {
  document: doc,
  fetch: fetchImpl,
  AbortController: class { constructor() { this.signal = {}; } abort() {} },
  URL: { createObjectURL: () => "blob:x", revokeObjectURL() {}, revokeURL() {} },
  setTimeout, clearTimeout, console,
  CustomEvent: class {},
  location: { href: "http://localhost/", assign() {} },
  addEventListener() {},
  __padiemLocale: { text: (k) => ({
    "claw-runs-download": "문서 다시 받기",
    "claw-runs-error": "실행 기록을 불러오지 못했습니다. 다시 시도해 주세요.",
    "claw-runs-empty": "최근 실행 기록이 없습니다.",
    "claw-runs-status-completed": "완료",
    "claw-error-auth-needed": "다시 로그인해 주세요.",
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
  const checks = {};
  const fail = (m) => { console.log(JSON.stringify({ ok: false, error: m, requests, checks })); process.exit(0); };
  process.on("unhandledRejection", (e) => { console.log(JSON.stringify({ ok: false, error: "unhandledRejection " + String((e && e.stack) || e) })); process.exit(0); });
  process.on("uncaughtException", (e) => { console.log(JSON.stringify({ ok: false, error: "uncaughtException " + String((e && e.stack) || e) })); process.exit(0); });
  const tick = (ms) => new Promise((r) => setTimeout(r, ms));
  const runCalls = () => requests.filter((r) => r.url.startsWith("/api/claw/runs")).length;
  await tick(40);

  // 1) Signed in but still on Chat: the Claw panel is not fetched.
  checks.RUN_HISTORY_NOT_FETCHED_OUTSIDE_CLAW = runCalls() === 0 && byId.clawRunHistory.hidden === true;
  if (!checks.RUN_HISTORY_NOT_FETCHED_OUTSIDE_CLAW) fail("RUN_HISTORY_NOT_FETCHED_OUTSIDE_CLAW");

  // 2) Opening the Claw workspace fetches the owner-scoped route exactly once.
  byId.clawNavButton.click();
  await tick(50);
  checks.RUN_HISTORY_FETCHED_ON_CLAW_OPEN = runCalls() === 1 && byId.clawRunHistory.hidden === false;
  if (!checks.RUN_HISTORY_FETCHED_ON_CLAW_OPEN) fail("RUN_HISTORY_FETCHED_ON_CLAW_OPEN");

  // 3) The rendered card shows the run summary and its artifact filename.
  const text = collectText(byId.clawRunHistoryList);
  checks.RUN_CARD_RENDERS_SUMMARY_AND_ARTIFACT =
    text.indexOf("quote_draft") >= 0 && text.indexOf("견적 요약") >= 0 && text.indexOf("quote.docx") >= 0;
  if (!checks.RUN_CARD_RENDERS_SUMMARY_AND_ARTIFACT) fail("RUN_CARD_RENDERS_SUMMARY_AND_ARTIFACT");

  // 4) Status token is localized, and no server-internal field leaks into the DOM.
  checks.RUN_STATUS_LOCALIZED = text.indexOf("완료") >= 0;
  if (!checks.RUN_STATUS_LOCALIZED) fail("RUN_STATUS_LOCALIZED");
  checks.SENSITIVE_FIELD_DOM_PROJECTION =
    text.indexOf("user_id") >= 0 || text.indexOf("workspace_id") >= 0 || text.indexOf("tenant_id") >= 0 ? 0 : 1;
  if (checks.SENSITIVE_FIELD_DOM_PROJECTION !== 1) fail("SENSITIVE_FIELD_DOM_PROJECTION");

  // 5) Two rapid refreshes collapse into one in-flight request (single flight).
  const before = runCalls();
  byId.clawRunHistoryRefresh.click();
  byId.clawRunHistoryRefresh.click();
  await tick(50);
  checks.RUN_HISTORY_SINGLE_FLIGHT = runCalls() === before + 1;
  if (!checks.RUN_HISTORY_SINGLE_FLIGHT) fail("RUN_HISTORY_SINGLE_FLIGHT");

  // 6) Re-download reuses the single bounded artifact route.
  const downloadBtn = findButton(byId.clawRunHistoryList, "문서 다시 받기");
  if (!downloadBtn) fail("RUN_ARTIFACT_DOWNLOAD_BUTTON_MISSING");
  downloadBtn.click();
  await tick(30);
  checks.ARTIFACT_REDOWNLOAD_REUSES_BOUNDED_ROUTE =
    requests.some((r) => r.url === "/api/claw/manual-intake/artifact/" + ARTIFACT_ID);
  if (!checks.ARTIFACT_REDOWNLOAD_REUSES_BOUNDED_ROUTE) fail("ARTIFACT_REDOWNLOAD_REUSES_BOUNDED_ROUTE");

  // 7) The inbox view hides the panel and does not fetch run history.
  const beforeInbox = runCalls();
  byId.tasksNavButton.click();
  await tick(50);
  checks.RUN_HISTORY_HIDDEN_IN_INBOX_VIEW = byId.clawRunHistory.hidden === true && runCalls() === beforeInbox;
  if (!checks.RUN_HISTORY_HIDDEN_IN_INBOX_VIEW) fail("RUN_HISTORY_HIDDEN_IN_INBOX_VIEW");

  // 8) Returning to the workspace shows the panel again and refetches.
  byId.clawNavButton.click();
  await tick(50);
  if (runCalls() !== beforeInbox + 1) fail("RUN_HISTORY_REFETCH_ON_RETURN");

  // 9) Empty history renders the empty state with no cards.
  runState = { runs: [] };
  byId.clawRunHistoryRefresh.click();
  await tick(50);
  checks.RUN_HISTORY_EMPTY_STATE =
    byId.clawRunHistoryEmpty.hidden === false && byId.clawRunHistoryList.hidden === true && byId.clawRunHistoryList.children.length === 0;
  if (!checks.RUN_HISTORY_EMPTY_STATE) fail("RUN_HISTORY_EMPTY_STATE");

  // 10) Failure surfaces a safe error, and retry recovers.
  runsStatus = 503;
  byId.clawRunHistoryRefresh.click();
  await tick(50);
  const errored = byId.clawRunHistoryError.hidden === false && byId.clawRunHistoryError.dataset.state === "error";
  if (!errored) fail("RUN_HISTORY_ERROR_STATE");
  runsStatus = 200;
  runState = { runs: [
    { run_id: "run_2", channel: "sms", action: "reply_draft", title: "[SMS] reply_draft", status: "completed",
      created_at: "2026-09-19T02:00:00Z", result_summary: "답장 요약", artifact: null },
  ] };
  byId.clawRunHistoryRefresh.click();
  await tick(50);
  checks.RUN_HISTORY_ERROR_RETRY =
    byId.clawRunHistoryError.hidden === true && byId.clawRunHistoryList.hidden === false && collectText(byId.clawRunHistoryList).indexOf("답장 요약") >= 0;
  if (!checks.RUN_HISTORY_ERROR_RETRY) fail("RUN_HISTORY_ERROR_RETRY");

  // 11) A run with no artifact renders no download button.
  checks.RUN_WITHOUT_ARTIFACT_HAS_NO_DOWNLOAD = findButton(byId.clawRunHistoryList, "문서 다시 받기") === null;
  if (!checks.RUN_WITHOUT_ARTIFACT_HAS_NO_DOWNLOAD) fail("RUN_WITHOUT_ARTIFACT_HAS_NO_DOWNLOAD");

  console.log(JSON.stringify({ ok: true, requests, checks }));
  process.exit(0);
})().catch((e) => { console.log(JSON.stringify({ ok: false, error: String((e && e.stack) || e) })); process.exit(0); });
"""


def _run_harness() -> dict:
    node = shutil.which("node")
    assert node, "node runtime is required for the behavioral harness"
    harness_path = ROOT / "tests" / "_b54_claw_run_history_harness.js"
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


def test_behavioral_run_history_journey() -> None:
    payload = _run_harness()
    assert payload.get("ok") is True, payload
    checks = payload["checks"]
    for name in (
        "RUN_HISTORY_NOT_FETCHED_OUTSIDE_CLAW",
        "RUN_HISTORY_FETCHED_ON_CLAW_OPEN",
        "RUN_CARD_RENDERS_SUMMARY_AND_ARTIFACT",
        "RUN_STATUS_LOCALIZED",
        "RUN_HISTORY_SINGLE_FLIGHT",
        "ARTIFACT_REDOWNLOAD_REUSES_BOUNDED_ROUTE",
        "RUN_HISTORY_HIDDEN_IN_INBOX_VIEW",
        "RUN_HISTORY_EMPTY_STATE",
        "RUN_HISTORY_ERROR_RETRY",
        "RUN_WITHOUT_ARTIFACT_HAS_NO_DOWNLOAD",
    ):
        assert checks.get(name) is True, name
    assert checks.get("SENSITIVE_FIELD_DOM_PROJECTION") == 1


def test_behavioral_requests_stay_within_existing_authority() -> None:
    payload = _run_harness()
    assert payload.get("ok") is True, payload
    urls = {request["url"].split("?")[0] for request in payload["requests"]}
    allowed = {
        "/api/auth/status",
        "/api/projects",
        "/api/conversations",
        "/api/claw/runs",
        "/api/claw/memory",
        "/api/claw/inbox/tasks",
        "/api/claw/manual-intake/artifact/" + "doc_" + "a" * 32,
    }
    assert urls <= allowed, urls - allowed
    # Presentation never POSTs: nothing in this slice mutates server state.
    assert all(request["method"] == "GET" for request in payload["requests"])


if __name__ == "__main__":
    test_run_history_surface_is_declared_inside_the_claw_workspace()
    test_accessible_loading_error_empty_and_refresh_states()
    test_consumes_the_existing_owner_scoped_route_without_new_authority()
    test_presentation_does_not_mint_run_truth_in_the_browser()
    test_single_flight_and_visibility_guards_are_present()
    test_auth_loss_clears_rendered_run_history_dom()
    test_locale_keys_are_declared_for_both_languages()
    test_runtime_copy_stays_locale_driven()
    test_theme_roles_inherit_shared_tokens()
    test_behavioral_harness_passes()
    test_behavioral_run_history_journey()
    test_behavioral_requests_stay_within_existing_authority()
    print("B54_CLAW_RUN_HISTORY_UI_TESTS=PASS")
