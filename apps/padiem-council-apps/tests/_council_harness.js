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
// #5942: the same-origin session contract the entry page uses. A scenario flips
// these to walk signed-out → in-page login → expiry without any second authority.
let authState = { authenticated: true, user: { name: "테스트 사용자" } };
let loginOutcome = null;

function json(body, status) {
  return { ok: (status || 200) < 400, status: status || 200, json: async () => body };
}

const stored = (name, textValue, mediaType, bytes) => {
  const file = { id: "f" + (++fileIdSeq), name, media_type: mediaType || "text/plain", content_chars: String(textValue || "").length };
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
  if (method === "POST" && String(url) === "/api/chat") {
    chatPayloads.push(body);
    if (chatResponseOverride) return chatResponseOverride;
    return json({ answer: "생성된 초안 본문입니다.\n\n두 번째 문단입니다." });
  }
  if (String(url) === "/api/auth/status") return json(authState);
  if (method === "POST" && String(url) === "/api/auth/password/login") {
    loginAttempts.push(body);
    if (loginOutcome) return loginOutcome;
    return json({ ok: true, user: { name: "테스트 사용자" } });
  }
  if (String(url) === "/api/projects") {
    if (method === "GET") return json({ projects: [{ id: "p1", name: "내 프로젝트" }] });
    return json({ project: { id: "p1", name: (body && body.name) || "" } });
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
      const file = stored((body && body.name) || "무제.txt", (body && body.text) || "", (body && body.media_type) || "text/plain");
      return json({ file });
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

// ── one council-app.js execution against a fresh fake DOM ──────────────────
class FakeFormData {
  constructor(form) { this._form = form || null; }
  get(key, default_) {
    const field = this._form && this._form.querySelector(`[name=${key}]`);
    if (!field) return default_ === undefined ? null : default_;
    return field.value;
  }
}

function FakeBlob() {}

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
  root.append(badge, note);

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

  const ctx = {
    document: {
      readyState: "complete",
      body: mk("body", null),
      documentElement: root,
      getElementById: (id) => byId[id] || root._descendants().find((n) => n.id === id) || null,
      querySelector: (sel) => root.querySelector(sel),
      querySelectorAll: (sel) => root.querySelectorAll(sel),
      createElement: (tag) => new N(tag),
      addEventListener() {},
    },
    window: windowState,
    navigator: { clipboard: { writeText: async () => {} } },
    fetch,
    alert: (message) => alerts.push(String(message)),
    console,
    setTimeout: () => 0,
    Blob: FakeBlob,
    FileReader: FakeFileReader,
    URL: { createObjectURL: () => "blob:fixture", revokeObjectURL() {} },
    FormData: FakeFormData,
  };
  vm.createContext(ctx);
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

    return {
      initSignedIn: initResult.signedIn,
      badge: text(find(session, "councilAuthBadge")),
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
      chatCredentials: requests.filter((r) => r.url === "/api/chat").map((r) => r.credentials),
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
    ];
    for (const [name, response] of errorResponses) {
      chatResponseOverride = response;
      await form.dispatch("submit");
      await sleep(20);
      outputs.push({ name, output: find(session, "councilSpeechOutput").value });
    }
    chatResponseOverride = null;
    return { outputs, pageErrors };
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
