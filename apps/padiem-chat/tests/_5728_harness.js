
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
  // classList stays in sync with className assignments (el() sets className).
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
      toggle: (c, forced) => { const has = (self._classSet || new Set()).has(c); const want = forced === undefined ? !has : forced; if (want) self.className = (self._cls + " " + c).trim(); else self.classList.remove(c); },
    };
  }
  setAttribute(k, v) { this.attrs[k] = String(v); if (k === "class") this._cls = String(v); }
  getAttribute(k) { return Object.prototype.hasOwnProperty.call(this.attrs, k) ? this.attrs[k] : null; }
  appendChild(child) { this.children.push(child); child.parentNode = this; return child; }
  append(...children) { children.forEach((child) => this.appendChild(child)); }
  removeChild(child) { const i = this.children.indexOf(child); if (i >= 0) this.children.splice(i, 1); }
  replaceChildren(...children) { this.children = []; this.append(...children); }
  addEventListener(type, fn) { (this._listeners[type] = this._listeners[type] || []).push(fn); }
  removeEventListener() {}
  async dispatch(type, event) {
    // Standard bubbling: the product relies on delegated listeners (the
    // photo list handles clicks fired by its inner buttons).
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

const chatRequests = [];
const storedFiles = [];
function json(data) { return { ok: true, status: 200, json: async () => data }; }
const requestsLog = [];
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
  // #5728 storage: binary image upload / stored-original read / delete.
  if (method === "POST" && path === "/api/projects/p1/files" && opts.headers && String(opts.headers["Content-Type"] || "").indexOf("octet-stream") >= 0) {
    const fname = decodeURIComponent(opts.headers["X-Padiem-Filename"] || "");
    const ftype = opts.headers["X-Padiem-Media-Type"] || "";
    const id = "file_" + String(1000 + storedFiles.length).padStart(32, "0").slice(-32);
    storedFiles.push({ id, name: fname, media_type: ftype, binary: true });
    return json({ file: { id, name: fname, media_type: ftype, content_chars: 0 } });
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
  const deleteMatch = /^\/api\/projects\/p1\/files\/(file_\d+)$/.exec(path);
  if (method === "DELETE" && deleteMatch) {
    const idx = storedFiles.findIndex((f) => f.id === deleteMatch[1]);
    if (idx >= 0) storedFiles.splice(idx, 1);
    return { ok: true, status: 204, json: async () => ({}) };
  }
  if (method === "GET" && path === "/api/projects") return json({ projects: [{ id: "p1", name: "유틸 작업" }] });
  if (method === "POST" && path === "/api/projects") return json({ project: { id: "p1", name: "유틸 작업" } });
  if (method === "POST" && path === "/api/projects/p1/files" && body) {
    const file = { id: "f" + (storedFiles.length + 1), name: body.name, media_type: body.media_type, content_chars: body.text.length };
    storedFiles.push(file);
    return json({ file });
  }
  if (method === "GET" && path === "/api/projects/p1/files") {
    return json({ files: storedFiles.map((f) => ({ id: f.id, name: f.name, media_type: f.media_type, content_chars: f.content_chars || 0 })) });
  }
  return { ok: false, status: 404, json: async () => ({}) };
}

const alerts = [];
const ctx = {
  document: {
    readyState: "complete",
    body: mk("body", null),
    documentElement: root,
    // Harness-built nodes resolve from the registry first; script-built
    // nodes (ids assigned at runtime) resolve from the live tree.
    getElementById: (id) => byId[id] || root._descendants().find((n) => n.id === id) || null,
    querySelector: (sel) => root.findAll(sel)[0] || null,
    querySelectorAll: (sel) => root.findAll(sel),
    createElement: (tag) => new N(tag),
    addEventListener() {},
  },
  window: {},
  navigator: {},
  fetch: fetch,
  alert: (message) => alerts.push(String(message)),
  console: console,
  setTimeout: () => 0,
  Blob: function Blob() {},
  URL: { createObjectURL: () => "blob:fixture", revokeObjectURL() {} },
  FormData: FakeFormData,
  FileReader: FakeFileReader,
};

vm.createContext(ctx);
vm.runInContext(fs.readFileSync(utilMenuPath, "utf8"), ctx, { filename: "util-menu.js" });

function fail(label, extra) {
  console.log(JSON.stringify({ ok: false, fail: label, extra: extra || null, alerts, chatRequests }));
  process.exit(1);
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  await navBtn.dispatch("click");
  const snsTab = utilView.querySelectorAll(".util-tab").find((t) => t.dataset.util === "sns");
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
  await sleep(0);
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
  // re-add a second photo so interleave has two entries.
  input.files = [{ name: "c.png", type: "image/png" }];
  await input.dispatch("change");
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

  // 9) #5728 storage sync: additions became binary uploads, removal issued a
  // server DELETE that actually dropped the stored original.
  const binaryUploads = storedFiles.filter((f) => f.binary);
  if (binaryUploads.length !== 2) fail("PHOTOS_NOT_UPLOADED", { stored: storedFiles.length });
  const deleteCalls = requestsLog.filter((r) => r.method === "DELETE" && /files\/file_\d+$/.test(r.url));
  if (deleteCalls.length !== 1) fail("REMOVE_DID_NOT_DELETE_STORED", { deletes: deleteCalls.length });
  const storedNames = storedFiles.filter((f) => f.binary).map((f) => f.name);
  if (storedNames.indexOf("b.png") >= 0) fail("STORED_ORIGINAL_NOT_DROPPED");
  if (storedNames.length !== 2) fail("UPLOAD_COUNT_WRONG", { storedNames: storedNames });

  console.log(JSON.stringify({ ok: true, photos: root.findAll(".util-photo-item").length, promptHead: prompt.slice(0, 60), blogSeq: seq.slice(0, 6), storedBinary: storedFiles.filter((f) => f.binary).length, alerts }));
})().catch((e) => { console.log(JSON.stringify({ ok: false, fail: "HARNESS_EXCEPTION", extra: String(e && e.stack || e) })); process.exit(1); });
