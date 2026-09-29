"""#3232 — Web Claw sidebar Files button wires into existing Project Files UI.

The sidebar already renders ``#filesNavButton`` (disabled), but no script
referenced it. This test proves the minimal wiring in ``app.js``:

- FILES_NAV_REFERENCE_PRESENT / FILES_NAV_CLICK_HANDLER_PRESENT
- readiness reuses the existing project authority
  (``authState.authenticated && projectsReady``) — no new readiness flag,
  no new storage authority, no new upload/delete routes
- SIGNED_OUT_FAIL_CLOSED: signed-out click opens nothing and issues no
  project API requests
- signed-in + active project: Files reopens that project's existing dialog
  with the existing ``projectFilesPanel`` visible
- signed-in + no active project: Files reuses the existing Projects flow
  (create dialog when empty, section scroll when projects exist) and never
  invents a global file store
- request contracts from #2319/#2342 are byte-for-byte preserved

Behavior is proven with a Node harness executing the REAL
attachment-capabilities.js + document-binary.js + app.js in one vm context
against a minimal DOM shim (same technique as the #2342 test).
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
DOCUMENT_BINARY_JS = ROOT / "static/document-binary.js"
INDEX_HTML = ROOT / "static/index.html"

EXPECTED_PROJECT_API_TEMPLATES = {
    'fetch("/api/projects"',
    "fetch(`/api/projects/${encodeURIComponent(id)}`",
    "fetch(`/api/projects/${encodeURIComponent(projectId)}/files`",
    "fetch(`/api/projects/${encodeURIComponent(editingProjectId)}/files`",
    "fetch(`/api/projects/${encodeURIComponent(editingProjectId)}/files/${encodeURIComponent(fileId)}`",
    '"/api/projects"',
    "fetch(`/api/projects/${encodeURIComponent(deletingId)}`",
}


# ── static wiring contracts ────────────────────────────────────────────────


def test_sidebar_still_renders_disabled_files_entry() -> None:
    html = INDEX_HTML.read_text(encoding="utf-8")
    assert 'id="filesNavButton"' in html
    assert 'data-locale-key="nav-files"' in html


def test_files_nav_reference_and_click_handler_present() -> None:
    source = APP_JS.read_text(encoding="utf-8")
    assert 'document.getElementById("filesNavButton")' in source
    assert "filesNavButton.addEventListener" in source
    assert "function syncFilesNav()" in source


def test_files_nav_reuses_existing_project_readiness_authority() -> None:
    source = APP_JS.read_text(encoding="utf-8")
    match = re.search(r"function syncFilesNav\(\) \{([^}]*)\}", source)
    assert match is not None
    body = match.group(1)
    assert "authState.authenticated" in body
    assert "projectsReady" in body
    # No new readiness authority may be invented for the Files entry.
    assert re.search(r"\bfilesReady\b", source) is None
    assert "filesNavReady" not in source
    assert "files_available" not in source


def test_files_click_handler_is_fail_closed_and_reuses_project_ui() -> None:
    source = APP_JS.read_text(encoding="utf-8")
    assert "if (!projectsReady || !authState.authenticated) return;" in source
    assert "openProjectDialog(activeProject)" in source
    # Empty-project and existing-project branches reuse the Projects flow.
    handler = source.split("filesNavButton.addEventListener")[1].split("projectCreateButton")[0]
    assert "openProjectDialog()" in handler
    assert "projectsSection.scrollIntoView" in handler


def test_no_new_file_backend_routes_or_storage() -> None:
    source = APP_JS.read_text(encoding="utf-8")
    found = set()
    for line in source.splitlines():
        stripped = line.strip()
        if "/api/projects" in stripped and ("fetch(" in stripped or stripped.startswith('"') or "url =" in stripped or "url=" in stripped):
            for template in EXPECTED_PROJECT_API_TEMPLATES:
                if template in stripped:
                    found.add(template)
    # Every project-API call site is one of the pre-existing templates;
    # the wiring adds zero fetch calls.
    assert EXPECTED_PROJECT_API_TEMPLATES <= found
    assert source.count("/files") == 3  # GET list, POST upload, DELETE (unchanged)
    # Existing #2319/#2342 request contracts preserved byte-for-byte.
    assert "payload = { name: documentFile.name, media_type: documentFile.mediaType, base64: documentFile.base64 };" in source
    assert "payload = { name: documentFile.name, media_type: documentFile.mediaType, text: documentFile.text };" in source
    assert "console." not in source


# ── behavioral proof via Node harness executing real app.js ────────────────

_HARNESS = r"""
const fs = require("fs");
const vm = require("vm");
const APP = fs.readFileSync(process.argv[2], "utf8");
const CAPS = fs.readFileSync(process.argv[3], "utf8");
const DOCBIN = fs.readFileSync(process.argv[4], "utf8");
const FIXTURE = JSON.parse(process.argv[5]);

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
  el.scrollIntoView = () => { el._scrolled = true; };
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
  "clawApprovedMemory","clawApprovedRefresh","clawApprovedLoading","clawApprovedError","clawApprovedList",
  "clawApprovedEmpty","clawMemoryReview",
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
function jsonResponse(status, obj) { return { ok: status >= 200 && status < 300, status, json: async () => obj }; }
async function fetchImpl(url, opts) {
  opts = opts || {};
  const method = (opts.method || "GET").toUpperCase();
  const u = String(url);
  requests.push({ url: u, method });
  if (u.startsWith("/api/auth/status")) return jsonResponse(200, FIXTURE.auth);
  if (method === "GET" && /\/api\/projects\/[^/]+\/files$/.test(u)) {
    const pid = decodeURIComponent(u.split("/")[3]);
    return jsonResponse(200, { files: (FIXTURE.filesByProject || {})[pid] || [] });
  }
  if (u.startsWith("/api/projects")) return jsonResponse(200, { projects: FIXTURE.projects || [] });
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
};
sandbox.window = sandbox;
vm.createContext(sandbox);
vm.runInContext(CAPS, sandbox, { filename: "attachment-capabilities.js" });
vm.runInContext(DOCBIN, sandbox, { filename: "document-binary.js" });
vm.runInContext(APP, sandbox, { filename: "app.js" });

function projectRequests() { return requests.filter((r) => r.url.startsWith("/api/projects")); }
function fileRequests() { return requests.filter((r) => /\/api\/projects\/[^/]+\/files/.test(r.url)); }
function clickFilesNav() { (byId.filesNavButton.listeners.click || []).forEach((fn) => fn({ preventDefault() {} })); }
function firstProjectRowButton() {
  const stack = [...(byId.projectsList.children || [])];
  while (stack.length) {
    const el = stack.shift();
    if (el.listeners && el.listeners.click && String(el.className || "").includes("project-item")) return el;
    stack.push(...(el.children || []));
  }
  return null;
}

(async () => {
  const fail = (m) => { console.log(JSON.stringify({ ok: false, error: m })); process.exit(0); };
  const tick = (ms) => new Promise((r) => setTimeout(r, ms));
  await tick(50);
  const mode = FIXTURE.mode;
  const snapshot = () => ({
    disabled: byId.filesNavButton.disabled,
    ariaDisabled: byId.filesNavButton.getAttribute("aria-disabled"),
    dialogOpen: byId.projectDialog.open === true,
    dialogTitle: byId.projectDialogTitle.textContent,
    filesPanelHidden: byId.projectFilesPanel.hidden === true,
    scrolledToProjects: byId.projectsSection._scrolled === true,
    projectApiCalls: projectRequests().length,
    fileApiCalls: fileRequests().length,
  });
  if (mode === "signed_out") {
    const before = snapshot();
    if (before.disabled !== true) fail("SIGNED_OUT_MUST_DISABLE");
    if (before.ariaDisabled !== "true") fail("SIGNED_OUT_ARIA_DISABLED");
    clickFilesNav();
    await tick(30);
    const after = snapshot();
    if (after.dialogOpen) fail("SIGNED_OUT_MUST_NOT_OPEN_DIALOG");
    if (after.projectApiCalls !== 0) fail("SIGNED_OUT_MUST_ISSUE_NO_PROJECT_REQUESTS");
  } else if (mode === "signed_in_empty") {
    const before = snapshot();
    if (before.disabled !== false) fail("READY_MUST_ENABLE");
    if (before.ariaDisabled !== "false") fail("READY_ARIA_ENABLED");
    clickFilesNav();
    await tick(30);
    const after = snapshot();
    if (!after.dialogOpen) fail("EMPTY_MUST_OPEN_CREATE_DIALOG");
    if (after.dialogTitle !== "project-new") fail("EMPTY_MUST_BE_CREATE_FLOW:" + after.dialogTitle);
    if (!after.filesPanelHidden) fail("CREATE_FLOW_MUST_NOT_SHOW_GLOBAL_FILES_PANEL");
    if (after.fileApiCalls !== 0) fail("CREATE_FLOW_MUST_ISSUE_NO_FILE_REQUESTS");
  } else if (mode === "signed_in_projects") {
    const before = snapshot();
    if (before.disabled !== false) fail("READY_MUST_ENABLE");
    clickFilesNav();
    await tick(30);
    const mid = snapshot();
    if (mid.dialogOpen) fail("NO_ACTIVE_MUST_NOT_OPEN_DIALOG_DIRECTLY");
    if (!mid.scrolledToProjects) fail("NO_ACTIVE_MUST_ROUTE_TO_PROJECTS_SECTION");
    const row = firstProjectRowButton();
    if (!row) fail("PROJECT_ROW_MISSING");
    row.click();
    await tick(50);
    clickFilesNav();
    await tick(50);
    const after = snapshot();
    if (!after.dialogOpen) fail("ACTIVE_PROJECT_MUST_OPEN_DIALOG");
    if (after.dialogTitle !== "project-edit-title") fail("ACTIVE_PROJECT_MUST_REUSE_EXISTING_DIALOG:" + after.dialogTitle);
    if (after.filesPanelHidden) fail("ACTIVE_PROJECT_MUST_SHOW_EXISTING_FILES_PANEL");
    if (after.fileApiCalls < 1) fail("ACTIVE_PROJECT_MUST_LOAD_EXISTING_FILE_LIST");
  } else {
    fail("UNKNOWN_MODE");
  }
  console.log(JSON.stringify({ ok: true, snapshot: snapshot() }));
  process.exit(0);
})();
"""


def _run_harness(mode: str, auth: dict, projects: list, files_by_project: dict) -> dict:
    node = shutil.which("node")
    assert node, "node runtime is required for the behavioral harness"
    harness_path = ROOT / "tests" / f"_b62_3232_behavior_harness_{mode}.js"
    harness_path.write_text(_HARNESS, encoding="utf-8")
    fixture = json.dumps({"mode": mode, "auth": auth, "projects": projects, "filesByProject": files_by_project})
    try:
        proc = subprocess.run(
            [node, str(harness_path), str(APP_JS), str(CAPABILITIES_JS), str(DOCUMENT_BINARY_JS), fixture],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(ROOT),
        )
    finally:
        harness_path.unlink(missing_ok=True)
    assert proc.returncode == 0, f"harness crashed: {proc.stderr[-2000:]}"
    try:
        result = json.loads(proc.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError) as error:
        raise AssertionError(f"harness produced no JSON: {proc.stdout[-2000:]!r} {proc.stderr[-2000:]!r}") from error
    assert result.get("ok") is True, f"behavior failed: {result}"
    return result


_SIGNED_OUT_AUTH = {"ready": True, "authenticated": False, "user": None, "history_ready": False, "project_files_ready": False}
_SIGNED_IN_AUTH = {
    "ready": True,
    "authenticated": True,
    "user": {"name": "owner"},
    "history_ready": True,
    "project_files_ready": True,
}
_P1 = {"id": "p1", "name": "P1", "instructions": "", "created_at": "2026-09-10T00:00:00Z", "updated_at": "2026-09-10T00:00:00Z"}
_P1_FILE = {
    "id": "file_1",
    "project_id": "p1",
    "name": "notes.txt",
    "media_type": "text/plain",
    "content_chars": 12,
    "created_at": "2026-09-10T00:00:00Z",
    "updated_at": "2026-09-10T00:00:00Z",
}


def test_signed_out_files_entry_is_fail_closed() -> None:
    _run_harness("signed_out", _SIGNED_OUT_AUTH, [], {})


def test_signed_in_without_projects_opens_create_flow_without_global_store() -> None:
    _run_harness("signed_in_empty", _SIGNED_IN_AUTH, [], {})


def test_signed_in_routes_via_existing_project_flow() -> None:
    _run_harness("signed_in_projects", _SIGNED_IN_AUTH, [_P1], {"p1": [_P1_FILE]})
