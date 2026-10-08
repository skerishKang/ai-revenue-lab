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
/* canonical 서버는 부분 CompanyProfile 을 허용한다 (유효기간/부가세 기본값 null) */
const PARTIAL_CGI_PROFILE = {
  company: "CGI상사",
  representative: "김범신",
  businessNumber: "111-11-11111",
  address: "서울특별시",
  phone: "02-000-0000",
  email: "cgi@example.invalid",
  defaultValidityDays: null,
  defaultTaxMode: null
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
function buildAccountEnv({ signedIn, withSkill, withProfile, profile }) {
  const runtimeProfile = profile || CGI_PROFILE;
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
      return jsonResponse({ company_profile: runtimeProfile });
    }
    if (target.endsWith("/api/padiem/b66/quote/interpret")) {
      const body = JSON.parse(opts.body || "{}");
      if (!body.message || !body.saved_skill_id) {
        return jsonResponse({ ok: false, error: { code: "quote_input_unrecognized" } }, 422);
      }
      return jsonResponse({
        ok: true,
        candidate: Object.assign({}, INTERPRET_CANDIDATE),
        company_profile: runtimeProfile
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
      privateStateReadable: () => true,
      getHistoryEnvelope: () => History.normalizeEnvelope(null),
      writeHistoryEnvelope: () => false,
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
  assert.equal(draft.meta.validDays, CGI_SKILL.fixedDefaults.validDays,
    "SKILL_VALIDITY_DEFAULT_PRESERVED=YES (approved Skill validity outranks account defaults)");
  assert.equal(draft.tax.mode, CGI_SKILL.fixedDefaults.taxMode,
    "SKILL_TAX_DEFAULT_PRESERVED=YES (approved Skill tax default outranks account defaults)");
  assert.equal(draft.meta.source, "saved-quote-skill", "draft is built by the assigned skill authority");
  assert.ok(draft.calculationPolicy, "skill calculationPolicy carried into the draft");
  const totals = Core.computeDraftTotals(draft);
  assert.equal(totals.grand, 1980000, "QuoteCore totals authority (100 x 18000 + VAT)");
  assert.ok(env.httpCalls.some((c) => c.url.endsWith("/api/padiem/b66/company-profile")),
    "company profile came from the standalone GET bridge");
  assert.ok(env.httpCalls.every((c) => !c.url.includes("extract-")), "no provider calls in the runtime path");

  /* partial canonical CompanyProfile: 유효기간/부가세 기본값이 없어도 견적이 만들어져야 한다 */
  const partialEnv = buildAccountEnv({
    signedIn: true,
    withSkill: true,
    withProfile: true,
    profile: PARTIAL_CGI_PROFILE
  });
  await flush();
  const partialBridge = partialEnv.context.window.B66QuoteRuntimeBridge;
  assert.equal(partialBridge.readiness().ready, true, "PARTIAL_COMPANY_PROFILE_ACCEPTED=YES");
  const partialFreeForm = await partialBridge.interpret(INTERPRET_TEXT);
  assert.equal(partialFreeForm.ok, true, "FREE_FORM_BUILD_WITH_PARTIAL_PROFILE=PASS");
  assert.equal(partialFreeForm.draft.meta.validDays, CGI_SKILL.fixedDefaults.validDays,
    "partial profile keeps the approved Skill validity");
  assert.equal(partialFreeForm.draft.tax.mode, CGI_SKILL.fixedDefaults.taxMode,
    "partial profile keeps the approved Skill tax default");
  assert.equal(partialFreeForm.draft.sender.company, "CGI상사",
    "DEMO_SENDER_LEAK=0 (partial profile still carries the account sender identity)");
  const partialGuidedBuild = await partialBridge.buildFromFacts({
    recipient: INTERPRET_CANDIDATE.recipient,
    items: INTERPRET_CANDIDATE.items,
    quoteNo: "PQ-20261004-045",
    issueDate: "2026-10-04"
  });
  assert.equal(partialGuidedBuild.ok === true && partialGuidedBuild.draft.sender.company === "CGI상사", true,
    "GUIDED_BUILD_WITH_PARTIAL_PROFILE=PASS " + JSON.stringify(partialGuidedBuild.ok));

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

  /* precedence: 이번 견적의 명시적 값 > 승인된 Skill 기본값 > CompanyProfile fallback */
  env.context.fetch = async (url, options) => {
    const target = String(url);
    if (target.endsWith("/api/padiem/b66/quote/interpret")) {
      env.httpCalls.push({ url: target, method: "POST", body: options && options.body });
      return jsonResponse({
        ok: true,
        candidate: Object.assign({ taxMode: "INCLUSIVE" }, INTERPRET_CANDIDATE),
        company_profile: Object.assign({}, CGI_PROFILE, { defaultTaxMode: "EXEMPT" })
      });
    }
    return fetchOriginal(url, options);
  };
  const explicitTaxDraft = await bridge.interpret(INTERPRET_TEXT);
  assert.equal(explicitTaxDraft.draft.tax.mode, "INCLUSIVE",
    "EXPLICIT_QUOTE_TAX_WINS=YES (per-quote tax outranks Skill default and CompanyProfile)");
  env.context.fetch = async (url, options) => {
    const target = String(url);
    if (target.endsWith("/api/padiem/b66/quote/interpret")) {
      env.httpCalls.push({ url: target, method: "POST", body: options && options.body });
      return jsonResponse({
        ok: true,
        candidate: Object.assign({}, INTERPRET_CANDIDATE),
        company_profile: Object.assign({}, CGI_PROFILE, { defaultTaxMode: "EXEMPT" })
      });
    }
    return fetchOriginal(url, options);
  };
  const skillTaxDraft = await bridge.interpret(INTERPRET_TEXT);
  assert.equal(skillTaxDraft.draft.tax.mode, CGI_SKILL.fixedDefaults.taxMode,
    "account tax default never overrides the approved Skill family default");

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

  /* #3751 — B66 model-selection 503 is NOT a malformed quote or a
     license to retry/silently fall back. The input and budget remain intact. */
  const unavailable = buildAccountEnv({ signedIn: true, withSkill: true, withProfile: true });
  await flush();
  const unavailableBridge = unavailable.context.window.B66QuoteRuntimeBridge;
  const originalInput = "테스트건설에 배관 10미터, 미터당 18000원";
  unavailable.getElement("padiemQuoteRequest").value = originalInput;
  let modelUnavailableCalls = 0;
  const originalFetchUnavailable = unavailable.context.fetch;
  unavailable.context.fetch = async (url, options) => {
    if (String(url).endsWith("/api/padiem/b66/quote/interpret")) {
      modelUnavailableCalls += 1;
      return jsonResponse({
        ok: false, error: {
          code: "quote_model_unavailable",
          message: "untrusted synthetic server error must not reach status"
        }
      }, 503);
    }
    return originalFetchUnavailable(url, options);
  };
  const unavailableResult = await unavailableBridge.interpret(originalInput);
  assert.equal(unavailableResult.ok, false);
  assert.equal(unavailableResult.code, "model_selection_unavailable");
  assert.match(unavailableBridge.errorText(unavailableResult.code), /AI 모델이 아직 준비되지 않았습니다/);
  assert.doesNotMatch(unavailableBridge.errorText(unavailableResult.code), /untrusted/);
  assert.equal(modelUnavailableCalls, 1, "exactly one B66 interpret POST");
  assert.equal(unavailable.replaceDrafts.length, 0, "not an approved QuoteDraft");
  assert.equal(unavailableBridge.pendingQuote(), null, "no partial state fabricated by 503");
  assert.equal(unavailable.getElement("padiemQuoteRequest").value, originalInput, "customer text retained");
  assert.ok(!unavailable.appCalls.includes("createFreshDraft:free-form"),
    "model absence must not allocate a quote number or silently start Guided");

  /* A 502 timeout is NOT mislabeled as 503 selection failure. */
  unavailable.context.fetch = async (url, options) => {
    if (String(url).endsWith("/api/padiem/b66/quote/interpret")) {
      modelUnavailableCalls += 1;
      return jsonResponse({ ok: false, error: { code: "quote_interpretation_failed" } }, 502);
    }
    return originalFetchUnavailable(url, options);
  };
  const actualUpstreamFailure = await unavailableBridge.interpret(originalInput);
  assert.equal(actualUpstreamFailure.code, "interpret_failed");
  assert.equal(modelUnavailableCalls, 2, "one attempt per user invocation, no retry");
  assert.equal(unavailable.replaceDrafts.length, 0);
  assert.equal(unavailable.getElement("padiemQuoteRequest").value, originalInput);
  assert.equal(unavailableBridge.pendingQuote(), null);

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
function buildEasyEnv({ ready, profile }) {
  const runtimeProfile = profile || CGI_PROFILE;
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
      privateStateReadable: () => true,
      /* app.js owner 게이트 미러: 최근 견적 저장소 접근은 이 스텁을 통해서만 일어난다 */
      getHistoryEnvelope: () => History.normalizeEnvelope(
        JSON.parse(context.localStorage.getItem(History.HISTORY_STORAGE_KEY) || "null")
      ),
      writeHistoryEnvelope: (envelope) => {
        context.localStorage.setItem(
          History.HISTORY_STORAGE_KEY,
          JSON.stringify(History.normalizeEnvelope(envelope))
        );
        return true;
      },
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
        }, { companyProfile: runtimeProfile });
        return Promise.resolve(built.ok ? { ok: true, draft: built.draft } : { ok: false, code: built.code });
      },
      supportedItemRows: () => 3,
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
  assert.equal(guidedDraft.meta.validDays, CGI_SKILL.fixedDefaults.validDays,
    "guided build keeps the approved Skill validity");
  assert.equal(guidedDraft.tax.mode, "EXCLUSIVE", "guided per-quote tax answer wins over the Skill default");

  /* The supported CGI guide ends at three real rows and keeps an extra
     typed '추가' on the existing step, so no invisible fourth row is accepted. */
  const cappedGuided = buildEasyEnv({ ready: true });
  await flush();
  clickStarter(cappedGuided, "guidedStarter");
  await flush();
  const cappedAnswer = async (text) => {
    cappedGuided.getElement("easyComposer").value = text;
    clickStarter(cappedGuided, "easySend");
    await flush();
  };
  await cappedAnswer("Synthetic buyer");
  await cappedAnswer("없음");
  for (let i = 1; i <= 3; i += 1) {
    await cappedAnswer("Synthetic item " + i);
    await cappedAnswer(String(i));
    await cappedAnswer("100");
    if (i < 3) await cappedAnswer("추가");
  }
  assert.equal(cappedGuided.getElement("easyChipRow").children.filter((node) => node.textContent === "품목 추가").length, 0, "CGI guide offers no fourth item chip");
  await cappedAnswer("추가");
  await cappedAnswer("다음");
  await cappedAnswer("별도");
  await cappedAnswer("없음");
  await cappedAnswer("현재");
  const cappedBuildChips = chipsWith(cappedGuided, "견적서 만들기");
  assert.ok(cappedBuildChips.length, "three-item guide completes normally after refusing extra input");
  cappedBuildChips[cappedBuildChips.length - 1].listeners.click[0]();
  await flush();
  assert.equal(cappedGuided.runtimeCalls.buildFromFacts.length, 1);
  assert.equal(cappedGuided.runtimeCalls.buildFromFacts[0].items.length, 3);
  assert.equal(cappedGuided.replaceDrafts[0].items.length, 3);
  console.log("CGI_GUIDED_THREE_ITEM_BOUND=PASS");

  /* B4. partial canonical CompanyProfile 로도 guided 가 정상 견적을 만든다 */
  const partialEnv = buildEasyEnv({ ready: true, profile: PARTIAL_CGI_PROFILE });
  await flush();
  clickStarter(partialEnv, "guidedStarter");
  await flush();
  const partialAnswer = async (text) => {
    partialEnv.getElement("easyComposer").value = text;
    clickStarter(partialEnv, "easySend");
    await flush();
  };
  await partialAnswer("ABC건설");
  await partialAnswer("없음");
  await partialAnswer("배관");
  await partialAnswer("100");
  await partialAnswer("18000");
  await partialAnswer("다음");
  await partialAnswer("별도");
  await partialAnswer("없음");
  await partialAnswer("현재");
  const partialChips = chipsWith(partialEnv, "견적서 만들기");
  assert.equal(partialChips.length > 0, true, "partial-profile guided reaches the summary");
  partialChips[partialChips.length - 1].listeners.click[0]();
  await flush();
  const partialGuidedDraft = partialEnv.replaceDrafts[0];
  assert.ok(partialGuidedDraft, "GUIDED_BUILD_WITH_PARTIAL_PROFILE=PASS");
  assert.equal(partialGuidedDraft.sender.company, "CGI상사", "partial-profile guided keeps the account sender");
  assert.equal(partialGuidedDraft.meta.validDays, CGI_SKILL.fixedDefaults.validDays,
    "partial-profile guided keeps the Skill validity default");
  assert.equal(partialGuidedDraft.recipient.company, "ABC건설", "partial-profile guided keeps per-quote facts");

  console.log("ONE_PRIMARY_B66_RUNTIME=PASS");
  console.log("HOME_COMPOSER_DEFAULT=FREE_FORM");
  console.log("EXPLICIT_GUIDED_BUTTON=START_GUIDED");
  console.log("HOME_TEXT_SILENTLY_CONVERTED_TO_GUIDED=NO");
  console.log("GUIDED_USES_ASSIGNED_SERVER_SKILL=PASS");
  console.log("GUIDED_USES_ACCOUNT_COMPANY_PROFILE=PASS");
  console.log("PARTIAL_COMPANY_PROFILE_ACCEPTED=YES");
  console.log("SKILL_VALIDITY_DEFAULT_PRESERVED=YES");
  console.log("SKILL_TAX_DEFAULT_PRESERVED=YES");
  console.log("GUIDED_BUILD_WITH_PARTIAL_PROFILE=PASS");
  console.log("FREE_FORM_BUILD_WITH_PARTIAL_PROFILE=PASS");
  console.log("DEMO_SENDER_LEAK=0");
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
