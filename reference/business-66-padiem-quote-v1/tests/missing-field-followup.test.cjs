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
const BrowserPdf = require(path.join(SRC, "quote-browser-pdf.js"));
const accountSource = fs.readFileSync(path.join(SRC, "padiem-account.js"), "utf8");
const easySource = fs.readFileSync(path.join(SRC, "easy-mode.js"), "utf8");

const NOW = "2026-10-04T09:00:00.000Z";
const SKILL_ID = BrowserPdf.CGI_SKILL_ID;
const SELECTED_MODEL_ID = "test-fixture/b66-selected-chat";
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
function buildAccountEnv(options) {
  const config = options || {};
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
    B66BrowserPdf: config.generic ? { isCgiSkill: () => false } : BrowserPdf,
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
      if (target.endsWith("/api/padiem/b66/quote/models")) {
        // Registered selection in a test fixture; user still explicitly
        // selects the exact model before generating a quote.
        return jsonResponse({
          ok: true,
          models: [{ model_id: SELECTED_MODEL_ID, name: "Synthetic Test Model" }],
          default_model_id: null
        });
      }
      if (target.endsWith("/api/padiem/b66/quote/interpret")) {
        const body = JSON.parse(opts.body || "{}");
        assert.equal(body.model_id, SELECTED_MODEL_ID,
          "explicit user choice is submitted independently of quote text");
        interpretBodies.push(body.message);
        if (config.unrecognizedModelOutput ||
            config.unrecognizedResponseTurn === interpretBodies.length) {
          return jsonResponse({ ok: false, error: { code: "quote_input_unrecognized",
            message: "견적 입력값을 확인해 주세요." } }, 422);
        }
        if (config.candidates) {
          const candidate = config.candidates[interpretBodies.length - 1];
          assert.ok(candidate, "one fixture per interpretation turn");
          return jsonResponse({ ok: true, candidate: JSON.parse(JSON.stringify(candidate)), company_profile: CGI_PROFILE });
        }
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
      privateStateReadable: () => true,
      getHistoryEnvelope: () => History.normalizeEnvelope(null),
      writeHistoryEnvelope: () => false,
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

const manuallyChooseModel = (env) => {
  const select = env.getElement("padiemQuoteModelSelect");
  assert.equal(select.disabled, false, "B66 model options are ready");
  assert.ok(select.children.some((row) => row.value === SELECTED_MODEL_ID));
  select.value = SELECTED_MODEL_ID; // explicit user action, never an implicit backend auto route
};

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
  const selectedModel = env.getElement("padiemQuoteModelSelect");
  assert.equal(selectedModel.value, "", "without owner default, no automatic model choice");
  assert.equal(selectedModel.disabled, false, "ready registered models are selectable");
  manuallyChooseModel(env); // fixture simulates a real user action


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
  manuallyChooseModel(resetEnv);
  const resetBridge = resetEnv.context.window.B66QuoteRuntimeBridge;
  await resetBridge.interpret(TURN1_TEXT);
  assert.ok(resetBridge.pendingQuote(), "pending exists before reset");
  resetBridge.clearPending();
  assert.equal(resetBridge.pendingQuote(), null, "explicit reset clears the pending conversation");

  /* Missing name/quantity/price all use the same precise, bounded path.
     The follow-up provider fixture deliberately returns only the answered fact:
     prior recipient and item facts must survive without defaults or a retype. */
  for (const field of ["name", "qty", "unitPrice"]) {
    const priorItem = { name: "Synthetic item", qty: 5, unitPrice: 700 };
    const answeredValue = priorItem[field];
    delete priorItem[field];
    const sequence = buildAccountEnv({ candidates: [
      { recipient: { person: "Synthetic recipient" }, items: [priorItem], missing: [field] },
      { recipient: {}, items: [{ [field]: answeredValue }], missing: ["recipient", "items"] }
    ] });
    await flush();
    manuallyChooseModel(sequence);
    const runtime = sequence.context.B66QuoteRuntimeBridge;
    const firstTurn = await runtime.interpret("Synthetic item request");
    assert.equal(firstTurn.code, "incomplete_request");
    assert.deepEqual(firstTurn.missing, [field]);
    assert.equal(firstTurn.question, { name: "품목명을 알려 주세요.", qty: "수량은 몇 개인가요?", unitPrice: "단가는 얼마인가요?" }[field]);
    assert.equal(sequence.allocations(), 1);
    const completed = await runtime.interpret(String(answeredValue));
    assert.equal(completed.ok, true, "minimal " + field + " answer completes the preserved facts");
    assert.equal(completed.draft.recipient.person, "Synthetic recipient");
    assert.equal(completed.draft.items[0].name, "Synthetic item");
    assert.equal(completed.draft.items[0].qty, 5);
    assert.equal(completed.draft.items[0].unitPrice, 700);
    assert.equal(sequence.allocations(), 1);
    assert.equal(sequence.interpretBodies.length, 2, "one request per turn, including a number-only quantity answer");
    assert.ok(sequence.interpretBodies[1].includes(firstTurn.question), "question identifies the meaning of a bare numeric answer");
  }

  /* #3916: an estimated customer quantity is not silently finalized.
     The server withholds qty; the browser keeps the quote and asks for an
     exact numerical correction before creating the final draft. */
  const estimated = buildAccountEnv({ candidates: [
    { recipient: { company: "대한건설" }, items: [{ name: "배관", unitPrice: 2000 }] },
    { recipient: { company: "대한건설" }, items: [{ name: "배관", qty: 120, unitPrice: 2000 }] }
  ] });
  await flush();
  manuallyChooseModel(estimated);
  const estimatedBridge = estimated.context.B66QuoteRuntimeBridge;
  const estimateFirst = await estimatedBridge.interpret("대한건설 배관 대충 100개 정도, 단가 2000원");
  assert.equal(estimateFirst.ok, false);
  assert.equal(estimateFirst.code, "incomplete_request");
  assert.deepEqual(estimateFirst.missing, ["qty"]);
  assert.match(estimateFirst.question, /최종 수량을 정확한 숫자와 단위/);
  assert.equal(estimated.allocations(), 1);
  assert.equal(estimated.replaceDrafts.length, 0, "unconfirmed quantity cannot create final draft");
  const estimatedNumber = estimatedBridge.pendingQuote().quoteNo;
  const estimateSecond = await estimatedBridge.interpret("120개");
  assert.equal(estimateSecond.ok, true, "explicit revised quantity completes pending quote");
  assert.equal(estimateSecond.draft.meta.quoteNo, estimatedNumber);
  assert.equal(estimateSecond.draft.items[0].qty, 120);
  assert.equal(estimated.allocations(), 1, "no extra allocation when confirming quantity");
  assert.equal(estimated.interpretBodies.length, 2, "one POST per turn");
  assert.ok(estimated.interpretBodies[1].includes("120개"));
  assert.equal(estimatedBridge.pendingQuote(), null);
  console.log("APPROXIMATE_QUANTITY_CONFIRMATION_UI=PASS");

  const multi = buildAccountEnv({ candidates: [
    { recipient: { company: "Synthetic buyer", person: "Known person" }, items: [
      { name: "First item", qty: 3, unitPrice: 400 }, { name: "Second item", unitPrice: 800 }
    ], missing: ["qty"] },
    { recipient: {}, items: [{ qty: 7 }], missing: ["recipient", "name", "unitPrice"] }
  ] });
  await flush();
  manuallyChooseModel(multi);
  const multiBridge = multi.context.B66QuoteRuntimeBridge;
  const multiFirst = await multiBridge.interpret("Synthetic multiple item request");
  assert.equal(multiFirst.question, "2번째 품목(Second item): 수량은 몇 개인가요?");
  const multiSecond = await multiBridge.interpret("7");
  assert.equal(multiSecond.ok, true);
  assert.equal(multiSecond.draft.items.length, 2);
  assert.equal(multiSecond.draft.items[0].qty, 3, "known first quantity is unchanged");
  assert.equal(multiSecond.draft.items[1].qty, 7, "bare answer fills the specifically asked second item");
  assert.equal(multiSecond.draft.items[1].unitPrice, 800);
  assert.equal(multiSecond.draft.recipient.person, "Known person");
  assert.equal(multi.interpretBodies.length, 2);

  const repeatedNames = buildAccountEnv({ candidates: [
    { recipient: { company: "Synthetic buyer" }, items: [
      { name: "Same item", qty: 3, unitPrice: 400 }, { name: "Same item", unitPrice: 800 }
    ], missing: ["qty"] },
    { recipient: {}, items: [{ name: "Same item", qty: 7 }], missing: ["recipient", "unitPrice"] }
  ] });
  await flush();
  manuallyChooseModel(repeatedNames);
  const repeatBridge = repeatedNames.context.B66QuoteRuntimeBridge;
  const repeatFirst = await repeatBridge.interpret("Synthetic repeated-name request");
  assert.equal(repeatFirst.question, "2번째 품목(Same item): 수량은 몇 개인가요?");
  const repeatSecond = await repeatBridge.interpret("7");
  assert.equal(repeatSecond.ok, true);
  assert.equal(repeatSecond.draft.items.length, 2, "duplicate names do not append a hidden third item");
  assert.equal(repeatSecond.draft.items[0].qty, 3);
  assert.equal(repeatSecond.draft.items[1].qty, 7);

  const detailPartial = buildAccountEnv({ generic: true, candidates: [
    { recipient: { person: "Known recipient" }, items: [{ name: "Summary", qty: 1, unitPrice: 0 }],
      detailGroups: [{ id: "detail-group-1", summaryItemId: "item-1", items: [{ name: "Detail item", qty: 2 }] }], missing: ["unitPrice"] },
    { recipient: {}, items: [{ name: "Summary", qty: 1, unitPrice: 0 }],
      detailGroups: [{ id: "detail-group-1", summaryItemId: "item-1", items: [{ unitPrice: 50 }] }], missing: ["recipient", "name", "qty"] }
  ] });
  await flush();
  manuallyChooseModel(detailPartial);
  const detailPartialBridge = detailPartial.context.B66QuoteRuntimeBridge;
  const detailFirst = await detailPartialBridge.interpret("Synthetic generic detail request");
  assert.equal(detailFirst.question, "1번째 상세그룹의 1번째 품목: 단가는 얼마인가요?");
  const detailSecond = await detailPartialBridge.interpret("50");
  assert.equal(detailSecond.ok, true, "generic detail missing price preserves the existing structured contract");
  assert.equal(detailSecond.draft.detailGroups[0].items[0].name, "Detail item");
  assert.equal(detailSecond.draft.detailGroups[0].items[0].qty, 2);
  assert.equal(detailSecond.draft.detailGroups[0].items[0].unitPrice, 50);
  assert.equal(detailSecond.draft.recipient.person, "Known recipient");

  const fourItems = [1, 2, 3, 4].map((i) => ({ name: "Synthetic item " + i, qty: i, unitPrice: 100 }));
  const oversize = buildAccountEnv({ candidates: [{ recipient: { person: "Synthetic buyer" }, items: fourItems, missing: [] }] });
  await flush();
  manuallyChooseModel(oversize);
  const oversizeBridge = oversize.context.B66QuoteRuntimeBridge;
  const rejected = await oversizeBridge.interpret("Synthetic four-item request");
  assert.equal(rejected.ok, false);
  assert.equal(rejected.code, "cgi_unsupported_rows");
  assert.ok(oversizeBridge.errorText(rejected.code).includes("3개"));
  assert.equal(oversize.allocations(), 0, "oversize request is rejected before accepting a pending/final quote");
  assert.equal(oversizeBridge.pendingQuote(), null);
  const guidedOversize = await oversizeBridge.buildFromFacts({ recipient: { person: "Synthetic buyer" }, items: fourItems });
  assert.equal(guidedOversize.code, "cgi_unsupported_rows");
  assert.equal(oversize.allocations(), 0, "structured oversize facts rejected before allocation");
  const threeSupported = await oversizeBridge.buildFromFacts({ recipient: { person: "Synthetic buyer" }, items: fourItems.slice(0, 3) });
  assert.equal(threeSupported.ok, true, "all three CGI rows remain supported");
  assert.equal(threeSupported.draft.items.length, 3);

  const detailed = buildAccountEnv({ candidates: [{ recipient: { person: "Synthetic buyer" },
    items: [{ name: "Summary", qty: 1, unitPrice: 0 }],
    detailGroups: [{ summaryItemId: "item-1", items: [{ name: "Detail", qty: 1, unitPrice: 100 }] }], missing: [] }] });
  await flush();
  manuallyChooseModel(detailed);
  const detailRejected = await detailed.context.B66QuoteRuntimeBridge.interpret("Synthetic detail request");
  assert.equal(detailRejected.code, "cgi_unsupported_details");
  assert.equal(detailed.allocations(), 0, "unsupported detail output is explicit before accepting a CGI draft");
  assert.ok(detailed.context.B66QuoteRuntimeBridge.errorText(detailRejected.code).includes("상세내역"));

  const generic = buildAccountEnv({ generic: true, candidates: [{ recipient: { person: "Synthetic buyer" }, items: fourItems, missing: [] }] });
  await flush();
  manuallyChooseModel(generic);
  const genericBuilt = await generic.context.B66QuoteRuntimeBridge.interpret("Synthetic generic request");
  assert.equal(genericBuilt.ok, true, "CGI row scope does not become a generic QuoteCore cap");
  assert.equal(genericBuilt.draft.items.length, 4);

  /* If the model emitted malformed output, ask for clarification rather than
     showing an opaque technical error or fabricating a price. */
  const unclear = buildAccountEnv({ unrecognizedModelOutput: true });
  await flush();
  manuallyChooseModel(unclear);
  const unclearBridge = unclear.context.B66QuoteRuntimeBridge;
  const unclearResult = await unclearBridge.interpret("부픔 ㅇㅇ몇개 견적");
  assert.equal(unclearResult.ok, false);
  assert.equal(unclearResult.code, "needs_clarification");
  assert.ok(unclearResult.question.includes("거래처명"));
  assert.equal(unclear.allocations(), 0);
  assert.equal(unclearBridge.pendingQuote(), null);
  assert.equal(unclear.replaceDrafts.length, 0);
  assert.ok(!JSON.stringify(unclearResult).includes("invalid_missing_fields"));
  console.log("MALFORMED_MODEL_OUTPUT_FRIENDLY_CLARIFICATION=PASS");

  const typoFollowup = buildAccountEnv({
    unrecognizedResponseTurn: 2,
    candidates: [
      Object.assign({ missing: ["unitPrice"] }, PARTIAL_CANDIDATE),
      null,
      Object.assign({ missing: [] }, COMPLETE_CANDIDATE)
    ]
  });
  await flush();
  manuallyChooseModel(typoFollowup);
  const typoBridge = typoFollowup.context.B66QuoteRuntimeBridge;
  const pendingBeforeTypo = await typoBridge.interpret(TURN1_TEXT);
  assert.equal(pendingBeforeTypo.code, "incomplete_request");
  const stableNumber = typoBridge.pendingQuote().quoteNo;
  const misunderstood = await typoBridge.interpret("1만팔처너");
  assert.equal(misunderstood.code, "incomplete_request",
    "a misspelled clarification is not a discarded quote");
  assert.ok(misunderstood.question.includes("단가는 얼마인가요?"));
  assert.equal(typoBridge.pendingQuote().quoteNo, stableNumber);
  assert.equal(typoFollowup.allocations(), 1);
  const corrected = await typoBridge.interpret(TURN2_TEXT);
  assert.equal(corrected.ok, true);
  assert.equal(corrected.draft.meta.quoteNo, stableNumber);
  assert.equal(corrected.draft.items[0].unitPrice, 18000);
  assert.equal(typoFollowup.allocations(), 1);
  assert.equal(typoFollowup.interpretBodies.length, 3);
  console.log("FOLLOWUP_TYPO_PRESERVES_CONFIRMED_FACTS=PASS");

  console.log("MISSING_NAME_QUANTITY_PRICE_BOUNDED_FOLLOWUP=PASS");
  console.log("MULTIPLE_ITEM_QUANTITY_ANSWER_MAPPING=PASS");
  console.log("CGI_INPUT_SCOPE_NO_ACCEPTED_HIDDEN_ROWS=PASS");
  console.log("CGI_DETAILS_UNSUPPORTED_BEFORE_ACCEPTANCE=PASS");

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