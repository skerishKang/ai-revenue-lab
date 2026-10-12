"""#3232 → #4489 — the sidebar Library entry and its project-file authority.

#3232 wired ``#filesNavButton`` into the existing Project UI and disabled it
unless project-file storage was provisioned. #4489 supersedes that routing: the
entry is now a real destination owned by ``static/library.js`` and stays
navigable for any signed-in owner, while every project-file read and open still
goes through the canonical #2319/#2342 authority.

What this file still guarantees:

- SIGNED_OUT_FAIL_CLOSED: the entry is inert and issues zero project API calls.
- No new backend route, storage authority, upload or delete path is introduced.
- The #2319/#2342 request contracts in ``app.js`` are byte-for-byte preserved.
- ``library.js`` reads only the two canonical owner-scoped list endpoints and
  never fetches file bytes or a file detail route.
- Storage that is not provisioned disables the *listing*, never the navigation.
- A session flip drops the previous owner's rows before they can be re-rendered.

Behavior is proven with a Node harness executing the REAL app.js + library.js in
one vm context against a minimal DOM shim (same technique #3232 shipped with).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "static/app.js"
LIBRARY_JS = ROOT / "static/library.js"
LIBRARY_CSS = ROOT / "static/library.css"
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


# ── markup and module wiring ────────────────────────────────────────────────


def test_sidebar_still_renders_the_library_entry() -> None:
    html = INDEX_HTML.read_text(encoding="utf-8")
    assert 'id="filesNavButton"' in html
    assert 'data-locale-key="nav-files"' in html
    # Fail-closed in markup: the entry starts disabled and library.js enables it
    # only for a projected signed-in owner.
    button = html[html.index('id="filesNavButton"') - 200 : html.index('id="filesNavButton"') + 200]
    assert "disabled" in button
    assert 'aria-disabled="true"' in button
    assert 'aria-current="false"' in button


def test_library_destination_is_wired_before_the_chat_surface() -> None:
    html = INDEX_HTML.read_text(encoding="utf-8")
    assert 'id="libraryView"' in html
    assert 'role="tablist"' in html
    assert 'id="libraryFilesTab"' in html and 'id="libraryImagesTab"' in html
    # A destination section must sit in the same band as Calendar and Claw, i.e.
    # before the shared conversation column, or the surface gating cannot work.
    assert html.index('id="calendarView"') < html.index('id="libraryView"') < html.index('<section class="conversation"')
    assert 'href="./library.css"' in html
    assert html.index('href="./library.css"') < html.index("<style>[hidden]")
    # It consumes the seam app.js publishes, so it must load after app.js.
    assert html.index('src="./app.js"') < html.index('src="./library.js"')
    # ... and never after the adapter that is contractually last.
    assert html.index('src="./library.js"') < html.index('src="./claw-local-adapter.js"')


def test_library_view_is_gated_on_the_shared_surface_state() -> None:
    css = LIBRARY_CSS.read_text(encoding="utf-8")
    assert ".app-shell[data-state=\"library\"] .library-view {" in css
    assert ".app-shell:not([data-state=\"library\"]) .library-view {" in css
    assert "display: none !important;" in css
    # The chat column and composer are hidden here, exactly like Calendar and Claw.
    assert ".app-shell[data-state=\"library\"] .conversation," in css
    assert ".app-shell[data-state=\"library\"] .composer-wrap {" in css


def test_library_view_stacks_above_the_glass_portrait_decoration() -> None:
    css = LIBRARY_CSS.read_text(encoding="utf-8")
    start = css.index("\n.library-view {")
    view_block = css[start : css.index("}", start)]
    # The glass theme paints a fixed decorative portrait at z-index 1 with
    # pointer-events disabled. An unpositioned destination renders its own
    # controls underneath it, so the view must be stacked above it.
    assert "position: relative;" in view_block
    assert re.search(r"z-index:\s*2;", view_block)


def test_library_entry_moves_out_of_app_js_into_the_module() -> None:
    app = APP_JS.read_text(encoding="utf-8")
    # The old gate that also required project-file storage is gone, so storage
    # provisioning can no longer make a signed-in owner's navigation inert.
    assert "function filesNavAvailable()" not in app
    assert "function syncFilesNav()" not in app
    assert 'getElementById("filesNavButton")' not in app
    # app.js keeps only the narrow trusted seam, and it resolves the project from
    # the already-loaded owner list rather than from a caller-supplied object.
    seam = app[app.index("window.PadiemChatProjectOpener") :]
    seam = seam[: seam.index("});")]
    assert "projects.find((item) => item && item.id === projectId)" in seam
    assert "openProjectDialog(project)" in seam
    assert "if (!projectsReady || !authState.authenticated || inFlight) return false;" in seam


def test_library_reads_only_canonical_owner_scoped_lists() -> None:
    source = LIBRARY_JS.read_text(encoding="utf-8")
    code = "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith("//")
    )
    assert 'fetch("/api/projects"' in code or '"/api/projects"' in code
    assert "/api/projects/${encodeURIComponent(projectId)}/files" in code
    # No file detail, no bytes, no upload, no delete, no second authority.
    for forbidden in (
        "/files/${",
        "/download",
        "/preview",
        "method:",
        "XMLHttpRequest",
        "createObjectURL",
    ):
        assert forbidden not in code, forbidden
    assert code.count("await fetch(") == 1  # one shared list reader
    # The fan-out is bounded, so a large account cannot issue an unbounded read.
    assert "MAX_PROJECTS_READ" in code
    assert "projects.length > MAX_PROJECTS_READ" in code


def test_library_module_keeps_the_privacy_and_sink_boundaries() -> None:
    source = LIBRARY_JS.read_text(encoding="utf-8")
    for forbidden in (
        "localStorage",
        "sessionStorage",
        "indexedDB",
        "document.cookie",
        "cookieStore",
        "serviceWorker",
        "caches.open",
        "innerHTML",
        "outerHTML",
        "insertAdjacentHTML",
        "document.write",
        "srcdoc",
    ):
        # The repository's raw-text gates scan comments too, so this module names
        # none of these primitives anywhere.
        assert forbidden not in source, forbidden
    assert "textContent" in source
    assert "console." not in source


def test_no_new_file_backend_routes_or_storage_in_app_js() -> None:
    source = APP_JS.read_text(encoding="utf-8")
    found = set()
    for line in source.splitlines():
        stripped = line.strip()
        if "/api/projects" in stripped and ("fetch(" in stripped or stripped.startswith('"') or "url =" in stripped or "url=" in stripped):
            for template in EXPECTED_PROJECT_API_TEMPLATES:
                if template in stripped:
                    found.add(template)
    assert EXPECTED_PROJECT_API_TEMPLATES <= found
    assert source.count("/files") == 3  # GET list, POST upload, DELETE (unchanged)
    assert "payload = { name: documentFile.name, media_type: documentFile.mediaType, base64: documentFile.base64 };" in source
    assert "payload = { name: documentFile.name, media_type: documentFile.mediaType, text: documentFile.text };" in source
    assert "console." not in source


# ── behavioral proof via Node harness executing real app.js + library.js ────

_HARNESS = r"""
const fs = require("fs");
const vm = require("vm");
const APP = fs.readFileSync(process.argv[2], "utf8");
const LIBRARY = fs.readFileSync(process.argv[3], "utf8");
const CAPS = fs.readFileSync(process.argv[4], "utf8");
const DOCBIN = fs.readFileSync(process.argv[5], "utf8");
const FIXTURE = JSON.parse(process.argv[6]);

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
  "libraryView","libraryKicker","libraryTitle","librarySubtitle","libraryCloseButton",
  "libraryFilesTab","libraryImagesTab","libraryNote","libraryFilesPanel","libraryImagesPanel",
  "libraryFileList","libraryImageList",
].forEach((id) => add(id, "div"));
const shell = add("app-shell", "div");
shell.dataset = { state: "home" };
const accountContainer = add("sidebar-account", "div");
byId.clawChannel.options = [{ textContent: "KakaoTalk" }];
byId.clawChannel.value = "kakao";
byId.clawAction.options = [{ textContent: "draft" }];
byId.clawAction.value = "quote";
byId.projectForm.querySelector = () => makeEl("div");

// Window listeners must be real here: the Library entry is driven by the
// capability projection event, so the harness needs to dispatch it.
const windowListeners = {};

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

let virtualNow = 0;
let timerSequence = 0;
const virtualTimers = new Map();
function virtualSetTimeout(callback, delay=0, ...args) {
  const id = ++timerSequence;
  virtualTimers.set(id, { when: virtualNow + Math.max(0, Number(delay) || 0), callback, args });
  return id;
}
function virtualClearTimeout(id) { virtualTimers.delete(id); }
async function flushAsync() {
  for (let i = 0; i < 12; i += 1) await new Promise((resolve) => setImmediate(resolve));
}
async function tick(ms) {
  await flushAsync();
  const deadline = virtualNow + ms;
  let iterations = 0;
  while (true) {
    let chosenId = null, chosen = null;
    for (const [id, timer] of virtualTimers) {
      if (timer.when <= deadline && (!chosen || timer.when < chosen.when)) { chosenId = id; chosen = timer; }
    }
    if (!chosen) break;
    virtualNow = chosen.when;
    virtualTimers.delete(chosenId);
    chosen.callback(...chosen.args);
    await flushAsync();
    if (++iterations > 10000) throw new Error("unbounded navigation timer loop");
  }
  virtualNow = deadline;
  await flushAsync();
}

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
    const table = FIXTURE.sessions[FIXTURE.activeSession].filesByProject || {};
    return jsonResponse(200, { files: table[pid] || [] });
  }
  if (u.startsWith("/api/projects")) {
    return jsonResponse(200, { projects: FIXTURE.sessions[FIXTURE.activeSession].projects || [] });
  }
  if (u.startsWith("/api/conversations")) return jsonResponse(200, { conversations: [] });
  return jsonResponse(200, {});
}

const sandbox = {
  document: doc,
  fetch: fetchImpl,
  setTimeout: virtualSetTimeout, clearTimeout: virtualClearTimeout, console,
  CustomEvent: class { constructor(type, init) { this.type = type; this.detail = (init || {}).detail; } },
  location: { href: "http://localhost/", assign() {} },
  addEventListener: (type, fn) => { (windowListeners[type] = windowListeners[type] || []).push(fn); },
  __padiemLocale: { text: (k) => k },
  PadiemChatLifecycle: { states: { IDLE: "idle", STREAMING: "streaming", COMPLETED: "completed", FAILED: "failed", CANCELLED: "cancelled", TIMED_OUT: "timed_out" }, set() {} },
  PadiemConfirmDialog: { confirm: async () => true },
  PadiemChatTransport: { requestCompleted: async () => ({}), requestStreaming: async () => ({}), readSseEvents: async () => {}, errorFor: () => new Error("x") },
  PadiemChatConversationState: { reset() {}, setConversationId() {}, getConversationId() { return null; }, outboundWithUser: () => [], commitAssistant() {}, setSkill() {}, getSkill: () => "auto" },
  PadiemProductCapabilities: { get: () => ({ auth: null }) },
};
sandbox.window = sandbox;
vm.createContext(sandbox);
vm.runInContext(CAPS, sandbox, { filename: "attachment-capabilities.js" });
vm.runInContext(DOCBIN, sandbox, { filename: "document-binary.js" });
vm.runInContext(APP, sandbox, { filename: "app.js" });
vm.runInContext(LIBRARY, sandbox, { filename: "library.js" });

function dispatchAuth(auth) {
  sandbox.PadiemProductCapabilities.get = () => ({ auth });
  (windowListeners["padiem:capabilitychange"] || []).forEach((fn) => fn({ detail: { auth } }));
}
function projectRequests() { return requests.filter((r) => r.url.startsWith("/api/projects")); }
function fileRequests() { return requests.filter((r) => /\/api\/projects\/[^/]+\/files/.test(r.url)); }
function clickEntry() { (byId.filesNavButton.listeners.click || []).forEach((fn) => fn({ preventDefault() {} })); }
function clickTab(id) { (byId[id].listeners.click || []).forEach((fn) => fn({ preventDefault() {} })); }
function rowButtons() {
  const out = [];
  const walk = (el) => { for (const c of el.children || []) { if (String(c.className).includes("library-item-action")) out.push(c); walk(c); } };
  walk(byId.libraryFileList);
  return out;
}
function rowText() {
  const out = [];
  const walk = (el) => { for (const c of el.children || []) { if (String(c.className).includes("library-item-title")) out.push(c.textContent); walk(c); } };
  walk(byId.libraryFileList);
  return out;
}
function collect(root, needle) {
  const out = [];
  const walk = (el) => { for (const c of el.children || []) { if (String(c.className).includes(needle)) out.push(c); walk(c); } };
  walk(root);
  return out;
}
function snapshot() {
  return {
    state: shell.dataset.state,
    viewHidden: byId.libraryView.hidden === true,
    disabled: byId.filesNavButton.disabled,
    ariaDisabled: byId.filesNavButton.getAttribute("aria-disabled"),
    ariaCurrent: byId.filesNavButton.getAttribute("aria-current"),
    note: byId.libraryNote.textContent,
    noteHidden: byId.libraryNote.hidden === true,
    rows: rowText(),
    filesPanelShown: byId.libraryFilesPanel.hidden !== true,
    imagesPanelShown: byId.libraryImagesPanel.hidden !== true,
    imagesRows: collect(byId.libraryImageList, "library-item-title").length,
    imagesText: collect(byId.libraryImageList, "library-item-title").concat(collect(byId.libraryImageList, "library-item-detail")).map((el) => el.textContent).join("|"),
    imagesHasAction: collect(byId.libraryImageList, "library-item-action").length > 0,
    outcome: sandbox.PadiemChatLibrary.getOutcome(),
    truncated: sandbox.PadiemChatLibrary.isTruncated(),
    partial: sandbox.PadiemChatLibrary.hasPartialFailure(),
    dialogOpen: byId.projectDialog.open === true,
    dialogTitle: byId.projectDialogTitle.textContent,
    projectFilesPanelHidden: byId.projectFilesPanel.hidden === true,
    projectApiCalls: projectRequests().length,
    fileApiCalls: fileRequests().length,
  };
}
const fail = (m) => { console.log(JSON.stringify({ ok: false, error: m, snapshot: snapshot() })); process.exit(0); };

const A_FILE = { id: "file_a", project_id: "pa", name: "A 소유 문서", media_type: "text/plain", content_chars: 12, created_at: "2026-09-01T00:00:00Z", updated_at: "2026-09-01T00:00:00Z" };
const B_FILE = { id: "file_b", project_id: "pb", name: "B 소유 문서", media_type: "text/plain", content_chars: 7, created_at: "2026-09-02T00:00:00Z", updated_at: "2026-09-02T00:00:00Z" };
const PROJECT_A = { id: "pa", name: "PA", instructions: "", created_at: "2026-09-01T00:00:00Z", updated_at: "2026-09-01T00:00:00Z" };
const PROJECT_B = { id: "pb", name: "PB", instructions: "", created_at: "2026-09-02T00:00:00Z", updated_at: "2026-09-02T00:00:00Z" };

(async () => {
  await tick(60);
  const mode = FIXTURE.mode;

  if (mode === "signed_out") {
    dispatchAuth({ loaded: true, authenticated: false, historyReady: false, projectFilesReady: false });
    await tick(30);
    let s = snapshot();
    if (s.disabled !== true) fail("SIGNED_OUT_MUST_DISABLE");
    if (s.ariaDisabled !== "true") fail("SIGNED_OUT_ARIA_DISABLED");
    clickEntry();
    await tick(30);
    s = snapshot();
    if (!s.viewHidden) fail("SIGNED_OUT_MUST_NOT_OPEN_VIEW");
    if (s.state === "library") fail("SIGNED_OUT_MUST_NOT_CHANGE_SURFACE");
    if (s.projectApiCalls !== 0 || s.fileApiCalls !== 0) fail("SIGNED_OUT_MUST_ISSUE_NO_PROJECT_REQUESTS");
  } else if (mode === "storage_off") {
    dispatchAuth({ loaded: true, authenticated: true, historyReady: true, projectFilesReady: false });
    await tick(30);
    let s = snapshot();
    // #4489: missing project-file storage must NOT make the entry inert.
    if (s.disabled !== false) fail("STORAGE_OFF_MUST_STILL_ALLOW_NAVIGATION");
    if (s.ariaDisabled !== "false") fail("STORAGE_OFF_ARIA_ENABLED");
    clickEntry();
    await tick(30);
    s = snapshot();
    if (s.viewHidden) fail("MUST_OPEN_LIBRARY_VIEW");
    if (s.state !== "library") fail("SURFACE_STATE_NOT_LIBRARY");
    if (s.ariaCurrent !== "page") fail("ENTRY_NOT_MARKED_CURRENT");
    if (s.outcome !== "storage-off") fail("OUTCOME_NOT_STORAGE_OFF:" + s.outcome);
    if (!/켜지지 않았습니다/.test(s.note)) fail("NOTE_MUST_EXPLAIN:" + s.note);
    // Honest unavailable must not be manufactured into a successful empty read.
    if (s.fileApiCalls !== 0) fail("STORAGE_OFF_MUST_ISSUE_NO_FILE_REQUESTS");
    clickTab("libraryImagesTab");
    await tick(20);
    s = snapshot();
    if (!s.imagesPanelShown) fail("IMAGES_PANEL_MUST_SHOW");
    if (s.filesPanelShown) fail("FILES_PANEL_MUST_HIDE");
    if (s.imagesRows !== 1) fail("IMAGES_MUST_STATE_NO_PERSISTENCE:" + s.imagesRows);
    if (!/저장되지 않습니다/.test(s.imagesText)) fail("IMAGES_TAB_MUST_SAY_NOT_STORED:" + s.imagesText);
    if (s.imagesHasAction) fail("IMAGES_MUST_OFFER_NO_OPEN:" + s.imagesRows);
  } else if (mode === "with_files") {
    dispatchAuth({ loaded: true, authenticated: true, historyReady: true, projectFilesReady: true });
    await tick(30);
    clickEntry();
    await tick(60);
    let s = snapshot();
    if (s.outcome !== "ready") fail("OUTCOME_NOT_READY:" + s.outcome);
    if (s.rows.length !== 1 || s.rows[0] !== "A 소유 문서") fail("ROWS:" + JSON.stringify(s.rows));
    if (s.projectApiCalls < 1 || s.fileApiCalls < 1) fail("MUST_READ_CANONICAL_LISTS");
    if (!/PA/.test(s.note) && !/1/.test(s.note)) fail("NOTE_MUST_COUNT:" + s.note);
    const buttons = rowButtons();
    if (buttons.length !== 1) fail("ACTION_MISSING");
    buttons[0].click();
    await tick(60);
    s = snapshot();
    // Opening reuses the canonical project dialog with its existing files panel.
    if (!s.dialogOpen) fail("MUST_OPEN_PROJECT_DIALOG");
    if (s.dialogTitle !== "project-edit-title") fail("MUST_REUSE_EDIT_FLOW:" + s.dialogTitle);
    if (s.projectFilesPanelHidden) fail("MUST_SHOW_EXISTING_FILES_PANEL");
  } else if (mode === "account_switch") {
    dispatchAuth({ loaded: true, authenticated: true, historyReady: true, projectFilesReady: true });
    await tick(30);
    clickEntry();
    await tick(60);
    let s = snapshot();
    if (s.rows[0] !== "A 소유 문서") fail("OWNER_A_ROWS_MISSING:" + JSON.stringify(s.rows));
    // Owner signs out: the surface must close and the rows must leave the DOM.
    FIXTURE.activeSession = "b";
    dispatchAuth({ loaded: true, authenticated: false, historyReady: false, projectFilesReady: false });
    await tick(30);
    s = snapshot();
    if (s.rows.length !== 0) fail("LOGOUT_MUST_DROP_ROWS:" + JSON.stringify(s.rows));
    if (!s.viewHidden) fail("LOGOUT_MUST_CLOSE_VIEW");
    if (s.disabled !== true) fail("LOGOUT_MUST_DISABLE_ENTRY");
    // A different owner signs in: nothing from A may still be reachable.
    dispatchAuth({ loaded: true, authenticated: true, historyReady: true, projectFilesReady: true });
    await tick(30);
    s = snapshot();
    if (s.rows.length !== 0) fail("NEXT_OWNER_MUST_INHERIT_NOTHING:" + JSON.stringify(s.rows));
    clickEntry();
    await tick(60);
    s = snapshot();
    if (s.rows.length === 1 && s.rows[0] === "B 소유 문서") {
      // ok
    } else {
      fail("NEXT_OWNER_ROWS:" + JSON.stringify(s.rows));
    }
    if (s.state !== "library") fail("NEXT_OWNER_VIEW_NOT_OPEN");
  } else {
    fail("UNKNOWN_MODE");
  }
  console.log(JSON.stringify({ ok: true, snapshot: snapshot() }));
  process.exit(0);
})();
"""


def _run_harness(mode: str, auth: dict, sessions: dict) -> dict:
    node = shutil.which("node")
    assert node, "node runtime is required for the behavioral harness"
    harness_path = ROOT / "tests" / f"_b62_4489_behavior_harness_{mode}.js"
    harness_path.write_text(_HARNESS, encoding="utf-8")
    fixture = json.dumps({"mode": mode, "auth": auth, "activeSession": "a", "sessions": sessions})
    try:
        proc = subprocess.run(
            [node, str(harness_path), str(APP_JS), str(LIBRARY_JS), str(CAPABILITIES_JS), str(DOCUMENT_BINARY_JS), fixture],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(ROOT),
        )
    finally:
        harness_path.unlink(missing_ok=True)
    assert proc.returncode == 0, f"harness crashed: {proc.stderr[-3000:]}"
    try:
        result = json.loads(proc.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError) as error:
        raise AssertionError(f"harness produced no JSON: {proc.stdout[-2000:]!r} {proc.stderr[-3000:]!r}") from error
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
_PROJECT_A = {"id": "pa", "name": "PA", "instructions": "", "created_at": "2026-09-01T00:00:00Z", "updated_at": "2026-09-01T00:00:00Z"}
_PROJECT_B = {"id": "pb", "name": "PB", "instructions": "", "created_at": "2026-09-02T00:00:00Z", "updated_at": "2026-09-02T00:00:00Z"}
_FILE_A = {
    "id": "file_a",
    "project_id": "pa",
    "name": "A 소유 문서",
    "media_type": "text/plain",
    "content_chars": 12,
    "created_at": "2026-09-01T00:00:00Z",
    "updated_at": "2026-09-01T00:00:00Z",
}
_FILE_B = {
    "id": "file_b",
    "project_id": "pb",
    "name": "B 소유 문서",
    "media_type": "text/plain",
    "content_chars": 7,
    "created_at": "2026-09-02T00:00:00Z",
    "updated_at": "2026-09-02T00:00:00Z",
}
_SESSIONS = {
    "a": {"projects": [_PROJECT_A], "filesByProject": {"pa": [_FILE_A]}},
    "b": {"projects": [_PROJECT_B], "filesByProject": {"pb": [_FILE_B]}},
}


def test_signed_out_library_entry_is_fail_closed_and_issues_no_reads() -> None:
    _run_harness("signed_out", _SIGNED_OUT_AUTH, _SESSIONS)


def test_missing_project_file_storage_stays_navigable_and_explains_itself() -> None:
    _run_harness("storage_off", _SIGNED_IN_AUTH, _SESSIONS)


def test_signed_in_library_lists_real_files_and_opens_the_canonical_project() -> None:
    _run_harness("with_files", _SIGNED_IN_AUTH, _SESSIONS)


def test_account_switch_drops_the_previous_owner_rows() -> None:
    _run_harness("account_switch", _SIGNED_IN_AUTH, _SESSIONS)
