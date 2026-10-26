// #5785 — one fake-DOM host for the REAL util-menu.js so the three 의원3종
// tools (speech / SNS / meeting) can be exercised one at a time.
//
// The DOM shim and the recording fetch follow the same contract the #5608 and
// #5728 harnesses already established for this file: the browser module under
// test is the shipped `static/util-menu.js`, the backend is a recording fake of
// the EXISTING endpoints (/api/chat, /api/projects, /api/projects/{id}/files),
// and nothing here invents a product behaviour or a second API.
//
// Usage: node _5785_util_harness.js <util-menu.js path> <scenario>
//   scenario = speech | sns | meeting | shared | tier
// Prints one JSON object of observations; the Python test modules own the
// assertions so a changed contract fails in the readable place.
const fs = require("node:fs");
const vm = require("node:vm");

const utilMenuPath = process.argv[2];
const scenario = String(process.argv[3] || "").toLowerCase();

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
    this._cls = "";
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
      toggle: (c, forced) => { const want = forced === undefined ? !has(c) : forced; if (want) self.classList.add(c); else self.classList.remove(c); },
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
    const evt = Object.assign({ preventDefault() {}, target: this }, event || {});
    let node = this;
    while (node) {
      for (const fn of (node._listeners[type] || []).slice()) await fn.call(node, evt);
      node = node.parentNode;
    }
  }
  focus() {}
  scrollIntoView() {}
  click() { return this.dispatch("click"); }
  querySelector(sel) { return this.findAll(sel)[0] || null; }
  querySelectorAll(sel) { return this.findAll(sel); }
  _descendants() {
    const out = [];
    for (const child of this.children) { out.push(child); out.push(...child._descendants()); }
    return out;
  }
  findAll(sel) {
    const parts = String(sel).trim().split(/\s+/);
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

function simpleMatch(node, part) {
  if (!node || !node.tagName) return false;
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

class FakeFormData {
  constructor(form) {
    this._entries = [];
    const seen = new Set();
    const all = [form, ...form._descendants()];
    for (const node of all) {
      if (!node.name || seen.has(node.name)) continue;
      seen.add(node.name);
      this._entries.push([node.name, node.value]);
    }
  }
  get(name) {
    const found = this._entries.find(([key]) => key === name);
    return found ? found[1] : null;
  }
  entries() { return this._entries[Symbol.iterator](); }
}

// ── recording backend: only the endpoints the util tools already use ────────
const requests = [];
const chatPayloads = [];
let chatResponseOverride = null;
const storedFiles = [];
const alerts = [];
// A browser logs an unhandled rejection and keeps the page alive; model that so
// one recorded defect does not hide the rest of the feature's contract.
const pageErrors = [];
process.on("unhandledRejection", (reason) => {
  pageErrors.push(String((reason && reason.message) || reason));
});
const PROJECT_ID = "p1";
const ANSWER = "생성된 초안 본문입니다.\n\n두 번째 문단입니다.";

function json(payload, status) {
  return { ok: (status || 200) < 400, status: status || 200, json: async () => payload };
}

async function fetch(url, opts) {
  const options = opts || {};
  const method = String(options.method || "GET").toUpperCase();
  const rawUrl = String(url);
  const path = rawUrl.split("?")[0];
  let body = null;
  if (typeof options.body === "string") {
    try { body = JSON.parse(options.body); } catch (_) { body = null; }
  }
  requests.push({ method, url: path, credentials: options.credentials || null });

  if (method === "POST" && path === "/api/chat") {
    chatPayloads.push(body);
    return chatResponseOverride || json({ answer: ANSWER });
  }
  if (method === "GET" && path === "/api/projects") {
    return json({ projects: [{ id: PROJECT_ID, name: "유틸 작업" }] });
  }
  if (method === "GET" && path === `/api/projects/${PROJECT_ID}/files`) {
    return json({
      files: storedFiles.map((f) => ({ id: f.id, name: f.name, media_type: f.media_type, content_chars: f.content_chars })),
    });
  }
  if (method === "POST" && path === `/api/projects/${PROJECT_ID}/files` && body) {
    const file = {
      id: "f" + (storedFiles.length + 1),
      name: body.name,
      media_type: body.media_type,
      content: String(body.text || ""),
      content_chars: String(body.text || "").length,
    };
    storedFiles.push(file);
    return json({ file });
  }
  const detail = new RegExp(`^/api/projects/${PROJECT_ID}/files/([\\w-]+)$`).exec(path);
  if (method === "GET" && detail) {
    const rec = storedFiles.find((f) => f.id === detail[1]);
    if (!rec) return json({}, 404);
    return json({ file: { id: rec.id, name: rec.name, media_type: rec.media_type, content_chars: rec.content_chars, content: rec.content } });
  }
  return json({}, 404);
}

// ── one util-menu.js execution against a fresh fake DOM ─────────────────────
function spawnSession(windowState = {}) {
  const root = new N("html");
  const byId = {};
  const mk = (tag, id, cls) => {
    const node = new N(tag);
    if (id) { node.id = id; byId[id] = node; }
    if (cls) node.className = cls;
    return node;
  };

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

  [["speech", "축사·인사말"], ["sns", "SNS 홍보"], ["meeting", "회의정리·책 제작"], ["pdfmd", "PDF → Markdown"]].forEach(([key, label]) => {
    const tab = mk("button", null, "util-tab" + (key === "speech" ? " active" : ""));
    tab.dataset.util = key;
    tab.textContent = label;
    utilView.appendChild(tab);
  });

  // The speech form is shipped markup in index.html, so the harness builds the
  // same field set the browser would hand to `new FormData(form)`.
  const speechPanel = mk("div", "utilSpeechPanel", "util-panel");
  const speechForm = mk("form", "utilSpeechForm", "util-form");
  const speechFields = [
    ["event", "input"], ["date", "input"], ["place", "input"], ["nature", "input"],
    ["audience", "input"], ["author", "input"], ["message", "textarea"],
    ["emphasis", "textarea"], ["length", "input"], ["tone", "input"], ["style", "textarea"],
  ];
  speechFields.forEach(([name, tag]) => {
    const field = mk(tag, null, null);
    field.name = name;
    if (name === "length") field.value = "medium";
    if (name === "tone") field.value = "formal";
    speechForm.appendChild(field);
  });
  const speechActions = mk("div", null, "util-form-actions");
  const speechSubmit = mk("button", null, "util-generate");
  speechSubmit.type = "submit";
  speechSubmit.textContent = "초안 생성";
  const speechSave = mk("button", "utilSpeechSave", "util-save");
  speechSave.type = "button";
  speechSave.textContent = "저장";
  speechActions.append(speechSubmit, speechSave);
  speechForm.appendChild(speechActions);
  speechPanel.appendChild(speechForm);

  const speechResult = mk("div", "utilSpeechResult");
  speechResult.hidden = true;
  const speechOutput = mk("textarea", "utilSpeechOutput");
  speechResult.appendChild(speechOutput);
  const speechCopy = mk("button", "utilSpeechCopy");
  speechCopy.type = "button";
  const speechDownload = mk("button", "utilSpeechDownload");
  speechDownload.type = "button";
  const speechResultActions = mk("div", null, "util-actions");
  speechResultActions.append(speechCopy, speechDownload);
  speechResult.appendChild(speechResultActions);
  speechPanel.appendChild(speechResult);
  utilView.appendChild(speechPanel);

  const snsPanel = mk("div", "utilSnsPanel", "util-panel");
  snsPanel.hidden = true;
  utilView.appendChild(snsPanel);
  const meetingPanel = mk("div", "utilMeetingPanel", "util-panel");
  meetingPanel.hidden = true;
  utilView.appendChild(meetingPanel);
  const pdfmdPanel = mk("div", "utilPdfmdPanel", "util-panel");
  pdfmdPanel.hidden = true;
  utilView.appendChild(pdfmdPanel);

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
    Blob: function Blob() {},
    URL: { createObjectURL: () => "blob:fixture", revokeObjectURL() {} },
    FormData: FakeFormData,
  };
  vm.createContext(ctx);
  vm.runInContext(fs.readFileSync(utilMenuPath, "utf8"), ctx, { filename: "util-menu.js" });
  return { root, utilView, navBtn, byId };
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const text = (value) => String((value && value.textContent) || "");

// Panels the module builds itself are created through document.createElement,
// so the id map only knows the shipped skeleton; resolve against the live tree.
function find(session, id) {
  const known = session.byId[id];
  if (known) return known;
  const found = session.root._descendants().find((n) => n.id === id) || null;
  if (!found) throw new Error("element missing: #" + id);
  return found;
}
const labels = (nodes) => nodes.map((n) => text(n).trim());

async function openTool(session, key) {
  await session.navBtn.dispatch("click");
  const tab = session.utilView.querySelectorAll(".util-tab").find((t) => t.dataset.util === key);
  if (!tab) throw new Error("util tab missing: " + key);
  await tab.dispatch("click");
  await sleep(20);
}

function storedByName(name) {
  return storedFiles.filter((f) => f.name === name);
}

function endpointSet() {
  return Array.from(new Set(requests.map((r) => r.method + " " + r.url))).sort();
}

// ── scenarios ──────────────────────────────────────────────────────────────
const SCENARIOS = {
  async tier() {
    const windowState = {};
    const session = spawnSession(windowState);
    await openTool(session, "speech");
    const form = find(session, "utilSpeechForm");
    form.querySelector("[name=event]").value = "등급 전달 검증";
    const tiers = [];
    const cases = [
      ...["free", "plus", "pro", "max", "admin"].map((value) => [value, value]),
      ["absent", undefined], ["missing_getter", undefined],
      ["unknown", "other"], ["uppercase", "MAX"], ["null", null],
      ["number", 3], ["undefined", undefined],
    ];
    for (const [name, value] of cases) {
      if (name === "absent") delete windowState.PadiemTierSelection;
      else if (name === "missing_getter") windowState.PadiemTierSelection = {};
      else windowState.PadiemTierSelection = { get: () => value };
      const before = chatPayloads.length;
      await form.dispatch("submit");
      await sleep(20);
      tiers.push({ name, payload: chatPayloads[before], calls: chatPayloads.length - before,
        output: find(session, "utilSpeechOutput").value });
    }
    const errors = [];
    windowState.PadiemTierSelection = { get: () => "admin" };
    for (const [name, response] of [
      ["server_message", json({ error: { message: "관리자 인증을 확인해 주세요." } }, 403)],
      ["no_message", json({ error: { code: "unavailable" } }, 502)],
      ["non_string", json({ error: { message: { unsafe: true } } }, 403)],
      ["not_json", { ok: false, status: 503, json: async () => { throw new Error("not JSON"); } }],
    ]) {
      chatResponseOverride = response;
      const before = chatPayloads.length;
      await form.dispatch("submit");
      await sleep(20);
      errors.push({ name, output: find(session, "utilSpeechOutput").value,
        calls: chatPayloads.length - before });
    }
    chatResponseOverride = null;
    return { tiers, errors, pageErrors };
  },
  async speech() {
    const session = spawnSession();
    await openTool(session, "speech");
    const form = find(session, "utilSpeechForm");
    const field = (name) => form.querySelector(`[name=${name}]`);
    field("event").value = "제78주년 광복절 기념식";
    field("date").value = "2026-08-15";
    field("place").value = "시청 대강당";
    field("nature").value = "기념식";
    field("audience").value = "지역 주민과 보훈 가족";
    field("author").value = "국회의원 임미란";
    field("message").value = "감사의 마음과 다음 세대의 책임";
    field("emphasis").value = "독립운동가 후손";
    field("length").value = "long";
    field("tone").value = "warm";
    field("style").value = "존경하는 지역민 여러분, 오늘 이 자리는…";

    await form.dispatch("submit");
    await sleep(20);
    const prompt = chatPayloads.length ? chatPayloads[chatPayloads.length - 1].messages[0].content : "";
    const generated = find(session, "utilSpeechOutput").value;

    // The user edits the generated draft, then saves it.
    const edited = generated + "\n\n[편집: 마무리 인사 추가]";
    find(session, "utilSpeechOutput").value = edited;
    await find(session, "utilSpeechSave").dispatch("click");
    await sleep(30);

    const speechFiles = storedFiles.filter((f) => (f.name || "").endsWith(".txt"));
    const savedFile = speechFiles[speechFiles.length - 1] || null;
    const savedListButtons = session.root.querySelectorAll("#utilSpeechSaved button");
    let reopened = null;
    if (savedListButtons.length) {
      await savedListButtons[0].dispatch("click");
      await sleep(20);
      reopened = find(session, "utilSpeechOutput").value;
    }

    // #5731: a stored speech can be picked as the style reference. The saved
    // list exposes one 참고로 선택 action per row; picking one fills the style
    // sample textarea with the stored body, and the next generation's prompt
    // carries it inside the sample fence.
    const refButton = session.root.querySelectorAll("#utilSpeechSaved .util-speech-use-ref")[0] || null;
    let refSelected = null;
    let refPrompt = null;
    if (refButton) {
      const styleField = form.querySelector("[name=style]");
      styleField.value = "";
      await refButton.dispatch("click");
      await sleep(20);
      refSelected = styleField.value;
      await form.dispatch("submit");
      await sleep(20);
      refPrompt = chatPayloads.length ? chatPayloads[chatPayloads.length - 1].messages[0].content : "";
    }

    // #5731: re-entering the tool later must still list the stored speeches —
    // a fresh session opening speech sees the same saved list without saving
    // anything first.
    const reentry = spawnSession();
    await openTool(reentry, "speech");
    await sleep(30);
    const reentryListButtons = reentry.root.querySelectorAll("#utilSpeechSaved button");

    return {
      prompt,
      generated,
      edited,
      savedName: savedFile ? savedFile.name : null,
      savedBody: savedFile ? savedFile.content : null,
      savedListLabels: labels(savedListButtons),
      reopened,
      refSelected,
      refSelectedMatchesSaved: refSelected === (savedFile ? savedFile.content : null),
      refPromptCarriesSample: refPrompt ? refPrompt.indexOf("아래는 사용자의 기존 축사/인사말 샘플입니다") >= 0 && refPrompt.indexOf(refSelected || "") >= 0 : null,
      reentryListCount: reentryListButtons.length,
      reentryListLabels: labels(reentryListButtons),
      chatPayload: chatPayloads[0] || null,
      endpoints: endpointSet(),
      alerts,
      pageErrors,
    };
  },

  async sns() {
    const session = spawnSession();
    await openTool(session, "sns");
    const form = find(session, "utilSnsForm");
    const field = (name) => form.querySelector(`[name=${name}]`);
    field("event").value = "마을 한마음 축제";
    field("whenwhere").value = "10월 3일 · 항구 광장";
    field("content").value = "주민 노래자랑과 먹거리 장터가 열렸습니다.";
    field("memo").value = "사진은 마을 신문에도 씁니다.";
    field("audience").value = "지역 주민";
    field("tone").value = "casual";

    await form.dispatch("submit");
    await sleep(20);
    const blogPrompt = chatPayloads[chatPayloads.length - 1].messages[0].content;
    const blogOutput = find(session, "utilSnsOutput").value;
    const blogTitle = text(session.root.querySelector("#utilSnsResult h3"));

    // Edit, save the blog draft, then switch platform: the draft must survive.
    const edited = blogOutput + "\n\n#마을축제 #임미란";
    find(session, "utilSnsOutput").value = edited;
    await find(session, "utilSnsSave").dispatch("click");
    await sleep(30);
    const savedFile = storedFiles.filter((f) => (f.name || "").endsWith(".txt")).pop() || null;

    const fbTab = form.querySelectorAll(".util-sns-tab").find((t) => t.dataset.platform === "facebook");
    await fbTab.dispatch("click");
    const afterSwitch = {
      event: field("event").value,
      output: find(session, "utilSnsOutput").value,
      title: text(session.root.querySelector("#utilSnsResult h3")),
    };
    await form.dispatch("submit");
    await sleep(20);
    const fbPrompt = chatPayloads[chatPayloads.length - 1].messages[0].content;

    const igTab = form.querySelectorAll(".util-sns-tab").find((t) => t.dataset.platform === "instagram");
    await igTab.dispatch("click");
    await form.dispatch("submit");
    await sleep(20);
    const igPrompt = chatPayloads[chatPayloads.length - 1].messages[0].content;

    return {
      blogPrompt,
      fbPrompt,
      igPrompt,
      blogTitle,
      blogOutput,
      edited,
      afterSwitch,
      savedName: savedFile ? savedFile.name : null,
      savedBody: savedFile ? savedFile.content : null,
      platformTitles: [blogTitle, afterSwitch.title],
      endpoints: endpointSet(),
      alerts,
      pageErrors,
    };
  },

  async meeting() {
    const session = spawnSession();
    await openTool(session, "meeting");
    const form = find(session, "utilMeetingForm");
    const field = (name) => form.querySelector(`[name=${name}]`);
    field("title").value = "10월 주민 민원 회의";
    field("when").value = "2026-10-24T10:00";
    field("attendees").value = "비서실장, 지역 담당";
    field("content").value = "항구 도로 보수 일정과 버스 노선 조정을 논의했습니다.";

    await form.dispatch("submit");
    await sleep(20);
    const prompt = chatPayloads[chatPayloads.length - 1].messages[0].content;
    const generated = find(session, "utilMeetingOutput").value;

    const edited = generated + "\n\n[편집: 후속 일정 확정]";
    find(session, "utilMeetingOutput").value = edited;
    await find(session, "utilMeetingSave").dispatch("click");
    await sleep(40);

    const archive = find(session, "utilMeetingArchive");
    const archiveButtons = archive.querySelectorAll("button");
    const fileButton = archiveButtons.find((b) => text(b).includes(".txt")) || null;
    let reopened = null;
    if (fileButton) {
      // Clear the editor first so a "restore" cannot be the draft already there.
      find(session, "utilMeetingOutput").value = "";
      await fileButton.dispatch("click");
      await sleep(20);
      reopened = find(session, "utilMeetingOutput").value;
    }

    // 활동집: select the stored record and generate the book draft from it.
    const checks = archive.querySelectorAll(".util-book-check");
    const bookBtn = session.root.querySelector("#utilBookGenerate");
    let bookPrompt = null;
    let bookOutput = null;
    if (checks.length && bookBtn) {
      checks[0].checked = true;
      await bookBtn.dispatch("click");
      await sleep(40);
      bookPrompt = chatPayloads[chatPayloads.length - 1].messages[0].content;
      bookOutput = find(session, "utilBookOutput").value;
    }

    return {
      prompt,
      generated,
      edited,
      savedName: storedFiles.length ? storedFiles[storedFiles.length - 1].name : null,
      savedBody: storedFiles.length ? storedFiles[storedFiles.length - 1].content : null,
      archiveLabels: labels(archiveButtons),
      archiveHasCheckbox: checks.length > 0,
      reopened,
      bookPrompt,
      bookOutput,
      endpoints: endpointSet(),
      alerts,
      pageErrors,
    };
  },

  async shared() {
    const session = spawnSession();
    const perTool = {};
    for (const key of ["speech", "sns", "meeting"]) {
      const before = requests.length;
      await openTool(session, key);
      const form = find(session, key === "speech" ? "utilSpeechForm" : key === "sns" ? "utilSnsForm" : "utilMeetingForm");
      const field = (name) => form.querySelector(`[name=${name}]`);
      if (key === "speech") field("event").value = "공통 계약 검증";
      if (key === "sns") { field("event").value = "공통 계약 검증"; field("content").value = "본문"; }
      if (key === "meeting") { field("title").value = "공통 계약 검증"; field("content").value = "내용"; }
      await form.dispatch("submit");
      await sleep(20);
      perTool[key] = requests.slice(before).map((r) => r.method + " " + r.url);
    }
    return {
      perTool,
      endpoints: endpointSet(),
      chatPayloads,
      credentials: Array.from(new Set(requests.map((r) => r.credentials))),
      projectWrites: storedFiles.length,
      alerts,
      pageErrors,
    };
  },
};

(async () => {
  if (!SCENARIOS[scenario]) throw new Error("unknown scenario: " + scenario);
  const observation = await SCENARIOS[scenario]();
  console.log(JSON.stringify({ ok: true, scenario, observation }));
})().catch((error) => {
  console.log(JSON.stringify({ ok: false, scenario, error: String((error && error.stack) || error), alerts }));
  process.exit(1);
});
