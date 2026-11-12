/*
 * #7501 — runs the REAL util-tools.js in a DOM shim and watches the
 * "라이브러리에 저장" path: the pinned project read/create, the POST to the
 * existing project-file route, the request body, and the success/failure copy.
 *
 * argv: util-tools.js util-tools-contract.js util-tools-markdown.js util-manifest.js
 * env:  SCENARIO (JSON)
 */
const fs = require("fs"), vm = require("vm");
const source = fs.readFileSync(process.argv[2], "utf8");
const contractSource = fs.readFileSync(process.argv[3], "utf8");
const markdownSource = fs.readFileSync(process.argv[4], "utf8");
const manifestSource = fs.readFileSync(process.argv[5], "utf8");
const scenario = JSON.parse(process.env.SCENARIO || "{}");
const calls = [];
const requests = [];
let authState = scenario.signedOut ? { authenticated: false } : { authenticated: true };

function El(tag) {
  const node = {
    tagName: (tag || "div").toUpperCase(), id: "", className: "", type: "",
    textContent: "", value: "", rows: 0, required: false, placeholder: "",
    hidden: false, disabled: false, focused: false, noValidate: false,
    children: [], attrs: {}, listeners: {},
    addEventListener(type, fn) { this.listeners[type] = fn; },
    setAttribute(k, v) { this.attrs[k] = v; if (k === "id") this.id = String(v); },
    getAttribute(k) { return Object.prototype.hasOwnProperty.call(this.attrs, k) ? this.attrs[k] : null; },
    appendChild(n) { this.children.push(n); n.parentElement = this; return n; },
    replaceChildren(...ns) { this.children.length = 0; ns.forEach((n) => this.appendChild(n)); },
    focus() { this.focused = true; },
    click() { if (this.listeners.click) this.listeners.click({ target: this }); },
    querySelector(sel) { return find(this, sel); },
    querySelectorAll(sel) { return findAll(this, sel); },
  };
  return node;
}
function walk(el, fn) { if (!el) return; fn(el); (el.children || []).forEach((c) => walk(c, fn)); }
function matches(el, sel) {
  if (!sel) return false;
  if (sel.charAt(0) === ".") return String(el.className).split(/\s+/).indexOf(sel.slice(1)) >= 0;
  if (sel.charAt(0) === "#") return el.id === sel.slice(1);
  const attr = /^\[([a-zA-Z-]+)(?:="([^"]*)")?\]$/.exec(sel);
  if (attr) {
    if (attr[1] === "name") {
      if (!el.name) return false;
      return attr[2] === undefined || el.name === attr[2];
    }
    const value = el.getAttribute(attr[1]);
    if (value === null) return false;
    return attr[2] === undefined || value === attr[2];
  }
  return el.tagName === String(sel).toUpperCase();
}
function find(root, sel) { let out = null; walk(root, (e) => { if (!out && e !== root && matches(e, sel)) out = e; }); return out; }
function findAll(root, sel) { const out = []; walk(root, (e) => { if (e !== root && matches(e, sel)) out.push(e); }); return out; }
function text(root) { let out = ""; walk(root, (e) => { if (typeof e.textContent === "string") out += e.textContent + "\n"; }); return out; }

const loginButton = El("button");
loginButton.id = "loginButton";
loginButton.addEventListener("click", () => calls.push("login-button"));
const createdTags = [];
const document = {
  readyState: "complete",
  documentElement: { lang: scenario.lang || "ko" },
  createElement: (tag) => { createdTags.push(String(tag).toLowerCase()); return El(tag); },
  createTextNode: (value) => { const node = El("#text"); node.textContent = String(value); return node; },
  getElementById: (id) => (id === "loginButton" ? loginButton : null),
  addEventListener: () => {},
};

// Locale table the surface reads (KR/EN); a missing key falls back to the module table.
const LOCALE = {
  ko: {
    "util-library-save": "라이브러리에 저장",
    "util-library-saving": "저장 중…",
    "util-library-saved": "라이브러리에 저장했습니다.",
    "util-library-save-failed": "문서를 저장하지 못했습니다. 잠시 후 다시 시도해 주세요.",
  },
  en: {
    "util-library-save": "Save to library",
    "util-library-saving": "Saving…",
    "util-library-saved": "Saved to your library.",
    "util-library-save-failed": "We couldn’t save the document. Please try again in a moment.",
  },
};

const answer = scenario.answer === undefined ? "초안 본문" : scenario.answer;
const saveSpecs = Array.isArray(scenario.saveResponses) ? scenario.saveResponses.slice() : [];
const saveResponses = saveSpecs.slice();
const storedFiles = [];

function jsonResponse(status, body) {
  return {
    ok: status >= 200 && status < 300,
    status: status,
    headers: { get: () => "application/json" },
    json: () => Promise.resolve(body || {}),
    body: null,
  };
}

function fetchStub(url, init) {
  const method = (init && init.method) || "GET";
  const parsed = init && init.body ? JSON.parse(init.body) : null;
  requests.push({ url: url, method: method, init: init, body: parsed });

  if (url === "/api/chat/stream") return jsonResponse(200, { answer: answer });

  if (url === "/api/projects" && method === "GET") {
    if (scenario.projectsUnavailable) return jsonResponse(503, { error: { code: "unavailable" } });
    const projects = Array.isArray(scenario.projects) ? scenario.projects : [];
    return jsonResponse(200, { projects: projects });
  }
  if (url === "/api/projects" && method === "POST") {
    const created = { id: "proj_created", name: parsed && parsed.name };
    if (scenario.createFails) return jsonResponse(422, { error: { code: "invalid_project" } });
    return jsonResponse(201, { project: created });
  }
  if (/^\/api\/projects\/[^/]+\/files$/.test(url) && method === "POST") {
    const spec = saveResponses.length ? saveResponses.shift() : { status: 201 };
    if (spec.throw) return Promise.reject(new Error("network"));
    if (spec.status === 201 || spec.status === undefined) {
      const file = { id: "file_saved", name: parsed.name, project_id: url.split("/")[3] };
      storedFiles.push(file);
      return jsonResponse(201, { file: file });
    }
    return jsonResponse(spec.status, spec.body || { error: { code: "save_failed" } });
  }
  return jsonResponse(404, { error: { code: "not_found" } });
}

const listeners = {};
const windowObj = {
  fetch: fetchStub,
  addEventListener: (type, fn) => { listeners[type] = fn; },
  PadiemAuthSession: { get: () => authState },
  PadiemTierSelection: { get: () => scenario.tier || "free" },
  PadiemAnswerCopy: { copyText: () => Promise.resolve(true) },
  __padiemLocale: {
    text: (key) => {
      const table = LOCALE[scenario.lang || "ko"] || LOCALE.ko;
      if (Object.prototype.hasOwnProperty.call(table, key)) return table[key];
      if (key === "timeout") return "응답 시간 초과";
      if (key === "connection-error") return "연결 오류";
      if (key === "claw-error-auth-needed") return "로그인이 필요합니다. 다시 로그인한 뒤 시도해 주세요.";
      if (key === "claw-error-rate-limited") return "요청이 잠시 많습니다. 잠시 후 다시 시도해 주세요.";
      if (key === "claw-error-generic") return "실행 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.";
      return key;
    },
  },
};
const sandbox = {
  document: document, window: windowObj, console: console,
  setTimeout: () => 0, clearTimeout: () => {},
};
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
vm.runInContext(manifestSource, sandbox, { filename: "util-manifest.js" });
vm.runInContext(markdownSource, sandbox, { filename: "util-tools-markdown.js" });
vm.runInContext(contractSource, sandbox, { filename: "util-tools-contract.js" });
vm.runInContext(source, sandbox, { filename: "util-tools.js" });

const api = windowObj.PadiemUtilTools;
const result = { ok: true, checks: {}, requests: requests, stored: storedFiles, text: "" };
function check(name, cond) { result.checks[name] = Boolean(cond); if (!cond) result.ok = false; }
function tick() { return new Promise((resolve) => setImmediate(resolve)); }

(async () => {
  check("api", Boolean(api) && api.TOOL_KEYS.length === 3);
  const tool = scenario.tool || "speech";

  if (scenario.signedOut) {
    const host = El("div"); host.className = "util-tool-body";
    check("mount_signed_out", api.mount(tool, host) === true);
    check("signed_out_gate", Boolean(find(host, ".util-gate")));
    check("signed_out_has_no_save_button", !find(host, "[data-util-save-library]"));
    check("signed_out_makes_no_request", requests.length === 0);
    result.text = text(host);
    console.log(JSON.stringify(result));
    return;
  }

  const host = El("div"); host.className = "util-tool-body";
  check("mount", api.mount(tool, host) === true);
  const form = find(host, ".util-form");
  check("form_present", Boolean(form));

  const saveBtn = find(host, "[data-util-save-library]");
  check("save_button_present", Boolean(saveBtn) && saveBtn.type === "button");
  check("save_label_is_locale_copy",
    Boolean(saveBtn) && saveBtn.textContent === (LOCALE[scenario.lang || "ko"]["util-library-save"]));
  // Empty result: the button exists but is inert, like copy/regenerate.
  check("save_disabled_before_result", Boolean(saveBtn) && saveBtn.disabled === true);
  saveBtn.click();
  await tick();
  check("save_before_result_makes_no_request", requests.length === 0);

  findAll(host, "[name]").forEach((input) => {
    if (input.name === "event") input.value = "제78주년 광복절 기념식";
    if (input.name === "title") input.value = "10월 주민 민원 회의";
    if (input.name === "content") input.value = "정원 사업 신청 방법과 지원 금액을 안내했다.";
  });
  form.listeners.submit({ preventDefault() {} });
  await tick();
  const generationCalls = requests.filter((r) => r.url === "/api/chat/stream").length;
  check("generated", generationCalls === 1);
  check("save_enabled_after_result", saveBtn.disabled === false);

  saveBtn.click();
  await tick(); await tick(); await tick();

  const projectReads = requests.filter((r) => r.url === "/api/projects" && r.method === "GET");
  const projectCreates = requests.filter((r) => r.url === "/api/projects" && r.method === "POST");
  const saves = requests.filter((r) => /^\/api\/projects\/[^/]+\/files$/.test(r.url) && r.method === "POST");
  check("library_project_read", projectReads.length === 1);
  check("library_project_read_credentials", projectReads.length === 1
    && projectReads[0].init && projectReads[0].init.credentials === "include");
  if (scenario.projects && scenario.projects.some((p) => p && p.name === "유틸")) {
    check("reuses_the_pinned_project", projectCreates.length === 0
      && saves.length >= 1 && saves.every((r) => r.url === "/api/projects/proj_pinned/files"));
  } else if (scenario.projectsUnavailable || scenario.createFails) {
    check("no_save_without_a_project", saves.length === 0);
    check("project_failure_is_reported", /저장하지 못했습니다\.|couldn’t save/.test(text(host)));
  } else {
    check("creates_the_pinned_project", projectCreates.length === 1
      && projectCreates[0].body && projectCreates[0].body.name === "유틸");
    check("saves_into_the_created_project", saves.length === 1
      && saves[0].url === "/api/projects/proj_created/files");
  }

  if (saves.length) {
    const sent = saves[0];
    check("save_posts_with_credentials", sent.init && sent.init.credentials === "include");
    check("save_inline_is_json", sent.init && sent.init.headers
      && sent.init.headers["Content-Type"] === "application/json");
    check("save_body_media_type", sent.body && sent.body.media_type === "text/plain");
    check("save_body_is_the_result", sent.body && sent.body.text === answer);
    check("save_body_names_the_tool", sent.body && sent.body.doc_kind === tool);
    const name = (sent.body && sent.body.name) || "";
    check("save_name_is_a_txt_file", /\.txt$/.test(name));
    check("save_name_has_the_date", / \d{4}-\d{2}-\d{2}\.txt$/.test(name));
    if (scenario.expectNameIncludes) {
      check("save_name_includes_the_tool_label", name.indexOf(scenario.expectNameIncludes) === 0);
    }
  }

  const lastSave = saveSpecs.length ? saveSpecs[saveSpecs.length - 1] : { status: 201 };
  if (lastSave && (lastSave.status === undefined || lastSave.status === 201) && saves.length) {
    check("saved_notice", text(host).indexOf(LOCALE[scenario.lang || "ko"]["util-library-saved"]) >= 0);
  }
  if (scenario.expectFailure) {
    check("failure_uses_the_existing_sentence",
      text(host).indexOf(LOCALE[scenario.lang || "ko"]["util-library-save-failed"]) >= 0);
    check("failure_is_not_a_status_token", !/\b(4\d\d|5\d\d)\b/.test(text(host)));
    check("failure_shows_no_success_copy",
      text(host).indexOf(LOCALE[scenario.lang || "ko"]["util-library-saved"]) < 0);
    check("save_retry_stays_available", saveBtn.disabled === false);
  }
  if (scenario.expectConflictRetry) {
    const all = requests.filter((r) => /^\/api\/projects\/[^/]+\/files$/.test(r.url));
    check("conflict_retries_with_a_new_name", all.length === 2
      && / \(2\)\.txt$/.test((all[1].body && all[1].body.name) || ""));
    check("conflict_never_overwrites", all.every((r) => r.method === "POST"));
  }
  result.text = text(host);
  console.log(JSON.stringify(result));
})();
