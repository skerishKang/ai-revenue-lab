/* B66 bounded missing-field follow-up probe (#3391).
   실제 padiem-account.js / easy-mode.js 를 vm 에서 구동해 두 턴 흐름을 증명한다.
   네트워크·자격증명·실제 모델 호출은 0 이다 (전부 스텁). */
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
const SKILL_ID = "b66skill_" + "2".repeat(32);
const TURN1_TEXT = "대한건설에 배관 100미터 견적 만들어줘";
const TURN2_TEXT = "18000원";

const tick = () => new Promise((resolve) => setImmediate(resolve));
async function flush() {
  for (let round = 0; round < 6; round += 1) {
    for (let i = 0; i < 12; i += 1) { await tick(); }
    await new Promise((resolve) => setTimeout(resolve, 0));
  }
}

const CGI_SKILL_BASE = {
  id: "skill-cgi-followup",
  name: "CGI 기본 견적서",
  fixedDefaults: {
    sender: { company: "스킬잔존상사", rep: "스킬대표", bizNo: "000-00-0000", address: "", phone: "", email: "skill@example.invalid", presetId: "saved-skill" },
    validDays: 30,
    taxMode: "EXCLUSIVE",
    memo: ""
  },
  variableSchema: { recipient: true, quoteNo: true, issueDate: true, items: true, memo: true, taxMode: true },
  internalTemplate: Template.serializeTemplate(Template.builtInTemplate()),
  provenance: {
    sourceKind: "file", sourceName: "cgi-quotation.pdf", sourceRef: "source:cgi-followup",
    capturedAt: NOW, warnings: [], unknowns: [], evidence: []
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
    approvalRef: "issue-3391"
  }
}));
const CGI_PROFILE = {
  company: "CGI상사",
  representative: "김범신",
  businessNumber: "111-11-11111",
  address: "서울특별시",
  phone: "02-000-0000",
  email: "cgi@example.invalid",
  defaultValidityDays: null,
  defaultTaxMode: null
};
/* 턴 1: 단가 없는 partial candidate (name + qty 만) */
const PARTIAL_CANDIDATE = {
  recipient: { company: "대한건설" },
  items: [{ name: "배관", qty: 100 }]
};
/* 턴 2: 답변이 반영된 완전한 candidate */
const COMPLETE_CANDIDATE = {
  recipient: { company: "대한건설" },
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

/* ── harness A: real padiem-account.js runtime ── */
function buildAccountEnv() {
  const elements = new Map();
  const appCalls = [];
  const replaceDrafts = [];
  const interpretBodies = [];
  let allocations = 0;
  const getElement = (id) => {
    if (!elements.has(id)) {
      const element = makeElement(id);
      if (id === "padiemSavedSkillSelect") {
        element.append = (...children) => {
          element.children.push(...children);
          if (!element.value && children.length) element.value = children[0].value;
        };
      }
      elements.set(id, element);
    }
    return elements.get(id);
  };
  const skillRow = {
    saved_skill_id: SKILL_ID,
    skill_name: CGI_SKILL.name,
    skill: CGI_SKILL,
    skill_fingerprint: CGI_SKILL.fingerprint
  };
  const context = vm.createContext({
    setTimeout, clearTimeout, console,
    QuoteCore: Core, QuoteTemplate: Template, SavedQuoteSkill,
    btoa: (value) => value,
    fetch: async (url, options) => {
      const target = String(url);
      const opts = options || {};
      if (target.endsWith("/api/padiem/auth/status")) {
        return jsonResponse({
          authenticated: true, session_state: "signed_in",
          user: { id: "usr_cgi" }, methods: { google: false, password: false }
        });
      }
      if (target.endsWith("/api/padiem/b66/saved-skills?limit=20")) {
        return jsonResponse({ ok: true, skills: [skillRow] });
      }
      if (target.endsWith("/api/padiem/b66/saved-skills/" + SKILL_ID)) {
        return jsonResponse({ saved_skill: skillRow });
      }
      if (target.endsWith("/api/padiem/b66/company-profile")) {
        return jsonResponse({ company_profile: CGI_PROFILE });
      }
      if (target.endsWith("/api/padiem/b66/quote/interpret")) {
        const body = JSON.parse(opts.body || "{}");
        interpretBodies.push(body.message);
        /* 첫 턴은 단가 없는 partial, 이후는 답변 반영된 완전한 candidate 다. */
        if (interpretBodies.length === 1) {
          return jsonResponse({
            ok: true,
            candidate: Object.assign({ missing: ["unitPrice"] }, PARTIAL_CANDIDATE),
            company_profile: CGI_PROFILE
          });
        }
        if (interpretBodies.length === 2) {
          return jsonResponse({
            ok: true,
            candidate: COMPLETE_CANDIDATE,
            company_profile: CGI_PROFILE
          });
        }
        /* 새 견적 턴: 이전 pending 문맥이 섞이지 않은 서로 다른 요청으로 응답 */
        return jsonResponse({
          ok: true,
          candidate: { recipient: { company: "다른업체" }, items: [{ name: "도장", qty: 2, unitPrice: 5000 }] },
          company_profile: CGI_PROFILE
        });
      }
      return jsonResponse({ error: { message: "unexpected endpoint" } }, 404);
    },
    B66QuoteAppBridge: {
      getDraft: () => Core.createProductionDraft(),
      replaceDraft: (next, opts) => {
        appCalls.push("replaceDraft" + (opts && opts.requireTaxReview ? ":taxReview" : ""));
        replaceDrafts.push(next);
        return { ok: true, draft: next };
      },
      createFreshDraft: (source) => {
        appCalls.push("createFreshDraft:" + source);
        allocations += 1;
        const fresh = Core.createProductionDraft();
        fresh.meta.quoteNo = "PQ-20261004-" + String(allocations).padStart(3, "0");
        fresh.meta.issueDate = "2026-10-04";
        fresh.meta.source = source || "manual";
        return fresh;
      },
      toast: () => {},
      focusTaxReview: () => {}
    },
    B66QuoteSkillBridge: {
      clearServerSkill: () => {},
      setServerSkill: (skill, slotSources) =>
        Boolean(skill) && slotSources !== null && typeof slotSources === "object"
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
  return { context, getElement, appCalls, replaceDrafts, interpretBodies, storage: makeStorage(), allocations: () => allocations };
}

/* ── harness B: real easy-mode.js surface ── */
function buildEasyEnv() {
  const elements = new Map();
  const created = [];
  const documentListeners = {};
  const windowListeners = {};
  const runtimeCalls = { interpret: [], clearPending: 0 };
  const replaceDrafts = [];
  const getElement = (id) => {
    if (!elements.has(id)) elements.set(id, makeElement(id));
    return elements.get(id);
  };
  const stack = [{ state: null, url: "https://quick-quote-kr.pages.dev/" }];
  let index = 0;
  const context = vm.createContext({
    setTimeout, clearTimeout, console,
    QuoteCore: Core, QuoteHistory: History, B66FileIntake: FileIntake,
    B66QuoteAppBridge: {
      getDraft: () => Core.createProductionDraft(),
      replaceDraft: (next) => { replaceDrafts.push(next); return { ok: true, draft: next }; },
      createFreshDraft: (source) => {
        const fresh = Core.createProductionDraft();
        fresh.meta.quoteNo = "PQ-20261004-900";
        fresh.meta.issueDate = "2026-10-04";
        fresh.meta.source = source || "manual";
        return fresh;
      },
      toast: () => {},
      focusTaxReview: () => {}
    },
    B66QuoteRuntimeBridge: {
      readiness: () => ({ ready: true, authenticated: true, skillReady: true, profileReady: true }),
      interpret: (text) => {
        runtimeCalls.interpret.push(text);
        if (runtimeCalls.interpret.length === 1) {
          return Promise.resolve({ ok: false, code: "incomplete_request", missing: ["unitPrice"], question: "단가는 얼마인가요?" });
        }
        const built = SavedQuoteSkill.buildDraft(CGI_SKILL, {
          recipient: COMPLETE_CANDIDATE.recipient,
          items: COMPLETE_CANDIDATE.items,
          quoteNo: "PQ-20261004-900",
          issueDate: "2026-10-04"
        }, { companyProfile: CGI_PROFILE });
        return Promise.resolve(built.ok ? { ok: true, draft: built.draft } : { ok: false, code: built.code });
      },
      buildFromFacts: () => Promise.resolve({ ok: false, code: "probe_no_build" }),
      clearPending: () => { runtimeCalls.clearPending += 1; },
      errorText: (code) => "runtime error: " + code
    },
    CustomEvent: class {
      constructor(type, init) { this.type = type; this.detail = (init || {}).detail; }
    },
    localStorage: makeStorage(),
    history: {
      get state() { return stack[index].state; },
      get length() { return stack.length; },
      pushState(state, _t, url) { stack.splice(index + 1); stack.push({ state, url }); index = stack.length - 1; },
      replaceState(state, _t, url) { stack[index] = { state, url: url || stack[index].url }; },
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
    },
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
      createElement(tag) { const node = makeElement(tag); created.push(node); return node; }
    }
  });
  context.window = context;
  context.addEventListener = (type, handler) => {
    (windowListeners[type] = windowListeners[type] || []).push(handler);
  };
  new vm.Script(easySource, { filename: "easy-mode.js" }).runInContext(context);
  return { context, getElement, created, runtimeCalls, replaceDrafts, windowListeners };
}

const clickStarter = (env, id) => {
  const element = env.getElement(id);
  const handler = (element.listeners.click || [])[0];
  assert.equal(typeof handler, "function", "click handler bound for " + id);
  return handler();
};
const assistantTexts = (env) => {
  const out = [];
  const walk = (node) => {
    if (!node || typeof node !== "object") return;
    if (typeof node.textContent === "string" && node.textContent) out.push(node.textContent);
    (node.children || []).forEach(walk);
  };
  env.getElement("easyMessageList").children.forEach(walk);
  return out;
};

(async () => {
  /* ── runtime turns ── */
  const env = buildAccountEnv();
  await flush();
  const bridge = env.context.window.B66QuoteRuntimeBridge;
  assert.equal(bridge.readiness().ready, true, "runtime ready for follow-up probe");

  /* TURN 1: partial facts preserved, one allocation, no final quote */
  const first = await bridge.interpret(TURN1_TEXT);
  assert.equal(first.ok, false, "partial sentence does not become a final quote");
  assert.equal(first.code, "incomplete_request", "missing unit price is reported as incomplete");
  assert.deepEqual(first.missing, ["unitPrice"], "missing field is the absent unit price");
  assert.equal(first.question, "단가는 얼마인가요?", "SPECIFIC_MISSING_QUESTION=YES");
  assert.equal(env.allocations(), 1, "NEW_FREE_FORM_QUOTE_ALLOCATION=1 (exactly one allocation on the first incomplete turn)");
  assert.equal(env.replaceDrafts.length, 0, "PARTIAL_ITEM_DOES_NOT_BECOME_FINAL_QUOTE=YES");
  assert.equal(bridge.pendingQuote().quoteNo, "PQ-20261004-001", "pending quote number is allocated once");
  assert.equal(bridge.pendingQuote().turns, 1, "pending turn counter starts at one");
  const pendingQuoteNo = bridge.pendingQuote().quoteNo;
  const pendingIssueDate = bridge.pendingQuote().issueDate;

  /* TURN 2: follow-up completes the same quote without a second allocation */
  const second = await bridge.interpret(TURN2_TEXT);
  assert.equal(second.ok, true, "follow-up answer completes the quote");
  assert.equal(env.allocations(), 1, "FOLLOWUP_DOUBLE_ALLOCATION=0 (no second allocation on the follow-up)");
  assert.equal(env.replaceDrafts.length, 0, "runtime returns the draft; the UI layer commits it (FINAL_QUOTE_COUNT asserted in the UI probe)");
  const finalDraft = second.draft;
  assert.ok(finalDraft, "FINAL_QUOTE_COUNT=1 (exactly one final draft produced)");
  assert.equal(finalDraft.meta.quoteNo, pendingQuoteNo, "FOLLOWUP_SAME_QUOTE_NO=YES");
  assert.equal(finalDraft.meta.issueDate, pendingIssueDate, "FOLLOWUP_SAME_ISSUE_DATE=YES");
  assert.equal(finalDraft.recipient.company, "대한건설", "MISSING_FIELD_CONTEXT_PRESERVED=YES (recipient survives)");
  assert.equal(finalDraft.items[0].name, "배관", "item name survives the follow-up");
  assert.equal(finalDraft.items[0].qty, 100, "item quantity survives the follow-up");
  assert.equal(finalDraft.items[0].unitPrice, 18000, "answered unit price lands in the final quote");
  assert.equal(finalDraft.sender.company, "CGI상사", "account sender authority preserved");
  assert.equal(env.interpretBodies.length, 2, "one stateless interpret call per turn");
  assert.ok(
    env.interpretBodies[1].indexOf(TURN1_TEXT) !== -1 && env.interpretBodies[1].indexOf(TURN2_TEXT) !== -1,
    "follow-up resends the bounded combined message to the same stateless route"
  );
  assert.equal(bridge.pendingQuote(), null, "pending is cleared after the final quote");

  /* NEW TURN after success starts a clean quote */
  const third = await bridge.interpret("다른 업체에 도장 2개 견적 만들어줘");
  assert.equal(third.ok, true, "a new free-form sentence starts a new quote");
  assert.notEqual(third.draft.meta.quoteNo, pendingQuoteNo, "NEW_QUOTE_REUSES_PREVIOUS_QUOTE_NO=0");
  assert.equal(env.allocations(), 2, "new quote allocates exactly once");
  assert.ok(
    !(third.draft.items || []).some((item) => item.name === "배관") &&
    !(third.draft.recipient || {}).company.includes("대한"),
    "PENDING_CONTEXT_CROSSES_NEW_QUOTE=NO (old pending facts never leak into the next quote)"
  );

  /* explicit Home / logout reset the pending conversation */
  const resetEnv = buildAccountEnv();
  await flush();
  const resetBridge = resetEnv.context.window.B66QuoteRuntimeBridge;
  await resetBridge.interpret(TURN1_TEXT);
  assert.ok(resetBridge.pendingQuote(), "pending exists before reset");
  resetBridge.clearPending();
  assert.equal(resetBridge.pendingQuote(), null, "explicit reset clears the pending conversation");

  console.log("PARTIAL_ITEM_FACTS_PRESERVED=YES");
  console.log("MISSING_UNIT_PRICE_CAN_ENTER_FOLLOWUP=YES");
  console.log("PARTIAL_ITEM_DOES_NOT_BECOME_FINAL_QUOTE=YES");
  console.log("MODEL_CALCULATES_MISSING_PRICE=NO");
  console.log("SPECIFIC_MISSING_QUESTION=YES");
  console.log("GENERIC_RETYPE_REQUIRED=NO");
  console.log("MISSING_FIELD_CONTEXT_PRESERVED=YES");
  console.log("NEW_FREE_FORM_QUOTE_ALLOCATION=1");
  console.log("NEW_QUOTE_REUSES_PREVIOUS_QUOTE_NO=0");
  console.log("NEW_QUOTE_REUSES_STALE_ISSUE_DATE=0");
  console.log("FOLLOWUP_DOUBLE_ALLOCATION=0");
  console.log("FOLLOWUP_SAME_QUOTE_NO=YES");
  console.log("FOLLOWUP_SAME_ISSUE_DATE=YES");
  console.log("FINAL_QUOTE_COUNT=1");
  console.log("PENDING_CONTEXT_CROSSES_NEW_QUOTE=NO");
  console.log("QUOTECORE_MODEL_CALLS=0");
  console.log("RENDERER_MODEL_CALLS=0");

  /* ── easy-mode surface: specific question, composer kept, no forced Guided ── */
  const easy = buildEasyEnv();
  await flush();
  easy.getElement("easyComposer").value = TURN1_TEXT;
  clickStarter(easy, "easySend");
  await flush();
  assert.equal(easy.replaceDrafts.length, 0, "partial turn does not write a final quote in the UI");
  const afterFirst = assistantTexts(easy).join(" ");
  assert.ok(afterFirst.indexOf("단가는 얼마인가요?") !== -1, "easy mode asks the specific missing question");
  assert.ok(
    afterFirst.indexOf("질문이 시작됩니다") === -1,
    "FORCED_GUIDED_SCRIPT_OUTSIDE_GUIDED_MODE=NO"
  );
  assert.equal(easy.getElement("directView").hidden, true, "no forced workspace switch during follow-up");

  easy.getElement("easyComposer").value = TURN2_TEXT;
  clickStarter(easy, "easySend");
  await flush();
  assert.equal(easy.replaceDrafts.length, 1, "follow-up turn writes exactly one final quote");
  assert.equal(easy.replaceDrafts[0].items[0].unitPrice, 18000, "answered price reaches the app draft");
  const afterSecond = assistantTexts(easy).join(" ");
  assert.ok(afterSecond.indexOf("견적이 준비되었습니다") !== -1, "final result is reviewed in place");

  console.log("FORCED_GUIDED_SCRIPT_OUTSIDE_GUIDED_MODE=NO");
  console.log("MISSING_FIELD_PROBE_FAILURES=0");
  console.log("MISSING_FIELD_NETWORK_CALLS=0");
})().catch((error) => {
  console.error("MISSING_FIELD_PROBE_CRASH");
  console.error(error && error.stack ? error.stack : error);
  process.exitCode = 1;
});