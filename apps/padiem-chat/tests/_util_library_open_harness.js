/*
 * #7782 — runs the REAL library.js and library-file-viewer.js in a DOM shim and
 * watches the two open paths: the row click that reads the stored content, and
 * the project action that lists the project's files. The settings-dialog seam
 * (PadiemChatProjectOpener) must stay untouched by both.
 *
 * argv: library.js library-file-viewer.js
 * env:  SCENARIO (JSON)
 */
const fs = require("fs"), vm = require("vm");
const librarySource = fs.readFileSync(process.argv[2], "utf8");
const viewerSource = fs.readFileSync(process.argv[3], "utf8");
const scenario = JSON.parse(process.env.SCENARIO || "{}");
const requests = [];

function El(tag) {
  const node = {
    tagName: (tag || "div").toUpperCase(), id: "", className: "", type: "",
    textContent: "", value: "", hidden: false, disabled: false, focused: false,
    open: false, href: "", download: "",
    children: [], attrs: {}, listeners: {}, dataset: {},
    classList: {
      add(...names) { const set = new Set(String(node.className).split(/\s+/).filter(Boolean)); names.forEach((n) => set.add(n)); node.className = [...set].join(" "); },
      remove(...names) { const set = new Set(String(node.className).split(/\s+/).filter(Boolean)); names.forEach((n) => set.delete(n)); node.className = [...set].join(" "); },
      contains(name) { return String(node.className).split(/\s+/).indexOf(name) >= 0; },
    },
    addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); },
    setAttribute(k, v) { this.attrs[k] = String(v); if (k === "id") this.id = String(v); },
    getAttribute(k) { return Object.prototype.hasOwnProperty.call(this.attrs, k) ? this.attrs[k] : null; },
    removeAttribute() {},
    appendChild(n) { this.children.push(n); n.parentElement = this; return n; },
    remove() { if (this.parentElement) { const i = this.parentElement.children.indexOf(this); if (i >= 0) this.parentElement.children.splice(i, 1); } },
    replaceChildren(...ns) { this.children.length = 0; ns.forEach((n) => this.appendChild(n)); },
    focus() { this.focused = true; },
    click() { (this.listeners.click || []).forEach((fn) => fn({ target: this, stopPropagation() {} })); },
    showModal() { this.open = true; },
    close() { this.open = false; (this.listeners.close || []).forEach((fn) => fn({})); },
    querySelector() { return null; },
    querySelectorAll() { return []; },
  };
  return node;
}
function walk(el, fn) { if (!el) return; fn(el); (el.children || []).forEach((c) => walk(c, fn)); }
function matches(el, sel) {
  if (!sel) return false;
  if (sel.charAt(0) === ".") return String(el.className).split(/\s+/).indexOf(sel.slice(1)) >= 0;
  if (sel.charAt(0) === "#") return el.id === sel.slice(1);
  return el.tagName === String(sel).toUpperCase();
}
function find(root, sel) { let out = null; walk(root, (e) => { if (!out && e !== root && matches(e, sel)) out = e; }); return out; }
function findAll(root, sel) { const out = []; walk(root, (e) => { if (e !== root && matches(e, sel)) out.push(e); }); return out; }
function text(root) { let out = ""; walk(root, (e) => { if (typeof e.textContent === "string") out += e.textContent + "\n"; }); return out; }

const shell = El("div");
shell.className = "app-shell";
shell.dataset = { state: "chat" };
const navButton = El("button"); navButton.id = "filesNavButton";
const view = El("div"); view.id = "libraryView";
const kicker = El("p"); kicker.id = "libraryKicker";
const heading = El("h2"); heading.id = "libraryTitle";
const subtitle = El("p"); subtitle.id = "librarySubtitle";
const closeButton = El("button"); closeButton.id = "libraryCloseButton";
const filesTab = El("button"); filesTab.id = "libraryFilesTab";
const imagesTab = El("button"); imagesTab.id = "libraryImagesTab";
const note = El("p"); note.id = "libraryNote";
const filesPanel = El("div"); filesPanel.id = "libraryFilesPanel";
const imagesPanel = El("div"); imagesPanel.id = "libraryImagesPanel";
const fileList = El("div"); fileList.id = "libraryFileList";
const imageList = El("div"); imageList.id = "libraryImageList";
const messageList = El("div"); messageList.id = "messageList";

const documentObj = {
  readyState: "complete",
  documentElement: { lang: scenario.lang || "ko" },
  activeElement: null,
  body: El("body"),
  createElement: (tag) => El(tag),
  querySelector: (sel) => (sel === ".app-shell" ? shell : null),
  getElementById: (id) => ({
    appShell: shell, filesNavButton: navButton, libraryView: view,
    libraryKicker: kicker, libraryTitle: heading, librarySubtitle: subtitle,
    libraryCloseButton: closeButton, libraryFilesTab: filesTab, libraryImagesTab: imagesTab,
    libraryNote: note, libraryFilesPanel: filesPanel, libraryImagesPanel: imagesPanel,
    libraryFileList: fileList, libraryImageList: imageList, messageList: messageList,
  }[id] || null),
  addEventListener: () => {},
};

const blobs = [];
let blobSeq = 0;
class Blob {
  constructor(parts, opts) { this.parts = parts; this.type = (opts && opts.type) || ""; this.id = ++blobSeq; }
}
const urlState = { revoked: [] };
const URLStub = { createObjectURL(blob) { const u = "blob:mock-" + blob.id; blobs.push({ url: u, blob }); return u; }, revokeObjectURL(u) { urlState.revoked.push(u); } };

const authState = { loaded: true, authenticated: true, storage: true, ownerKey: "owner-7782", displayName: "Owner" };

function jsonResponse(status, body) {
  return { ok: status >= 200 && status < 300, status: status, json: () => Promise.resolve(body || {}) };
}

const stored = {
  files: [
    { id: "file_a", project_id: "proj_pinned", name: "축사 초안 2026-11-14.txt", media_type: "text/plain", content_chars: 695, project_name: "유틸" },
  ],
  detail: { file: { id: "file_a", project_id: "proj_pinned", name: "축사 초안 2026-11-14.txt", media_type: "text/plain", content_chars: 695, content: scenario.detailContent === undefined ? "존경하는 회원 여러분, 안녕하십니까." : scenario.detailContent } },
  list: { files: [{ id: "file_a", project_id: "proj_pinned", name: "축사 초안 2026-11-14.txt", media_type: "text/plain", content_chars: 695 }] },
};

function fetchStub(url, init) {
  const method = (init && init.method) || "GET";
  requests.push({ url: url, method: method, credentials: init && init.credentials });
  // Real fetch always returns a Promise — the viewer chains .then/.catch on it.
  const respond = (status, body) => Promise.resolve(jsonResponse(status, body));
  if (url.split("?")[0] === "/api/project-files") {
    if (scenario.listUnavailable) return respond(503, { error: { code: "unavailable" } });
    return respond(200, { files: stored.files, next_cursor: null, has_more: false, limit: 50 });
  }
  if (/^\/api\/projects\/[^/]+\/files$/.test(url) && method === "GET") {
    if (scenario.projectListStatus) return respond(scenario.projectListStatus, { error: { code: "unavailable" } });
    return respond(200, stored.list);
  }
  if (/^\/api\/projects\/[^/]+\/files\/[^/]+$/.test(url) && method === "GET") {
    if (scenario.detailStatus) return respond(scenario.detailStatus, { error: { code: "project_file_not_found" } });
    return respond(200, stored.detail);
  }
  return respond(404, { error: { code: "not_found" } });
}

const openerCalls = [];
const listeners = {};
const windowObj = {
  fetch: fetchStub,
  addEventListener: (type, fn) => { (listeners[type] = listeners[type] || []).push(fn); },
  PadiemAuthSession: { get: () => authState },
  PadiemAnswerCopy: { copyText: (value) => { windowObj.__copied = value; return Promise.resolve(scenario.copyResult !== false); } },
  // The settings seam stays wired exactly as before; both library paths must
  // leave it alone. Any call here fails the run.
  PadiemChatProjectOpener: {
    open: () => { openerCalls.push("open"); return true; },
    openFile: () => { openerCalls.push("openFile"); return true; },
  },
  Blob: Blob,
  URL: URLStub,
};

const sandbox = {
  document: documentObj, window: windowObj, console: console,
  setTimeout: (fn) => 0, clearTimeout: () => {},
  URL: URLStub, Blob: Blob, fetch: fetchStub,
};
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
vm.runInContext(viewerSource, sandbox, { filename: "library-file-viewer.js" });
vm.runInContext(librarySource, sandbox, { filename: "library.js" });

const result = { ok: true, checks: {}, requests: requests, openerCalls: openerCalls, text: "" };
function check(name, cond) { result.checks[name] = Boolean(cond); if (!cond) result.ok = false; }
function tick() { return new Promise((resolve) => setImmediate(resolve)); }

(async () => {
  try {
  check("viewer_seam_published", typeof windowObj.PadiemChatLibraryFiles === "object");
  check("library_surface_published", typeof windowObj.PadiemChatLibrary === "object");

  // Open the Library surface the way the sidebar button does.
  navButton.listeners.click[0]({});
  await tick(); await tick(); await tick();
  check("library_open", windowObj.PadiemChatLibrary.isOpen());
  check("library_listed_one_row", windowObj.PadiemChatLibrary.getRowCount() === 1);
  const row = find(fileList, ".library-item");
  check("row_present", Boolean(row));
  check("row_is_openable", Boolean(row) && row.classList.contains("library-item-openable"));
  check("row_keeps_project_action", Boolean(find(row, ".library-item-action")));

  // 1) Row click → the stored content is read through the viewer seam.
  row.click();
  await tick(); await tick(); await tick();
  const detailReads = requests.filter((r) => /^\/api\/projects\/[^/]+\/files\/[^/]+$/.test(r.url) && r.method === "GET");
  check("row_click_reads_file_detail", detailReads.length === 1);
  check("detail_read_is_same_origin", detailReads.length === 1 && detailReads[0].credentials === "same-origin");
  const viewerDialog = find(documentObj.body, ".library-file-dialog");
  check("viewer_dialog_open", Boolean(viewerDialog) && viewerDialog.open === true);
  check("settings_seam_untouched_after_row_click", openerCalls.length === 0);

  // 2) Copy hands the exact stored text to the shared copy helper, and the
  // download Blob carries it. (Content-bearing checks need a content response.)
  if (!scenario.detailStatus) {
  check("viewer_shows_stored_text", Boolean(viewerDialog) && text(viewerDialog).indexOf("존경하는 회원 여러분, 안녕하십니까.") >= 0);
  check("viewer_has_copy_button", Boolean(viewerDialog) && Boolean(find(viewerDialog, ".library-dialog-button")));
  const copyButton = viewerDialog && findAll(viewerDialog, ".library-dialog-button").find((b) => b.textContent === "복사");
  check("copy_button_label", Boolean(copyButton));
  if (copyButton) { copyButton.click(); await tick(); }
  check("copy_hands_stored_text", windowObj.__copied === (scenario.detailContent === undefined ? "존경하는 회원 여러분, 안녕하십니까." : scenario.detailContent));
  if (scenario.copyResult === false) {
    check("copy_failure_is_reported", Boolean(viewerDialog) && text(viewerDialog).indexOf("복사하지 못했습니다") >= 0);
  }

  // 3) Download builds a Blob carrying the exact stored text.
  const downloadButton = viewerDialog && findAll(viewerDialog, ".library-dialog-button").find((b) => b.textContent === "내려받기");
  check("download_button_present", Boolean(downloadButton));
  if (downloadButton) { downloadButton.click(); await tick(); }
  check("download_built_one_blob", blobs.length === 1);
  check("download_blob_is_text_type", blobs.length === 1 && /text\/plain/.test(blobs[0].blob.type));
  check("download_blob_is_text_kind", blobs.length === 1 && blobs[0].blob.type.indexOf("text/") === 0);
  const storedText = scenario.detailContent === undefined ? "존경하는 회원 여러분, 안녕하십니까." : scenario.detailContent;
  check("download_blob_holds_the_content", blobs.length === 1 && blobs[0].blob.parts.join("") === storedText);
  }

  // Close the viewer before the next path.
  viewerDialog.close();
  await tick();

  // 4) The project action lists the project's files — never the settings dialog.
  const actionButton = row && find(row, ".library-item-action");
  actionButton.click();
  await tick(); await tick(); await tick();
  const listReads = requests.filter((r) => /^\/api\/projects\/[^/]+\/files$/.test(r.url) && r.method === "GET");
  check("project_action_reads_file_list", listReads.length === 1);
  const listDialog = find(documentObj.body, ".library-files-dialog");
  check("list_dialog_open", Boolean(listDialog) && listDialog.open === true);
  if (!scenario.projectListStatus) {
  check("list_shows_the_file", Boolean(listDialog) && text(listDialog).indexOf("축사 초안 2026-11-14.txt") >= 0);
  }
  check("settings_seam_never_called", openerCalls.length === 0);

  // 5) A foreign / gone file gets an honest refusal and no fabricated content.
  if (scenario.detailStatus) {
    viewerDialog.open = true;
    const viewer2 = windowObj.PadiemChatLibraryFiles;
    viewer2.openFile({ id: "file_foreign", project_id: "proj_pinned", name: "남의 파일.txt", media_type: "text/plain", content_chars: 10, project_name: "유틸" });
    await tick(); await tick(); await tick();
    check("foreign_file_reads_the_route", requests.some((r) => r.url.indexOf("file_foreign") >= 0));
    check("foreign_file_shows_no_content", text(viewerDialog).indexOf("존경하는 회원 여러분") < 0);
    check("foreign_file_is_honest", text(viewerDialog).indexOf("찾을 수 없습니다") >= 0);
  }

  if (scenario.projectListStatus) {
    const viewer2 = windowObj.PadiemChatLibraryFiles;
    viewer2.openProjectFiles("proj_pinned", "유틸");
    await tick(); await tick(); await tick();
    check("list_failure_is_honest", text(listDialog).indexOf("불러오지 못했습니다") >= 0);
    check("list_failure_shows_no_rows", !find(listDialog, ".library-item"));
  }
  } catch (error) {
    result.error = String((error && error.stack) || error);
  }
  result.text = text(fileList);
  console.log(JSON.stringify(result));
})();
