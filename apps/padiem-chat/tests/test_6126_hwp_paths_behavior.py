"""#6126 — the three-sample × Chat-attachment/project-file behavior proof.

Static assertions alone do not prove the decision, so this file runs a Node
harness that executes the REAL attachment-capabilities.js + document-binary.js
+ app.js in one vm context against a minimal DOM shim with a recording fetch
(the #2342 harness shape). It proves actual pick -> outcome for the #6126
sample matrix on the two browser-owned paths:

- Chat attachment: OLE2 .hwp  -> ordinary save-as-HWPX guidance note (no error
  state), picker cleared, zero network calls;
- Chat attachment: .hwp whose bytes are a real HWPX (ZIP) -> attached as HWPX
  with the HWPX note;
- Project file: OLE2 .hwp -> the save-as-HWPX guidance as the panel status
  note (never the red error row), zero uploads;
- Project file: mislabeled real HWPX (ZIP) -> the same shared tus upload the
  .hwpx extension uses (HWPX media type, original file name);
- control: a real .hwpx keeps the exact same binary upload contract.

The PC-import path (signature sniff + one guidance code end to end) is owned
by ``test_6126_legacy_hwp_guidance.py``, which needs no DOM.
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
TUS_UPLOAD_JS = ROOT / "static/tus-upload.js"
PROJECT_UPLOAD_JS = ROOT / "static/project-file-upload.js"

OLE_BYTES = [0xD0, 0xCF, 0x11, 0xE0, 0xA1, 0xB1, 0x1A, 0xE1, 0x00, 0x11]
ZIP_BYTES = [0x50, 0x4B, 0x03, 0x04, 0x14, 0x00, 0x06, 0x00, 0x28, 0x00]

_HARNESS = r"""
const fs = require("fs");
const vm = require("vm");
const APP = fs.readFileSync(process.argv[2], "utf8");
const CAPS = fs.readFileSync(process.argv[3], "utf8");
const DOCBIN = fs.readFileSync(process.argv[4], "utf8");
const TUSLIB = fs.readFileSync(process.argv[5], "utf8");
const TUSMODULE = fs.readFileSync(process.argv[6], "utf8");

const OLE_BYTES = Uint8Array.from([0xD0, 0xCF, 0x11, 0xE0, 0xA1, 0xB1, 0x1A, 0xE1, 0x00, 0x11]);
const ZIP_BYTES = Uint8Array.from([0x50, 0x4B, 0x03, 0x04, 0x14, 0x00, 0x06, 0x00, 0x28, 0x00]);

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

// #6126: the sniff reads the file's own first bytes, so the shim must expose
// the same slice(0, 8).arrayBuffer() surface a real browser File has, and the
// shared tus client reads chunk slices by length/_bytes (the #2342 shape).
function makeFile(name, type, bytes, text) {
  const u8 = Uint8Array.from(bytes);
  return {
    name, type, size: u8.length, _bytes: u8, _text: text,
    slice(start, end) {
      const from = start || 0;
      const to = end === undefined ? u8.length : Math.min(end, u8.length);
      const part = u8.slice(from, to);
      return { length: part.length, _bytes: part, async arrayBuffer() { return part.slice().buffer; } };
    },
    async arrayBuffer() { return u8.slice().buffer; },
  };
}

const requests = [];
let fileSeq = 0;
let tusResult = { status: 201, name: "이름 없음", media_type: "extracted/hwpx" };
const tusCreates = [];
const tusPatches = [];
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
  // The shared tus client runs for real; the server side of the protocol is
  // answered here exactly like the #2342 harness does.
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
    tusCreates.push({ endpoint: u, length, filename: meta.filename, media_type: meta.filetype });
    uploads.set(location, { offset: 0, total: length });
    return { ok: true, status: 201, json: async () => ({ upload_id: "stub-" + uploadSeq }),
      headers: headerMap({ location }) };
  }
  if (method === "PATCH" && tusItem) {
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
    return { ok: true, status: 200, json: async () => ({}),
      headers: headerMap({ "upload-offset": String(state ? state.offset : 0) }) };
  }
  if (method === "GET" && tusItem) {
    if (tusResult.status !== 201) return jsonResponse(tusResult.status, tusResult.body);
    fileSeq += 1;
    return jsonResponse(201, { file: {
      id: "file_tus_" + fileSeq, project_id: "p1", name: tusResult.name, media_type: tusResult.media_type,
      content_chars: 120, created_at: "2026-11-01T00:00:00Z", updated_at: "2026-11-01T00:00:00Z",
    } });
  }
  if (isTextFilePost) {
    const body = requests[requests.length - 1].body;
    return jsonResponse(201, { file: {
      id: "file_text_" + (++fileSeq), project_id: "p1", name: body.name, media_type: body.media_type,
      content_chars: 120, created_at: "2026-09-11T00:00:00Z", updated_at: "2026-09-11T00:00:00Z",
    } });
  }
  if (method === "GET" && /\/api\/projects\/[^/]+\/files$/.test(u)) return jsonResponse(200, { files: [] });
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
// The real boot learns this from /health (binary_document_attachment_ready,
// locale.js syncBinaryAttachmentSupport); the harness loads no locale bundle,
// so it takes the same confirmed-deployment state directly.
sandbox.PadiemAttachmentCapabilities.setBinarySupport(true);
vm.runInContext(DOCBIN, sandbox, { filename: "document-binary.js" });
if (!sandbox.PadiemBinaryDocuments || typeof sandbox.PadiemBinaryDocuments.headerFamily !== "function") {
  console.log(JSON.stringify({ ok: false, error: "SNIFF_HELPER_NOT_LOADED" }));
  process.exit(0);
}
vm.runInContext(TUSLIB, sandbox, { filename: "tus-upload.js" });
vm.runInContext(TUSMODULE, sandbox, { filename: "project-file-upload.js" });
if (!sandbox.PadiemProjectFileUpload) {
  console.log(JSON.stringify({ ok: false, error: "TUS_MODULE_NOT_LOADED" }));
  process.exit(0);
}
vm.runInContext(APP, sandbox, { filename: "app.js" });
// index.html ships #attachmentTray and #attachmentThumb with the hidden
// attribute; the shim's elements default to visible, so model the real
// initial state before any pick.
byId.attachmentTray.hidden = true;
byId.attachmentThumb.hidden = true;

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
function pickChatAttachment(file) {
  byId.attachmentFileInput.files = [file];
  (byId.attachmentFileInput.listeners.change || []).forEach((fn) => fn({ target: byId.attachmentFileInput }));
}
function pickProjectFile(file) {
  byId.projectFormError.hidden = true;
  byId.projectFormError.textContent = "";
  byId.projectFileInput.files = [file];
  (byId.projectFileInput.listeners.change || []).forEach((fn) => fn({ target: byId.projectFileInput }));
}
function filePosts() { return requests.filter((r) => r.method === "POST" && /\/api\/projects\/[^/]+\/files$/.test(r.url)); }
function octetStreamPosts() {
  return filePosts().filter((r) => r.headers && r.headers["Content-Type"] === "application/octet-stream");
}
function laneCalls() { return requests.filter((r) => r.url.includes("/api/files/")); }

(async () => {
  const fail = (m) => { console.log(JSON.stringify({ ok: false, error: m })); process.exit(0); };
  const tick = (ms) => new Promise((r) => setTimeout(r, ms));
  await tick(60);

  // 1) Chat attachment, OLE2 .hwp: ordinary guidance note, no error state,
  //    picker cleared, zero network.
  pickChatAttachment(makeFile("작년 축사.hwp", "", OLE_BYTES, null));
  await tick(80);
  const chatOle = {
    note: byId.runtimeNote.textContent,
    noteState: byId.runtimeNote.dataset.state,
    trayHidden: byId.attachmentTray.hidden,
    cleared: byId.attachmentFileInput.value === "",
    laneCalls: laneCalls().length,
  };
  if (chatOle.note !== "hwp-legacy-guidance\nhwp-legacy-steps") fail("CHAT_OLE_NOTE:" + JSON.stringify(chatOle.note));
  if (chatOle.noteState !== "normal") fail("CHAT_OLE_NOTE_STATE:" + chatOle.noteState);
  if (chatOle.trayHidden !== true) fail("CHAT_OLE_TRAY_VISIBLE");
  if (chatOle.cleared !== true) fail("CHAT_OLE_INPUT_NOT_CLEARED");
  if (chatOle.laneCalls !== 0) fail("CHAT_OLE_MADE_NETWORK_CALLS");

  // 2) Chat attachment, mislabeled real HWPX (ZIP): attached as HWPX.
  pickChatAttachment(makeFile("보고서.hwp", "", ZIP_BYTES, null));
  await tick(80);
  const chatZip = {
    trayHidden: byId.attachmentTray.hidden,
    name: byId.attachmentName.textContent,
    note: byId.runtimeNote.textContent,
  };
  if (chatZip.trayHidden !== false) fail("CHAT_ZIP_NOT_ATTACHED");
  if (chatZip.name !== "보고서.hwp") fail("CHAT_ZIP_NAME:" + chatZip.name);
  if (chatZip.note !== "attachment-hwpx-note") fail("CHAT_ZIP_NOTE:" + chatZip.note);

  // 3) Project file, OLE2 .hwp: guidance as the status note, no red error row,
  //    zero uploads.
  const manage = findButtonByClass(byId.projectsList, "project-manage");
  if (!manage) fail("PROJECT_MANAGE_BUTTON_MISSING");
  manage.click();
  await tick(60);
  if (byId.projectFilesPanel.hidden !== false) fail("FILES_PANEL_NOT_VISIBLE");
  pickProjectFile(makeFile("예전 기획서.hwp", "", OLE_BYTES, null));
  await tick(80);
  const projectOle = {
    status: byId.projectFileStatus.textContent,
    statusHidden: byId.projectFileStatus.hidden,
    errorHidden: byId.projectFormError.hidden,
    posts: filePosts().length,
  };
  if (projectOle.status !== "hwp-legacy-guidance\nhwp-legacy-steps") fail("PROJECT_OLE_STATUS:" + JSON.stringify(projectOle.status));
  if (projectOle.statusHidden !== false) fail("PROJECT_OLE_STATUS_HIDDEN");
  if (projectOle.errorHidden !== true) fail("PROJECT_OLE_ERROR_ROW_SHOWN");
  if (projectOle.posts !== 0) fail("PROJECT_OLE_ISSUED_UPLOAD");

  // 4) Project file, mislabeled real HWPX (ZIP): the shared tus upload the
  //    .hwpx extension uses — HWPX media, original file name, own bytes.
  tusResult = { status: 201, name: "보고서.hwp", media_type: "extracted/hwpx" };
  pickProjectFile(makeFile("보고서.hwp", "", ZIP_BYTES, null));
  await tick(120);
  if (tusCreates.length !== 1) fail("PROJECT_ZIP_TUS_COUNT:" + tusCreates.length);
  const zipCreate = tusCreates[0];
  if (zipCreate.endpoint !== "/api/projects/p1/files/tus") fail("PROJECT_ZIP_TUS_ENDPOINT");
  if (zipCreate.filename !== "보고서.hwp") fail("PROJECT_ZIP_FILENAME");
  if (zipCreate.media_type !== "application/hwp+zip") fail("PROJECT_ZIP_MEDIA");
  if (zipCreate.length !== ZIP_BYTES.length) fail("PROJECT_ZIP_LENGTH_MISMATCH");
  if (tusPatches.length !== 1 || tusPatches[0].bytes !== ZIP_BYTES.length) fail("PROJECT_ZIP_CHUNK_SHAPE");
  if (octetStreamPosts().length !== 0) fail("PROJECT_ZIP_DIRECT_POST_RETURNED");

  // 5) Control: a real .hwpx keeps the exact same tus upload contract.
  pickProjectFile(makeFile("sample.hwpx", "application/hwp+zip", ZIP_BYTES, null));
  await tick(120);
  if (tusCreates.length !== 2) fail("HWPX_CONTROL_TUS_COUNT:" + tusCreates.length);
  if (tusCreates[1].media_type !== "application/hwp+zip") fail("HWPX_CONTROL_MEDIA");
  if (tusCreates[1].filename !== "sample.hwpx") fail("HWPX_CONTROL_FILENAME");

  console.log(JSON.stringify({ ok: true, chatOle, chatZip, projectOle,
    projectZip: { mediaType: zipCreate.media_type, filename: zipCreate.filename,
      bytes: zipCreate.length },
    uploads: tusCreates.length }));
})().catch((e) => { console.log(JSON.stringify({ ok: false, error: String((e && e.stack) || e) })); });
"""

# All consumers assert read-only facts from the same completed real app.js
# behavior journey. Reuse it once per Python module rather than respawning
# Node for each test; separate pytest processes still run independent checks.
@lru_cache(maxsize=1)
def _run_harness() -> dict:
    node = shutil.which("node")
    assert node, "node runtime is required for the behavioral harness"
    harness_path = ROOT / "tests" / "_6126_hwp_paths_behavior_harness.js"
    harness_path.write_text(_HARNESS, encoding="utf-8")
    try:
        result = subprocess.run(
            [node, str(harness_path), str(APP_JS), str(CAPABILITIES_JS), str(DOCUMENT_BINARY_JS),
             str(TUS_UPLOAD_JS), str(PROJECT_UPLOAD_JS)],
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


def test_chat_attachment_paths_match_the_decision() -> None:
    payload = _run_harness()
    assert payload.get("ok") is True, payload
    assert payload["chatOle"]["note"] == "hwp-legacy-guidance\nhwp-legacy-steps"
    assert payload["chatOle"]["noteState"] == "normal"
    assert payload["chatOle"]["trayHidden"] is True
    assert payload["chatOle"]["laneCalls"] == 0
    assert payload["chatZip"]["trayHidden"] is False
    assert payload["chatZip"]["name"] == "보고서.hwp"
    assert payload["chatZip"]["note"] == "attachment-hwpx-note"


def test_project_file_paths_match_the_decision() -> None:
    payload = _run_harness()
    assert payload.get("ok") is True, payload
    assert payload["projectOle"]["status"] == "hwp-legacy-guidance\nhwp-legacy-steps"
    assert payload["projectOle"]["statusHidden"] is False
    assert payload["projectOle"]["errorHidden"] is True
    assert payload["projectOle"]["posts"] == 0
    assert payload["projectZip"]["mediaType"] == "application/hwp+zip"
    assert payload["projectZip"]["filename"] == "보고서.hwp"
    assert payload["uploads"] == 2
