"""#2342 — Projects/File PDF/DOCX upload UI consumption contracts (tus 1단계).

Static string assertions alone do not prove behavior, so this file also runs a
Node harness that executes the REAL attachment-capabilities.js +
document-binary.js + project-file-upload.js + app.js in one vm context against
a minimal DOM shim with a recording fetch. The harness answers the tus
protocol on that fetch, so the real shared client (static/tus-upload.js) runs
end to end:

- BINARY uploads go through window.PadiemProjectFileUpload (tus) only — the old
  direct octet-stream POST is gone from app.js
- tus protocol: OPTIONS limits from the server, POST create with an
  Upload-Length and base64(UTF-8) Upload-Metadata the server decodes back to the
  raw name, PATCH chunks with Upload-Offset, HEAD offset reconcile on a dropped
  connection, and one result GET
- limits come from the server's OPTIONS answer (Tus-Max-Size), never a constant
- TEXT_POST_KEYS_EXACT {name, media_type, text} preserved byte-for-byte
- PROJECT_PICKER_SUBSET: PPTX rejected with zero network request
- SERVER_AUTHORITY: a 422 pickup result surfaces the module's first-party Korean
  guidance plus the error-code reference — never the raw server message
- RESUME: a dropped connection (status 0) is retried through onShouldRetry and
  completes on the second attempt
- RETRY: a second, successful upload after the failed one
- BUSY_ACCESSIBILITY: aria-busy + #projectFileStatus (with %) during upload,
  cleared after
- BASE64_NEVER_RENDERED: no encoded payload ever appears in dialog DOM text
"""

from __future__ import annotations

from functools import lru_cache

import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "static/app.js"
CAPABILITIES_JS = ROOT / "static/attachment-capabilities.js"
DOCUMENT_BINARY_JS = ROOT / "static/document-binary.js"
TUS_MODULE_JS = ROOT / "static/project-file-upload.js"
TUS_UPLOAD_JS = ROOT / "static/tus-upload.js"
LICENSES_HTML = ROOT / "static/third-party-licenses.html"
INDEX_HTML = ROOT / "static/index.html"
DOCUMENTS_CSS = ROOT / "static/documents.css"
POLISH_CSS = ROOT / "static/accessibility-polish.css"

PDF_BYTES = bytes([0x25, 0x50, 0x44, 0x46, 0x2D, 0x31, 0x2E, 0x34, 0x0A, 0x31, 0x2C, 0x30, 0x20, 0x6F])
DOCX_BYTES = bytes([0x50, 0x4B, 0x03, 0x04, 0x14, 0x00, 0x06, 0x00, 0x42, 0x42])


# ── static structural contracts ────────────────────────────────────────────


def test_html_has_accessible_project_file_status_surface() -> None:
    html = INDEX_HTML.read_text(encoding="utf-8")
    assert 'class="project-files-status" id="projectFileStatus" role="status" aria-live="polite" hidden' in html


def test_project_file_picker_accepts_text_pdf_docx_hwpx() -> None:
    html = INDEX_HTML.read_text(encoding="utf-8")
    accept = 'accept="text/plain,text/markdown,text/csv,application/json,.txt,.md,.markdown,.csv,.json,application/pdf,.pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,.docx,application/hwp+zip,.hwpx"'
    assert accept in html
    assert "presentationml" not in html
    assert "spreadsheetml" not in html
    assert ".pptx" not in html
    assert ".xlsx" not in html


def test_tus_wiring_static_contracts() -> None:
    # index.html loads the shared module once, before its lanes and app.js.
    html = INDEX_HTML.read_text(encoding="utf-8")
    assert html.count('src="./tus-upload.js"') == 1
    assert '<script src="./project-file-upload.js"></script>' in html
    assert html.index('src="./tus-upload.js"') < html.index("project-file-upload.js") < html.index('src="./app.js"')
    # No vendored client ships: its resume fingerprint lives in localStorage,
    # which the browser persistence audit refuses outright.
    assert not (ROOT / "static/tus-js-client-4.3.1.min.js").exists()
    assert not (ROOT / "static/tus-js-client-4.3.1.LICENSE.txt").exists()
    licenses = LICENSES_HTML.read_text(encoding="utf-8")
    assert "tus-js-client" not in licenses


def test_binary_uploads_only_through_the_shared_tus_module() -> None:
    source = APP_JS.read_text(encoding="utf-8")
    # The binary branch consumes the shared tus module; the text branch keeps
    # the exact JSON contract on the collection endpoint.
    assert "window.PadiemProjectFileUpload.upload({" in source
    assert 'payload = { name: documentFile.name, media_type: documentFile.mediaType, text: documentFile.text };' in source
    assert '/api/projects/${encodeURIComponent(editingProjectId)}/files' in source
    # The old direct octet-stream binary POST is gone for good.
    assert '"Content-Type": "application/octet-stream"' not in source
    assert "X-Padiem-Filename" not in source
    assert "body: file" not in source

    module = TUS_MODULE_JS.read_text(encoding="utf-8")
    assert "new tus.Upload(" not in module
    assert '"/api/projects/" + encodeURIComponent(projectId) + "/files/tus"' in module
    # The transport lives in the shared module: server-answered limits, the
    # three protocol verbs and the offset arithmetic are written once there.
    shared = TUS_UPLOAD_JS.read_text(encoding="utf-8")
    for needle in ("Tus-Max-Size", "X-Padiem-Tus-Chunk-Max", "Upload-Length",
                   "Upload-Metadata", "Upload-Offset", "application/offset+octet-stream"):
        assert needle in shared, needle
    # No browser persistence primitive anywhere in the uploader.
    for forbidden in ("localStorage", "sessionStorage", "indexedDB", "document.cookie"):
        assert forbidden not in shared, forbidden
    # First-party Korean guidance only; the server body survives as a code.
    assert "uiMessageSafe" in module and "uiMessageSafe" in shared


def test_no_console_logging_and_no_leftover_removed_symbol() -> None:
    source = APP_JS.read_text(encoding="utf-8")
    assert "console." not in source
    assert "PROJECT_BINARY_MEDIA" not in source


def test_status_line_css_and_accessibility_floor_present() -> None:
    documents = DOCUMENTS_CSS.read_text(encoding="utf-8")
    polish = POLISH_CSS.read_text(encoding="utf-8")
    assert ".project-files-status" in documents
    assert ".project-files-status" in polish


# ── behavioral proof via Node harness executing real app.js ─────────────────

_HARNESS = r"""
const fs = require("fs");
const vm = require("vm");
const APP = fs.readFileSync(process.argv[2], "utf8");
const CAPS = fs.readFileSync(process.argv[3], "utf8");
const DOCBIN = fs.readFileSync(process.argv[4], "utf8");
const TUSLIB = fs.readFileSync(process.argv[5], "utf8");
const TUSMODULE = fs.readFileSync(process.argv[6], "utf8");

const PDF_BYTES = Uint8Array.from([0x25, 0x50, 0x44, 0x46, 0x2D, 0x31, 0x2E, 0x34, 0x0A, 0x31, 0x2C, 0x30, 0x20, 0x6F]);
const DOCX_BYTES = Uint8Array.from([0x50, 0x4B, 0x03, 0x04, 0x14, 0x00, 0x06, 0x00, 0x42, 0x42]);

function makeEl(tag) {
  const el = {
    tagName: tag, id: "", className: "", textContent: "", hidden: false, open: false,
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
  el.scrollIntoView = () => {};
  el.showModal = () => { el.open = true; el.hidden = false; };
  el.close = () => { el.open = false; };
  el.click = () => (el.listeners.click || []).forEach((fn) => fn({ preventDefault() {}, target: el, key: "" }));
  el.requestSubmit = () => (el.listeners.submit || []).forEach((fn) => fn({ preventDefault() {} }));
  el.matches = () => false;
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
  "historySection","historyList","historyEmpty","projectsNavButton","projectsBadge","projectsSection",
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
byId.clawAction.options = [{ textContent: "견적서 초안" }];
byId.clawAction.value = "quote";

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
byId.projectForm.querySelector = () => makeEl("div");

class FileReader {
  constructor() { this.result = null; this._l = {}; }
  addEventListener(t, fn) { (this._l[t] = this._l[t] || []).push(fn); }
  readAsText(file) { this.result = file._text; setTimeout(() => (this._l.load || []).forEach((fn) => fn({ target: this })), 0); }
  readAsDataURL(file) { this.result = "data:,"; setTimeout(() => (this._l.load || []).forEach((fn) => fn({ target: this })), 0); }
}

function makeFile(name, type, bytes, text) {
  const slice = (start, end) => {
    const from = start || 0;
    const to = end === undefined ? bytes.length : Math.min(end, bytes.length);
    return { length: Math.max(0, to - from), _bytes: bytes.slice(from, to) };
  };
  return {
    name, type, size: bytes.length, _bytes: bytes, _text: text, slice,
    async arrayBuffer() { return Uint8Array.from(bytes).buffer; },
  };
}

const requests = [];
const busyDuringUpload = [];
const statusDuringUpload = [];
const percentDuringUpload = [];
let serverFiles = [];
let fileSeq = 0;
let tusFailure = null;   // {status, body} — the module's onShouldRetry must refuse it
let tusDrop = false;     // one simulated connection drop — onShouldRetry must retry it
let resumed = 0;
let tusResult = { status: 201, name: "이름 없음", media_type: "extracted/pdf" };

const tusCreates = [];
const tusPatches = [];
const tusHeads = [];
const uploads = new Map();
let uploadSeq = 0;
let tusOptions = 0;

function headerMap(values) {
  const lower = {};
  Object.keys(values || {}).forEach((k) => { lower[String(k).toLowerCase()] = String(values[k]); });
  return { get: (k) => (Object.prototype.hasOwnProperty.call(lower, String(k).toLowerCase())
    ? lower[String(k).toLowerCase()] : null) };
}
function decodeMetadata(raw) {
  const out = {};
  String(raw || "").split(",").forEach((pair) => {
    const at = pair.indexOf(" ");
    if (at < 0) return;
    out[pair.slice(0, at)] = Buffer.from(pair.slice(at + 1), "base64").toString("utf8");
  });
  return out;
}
function uploadState(u) {
  const path = String(u).replace(/^[a-z]+:\/\/[^/]+/i, "");
  return uploads.get(path) || null;
}

function jsonResponse(status, obj) { return { ok: status >= 200 && status < 300, status, json: async () => obj }; }
async function fetchImpl(url, opts) {
  opts = opts || {};
  const method = (opts.method || "GET").toUpperCase();
  const u = String(url);
  const isTextFilePost = method === "POST" && /\/api\/projects\/[^/]+\/files$/.test(u);
  requests.push({ url: u, method, body: isTextFilePost ? (opts.body ? JSON.parse(opts.body) : null) : opts.body, headers: opts.headers });
  if (u.startsWith("/api/auth/status")) return jsonResponse(200, { ready: true, authenticated: true, user: { name: "owner" }, history_ready: true, project_files_ready: true });
  const tusCollection = /\/api\/projects\/[^/]+\/files\/tus$/.test(u);
  const tusItem = /\/api\/projects\/[^/]+\/files\/tus\/[^/]+$/.test(u);
  if (method === "OPTIONS" && tusCollection) {
    tusOptions += 1;
    return {
      ok: true, status: 204, json: async () => ({}),
      headers: headerMap({ "tus-max-size": "1073741824", "x-padiem-tus-chunk-max": "94371840" }),
    };
  }
  if (method === "POST" && tusCollection) {
    const meta = decodeMetadata(opts.headers && opts.headers["Upload-Metadata"]);
    const length = Number(opts.headers && opts.headers["Upload-Length"]);
    const location = "/api/projects/p1/files/tus/stub-" + (++uploadSeq);
    tusCreates.push({ endpoint: u, length, filename: meta.filename, media_type: meta.filetype,
      raw_metadata: opts.headers && opts.headers["Upload-Metadata"] });
    uploads.set(location, { offset: 0, total: length });
    return { ok: true, status: 201, json: async () => ({ upload_id: "stub-" + uploadSeq }),
      headers: headerMap({ location }) };
  }
  if (method === "PATCH" && tusItem) {
    if (tusDrop) {
      tusDrop = false;
      resumed += 1;
      throw new TypeError("network down");
    }
    if (tusFailure) {
      const f = tusFailure; tusFailure = null;
      return jsonResponse(f.status, f.body);
    }
    const state = uploadState(u);
    const body = opts.body;
    const bytes = body && typeof body.length === "number" ? body.length : 0;
    state.offset += bytes;
    tusPatches.push({ url: u, offset: Number(opts.headers["Upload-Offset"]), bytes });
    return { ok: true, status: 204, json: async () => ({}),
      headers: headerMap({ "upload-offset": String(state.offset) }) };
  }
  if (method === "HEAD" && tusItem) {
    const state = uploadState(u);
    tusHeads.push(u);
    return { ok: true, status: 200, json: async () => ({}),
      headers: headerMap({ "upload-offset": String(state ? state.offset : 0) }) };
  }
  if (method === "GET" && tusItem) {
    if (tusResult.status !== 201) return jsonResponse(tusResult.status, tusResult.body);
    // The last chunk's progress paints the status line before the result
    // pickup, so that is the moment the UI contract applies to.
    percentDuringUpload.push(byId.projectFileStatus.hidden === false && /%$/.test(byId.projectFileStatus.textContent));
    busyDuringUpload.push(byId.projectFilesPanel.getAttribute("aria-busy"));
    statusDuringUpload.push(byId.projectFileStatus.hidden === false && byId.projectFileStatus.textContent.length > 0);
    fileSeq += 1;
    const projection = {
      id: "file_tus_" + fileSeq, project_id: "p1", name: tusResult.name, media_type: tusResult.media_type,
      content_chars: 120, created_at: "2026-11-01T00:00:00Z", updated_at: "2026-11-01T00:00:00Z",
    };
    serverFiles.push(projection);
    return jsonResponse(201, { file: projection });
  }
  if (isTextFilePost) {
    const body = requests[requests.length - 1].body;
    return jsonResponse(201, { file: {
      id: "file_text_" + (++fileSeq), project_id: "p1", name: body.name, media_type: body.media_type,
      content_chars: 120, created_at: "2026-09-11T00:00:00Z", updated_at: "2026-09-11T00:00:00Z",
    } });
  }
  if (method === "GET" && /\/api\/projects\/[^/]+\/files$/.test(u)) return jsonResponse(200, { files: serverFiles });
  if (u.startsWith("/api/projects")) return jsonResponse(200, { projects: [{ id: "p1", name: "테스트 프로젝트", instructions: "", created_at: "2026-09-10T00:00:00Z", updated_at: "2026-09-10T00:00:00Z" }] });
  if (u.startsWith("/api/conversations")) return jsonResponse(200, { conversations: [] });
  return jsonResponse(200, {});
}

const sandbox = {
  document: doc,
  fetch: fetchImpl,
  FileReader,
  btoa: (binary) => Buffer.from(binary, "latin1").toString("base64"),
  TextEncoder,
  AbortController: class { constructor() { this.signal = {}; } abort() {} },
  URL: { createObjectURL: () => "blob:x", revokeURL() {} },
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
vm.runInContext(TUSLIB, sandbox, { filename: "tus-upload.js" });
vm.runInContext(TUSMODULE, sandbox, { filename: "project-file-upload.js" });
if (!sandbox.PadiemBinaryDocuments) { console.log(JSON.stringify({ ok: false, error: "BINARY_HELPER_NOT_LOADED" })); process.exit(0); }
if (!sandbox.PadiemProjectFileUpload) { console.log(JSON.stringify({ ok: false, error: "TUS_MODULE_NOT_LOADED" })); process.exit(0); }
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
function findButtonByClass(root, className) {
  const stack = [...(root.children || [])];
  while (stack.length) {
    const el = stack.shift();
    const classes = String(el.className || "").split(/\s+/);
    if (String(el.tagName).toUpperCase() === "BUTTON" && classes.includes(className)) return el;
    stack.push(...(el.children || []));
  }
  return null;
}
function collectText(root) {
  let out = root.textContent || "";
  (root.children || []).forEach((c) => { out += " " + collectText(c); });
  return out;
}
function directFilePosts() { return requests.filter((r) => r.method === "POST" && /\/api\/projects\/[^/]+\/files$/.test(r.url)); }
function octetStreamPosts() {
  return directFilePosts().filter((r) => r.headers && r.headers["Content-Type"] === "application/octet-stream");
}
function pickAndUpload(file) {
  byId.projectFormError.hidden = true;
  byId.projectFormError.textContent = "";
  byId.projectFileInput.files = [file];
  (byId.projectFileInput.listeners.change || []).forEach((fn) => fn({ target: byId.projectFileInput }));
}

(async () => {
  const fail = (m) => { console.log(JSON.stringify({ ok: false, error: m, tusUploads: tusCreates.length, directPosts: directFilePosts().length })); process.exit(0); };
  const tick = (ms) => new Promise((r) => setTimeout(r, ms));
  await tick(60);

  // Open the manage dialog for the existing project (files panel visible, ready).
  const manage = findButtonByClass(byId.projectsList, "project-manage");
  if (!manage) fail("PROJECT_MANAGE_BUTTON_MISSING");
  manage.click();
  await tick(60);
  if (byId.projectFilesPanel.hidden !== false) fail("FILES_PANEL_NOT_VISIBLE");
  if (byId.projectDialog.open !== true) fail("DIALOG_NOT_OPENED");
  const getFilesAtOpen = requests.filter((r) => r.method === "GET" && /\/files$/.test(r.url)).length;

  // 1) Text file: payload keys remain EXACTLY {name, media_type, text}.
  pickAndUpload(makeFile("guide.md", "text/markdown", Buffer.from("# 제주 준비\n신분증을 챙긴다.", "utf8"), "# 제주 준비\n신분증을 챙긴다."));
  await tick(80);
  let posts = directFilePosts();
  if (posts.length !== 1) fail("TEXT_UPLOAD_POST_COUNT");
  const textKeys = Object.keys(posts[0].body).sort().join(",");
  if (textKeys !== "media_type,name,text") fail("TEXT_POST_KEYS_NOT_EXACT:" + textKeys);
  if (posts[0].body.media_type !== "text/markdown") fail("TEXT_POST_MEDIA_TYPE");
  if (tusCreates.length !== 0) fail("TEXT_USED_TUS");

  // 2) PDF: constructed on the tus endpoint with RAW metadata and server limits.
  tusResult = { status: 201, name: "positive.pdf", media_type: "extracted/pdf" };
  pickAndUpload(makeFile("positive.pdf", "application/pdf", PDF_BYTES, null));
  await tick(80);
  if (tusCreates.length !== 1) fail("PDF_TUS_NOT_USED");
  const pdfCreate = tusCreates[0];
  if (pdfCreate.endpoint !== "/api/projects/p1/files/tus") fail("PDF_TUS_ENDPOINT");
  if (pdfCreate.filename !== "positive.pdf") fail("PDF_METADATA_NOT_RAW");
  if (pdfCreate.media_type !== "application/pdf") fail("PDF_METADATA_TYPE");
  if (pdfCreate.length !== PDF_BYTES.length) fail("PDF_UPLOAD_LENGTH");
  if (tusOptions !== 1) fail("LIMITS_NOT_FROM_SERVER");
  if (tusPatches.length !== 1 || tusPatches[0].offset !== 0
      || tusPatches[0].bytes !== PDF_BYTES.length || tusPatches[0].bytes > 94371840) fail("PDF_CHUNK_SHAPE");
  if (octetStreamPosts().length !== 0) fail("OCTET_STREAM_DIRECT_POST_RETURNED");
  if (busyDuringUpload[0] !== "true") fail("ARIA_BUSY_NOT_SET_DURING_TUS");
  if (statusDuringUpload[0] !== true) fail("STATUS_LINE_NOT_VISIBLE_DURING_TUS");
  if (percentDuringUpload[0] !== true) fail("PERCENT_NOT_SHOWN_DURING_TUS");
  if (byId.projectFilesPanel.getAttribute("aria-busy") !== null) fail("ARIA_BUSY_NOT_CLEARED_AFTER_PDF");
  if (byId.projectFileStatus.hidden !== true) fail("STATUS_LINE_NOT_HIDDEN_AFTER_PDF");
  if (findRowText("positive.pdf") === null) fail("PDF_ROW_NOT_RENDERED");

  // 3) DOCX: same exact tus contract.
  tusResult = { status: 201, name: "report.docx", media_type: "extracted/docx" };
  pickAndUpload(makeFile("report.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", DOCX_BYTES, null));
  await tick(80);
  if (tusCreates.length !== 2) fail("DOCX_TUS_NOT_USED");
  if (tusCreates[1].media_type !== "application/vnd.openxmlformats-officedocument.wordprocessingml.document") fail("DOCX_METADATA_TYPE");

  // 4) PPTX is outside the project subset: rejected client-side, ZERO new requests.
  pickAndUpload(makeFile("deck.pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation", [1, 2, 3], null));
  await tick(80);
  if (tusCreates.length !== 2) fail("PPTX_ISSUED_TUS");
  if (byId.projectFormError.hidden !== false) fail("PPTX_ERROR_NOT_VISIBLE");

  // 5) Oversize follows the server's Tus-Max-Size answer, not a client constant.
  //    (The stub's discovery answer caps at 1GiB; a 2GiB file is refused before
  //    any tus construction, mirroring the module's preflight.)
  const bigBytes = new Uint8Array(8); bigBytes.size = 2 * 1073741824;
  const bigFile = makeFile("huge.pdf", "application/pdf", bigBytes, null);
  bigFile.size = 2 * 1073741824;
  pickAndUpload(bigFile);
  await tick(80);
  if (tusCreates.length !== 2) fail("OVERSIZE_REACHED_TUS");
  if (byId.projectFormError.hidden !== false) fail("OVERSIZE_ERROR_NOT_VISIBLE");
  if (!byId.projectFormError.textContent.includes("너무 커요")) fail("OVERSIZE_KOREAN_GUIDANCE_MISSING");

  // 6) Server remains the validation authority; the raw body never reaches the UI.
  tusFailure = { status: 422, body: { error: { code: "invalid_document", message: "SERVER_REJECT_MARKER_2342" } } };
  tusResult = { status: 201, name: "second.pdf", media_type: "extracted/pdf" };
  pickAndUpload(makeFile("second.pdf", "application/pdf", PDF_BYTES, null));
  await tick(80);
  if (tusCreates.length !== 3) fail("SERVER_ERROR_TUS_COUNT");
  if (byId.projectFormError.textContent !== "이 형식은 올릴 수 없어요.") fail("FIRST_PARTY_GUIDANCE_NOT_SHOWN:" + byId.projectFormError.textContent);
  const reference = byId.projectFormError.children.find((child) => child.className === "error-code");
  if (!reference || reference.textContent !== "error-code-reference: invalid_document") fail("REFERENCE_CODE_NOT_SHOWN");
  if (collectText(byId.projectFormError).includes("SERVER_REJECT_MARKER_2342")) fail("RAW_SERVER_ERROR_SHOWN");
  if (byId.projectFormError.hidden !== false) fail("SERVER_ERROR_NOT_VISIBLE");
  if (findRowText("second.pdf") !== null) fail("REJECTED_FILE_ROW_ADDED");
  if (byId.projectFilesPanel.getAttribute("aria-busy") !== null) fail("ARIA_BUSY_NOT_CLEARED_AFTER_FAILURE");

  // 7) Retry: the same pick succeeds once the server accepts it.
  tusFailure = null;
  pickAndUpload(makeFile("second.pdf", "application/pdf", PDF_BYTES, null));
  await tick(80);
  if (tusCreates.length !== 4) fail("RETRY_DID_NOT_ISSUE_SECOND_TUS");
  if (findRowText("second.pdf") === null) fail("RETRY_ROW_NOT_RENDERED");
  if (byId.projectFormError.hidden !== true) fail("ERROR_NOT_CLEARED_ON_RETRY");

  // 8) A dropped connection (status 0) is retried by the module's own policy.
  tusDrop = true;
  tusResult = { status: 201, name: "resumed.pdf", media_type: "extracted/pdf" };
  pickAndUpload(makeFile("resumed.pdf", "application/pdf", PDF_BYTES, null));
  await tick(80);
  if (tusCreates.length !== 5) fail("DROP_TUS_COUNT");
  if (resumed !== 1) fail("DROP_NOT_RETRIED");
  if (tusHeads.length !== 1) fail("DROP_DID_NOT_RECONCILE_OFFSET");
  if (findRowText("resumed.pdf") === null) fail("RESUMED_ROW_NOT_RENDERED");

  // 9) base64 must never appear in rendered dialog text.
  const dialogText = collectText(byId.projectDialog) + " " + collectText(byId.projectFormError);
  if (dialogText.includes("data:application/pdf;base64")) fail("BASE64_RENDERED_IN_DOM");

  // HWPX uses the same tus contract, without browser extraction.
  tusResult = { status: 201, name: "sample.hwpx", media_type: "extracted/hwpx" };
  pickAndUpload(makeFile("sample.hwpx", "application/hwp+zip", DOCX_BYTES, null));
  await tick(80);
  if (tusCreates.length !== 6) fail("HWPX_TUS_COUNT");
  if (tusCreates[5].media_type !== "application/hwp+zip") fail("HWPX_METADATA_TYPE");
  if (tusCreates[5].filename !== "sample.hwpx") fail("HWPX_METADATA_NOT_RAW");

  function findRowText(name) {
    const rows = byId.projectFilesList.children || [];
    for (const row of rows) { if (collectText(row).indexOf(name) >= 0) return name; }
    return null;
  }

  const getFiles = requests.filter((r) => r.method === "GET" && /\/files$/.test(r.url)).length;
  console.log(JSON.stringify({
    ok: true,
    tusUploads: tusCreates.length,
    directPosts: directFilePosts().length,
    octetStreamPosts: octetStreamPosts().length,
    getFiles,
    getFilesAtOpen,
    resumed,
  }));
})().catch((e) => { console.log(JSON.stringify({ ok: false, error: String((e && e.stack) || e) })); });
"""


# All consumers assert read-only facts from the same completed real app.js
# behavior journey. Reuse it once per Python module rather than respawning
# Node for each test; separate pytest processes still run independent checks.
@lru_cache(maxsize=1)
def _run_harness() -> dict:
    node = shutil.which("node")
    assert node, "node runtime is required for the behavioral harness"
    harness_path = ROOT / "tests" / "_b62_2342_behavior_harness.js"
    harness_path.write_text(_HARNESS, encoding="utf-8")
    try:
        result = subprocess.run(
            [node, str(harness_path), str(APP_JS), str(CAPABILITIES_JS), str(DOCUMENT_BINARY_JS),
             str(TUS_UPLOAD_JS), str(TUS_MODULE_JS)],
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


def test_behavioral_request_shapes_proved() -> None:
    payload = _run_harness()
    assert payload.get("ok") is True, payload
    # Every binary pick rode the tus module; the only direct collection POST is
    # the text document; the old octet-stream POST count is zero.
    assert payload["tusUploads"] == 6
    assert payload["directPosts"] == 1
    assert payload["octetStreamPosts"] == 0
    assert payload["resumed"] == 1
    # GET file refresh runs once at dialog open and once per SUCCESSFUL save —
    # never after the 422 (open, text, pdf, docx, retry, resumed, hwpx).
    assert payload["getFiles"] == payload["getFilesAtOpen"] + 6


if __name__ == "__main__":
    test_html_has_accessible_project_file_status_surface()
    test_project_file_picker_accepts_text_pdf_docx_hwpx()
    test_tus_wiring_static_contracts()
    test_binary_uploads_only_through_the_shared_tus_module()
    test_no_console_logging_and_no_leftover_removed_symbol()
    test_status_line_css_and_accessibility_floor_present()
    test_behavioral_harness_passes()
    test_behavioral_request_shapes_proved()
    print("B62_PROJECT_FILE_BINARY_UI_TESTS=PASS")
