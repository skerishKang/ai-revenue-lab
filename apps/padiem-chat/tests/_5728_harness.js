const fs = require("node:fs");
const vm = require("node:vm");

const utilMenuPath = process.argv[2];

class N {
  constructor(tag) {
    this.tagName = String(tag || "div").toUpperCase();
    this.children = [];
    this.attrs = {};
    this.dataset = {};
    this.style = {};
    this.value = "";
    this.textContent = "";
    this.hidden = false;
    this.type = "";
    this.name = "";
    this.placeholder = "";
    this.checked = false;
    this.rows = 0;
    this.required = false;
    this.multiple = false;
    this.id = "";
    this.files = [];
    this._listeners = {};
  }
  set className(v) {
    this._cls = String(v || "");
    this._classSet = new Set(this._cls.split(/\s+/).filter(Boolean));
  }
  get className() { return this._cls || ""; }
  get classList() {
    const self = this;
    return {
      add: (...c) => { self.className = (self._cls + " " + c.join(" ")).trim(); },
      remove: (...c) => { const drop = new Set(c); self.className = self._cls.split(/\s+/).filter((x) => x && !drop.has(x)).join(" "); },
      contains: (c) => (self._classSet || new Set()).has(c),
      toggle: (c, forced) => { const has = (self._classSet || new Set()).has(c); const want = forced === undefined ? !has : forced; if (want) self.className = (self._cls + " " + c.join(" ")).trim(); else self.classList.remove(c); },
    };
  }
  setAttribute(k, v) { this.attrs[k] = String(v); if (k === "class") this._cls = String(v); }
  getAttribute(k) { return Object.prototype.hasOwnProperty.call(this.attrs, k) ? this.attrs[k] : null; }
  appendChild(child) { this.children.push(child); child.parentNode = this; return child; }
  append(...children) { children.forEach((child) => this.appendChild(child)); }
  removeChild(child) { const i = this.children.indexOf(child); if (i >= 0) this.children.splice(i, 1); }
  insertBefore(child, ref) {
    const i = this.children.indexOf(ref);
    if (i < 0) return this.appendChild(child);
    this.children.splice(i, 0, child);
    child.parentNode = this;
    return child;
  }
  replaceChildren(...children) { this.children = []; this.append(...children); }
  addEventListener(type, fn) { (this._listeners[type] = this._listeners[type] || []).push(fn); }
  removeEventListener() {}
  async dispatch(type, event) {
    const evt = event || { preventDefault() {} };
    let node = this;
    while (node) {
      for (const fn of (node._listeners[type] || []).slice()) {
        await fn.call(node === this ? this : node, Object.assign({}, evt, { target: this }));
      }
      node = node.parentNode;
    }
  }
  focus() {}
  click() { return this.dispatch("click"); }
  scrollIntoView() {}
  querySelector(sel) { return this.findAll(sel)[0] || null; }
  querySelectorAll(sel) { return this.findAll(sel); }
  _descendants() {
    const out = [];
    for (const child of this.children) { out.push(child); out.push(...child._descendants()); }
    return out;
  }
  findAll(sel) {
    const parts = String(sel).split(/\s+/);
    let scope = [this, ...this.children];
    parts.forEach((part, index) => {
      const next = [];
      for (const node of scope) {
        if (index === 0 && simpleMatch(node, part)) next.push(node);
        for (const descendant of node._descendants()) {
          if (simpleMatch(descendant, part)) next.push(descendant);
        }
      }
      scope = Array.from(new Set(next));
    });
    return scope;
  }
}

function attrValue(node, key) {
  if (key.indexOf("data-") === 0) {
    const camel = key.slice(5).replace(/-([a-z])/g, (m, c) => c.toUpperCase());
    return node.dataset && node.dataset[camel] !== undefined ? node.dataset[camel]
      : (node.attrs && node.attrs[key] !== undefined ? node.attrs[key] : null);
  }
  if (key === "name") return node.name !== undefined && node.name !== "" ? node.name : null;
  if (key === "id") return node.id || null;
  return node.attrs && node.attrs[key] !== undefined ? node.attrs[key] : null;
}
function simpleMatch(node, sel) {
  let rest = String(sel);
  let attrMatch;
  while ((attrMatch = /\[([\w-]+)=([^\]]+)\]/.exec(rest))) {
    if (String(attrValue(node, attrMatch[1]) || "") !== attrMatch[2].replace(/^["']|["']$/g, "")) return false;
    rest = rest.replace(attrMatch[0], "");
  }
  const idMatch = /^#([\w-]+)/.exec(rest);
  if (idMatch) {
    if (node.id !== idMatch[1]) return false;
    rest = rest.slice(idMatch[0].length);
  }
  const tagMatch = /^([\w-]+)/.exec(rest);
  if (tagMatch) {
    if (tagMatch[1].toUpperCase() !== node.tagName) return false;
    rest = rest.slice(tagMatch[0].length);
  }
  const classes = rest.split(".").filter(Boolean);
  if (classes.length && !classes.every((c) => String(node._cls || "").split(/\s+/).includes(c))) {
    return false;
  }
  return true;
}

class FakeFormData {
  constructor(form) { this._form = form || null; }
  get(name) {
    if (!this._form) return null;
    const hit = this._form._descendants().find((n) => n.name === name);
    return hit ? hit.value : null;
  }
}

class FakeFileReader {
  readAsDataURL(source) {
    let text = String(source && source.name ? source.name : "");
    if (!text && source && typeof source.arrayBuffer === "function") {
      const buf = source.arrayBuffer();
      text = buf && buf.__syncBytes ? Buffer.from(buf.__syncBytes).toString("utf8").replace(/^img:/, "") : "stored.png";
    }
    this.result = "data:image/png;base64," + Buffer.from(text).toString("base64");
    if (typeof this.onload === "function") this.onload();
  }
}

// Shared fake backend: survives across sessions like the real project store.
const chatRequests = [];
const storedFiles = [];
const requestsLog = [];
// The real store never reuses an id after a DELETE; the fake must not either,
// or a delete+recreate (exactly what the roster rewrite does) collides two
// different files under one id.
let fakeFileSeq = 0;
function nextBinaryId() { return "file_" + String(1000 + ++fakeFileSeq).padStart(32, "0").slice(-32); }
function nextTextId() { return "f" + (++fakeFileSeq); }
function json(data) { return { ok: true, status: 200, json: async () => data }; }
const CURRENT = { alerts: [], links: [], exchangeOpens: [], exchangeSelect: null, nativePicks: 0, pcFileStatus: 0, pcFileBytes: null };

class FakeFile {
  constructor(parts, name, opts) {
    this._parts = parts || [];
    this.name = String(name || "");
    this.type = (opts && opts.type) || "";
    const sizes = this._parts.map((p) => Number(p && p.size)).filter(Number.isFinite);
    this.size = (opts && Number.isFinite(Number(opts.size))) ? Number(opts.size)
      : sizes.length === this._parts.length ? sizes.reduce((a, b) => a + b, 0) : 0;
  }
}

async function fetch(url, opts) {
  opts = opts || {};
  const method = (opts.method || "GET").toUpperCase();
  requestsLog.push({ method: method, url: String(url).split("?")[0] });
  const path = String(url).split("?")[0];
  const body = typeof opts.body === "string" ? JSON.parse(opts.body) : null;
  if (method === "POST" && path === "/api/chat") {
    chatRequests.push(body);
    return json({ answer: "첫 문단입니다.\n\n둘째 문단입니다.\n\n마지막 문단입니다." });
  }
  if (method === "POST" && path === "/api/projects/p1/files" && opts.headers && String(opts.headers["Content-Type"] || "").indexOf("octet-stream") >= 0) {
    const fname = decodeURIComponent(opts.headers["X-Padiem-Filename"] || "");
    const ftype = opts.headers["X-Padiem-Media-Type"] || "";
    const id = nextBinaryId();
    storedFiles.push({ id, name: fname, media_type: ftype, binary: true });
    return json({ file: { id, name: fname, media_type: ftype, content_chars: 0 } });
  }
  if (method === "GET" && path === "/api/pc/pairings") {
    if (CURRENT.links === null) return { ok: false, status: 503, json: async () => ({ error: { code: "pc_pairing_unavailable" } }) };
    return json({ links: CURRENT.links });
  }
  if (method === "GET" && path === "/api/pc/file") {
    // /api/pc/file answers the PC file's real bytes; the fake serves a real
    // JPEG signature, because the client now reads the media type from them.
    if (CURRENT.pcFileStatus) return { ok: false, status: CURRENT.pcFileStatus, json: async () => ({}) };
    const bytes = CURRENT.pcFileBytes
      || new Uint8Array([0xff, 0xd8, 0xff, 0xe0, 0x00, 0x10, 0x4a, 0x46, 0x49, 0x46, 0x00, 0x01]);
    return { ok: true, status: 200, blob: async () => ({ size: bytes.length, arrayBuffer: async () => bytes }) };
  }
  const originalMatch = /^\/api\/projects\/p1\/files\/(file_\d+)\/original$/.exec(path);
  if (method === "GET" && originalMatch) {
    const found = storedFiles.find((f) => f.id === originalMatch[1] && f.binary);
    if (!found) return { ok: false, status: 404, json: async () => ({}) };
    const bytes = new TextEncoder().encode("img:" + found.name);
    return {
      ok: true, status: 200,
      headers: { get: (k) => (String(k).toLowerCase() === "content-type" ? found.media_type : null) },
      blob: async () => ({ arrayBuffer: () => ({ __syncBytes: bytes }) }),
    };
  }
  const deleteMatch = /^\/api\/projects\/p1\/files\/([\w-]+)$/.exec(path);
  if (method === "DELETE" && deleteMatch) {
    const idx = storedFiles.findIndex((f) => f.id === deleteMatch[1]);
    if (idx >= 0) storedFiles.splice(idx, 1);
    return { ok: true, status: 204, json: async () => ({}) };
  }
  const detailMatch = /^\/api\/projects\/p1\/files\/([\w-]+)$/.exec(path);
  if (method === "GET" && detailMatch) {
    const rec = storedFiles.find((f) => f.id === detailMatch[1]);
    if (!rec) return { ok: false, status: 404, json: async () => ({}) };
    return json({ file: { id: rec.id, name: rec.name, media_type: rec.media_type, content_chars: rec.content_chars || 0, content: rec.content || "" } });
  }
  if (method === "GET" && path === "/api/projects") return json({ projects: [{ id: "p1", name: "유틸 작업" }] });
  if (method === "POST" && path === "/api/projects") return json({ project: { id: "p1", name: "유틸 작업" } });
  if (method === "POST" && path === "/api/projects/p1/files" && body) {
    // Mirror the server's document validation: a file whose media type
    // contradicts its extension is refused (the live 422 the roster hit
    // when it was saved text/plain under a .json name).
    const ext = String(body.name || "").split(".").pop().toLowerCase();
    if (ext === "json" && body.media_type !== "application/json") {
      return { ok: false, status: 422, json: async () => ({ error: { code: "invalid_document", message: "문서 확장자와 파일 형식이 일치하지 않습니다." } }) };
    }
    const file = { id: nextTextId(), name: body.name, media_type: body.media_type, content: String(body.text || ""), content_chars: (body.text || "").length };
    storedFiles.push(file);
    return json({ file });
  }
  if (method === "GET" && path === "/api/projects/p1/files") {
    return json({ files: storedFiles.map((f) => ({ id: f.id, name: f.name, media_type: f.media_type, content_chars: f.content_chars || 0 })) });
  }
  return { ok: false, status: 404, json: async () => ({}) };
}

// One util-menu.js execution against a fresh fake DOM. Two sessions share
// the backend above, so the second one is the re-entry of the same account.
function spawnSession(tag) {
  const root = new N("html");
  const byId = {};
  function mk(tag, id, cls) {
    const node = new N(tag);
    if (id) { node.id = id; byId[id] = node; }
    if (cls) node.className = cls;
    return node;
  }

  const shell = mk("div", null, "app-shell");
  shell.dataset.state = "chat";
  root.appendChild(shell);
  const main = mk("main", "mainPanel", "main-panel");
  shell.appendChild(main);

  const utilView = mk("section", "utilView", "util-view");
  utilView.hidden = true;
  main.appendChild(utilView);
  const navBtn = mk("button", "utilNavButton", "side-item");
  navBtn.setAttribute("aria-current", "false");
  shell.appendChild(navBtn);

  [["speech", "축사·인사말"], ["sns", "SNS 홍보"], ["meeting", "회의정리·책 제작"], ["pdfmd", "PDF → Markdown"]].forEach(([key, label], i) => {
    const tab = mk("button", null, "util-tab" + (i === 0 ? " active" : ""));
    tab.dataset.util = key;
    tab.textContent = label;
    utilView.appendChild(tab);
  });
  const speechForm = mk("form", "utilSpeechForm", "util-form");
  utilView.appendChild(speechForm);
  const speechResult = mk("div", "utilSpeechResult");
  speechResult.hidden = true;
  utilView.appendChild(speechResult);
  const speechOutput = mk("textarea", "utilSpeechOutput");
  speechResult.appendChild(speechOutput);
  const speechActions = mk("div", null, "util-actions");
  speechResult.appendChild(speechActions);
  mk("button", "utilSpeechCopy");
  mk("button", "utilSpeechDownload");
  const speechFormActions = mk("div", null, "util-form-actions");
  speechForm.appendChild(speechFormActions);
  speechFormActions.appendChild(mk("button", "utilSpeechSave", "util-save"));
  const speechPanel = mk("div", "utilSpeechPanel", "util-panel");
  const snsPanel = mk("div", "utilSnsPanel", "util-panel");
  snsPanel.hidden = true;
  const meetingPanel = mk("div", "utilMeetingPanel", "util-panel");
  meetingPanel.hidden = true;
  const pdfmdPanel = mk("div", "utilPdfmdPanel", "util-panel");
  pdfmdPanel.hidden = true;
  utilView.append(speechPanel, snsPanel, meetingPanel, pdfmdPanel);
  mk("div", "utilMeetingOutput");

  const alerts = [];
  CURRENT.alerts = alerts;
  const ctx = {
    document: {
      readyState: "complete",
      body: mk("body", null),
      documentElement: root,
      getElementById: (id) => byId[id] || root._descendants().find((n) => n.id === id) || null,
      querySelector: (sel) => root.findAll(sel)[0] || null,
      querySelectorAll: (sel) => root.findAll(sel),
      createElement: (tag) => new N(tag),
      addEventListener() {},
    },
    window: {
      PadiemPcFileExchange: {
        open: (settings) => {
          CURRENT.exchangeOpens.push(settings || {});
          CURRENT.exchangeSelect = (settings && settings.onSelect) || null;
          return { close() {} };
        },
        close() {},
      },
    },
    navigator: {},
    atob: (text) => Buffer.from(String(text), "base64").toString("binary"),
    fetch: fetch,
    alert: (message) => alerts.push(String(message)),
    console: console,
    setTimeout: () => 0,
    Blob: function Blob() {},
    File: FakeFile,
    URL: { createObjectURL: () => "blob:fixture", revokeObjectURL() {} },
    FormData: FakeFormData,
    FileReader: FakeFileReader,
  };
  vm.createContext(ctx);
  vm.runInContext(fs.readFileSync(utilMenuPath, "utf8"), ctx, { filename: "util-menu.js [" + tag + "]" });
  return { tag, root, utilView, navBtn, alerts };
}

function fail(label, extra) {
  console.log(JSON.stringify({ ok: false, fail: label, extra: extra || null, alerts: CURRENT.alerts, chatRequests }));
  process.exit(1);
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  const A = spawnSession("A");
  const root = A.root;
  await A.navBtn.dispatch("click");
  const snsTab = A.utilView.querySelectorAll(".util-tab").find((t) => t.dataset.util === "sns");
  await snsTab.dispatch("click");

  // 1) URL field replaced by a multi photo picker.
  if (root.findAll('[name=photo]').length) fail("PHOTO_URL_FIELD_STILL_PRESENT");
  const addBtn = root._descendants().find((n) => n.id === "utilSnsPhotoAdd");
  const input = root._descendants().find((n) => n.id === "utilSnsPhotoInput");
  if (!addBtn || !input) fail("PHOTO_PICKER_NOT_BUILT");
  if (input.accept !== "image/*" || input.multiple !== true) fail("PICKER_NOT_MULTI_IMAGE");

  // 2) add two photos -> thumbnails render with reorder/remove controls.
  input.files = [{ name: "a.png", type: "image/png" }, { name: "b.png", type: "image/png" }];
  await input.dispatch("change");
  await sleep(30);
  let items = root.findAll(".util-photo-item");
  if (items.length !== 2) fail("TWO_PHOTOS_NOT_LISTED", { count: items.length });
  const names = () => items.map((li) => li.querySelector(".util-photo-name").textContent);
  if (JSON.stringify(names()) !== JSON.stringify(["a.png", "b.png"])) fail("PHOTO_ORDER_INITIAL_WRONG");
  const countEl = root._descendants().find((n) => n.id === "utilSnsPhotoCount");
  if (!countEl || countEl.textContent !== "2장") fail("COUNT_NOT_UPDATED");

  // 3) reorder down then up.
  await items[0].querySelector('[data-move="1"]').dispatch("click");
  items = root.findAll(".util-photo-item");
  if (JSON.stringify(names()) !== JSON.stringify(["b.png", "a.png"])) fail("REORDER_DOWN_FAILED");
  await items[1].querySelector('[data-move="-1"]').dispatch("click");
  items = root.findAll(".util-photo-item");
  if (JSON.stringify(names()) !== JSON.stringify(["a.png", "b.png"])) fail("REORDER_UP_FAILED");

  // 4) remove one photo.
  await items[1].querySelector(".util-photo-remove").dispatch("click");
  items = root.findAll(".util-photo-item");
  if (items.length !== 1 || names()[0] !== "a.png") fail("REMOVE_FAILED");

  // 5) generation prompt carries the roster, never a URL line.
  const snsForm = root._descendants().find((n) => n.id === "utilSnsForm");
  snsForm.querySelector('[name=event]').value = "항구 축제";
  snsForm.querySelector('[name=content]').value = "하루 행사 내용";
  input.files = [{ name: "c.png", type: "image/png" }];
  await input.dispatch("change");
  await sleep(30);
  await snsForm.dispatch("submit");
  await sleep(0);
  if (!chatRequests.length) fail("GEN_DID_NOT_CALL_MODEL");
  const prompt = chatRequests[chatRequests.length - 1].messages[0].content;
  if (prompt.indexOf("사진 URL") >= 0) fail("PROMPT_STILL_CARRIES_URL");
  if (prompt.indexOf("첨부 사진: 2장") < 0) fail("PROMPT_MISSING_PHOTO_ROSTER");

  // 6) blog preview interleaves photos between paragraphs (auto positions).
  const preview = root._descendants().find((n) => n.id === "utilSnsPreview");
  if (!preview || preview.hidden) fail("PREVIEW_NOT_SHOWN");
  const seq = preview.children.map((c) => c.tagName + (c.className ? "." + c.className : ""));
  const paras = preview.children.filter((c) => c.classList.contains("util-preview-para"));
  const imgs = preview.children.filter((c) => c.tagName === "IMG");
  if (paras.length !== 3) fail("BLOG_PARAGRAPHS_NOT_RENDERED");
  if (imgs.length !== 2) fail("BLOG_PHOTOS_NOT_INTERLEAVED");
  const firstImgIndex = preview.children.indexOf(imgs[0]);
  if (firstImgIndex === 0 || firstImgIndex >= preview.children.length - 1) fail("PHOTO_NOT_BETWEEN_PARAGRAPHS");

  // 7) platform switch keeps text + photos, preview becomes separate media.
  const fbTab = snsForm.querySelectorAll(".util-sns-tab").find((t) => t.dataset.platform === "facebook");
  await fbTab.dispatch("click");
  if (snsForm.querySelector('[name=event]').value !== "항구 축제") fail("TEXT_LOST_ON_SWITCH");
  if (root.findAll(".util-photo-item").length !== 2) fail("PHOTOS_LOST_ON_SWITCH");
  const grid = preview.querySelector(".util-sns-media-grid");
  if (!grid || grid.querySelectorAll("img").length !== 2) fail("FB_MEDIA_GRID_MISSING");
  const betweenImgs = preview.children.filter((c) => c.tagName === "IMG").length;
  if (betweenImgs !== 0) fail("FB_MIXED_IMAGES_INTO_TEXT");

  // 8) no publishing claim.
  const note = preview.children[preview.children.length - 1].textContent;
  if (note.indexOf("자동 게시") < 0) fail("PREVIEW_NOTE_MISSING_NO_PUBLISH_DISCLAIMER");

  // 9) storage sync: additions became binary uploads, removal issued a
  // server DELETE that actually dropped the stored original.
  const binaryUploads = storedFiles.filter((f) => f.binary);
  if (binaryUploads.length !== 2) fail("PHOTOS_NOT_UPLOADED", { stored: storedFiles.length });
  const deleteCalls = requestsLog.filter((r) => r.method === "DELETE" && /files\/file_\d+$/.test(r.url));
  if (deleteCalls.length !== 1) fail("REMOVE_DID_NOT_DELETE_STORED", { deletes: deleteCalls.length });
  const storedNames = storedFiles.filter((f) => f.binary).map((f) => f.name);
  if (storedNames.indexOf("b.png") >= 0) fail("STORED_ORIGINAL_NOT_DROPPED");
  if (storedNames.length !== 2) fail("UPLOAD_COUNT_WRONG", { storedNames: storedNames });

  // 10) persistence: the composition changes rewrote the roster file.
  // Back on blog so the insertion-position control exists, set 맨 앞, then
  // let the serialized roster chain settle.
  const blogTabA = snsForm.querySelectorAll(".util-sns-tab").find((t) => t.dataset.platform === "blog");
  await blogTabA.dispatch("click");
  items = root.findAll(".util-photo-item");
  const posSelect = items[0].querySelector(".util-photo-pos-select");
  if (!posSelect) fail("BLOG_POSITION_SELECT_MISSING");
  posSelect.value = "0";
  await posSelect.dispatch("change");
  await sleep(50);
  const rosterRec = storedFiles.find((f) => f.name === "SNS 사진 구성.json");
  if (!rosterRec) fail("ROSTER_NOT_WRITTEN", { stored: storedFiles.map((f) => f.name) });
  if (rosterRec.media_type !== "application/json") fail("ROSTER_MEDIA_TYPE_WRONG", { media_type: rosterRec.media_type });
  let roster = null;
  try { roster = JSON.parse(rosterRec.content); } catch (_) { fail("ROSTER_NOT_JSON"); }
  if (!Array.isArray(roster.photos) || roster.photos.length !== 2) fail("ROSTER_COUNT_WRONG");
  if (roster.photos[0].name !== "a.png" || roster.photos[1].name !== "c.png") fail("ROSTER_ORDER_WRONG", { roster: roster.photos });
  if (roster.photos[0].position !== "0") fail("ROSTER_POSITION_NOT_KEPT", { roster: roster.photos });

  // 11) the user writes the draft and presses 저장: the draft text and its
  // platform ride the SAME roster record, and the roster is rewritten in
  // place (never a second roster file).
  const draftText = "저장한 초안입니다.\n\n둘째 문단입니다.";
  root._descendants().find((n) => n.id === "utilSnsOutput").value = draftText;
  const saveBtnA = root._descendants().find((n) => n.id === "utilSnsSave");
  if (!saveBtnA) fail("SAVE_BUTTON_MISSING");
  await saveBtnA.dispatch("click");
  await sleep(60);
  const rosterCount = storedFiles.filter((f) => f.name === "SNS 사진 구성.json").length;
  if (rosterCount !== 1) fail("ROSTER_DUPLICATED", { count: rosterCount });
  let savedRoster = null;
  try { savedRoster = JSON.parse(storedFiles.find((f) => f.name === "SNS 사진 구성.json").content); } catch (_) { fail("ROSTER_NOT_JSON_AFTER_SAVE"); }
  if (!savedRoster.draft || savedRoster.draft.text !== draftText) fail("ROSTER_DRAFT_NOT_SAVED", { draft: savedRoster.draft || null });
  if (savedRoster.draft.platform !== "blog") fail("ROSTER_DRAFT_PLATFORM_WRONG", { platform: savedRoster.draft.platform });
  if (!Array.isArray(savedRoster.photos) || savedRoster.photos.length !== 2) fail("ROSTER_PHOTOS_LOST_ON_SAVE", { photos: savedRoster.photos });
  const draftTxtFiles = storedFiles.filter((f) => f.name === "블로그 게시글.txt");
  if (draftTxtFiles.length !== 1 || draftTxtFiles[0].content !== draftText) fail("DRAFT_FILE_NOT_SAVED");

  // 12) session B: re-entry restores the composition at build time — no
  // interaction — in the roster's order with its positions, and the saved
  // draft text comes back with it.
  const B = spawnSession("B");
  await B.navBtn.dispatch("click");
  const snsTabB = B.utilView.querySelectorAll(".util-tab").find((t) => t.dataset.util === "sns");
  await snsTabB.dispatch("click");
  await sleep(50);
  const restored = B.root.findAll(".util-photo-item");
  if (restored.length !== 2) fail("RESTORE_COUNT_WRONG", { count: restored.length });
  const restoredNames = restored.map((li) => li.querySelector(".util-photo-name").textContent);
  if (JSON.stringify(restoredNames) !== JSON.stringify(["a.png", "c.png"])) fail("RESTORE_ORDER_WRONG", { names: restoredNames });
  const restoredSelect = restored[0].querySelector(".util-photo-pos-select");
  if (!restoredSelect || restoredSelect.value !== "0") fail("RESTORE_POSITION_WRONG");
  const restoredCount = B.root._descendants().find((n) => n.id === "utilSnsPhotoCount");
  if (!restoredCount || restoredCount.textContent !== "2장") fail("RESTORE_COUNT_LABEL_WRONG");
  const restoredOutput = B.root._descendants().find((n) => n.id === "utilSnsOutput");
  if (!restoredOutput || restoredOutput.value !== draftText) fail("RESTORE_DRAFT_WRONG", { text: restoredOutput ? restoredOutput.value : null });
  const restoredResult = B.root._descendants().find((n) => n.id === "utilSnsResult");
  if (!restoredResult || restoredResult.hidden) fail("RESTORE_RESULT_HIDDEN");
  const restoredTitle = B.root._descendants().find((n) => n.id === "utilSnsTitle");
  if (!restoredTitle || restoredTitle.textContent !== "블로그 게시글") fail("RESTORE_TITLE_WRONG", { title: restoredTitle ? restoredTitle.textContent : null });

  // 13) a draft saved under another platform re-opens on that platform.
  // Session B switches to facebook, saves, then session C must restore the
  // facebook draft through the platform tab, not the blog default.
  const fbTabB = B.root._descendants().find((n) => n.id === "utilSnsForm").querySelectorAll(".util-sns-tab").find((t) => t.dataset.platform === "facebook");
  if (!fbTabB) fail("FB_TAB_MISSING_IN_B");
  await fbTabB.dispatch("click");
  const fbDraftText = "페이스북용으로 다시 저장한 초안입니다.";
  restoredOutput.value = fbDraftText;
  await B.root._descendants().find((n) => n.id === "utilSnsSave").dispatch("click");
  await sleep(60);
  const C = spawnSession("C");
  await C.navBtn.dispatch("click");
  const snsTabC = C.utilView.querySelectorAll(".util-tab").find((t) => t.dataset.util === "sns");
  await snsTabC.dispatch("click");
  await sleep(50);
  const cOutput = C.root._descendants().find((n) => n.id === "utilSnsOutput");
  if (!cOutput || cOutput.value !== fbDraftText) fail("RESTORE_C_DRAFT_WRONG", { text: cOutput ? cOutput.value : null });
  const cTitle = C.root._descendants().find((n) => n.id === "utilSnsTitle");
  if (!cTitle || cTitle.textContent !== "페이스북 게시글") fail("RESTORE_C_PLATFORM_WRONG", { title: cTitle ? cTitle.textContent : null });

  // 14) #5728: with a linked PC, 사진 추가 opens the shared 가져오기 dialog
  // and the picked PC file joins the composition through the same pipeline.
  CURRENT.links = [{ state: "active" }];
  input.addEventListener("click", () => { CURRENT.nativePicks += 1; });
  await addBtn.dispatch("click");
  if (CURRENT.exchangeOpens.length !== 1) fail("SHARED_DIALOG_NOT_OPENED", { opens: CURRENT.exchangeOpens.length });
  if (CURRENT.exchangeOpens[0].mode !== "import" || typeof CURRENT.exchangeOpens[0].onSelect !== "function") fail("SHARED_DIALOG_MODE_OR_CALLBACK_WRONG");
  if (CURRENT.nativePicks !== 0) fail("NATIVE_PICKER_USED_WITH_LINKED_PC");
  await CURRENT.exchangeSelect({ fileId: "d1", name: "pc사진.jpg" });
  await sleep(30);
  items = root.findAll(".util-photo-item");
  if (items.length !== 3 || names()[2] !== "pc사진.jpg") fail("PC_PHOTO_NOT_ADDED", { names: names() });

  // 15) no linked PC (a phone included), and a pairing store that cannot
  // answer: 사진 추가 keeps the local picker instead of a dead-end dialog.
  CURRENT.links = [];
  await addBtn.dispatch("click");
  await sleep(10);
  if (CURRENT.exchangeOpens.length !== 1) fail("SHARED_DIALOG_OPENED_WITHOUT_PC");
  if (CURRENT.nativePicks !== 1) fail("NATIVE_PICKER_FALLBACK_MISSING");
  CURRENT.links = null;
  await addBtn.dispatch("click");
  await sleep(10);
  if (CURRENT.exchangeOpens.length !== 1) fail("SHARED_DIALOG_OPENED_ON_UNKNOWN_PAIRINGS");
  if (CURRENT.nativePicks !== 2) fail("NATIVE_PICKER_MISSING_ON_UNKNOWN_PAIRINGS");

  // 16) The 가져오기 dialog lists every file in a folder, so the extension
  // proves nothing. A PC file whose bytes are not PNG/JPG/WEBP is refused by
  // the bytes themselves: no upload, one sentence naming the formats, and no
  // [다시 시도] row — a retry against a permanent refusal would only loop.
  CURRENT.links = [{ state: "active" }];
  CURRENT.pcFileBytes = new TextEncoder().encode("그냥 텍스트 파일입니다");
  const photosBefore = root.findAll(".util-photo-item").length;
  const binariesBefore = storedFiles.filter((f) => f.binary).length;
  await addBtn.dispatch("click");
  await sleep(10);
  if (CURRENT.exchangeOpens.length !== 2) fail("SHARED_DIALOG_NOT_REOPENED", { opens: CURRENT.exchangeOpens.length });
  await CURRENT.exchangeSelect({ fileId: "d2", name: "메모.txt" });
  await sleep(30);
  if (root.findAll(".util-photo-item").length !== photosBefore) fail("NON_IMAGE_PC_FILE_ADDED", { names: names() });
  if (storedFiles.filter((f) => f.binary).length !== binariesBefore) fail("NON_IMAGE_PC_FILE_UPLOADED");
  const refusedStatus = root._descendants().find((n) => n.id === "utilSnsPhotoStatus");
  if (!refusedStatus || refusedStatus.hidden || refusedStatus.textContent.indexOf("PNG·JPG·WEBP") < 0) {
    fail("NON_IMAGE_PC_FILE_NOT_EXPLAINED", { text: refusedStatus ? refusedStatus.textContent : null });
  }
  if (refusedStatus.textContent.indexOf("메모.txt") < 0) fail("NON_IMAGE_PC_FILE_NOT_NAMED", { text: refusedStatus.textContent });
  const refusedRetry = root._descendants().find((n) => n.id === "utilSnsPhotoRetry");
  if (!refusedRetry || !refusedRetry.hidden) fail("RETRY_OFFERED_FOR_PERMANENT_REFUSAL");

  // 17) The PC read itself failing says which side stopped it — an HTTP status
  // in the menu's own Korean copy, and the offline sentence for a dead network
  // — with nothing added and nothing to retry.
  CURRENT.pcFileBytes = null;
  CURRENT.pcFileStatus = 503;
  await addBtn.dispatch("click");
  await sleep(10);
  await CURRENT.exchangeSelect({ fileId: "d3", name: "큰사진.jpg" });
  await sleep(30);
  if (root.findAll(".util-photo-item").length !== photosBefore) fail("FAILED_PC_READ_ADDED_PHOTO");
  if (refusedStatus.textContent.indexOf("사진을 가져오지 못했어요") < 0
      || refusedStatus.textContent.indexOf("과부하") < 0) {
    fail("FAILED_PC_READ_COPY_WRONG", { text: refusedStatus.textContent });
  }
  if (!refusedRetry.hidden) fail("RETRY_OFFERED_FOR_FAILED_PC_READ");
  CURRENT.pcFileStatus = 0;
  CURRENT.links = [];

  console.log(JSON.stringify({
    ok: true,
    photos: root.findAll(".util-photo-item").length,
    restored: restoredNames,
    restoredPosition: restoredSelect ? restoredSelect.value : null,
    restoredDraft: restoredOutput ? restoredOutput.value : null,
    restoredPlatform: cTitle ? cTitle.textContent : null,
    rosterOrder: roster.photos.map((p) => p.name + ":" + p.position),
    promptHead: prompt.slice(0, 60),
    blogSeq: seq.slice(0, 6),
    storedBinary: storedFiles.filter((f) => f.binary).length,
    pcPhoto: names()[2] || null,
    pcRefusalCopy: refusedStatus ? refusedStatus.textContent : null,
    alertsA: A.alerts, alertsB: B.alerts,
  }));
})().catch((e) => { console.log(JSON.stringify({ ok: false, fail: "HARNESS_EXCEPTION", extra: String(e && e.stack || e) })); process.exit(1); });
