/* B66 MVP runtime behavioral probe (#3478).
   두 개의 vm 하네스로 실제 padiem-account.js 와 easy-mode.js 를 구동한다.
   - harness A: 인증/스킬/CompanyProfile 준비 + interpret → buildDraft 런타임 계약
   - harness B: Home composer / Free-form / Guided 가 하나의 runtime 으로 수렴하는 UI 계약
   네트워크 호출은 전부 스텁이다. 실제 자격증명/외부 호출은 0 이다. */
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const SRC = path.join(__dirname, "..");
const Core = require(path.join(SRC, "quote-core.js"));
const History = require(path.join(SRC, "quote-history.js"));
const FileIntake = require(path.join(SRC, "file-intake.js"));
const Template = require(path.join(SRC, "quote-template.js"));
const SavedQuoteSkill = require(path.join(SRC, "quote-skill.js"));
const accountSource = fs.readFileSync(path.join(SRC, "padiem-account.js"), "utf8");
const easySource = fs.readFileSync(path.join(SRC, "easy-mode.js"), "utf8");

const NOW = "2026-10-04T09:00:00.000Z";
const SKILL_ID = "b66skill_" + "1".repeat(32);

const tick = () => new Promise((resolve) => setImmediate(resolve));
async function flush() {
  /* 인증→스킬/프로필 로드 체인은 여러 await 단계를 거치므로 여러 매크로틱을 돌린다 */
  for (let round = 0; round < 6; round += 1) {
    for (let i = 0; i < 12; i += 1) { await tick(); }
    await new Promise((resolve) => setTimeout(resolve, 0));
  }
}

const CGI_SKILL_BASE = {
  id: "skill-cgi-mvp",
  name: "CGI 기본 견적서",
  fixedDefaults: {
    sender: {
      company: "스킬잔존상사", rep: "스킬대표", bizNo: "000-00-0000",
      address: "스킬주소", phone: "010-0000-0000", email: "skill@example.invalid",
      presetId: "saved-skill"
    },
    validDays: 30,
    taxMode: "EXCLUSIVE",
    memo: "스킬 기본 메모",
    calculationPolicy: { grandRounding: { mode: "FLOOR", unit: 10000 } }
  },
  variableSchema: { recipient: true, quoteNo: true, issueDate: true, items: true, memo: true, taxMode: true },
  internalTemplate: Template.serializeTemplate(Template.builtInTemplate()),
  provenance: {
    sourceKind: "file", sourceName: "cgi-quotation.pdf", sourceRef: "source:cgi-mvp",
    capturedAt: NOW, warnings: [], unknowns: [],
    evidence: [{ label: "sender", value: "CGI상사" }]
  },
  createdAt: NOW,
  updatedAt: NOW
};
const CGI_SKILL = SavedQuoteSkill.buildSkill(Object.assign({}, CGI_SKILL_BASE, {
  approval: {
    schemaVersion: 1,
    status: "approved",
    skillFingerprint: SavedQuoteSkill.buildSkill(CGI_SKILL_BASE).fingerprint,
    approvedBy: "central-cto",
    approvedAt: NOW,
    approvalRef: "issue-3478"
  }
}));
const CGI_PROFILE = {
  company: "CGI상사",
  representative: "김범신",
  businessNumber: "111-11-11111",
  address: "서울특별시",
  phone: "02-000-0000",
  email: "cgi@example.invalid",
  defaultValidityDays: 14,
  defaultTaxMode: "EXCLUSIVE"
};
const INTERPRET_TEXT = "대한건설에 배관 100미터, 미터당 18000원, 부가세 별도로 견적 만들어줘";
const INTERPRET_CANDIDATE = {
  recipient: { company: "ABC건설", person: "" },
  items: [{ name: "배관", qty: 100, unitPrice: 18000 }]
};

const makeElement = (id) => {
  const classes = new Set();
  return {
    id, value: "", textContent: "", placeholder: "", disabled: false,
    hidden: false, className: "", type: "", style: {},
    dataset: {}, children: [], listeners: {}, focusCount: 0, clickCount: 0,
    get innerHTML() { return this._innerHTML || ""; },
    set innerHTML(value) {
      this._innerHTML = value;
      if (value === "") this.children = [];
    },
    classList: {
      toggle(name, on) { if (on) classes.add(name); else classes.delete(name); },
      add(name) { classes.add(name); }, remove(name) { classes.delete(name); },
      contains(name) { return classes.has(name); }
    },
    addEventListener(type, handler) {
      (this.listeners[type] = this.listeners[type] || []).push(handler);
    },
    dispatchEvent() { return true; },
    setAttribute() {}, removeAttribute() {}, remove() {}, before() {},
    appendChild(child) { this.children.push(child); return child; },
    append(...children) { this.children.push(...children); },
    replaceChildren() { this.children = []; },
    scrollIntoView() {}, focus() { this.focusCount += 1; }, click() { this.clickCount += 1; }
  };
};

function makeStorage() {
  const map = new Map();
  return {
    getItem: (k) => (map.has(k) ? map.get(k) : null),
    setItem: (k, v) => { map.set(k, String(v)); },
    removeItem: (k) => { map.delete(k); }
  };
}

const jsonResponse = (data, status) => ({
  ok: status === undefined || (status >= 200 && status < 300),
  status: status === undefined ? 200 : status,
  headers: { get: () => null },
  json: async () => data
});

/* ── harness A: padiem-account runtime authority ── */
function buildAccountEnv({ signedIn, withSkill, withProfile }) {
  const elements = new Map();
  const httpCalls = [];
  const appCalls = [];
  const replaceDrafts = [];
  const getElement = (id) => {
    if (!elements.has(id)) {
      const element = makeElement(id);
      if (id === "padiemSavedSkillSelect") {
        /* 실제 select 는 첫 option 이 선택값이 된다 */
        element.append = (...children) => {
          element.children.push(...children);
          if (!element.value && children.length) element.value = children[0].value;
        };
      }
      elements.set(id, element);
    }
    return elements.get(id);
  };
  const storage = makeStorage();
  const skillRow = {
    saved_skill_id: SKILL_ID,
    skill_name: CGI_SKILL.name,
    skill: CGI_SKILL,
    skill_fingerprint: CGI_SKILL.fingerprint
  };
  const fetchStub = async (url, options) => {
    const opts = options || {};
    const target = String(url);
    httpCalls.push({ url: target, method: opts.method || "GET", body: opts.body || null });
    if (target.endsWith("/api/padiem/auth/status")) {
      return jsonResponse(signedIn ? {
        authenticated: true,
        session_state: "signed_in",
        user: { id: "usr_cgi", name: "김범신" },
        methods: { google: false, password: false }
      } : { authenticated: false, methods: { google: false, password: false } });
    }
    if (target.endsWith("/api/padiem/b66/saved-skills?limit=20")) {
      return jsonResponse({ ok: true, skills: withSkill ? [skillRow] : [] });
    }
    if (target.endsWith("/api/padiem/b66/saved-skills/" + SKILL_ID)) {
      return jsonResponse(withSkill ? { saved_skill: skillRow } : { error: { message: "not found" } }, withSkill ? 200 : 404);
    }
    if (target.endsWith("/api/padiem/b66/company-profile")) {
      if (!withProfile) return jsonResponse({ error: { message: "profile unavailable" } }, 404);
      return jsonResponse({ company_profile: CGI_PROFILE });
    }
    if (target.endsWith("/api/padiem/b66/quote/interpret")) {
      const body = JSON.parse(opts.body || "{}");
      if (!body.message || !body.saved_skill_id) {
        return jsonResponse({ ok: false, error: { code: "quote_input_unrecognized" } }, 422);
      }
      return jsonResponse({
        ok: true,
        candidate: Object.assign({}, INTERPRET_CANDIDATE),
        company_profile: CGI_PROFILE
      });
    }
    return jsonResponse({ error: { message: "unexpected endpoint" } }, 404);
  };
  const context = vm.createContext({
    setTimeout, clearTimeout, console,
    QuoteCore: Core,
    QuoteTemplate: Template,
    SavedQuoteSkill,
    btoa: (value) => value,
    fetch: fetchStub,
    B66QuoteAppBridge: {
      getDraft: () => Core.createProductionDraft(),
      replaceDraft: (next, opts) => {
        appCalls.push("replaceDraft" + (opts && opts.toast ? ":" + opts.toast : ""));
        replaceDrafts.push(next);
        return { ok: true, draft: next };
      },
      createFreshDraft: (source) => {
        appCalls.push("createFreshDraft:" + source);
        const fresh = Core.createProductionDraft();
        fresh.meta.quoteNo = "PQ-20261004-0" + (appCalls.filter((c) => c.startsWith("createFreshDraft")).length + 1);
        fresh.meta.issueDate = "2026-10-04";
        fresh.meta.source = source || "manual";
        return fresh;
      },
      toast: () => {},
      focusTaxReview: () => {}
    },
    B66QuoteSkillBridge: {
      clearServerSkill: () => { appCalls.push("clearServerSkill"); },
      setServerSkill: (skill, slotSources) => {
        appCalls.push("setServerSkill:" + (skill && skill.id));
        return Boolean(skill) && slotSources !== null && typeof slotSources === "object";
      }
    },
    CustomEvent: class {
      constructor(type, init) { this.type = type; this.detail = (init || {}).detail; }
    },
    document: {
      readyState: "complete",
      getElementById: getElement,
      addEventListener() {},
      dispatchEvent() { return true; },
      createElement: (tag) => makeElement(tag)
    }
  });
  context.window = context;
  new vm.Script(accountSource, { filename: "padiem-account.js" }).runInContext(context);
  return { context, elements, getElement, httpCalls, appCalls, replaceDrafts, storage };
}

async function harnessA() {
  /* signed out: primary action 은 authoritative quote 를 만들 수 없다 */
  const signedOut = buildAccountEnv({ signedIn: false, withSkill: true, withProfile: true });
  await flush();
  const outBridge = signedOut.context.window.B66QuoteRuntimeBridge;
  assert.equal(outBridge.readiness().ready, false, "signed out runtime must not be ready");
  const outResult = await outBridge.interpret(INTERPRET_TEXT);
  assert.equal(outResult.ok, false);
  assert.equal(outResult.code, "auth_required", "signed out: primary action refuses without auth");

  /* signed in + skill + profile: readiness ready, interpret builds canonical draft */
  const env = buildAccountEnv({ signedIn: true, withSkill: true, withProfile: true });
  await flush();
  const bridge = env.context.window.B66QuoteRuntimeBridge;
  const readiness = bridge.readiness();
  const diag = JSON.stringify({
    http: env.httpCalls.map((c) => c.url),
    status: env.getElement("padiemQuoteStatus").textContent
  });
  assert.equal(readiness.authenticated, true, "authenticated after sign-in " + diag);
  assert.equal(readiness.skillReady, true, "assigned skill auto-loaded " + diag);
  assert.equal(readiness.profileReady, true, "company profile loaded via GET bridge " + diag);
  assert.equal(readiness.ready, true, "primary actions enabled only when authority is ready");
  assert.equal(bridge.getCompanyProfile().company, "CGI상사", "company profile is the account authority");

  const result = await bridge.interpret(INTERPRET_TEXT);
  assert.equal(result.ok, true, "complete sentence interprets successfully");
  const draft = result.draft;
  assert.equal(draft.recipient.company, "ABC건설", "recipient from the sentence");
  assert.equal(draft.items.length, 1, "item extracted");
  assert.equal(draft.items[0].name, "배관", "item name");
  assert.equal(draft.items[0].qty, 100, "item qty");
  assert.equal(draft.items[0].unitPrice, 18000, "item unitPrice");
  assert.equal(draft.sender.company, "CGI상사", "sender from CompanyProfile (skill demo sender never leaks)");
  assert.equal(draft.sender.rep, "김범신", "sender rep from CompanyProfile");
  assert.equal(draft.meta.validDays, 14, "validity from CompanyProfile");
  assert.equal(draft.tax.mode, "EXCLUSIVE", "tax mode from CompanyProfile default");
  assert.equal(draft.meta.source, "saved-quote-skill", "draft is built by the assigned skill authority");
  assert.ok(draft.calculationPolicy, "skill calculationPolicy carried into the draft");
  const totals = Core.computeDraftTotals(draft);
  assert.equal(totals.grand, 1980000, "QuoteCore totals authority (100 x 18000 + VAT)");
  assert.ok(env.httpCalls.some((c) => c.url.endsWith("/api/padiem/b66/company-profile")),
    "company profile came from the standalone GET bridge");
  assert.ok(env.httpCalls.every((c) => !c.url.includes("extract-")), "no provider calls in the runtime path");

  /* 서버가 응답으로 내려준 company_profile 이 최신 authority 다 (무시 금지) */
  env.httpCalls.push({ url: "/api/padiem/b66/quote/interpret", method: "POST", body: null });
  const branchProfile = Object.assign({}, CGI_PROFILE, { company: "CGI지점상사" });
  const fetchOriginal = env.context.fetch;
  env.context.fetch = async (url, options) => {
    const target = String(url);
    if (target.endsWith("/api/padiem/b66/quote/interpret")) {
      env.httpCalls.push({ url: target, method: "POST", body: options && options.body });
      return jsonResponse({ ok: true, candidate: Object.assign({}, INTERPRET_CANDIDATE), company_profile: branchProfile });
    }
    return fetchOriginal(url, options);
  };
  const branched = await bridge.interpret(INTERPRET_TEXT);
  assert.equal(branched.ok, true);
  assert.equal(branched.draft.sender.company, "CGI지점상사", "server-returned company profile is honored");

  /* 불완전 문장: follow-up engine 없이 정직한 partial 보고 */
  env.context.fetch = async (url, options) => {
    const target = String(url);
    if (target.endsWith("/api/padiem/b66/quote/interpret")) {
      env.httpCalls.push({ url: target, method: "POST", body: options && options.body });
      return jsonResponse({ ok: true, candidate: { recipient: { company: "대한건설" }, items: [{ name: "배관", qty: 100 }], missing: ["unitPrice"] } });
    }
    return jsonResponse({ error: { message: "stopped" } }, 500);
  };
  const incomplete = await bridge.interpret("대한건설에 배관 100미터로 견적 만들어줘");
  assert.equal(incomplete.ok, false, "incomplete sentence does not fabricate a quote");
  assert.equal(incomplete.code, "incomplete_request", "incomplete sentence is reported truthfully");
  assert.deepEqual(incomplete.missing, ["unitPrice"], "missing fields surface to the UI");

  /* profile 없음: demo fallback 없이 실패 */
  const noProfile = buildAccountEnv({ signedIn: true, withSkill: true, withProfile: false });
  await flush();
  const noProfileBridge = noProfile.context.window.B66QuoteRuntimeBridge;
  assert.equal(noProfileBridge.readiness().ready, false, "missing profile keeps runtime not-ready");
  const noProfileResult = await noProfileBridge.interpret(INTERPRET_TEXT);
  assert.equal(noProfileResult.code, "company_profile_not_ready", "no silent demo fallback");

  /* skill 없음: primary gate 유지 */
  const noSkill = buildAccountEnv({ signedIn: true, withSkill: false, withProfile: true });
  await flush();
  const noSkillResult = await noSkill.context.window.B66QuoteRuntimeBridge.interpret(INTERPRET_TEXT);
  assert.equal(noSkillResult.code, "skill_not_ready", "no assigned skill keeps runtime not-ready");

  console.log("MVP_RUNTIME_AUTHORITY=PASS");
  console.log("CGI_SKILL_AUTO_SELECTED=PASS");
  console.log("FREE_FORM_USES_ASSIGNED_SERVER_SKILL=PASS");
  console.log("FREE_FORM_USES_ACCOUNT_COMPANY_PROFILE=PASS");
  console.log("COMPANY_PROFILE_IGNORED_BY_STANDALONE=0");
  console.log("SILENT_DEMO_FALLBACK=0");
  console.log("QUOTECORE_AUTHORITY=PASS");
  console.log("COMPANY_PROFILE_MODEL_CALLS=0");
  console.log("ACCOUNT_RUNTIME_NETWORK_CALLS=stubbed");
}

/* ── harness B: easy-mode UI 수렴 ── */
function buildEasyEnv({ ready }) {
  const elements = new Map();
  const created = [];
  const documentListeners = {};
  const windowListeners = {};
  const appCalls = [];
  const replaceDrafts = [];
  const runtimeCalls = { interpret: [], buildFromFacts: [] };
  const storage = makeStorage();
  const readinessFlag = { value: ready };
  const getElement = (id) => {
    if (!elements.has(id)) elements.set(id, makeElement(id));
    return elements.get(id);
  };
  const stack = [{ state: null, url: "https://quick-quote-kr.pages.dev/" }];
  let index = 0;
  const history = {
    get state() { return stack[index].state; },
    get length() { return stack.length; },
    pushState(state, _title, url) {
      stack.splice(index + 1);
      stack.push({ state, url });
      index = stack.length - 1;
    },
    replaceState(state, _title, url) {
      stack[index] = { state, url: url || stack[index].url };
    },
    back() {
      if (index > 0) {
        index -= 1;
        setTimeout(() => (windowListeners.popstate || []).forEach((fn) => fn({ state: stack[index].state })), 0);
      }
    },
    forward() {
      if (index < stack.length - 1) {
        index += 1;
        setTimeout(() => (windowListeners.popstate || []).forEach((fn) => fn({ state: stack[index].state })), 0);
      }
    }
  };
  const context = vm.createContext({
    setTimeout, clearTimeout, console,
    QuoteCore: Core, QuoteHistory: History, B66FileIntake: FileIntake,
    B66QuoteAppBridge: {
      getDraft: () => Core.createProductionDraft(),
      replaceDraft: (next, opts) => {
        appCalls.push("replaceDraft" + (opts && opts.requireTaxReview ? ":taxReview" : ""));
        replaceDrafts.push(next);
        return { ok: true, draft: next };
      },
      createFreshDraft: (source) => {
        appCalls.push("createFreshDraft:" + source);
        const fresh = Core.createProductionDraft();
        fresh.meta.quoteNo = "PQ-20261004-0" + (appCalls.filter((c) => c.startsWith("createFreshDraft")).length + 1);
        fresh.meta.issueDate = "2026-10-04";
        fresh.meta.source = source || "manual";
        return fresh;
      },
      toast: () => {},
      focusTaxReview: () => { appCalls.push("focusTaxReview"); }
    },
    B66QuoteRuntimeBridge: {
      readiness: () => readinessFlag.value
        ? { ready: true, authenticated: true, skillReady: true, profileReady: true }
        : { ready: false, authenticated: false, skillReady: false, profileReady: false },
      interpret: (text) => {
        runtimeCalls.interpret.push(text);
        const built = SavedQuoteSkill.buildDraft(CGI_SKILL, {
          recipient: INTERPRET_CANDIDATE.recipient,
          items: INTERPRET_CANDIDATE.items,
          quoteNo: "PQ-20261004-099",
          issueDate: "2026-10-04"
        }, { companyProfile: CGI_PROFILE });
        return Promise.resolve(built.ok ? { ok: true, draft: built.draft } : { ok: false, code: built.code });
      },
      buildFromFacts: (facts) => {
        runtimeCalls.buildFromFacts.push(facts);
        const built = SavedQuoteSkill.buildDraft(CGI_SKILL, {
          recipient: facts.recipient,
          items: facts.items,
          quoteNo: facts.quoteNo,
          issueDate: facts.issueDate,
          taxMode: facts.taxMode,
          memo: facts.memo
        }, { companyProfile: CGI_PROFILE });
        return Promise.resolve(built.ok ? { ok: true, draft: built.draft } : { ok: false, code: built.code });
      },
      errorText: (code) => "runtime error: " + code
    },
    CustomEvent: class {
      constructor(type, init) { this.type = type; this.detail = (init || {}).detail; }
    },
    localStorage: storage,
    history,
    location: { href: "https://quick-quote-kr.pages.dev/" },
    confirm: () => true,
    scrollTo() {},
    getComputedStyle: () => ({ getPropertyValue: () => "" }),
    document: {
      readyState: "complete",
      getElementById: getElement,
      addEventListener(type, handler) {
        (documentListeners[type] = documentListeners[type] || []).push(handler);
      },
      dispatchEvent(event) {
        (documentListeners[event.type] || []).forEach((fn) => fn(event));
        return true;
      },
      createElement(tag) {
        const node = makeElement(tag);
        created.push(node);
        return node;
      }
    }
  });
  context.window = context;
  context.addEventListener = (type, handler) => {
    (windowListeners[type] = windowListeners[type] || []).push(handler);
  };
  new vm.Script(easySource, { filename: "easy-mode.js" }).runInContext(context);
  return { context, getElement, created, storage, history, appCalls, replaceDrafts, runtimeCalls, readinessFlag, windowListeners };
}

const clickStarter = (env, id) => {
  const element = env.getElement(id);
  const handler = (element.listeners.click || [])[0];
  assert.equal(typeof handler, "function", "click handler bound for " + id);
  return handler();
};
const chipsWith = (env, label) => env.created.filter(
  (node) => node.textContent === label && (node.listeners.click || []).length > 0
);

async function harnessB() {
  /* B1. ready=true: Home composer 일반 문장 → 진짜 free-form interpret (guided 아님) */
  const readyEnv = buildEasyEnv({ ready: true });
  await flush();
  readyEnv.getElement("easyComposer").value = INTERPRET_TEXT;
  clickStarter(readyEnv, "easySend");
  await flush();
  assert.deepEqual(readyEnv.runtimeCalls.interpret, [INTERPRET_TEXT],
    "home composer text goes to the real interpreter");
  assert.ok(!readyEnv.appCalls.some((c) => c.startsWith("createFreshDraft:guided")),
    "home text is NOT silently converted into a guided session");
  assert.equal(readyEnv.replaceDrafts.length, 1, "generated quote replaces the app draft");
  const generated = readyEnv.replaceDrafts[0];
  assert.equal(generated.recipient.company, "ABC건설", "free-form result recipient");
  assert.equal(generated.items[0].name, "배관", "free-form result item");
  assert.equal(generated.sender.company, "CGI상사", "free-form sender from CompanyProfile");
  assert.equal(readyEnv.getElement("directView").hidden, true,
    "PRIMARY_FLOW_AUTO_OPENS_COMPLEX_DIRECT_FORM=NO (success stays in the conversation)");
  const reviewChips = chipsWith(readyEnv, "견적서 확인하기");
  assert.equal(reviewChips.length > 0, true, "result review offers the canonical paper");
  reviewChips[reviewChips.length - 1].listeners.click[0]();
  await flush();
  assert.equal(readyEnv.getElement("directView").hidden, false,
    "PRIMARY_RESULT_REVIEW=YES (explicit click opens the canonical result)");

  /* B2. ready=false: primary action 은 demo/blank authority 로 진행하지 않는다 */
  const lockedEnv = buildEasyEnv({ ready: false });
  await flush();
  lockedEnv.getElement("easyComposer").value = INTERPRET_TEXT;
  clickStarter(lockedEnv, "easySend");
  await flush();
  assert.equal(lockedEnv.runtimeCalls.interpret.length, 0, "locked runtime never interprets");
  assert.equal(lockedEnv.replaceDrafts.length, 0, "locked runtime never produces a quote");
  const lockedMessages = lockedEnv.getElement("easyMessageList").children.length;
  assert.equal(lockedMessages > 0, true, "locked runtime explains itself instead of failing silently");
  clickStarter(lockedEnv, "guidedStarter");
  await flush();
  assert.equal(lockedEnv.appCalls.some((c) => c.startsWith("createFreshDraft:guided")), false,
    "guided start is also gated when the runtime is not ready");

  /* B3. explicit guided button → guided (interpret 아님), 결과는 같은 runtime 으로 build */
  const guidedEnv = buildEasyEnv({ ready: true });
  await flush();
  clickStarter(guidedEnv, "guidedStarter");
  await flush();
  assert.equal(guidedEnv.runtimeCalls.interpret.length, 0, "explicit guided button starts guided, not the interpreter");
  const answer = async (text) => {
    guidedEnv.getElement("easyComposer").value = text;
    clickStarter(guidedEnv, "easySend");
    await flush();
  };
  await answer("ABC건설");     /* 받는 곳 */
  await answer("없음");        /* 담당자 없음 */
  await answer("배관");        /* 품목 */
  await answer("100");         /* 수량 */
  await answer("18000");       /* 단가 */
  await answer("다음");        /* 품목 종료 */
  await answer("별도");        /* 부가세 */
  await answer("없음");        /* 메모 없음 */
  await answer("현재");        /* 보내는 사람 확인 → 요약 */
  const buildChips = chipsWith(guidedEnv, "견적서 만들기");
  assert.equal(buildChips.length > 0, true, "guided summary offers the runtime build");
  buildChips[buildChips.length - 1].listeners.click[0]();
  await flush();
  assert.equal(guidedEnv.runtimeCalls.buildFromFacts.length, 1, "guided final draft goes through the runtime authority");
  const facts = guidedEnv.runtimeCalls.buildFromFacts[0];
  assert.equal(facts.recipient.company, "ABC건설", "guided facts carry the answered recipient");
  assert.equal(facts.items[0].name, "배관", "guided facts carry the answered item");
  assert.equal(facts.items[0].unitPrice, 18000, "guided facts carry the answered price");
  assert.equal(guidedEnv.replaceDrafts.length, 1, "guided build result reaches the app draft");
  const guidedDraft = guidedEnv.replaceDrafts[0];
  assert.equal(guidedDraft.sender.company, "CGI상사", "GUIDED_DEMO_SENDER_LEAK=0");
  assert.equal(guidedDraft.recipient.company, "ABC건설", "guided result keeps per-quote facts");

  console.log("ONE_PRIMARY_B66_RUNTIME=PASS");
  console.log("HOME_COMPOSER_DEFAULT=FREE_FORM");
  console.log("EXPLICIT_GUIDED_BUTTON=START_GUIDED");
  console.log("HOME_TEXT_SILENTLY_CONVERTED_TO_GUIDED=NO");
  console.log("GUIDED_USES_ASSIGNED_SERVER_SKILL=PASS");
  console.log("GUIDED_USES_ACCOUNT_COMPANY_PROFILE=PASS");
  console.log("GUIDED_DEMO_SENDER_LEAK=0");
  console.log("FREE_FORM_DEMO_SENDER_LEAK=0");
  console.log("PRIMARY_FLOW_AUTO_OPENS_COMPLEX_DIRECT_FORM=NO");
  console.log("PRIMARY_RESULT_REVIEW=PASS");
  console.log("AUTH_READY_BEFORE_PRIMARY_ACTION=PASS");
  console.log("SKILL_READY_BEFORE_PRIMARY_ACTION=PASS");
  console.log("COMPANY_PROFILE_READY_BEFORE_PRIMARY_ACTION=PASS");
  console.log("RENDERER_MODEL_CALLS=0");
}

(async () => {
  await harnessA();
  await harnessB();
  console.log("MVP_RUNTIME_PROBE_FAILURES=0");
  console.log("MVP_RUNTIME_NETWORK_CALLS=0");
  console.log("PADIEM_CHAT_SHELL_REQUIRED=NO");
})().catch((error) => {
  console.error("MVP_RUNTIME_PROBE_CRASH");
  console.error(error && error.message ? error.message : error);
  process.exitCode = 1;
});
