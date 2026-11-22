"""Parsed views and the Node harness for the #3232/#4489 Library sidebar contracts (#8060 62차).

Every shipped-source read lives here (reusing claw_static and css_rules); the
test receives named facts, parsed selectors and behavior snapshots instead of
raw source text.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

from _support.claw_static import sheet
from css_rules import rules_for_sheet

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "static"
APP_JS = STATIC / "app.js"
LIBRARY_JS = STATIC / "library.js"
LIBRARY_CSS = STATIC / "library.css"
CAPABILITIES_JS = STATIC / "attachment-capabilities.js"
DOCUMENT_BINARY_JS = STATIC / "document-binary.js"

EXPECTED_PROJECT_API_TEMPLATES = {
    'fetch("/api/projects"',
    "fetch(`/api/projects/${encodeURIComponent(id)}`",
    "fetch(`/api/projects/${encodeURIComponent(projectId)}/files`",
    "fetch(`/api/projects/${encodeURIComponent(editingProjectId)}/files`",
    "fetch(`/api/projects/${encodeURIComponent(editingProjectId)}/files/${encodeURIComponent(fileId)}`",
    '"/api/projects"',
    "fetch(`/api/projects/${encodeURIComponent(deletingId)}`",
}


# ── shipped source readers (this module only) ──────────────────────────────


@lru_cache(maxsize=1)
def index_html() -> str:
    return sheet("index.html")


@lru_cache(maxsize=1)
def app_js_text() -> str:
    return sheet("app.js")


@lru_cache(maxsize=1)
def library_js_text() -> str:
    return sheet("library.js")


@lru_cache(maxsize=1)
def library_css_text() -> str:
    return sheet("library.css")


def _missing(values, needles) -> list[str]:
    return [needle for needle in needles if needle not in values]


# ── parsed facts: markup, CSS and module wiring ────────────────────────────


def sidebar_entry_facts() -> dict:
    html = index_html()
    at = html.index('id="filesNavButton"')
    button = html[at - 200:at + 200]
    return {
        "has_id": 'id="filesNavButton"' in html,
        "locale_key": 'data-locale-key="nav-files"' in html,
        "not_disabled": "disabled" not in button,
        "aria_current_false": 'aria-current="false"' in button,
    }


def destination_facts() -> dict:
    html = index_html()
    return {
        "view_id": 'id="libraryView"' in html,
        "tablist": 'role="tablist"' in html,
        "tabs": 'id="libraryFilesTab"' in html and 'id="libraryImagesTab"' in html,
        "band_order_ok": (
            html.index('id="calendarView"')
            < html.index('id="libraryView"')
            < html.index('<section class="conversation"')
        ),
        "css_link": 'href="./library.css"' in html,
        "css_before_head_end": html.index('href="./library.css"') < html.index("</head>"),
        "app_before_library": html.index('src="./app.js"') < html.index('src="./library.js"'),
        "library_before_adapter": html.index('src="./library.js"') < html.index('src="./claw-local-adapter.js"'),
    }


def library_css_facts() -> dict:
    css = library_css_text()
    selectors = [selector for rule in rules_for_sheet("library.css") for selector in rule.selectors]
    reviewed = (
        '.app-shell[data-state="library"] .library-view',
        '.app-shell:not([data-state="library"]) .library-view',
        '.app-shell[data-state="library"] .conversation',
        '.app-shell[data-state="library"] .composer-wrap',
    )
    return {
        "missing_selectors": _missing(selectors, reviewed),
        "important_display_none": "display: none !important;" in css,
    }


def view_block_facts() -> dict:
    css = library_css_text()
    start = css.index("\n.library-view {")
    block = css[start:css.index("}", start)]
    return {
        "position_relative": "position: relative;" in block,
        "z_index_two": re.search(r"z-index:\s*2;", block) is not None,
    }


def app_seam_facts() -> dict:
    source = app_js_text()
    seam = source[source.index("window.PadiemChatProjectOpener"):]
    seam = seam[:seam.index("});")]
    return {
        "legacy_tokens": [
            token for token in (
                "function filesNavAvailable()", "function syncFilesNav()", 'getElementById("filesNavButton")',
            ) if token in source
        ],
        "find_project": "projects.find((item) => item && item.id === projectId)" in seam,
        "open_dialog": "openProjectDialog(project)" in seam,
        "seam_guard": "if (!projectsReady || !authState.authenticated || inFlight) return false;" in seam,
    }


def library_reader_facts() -> dict:
    source = library_js_text()
    code = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("//"))
    return {
        "owner_endpoint": 'const OWNER_FILES_ENDPOINT = "/api/project-files";' in code,
        "limit_param": "limit=${OWNER_FILES_PAGE}" in code,
        "cursor_param": "cursor=${encodeURIComponent(after)}" in code,
        "removed_tokens": [
            token for token in (
                'fetch("/api/projects"', "/api/projects/${", "Promise.all", "MAX_PROJECTS_READ", "truncated",
            ) if token in code
        ],
        "forbidden_tokens": [
            token for token in ("/files/${", "/download", "/preview", "method:", "XMLHttpRequest", "createObjectURL")
            if token in code
        ],
        "fetch_count": code.count("await fetch("),
    }


def library_boundary_facts() -> dict:
    source = library_js_text()
    return {
        "forbidden_tokens": [
            token for token in (
                "localStorage", "sessionStorage", "indexedDB", "document.cookie", "cookieStore",
                "serviceWorker", "caches.open", "innerHTML", "outerHTML", "insertAdjacentHTML",
                "document.write", "srcdoc",
            ) if token in source
        ],
        "text_content": "textContent" in source,
        "no_console": "console." not in source,
    }


def backend_routes_facts() -> dict:
    source = app_js_text()
    found = set()
    for line in source.splitlines():
        stripped = line.strip()
        if "/api/projects" in stripped and (
            "fetch(" in stripped or stripped.startswith('"') or "url =" in stripped or "url=" in stripped
        ):
            for template in EXPECTED_PROJECT_API_TEMPLATES:
                if template in stripped:
                    found.add(template)
    return {
        "missing_templates": sorted(EXPECTED_PROJECT_API_TEMPLATES - found),
        "files_count": source.count("/files"),
        "upload_seam": "window.PadiemProjectFileUpload.upload({" in source,
        "forbidden_tokens": [
            token for token in ('"Content-Type": "application/octet-stream"', 'body: file') if token in source
        ],
        "payload_builder": (
            "payload = { name: documentFile.name, media_type: documentFile.mediaType, text: documentFile.text };"
            in source
        ),
        "no_console": "console." not in source,
    }


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
  // #4806 inserts the artifact context relative to #messageList, so the shim
  // needs the same child-insertion API the real Element exposes.
  el.insertBefore = (node, ref) => {
    const at = el.children.indexOf(ref);
    if (at < 0) el.children.push(node); else el.children.splice(at, 0, node);
    node.parentNode = el;
    return node;
  };
  el.removeChild = (node) => { el.children = el.children.filter((c) => c !== node); return node; };
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
  // #4806 added `messageList.closest(".conversation")` to the real app.js.
  // This minimal DOM shim must expose the same Element API instead of
  // crashing every behavioral harness that runs the real source.
  el.closest = (sel) => {
    const want = String(sel).replace(/^\./, "");
    let node = el;
    while (node) {
      if (node.className && String(node.className).includes(want)) return node;
      node = node.parentNode;
    }
    return null;
  };
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
// index.html nests #messageList inside <section class="conversation">, and the
// real app.js reads that ancestor to decide whether the first turn continues
// the landing panel (#4806). Model the same nesting instead of returning null.
if (byId.messageList) {
  const conversationSection = makeEl("section");
  conversationSection.className = "conversation";
  conversationSection.appendChild(byId.messageList);
}
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
  createElementNS: (_namespace, tag) => makeEl(tag),
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
function queryValue(u, name) {
  const q = u.indexOf("?");
  if (q < 0) return "";
  for (const part of u.slice(q + 1).split("&")) {
    const eq = part.indexOf("=");
    if (eq > 0 && part.slice(0, eq) === name) return decodeURIComponent(part.slice(eq + 1));
  }
  return "";
}
function ownerFilesOf(session) {
  let all = [];
  if (session && Array.isArray(session.files)) all = session.files.slice();
  else {
    const table = (session && session.filesByProject) || {};
    for (const pid of Object.keys(table)) all = all.concat(table[pid] || []);
  }
  // Newest first with an id tie-break: the same keyset order the server promises.
  return all.sort((a, b) => (a.updated_at === b.updated_at
    ? (a.id < b.id ? 1 : -1)
    : (a.updated_at < b.updated_at ? 1 : -1)));
}
// Page tokens are handed out by this stub only. A client that invented its own position
// is refused, which is what keeps the walk server-driven instead of client-guessed.
const issuedTokens = new Map();
let tokenSeq = 0;
function pageOf(files, limit, cursor) {
  let start = 0;
  if (cursor) {
    if (!issuedTokens.has(cursor)) return { rejected: true };
    start = issuedTokens.get(cursor);
  }
  const cap = FIXTURE.pageCap ? Math.min(limit, FIXTURE.pageCap) : limit;
  if (FIXTURE.emptyFirstPage && start === 0) {
    if (!files.length) return { files: [], has_more: false, next_cursor: null };
    const token = "tok-" + (++tokenSeq);
    issuedTokens.set(token, 0);
    return { files: [], has_more: true, next_cursor: token };
  }
  const page = files.slice(start, start + cap);
  const next = start + cap;
  let token = null;
  if (next < files.length) {
    token = "tok-" + (++tokenSeq);
    issuedTokens.set(token, next);
  }
  return { files: page, has_more: next < files.length, next_cursor: token };
}
async function fetchImpl(url, opts) {
  opts = opts || {};
  const method = (opts.method || "GET").toUpperCase();
  const u = String(url);
  requests.push({ url: u, method });
  if (u.startsWith("/api/auth/status")) return jsonResponse(200, FIXTURE.auth);
  if (method === "GET" && u.startsWith("/api/project-files")) {
    const pages = requests.filter((r) => r.url.startsWith("/api/project-files")).length;
    if (FIXTURE.failAfterPages && pages > FIXTURE.failAfterPages) {
      return jsonResponse(503, { error: { code: "project_files_unavailable" } });
    }
    // One transient page failure, followed by a genuinely successful retry.
    if (FIXTURE.failPageOnce && pages === 2) {
      return jsonResponse(503, { error: { code: "project_files_unavailable" } });
    }
    const limit = Number(queryValue(u, "limit") || "50");
    const result = pageOf(ownerFilesOf(FIXTURE.sessions[FIXTURE.activeSession]), limit, queryValue(u, "cursor"));
    if (result.rejected) return jsonResponse(400, { error: { code: "invalid_cursor" } });
    return jsonResponse(200, result);
  }
  if (method === "GET" && /\/api\/projects\/[^/]+\/files$/.test(u)) {
    // Still served for the project dialog itself; the Library must not use it.
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
  dispatchEvent: (event) => { (windowListeners[event.type] || []).forEach((fn) => fn(event)); },
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
vm.runInContext(fs.readFileSync(require("path").join(require("path").dirname(process.argv[2]), "auth-session.js"), "utf8"), sandbox, { filename: "auth-session.js" });
vm.runInContext(fs.readFileSync(require("path").join(require("path").dirname(process.argv[2]), "chat-session.js"), "utf8"), sandbox, { filename: "chat-session.js" });
vm.runInContext(fs.readFileSync(require("path").join(require("path").dirname(process.argv[2]), "claw-session.js"), "utf8"), sandbox, { filename: "claw-session.js" });
vm.runInContext(APP, sandbox, { filename: "app.js" });
vm.runInContext(LIBRARY, sandbox, { filename: "library.js" });
// #7782 — the library viewer seam ships next to library.js and must be loaded
// wherever the Library surface is exercised.
vm.runInContext(fs.readFileSync(require("path").join(require("path").dirname(process.argv[2]), "library-file-viewer.js"), "utf8"), sandbox, { filename: "library-file-viewer.js" });

function dispatchAuth(auth) {
  sandbox.PadiemProductCapabilities.get = () => ({ auth });
  (windowListeners["padiem:capabilitychange"] || []).forEach((fn) => fn({ detail: { auth } }));
}
function projectRequests() { return requests.filter((r) => r.url.startsWith("/api/projects")); }
function fileRequests() { return requests.filter((r) => /\/api\/projects\/[^/]+\/files/.test(r.url)); }
function ownerFileRequests() { return requests.filter((r) => r.url.startsWith("/api/project-files")); }
function cursorRequests() { return ownerFileRequests().filter((r) => r.url.indexOf("cursor=") >= 0); }
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
// The continuation affordance the module appends while the server reports more pages.
const MORE_TITLE = "이보다 오래된 저장 파일이 있습니다.";
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
    fileRows: rowText().filter((text) => text !== MORE_TITLE),
    hasMoreRow: rowText().includes(MORE_TITLE),
    filesPanelShown: byId.libraryFilesPanel.hidden !== true,
    imagesPanelShown: byId.libraryImagesPanel.hidden !== true,
    imagesRows: collect(byId.libraryImageList, "library-item-title").length,
    imagesText: collect(byId.libraryImageList, "library-item-title").concat(collect(byId.libraryImageList, "library-item-detail")).map((el) => el.textContent).join("|"),
    imagesHasAction: collect(byId.libraryImageList, "library-item-action").length > 0,
    outcome: sandbox.PadiemChatLibrary.getOutcome(),
    hasMore: sandbox.PadiemChatLibrary.hasMore(),
    complete: sandbox.PadiemChatLibrary.isComplete(),
    partial: sandbox.PadiemChatLibrary.hasPartialFailure(),
    ownerFileApiCalls: ownerFileRequests().length,
    cursorCalls: cursorRequests().length,
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
    if (s.disabled !== false) fail("SIGNED_OUT_ENTRY_MUST_BE_CLICKABLE");
    clickEntry();
    await tick(30);
    s = snapshot();
    if (s.viewHidden) fail("SIGNED_OUT_MUST_OPEN_VIEW");
    if (s.state !== "library") fail("SIGNED_OUT_MUST_CHANGE_SURFACE");
    if (s.note.indexOf("로그인") < 0) fail("SIGNED_OUT_NOTE_MISSING:" + s.note);
    if (s.rows.length !== 0) fail("SIGNED_OUT_MUST_RENDER_NO_ROWS:" + JSON.stringify(s.rows));
    if (s.projectApiCalls !== 0 || s.fileApiCalls !== 0 || s.ownerFileApiCalls !== 0) {
      fail("SIGNED_OUT_MUST_ISSUE_NO_PROJECT_REQUESTS");
    }
  } else if (mode === "storage_off") {
    dispatchAuth({ loaded: true, authenticated: true, historyReady: true, projectFilesReady: false });
    await tick(30);
    let s = snapshot();
    // #4489: missing project-file storage must NOT make the entry inert.
    if (s.disabled !== false) fail("STORAGE_OFF_MUST_STILL_ALLOW_NAVIGATION");
    clickEntry();
    await tick(30);
    s = snapshot();
    if (s.viewHidden) fail("MUST_OPEN_LIBRARY_VIEW");
    if (s.state !== "library") fail("SURFACE_STATE_NOT_LIBRARY");
    if (s.ariaCurrent !== "page") fail("ENTRY_NOT_MARKED_CURRENT");
    if (s.outcome !== "storage-off") fail("OUTCOME_NOT_STORAGE_OFF:" + s.outcome);
    if (!/켜지지 않았습니다/.test(s.note)) fail("NOTE_MUST_EXPLAIN:" + s.note);
    // Honest unavailable must not be manufactured into a successful empty read.
    if (s.fileApiCalls !== 0 || s.ownerFileApiCalls !== 0) fail("STORAGE_OFF_MUST_ISSUE_NO_FILE_REQUESTS");
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
    if (s.fileRows.length !== 1 || s.fileRows[0] !== "A 소유 문서") fail("ROWS:" + JSON.stringify(s.fileRows));
    if (s.ownerFileApiCalls !== 1) fail("MUST_READ_OWNER_FILE_PAGE_ONCE:" + s.ownerFileApiCalls);
    // The per-project fan-out is gone: opening the Library must not read project files
    // one project at a time any more.
    if (s.fileApiCalls !== 0) fail("LIBRARY_MUST_NOT_FAN_OUT_PER_PROJECT:" + s.fileApiCalls);
    if (s.hasMore || !s.complete) fail("SINGLE_PAGE_MUST_BE_COMPLETE");
    if (s.hasMoreRow) fail("NO_CONTINUATION_ROW_WHEN_COMPLETE");
    if (!/저장된 파일 1개/.test(s.note)) fail("NOTE_MUST_COUNT_TRUTHFULLY:" + s.note);
    if (!/가장 오래된 파일까지/.test(s.note)) fail("NOTE_MUST_MARK_THE_END:" + s.note);
    const buttons = rowButtons();
    if (buttons.length !== 1) fail("ACTION_MISSING");
    buttons[0].click();
    await tick(60);
    s = snapshot();
    // #7782 — the project action opens the project's file list through the
    // library viewer seam; the settings dialog must stay closed.
    if (!sandbox.PadiemChatLibraryFiles || !sandbox.PadiemChatLibraryFiles.isProjectOpen()) fail("MUST_OPEN_PROJECT_FILE_LIST");
    if (s.dialogOpen) fail("MUST_NOT_OPEN_SETTINGS_DIALOG");
    const listText = collect(doc.body, "library-item-title").map((el) => el.textContent).join("|");
    if (listText.indexOf("A 소유 문서") < 0) fail("FILE_LIST_MUST_LIST_THE_FILE:" + listText);
  } else if (mode === "auth_session_owner_events") {
    const status = {ready: true, authenticated: true, project_files_ready: true,
      user: {email: "a@example.test", name: "Same name"}};
    sandbox.PadiemAuthSession.update(status, 10);
    await tick(30);
    clickEntry();
    await tick(60);
    const before = snapshot();
    if (before.fileRows.length !== 1) fail("FIRST_OWNER_NOT_LOADED");
    sandbox.PadiemAuthSession.update({...status, user: {...status.user}}, 11);
    await tick(60);
    if (snapshot().ownerFileApiCalls !== before.ownerFileApiCalls) fail("SAME_SESSION_RELOADED");
    if (snapshot().fileRows[0] !== before.fileRows[0]) fail("SAME_SESSION_LOST_ROWS");
    FIXTURE.activeSession = "b";
    sandbox.PadiemAuthSession.update({...status, user: {...status.user, email: "b@example.test"}}, 12);
    if (snapshot().fileRows.length !== 0) fail("OWNER_EVENT_MUST_CLEAR_SYNCHRONOUSLY");
    await tick(60);
    const after = snapshot();
    if (after.fileRows.length !== 1 || after.fileRows[0] === before.fileRows[0]) fail("STALE_OWNER_EVENT_ROWS");
    if (after.ownerFileApiCalls !== before.ownerFileApiCalls + 1) fail("OWNER_EVENT_MUST_RELOAD_ONCE");
    sandbox.PadiemAuthSession.update({ready: true, authenticated: false}, 13);
    if (snapshot().fileRows.length !== 0) fail("LOGOUT_EVENT_MUST_CLEAR_SYNCHRONOUSLY");
  } else if (mode === "account_switch_same_flags") {
    dispatchAuth({ loaded: true, authenticated: true, historyReady: true, projectFilesReady: true });
    await tick(30);
    clickEntry();
    await tick(60);
    let s = snapshot();
    if (s.rows.length !== 1 || s.rows[0] !== "A 소유 문서") fail("FIRST_OWNER_MISSING");
    // Account B replaces A without a signed-out capability event. The two
    // accounts project exactly the same authenticated/storage booleans.
    FIXTURE.activeSession = "b";
    dispatchAuth({ loaded: true, authenticated: true, historyReady: true, projectFilesReady: true });
    await tick(60);
    s = snapshot();
    if (s.rows.some((name) => name.includes("A 소유"))) fail("STALE_OWNER_A_RENDERED:" + JSON.stringify(s.rows));
    if (s.rows.length !== 1 || s.rows[0] !== "B 소유 문서") fail("NEW_OWNER_B_MISSING:" + JSON.stringify(s.rows));
  } else if (mode === "incomplete_empty") {
    // The server reported another page while this page carried no rows. That is not an
    // empty account and must never be presented as one.
    dispatchAuth({ loaded: true, authenticated: true, historyReady: true, projectFilesReady: true });
    await tick(30);
    clickEntry();
    await tick(80);
    const s = snapshot();
    if (s.fileRows.length !== 0) fail("EXPECTED_NO_ROWS_ON_FIRST_PAGE");
    if (s.hasMore !== true || s.complete !== false) fail("INCOMPLETE_PAGE_STATE:" + JSON.stringify([s.hasMore, s.complete]));
    if (!/전체 목록을 확인한 것은 아닙니다/.test(s.note)) fail("INCOMPLETE_SCOPE_HIDDEN:" + s.note);
    if (/저장된 파일 0개/.test(s.note)) fail("MUST_NOT_COUNT_AS_A_TOTAL:" + s.note);
    if (!s.hasMoreRow) fail("CONTINUATION_AFFORDANCE_MISSING");
  } else if (mode === "walk_to_end") {
    dispatchAuth({ loaded: true, authenticated: true, historyReady: true, projectFilesReady: true });
    await tick(30);
    clickEntry();
    await tick(80);
    let s = snapshot();
    if (s.fileRows.length !== 1 || !s.hasMore || s.complete) fail("FIRST_PAGE:" + JSON.stringify(s.fileRows));
    if (!/지금까지 확인한 파일 1개/.test(s.note)) fail("PARTIAL_COUNT_MUST_NOT_CLAIM_TOTAL:" + s.note);
    for (let step = 0; step < 4; step += 1) {
      if (!s.hasMore) break;
      const actions = rowButtons();
      if (!actions.length) fail("CONTINUATION_LOST_AT_STEP:" + step);
      actions[actions.length - 1].click();
      await tick(80);
      s = snapshot();
    }
    if (s.fileRows.length !== 3) fail("WALK_ROWS:" + JSON.stringify(s.fileRows));
    if (new Set(s.fileRows).size !== 3) fail("WALK_DUPLICATED_ROWS:" + JSON.stringify(s.fileRows));
    if (s.hasMore || !s.complete) fail("WALK_NOT_FINISHED");
    if (s.cursorCalls !== 2) fail("WALK_MUST_ECHO_SERVER_CURSORS:" + s.cursorCalls);
    if (s.ownerFileApiCalls !== 3) fail("WALK_PAGE_COUNT:" + s.ownerFileApiCalls);
    if (!/저장된 파일 3개/.test(s.note) || !/가장 오래된 파일까지/.test(s.note)) fail("FINAL_NOTE:" + s.note);
    if (s.hasMoreRow) fail("CONTINUATION_ROW_MUST_LEAVE_AT_THE_END");
  } else if (mode === "page_failure") {
    dispatchAuth({ loaded: true, authenticated: true, historyReady: true, projectFilesReady: true });
    await tick(30);
    clickEntry();
    await tick(80);
    let s = snapshot();
    if (s.fileRows.length !== 1 || !s.hasMore) fail("FIRST_PAGE:" + JSON.stringify(s.fileRows));
    const actions = rowButtons();
    actions[actions.length - 1].click();
    await tick(80);
    s = snapshot();
    // A failed page keeps what was already confirmed, but the listing is no longer
    // allowed to read as complete, and the retry path must stay reachable.
    if (s.fileRows.length !== 1) fail("FAILED_PAGE_MUST_KEEP_ROWS:" + JSON.stringify(s.fileRows));
    if (s.partial !== true || s.complete !== false) fail("FAILED_PAGE_STATE:" + JSON.stringify([s.partial, s.complete]));
    if (!/전체가 아닙니다/.test(s.note)) fail("FAILED_PAGE_NOTE:" + s.note);
    if (!s.hasMoreRow) fail("RETRY_PATH_LOST");
  } else if (mode === "page_failure_recovery") {
    dispatchAuth({ loaded: true, authenticated: true, historyReady: true, projectFilesReady: true });
    await tick(30);
    clickEntry();
    await tick(80);
    let s = snapshot();
    if (s.fileRows.length !== 1 || !s.hasMore || s.partial) fail("RECOVERY_FIRST_PAGE");
    rowButtons()[rowButtons().length - 1].click();
    await tick(80);
    s = snapshot();
    if (!s.partial || s.fileRows.length !== 1 || !s.hasMore) fail("RECOVERY_FAILURE_NOT_SEEN");
    // Retry exactly the failed cursor. The prior error warning must disappear.
    rowButtons()[rowButtons().length - 1].click();
    await tick(80);
    s = snapshot();
    if (s.partial || s.complete || s.fileRows.length !== 2 || !s.hasMore) {
      fail("RECOVERY_WARNING_STALE_AFTER_SUCCESS:" + JSON.stringify(s));
    }
    rowButtons()[rowButtons().length - 1].click();
    await tick(80);
    s = snapshot();
    if (s.partial || !s.complete || s.hasMore || s.fileRows.length !== 3) {
      fail("RECOVERY_FINAL_STATE_WRONG:" + JSON.stringify(s));
    }
    if (!/저장된 파일 3개/.test(s.note) || /전체가 아닙니다/.test(s.note)) {
      fail("RECOVERY_FINAL_COPY_WRONG:" + s.note);
    }
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
    if (s.disabled !== false) fail("LOGOUT_MUST_NOT_DISABLE_ENTRY");
    // A visitor can still open the page after logout, and that open must not
    // re-read anything: the row set and every endpoint counter stay where they were.
    const readsBefore = { file: s.fileApiCalls, owner: s.ownerFileApiCalls, project: s.projectApiCalls };
    clickEntry();
    await tick(30);
    s = snapshot();
    if (s.viewHidden) fail("LOGOUT_PAGE_MUST_STAY_BROWSABLE");
    if (s.rows.length !== 0) fail("LOGOUT_REOPEN_MUST_SHOW_NO_ROWS:" + JSON.stringify(s.rows));
    if (s.note.indexOf("로그인") < 0) fail("LOGOUT_REOPEN_NOTE_MISSING:" + s.note);
    if (s.fileApiCalls !== readsBefore.file || s.ownerFileApiCalls !== readsBefore.owner
      || s.projectApiCalls !== readsBefore.project) fail("LOGOUT_REOPEN_ISSUED_READS");
    // Leave the page again so the next owner's step still starts from a closed view.
    (byId.libraryCloseButton.listeners.click || []).forEach((fn) => fn({ preventDefault() {} }));
    await tick(30);
    if (!snapshot().viewHidden) fail("CLOSE_BUTTON_DID_NOT_LEAVE_LIBRARY");
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

def _run_harness(mode: str, auth: dict, sessions: dict, options: dict | None = None) -> dict:
    node = shutil.which("node")
    assert node, "node runtime is required for the behavioral harness"
    harness_path = ROOT / "tests" / f"_b62_4489_behavior_harness_{mode}.js"
    harness_path.write_text(_HARNESS, encoding="utf-8")
    fixture = json.dumps({
        "mode": mode,
        "auth": auth,
        "activeSession": "a",
        "sessions": sessions,
        **(options or {}),
    })
    try:
        proc = subprocess.run(
            [node, str(harness_path), str(APP_JS), str(LIBRARY_JS), str(CAPABILITIES_JS), str(DOCUMENT_BINARY_JS), fixture],
            capture_output=True,
            text=True, encoding="utf-8",
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


run_harness = _run_harness

