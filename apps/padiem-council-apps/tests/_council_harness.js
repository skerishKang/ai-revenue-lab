// One fake-DOM host for the REAL static/council-app.js.
//
// Same contract as apps/padiem-chat/tests/_5785_util_harness.js: the browser
// module under test is the shipped file, the backend is a recording fake of
// the EXISTING endpoints, and nothing here invents a product behaviour or a
// second API. The assertions live in the Python test modules.
//
// Usage: node _council_harness.js <council-app.js path> <scenario> [builder] [json]
//   scenario = generate | errors | calendar_words | prompt
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
    for (const fn of (this._listeners[type] || []).slice()) await fn.call(this, evt);
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
const storedFiles = [];
let fileIdSeq = 0;
let chatResponseOverride = null;

function json(body, status) {
  return { ok: (status || 200) < 400, status: status || 200, json: async () => body };
}

const stored = (name, textValue) => {
  const file = { id: "f" + (++fileIdSeq), name, media_type: "text/plain", content_chars: String(textValue || "").length };
  storedFiles.push(Object.assign({ text: textValue }, file));
  return file;
};

async function fetch(url, init) {
  const method = (init && init.method) || "GET";
  const options = {
    method,
    url: String(url),
    headers: (init && init.headers) || {},
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
  if (String(url) === "/api/auth/status") return json({ authenticated: true, user: { name: "테스트 사용자" } });
  if (String(url) === "/api/projects") {
    if (method === "GET") return json({ projects: [{ id: "p1", name: "내 프로젝트" }] });
    return json({ project: { id: "p1", name: (body && body.name) || "" } });
  }
  const filesMatch = /^\/api\/projects\/([^/]+)\/files\/?([^/]*)$/.exec(String(url));
  if (filesMatch) {
    if (method === "GET" && !filesMatch[2]) {
      return json({ files: storedFiles.map(({ text, ...meta }) => meta) });
    }
    if (method === "POST") {
      const file = stored((body && body.name) || "무제.txt", (body && body.text) || "");
      return json({ file });
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
  root.append(speechBody, snsBody, meetingBody);
  const badge = mk("span", "councilAuthBadge");
  const note = mk("p", "councilSigninNote");
  root.append(badge, note);

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

    // sns: switch platform then generate
    const snsForm = find(session, "councilSnsForm");
    snsForm.querySelector("[name=event]").value = "주민 정원 사업 설명회";
    snsForm.querySelector("[name=whenwhere]").value = "10월 30일 오후 2시, 구청 소회의실";
    snsForm.querySelector("[name=content]").value = "정원 사업 신청 방법과 지원 금액 안내";
    snsForm.querySelector("[name=audience]").value = "구내 상인";
    const instagramTab = snsForm.querySelectorAll(".council-sns-tab").find((b) => b.dataset.platform === "instagram");
    await instagramTab.dispatch("click");
    const snsCalls = chatPayloads.length;
    await snsForm.dispatch("submit");
    await sleep(20);
    const snsOutput = find(session, "councilSnsOutput").value;
    const snsPrompt = chatPayloads[snsCalls];
    await find(session, "councilSnsSave").dispatch("click");
    await sleep(20);

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
      speech: { prompt: speechPrompt, output: speechOutput },
      sns: { prompt: snsPrompt, output: snsOutput, title: text(find(session, "councilSnsTitle")) },
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
      const { platform, ...fields } = payload;
      return { prompt: api.sns.buildPrompt(toForm(fields), platform) };
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
