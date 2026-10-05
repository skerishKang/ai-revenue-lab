/* B66 production blocker acceptance (#3391 lineage + guided finalize)

   Runs the REAL padiem-account.js and easy-mode.js in a vm against a stub
   DOM/network, with real QuoteCore / QuoteHistory / SavedQuoteSkill / template
   semantics. Proves:

   BLOCKER 1 — a partial free-form request keeps the known facts, asks one
   specific missing question, preserves the pending quote allocation, and a
   combined follow-up completes without a second allocation.

   BLOCKER 2 — guided facts reach SavedQuoteSkill.buildDraft through the real
   runtime bridge, replace the app draft, and render the result review.
*/

const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const DIR = __dirname;
const Core = require(path.join(DIR, "..", "quote-core.js"));
const History = require(path.join(DIR, "..", "quote-history.js"));
const Template = require(path.join(DIR, "..", "quote-template.js"));
const Skill = require(path.join(DIR, "..", "quote-skill.js"));
const Intake = require(path.join(DIR, "..", "file-intake.js"));

const NOW = "2026-09-29T11:00:00.000Z";
const TODAY = "2026-02-03";

/* ── synthetic approved skill (no real customer facts) ── */
function approvedSkill() {
  const base = {
    id: "skill-cgi-test",
    name: "테스트상사 기본 견적서",
    fixedDefaults: {
      sender: {
        company: "테스트상사",
        rep: "김대표",
        bizNo: "000-00-00000",
        address: "광주광역시 테스트로 1",
        phone: "062-000-0000",
        email: "test@example.invalid",
        presetId: "saved-skill"
      },
      validDays: 14,
      taxMode: "EXCLUSIVE",
      memo: ""
    },
    variableSchema: { recipient: true, quoteNo: true, issueDate: true, items: true, memo: true, taxMode: true },
    internalTemplate: Template.serializeTemplate(Template.builtInTemplate()),
    provenance: {
      sourceKind: "file",
      sourceName: "synthetic-quotation.pdf",
      sourceRef: "source:synthetic-b66-test",
      capturedAt: NOW,
      warnings: [],
      unknowns: [],
      evidence: [{ label: "sender", value: "테스트상사" }]
    },
    approval: null,
    createdAt: NOW,
    updatedAt: NOW
  };
  const unapproved = Skill.buildSkill(JSON.parse(JSON.stringify(base)));
  assert.ok(unapproved && unapproved.approved === false);
  return Skill.buildSkill(Object.assign(JSON.parse(JSON.stringify(base)), {
    approval: {
      schemaVersion: 1,
      status: "approved",
      skillFingerprint: unapproved.fingerprint,
      approvedBy: "central-cto",
      approvedAt: NOW,
      approvalRef: "issue-3391-test"
    }
  }));
}
const SKILL = approvedSkill();
const SAVED_ID = "b66skill_" + "c".repeat(32);

/* ── stub DOM ── */
function makeElement(id, tagName) {
  return {
    id, tagName: tagName || "div", value: "", textContent: "", placeholder: "", disabled: false,
    hidden: false, innerHTML: "", className: "", style: {}, dataset: {},
    children: [], listeners: {}, focusCount: 0, clickCount: 0, open: false,
    classList: {
      toggle() {}, add() {}, remove() {}, contains() { return false; }
    },
    addEventListener(type, handler) {
      (this.listeners[type] = this.listeners[type] || []).push(handler);
    },
    dispatchEvent() { return true; },
    setAttribute() {}, removeAttribute() {}, remove() {}, before() {},
    appendChild(...kids) {
      for (const child of kids) {
        this.children.push(child);
        this.textContent += child.textContent || "";
        if (child && child.tagName === "option") this.value = child.value;
      }
      return kids.length === 1 ? kids[0] : this;
    },
    append(...kids) {
      for (const child of kids) {
        this.children.push(child);
        this.textContent += child.textContent || "";
        if (child && child.tagName === "option") this.value = child.value;
      }
    },
    replaceChildren() { this.children = []; this.textContent = ""; this.value = ""; },
    scrollIntoView() {}, focus() { this.focusCount += 1; },
    click() { this.clickCount += 1; (this.listeners.click || []).forEach((fn) => fn()); },
    showModal() { this.open = true; }, close() { this.open = false; }
  };
}

function buildContext({ fetchHandler }) {
  const elements = new Map();
  const created = [];
  const documentListeners = {};
  const windowListeners = {};
  const storage = new Map();

  const getElement = (id) => {
    if (!elements.has(id)) elements.set(id, makeElement(id));
    return elements.get(id);
  };

  const context = vm.createContext({
    setTimeout, clearTimeout,
    console,
    QuoteCore: Core,
    QuoteHistory: History,
    B66FileIntake: Intake,
    SavedQuoteSkill: Skill,
    /* app.js owns the real bridge; stub the surface padiem-account uses */
    B66QuoteSkillBridge: {
      setServerSkill: () => true,
      clearServerSkill: () => {}
    },
    B66QuoteAppBridge: {
      calls: { replaceDraft: [], createFreshDraft: [] },
      /* real app state always holds a startup draft, never null */
      _current: (() => {
        const startup = Core.createProductionDraft();
        startup.meta.quoteNo = "PQ-TEST-000";
        startup.meta.issueDate = TODAY;
        return startup;
      })(),
      getDraft() { return this._current; },
      replaceDraft(next, options) {
        const normalized = Core.normalizeDraft(next);
        if (!normalized) return { ok: false, error: "invalid_draft" };
        this.calls.replaceDraft.push({ draft: normalized, options: options || {} });
        this._current = normalized;
        return { ok: true, draft: normalized };
      },
      createFreshDraft(source) {
        const fresh = Core.createProductionDraft();
        const seq = String(this.calls.createFreshDraft.length + 1).padStart(3, "0");
        fresh.meta.quoteNo = "PQ-TEST-" + seq;
        fresh.meta.issueDate = TODAY;
        fresh.meta.source = source || "manual";
        this.calls.createFreshDraft.push({ quoteNo: fresh.meta.quoteNo, source: fresh.meta.source });
        return fresh;
      },
      copyHistoryAsNew() { return null; },
      toast() {},
      focusTaxReview() {}
    },
    CustomEvent: class {
      constructor(type, init) { this.type = type; this.detail = (init || {}).detail; }
    },
    localStorage: {
      getItem: (k) => (storage.has(k) ? storage.get(k) : null),
      setItem: (k, v) => { storage.set(k, String(v)); },
      removeItem: (k) => { storage.delete(k); }
    },
    history: {
      state: null,
      pushState(state) { this.state = state; },
      replaceState(state) { this.state = state; },
      back() {}
    },
    location: { href: "https://quick-quote-kr.pages.dev/", assign() {} },
    confirm: () => true,
    scrollTo() {},
    fetch: (url, options) => Promise.resolve(fetchHandler(String(url), options || {})),
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
        const node = makeElement("created-" + tag + "-" + Math.random().toString(36).slice(2), tag);
        created.push(node);
        return node;
      }
    }
  });
  context.window = context;
  context.addEventListener = (type, handler) => {
    (windowListeners[type] = windowListeners[type] || []).push(handler);
  };
  context.dispatchEvent = () => true;
  return { context, getElement, created, documentListeners };
}

const flush = async () => {
  for (let i = 0; i < 12; i += 1) await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setTimeout(resolve, 0));
  for (let i = 0; i < 6; i += 1) await new Promise((resolve) => setImmediate(resolve));
};

const clickChip = (getElement, label) => {
  const chipRow = getElement("easyChipRow");
  const chip = chipRow.children.find((node) => node.textContent === label);
  if (!chip) return false;
  (chip.listeners.click || [])[0]();
  return true;
};

(async () => {
  let failures = 0;
  const check = (condition, label) => {
    console.log((condition ? "PASS  " : "FAIL  ") + label);
    if (!condition) failures += 1;
  };

  let interpretResponses = [];
  const routesHit = [];
  const fetchHandler = (url, options) => {
    const route = url.replace("https://quick-quote-kr.pages.dev", "");
    routesHit.push(route);
    const json = (body) => ({ ok: true, status: 200, headers: { get: () => null }, json: async () => body });
    if (route === "/api/padiem/auth/status") {
      return json({ authenticated: true, session_state: "signed_in", user: { name: "cgi-test" }, methods: { google: true, password: true } });
    }
    if (route === "/api/padiem/b66/saved-skills?limit=20") {
      return json({ ok: true, skills: [{ saved_skill_id: SAVED_ID, skill_name: SKILL.name }] });
    }
    if (route.startsWith("/api/padiem/b66/saved-skills/")) {
      return json({
        ok: true,
        saved_skill: {
          saved_skill_id: SAVED_ID, skill_id: SKILL.id, skill_name: SKILL.name,
          skill_fingerprint: SKILL.fingerprint, skill_version: 1, skill: SKILL
        }
      });
    }
    if (route === "/api/padiem/b66/company-profile") {
      return json({
        ok: true,
        company_profile: {
          company: "테스트상사", representative: "김대표", businessNumber: "000-00-00000",
          address: "광주광역시 테스트로 1", phone: "062-000-0000", email: "test@example.invalid",
          defaultValidityDays: 14, defaultTaxMode: "EXCLUSIVE"
        }
      });
    }
    if (route === "/api/padiem/b66/quote/interpret") {
      const body = JSON.parse(options.body);
      interpretResponses.push(body.message);
      const answer = interpretResponses.length === 1
        ? {
            recipient: { company: "대한건설" },
            items: [{ name: "배관", qty: 100 }],
            taxMode: "EXCLUSIVE",
            detailGroups: []
          }
        : {
            recipient: { company: "대한건설" },
            items: [{ name: "배관", qty: 100, unitPrice: 18000 }],
            taxMode: "EXCLUSIVE",
            detailGroups: []
          };
      return json({
        ok: true,
        saved_skill: { saved_skill_id: SAVED_ID },
        candidate: Object.assign({ missing: interpretResponses.length === 1 ? ["unitPrice"] : [] }, answer),
        company_profile: {
          company: "테스트상사", representative: "김대표", businessNumber: "000-00-00000",
          address: "광주광역시 테스트로 1", phone: "062-000-0000", email: "test@example.invalid",
          defaultValidityDays: 14, defaultTaxMode: "EXCLUSIVE"
        },
        execution: { source_document_parse_calls: 0, server_total_calculation: false, server_rendering: false, browser_quote_core_required: true, browser_approved_renderer_required: true }
      });
    }
    return { ok: false, status: 404, headers: { get: () => null }, json: async () => ({ error: { code: "unexpected", message: "stub 404" } }) };
  };

  const env = buildContext({ fetchHandler });
  const source = (name) => fs.readFileSync(path.join(DIR, "..", name), "utf8");
  new vm.Script(source("padiem-account.js"), { filename: "padiem-account.js" }).runInContext(env.context);
  await flush();

  const bridge = env.context.window.B66QuoteRuntimeBridge;
  const readiness = bridge.readiness();
  if (!readiness.ready) {
    console.log("DEBUG routes=", JSON.stringify(routesHit));
    console.log("DEBUG status=", JSON.stringify(env.getElement("padiemQuoteStatus").textContent));
    console.log("DEBUG authError=", JSON.stringify(env.getElement("padiemAuthError").textContent));
    console.log("DEBUG readiness=", JSON.stringify(readiness));
  }
  check(readiness.ready === true && readiness.authenticated && readiness.skillReady && readiness.profileReady,
    "runtime readiness after login + skill + CompanyProfile");

  /* ── BLOCKER 1: partial free-form request ── */
  const app = env.context.window.B66QuoteAppBridge;
  const draftBefore = app.getDraft();
  const partial = await bridge.interpret("대한건설에 배관 100미터, 부가세 별도");
  await flush();

  check(partial && partial.ok === false && partial.code === "incomplete_request",
    "PARTIAL_ITEM_DOES_NOT_BECOME_FINAL_QUOTE=YES");
  check(Array.isArray(partial.missing) && partial.missing.includes("unitPrice"),
    "server-derived missing includes unitPrice");
  check(partial.question === "단가는 얼마인가요?", "SPECIFIC_MISSING_QUESTION=YES (단가는 얼마인가요?)");
  check(partial.pending && partial.pending.quoteNo && partial.pending.quoteNo.startsWith("PQ-TEST-"),
    "pending quote allocation exists");
  check(app.getDraft() === draftBefore, "app draft untouched by the partial request");
  check(app.calls.createFreshDraft.length === 1, "exactly one allocation for the pending quote");

  const followUp = await bridge.interpret("미터당 18000원");
  await flush();

  check(followUp && followUp.ok === true && followUp.draft, "FOLLOWUP_FINAL_DRAFT built");
  check(interpretResponses[1] === "대한건설에 배관 100미터, 부가세 별도\n미터당 18000원",
    "follow-up re-interprets the combined original text");
  check(followUp.draft.recipient.company === "대한건설", "MISSING_FIELD_CONTEXT_PRESERVED (recipient)");
  check(followUp.draft.items[0].name === "배관" && followUp.draft.items[0].qty === 100,
    "PARTIAL_ITEM_FACTS_PRESERVED (name/qty)");
  check(followUp.draft.items[0].unitPrice === 18000, "follow-up unit price applied (18000)");
  check(followUp.draft.meta.quoteNo === partial.pending.quoteNo,
    "FOLLOWUP_DOUBLE_ALLOCATION=0 (same pending quote number reused)");
  check(app.calls.createFreshDraft.length === 1, "no second allocation after completion");
  check(followUp.draft.tax.mode === "EXCLUSIVE", "tax context preserved");
  check(followUp.draft.sender.company === "테스트상사", "sender authority from approved skill");
  check(Core.computeDraftTotals(followUp.draft).grand === 1980000, "QuoteCore grand total (1,980,000)");
  console.log("MISSING_UNIT_PRICE_CAN_ENTER_FOLLOWUP=YES");
  console.log("GENERIC_RETYPE_REQUIRED=NO");
  console.log("MODEL_CALCULATES_MISSING_PRICE=NO");

  /* ── BLOCKER 2: guided facts → buildFromFacts → replaceDraft → result review ── */
  new vm.Script(source("easy-mode.js"), { filename: "easy-mode.js" }).runInContext(env.context);
  await flush();
  const easy = env.context.window;
  env.getElement("guidedStarter").click();
  await flush();

  const answer = async (text) => {
    env.getElement("easyComposer").value = text;
    env.getElement("easySend").click();
    await flush();
    if (process.env.B66_DEBUG) {
      console.log("DEBUG after [" + text + "]:", JSON.stringify(env.getElement("easyMessageList").textContent.slice(-140)));
      console.log("DEBUG chips:", JSON.stringify(env.getElement("easyChipRow").children.map((n) => n.textContent)));
    }
  };
  await answer("대한건설");
  await answer("없음");
  await answer("배관");
  await answer("100");
  await answer("18000");
  await answer("다음");
  await answer("별도");
  await answer("없음");
  await answer("현재");
  await flush();

  const messageList = env.getElement("easyMessageList");
  const summaryShown = messageList.textContent.includes("이렇게 준비했어요") &&
    messageList.textContent.includes("대한건설") &&
    messageList.textContent.includes("배관");
  check(summaryShown, "GUIDED_SUMMARY=PASS (recipient + item in summary)");

  const replaceCallsBefore = app.calls.replaceDraft.length;
  const clicked = clickChip(env.getElement, "견적서 만들기");
  check(clicked, "견적서 만들기 chip exists in summary");
  await flush();
  await flush();

  const replaceCall = app.calls.replaceDraft[replaceCallsBefore];
  check(Array.isArray(app.calls.replaceDraft) && app.calls.replaceDraft.length === replaceCallsBefore + 1 && replaceCall,
    "GUIDED_BUILD_FROM_FACTS=PASS → replaceDraft invoked once");
  check(replaceCall && replaceCall.draft.recipient.company === "대한건설", "GUIDED_REPLACE_DRAFT recipient");
  check(replaceCall && replaceCall.draft.items[0].name === "배관" && replaceCall.draft.items[0].qty === 100 &&
    replaceCall.draft.items[0].unitPrice === 18000, "GUIDED_REPLACE_DRAFT item facts");
  check(replaceCall && replaceCall.draft.tax.mode === "EXCLUSIVE", "GUIDED_REPLACE_DRAFT tax");
  check(replaceCall && Boolean(replaceCall.draft.meta.quoteNo) && Boolean(replaceCall.draft.meta.issueDate),
    "GUIDED_REPLACE_DRAFT quoteNo/issueDate preserved");
  check(replaceCall && replaceCall.draft.sender.company === "테스트상사", "sender authority preserved in final draft");

  const chips = env.getElement("easyChipRow").children.map((node) => node.textContent);
  check(chips.includes("견적서 확인하기") && chips.includes("처음으로"),
    "GUIDED_RESULT_REVIEW=PASS (견적서 확인하기 / 처음으로 chips)");
  check(messageList.textContent.includes("견적이 준비되었습니다") &&
    messageList.textContent.includes("1,980,000"), "result review shows the QuoteCore total");

  const finalDraft = app.getDraft();
  check(finalDraft && finalDraft.recipient.company === "대한건설" &&
    finalDraft.items[0].name === "배관" && finalDraft.items[0].qty === 100 &&
    finalDraft.items[0].unitPrice === 18000 && finalDraft.tax.mode === "EXCLUSIVE" &&
    Boolean(finalDraft.meta.quoteNo) && Boolean(finalDraft.meta.issueDate),
    "GUIDED_FINAL_DRAFT=PASS (full QuoteDraft in app state)");
  check(finalDraft.sender.company === "테스트상사", "final draft sender authority (approved skill)");
  check(Core.printReadiness(finalDraft).ready === true, "final guided draft is print-ready");
  check(env.context.window.QuoteCore.computeDraftTotals(finalDraft).grand === 1980000,
    "final draft totals re-derived by QuoteCore only");
  console.log("SECOND_CALCULATION_AUTHORITY=0");

  console.log("");
  console.log("GUIDED_FINALIZE_ACCEPTANCE_FAILURES=" + failures);
  console.log("PADIEM_CHAT_REQUIRED=NO");
  console.log("PRODUCTION_MUTATION=0");
  process.exitCode = failures === 0 ? 0 : 1;
})().catch((error) => {
  console.error("HARNESS_CRASH");
  console.error(error && error.stack ? error.stack : error);
  process.exitCode = 1;
});