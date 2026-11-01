// One fake-DOM host for the REAL static/council-app.js.
//
// Same contract as apps/padiem-chat/tests/_5785_util_harness.js: the browser
// module under test is the shipped file, the backend is a recording fake of
// the EXISTING endpoints, and nothing here invents a product behaviour or a
// second API. The assertions live in the Python test modules.
//
// Usage: node _council_harness.js <council-app.js path> <scenario> [builder] [json]
//   scenario = generate | restore | errors | calendar_words | prompt
const fs = require("node:fs");
const vm = require("node:vm");

const councilPath = process.argv[2];
const scenario = String(process.argv[3] || "").toLowerCase();

// ── minimal DOM node ────────────────────────────────────────────────────────
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
    this.accept = "";
    this.id = "";
    this.files = [];
    this._listeners = {};
    this._cls = "";
    this.parentNode = null;
  }
  set className(v) { this._cls = String(v || ""); }
  get className() { return this._cls || ""; }
  get classList() {
    const self = this;
    const has = (c) => (self._cls || "").split(/\s+/).filter(Boolean).includes(c);
    return {
      add: (...c) => { self._cls = [...new Set([...(self._cls || "").split(/\s+/).filter(Boolean), ...c])].join(" "); },
      remove: (...c) => { const drop = new Set(c); self._cls = (self._cls || "").split(/\s+/).filter((x) => x && !drop.has(x)).join(" "); },
      contains: (c) => has(c),
    };
  }
  setAttribute(k, v) { this.attrs[k] = String(v); if (k === "class") this._cls = String(v); }
  getAttribute(k) { return Object.prototype.hasOwnProperty.call(this.attrs, k) ? this.attrs[k] : null; }
  appendChild(child) { this.children.push(child); child.parentNode = this; return child; }
  get previousElementSibling() {
    if (!this.parentNode) return null;
    const index = this.parentNode.children.indexOf(this);
    return index > 0 ? this.parentNode.children[index - 1] : null;
  }
  get nextElementSibling() {
    if (!this.parentNode) return null;
    const index = this.parentNode.children.indexOf(this);
    return index >= 0 && index < this.parentNode.children.length - 1
      ? this.parentNode.children[index + 1] : null;
  }
  insertBefore(node, reference) {
    if (node.parentNode) node.parentNode.removeChild(node);
    const index = this.children.indexOf(reference);
    if (index < 0) this.children.push(node);
    else this.children.splice(index, 0, node);
    node.parentNode = this;
    return node;
  }
  removeChild(child) {
    const index = this.children.indexOf(child);
    if (index >= 0) this.children.splice(index, 1);
    child.parentNode = null;
    return child;
  }
  append(...children) { children.forEach((child) => this.appendChild(child)); }
  replaceChildren(...children) { this.children = []; this.append(...children); }
  addEventListener(type, fn) { (this._listeners[type] = this._listeners[type] || []).push(fn); }
  removeEventListener() {}
  async dispatch(type, event) {
    const evt = Object.assign({ preventDefault() {}, target: this }, event || {});
    // Event delegation (e.g. the photo list) relies on bubbling in a real
    // browser; mirror that here so delegated handlers fire when a child is
    // dispatched. The original target stays the dispatched node.
    let cur = this;
    while (cur) {
      for (const fn of (cur._listeners[type] || []).slice()) await fn.call(cur, evt);
      cur = cur.parentNode;
    }
  }
  focus() {}
  click() { return this.dispatch("click"); }
  querySelector(sel) { return this.findAll(sel)[0] || null; }
  querySelectorAll(sel) { return this.findAll(sel); }
  _descendants() {
    const out = [];
    for (const child of this.children) { out.push(child); out.push(...child._descendants()); }
    return out;
  }
  findAll(sel) {
    const parts = String(sel).trim().split(/\s+/).filter(Boolean);
    let scope = [this, ...this.children];
    for (const part of parts) {
      const next = [];
      for (const node of scope) {
        if (simpleMatch(node, part)) next.push(node);
        for (const descendant of node._descendants()) {
          if (simpleMatch(descendant, part)) next.push(descendant);
        }
      }
      scope = Array.from(new Set(next));
    }
    return scope;
  }
}

function simpleMatch(node, part) {
  if (!node || !node.tagName || !part) return false;
  let token = String(part);
  // `:checked` is the only pseudo-class the module queries.
  let wantsChecked = false;
  if (token.endsWith(":checked")) {
    wantsChecked = true;
    token = token.slice(0, -":checked".length);
  }
  if (wantsChecked && !node.checked) return false;
  if (token.startsWith("#")) return node.id === token.slice(1);
  if (token.startsWith(".")) return node.classList.contains(token.slice(1));
  const attr = /^\[([\w-]+)(?:="?([^"\]]*)"?)?\]$/.exec(token);
  if (attr) {
    const key = attr[1];
    const want = attr[2];
    const have = key === "name" ? node.name : node.getAttribute(key);
    if (want === undefined) return have !== null && have !== undefined && have !== "";
    return have === want;
  }
  return node.tagName === token.toUpperCase();
}

// ── recording fake backend (the EXISTING endpoints) ────────────────────────
const requests = [];
const chatPayloads = [];
const loginAttempts = [];
const storedFiles = [];
let fileIdSeq = 0;
let chatResponseOverride = null;
let saveFailureOverride = null;
// The pinned storage project (#A1). The default listing already carries the
// one project this app stores under; a scenario swaps it to prove the lookup.
let projectRows = [{ id: "p1", name: "의원3종" }];
let projectCreates = 0;
let createdProjectId = "p2";
let projectsReadFails = false;
const projectsListing = () => projectRows.slice();
// #5942: the same-origin session contract the entry page uses. A scenario flips
// these to walk signed-out → in-page login → expiry without any second authority.
let authState = { authenticated: true, user: { name: "테스트 사용자" } };
let loginOutcome = null;
// #6127: the status read itself can fail. A scenario swaps this in to prove the
// module tells a server fault apart from a signed-out visitor.
let authStatusOutcome = null;
let statusReads = 0;
let fetchRejects = null;
const saveBodies = [];
// a queue answers successive status reads differently, which is how the re-ask is proven
let authStatusQueue = null;
// #5895: the PC bridge. Defaults say "no computer is linked"; a scenario swaps
// these to walk the import/save/photo path through the shared dialog contract.
let pcLinks = [];
let pcReferenceText = "예전 축사 원고입니다. 문체를 참고하세요.";
let pcReferenceCode = "";
let pcUploads = [];
const pcSaves = [];
const pcReferenceReads = [];
const pcDispatches = [];
const PC_PHOTO_BYTES = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0, 0, 0, 13]);

function json(body, status) {
  return { ok: (status || 200) < 400, status: status || 200, json: async () => body };
}

const ANSWER_PARTS = ["생성된 초안 본문입니다.\n\n", "두 번째 문단입니다."];
let streamDelayMs = 0;

// A real SSE body: event/data frames read through a stream reader, so the
// delivered behaviour is the one the server actually sends.
function sseResponse(parts) {
  const frames = (parts || ANSWER_PARTS).map((part) =>
    "event: delta\ndata: " + JSON.stringify({ delta: part }) + "\n\n");
  frames.push("event: done\ndata: " + JSON.stringify({ done: true }) + "\n\n");
  const chunks = frames.map((frame) => Buffer.from(frame, "utf8"));
  let index = 0;
  return {
    ok: true,
    status: 200,
    headers: { get: (name) => (String(name).toLowerCase() === "content-type" ? "text/event-stream; charset=utf-8" : null) },
    body: {
      getReader() {
        return {
          read() {
            const next = () => (index >= chunks.length
              ? { done: true }
              : { done: false, value: chunks[index++] });
            if (streamDelayMs <= 0) return Promise.resolve(next());
            return new Promise((resolve) => setTimeout(() => resolve(next()), streamDelayMs));
          },
          async cancel() {},
          releaseLock() {},
        };
      },
    },
  };
}

const stored = (name, textValue, mediaType, bytes, country, docKind) => {
  const file = { id: "f" + (++fileIdSeq), name, media_type: mediaType || "text/plain",
                 content_chars: String(textValue || "").length };
  // #6046 contract: kr is sent as NO country field, so an absent field reads back as kr.
  if (country) file.country = country;
  if (docKind) file.doc_kind = docKind;
  storedFiles.push(Object.assign({ text: textValue, bytes: bytes || null }, file));
  return file;
};

async function fetch(url, init) {
  const method = (init && init.method) || "GET";
  const headers = (init && init.headers) || {};
  const options = {
    method,
    url: String(url),
    headers,
    credentials: (init && init.credentials) || null,
  };
  let body = null;
  if (init && typeof init.body === "string") {
    try { body = JSON.parse(init.body); } catch (_) { body = init.body; }
  }
  requests.push(options);
  if (method === "POST" && String(url) === "/api/chat/stream") {
    chatPayloads.push(body);
    if (chatResponseOverride) return chatResponseOverride;
    return sseResponse();
  }
  if (String(url) === "/api/pc/pairings") {
    return json({ links: pcLinks });
  }
  if (method === "POST" && String(url) === "/api/pc/reference") {
    pcReferenceReads.push(body);
    if (pcReferenceCode) return json({ error: { code: pcReferenceCode } }, 422);
    return json({ ok: true, name: "예전 축사.hwp", text: pcReferenceText });
  }
  if (String(url).indexOf("/api/pc/file") === 0) {
    const dispatch = new URLSearchParams(String(url).split("?")[1] || "").get("dispatch_id");
    pcDispatches.push(dispatch);
    return {
      ok: true,
      status: 200,
      blob: async () => ({ arrayBuffer: async () => PC_PHOTO_BYTES.buffer.slice(0) }),
    };
  }
  if (String(url) === "/api/auth/status") {
    statusReads += 1;
    if (fetchRejects) throw fetchRejects;
    if (authStatusQueue && authStatusQueue.length) return authStatusQueue.shift();
    return authStatusOutcome || json(authState);
  }
  if (method === "POST" && String(url) === "/api/auth/password/login") {
    loginAttempts.push(body);
    if (loginOutcome) return loginOutcome;
    return json({ ok: true, user: { name: "테스트 사용자" } });
  }
  if (String(url) === "/api/projects") {
    if (method === "GET") {
      if (projectsReadFails) return json({ error: { code: "unavailable" } }, 503);
      return json({ projects: projectsListing() });
    }
    projectCreates += 1;
    return json({ project: { id: createdProjectId, name: (body && body.name) || "" } });
  }
  const filesMatch = /^\/api\/projects\/([^/]+)\/files\/?([^/]*)$/.exec(String(url));
  const originalMatch = /^\/api\/projects\/([^/]+)\/files\/([^/]+)\/original$/.exec(String(url));
  if (originalMatch) {
    const found = storedFiles.find((f) => f.id === originalMatch[2]);
    if (!found) return json({ error: { code: "not_found" } }, 404);
    return {
      ok: true,
      status: 200,
      blob: async () => ({ __bytes: found.bytes || "original-bytes:" + found.name }),
    };
  }
  if (filesMatch) {
    if (method === "GET" && !filesMatch[2]) {
      return json({ files: storedFiles.map(({ text, bytes, ...meta }) => meta) });
    }
    if (method === "POST") {
      const ct = String(headers["Content-Type"] || "");
      if (ct === "application/octet-stream") {
        // Binary original upload: the file name/media type ride the headers
        // and the request body IS the picked file — keep its bytes so the
        // restore flow reads back exactly what was uploaded.
        const rawName = decodeURIComponent(headers["X-Padiem-Filename"] || "photo");
        const mediaType = headers["X-Padiem-Media-Type"] || "application/octet-stream";
        const uploaded = init && init.body;
        const bytes = uploaded && uploaded.__bytes !== undefined ? uploaded.__bytes : "binary-bytes";
        const file = stored(rawName, "", mediaType, bytes);
        return json({ file });
      }
      if (saveFailureOverride) {
        const forced = saveFailureOverride;
        saveFailureOverride = null;
        return forced;
      }
      saveBodies.push({ keys: Object.keys(body || {}).sort(), country: body && body.country,
                        doc_kind: body && body.doc_kind });
      // #5731: a name already used by the same kind answers 409 with the existing file.
      const sameName = storedFiles.find((f) => f.name === (body && body.name)
        && (f.doc_kind || "") === ((body && body.doc_kind) || ""));
      if (sameName) {
        return json({ error: { code: "name_taken",
                               existing: { id: sameName.id, name: sameName.name } } }, 409);
      }
      const file = stored((body && body.name) || "무제.txt", (body && body.text) || "",
                             (body && body.media_type) || "text/plain", null, body && body.country,
                             body && body.doc_kind);
      return json({ file });
    }
    if (method === "PUT" && filesMatch[2]) {
      // #5731 overwrite: the displaced body stays as a version on the server.
      const found = storedFiles.find((f) => f.id === filesMatch[2]);
      if (!found) return json({ error: { code: "not_found" } }, 404);
      const previous = { id: "v" + (++fileIdSeq), name: found.name, text: found.text };
      found.text = (body && body.text) || "";
      found.content_chars = String(found.text).length;
      if (body && body.doc_kind) found.doc_kind = body.doc_kind;
      saveBodies.push({ keys: Object.keys(body || {}).sort(), country: body && body.country,
                        doc_kind: body && body.doc_kind });
      return json({ file: { id: found.id, name: found.name, media_type: found.media_type,
                            content_chars: found.content_chars, doc_kind: found.doc_kind }, previous });
    }
    if (method === "DELETE" && filesMatch[2]) {
      const idx = storedFiles.findIndex((f) => f.id === filesMatch[2]);
      if (idx >= 0) storedFiles.splice(idx, 1);
      return json({ ok: true });
    }
    if (method === "GET" && filesMatch[2]) {
      const found = storedFiles.find((f) => f.id === filesMatch[2]);
      if (!found) return json({ error: { code: "not_found" } }, 404);
      return json({ file: { id: found.id, name: found.name, content: found.text } });
    }
  }
  return json({}, 404);
}

const pageErrors = [];
const alerts = [];
const downloads = [];
const downloadDetails = [];

// ── one council-app.js execution against a fresh fake DOM ──────────────────
class FakeFormData {
  constructor(form) { this._form = form || null; }
  get(key, default_) {
    const field = this._form && this._form.querySelector(`[name=${key}]`);
    if (!field) return default_ === undefined ? null : default_;
    return field.value;
  }
}

function FakeBlob(parts, options) {
  // 2026-11-01: the export tests read the bytes a download would carry.
  this.parts = Array.isArray(parts) ? parts : (parts === undefined ? [] : [parts]);
  this.type = (options && options.type) || "";
}
class FakeFile extends FakeBlob {
  constructor(parts, name, options) {
    super();
    this.name = String(name || "file");
    this.type = (options && options.type) || "";
    const first = Array.isArray(parts) ? parts[0] : parts;
    this.__bytes = first instanceof Uint8Array ? first : new Uint8Array(0);
  }
}

class FakeFileReader {
  readAsDataURL(source) {
    // Pick flow: source is the picked File-like ({name, __bytes}). Restore
    // flow: source is the blob() of GET …/original ({__bytes}). Both encode
    // the SAME original bytes, so a restored thumbnail is provably the
    // stored original, not a resampled copy.
    const raw = source && source.__bytes !== undefined ? source.__bytes : (source && source.name) || "";
    this.result = "data:image/png;base64," + Buffer.from(String(raw), "utf8").toString("base64");
    if (typeof this.onload === "function") this.onload();
  }
}

function spawnSession(windowState = {}) {
  const root = new N("html");
  const byId = {};
  const mk = (tag, id, cls) => {
    const node = new N(tag);
    if (id) { node.id = id; byId[id] = node; }
    if (cls) node.className = cls;
    return node;
  };

  const speechBody = mk("div", "councilSpeechBody");
  const snsBody = mk("div", "councilSnsBody");
  const meetingBody = mk("div", "councilMeetingBody");
  speechBody.hidden = true;
  snsBody.hidden = true;
  meetingBody.hidden = true;
  root.append(speechBody, snsBody, meetingBody);
  const badge = mk("span", "councilAuthBadge");
  const note = mk("p", "councilSigninNote");
  // #6065: the content-country control is part of the surface the shipped module
  // binds, so the fake document carries it - the stored lists are country-scoped
  // and a scenario has to be able to change it.
  const countrySelect = mk("select", "councilCountry");
  ["kr", "us", "uk", "fr"].forEach((code) => {
    const option = new N("option");
    option.value = code;
    countrySelect.appendChild(option);
  });
  countrySelect.value = "kr";
  root.append(badge, note, countrySelect);

  // The #6065 cinematic surface: the two design axes, the popover that carries them, the
  // workspace bar the tool selection reveals, and the hero's entry control. The shipped
  // module binds these by id, so a scenario can drive the axes for real.
  const themePanel = mk("span", "councilThemePanel", "council-theme-panel");
  themePanel.hidden = true;
  const themeTrigger = mk("button", "councilThemeTrigger", "council-theme-trigger");
  const themeValue = mk("span", "councilThemeValue", "council-theme-value");
  const countryGroup = mk("span", "councilCountryGroup", "council-theme-group");
  ["kr", "us", "uk", "fr"].forEach((code) => {
    const pill = mk("button");
    pill.setAttribute("data-country", code);
    pill.setAttribute("role", "radio");
    pill.setAttribute("aria-checked", code === "kr" ? "true" : "false");
    countryGroup.append(pill);
  });
  const styleGroup = mk("span", "councilStyleGroup", "council-theme-group");
  ["classic", "modern", "dark", "light", "minimal"].forEach((code) => {
    const pill = mk("button");
    pill.setAttribute("data-style", code);
    pill.setAttribute("role", "radio");
    pill.setAttribute("aria-checked", code === "light" ? "true" : "false");
    styleGroup.append(pill);
  });
  themePanel.append(countryGroup, styleGroup);
  themeTrigger.append(themeValue);
  const workspaceBar = mk("div", "councilWorkspaceBar", "council-workspace-bar");
  workspaceBar.hidden = true;
  const backButton = mk("button", "councilBack", "council-back");
  const workspaceTitle = mk("span", "councilWorkspaceTitle", "council-workspace-title");
  workspaceBar.append(backButton, workspaceTitle);
  const heroCta = mk("button", "councilHeroCta", "council-cta");
  root.append(themeTrigger, themePanel, workspaceBar, heroCta);

  // The #5942 entry surface: three selectable cards and the in-page login panel,
  // mirroring static/index.html so the shipped module is driven against the markup
  // it actually runs on.
  const panel = mk("section", "councilAuthPanel", "council-auth");
  panel.hidden = true;
  const authStatus = mk("p", "councilAuthStatus", "council-auth-status");
  authStatus.hidden = true;
  const googleRow = mk("p", "councilGoogleRow", "council-auth-alt");
  googleRow.hidden = true;
  const loginForm = mk("form", "councilLoginForm", "council-form");
  const identifier = mk("input", null, null);
  identifier.name = "identifier";
  const password = mk("input", null, null);
  password.name = "password";
  const submit = mk("button", null, "council-login");
  submit.type = "submit";
  loginForm.append(identifier, password, submit);
  panel.append(loginForm, authStatus, googleRow);
  const action = mk("button", "councilAuthAction", "council-badge-action");
  action.hidden = true;
  root.append(panel, action);

  ["speech", "sns", "meeting"].forEach((tool) => {
    const section = mk("section", "council-" + tool, "council-card");
    section.dataset.tool = tool;
    const button = mk("button", null, "council-card-select");
    button.type = "button";
    button.dataset.tool = tool;
    button.setAttribute("aria-expanded", "false");
    section.append(button);
    root.append(section);
  });

  // nav_search 시나리오용: 시안(04) 상단 메뉴와 검색 상자. index.html의 마크업을
  // 그대로 받아 본다(항목은 data-nav, 검색은 #councilSearchForm/#councilSearch).
  const nav = mk("nav", "councilNav", "council-nav");
  ["home", "tools", "speech", "sns", "meeting"].forEach((name) => {
    const item = mk("button", null, "council-nav-item");
    item.setAttribute("data-nav", name);
    item.textContent = name;
    nav.append(item);
  });
  root.append(nav);
  const searchWrap = mk("div", null, "council-tool-search-wrap");
  const searchForm = mk("form", "councilSearchForm", "council-tool-search");
  const searchInput = mk("input", "councilSearch", "council-tool-search-input");
  const searchGo = mk("button", "councilSearchGo", "council-tool-search-go");
  searchGo.type = "submit";
  const searchStatus = mk("p", "councilSearchStatus", "council-tool-search-status");
  searchStatus.hidden = true;
  searchForm.append(searchInput, searchGo);
  searchWrap.append(searchForm, searchStatus);
  root.append(searchWrap);

  // The shipped module binds document-level listeners (the Escape rule, the
  // popover's outside click). The fake document must actually deliver them, or
  // a scenario would prove nothing about those handlers.
  const documentListeners = {};
  const ctx = {
    document: {
      readyState: "complete",
      body: mk("body", null),
      documentElement: root,
      getElementById: (id) => byId[id] || root._descendants().find((n) => n.id === id) || null,
      querySelector: (sel) => root.querySelector(sel),
      querySelectorAll: (sel) => root.querySelectorAll(sel),
      createElement: (tag) => {
        const node = new N(tag);
        // The download control builds an <a download>; record the file name the
        // user would actually receive, then let the click resolve.
        if (String(tag).toLowerCase() === "a") {
          node.click = async function () {
            const name = String(this.download || "");
            downloads.push(name);
            // 2026-11-01: only byte-carrying downloads (HWPX/DOCX) land here —
            // the export tests read the payload with the name.
            if (this.__exportBytes) {
              downloadDetails.push({ download: name, bytes: this.__exportBytes });
            }
          };
        }
        return node;
      },
      addEventListener(type, fn) { (documentListeners[type] = documentListeners[type] || []).push(fn); },
      async dispatch(type, event) {
        const evt = Object.assign({ preventDefault() {} }, event || {});
        for (const fn of (documentListeners[type] || []).slice()) await fn(evt);
      },
    },
    atob: (value) => Buffer.from(String(value), "base64").toString("binary"),
    window: windowState,
    navigator: { clipboard: { writeText: async () => {} } },
    fetch,
    alert: (message) => alerts.push(String(message)),
    console,
    setTimeout: () => 0,
    Blob: FakeBlob,
    File: FakeFile,
    TextDecoder,
    TextEncoder,
    FileReader: FakeFileReader,
    URL: { createObjectURL: () => "blob:fixture", revokeObjectURL() {} },
    FormData: FakeFormData,
  };
  vm.createContext(ctx);
  // The page loads document-export.js alongside the app (defer); the sandbox
  // does the same so the export buttons exercise the real byte builders.
  vm.runInContext(
    fs.readFileSync(councilPath.replace(/council-app\.js$/, "document-export.js"), "utf8"),
    ctx, { filename: "document-export.js" });
  vm.runInContext(fs.readFileSync(councilPath, "utf8"), ctx, { filename: "council-app.js" });
  return { root, byId, ctx };
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const text = (value) => String((value && value.textContent) || "");

function find(session, id) {
  const found = session.root._descendants().find((n) => n.id === id);
  if (!found) throw new Error("element missing: #" + id);
  return found;
}

function endpointSet() {
  return Array.from(new Set(requests.map((r) => r.method + " " + r.url))).sort();
}

// ── scenarios ──────────────────────────────────────────────────────────────
const SCENARIOS = {
  async cinematic() {
    // #6065: 4 countries x 5 styles must be switchable, and choosing a tool must move the
    // page into the 작업실 and back. Driven through the shipped module on the fake document
    // that carries the new surface, so this is executed behaviour, not a string match.
    const sessionOf = (state) => {
      authState = state;
      const bag = {};
      const s = spawnSession({ localStorage: { getItem: (k) => (k in bag ? bag[k] : null),
                                               setItem: (k, v) => { bag[k] = String(v); } } });
      s.bag = bag;
      return s;
    };
    const pill = (s, group, attr, value) => find(s, group).querySelectorAll("[" + attr + "]")
      .find((n) => n.getAttribute(attr) === value);
    const checked = (s, group, attr) => find(s, group).querySelectorAll("[" + attr + "]")
      .filter((n) => n.getAttribute("aria-checked") === "true").map((n) => n.getAttribute(attr));
    const openBodies = (s) => ["councilSpeechBody", "councilSnsBody", "councilMeetingBody"]
      .filter((id) => !find(s, id).hidden);

    const s = sessionOf({ authenticated: true, user: { name: "테스트 사용자" } });
    const api = s.ctx.window.PadiemCouncilApps;
    await api.init();
    await sleep(30);
    const out = { signedIn: { initialCountry: s.root.dataset.country, initialStyle: s.root.dataset.style } };

    await pill(s, "councilCountryGroup", "data-country", "uk").dispatch("click");
    await pill(s, "councilStyleGroup", "data-style", "classic").dispatch("click");
    await sleep(20);
    out.signedIn.afterPills = {
      country: s.root.dataset.country, style: s.root.dataset.style,
      // the pills are a mirror: the country authority stays the <select> the app already had
      selectValue: find(s, "councilCountry").value,
      checkedCountry: checked(s, "councilCountryGroup", "data-country"),
      checkedStyle: checked(s, "councilStyleGroup", "data-style"),
      storedStyle: s.bag["padiem-council-style"] || null,
      triggerValue: text(find(s, "councilThemeValue")),
    };

    const seen = [];
    for (const country of api.theme().countries) {
      for (const style of api.theme().styles) {
        api.setTheme(country, style);
        seen.push(s.root.dataset.country + "/" + s.root.dataset.style);
      }
    }
    out.signedIn.combos = { reached: seen.length, distinct: new Set(seen).size,
                            sample: seen.slice(0, 3).concat(seen.slice(-1)) };
    api.setTheme("kr", "light");

    const selects = s.root.querySelectorAll(".council-card-select");
    await selects[0].dispatch("click");
    await sleep(40);
    out.signedIn.workspace = {
      on: s.root.classList.contains("council-in-workspace"),
      barHidden: find(s, "councilWorkspaceBar").hidden,
      title: text(find(s, "councilWorkspaceTitle")),
      openBodies: openBodies(s),
      selected: api.state().selected,
      forms: s.root.querySelectorAll(".council-form").length,
    };
    await find(s, "councilBack").dispatch("click");
    await sleep(30);
    out.signedIn.afterBack = {
      on: s.root.classList.contains("council-in-workspace"),
      barHidden: find(s, "councilWorkspaceBar").hidden,
      title: text(find(s, "councilWorkspaceTitle")),
      openBodies: openBodies(s),
      selected: api.state().selected,
    };

    // the design belongs to the page, not to the session: signed out, the axes still move
    // and the tool builders still do not attach (the fail-closed gate is unchanged).
    const off = sessionOf({ authenticated: false });
    const offApi = off.ctx.window.PadiemCouncilApps;
    await offApi.init();
    await sleep(30);
    await pill(off, "councilCountryGroup", "data-country", "fr").dispatch("click");
    await pill(off, "councilStyleGroup", "data-style", "dark").dispatch("click");
    await sleep(20);
    await off.root.querySelectorAll(".council-card-select")[0].dispatch("click");
    await sleep(30);
    out.signedOut = {
      country: off.root.dataset.country, style: off.root.dataset.style,
      selectValue: find(off, "councilCountry").value,
      panelVisible: !find(off, "councilAuthPanel").hidden,
      forms: off.root.querySelectorAll(".council-form").length,
      workspaceOn: off.root.classList.contains("council-in-workspace"),
      openBodies: openBodies(off),
      badge: text(find(off, "councilAuthBadge")),
    };
    return out;
  },

  async auth() {
    // #5942: the whole in-page sign-in path on one real execution of the shipped
    // module — signed-out visit, choosing a tool, a failed credential, a successful
    // login that continues into the chosen tool, then a session that lapses mid-use.
    const phases = [];
    const snapshot = () => requests.map((r) => r.method + " " + r.url);
    const card = (tool) => s0.root.querySelectorAll(".council-card-select")
      .find((b) => b.dataset.tool === tool);
    const formOf = (root, id) => root._descendants().find((n) => n.id === id) || null;

    authState = {
      authenticated: false,
      methods: { google: true, password: true },
      session_state: "guest",
    };
    loginOutcome = null;
    const s0 = spawnSession();
    const api = s0.ctx.window.PadiemCouncilApps;
    const first = await api.init();
    await sleep(20);
    phases.push({
      name: "signed_out",
      initSignedIn: first.signedIn,
      state: api.state(),
      badge: text(find(s0, "councilAuthBadge")),
      panelHidden: find(s0, "councilAuthPanel").hidden,
      actionHidden: find(s0, "councilAuthAction").hidden,
      googleHidden: find(s0, "councilGoogleRow").hidden,
      anyToolBuilt: Boolean(formOf(s0.root, "councilSpeechForm")),
      requests: snapshot(),
    });

    await card("sns").dispatch("click");
    await sleep(20);
    phases.push({
      name: "pick_while_signed_out",
      state: api.state(),
      panelHidden: find(s0, "councilAuthPanel").hidden,
      status: text(find(s0, "councilAuthStatus")),
      snsBodyHidden: find(s0, "councilSnsBody").hidden,
      anyToolBuilt: Boolean(formOf(s0.root, "councilSnsForm")),
      requests: snapshot(),
    });

    const loginForm = find(s0, "councilLoginForm");
    loginForm.querySelector("[name=identifier]").value = "council@example.test";
    loginForm.querySelector("[name=password]").value = "wrong-password";
    loginOutcome = json(
      { error: { code: "invalid_credentials", message: "이메일 또는 비밀번호가 올바르지 않습니다." } },
      401,
    );
    await loginForm.dispatch("submit");
    await sleep(40);
    phases.push({
      name: "failed_login",
      state: api.state(),
      status: text(find(s0, "councilAuthStatus")),
      passwordCleared: loginForm.querySelector("[name=password]").value === "",
      panelHidden: find(s0, "councilAuthPanel").hidden,
      anyToolBuilt: Boolean(formOf(s0.root, "councilSnsForm")),
      requests: snapshot(),
    });

    loginOutcome = null;
    authState = { authenticated: true, user: { name: "테스트 사용자" } };
    loginForm.querySelector("[name=password]").value = "right-password";
    await loginForm.dispatch("submit");
    await sleep(60);
    phases.push({
      name: "signed_in_continues",
      state: api.state(),
      badge: text(find(s0, "councilAuthBadge")),
      panelHidden: find(s0, "councilAuthPanel").hidden,
      status: text(find(s0, "councilAuthStatus")),
      toolsBuilt: ["councilSpeechForm", "councilSnsForm", "councilMeetingForm"]
        .map((id) => (formOf(s0.root, id) ? 1 : 0)).join(""),
      selectedHidden: find(s0, "councilSnsBody").hidden,
      otherHidden: find(s0, "councilSpeechBody").hidden,
      ariaExpanded: card("sns").getAttribute("aria-expanded"),
      activeClass: card("sns").classList.contains("active"),
      otherActiveClass: card("speech").classList.contains("active"),
      requests: snapshot(),
    });

    authState = { authenticated: false, methods: { google: true, password: true } };
    chatResponseOverride = json(
      { error: { code: "authentication_required", message: "로그인이 필요합니다." } },
      401,
    );
    await formOf(s0.root, "councilSnsForm").dispatch("submit");
    await sleep(60);
    chatResponseOverride = null;
    phases.push({
      name: "session_lapsed",
      state: api.state(),
      badge: text(find(s0, "councilAuthBadge")),
      panelHidden: find(s0, "councilAuthPanel").hidden,
      status: text(find(s0, "councilAuthStatus")),
      draftKept: (formOf(s0.root, "councilSnsOutput") || {}).value || "",
      notice: text(find(s0, "councilSnsNotice")),
      noticeTone: find(s0, "councilSnsNotice").dataset.tone || "",
      saveDisabled: find(s0, "councilSnsSave").disabled,
      requests: snapshot(),
    });

    const outcomes = loginAttempts.map((body) => Object.keys(body || {}).sort());
    authState = { authenticated: true, user: { name: "테스트 사용자" } };
    return {
      phases,
      loginAttemptKeys: outcomes,
      endpoints: endpointSet(),
      alerts,
      pageErrors,
    };
  },
  async auth_states() {
    // #6127: five answers from the SAME status read. 200 {authenticated:false} is a
    // signed-out visitor; 401/403 is a real "not allowed"; 5xx, a rejected fetch and
    // an unparseable 200 all mean the server did not say anything about this visitor.
    // The gate stays closed in the first four - that is the part that must not change
    // - and the fifth proves the single re-ask actually rescues a page load.
    const cases = [
      ["signed_out_200", {}, () => json({ authenticated: false, session_state: "guest",
                                          methods: { google: true, password: true } })],
      ["forbidden_401", {}, () => json({ error: { code: "forbidden" } }, 401)],
      ["fault_500", {}, () => ({ ok: false, status: 500,
                                 json: async () => { throw new Error("Cloudflare HTML, not JSON"); } })],
      ["network_throw", { rejects: true }, () => { throw new Error("worker did not answer"); }],
      ["ok_200_unparseable", {}, () => ({ ok: true, status: 200,
                                          json: async () => { throw new Error("HTML, not JSON"); } })],
    ];
    const rows = [];
    const runOne = async (setup) => {
      authStatusQueue = null;
      fetchRejects = null;
      authStatusOutcome = null;
      authState = { authenticated: false, methods: { google: true, password: true } };
      setup();
      const s = spawnSession();
      // the module starts itself once when the document is ready, so the counter is
      // zeroed AFTER the spawn: what is measured below is one explicit init().
      statusReads = 0;
      const api = s.ctx.window.PadiemCouncilApps;
      const first = await api.init();
      await sleep(20);
      return {
        initSignedIn: first.signedIn,
        initUnavailable: Boolean(first.unavailable),
        badge: text(find(s, "councilAuthBadge")),
        status: text(find(s, "councilAuthStatus")),
        panelHidden: find(s, "councilAuthPanel").hidden,
        loginActionHidden: find(s, "councilAuthAction").hidden,
        anyToolBuilt: ["councilSpeechForm", "councilSnsForm", "councilMeetingForm"]
          .some((id) => s.root._descendants().find((n) => n.id === id)),
        statusReads,
      };
    };

    for (const [name, opts, make] of cases) {
      const row = await runOne(() => {
        if (opts.rejects) { fetchRejects = new Error("worker did not answer"); return; }
        authStatusOutcome = make();
      });
      rows.push(Object.assign({ name }, row));
      authStatusOutcome = null;
      fetchRejects = null;
    }

    // the rescue: one 500 then a real answer. The page must end signed IN, because
    // the fault was never a statement about the visitor.
    const rescued = await runOne(() => {
      const fault = () => ({ ok: false, status: 500, json: async () => { throw new Error("no"); } });
      const answer = () => json({ authenticated: true, user: { name: "테스트 사용자" },
                                  session_state: "signed_in" });
      // one pair per init(): the module starts itself once and the scenario calls it
      // once, and each of those must survive its own 500 by re-asking.
      authStatusQueue = [fault(), answer(), fault(), answer()];
    });
    rows.push(Object.assign({ name: "fault_then_answer" }, rescued));

    authStatusQueue = null;
    authState = { authenticated: true, user: { name: "테스트 사용자" } };
    return { cases: rows, endpoints: endpointSet() };
  },
  async country_filter() {
    // #6065: switching the content country must move the stored lists with it.
    // The filter itself (sameCountry, #6046) was never missing - nothing re-ran it,
    // so a list stayed filtered for whatever country was active when it was last
    // rebuilt. One document per country is saved, then the select is moved without
    // any reload and the visible list is read.
    storedFiles.length = 0;
    saveBodies.length = 0;
    chatPayloads.length = 0;
    authState = { authenticated: true, user: { name: "테스트 사용자" } };
    const store = {};
    const s = spawnSession({ localStorage: { getItem: (k) => (k in store ? store[k] : null),
                                             setItem: (k, v) => { store[k] = String(v); } } });
    const api = s.ctx.window.PadiemCouncilApps;
    await api.init();
    await sleep(30);

    const select = find(s, "councilCountry");
    const setCountry = async (code) => {
      select.value = code;
      await select.dispatch("change");
      await sleep(40);
    };
    const speechList = () => s.root.querySelectorAll(".council-saved-open")
      .map((n) => String(n.textContent).trim().replace(/ \(.*/, ""));
    const archiveList = () => {
      const arc = find(s, "councilMeetingArchive");
      return arc ? arc.querySelectorAll(".council-archive-item").map((li) => {
        const button = li.querySelector("button");
        return button ? String(button.textContent).trim().replace(/ \(.*/, "") : "";
      }) : [];
    };
    const saveSpeech = async (eventName) => {
      const form = find(s, "councilSpeechForm");
      form.querySelector("[name=event]").value = eventName;
      await form.dispatch("submit");
      await sleep(40);
      await find(s, "councilSpeechSave").dispatch("click");
      await sleep(60);
    };

    const seen = {};
    for (const [code, eventName] of [["uk", "UK hall address"], ["fr", "Salle communale"], ["kr", "주민 센터 행사"]]) {
      await setCountry(code);
      await saveSpeech(eventName);
      seen["list_after_saving_" + code] = speechList();
      await setCountry("kr");
      seen["kr_sees_when_last_saved_was_" + code] = speechList();
      await setCountry(code);
    }
    seen["final_list"] = speechList();

    // the meeting archive follows the same rule
    const meetingForm = find(s, "councilMeetingForm");
    await setCountry("kr");
    meetingForm.querySelector("[name=title]").value = "주민 안전 회의";
    meetingForm.querySelector("[name=content]").value = "도로 보수 일정을 논의했습니다.";
    await meetingForm.dispatch("submit");
    await sleep(40);
    await find(s, "councilMeetingSave").dispatch("click");
    await sleep(60);
    const krArchive = archiveList();
    await setCountry("fr");
    const frArchive = archiveList();

    return {
      seen,
      krArchive, frArchive,
      storedCountries: storedFiles.map((f) => [f.name, f.country || "kr"]),
      // #6065 must not change what goes on the wire: the generation payload keeps
      // its keys, and a stored document is still {name, media_type, text} with
      // country present only for a non-kr save.
      chatBodyKeys: chatPayloads.map((b) => Object.keys(b || {}).sort().join(",")),
      saveBodyKeys: saveBodies.map((b) => b.keys.join(",")),
      saveCountries: saveBodies.map((b) => b.country || "kr(absent)"),
    };
  },
  async auth_routing() {
    // URL and host-storage selection: a refresh or a provider round trip must land
    // back on the tool the user had opened, without any authority in the value.
    const results = [];
    authState = { authenticated: true, user: { name: "테스트 사용자" } };
    for (const [label, windowState] of [
      ["hash", { location: { hash: "#/meeting" } }],
      ["bare_hash", { location: { hash: "#sns" } }],
      ["unknown_hash", { location: { hash: "#/../../etc" } }],
      ["remembered", { localStorage: { getItem: () => "speech", setItem: () => {} } }],
      ["hostile_stored", { localStorage: { getItem: () => "https://evil.example", setItem: () => {} } }],
    ]) {
      const session = spawnSession(windowState);
      const api = session.ctx.window.PadiemCouncilApps;
      await api.init();
      await sleep(20);
      results.push({
        label,
        selected: api.state().selected,
        openBody: ["councilSnsBody", "councilMeetingBody", "councilSpeechBody"]
          .filter((id) => !find(session, id).hidden).join("|"),
      });
    }
    return { results, pageErrors };
  },
  async selection() {
    // One click must open exactly one tool, and the next click must close it.
    // A listener bound twice would toggle twice in one click and land nowhere,
    // so the listener count is part of the observation.
    authState = { authenticated: true, user: { name: "테스트 사용자" } };
    const session = spawnSession();
    const api = session.ctx.window.PadiemCouncilApps;
    await api.init();
    await sleep(20);
    const card = (tool) => session.root.querySelectorAll(".council-card-select")
      .find((b) => b.dataset.tool === tool);
    const steps = [];
    const snap = (label) => {
      const state = api.state();
      state.label = label;
      state.speechHidden = find(session, "councilSpeechBody").hidden;
      state.snsHidden = find(session, "councilSnsBody").hidden;
      state.meetingHidden = find(session, "councilMeetingBody").hidden;
      state.speechExpanded = card("speech").getAttribute("aria-expanded");
      state.speechClickHandlers = card("speech")._listeners.click.length;
      state.activeCards = session.root.querySelectorAll(".council-card")
        .filter((node) => node.classList.contains("active")).length;
      steps.push(state);
    };
    snap("init");
    await card("speech").dispatch("click");
    await sleep(20);
    snap("open_speech");
    await card("speech").dispatch("click");
    await sleep(20);
    snap("close_speech");
    await card("meeting").dispatch("click");
    await sleep(20);
    snap("open_meeting");
    await card("sns").dispatch("click");
    await sleep(20);
    snap("switch_to_sns");
    return { steps, endpoints: endpointSet(), pageErrors };
  },
  async period_book() {
    stored("1월 회의.txt", "회의 일시: 2026-01-05T10:00\n안건 확인과 일정 논의");
    stored("3월 회의.txt", "회의 일시: 2026-03-12T10:00\n예산 추가 발언");
    stored("6월 회의.txt", "회의 일시: 2026-06-30T10:00\n성과 보고");
    stored("7월 회의.txt", "회의 일시: 2026-07-01T10:00\n범위 밖");
    stored("날짜 없는 회의.txt", "토론에서 2026-02-01 일정을 검토");
    const session = spawnSession();
    await session.ctx.window.PadiemCouncilApps.init();
    await sleep(30);
    find(session, "councilBookStart").value = "2026-01-01";
    find(session, "councilBookEnd").value = "2026-06-30";
    await find(session, "councilBookSelectPeriod").dispatch("click");
    const status = find(session, "councilBookPeriodStatus").textContent;
    const checks = find(session, "councilMeetingArchive").querySelectorAll(".council-book-check");
    const selected = checks.filter((c) => c.checked).map((c) => c.value);
    await find(session, "councilBookGenerate").dispatch("click");
    const payload = chatPayloads[chatPayloads.length - 1];
    const generated = find(session, "councilBookOutput").value;
    find(session, "councilBookOutput").value = "의정활동집 편집본\n" + generated;
    await find(session, "councilBookSave").dispatch("click");
    await sleep(30);
    const reopened = spawnSession();
    await reopened.ctx.window.PadiemCouncilApps.init();
    await sleep(30);
    const open = find(reopened, "councilMeetingArchive").querySelectorAll(".council-book-open")[0];
    await open.dispatch("click");
    return { status, selected, payload, generated,
      reopened: find(reopened, "councilBookOutput").value,
      endpoints: endpointSet(), alerts, pageErrors };
  },
  async book() {
    // #5942: the book is a product, so it must survive a page refresh. One
    // session generates and edits it, presses save twice, and a second session
    // reopens it from the stored list. The lists must also stay separated.
    authState = { authenticated: true, user: { name: "테스트 사용자" } };
    loginOutcome = null;

    const A = spawnSession();
    await A.ctx.window.PadiemCouncilApps.init();
    await sleep(20);

    const meetingFormA = find(A, "councilMeetingForm");
    meetingFormA.querySelector("[name=title]").value = "10월 주민 안전 회의";
    meetingFormA.querySelector("[name=content]").value = "도로 보수 일정과 야간 조명 예산을 논의했습니다.";
    await meetingFormA.dispatch("submit");
    await sleep(30);
    await find(A, "councilMeetingSave").dispatch("click");
    await sleep(50);

    const checksA = find(A, "councilMeetingArchive").querySelectorAll(".council-book-check");
    checksA.forEach((cb) => { cb.checked = true; });
    await find(A, "councilBookGenerate").dispatch("click");
    await sleep(60);
    const generated = find(A, "councilBookOutput").value;
    find(A, "councilBookOutput").value = "주민 안전 활동집\n\n" + generated;

    const beforeSave = requests.length;
    void find(A, "councilBookSave").dispatch("click");
    void find(A, "councilBookSave").dispatch("click");
    await sleep(120);
    const saveRequests = requests.slice(beforeSave).filter((r) => r.method === "POST")
      .map((r) => r.method + " " + r.url);
    const bookNamesA = storedFiles.filter((f) => f.name.startsWith("활동집 - ")).map((f) => f.name);
    // Right after a save the archive is re-read, so the draft and the
    // confirmation must be on the nodes that are actually on screen.
    const keptInA = {
      draftHead: find(A, "councilBookOutput").value.slice(0, 12).replace(/\s+/g, " "),
      resultHidden: find(A, "councilBookResult").hidden,
      saveLabel: find(A, "councilBookSave").textContent,
    };

    const B = spawnSession();
    await B.ctx.window.PadiemCouncilApps.init();
    await sleep(80);
    const archiveB = find(B, "councilMeetingArchive");
    const openLabels = archiveB.querySelectorAll(".council-book-open").map((b) => text(b));
    const recordChecks = archiveB.querySelectorAll(".council-book-check").length;
    const recordLabels = archiveB.querySelectorAll("li button")
      .map((b) => text(b)).filter((value) => value.indexOf("활동집 - ") !== 0);
    const speechLabelsB = find(B, "councilSpeechSaved").querySelectorAll(".council-saved-open")
      .map((b) => text(b));

    let reopened = null;
    let resultHiddenAfterOpen = null;
    if (openLabels.length) {
      await archiveB.querySelectorAll(".council-book-open")[0].dispatch("click");
      await sleep(60);
      reopened = find(B, "councilBookOutput").value;
      resultHiddenAfterOpen = find(B, "councilBookResult").hidden;
    }

    // Re-saving the reopened draft with an edited title writes under the new name.
    find(B, "councilBookOutput").value = "여름 활동 보고\n\n" + reopened;
    await find(B, "councilBookSave").dispatch("click");
    await sleep(120);
    const C = spawnSession();
    await C.ctx.window.PadiemCouncilApps.init();
    await sleep(80);
    const openLabelsC = find(C, "councilMeetingArchive").querySelectorAll(".council-book-open")
      .map((b) => text(b));

    return {
      generatedChars: generated.length,
      saveRequests,
      keptInA,
      bookNamesA,
      openLabels,
      recordChecks,
      recordLabels,
      speechLabelsB,
      reopenedHead: reopened === null ? null : reopened.slice(0, 20).replace(/\s+/g, " "),
      reopenedMatchesEdit: reopened === null ? false : reopened.startsWith("주민 안전 활동집"),
      resultHiddenAfterOpen,
      openLabelsC,
      endpoints: endpointSet(),
      alerts,
      pageErrors,
    };
  },
  async generate() {
    const session = spawnSession();
    const api = session.ctx.window.PadiemCouncilApps;
    const initResult = await api.init();
    await sleep(10);

    // speech: fill the built form and submit
    const speechForm = find(session, "councilSpeechForm");
    speechForm.querySelector("[name=event]").value = "제78주년 광복절 기념식";
    speechForm.querySelector("[name=date]").value = "2026-08-15";
    speechForm.querySelector("[name=place]").value = "강서문화회관";
    speechForm.querySelector("[name=nature]").value = "지역 행사";
    speechForm.querySelector("[name=audience]").value = "주민 200명";
    speechForm.querySelector("[name=author]").value = "김의원";
    speechForm.querySelector("[name=message]").value = "함께 성장하는 지역사회";
    speechForm.querySelector("[name=emphasis]").value = "상생과 배려";
    speechForm.querySelector("[name=length]").value = "medium";
    speechForm.querySelector("[name=tone]").value = "formal";
    const speechCalls = chatPayloads.length;
    await speechForm.dispatch("submit");
    await sleep(20);
    const speechOutput = find(session, "councilSpeechOutput").value;
    const speechPrompt = chatPayloads[speechCalls];
    // The download control names the same draft the save stores.
    await find(session, "councilSpeechDownload").dispatch("click");
    await find(session, "councilSpeechSave").dispatch("click");
    await sleep(20);

    // #5731: the saved list must list the stored speech (re-entry included)
    // and its 참고로 선택 action fills the style sample textarea.
    const speechSaved = find(session, "councilSpeechSaved");
    const refButton = speechSaved.querySelectorAll(".council-speech-use-ref")[0];
    if (!refButton) throw new Error("speech reference action missing");
    await refButton.dispatch("click");
    await sleep(20);
    const styleAfterRef = speechForm.querySelector("[name=style]").value;
    const savedListLabels = speechSaved.querySelectorAll(".council-saved-open").map((b) => text(b));

    // The generation that follows the 참고로 선택 must fence the picked
    // manuscript as the style sample, like a pasted one (#5731).
    const speechCallsAfterRef = chatPayloads.length;
    await speechForm.dispatch("submit");
    await sleep(20);
    const speechPromptAfterRef = chatPayloads[speechCallsAfterRef];
    const afterRefContent = speechPromptAfterRef && speechPromptAfterRef.messages
      && speechPromptAfterRef.messages[0] && speechPromptAfterRef.messages[0].content;
    const refPromptCarriesSample = typeof afterRefContent === "string"
      && afterRefContent.includes("아래는 사용자의 기존 축사/인사말 샘플입니다.")
      && afterRefContent.includes("---\n" + styleAfterRef + "\n---");

    // sns: pick two photos (binary originals upload first, thumbnails read
    // back through FileReader), switch platform, then generate
    const snsForm = find(session, "councilSnsForm");
    snsForm.querySelector("[name=event]").value = "주민 정원 사업 설명회";
    snsForm.querySelector("[name=whenwhere]").value = "10월 30일 오후 2시, 구청 소회의실";
    snsForm.querySelector("[name=content]").value = "정원 사업 신청 방법과 지원 금액 안내";
    snsForm.querySelector("[name=audience]").value = "구내 상인";
    const photoInput = find(session, "councilSnsPhotoInput");
    photoInput.files = [
      { name: "현장1.png", type: "image/png", __bytes: "photo-bytes-1" },
      { name: "현장2.jpg", type: "image/jpeg", __bytes: "photo-bytes-2" },
    ];
    await photoInput.dispatch("change");
    await sleep(30);
    // blog insertion position: first photo to 맨 앞
    const posSelect = find(session, "councilSnsPhotoList").querySelector(".council-photo-pos-select");
    if (posSelect) { posSelect.value = "0"; await posSelect.dispatch("change"); await sleep(20); }
    const instagramTab = snsForm.querySelectorAll(".council-sns-tab").find((b) => b.dataset.platform === "instagram");
    await instagramTab.dispatch("click");
    await sleep(10);
    const snsCalls = chatPayloads.length;
    await snsForm.dispatch("submit");
    await sleep(20);
    const snsOutput = find(session, "councilSnsOutput").value;
    const snsPrompt = chatPayloads[snsCalls];
    await find(session, "councilSnsSave").dispatch("click");
    await sleep(20);
    const photoCountText = text(find(session, "councilSnsPhotoCount"));
    const rosterFile = storedFiles.find((f) => f.name === "SNS 사진 구성.json");
    let roster = null;
    if (rosterFile) { try { roster = JSON.parse(rosterFile.text); } catch (_) {} }

    // meeting: generate, save, reopen the record, build the book
    const meetingForm = find(session, "councilMeetingForm");
    meetingForm.querySelector("[name=title]").value = "10월 주민 민원 회의";
    meetingForm.querySelector("[name=when]").value = "2026-10-24T10:00";
    meetingForm.querySelector("[name=attendees]").value = "비서실장, 지역 담당";
    meetingForm.querySelector("[name=content]").value = "항구 도로 보수 일정과 버스 노선 조정을 논의했습니다.";
    const meetingCalls = chatPayloads.length;
    await meetingForm.dispatch("submit");
    await sleep(20);
    const meetingOutput = find(session, "councilMeetingOutput").value;
    const meetingPrompt = chatPayloads[meetingCalls];
    await find(session, "councilMeetingSave").dispatch("click");
    await sleep(20);

    // the archive lists the stored record; reopen it into the editor
    const archiveButton = find(session, "councilMeetingArchive")
      .querySelectorAll("li button")
      .find((b) => b.textContent.includes("10월 주민 민원 회의"));
    if (!archiveButton) throw new Error("archive record button missing");
    find(session, "councilMeetingOutput").value = "";
    await archiveButton.dispatch("click");
    await sleep(20);
    const reopened = find(session, "councilMeetingOutput").value;

    // build the book from the selected record
    const checkbox = find(session, "councilMeetingArchive").querySelector(".council-book-check");
    if (!checkbox) throw new Error("book checkbox missing");
    checkbox.checked = true;
    const bookCalls = chatPayloads.length;
    await find(session, "councilBookGenerate").dispatch("click");
    await sleep(20);
    const bookOutput = find(session, "councilBookOutput").value;
    const bookPrompt = chatPayloads[bookCalls];

    const actionOrder = (resultId) => {
      const result = find(session, resultId);
      const actions = result.querySelector(".council-actions");
      return actions ? actions.children.map((b) => b.id || text(b)) : [];
    };
    return {
      initSignedIn: initResult.signedIn,
      badge: text(find(session, "councilAuthBadge")),
      actionOrder: {
        speech: actionOrder("councilSpeechResult"),
        sns: actionOrder("councilSnsResult"),
        meeting: actionOrder("councilMeetingResult"),
        book: actionOrder("councilBookResult"),
      },
      speech: { prompt: speechPrompt, output: speechOutput,
        savedListLabels, refSelected: styleAfterRef,
        refSelectedMatchesSaved: styleAfterRef.includes("생성된 초안 본문입니다."),
        refPromptCarriesSample },
      sns: { prompt: snsPrompt, output: snsOutput, title: text(find(session, "councilSnsTitle")),
        photoCountText, roster },
      meeting: { prompt: meetingPrompt, output: meetingOutput, reopened },
      book: { prompt: bookPrompt, output: bookOutput },
      savedCount: storedFiles.length,
      savedNames: storedFiles.map((f) => f.name),
      savedKinds: storedFiles.map((f) => [f.name, f.doc_kind || ""]),
      speechNotice: text(find(session, "councilSpeechNotice")),
      speechSaveDisabled: find(session, "councilSpeechSave").disabled,
      downloads,
      chatCredentials: requests.filter((r) => r.url === "/api/chat/stream").map((r) => r.credentials),
      endpoints: endpointSet(),
      alerts,
      pageErrors,
    };
  },
  async restore() {
    // Session A composes the durable state: three photos in the three stored
    // formats, a blog order + insertion positions, and a saved draft. Session
    // B is the re-entry: the composition must come back once at build time,
    // a removal must delete the stored original, and session C must then
    // restore the surviving composition under the re-saved platform.
    const expectedDataUrl = (bytes) => "data:image/png;base64," + Buffer.from(String(bytes), "utf8").toString("base64");

    const A = spawnSession();
    await A.ctx.window.PadiemCouncilApps.init();
    await sleep(10);

    // speech: one saved manuscript so the re-entry list has it to offer
    const speechFormA = find(A, "councilSpeechForm");
    speechFormA.querySelector("[name=event]").value = "재진입 복원 검증 행사";
    speechFormA.querySelector("[name=audience]").value = "주민";
    await speechFormA.dispatch("submit");
    await sleep(20);
    const speechDraftA = find(A, "councilSpeechOutput").value;
    await find(A, "councilSpeechSave").dispatch("click");
    await sleep(20);

    // sns: three photos — image/png, image/jpeg, image/webp
    const snsFormA = find(A, "councilSnsForm");
    snsFormA.querySelector("[name=event]").value = "복원 검증 행사";
    snsFormA.querySelector("[name=content]").value = "복원 검증용 본문";
    const photoInputA = find(A, "councilSnsPhotoInput");
    photoInputA.files = [
      { name: "앞.png", type: "image/png", __bytes: "bytes-front" },
      { name: "중간.jpg", type: "image/jpeg", __bytes: "bytes-middle" },
      { name: "끝.webp", type: "image/webp", __bytes: "bytes-end" },
    ];
    await photoInputA.dispatch("change");
    await sleep(40);

    // order: [앞, 중간, 끝] → move 앞 down → [중간, 앞, 끝]
    const photoListA = find(A, "councilSnsPhotoList");
    const frontDown = photoListA.querySelectorAll(".council-photo-move")[1];
    if (!frontDown || frontDown.dataset.move !== "1") throw new Error("move-down control missing");
    await frontDown.dispatch("click");
    await sleep(20);

    // blog insertion positions: first row 맨 앞, last row 문단 끝
    const selectsA = photoListA.querySelectorAll(".council-photo-pos-select");
    if (selectsA.length !== 3) throw new Error("position selects missing: " + selectsA.length);
    selectsA[0].value = "0";
    await selectsA[0].dispatch("change");
    await sleep(20);
    selectsA[2].value = "end";
    await selectsA[2].dispatch("change");
    await sleep(20);

    // generate on blog, then save the draft (blog platform)
    await snsFormA.dispatch("submit");
    await sleep(20);
    const draftA = find(A, "councilSnsOutput").value;
    await find(A, "councilSnsSave").dispatch("click");
    await sleep(30);
    const storedSnapshotA = storedFiles.map((f) => ({ id: f.id, name: f.name }));
    const frontId = (storedSnapshotA.find((f) => f.name === "앞.png") || {}).id;
    const middleId = (storedSnapshotA.find((f) => f.name === "중간.jpg") || {}).id;
    if (!frontId || !middleId) throw new Error("stored photos missing: " + JSON.stringify(storedSnapshotA));

    // ── session B: re-entry of the same account ──
    const B = spawnSession();
    await B.ctx.window.PadiemCouncilApps.init();
    await sleep(60);

    const speechSavedB = find(B, "councilSpeechSaved");
    const speechLabelsB = speechSavedB.querySelectorAll(".council-saved-open").map((b) => text(b));
    const speechRefCountB = speechSavedB.querySelectorAll(".council-speech-use-ref").length;

    const photoCountB = text(find(B, "councilSnsPhotoCount"));
    const photoNamesB = Array.from(find(B, "councilSnsPhotoList").querySelectorAll(".council-photo-name")).map((n) => text(n));
    const positionsB = Array.from(find(B, "councilSnsPhotoList").querySelectorAll(".council-photo-pos-select")).map((s) => s.value);
    const thumbsB = Array.from(find(B, "councilSnsPhotoList").querySelectorAll(".council-photo-thumb")).map((img) => img.src);
    const thumbsMatchOriginals = thumbsB.length === 3
      && thumbsB[0] === expectedDataUrl("bytes-middle")
      && thumbsB[1] === expectedDataUrl("bytes-front")
      && thumbsB[2] === expectedDataUrl("bytes-end");
    const draftB = find(B, "councilSnsOutput").value;
    const titleB = text(find(B, "councilSnsTitle"));
    const resultHiddenB = find(B, "councilSnsResult").hidden;
    const previewShownB = !find(B, "councilSnsPreview").hidden;

    // delete sync: removing a restored photo deletes the stored original
    const removeButtonsB = find(B, "councilSnsPhotoList").querySelectorAll(".council-photo-remove");
    const removeTarget = removeButtonsB.find((b) => b.dataset.photoId === middleId);
    if (!removeTarget) throw new Error("remove control for 중간.jpg missing");
    await removeTarget.dispatch("click");
    await sleep(30);
    const deleteRequested = requests.some((r) => r.method === "DELETE" && r.url === "/api/projects/p1/files/" + middleId);
    const middleStillStored = storedFiles.some((f) => f.id === middleId);
    const rosterAfterDelete = (() => {
      const rosterFile = storedFiles.find((f) => f.name === "SNS 사진 구성.json");
      if (!rosterFile) return null;
      try { return JSON.parse(rosterFile.text); } catch (_) { return null; }
    })();

    // re-save the draft under instagram: the roster's platform must follow
    const instaB = find(B, "councilSnsForm").querySelectorAll(".council-sns-tab")
      .find((b) => b.dataset.platform === "instagram");
    await instaB.dispatch("click");
    await sleep(10);
    await find(B, "councilSnsSave").dispatch("click");
    await sleep(30);

    // ── session C: the surviving composition, under the re-saved platform ──
    const C = spawnSession();
    await C.ctx.window.PadiemCouncilApps.init();
    await sleep(60);
    const countC = text(find(C, "councilSnsPhotoCount"));
    const namesC = Array.from(find(C, "councilSnsPhotoList").querySelectorAll(".council-photo-name")).map((n) => text(n));
    const titleC = text(find(C, "councilSnsTitle"));
    const draftC = find(C, "councilSnsOutput").value;

     return {
       speechDraftA,
       snsDraftA: draftA,
       restored: {
         speechLabelsB, speechRefCountB,
         photoCountB, photoNamesB, positionsB, thumbsMatchOriginals, thumbsB,
         draftB, titleB, resultHiddenB, previewShownB,
       },
      afterDelete: { deleteRequested, middleStillStored, rosterAfterDelete },
      sessionC: { countC, namesC, titleC, draftC },
      storedCountA: storedSnapshotA.length,
      alerts,
      pageErrors,
    };
  },
  async errors() {
    const session = spawnSession();
    await session.ctx.window.PadiemCouncilApps.init();
    await sleep(10);
    const form = find(session, "councilSpeechForm");
    form.querySelector("[name=event]").value = "오류 전달 검증";
    const outputs = [];
    const errorResponses = [
      ["server_message", json({ error: { message: "관리자 인증을 확인해 주세요." } }, 403)],
      ["no_message", json({ error: { code: "unavailable" } }, 502)],
      ["non_string", json({ error: { message: { unsafe: true } } }, 403)],
      ["not_json", { ok: false, status: 503, json: async () => { throw new Error("not JSON"); } }],
      ["empty_answer", json({ answer: "   " })],
      ["no_answer", json({ message: "서버 문장" })],
    ];
    for (const [name, response] of errorResponses) {
      chatResponseOverride = response;
      await form.dispatch("submit");
      await sleep(20);
      outputs.push({
        name,
        notice: text(find(session, "councilSpeechNotice")),
        noticeHidden: find(session, "councilSpeechNotice").hidden,
        noticeTone: find(session, "councilSpeechNotice").dataset.tone || "",
        output: find(session, "councilSpeechOutput").value,
        resultHidden: find(session, "councilSpeechResult").hidden,
        saveDisabled: find(session, "councilSpeechSave").disabled,
        generateDisabled: find(session, "councilSpeechGenerate").disabled,
      });
    }
    // A failed generation carries its own 다시 시도; pressing it runs the same
    // generation again instead of making the owner find the form button.
    const retry = find(session, "councilSpeechNotice").querySelector(".council-notice-retry");
    const retryPresent = Boolean(retry);
    const callsBeforeRetry = chatPayloads.length;
    chatResponseOverride = null;
    if (retry) { await retry.dispatch("click"); await sleep(40); }
    const retried = {
      calls: chatPayloads.length - callsBeforeRetry,
      notice: text(find(session, "councilSpeechNotice")),
      output: find(session, "councilSpeechOutput").value,
    };
    chatResponseOverride = null;
    // the same line reports a successful generation as success and re-enables saving
    await form.dispatch("submit");
    await sleep(20);
    const success = {
      notice: text(find(session, "councilSpeechNotice")),
      noticeHidden: find(session, "councilSpeechNotice").hidden,
      output: find(session, "councilSpeechOutput").value,
      saveDisabled: find(session, "councilSpeechSave").disabled,
    };
    return { outputs, retryPresent, retried, success, pageErrors };
  },
  async calendar_words() {
    // The #5655 residual case: a meeting text whose user content contains
    // 확인/추가/일정 used to be hijacked by the shared native-calendar
    // classifier when no util scope travelled with the request. With the
    // #5916 declaration the request must reach the model lane and return a
    // generation, never a calendar clarification. The fake backend records
    // the payloads; if the client failed to declare its scope the server
    // could legally answer with a clarify question — the Python assertions
    // fail on both the util field and the output in that case.
    const session = spawnSession();
    await session.ctx.window.PadiemCouncilApps.init();
    await sleep(10);
    const form = find(session, "councilMeetingForm");
    const userTexts = [
      "안건 세 개 확인했습니다.",
      "예산안 추가 논의.",
      "운영위원회 일정 확인 후 추가 안건 등록",
    ];
    const cases = [];
    for (const userText of userTexts) {
      form.querySelector("[name=title]").value = "주간 회의";
      form.querySelector("[name=content]").value = userText;
      const before = chatPayloads.length;
      await form.dispatch("submit");
      await sleep(20);
      cases.push({
        userText,
        prompt: chatPayloads[before],
        output: find(session, "councilMeetingOutput").value,
      });
    }
    return { cases, pageErrors };
  },
  async storage() {
    // #A1: one pinned project ("의원3종") is looked up by name, created once
    // when absent, and shared by all three tools through one promise. A read
    // that failed is not "there are none", so it never creates.
    authState = { authenticated: true, user: { name: "테스트 사용자" } };
    const getReads = () => requests.filter((r) => r.method === "GET" && r.url === "/api/projects").length;
    const postCreates = () => requests.filter((r) => r.method === "POST" && r.url === "/api/projects").length;
    const runOne = async (setup) => {
      requests.length = 0;
      storedFiles.length = 0;
      saveBodies.length = 0;
      projectRows = [{ id: "p1", name: "의원3종" }];
      projectCreates = 0;
      createdProjectId = "p2";
      projectsReadFails = false;
      setup();
      const s = spawnSession();
      const api = s.ctx.window.PadiemCouncilApps;
      await api.init();
      await sleep(40);
      const form = find(s, "councilSpeechForm");
      form.querySelector("[name=event]").value = "저장 프로젝트 확인";
      form.querySelector("[name=date]").value = "2026-11-01";
      await form.dispatch("submit");
      await sleep(20);
      await find(s, "councilSpeechSave").dispatch("click");
      await sleep(60);
      return {
        getReads: getReads(), postCreates: postCreates(),
        savedTo: requests.filter((r) => r.method === "POST" && /^\/api\/projects\/[^/]+\/files$/.test(r.url))
          .map((r) => r.url),
        storedNames: storedFiles.map((f) => f.name),
        notice: text(find(s, "councilSpeechNotice")),
      };
    };
    const otherFirst = await runOne(() => {
      projectRows = [{ id: "p0", name: "다른 작업" }, { id: "p1", name: "의원3종" }];
    });
    const absent = await runOne(() => { projectRows = []; });
    const readFails = await runOne(() => { projectsReadFails = true; });
    // a failed read is retried by the next ensure(), and only then may create
    const retry = await (async () => {
      projectsReadFails = false;
      requests.length = 0;
      storedFiles.length = 0;
      projectRows = [];
      const s = spawnSession();
      const api = s.ctx.window.PadiemCouncilApps;
      await api.init();
      await sleep(40);
      const form = find(s, "councilSpeechForm");
      form.querySelector("[name=event]").value = "재시도 저장";
      form.querySelector("[name=date]").value = "2026-11-01";
      await form.dispatch("submit");
      await sleep(20);
      await find(s, "councilSpeechSave").dispatch("click");
      await sleep(60);
      return { postCreates: postCreates(), storedNames: storedFiles.map((f) => f.name) };
    })();
    const createBodies = requests.filter((r) => r.method === "POST" && r.url === "/api/projects").length;
    projectRows = [{ id: "p1", name: "의원3종" }];
    projectCreates = 0;
    projectsReadFails = false;
    return { otherFirst, absent, readFails, retry, createBodies,
             projectCreates, pageErrors, requests: requests.map((r) => r.method + " " + r.url) };
  },
  async conflict() {
    // #5731: a name already used by the same kind asks the owner — new name
    // (default) or overwrite; a save failure shows the server's sentence.
    authState = { authenticated: true, user: { name: "테스트 사용자" } };
    storedFiles.length = 0;
    requests.length = 0;
    saveBodies.length = 0;
    const s = spawnSession();
    await s.ctx.window.PadiemCouncilApps.init();
    await sleep(30);
    const form = find(s, "councilSpeechForm");
    form.querySelector("[name=event]").value = "중복 이름 행사";
    form.querySelector("[name=date]").value = "2026-11-01";
    await form.dispatch("submit");
    await sleep(20);
    const save = find(s, "councilSpeechSave");
    await save.dispatch("click");
    await sleep(40);
    const firstName = storedFiles.map((f) => f.name);

    // second save: the server answers 409 with the existing file. The click
    // handler waits for the owner's choice, so the dispatch is not awaited.
    void save.dispatch("click");
    await sleep(60);
    const choice = s.root.querySelectorAll(".council-save-as-new")[0];
    const choiceLabel = choice ? text(choice) : "";
    const saveChoiceText = s.root.querySelectorAll(".council-save-choice-text").map((n) => text(n));
    if (choice) { await choice.dispatch("click"); await sleep(60); }
    const afterNew = storedFiles.map((f) => f.name);

    // a third save collides again, this time overwrite keeps the id
    const beforeIds = storedFiles.map((f) => f.id);
    find(s, "councilSpeechOutput").value = "덮어쓴 본문";
    void save.dispatch("click");
    await sleep(60);
    const overwriteAgain = s.root.querySelectorAll(".council-save-overwrite")[0];
    if (overwriteAgain) { await overwriteAgain.dispatch("click"); await sleep(60); }
    const afterOverwrite = storedFiles.map((f) => ({ id: f.id, name: f.name, text: f.text }));

    // a save the server refuses says so on the notice line
    find(s, "councilSpeechOutput").value = "저장 실패 문구 검증";
    saveFailureOverride = json({ error: { code: "unavailable", message: "저장소가 잠시 응답하지 않습니다." } }, 503);
    await save.dispatch("click");
    await sleep(40);
    const failureNotice = text(find(s, "councilSpeechNotice"));
    const failureTone = find(s, "councilSpeechNotice").dataset.tone || "";
    const failureDisabled = save.disabled;

    return { firstName, choiceLabel, saveChoiceText, afterNew, beforeIds,
             afterOverwrite, failureNotice, failureTone, failureDisabled,
             endpoints: endpointSet(), alerts, pageErrors };
  },
  async roster() {
    // #A4: the roster is updated in place (PUT), a photo the roster does not
    // name never comes back, and a big photo is shrunk before upload.
    authState = { authenticated: true, user: { name: "테스트 사용자" } };
    storedFiles.length = 0;
    requests.length = 0;
    downloads.length = 0;
    const resizeCalls = [];
    const shrink = {
      MAX_EDGE: 1920,
      resizeDataUrl: async (source, edge, type) => {
        resizeCalls.push({ edge: edge, type: type });
        return { dataUrl: "data:image/png;base64,QUJD", resized: true, width: 10, height: 10 };
      },
    };
    const windowState = {
      Image: function () {},
      PadiemPhotoResize: shrink,
    };
    const A = spawnSession(windowState);
    await A.ctx.window.PadiemCouncilApps.init();
    await sleep(30);
    const formA = find(A, "councilSnsForm");
    formA.querySelector("[name=event]").value = "로스터 갱신 검증";
    formA.querySelector("[name=content]").value = "본문";
    const inputA = find(A, "councilSnsPhotoInput");
    inputA.files = [
      { name: "하나.png", type: "image/png", __bytes: "one" },
      { name: "둘.png", type: "image/png", __bytes: "two" },
    ];
    await inputA.dispatch("change");
    await sleep(80);
    const rosterPosts = requests.filter((r) => r.method === "POST"
      && r.headers["Content-Type"] === "application/json").length;

    // reorder → the existing roster is rewritten in place
    const down = find(A, "councilSnsPhotoList").querySelectorAll(".council-photo-move")[1];
    await down.dispatch("click");
    await sleep(60);
    const rosterWrites = requests.filter((r) => r.url.indexOf("/files/") >= 0 && r.method === "PUT").length;
    const rosterDeletes = requests.filter((r) => r.method === "DELETE").length;
    const rosterFiles = storedFiles.filter((f) => f.name === "SNS 사진 구성.json");

    // a stale image the roster never names must not resurface on re-entry
    const stray = stored("stray.png", "", "image/png", "stray");
    const B = spawnSession(windowState);
    await B.ctx.window.PadiemCouncilApps.init();
    await sleep(80);
    const namesB = find(B, "councilSnsPhotoList").querySelectorAll(".council-photo-name").map((n) => text(n));
    const countB = text(find(B, "councilSnsPhotoCount"));
    return {
      resizeCalls: resizeCalls.length,
      uploadTypes: storedFiles.filter((f) => f.media_type.indexOf("image/") === 0)
        .map((f) => [f.name, f.media_type]),
      rosterPosts, rosterWrites, rosterDeletes,
      rosterCount: rosterFiles.length,
      rosterNames: rosterFiles.length ? JSON.parse(rosterFiles[0].text).photos.map((p) => p.name) : [],
      strayRestored: namesB.indexOf("stray.png") >= 0 || namesB.indexOf(stray.name) >= 0,
      namesB, countB,
      alerts, pageErrors,
    };
  },
  async runtime() {
    // #A5: Escape inside a field does not close the workspace; the book save's
    // list scan uses an Array (querySelectorAll returns a NodeList).
    authState = { authenticated: true, user: { name: "테스트 사용자" } };
    const s = spawnSession();
    const api = s.ctx.window.PadiemCouncilApps;
    await api.init();
    await sleep(30);
    await s.root.querySelectorAll(".council-card-select")[0].dispatch("click");
    await sleep(30);
    const opened = api.state().selected;
    const textarea = find(s, "councilSpeechForm").querySelector("textarea");
    await s.ctx.document.dispatch("keydown", { key: "Escape", target: textarea });
    const afterTypingEscape = api.state().selected;
    await s.ctx.document.dispatch("keydown", { key: "Escape", target: null });
    const afterPlainEscape = api.state().selected;
    return { opened, afterTypingEscape, afterPlainEscape, pageErrors };
  },
  async speech_form() {
    // #B8: the first four fields only, the rest folded; placeholders per field;
    // the last 직책과 이름 comes back.
    authState = { authenticated: true, user: { name: "테스트 사용자" } };
    downloads.length = 0;
    const bag = {};
    const state = { localStorage: { getItem: (k) => (k in bag ? bag[k] : null),
                                   setItem: (k, v) => { bag[k] = String(v); } } };
    const A = spawnSession(state);
    await A.ctx.window.PadiemCouncilApps.init();
    await sleep(30);
    const formA = find(A, "councilSpeechForm");
    const directlyVisible = ["event", "audience", "author", "length"];
    const folded = ["date", "place", "nature", "message", "emphasis", "tone", "style"];
    const fold = formA.querySelector(".council-more");
    const foldFields = fold ? folded.map((name) => Boolean(fold.querySelector("[name=" + name + "]"))) : [];
    const placeholders = {};
    ["event", "audience", "author", "place", "nature", "message", "emphasis"].forEach((name) => {
      const field = formA.querySelector("[name=" + name + "]");
      placeholders[name] = field ? field.placeholder : "";
    });
    const lengthOptions = formA.querySelector("[name=length]").children.map((o) => text(o));
    formA.querySelector("[name=author]").value = "지역구 국회의원 김의민";
    await formA.querySelector("[name=author]").dispatch("change");
    formA.querySelector("[name=event]").value = "86주년 기념식";
    formA.querySelector("[name=date]").value = "2026-12-24";
    await formA.dispatch("submit");
    await sleep(20);
    await find(A, "councilSpeechDownload").dispatch("click");
    await sleep(10);

    const B = spawnSession(state);
    await B.ctx.window.PadiemCouncilApps.init();
    await sleep(30);
    const rememberedAuthor = find(B, "councilSpeechForm").querySelector("[name=author]").value;
    return { directlyVisible, foldedFields: foldFields, foldTag: fold ? fold.tagName : "",
             placeholders, lengthOptions, rememberedAuthor, downloads, pageErrors };
  },
  async pc() {
    // #5895: the independent app keeps the same PC bridge — a calm no-PC
    // sentence with the way to connect, a reference import that reaches the
    // prompt, a save that always offers a NEW name, and the shared photo
    // import reading /api/pc/file.
    authState = { authenticated: true, user: { name: "테스트 사용자" } };
    const opened = [];
    const exchange = {
      open(options) {
        opened.push(options);
        if (options.mode === "save") {
          pcSaves.push({ fileName: options.fileName, content: options.content });
          if (options.onSave) options.onSave({});
          return;
        }
        if (options.mode === "import") {
          options.onSelect({ fileId: "pc-photo-1", name: "현장사진.png" });
          return;
        }
        options.onSelect({ fileId: "pc-doc-1", name: "예전 축사.hwp" });
      },
    };
    const state = { PadiemPcFileExchange: exchange };

    // signed in, no computer linked
    pcLinks = [];
    const A = spawnSession(state);
    await A.ctx.window.PadiemCouncilApps.init();
    await sleep(30);
    await A.root.querySelectorAll(".council-card-select")[0].dispatch("click");
    await sleep(40);
    const pickA = find(A, "councilSpeechForm").querySelector(".council-pc-ref-pick");
    const noteA = find(A, "councilSpeechForm").querySelector(".council-pc-ref-note");
    const linkA = noteA.querySelector(".council-pc-ref-connect");
    const noPc = {
      pickHidden: pickA.hidden,
      noteHidden: noteA.hidden,
      note: text(noteA),
      linkLabel: linkA ? text(linkA) : "",
      linkHref: linkA ? (linkA.href || linkA.getAttribute("href")) : "",
      referenceReads: pcReferenceReads.length,
    };
    // saving to a PC that is not linked is guidance, not an error
    const formA = find(A, "councilSpeechForm");
    formA.querySelector("[name=event]").value = "PC 없음 저장";
    await formA.dispatch("submit");
    await sleep(30);
    await find(A, "councilSpeechPcSave").dispatch("click");
    await sleep(30);
    const noPcSaveNotice = find(A, "councilSpeechNotice");
    noPc.saveNotice = text(noPcSaveNotice);
    noPc.saveNoticeLink = noPcSaveNotice.querySelector
      ? (noPcSaveNotice.querySelector(".council-notice-link") || {}).href || ""
      : "";
    noPc.saveNoticeTone = noPcSaveNotice.dataset.tone || "";

    // linked: import a reference, generate, then save to the PC
    pcLinks = [{ state: "active" }];
    const B = spawnSession(state);
    await B.ctx.window.PadiemCouncilApps.init();
    await sleep(30);
    await B.root.querySelectorAll(".council-card-select")[0].dispatch("click");
    await sleep(40);
    const formB = find(B, "councilSpeechForm");
    formB.querySelector("[name=event]").value = "PC 가져오기 검증";
    formB.querySelector("[name=date]").value = "2026-11-01";
    await formB.querySelector(".council-pc-ref-pick").dispatch("click");
    await sleep(60);
    const previewB = formB.querySelector(".council-pc-ref-preview");
    const importedB = { preview: previewB ? text(previewB) : "", reads: pcReferenceReads.slice() };
    await formB.dispatch("submit");
    await sleep(40);
    const promptB = chatPayloads[chatPayloads.length - 1];
    const outputB = find(B, "councilSpeechOutput").value;
    await find(B, "councilSpeechPcSave").dispatch("click");
    await sleep(30);
    const saveNoticeB = text(find(B, "councilSpeechNotice"));
    const savedB = pcSaves.length ? pcSaves[pcSaves.length - 1] : null;
    const storedNameB = storedFiles.map((f) => f.name);

    // SNS photo import through /api/pc/file
    await B.ctx.window.PadiemCouncilApps.select("sns", false);
    await sleep(40);
    await find(B, "councilSnsPhotoAdd").dispatch("click");
    await sleep(80);
    const photoCount = text(find(B, "councilSnsPhotoCount"));
    const photoNames = find(B, "councilSnsPhotoList").querySelectorAll(".council-photo-name").map((n) => text(n));
    const photoUpload = storedFiles.filter((f) => f.media_type === "image/png").map((f) => f.name);

    await find(B, "councilSnsForm").querySelector(".council-pc-ref-pick").dispatch("click");
    await sleep(40);
    const snsFormB = find(B, "councilSnsForm");
    snsFormB.querySelector("[name=event]").value = "SNS PC 참고";
    snsFormB.querySelector("[name=content]").value = "본문";
    const snsCalls = chatPayloads.length;
    await snsFormB.dispatch("submit");
    await sleep(40);
    const snsPromptB = chatPayloads[snsCalls];
    pcLinks = [];
    return {
      noPc, importedB,
      speechPrompt: promptB && promptB.messages && promptB.messages[0] ? promptB.messages[0].content : "",
      outputB, saveNoticeB, savedB,
      savedIsNewName: savedB ? !storedNameB.includes(savedB.fileName) : false,
      pcDispatch: pcDispatches.slice(),
      photoCount, photoNames, photoUpload,
      snsPrompt: snsPromptB && snsPromptB.messages && snsPromptB.messages[0] ? snsPromptB.messages[0].content : "",
      openedModes: opened.map((o) => o.mode || "import"),
      endpoints: endpointSet(), alerts, pageErrors,
    };
  },
  async streaming() {
    // The answer is painted as it arrives: an intermediate value is observed
    // before the final one, from the /api/chat/stream route.
    authState = { authenticated: true, user: { name: "테스트 사용자" } };
    streamDelayMs = 12;
    const s = spawnSession();
    await s.ctx.window.PadiemCouncilApps.init();
    await sleep(30);
    const form = find(s, "councilSpeechForm");
    form.querySelector("[name=event]").value = "스트리밍 검증";
    await form.dispatch("submit");
    const lengths = [];
    for (let i = 0; i < 40; i += 1) {
      await sleep(5);
      const length = String(find(s, "councilSpeechOutput").value || "").length;
      if (!lengths.length || lengths[lengths.length - 1] !== length) lengths.push(length);
      if (find(s, "councilSpeechSave").disabled === false) break;
    }
    const request = requests.find((r) => r.url === "/api/chat/stream");
    streamDelayMs = 0;
    return {
      lengths,
      final: find(s, "councilSpeechOutput").value,
      expected: ANSWER_PARTS.join(""),
      endpoint: request ? request.url : "",
      accept: request ? request.headers.Accept : "",
      notice: text(find(s, "councilSpeechNotice")),
      pageErrors,
    };
  },
  async parity() {
    // 저장 글 다시 열기 · 회의 기록 순서 · 기간 빠른 선택 · SNS 저장 목록.
    authState = { authenticated: true, user: { name: "테스트 사용자" } };
    storedFiles.length = 0;
    requests.length = 0;
    const NL = String.fromCharCode(10);
    stored("1월 회의.txt", "회의 일시: 2026-01-05T10:00" + NL + "첫 기록", "text/plain", null, null, "meeting");
    stored("3월 회의.txt", "회의 일시: 2026-03-12T10:00" + NL + "둘째 기록", "text/plain", null, null, "meeting");
    stored("지난 축사.txt", "지난 축사 본문", "text/plain", null, null, "speech");
    stored("블로그 게시글.txt", "저장된 SNS 초안", "text/plain", null, null, "sns");
    const s = spawnSession();
    await s.ctx.window.PadiemCouncilApps.init();
    await sleep(40);
    const archive = find(s, "councilMeetingArchive");

    // the visible order is the book order
    const rows = () => archive.querySelectorAll(".council-archive-item");
    const names = () => rows().map((li) => {
      const buttons = li.querySelectorAll("button");
      return buttons.length ? text(buttons[0]) : "";
    });
    const before = names();
    const secondUp = rows()[1].querySelectorAll(".council-record-move")[0];
    await secondUp.dispatch("click");
    const afterMove = names();
    archive.querySelectorAll(".council-book-check").forEach((cb) => { cb.checked = true; });
    const calls = chatPayloads.length;
    await find(s, "councilBookGenerate").dispatch("click");
    await sleep(40);
    const bookPrompt = chatPayloads[calls] ? chatPayloads[calls].messages[0].content : "";

    // quick ranges fill the two dates and run the selection
    const year = new Date().getFullYear();
    const thisYear = archive.querySelectorAll(".council-book-quick").find((b) => text(b) === "올해");
    await thisYear.dispatch("click");
    await sleep(80);
    const periodStatus = text(find(s, "councilBookPeriodStatus"));
    const selectedAfterQuick = archive.querySelectorAll(".council-book-check").filter((cb) => cb.checked).length;

    // a stored speech opens with the naming note
    const speechOpen = find(s, "councilSpeechSaved").querySelectorAll(".council-saved-open")[0];
    await speechOpen.dispatch("click");
    await sleep(30);
    const speechNotice = text(find(s, "councilSpeechNotice"));
    const speechBody = find(s, "councilSpeechOutput").value;

    // a stored SNS draft is listed and reopens
    const snsList = find(s, "councilSnsSaved");
    const snsLabels = snsList.querySelectorAll(".council-saved-open").map((b) => text(b));
    await snsList.querySelectorAll(".council-saved-open")[0].dispatch("click");
    await sleep(30);
    const snsBody = find(s, "councilSnsOutput").value;
    const snsNotice = text(find(s, "councilSnsNotice"));
    return { before, afterMove, bookPrompt, year, periodStatus, selectedAfterQuick,
             speechNotice, speechBody, snsLabels, snsBody, snsNotice,
             alerts, pageErrors };
  },
  async prompt() {
    const builder = String(process.argv[4] || "");
    const payload = JSON.parse(process.argv[5] || "{}");
    // Prompt builders are pure: expose them through a throwaway module load.
    const session = spawnSession();
    const api = session.ctx.window.PadiemCouncilApps;
    if (builder === "speech") return { prompt: api.speech.buildPrompt(toForm(payload)) };
    if (builder === "sns") {
      const { platform, photos, ...fields } = payload;
      return { prompt: api.sns.buildPrompt(toForm(fields), platform, photos) };
    }
    if (builder === "meeting") return { prompt: api.meeting.buildPrompt(toForm(payload)) };
    if (builder === "book") return { prompt: api.meeting.buildBookPrompt(payload.contents || []) };
    throw new Error("unknown builder: " + builder);
  },
  async nav_search() {
    // 2026-11-01: 시안(04) 상단 메뉴·검색 상자. 메뉴 항목은 실제 있는 화면으로만
    // 연결되고(홈·업무 도구·도구 3종), 검색은 도구 3종 안에서만 길을 찾는다.
    // fail-closed 게이트는 메뉴·검색 경로에서도 동일하게 유지된다.
    const sessionOf = (state) => {
      authState = state;
      return spawnSession();
    };
    const navItem = (s, name) => s.root.querySelectorAll("[data-nav]")
      .find((n) => n.getAttribute("data-nav") === name);
    const snapshotState = (s) => ({
      inWorkspace: s.root.classList.contains("council-in-workspace"),
      activeTool: s.root.dataset.activeTool || null,
      barHidden: find(s, "councilWorkspaceBar").hidden,
      title: text(find(s, "councilWorkspaceTitle")),
      openBodies: ["councilSpeechBody", "councilSnsBody", "councilMeetingBody"]
        .filter((id) => !find(s, id).hidden),
      forms: s.root.querySelectorAll(".council-form").length,
    });

    const s = sessionOf({ authenticated: true, user: { name: "테스트 사용자" } });
    const api = s.ctx.window.PadiemCouncilApps;
    await api.init();
    await sleep(30);
    const out = { signedIn: {} };

    await navItem(s, "speech").dispatch("click");
    await sleep(40);
    out.signedIn.navSpeech = snapshotState(s);

    await navItem(s, "tools").dispatch("click");
    await sleep(40);
    out.signedIn.navTools = snapshotState(s);

    await navItem(s, "meeting").dispatch("click");
    await sleep(40);
    out.signedIn.navMeeting = snapshotState(s);

    await navItem(s, "home").dispatch("click");
    await sleep(40);
    out.signedIn.navHome = snapshotState(s);

    const form = find(s, "councilSearchForm");
    const input = find(s, "councilSearch");
    const status = find(s, "councilSearchStatus");
    input.value = "축사";
    await form.dispatch("submit");
    await sleep(40);
    out.signedIn.searchSpeech = { state: snapshotState(s), statusHidden: status.hidden };

    input.value = "전혀 어울리지 않는 낱말";
    await form.dispatch("submit");
    await sleep(40);
    out.signedIn.searchMiss = {
      state: snapshotState(s),
      statusShown: !status.hidden,
      statusText: text(status),
    };

    const off = sessionOf({ authenticated: false, methods: { password: true } });
    const apiOff = off.ctx.window.PadiemCouncilApps;
    await apiOff.init();
    await sleep(30);
    await navItem(off, "sns").dispatch("click");
    await sleep(40);
    out.signedOut = {
      navSns: snapshotState(off),
      panelHidden: find(off, "councilAuthPanel").hidden,
    };
    const formOff = find(off, "councilSearchForm");
    const inputOff = find(off, "councilSearch");
    inputOff.value = "SNS";
    await formOff.dispatch("submit");
    await sleep(40);
    out.signedOut.searchSns = snapshotState(off);
    return out;
  },
  async export() {
    // 2026-11-01: 한글(HWPX)·워드(DOCX)·텍스트 내려받기. 실제 버튼 클릭이
    // 만드는 바이트와 파일 이름을 그대로 관찰한다. 활동집은 초안의 구조
    // (제목·기간·회의별 소제목·본문)가 문서로 옮겨지는지 함께 본다.
    downloads.length = 0;
    downloadDetails.length = 0;
    const s = spawnSession({ authenticated: true, user: { name: "테스트 사용자" } });
    const api = s.ctx.window.PadiemCouncilApps;
    await api.init();
    await sleep(30);
    const out = {};

    // 축사: 폼의 행사명·날짜가 문서 제목과 파일명에 그대로 간다.
    const speechForm = find(s, "councilSpeechForm");
    speechForm.querySelector("[name=event]").value = "주민 감사의 밤";
    speechForm.querySelector("[name=date]").value = "2026-11-01";
    find(s, "councilSpeechOutput").value =
      "존경하는 시민 여러분,\n\n함께 감사를 나누는 자리였습니다.\n감사합니다.";
    await find(s, "councilSpeechDownloadHwpx").dispatch("click");
    await sleep(20);
    await find(s, "councilSpeechDownloadDocx").dispatch("click");
    await sleep(20);
    await find(s, "councilSpeechDownload").dispatch("click");
    await sleep(20);
    out.speech = {
      hwpx: downloadDetails[0], docx: downloadDetails[1], txt: downloads[2],
    };

    // 활동집: "1. 제목" 첫 줄·기간 줄·"제N장" 소제목·본문 — 구조 보존 확인.
    find(s, "councilBookOutput").value = [
      "1. 10월 활동집",
      "기간: 2026-10-01 ~ 2026-10-31",
      "제1장 주민 간담회",
      "관내 주민 40명이 참석해 정자 조성을 논의했다.",
      "",
      "제2장 현장 방문",
      "함께 현장을 살폈다.",
    ].join("\n");
    await find(s, "councilBookDownloadHwpx").dispatch("click");
    await sleep(20);
    await find(s, "councilBookDownloadDocx").dispatch("click");
    await sleep(20);
    await find(s, "councilBookDownload").dispatch("click");
    await sleep(20);
    out.book = {
      hwpx: downloadDetails[2], docx: downloadDetails[3], txt: downloads[5],
    };
    const toB64 = (detail) => ({
      download: detail.download,
      bytes: detail.bytes ? Buffer.from(detail.bytes).toString("base64") : null,
    });
    out.speech.hwpx = toB64(out.speech.hwpx);
    out.speech.docx = toB64(out.speech.docx);
    out.book.hwpx = toB64(out.book.hwpx);
    out.book.docx = toB64(out.book.docx);
    return out;
  },
};

function toForm(fields) {
  // A minimal form shim whose querySelector resolves named fields.
  const form = new N("form");
  Object.keys(fields || {}).forEach((name) => {
    const field = new N("input");
    field.name = name;
    field.value = String(fields[name] == null ? "" : fields[name]);
    form.appendChild(field);
  });
  return form;
}

(async () => {
  try {
    if (!Object.prototype.hasOwnProperty.call(SCENARIOS, scenario)) {
      throw new Error("unknown scenario: " + scenario);
    }
    const observation = await SCENARIOS[scenario]();
    if (observation && Object.prototype.hasOwnProperty.call(observation, "prompt")) {
      process.stdout.write(JSON.stringify({ ok: true, scenario, prompt: observation.prompt }));
    } else {
      process.stdout.write(JSON.stringify({ ok: true, scenario, observation }));
    }
  } catch (error) {
    process.stdout.write(JSON.stringify({ ok: false, scenario, error: String((error && error.stack) || error) }));
  }
})();
