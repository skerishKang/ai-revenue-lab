/* B66 voice lane (#3404) — the real easy-mode.js composer is the only egress.
   Loads the actual easy-mode.js in a vm with a stubbed bridge, captures the host
   object the voice lane is handed, and proves: staging is editable, a send goes
   through the existing inputHandler exactly once, and no second interpreter or
   QuoteCore path exists. No network, no credentials, no provider. */
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const SRC = path.join(__dirname, "..");

const Core = require(path.join(SRC, "quote-core.js"));
const History = require(path.join(SRC, "quote-history.js"));
const FileIntake = require(path.join(SRC, "file-intake.js"));

const TURN_TEXT = "대한건설에 배관 100미터, 미터당 18,000원, 부가세 별도";

const DRAFT = {
  sender: { company: "스킬잔존상사", rep: "스킬대표", bizNo: "000-00-00000", address: "", phone: "", email: "s@example.invalid" },
  recipient: { company: "대한건설", rep: "", bizNo: "", address: "", phone: "", email: "" },
  quoteNo: "Q-1", issueDate: "2026-10-08", validUntil: "2026-11-07",
  items: [{ name: "배관", spec: "", qty: 100, unit: "m", unitPrice: 18000 }],
  memo: "", taxMode: "EXCLUSIVE"
};

function makeElement(id) {
  const classes = new Set();
  const listeners = {};
  return {
    id,
    value: "",
    textContent: "",
    placeholder: "",
    disabled: false,
    hidden: false,
    type: "",
    style: {},
    dataset: {},
    children: [],
    listeners,
    focusCount: 0,
    clickCount: 0,
    get innerHTML() { return this._innerHTML || ""; },
    set innerHTML(value) { this._innerHTML = value; if (value === "") this.children = []; },
    classList: {
      toggle(name, on) { if (on) classes.add(name); else classes.delete(name); },
      add(name) { classes.add(name); },
      remove(name) { classes.delete(name); },
      contains(name) { return classes.has(name); }
    },
    addEventListener(type, handler) { (listeners[type] = listeners[type] || []).push(handler); },
    dispatchEvent() { return true; },
    setAttribute() {},
    removeAttribute() {},
    remove() {},
    before() {},
    appendChild(child) { this.children.push(child); return child; },
    append(...children) { this.children.push(...children); },
    replaceChildren() { this.children = []; },
    scrollIntoView() {},
    focus() { this.focusCount += 1; },
    click() { (listeners.click || []).forEach((handler) => handler({ preventDefault() {} })); this.clickCount += 1; }
  };
}

function makeDocument(ids) {
  const elements = new Map();
  ids.forEach((id) => elements.set(id, makeElement(id)));
  const documentListeners = {};
  return {
    elements,
    getElementById: (id) => elements.get(id) || null,
    createElement: (tag) => makeElement(tag),
    addEventListener(type, handler) { (documentListeners[type] = documentListeners[type] || []).push(handler); },
    dispatchEvent(event) {
      (documentListeners[event.type] || []).forEach((handler) => handler(event));
      return true;
    },
    querySelector: () => null
  };
}

function buildEnv() {
  const interpretCalls = [];
  const voiceInitOptions = [];
  const easySource = fs.readFileSync(path.join(SRC, "easy-mode.js"), "utf8");
  /* Every element easy-mode reaches for, extracted rather than hand-listed, so the
     harness cannot silently drift from the module it is proving. */
  const ids = new Set(["easyVoiceMic", "easyVoiceStatus", "easyVoiceModeToggle",
    "easyVoiceModeReview", "easyVoiceModeAuto", "easyVoiceHint"]);
  const pattern = /\$\(\s*"([A-Za-z0-9_]+)"\s*\)|getElementById\(\s*"([A-Za-z0-9_]+)"\s*\)/g;
  let found = pattern.exec(easySource);
  while (found) {
    ids.add(found[1] || found[2]);
    found = pattern.exec(easySource);
  }
  const doc = makeDocument(Array.from(ids));

  /* Same for the app-bridge surface: any App.<method> easy-mode may call gets a
     stub, so the harness cannot be the reason a test stops exercising real code. */
  const APP_DEFAULTS = {
    getDraft: () => null,
    getHistoryEnvelope: () => null,
    writeHistoryEnvelope: () => null,
    recentListAuthority: () => false,
    listRecentQuotes: () => ({ ok: true, quotes: [] }),
    replaceDraft: (draft) => { appCalls.push(draft); return { ok: true }; },
    toast: () => null
  };
  const appCalls = [];
  const appMethods = new Set(["getDraft", "getHistoryEnvelope", "writeHistoryEnvelope",
    "recentListAuthority", "listRecentQuotes", "replaceDraft", "toast"]);
  const appPattern = /App\.([A-Za-z0-9_]+)/g;
  found = appPattern.exec(easySource);
  while (found) {
    appMethods.add(found[1]);
    found = appPattern.exec(easySource);
  }
  const appBridge = {};
  appMethods.forEach((name) => {
    appBridge[name] = APP_DEFAULTS[name] || (() => null);
  });

  const bridge = {
    readiness: () => ({ ready: true }),
    interpret(text) {
      interpretCalls.push(text);
      return Promise.resolve({ ok: true, draft: DRAFT });
    },
    errorText: () => "오류"
  };

  const sandbox = {
    window: {
      addEventListener() {},
      dispatchEvent() { return true; },
      location: { href: "https://example.invalid/", search: "", origin: "https://example.invalid" },
      history: { state: {}, replaceState() {}, pushState() {} },
      matchMedia: () => ({ matches: false, addEventListener() {}, addListener() {} }),
      requestAnimationFrame: (fn) => setTimeout(fn, 0),
      getComputedStyle: () => ({ getPropertyValue: () => "" })
    },
    document: doc,
    navigator: { language: "ko-KR", userAgent: "node", onLine: true },
    location: sandbox_location(),
    localStorage: makeStorage(),
    sessionStorage: makeStorage(),
    console,
    setTimeout,
    clearTimeout,
    setInterval,
    clearInterval,
    queueMicrotask,
    fetch: () => Promise.reject(new Error("network must not be used")),
    URL,
    Blob: class { constructor(parts) { this.parts = parts; } },
    crypto: { randomUUID: () => "ut-" + Math.random().toString(36).slice(2, 10) },
    QuoteCore: Core,
    QuoteHistory: History,
    B66FileIntake: FileIntake,
    B66QuoteRuntimeBridge: bridge,
    B66QuoteAppBridge: appBridge,
    QuoteTemplate: require(path.join(SRC, "quote-template.js")),
    QuoteTemplateStore: { list: () => [], save: () => {} },
    QuoteTemplateRenderer: { render: () => "" },
    QuoteTemplateUI: { open: () => {} },
    QuoteTemplateSelection: { read: () => null, write: () => {} },
    QuoteTemplateCandidate: { fromDraft: () => null },
    QuoteTemplateCloner: { clone: () => null },
    QuoteTemplateRegistration: { register: () => ({ ok: true }) },
    QuoteSkill: { create: () => ({}) },
    QuoteSkillStore: { list: () => [], save: () => ({ ok: true }) },
    QuoteSkillCandidate: { fromDraft: () => null },
    QuoteSkillRegistration: { register: () => ({ ok: true }) },
    QuoteSkillUI: { open: () => {} },
    QuoteSkillLiveAnalysis: { analyze: () => null },
    QuoteRegistrationSession: { begin: () => null },
    QuoteAccountScope: null,
    QuoteHistoryServer: { list: () => Promise.resolve({ ok: true, quotes: [] }), save: () => Promise.resolve({ ok: true }) },
    XlsxExport: {},
    CompanyProfileSettings: { open: () => {} },
    B66VoiceInput: {
      init(options) {
        voiceInitOptions.push(options);
        return { controller: null, bindings: null, host: options.host };
      }
    },
    CustomEvent: class { constructor(type, init) { this.type = type; Object.assign(this, init || {}); } },
    Event: class { constructor(type) { this.type = type; } },
    Node: class {},
    Image: class { constructor() { this.onload = null; } },
    encodeURIComponent,
    decodeURIComponent,
    Intl,
    Math,
    Date,
    JSON,
    Object,
    Array,
    String,
    Number,
    Boolean,
    Error,
    TypeError,
    RangeError,
    Promise,
    Map,
    Set,
    WeakMap,
    Symbol,
    RegExp,
    Function,
    parseInt,
    parseFloat,
    isNaN,
    isFinite,
    btoa: (value) => Buffer.from(value, "binary").toString("base64"),
    atob: (value) => Buffer.from(value, "base64").toString("binary"),
    Uint8Array,
    Uint16Array,
    Int16Array,
    Float32Array,
    ArrayBuffer,
    TextEncoder,
    TextDecoder
  };
  sandbox.globalThis = sandbox;
  sandbox.self = sandbox.window;
  sandbox.window.window = sandbox.window;
  sandbox.window.document = doc;
  /* easy-mode.js resolves its collaborators off `window`, and returns without a
     word if any is missing — so the four it requires must be reachable there. */
  sandbox.window.QuoteCore = Core;
  sandbox.window.QuoteHistory = History;
  sandbox.window.B66FileIntake = FileIntake;
  sandbox.window.B66QuoteAppBridge = sandbox.B66QuoteAppBridge;
  sandbox.window.B66QuoteRuntimeBridge = bridge;
  sandbox.window.B66VoiceInput = sandbox.B66VoiceInput;

  function sandbox_location() {
    return { href: "https://example.invalid/", origin: "https://example.invalid", pathname: "/", search: "", hash: "" };
  }

  function makeStorage() {
    const map = new Map();
    return {
      getItem: (key) => (map.has(key) ? map.get(key) : null),
      setItem: (key, value) => { map.set(key, String(value)); },
      removeItem: (key) => { map.delete(key); },
      clear: () => map.clear()
    };
  }

  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(path.join(SRC, "easy-mode.js"), "utf8"), sandbox, { filename: "easy-mode.js" });

  return {
    sandbox,
    doc,
    bridge,
    easySource,
    interpretCalls,
    appCalls,
    voiceInitOptions,
    composer: doc.elements.get("easyComposer"),
    send: doc.elements.get("easySend"),
    note: () => doc.elements.get("easyComposerNote").textContent
  };
}

async function flush() {
  for (let round = 0; round < 8; round += 1) {
    await new Promise((resolve) => setImmediate(resolve));
  }
}

async function main() {
  const env = buildEnv();
  assert.equal(env.voiceInitOptions.length, 1, "easy-mode hands its composer to the voice lane once");
  const host = env.voiceInitOptions[0].host;
  assert.equal(typeof host.stageText, "function");
  assert.equal(typeof host.hasUnsentStagedText, "function");

  /* easy-mode refuses to boot without its collaborators, which would leave the
     host missing: prove the guard actually ran rather than assuming it. */
  assert.ok(env.doc.elements.get("easyComposer"), "composer exists");

  /* free-chat mode is what exposes submitComposer to the voice lane */
  env.doc.elements.get("freeChatStarter").click();
  await flush();
  assert.equal(host.canSubmit(), true, "the composer is submit-able in free chat");

  /* MODE A: staged text is editable and nothing is interpreted */
  const staged = host.stageText(TURN_TEXT);
  assert.equal(staged.staged, true);
  assert.equal(env.composer.value, TURN_TEXT, "the transcript lands in the existing input");
  assert.equal(env.interpretCalls.length, 0, "staging alone must not call the interpreter");
  assert.equal(host.hasUnsentStagedText(), true, "an unsent voice transcript is detectable");

  /* user edits it, which returns control to the person */
  env.composer.value = TURN_TEXT + " (직접 수정)";
  assert.equal(host.hasUnsentStagedText(), false, "a manual edit ends the staged claim");

  /* the canonical send path runs exactly once */
  env.composer.value = TURN_TEXT;
  const submitted = host.submitStaged();
  assert.equal(submitted.submitted, true);
  assert.deepEqual(env.interpretCalls, [TURN_TEXT], "the existing bridge received the transcript once");
  assert.equal(env.composer.value, "", "the composer is cleared by the existing path");

  /* busy while the answer is in flight: no auto-send possible */
  assert.equal(host.canSubmit(), false, "input is disabled while B66 works");
  assert.equal(host.submitStaged().submitted, false, "submitStaged cannot force a send while busy");
  await flush();
  assert.equal(env.interpretCalls.length, 1, "the answer completing adds no second call");

  /* the send button itself is the same path the voice lane reuses */
  env.composer.value = "단가 18000원";
  assert.equal(host.canSubmit(), true, "the composer is live again after the answer");
  const before = env.interpretCalls.length;
  env.send.click();
  await flush();
  assert.equal(env.interpretCalls.length, before + 1, "the send button still drives the canonical path");
  assert.equal(env.interpretCalls[env.interpretCalls.length - 1], "단가 18000원");

  /* no new interpreter surface was introduced by the voice lane */
  assert.equal((env.easySource.match(/bridge\.interpret\(/g) || []).length, 1,
    "exactly one interpret call site remains");
  assert.ok(!/voice[\s\S]{0,40}interpret|interpret[\s\S]{0,40}voice/i.test(env.easySource),
    "the voice lane must not gain its own interpretation call");

  console.log("B66_VOICE_EASY_MODE_HOST=PASS");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
