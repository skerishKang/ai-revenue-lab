"""#2342 — Projects/File PDF/DOCX upload UI consumption contracts.

Static string assertions alone do not prove behavior, so this file also runs a
Node harness that executes the REAL attachment-capabilities.js +
document-binary.js + app.js in one vm context against a minimal DOM shim with a
recording fetch. The harness proves actual change -> request behavior:

- BINARY_POST_KEYS_EXACT {name, media_type, base64} (PDF and DOCX)
- TEXT_POST_KEYS_EXACT {name, media_type, text} preserved byte-for-byte
- PROJECT_PICKER_SUBSET: PPTX rejected with zero network request
- OVERSIZE PREFLIGHT: >2 MiB PDF rejected client-side, zero request
- SERVER_AUTHORITY: 422 error.message surfaced verbatim in #projectFormError
- RETRY: a second, successful POST after the failed one
- BUSY_ACCESSIBILITY: aria-busy + #projectFileStatus visible during POST, cleared after
- BASE64_NEVER_RENDERED: the encoded payload never appears in dialog DOM text
"""

from __future__ import annotations

import base64
import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "static/app.js"
CAPABILITIES_JS = ROOT / "static/attachment-capabilities.js"
DOCUMENT_BINARY_JS = ROOT / "static/document-binary.js"
INDEX_HTML = ROOT / "static/index.html"
DOCUMENTS_CSS = ROOT / "static/documents.css"
POLISH_CSS = ROOT / "static/accessibility-polish.css"

PDF_BYTES = bytes([0x25, 0x50, 0x44, 0x46, 0x2D, 0x31, 0x2E, 0x34, 0x0A, 0x31, 0x2C, 0x30, 0x20, 0x6F])
DOCX_BYTES = bytes([0x50, 0x4B, 0x03, 0x04, 0x14, 0x00, 0x06, 0x00, 0x42, 0x42])
PDF_BASE64 = base64.b64encode(PDF_BYTES).decode("ascii")


# ── static structural contracts ────────────────────────────────────────────


def test_html_has_accessible_project_file_status_surface() -> None:
    html = INDEX_HTML.read_text(encoding="utf-8")
    assert 'class="project-files-status" id="projectFileStatus" role="status" aria-live="polite" hidden' in html


def test_project_file_picker_accepts_text_plus_pdf_docx_only() -> None:
    html = INDEX_HTML.read_text(encoding="utf-8")
    accept = 'accept="text/plain,text/markdown,text/csv,application/json,.txt,.md,.markdown,.csv,.json,application/pdf,.pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,.docx"'
    assert accept in html
    assert "presentationml" not in html
    assert "spreadsheetml" not in html
    assert ".pptx" not in html
    assert ".xlsx" not in html


def test_binary_and_text_payload_shapes_are_exact_in_source() -> None:
    source = APP_JS.read_text(encoding="utf-8")
    assert 'payload = { name: documentFile.name, media_type: documentFile.mediaType, base64: documentFile.base64 };' in source
    assert 'payload = { name: documentFile.name, media_type: documentFile.mediaType, text: documentFile.text };' in source
    # the binary branch must consume the shared helper, not a private reader
    assert "binaryDocuments.read(file)" in source


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

const PDF_BYTES = Uint8Array.from([0x25, 0x50, 0x44, 0x46, 0x2D, 0x31, 0x2E, 0x34, 0x0A, 0x31, 0x2C, 0x30, 0x20, 0x6F]);
const DOCX_BYTES = Uint8Array.from([0x50, 0x4B, 0x03, 0x04, 0x14, 0x00, 0x06, 0x00, 0x42, 0x42]);
const PDF_BASE64 = Buffer.from(PDF_BYTES).toString("base64");

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
  "historySection","historyList","historyEmpty","projectsNavButton","projectsBadge","projectsSection",
  "projectsList","projectsEmpty","projectCreateButton","projectBanner","activeProjectName","activeProjectFiles",
  "editProjectButton","exitProjectButton","projectDialog","projectForm","projectDialogTitle","projectDialogClose",
  "projectDialogCancel","projectNameInput","projectInstructionsInput","projectFormError","projectSaveButton",
  "projectFilesPanel","projectFileInput","projectFilesList","projectFilesEmpty","projectFileStatus",
  "clawNavButton","clawWorkspace","clawManualForm","clawChannel","clawAction","clawSender","clawRequestText",
  "clawResultArea","clawResultPreview","clawResultCard","clawResultEmpty","clawResultKind","clawGenerateBtn",
  "clawExecuteButton","clawResultBadge","clawResultOpen","clawResultDocx","clawStatus","clawArtifactMeta",
  "clawArtifactName","clawArtifactSize","clawResultSuccessNote","clawResultHint","clawExecuteHint",
  "clawApprovedMemory","clawApprovedRefresh","clawApprovedLoading","clawApprovedError","clawApprovedList",
  "clawApprovedEmpty","clawMemoryReview",
].forEach((id) => add(id, "div"));
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
  return {
    name, type, size: bytes.length, _bytes: bytes, _text: text,
    async arrayBuffer() { return Uint8Array.from(bytes).buffer; },
  };
}

const requests = [];
const busyDuringPost = [];
const statusDuringPost = [];
let serverFiles = [];      // GET /files responses (server-owned safe projections)
let nextPostFailure = null; // {status, body}
let postSeq = 0;
function jsonResponse(status, obj) { return { ok: status >= 200 && status < 300, status, json: async () => obj }; }
async function fetchImpl(url, opts) {
  opts = opts || {};
  const method = (opts.method || "GET").toUpperCase();
  const u = String(url);
  const body = opts.body ? JSON.parse(opts.body) : null;
  requests.push({ url: u, method, body });
  if (u.startsWith("/api/auth/status")) return jsonResponse(200, { ready: true, authenticated: true, user: { name: "owner" }, history_ready: true, project_files_ready: true });
  if (method === "POST" && /\/api\/projects\/[^/]+\/files$/.test(u)) {
    busyDuringPost.push(byId.projectFilesPanel.getAttribute("aria-busy"));
    statusDuringPost.push(byId.projectFileStatus.hidden === false && byId.projectFileStatus.textContent.length > 0);
    postSeq += 1;
    if (nextPostFailure) {
      const failure = nextPostFailure;
      nextPostFailure = null;
      return jsonResponse(failure.status, failure.body);
    }
    const projection = {
      id: "file_" + postSeq, project_id: "p1", name: body.name,
      media_type: body.base64 !== undefined ? (body.media_type === "application/pdf" ? "extracted/pdf" : "extracted/docx") : body.media_type,
      content_chars: 120, created_at: "2026-09-11T00:00:00Z", updated_at: "2026-09-11T00:00:00Z",
    };
    serverFiles.push(projection);
    return jsonResponse(201, { file: projection });
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
if (!sandbox.PadiemBinaryDocuments) { console.log(JSON.stringify({ ok: false, error: "BINARY_HELPER_NOT_LOADED" })); process.exit(0); }
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
function filePosts() { return requests.filter((r) => r.method === "POST" && /\/api\/projects\/[^/]+\/files$/.test(r.url)); }
function pickAndUpload(file) {
  byId.projectFormError.hidden = true;
  byId.projectFormError.textContent = "";
  byId.projectFileInput.files = [file];
  (byId.projectFileInput.listeners.change || []).forEach((fn) => fn({ target: byId.projectFileInput }));
}

(async () => {
  const fail = (m) => { console.log(JSON.stringify({ ok: false, error: m, posts: filePosts().length })); process.exit(0); };
  const tick = (ms) => new Promise((r) => setTimeout(r, ms));
  await tick(60);

  // Open the manage dialog for the existing project (files panel visible, ready).
  const manage = findButton(byId.projectsList, "관리");
  if (!manage) fail("PROJECT_MANAGE_BUTTON_MISSING");
  manage.click();
  await tick(60);
  if (byId.projectFilesPanel.hidden !== false) fail("FILES_PANEL_NOT_VISIBLE");
  if (byId.projectDialog.open !== true) fail("DIALOG_NOT_OPENED");

  // 1) Text file: payload keys remain EXACTLY {name, media_type, text}.
  pickAndUpload(makeFile("guide.md", "text/markdown", Buffer.from("# 제주 준비\n신분증을 챙긴다.", "utf8"), "# 제주 준비\n신분증을 챙긴다."));
  await tick(80);
  let posts = filePosts();
  if (posts.length !== 1) fail("TEXT_UPLOAD_POST_COUNT");
  const textKeys = Object.keys(posts[0].body).sort().join(",");
  if (textKeys !== "media_type,name,text") fail("TEXT_POST_KEYS_NOT_EXACT:" + textKeys);
  if (posts[0].body.media_type !== "text/markdown") fail("TEXT_POST_MEDIA_TYPE");

  // 2) PDF: binary payload keys EXACTLY {name, media_type, base64}.
  pickAndUpload(makeFile("positive.pdf", "application/pdf", PDF_BYTES, null));
  await tick(80);
  posts = filePosts();
  if (posts.length !== 2) fail("PDF_POST_COUNT");
  const pdfKeys = Object.keys(posts[1].body).sort().join(",");
  if (pdfKeys !== "base64,media_type,name") fail("PDF_POST_KEYS_NOT_EXACT:" + pdfKeys);
  if (posts[1].body.media_type !== "application/pdf") fail("PDF_POST_MEDIA_TYPE");
  if (posts[1].body.base64 !== PDF_BASE64) fail("PDF_BASE64_PAYLOAD_MISMATCH");
  if (busyDuringPost[1] !== "true") fail("ARIA_BUSY_NOT_SET_DURING_PDF_POST");
  if (statusDuringPost[1] !== true) fail("STATUS_LINE_NOT_VISIBLE_DURING_PDF_POST");
  if (byId.projectFilesPanel.getAttribute("aria-busy") !== null) fail("ARIA_BUSY_NOT_CLEARED_AFTER_PDF");
  if (byId.projectFileStatus.hidden !== true) fail("STATUS_LINE_NOT_HIDDEN_AFTER_PDF");
  if (findRowText("positive.pdf") === null) fail("PDF_ROW_NOT_RENDERED");

  // 3) DOCX: same exact binary contract.
  pickAndUpload(makeFile("report.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", DOCX_BYTES, null));
  await tick(80);
  posts = filePosts();
  if (posts.length !== 3) fail("DOCX_POST_COUNT");
  const docxKeys = Object.keys(posts[2].body).sort().join(",");
  if (docxKeys !== "base64,media_type,name") fail("DOCX_POST_KEYS_NOT_EXACT:" + docxKeys);
  if (posts[2].body.media_type !== "application/vnd.openxmlformats-officedocument.wordprocessingml.document") fail("DOCX_POST_MEDIA_TYPE");

  // 4) PPTX is outside the project subset: rejected client-side, ZERO new requests.
  pickAndUpload(makeFile("deck.pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation", [1, 2, 3], null));
  await tick(80);
  if (filePosts().length !== 3) fail("PPTX_ISSUED_REQUEST");
  if (byId.projectFormError.hidden !== false) fail("PPTX_ERROR_NOT_VISIBLE");

  // 5) Oversize PDF (>2 MiB): size preflight before the request, ZERO new requests.
  const big = new Uint8Array(2 * 1024 * 1024 + 1);
  pickAndUpload(makeFile("huge.pdf", "application/pdf", big, null));
  await tick(80);
  if (filePosts().length !== 3) fail("OVERSIZE_PDF_ISSUED_REQUEST");
  if (byId.projectFormError.hidden !== false) fail("OVERSIZE_ERROR_NOT_VISIBLE");

  // 6) Server stays the validation authority: 422 message surfaced verbatim; no row added.
  nextPostFailure = { status: 422, body: { error: { code: "invalid_project_file", message: "SERVER_REJECT_MARKER_2342" } } };
  pickAndUpload(makeFile("second.pdf", "application/pdf", PDF_BYTES, null));
  await tick(80);
  posts = filePosts();
  if (posts.length !== 4) fail("SERVER_ERROR_POST_COUNT");
  if (byId.projectFormError.textContent !== "SERVER_REJECT_MARKER_2342") fail("SERVER_ERROR_MESSAGE_NOT_SURFACED");
  if (byId.projectFormError.hidden !== false) fail("SERVER_ERROR_NOT_VISIBLE");
  if (findRowText("second.pdf") !== null) fail("REJECTED_FILE_ROW_ADDED");
  if (busyDuringPost[3] !== "true") fail("ARIA_BUSY_NOT_SET_DURING_FAILED_POST");
  if (byId.projectFilesPanel.getAttribute("aria-busy") !== null) fail("ARIA_BUSY_NOT_CLEARED_AFTER_FAILURE");

  // 7) Retry: the same pick succeeds once the server accepts it.
  pickAndUpload(makeFile("second.pdf", "application/pdf", PDF_BYTES, null));
  await tick(80);
  if (filePosts().length !== 5) fail("RETRY_DID_NOT_ISSUE_SECOND_POST");
  if (findRowText("second.pdf") === null) fail("RETRY_ROW_NOT_RENDERED");
  if (byId.projectFormError.hidden !== true) fail("ERROR_NOT_CLEARED_ON_RETRY");

  // 8) base64 must never appear in rendered dialog text.
  const dialogText = collectText(byId.projectDialog) + " " + collectText(byId.projectFormError);
  if (dialogText.indexOf(PDF_BASE64) >= 0) fail("BASE64_RENDERED_IN_DOM");

  function findRowText(name) {
    const rows = byId.projectFilesList.children || [];
    for (const row of rows) { if (collectText(row).indexOf(name) >= 0) return name; }
    return null;
  }

  console.log(JSON.stringify({ ok: true, posts: filePosts().length, getFiles: requests.filter((r) => r.method === "GET" && /\/files$/.test(r.url)).length }));
})().catch((e) => { console.log(JSON.stringify({ ok: false, error: String((e && e.stack) || e) })); });
"""


def _run_harness() -> dict:
    node = shutil.which("node")
    assert node, "node runtime is required for the behavioral harness"
    harness_path = ROOT / "tests" / "_b62_2342_behavior_harness.js"
    harness_path.write_text(_HARNESS, encoding="utf-8")
    try:
        result = subprocess.run(
            [node, str(harness_path), str(APP_JS), str(CAPABILITIES_JS), str(DOCUMENT_BINARY_JS)],
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
    # 5 project-file POSTs (text, PDF, DOCX, rejected PDF, retried PDF); the GET file
    # refresh runs once at dialog open and once per SUCCESSFUL POST — never after the 422.
    assert payload["posts"] == 5
    assert payload["getFiles"] == 5


if __name__ == "__main__":
    test_html_has_accessible_project_file_status_surface()
    test_project_file_picker_accepts_text_plus_pdf_docx_only()
    test_binary_and_text_payload_shapes_are_exact_in_source()
    test_no_console_logging_and_no_leftover_removed_symbol()
    test_status_line_css_and_accessibility_floor_present()
    test_behavioral_harness_passes()
    test_behavioral_request_shapes_proved()
    print("B62_PROJECT_FILE_BINARY_UI_TESTS=PASS")
