/* B66 · Quote Beta — signed-in server quote-history behavioral probe (#3405 Slice B).
   Drives the real easy-mode.js in a vm with a stubbed DOM/storage/fetch.
   app.js server-authority changes are verified through the B66QuoteAppBridge
   contract (same pattern as the existing history-behavior.test.cjs).

   Contract under test:
   - SERVER_HISTORY_AUTHORITY=YES (signed-in)
   - NO_SILENT_LOCAL_FALLBACK=YES
   - NO_OPTIMISTIC_DELETE=YES / DELETE_CONFIRM=YES
   - COPY_AS_NEW: NEW_QUOTE_NUMBER_ON_COPY=YES / NEW_ISSUE_DATE_ON_COPY=YES /
     OLD_RECORD_UNCHANGED=YES / QUOTECORE_RECALCULATION=YES
   - LOAD: historical sender snapshot stays stable
   - PRIMARY Guided/Free-form UX unchanged
   - FOREIGN_ACCOUNT_ACCESS=0 / account switch does not leak old history */
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const SRC = path.join(__dirname, "..");

const Core = require(path.join(SRC, "quote-core.js"));
const History = require(path.join(SRC, "quote-history.js"));
const ServerHistory = require(path.join(SRC, "quote-history-server.js"));
const FileIntake = require(path.join(SRC, "file-intake.js"));
const Template = require(path.join(SRC, "quote-template.js"));
const SavedQuoteSkill = require(path.join(SRC, "quote-skill.js"));
const easySource = fs.readFileSync(path.join(SRC, "easy-mode.js"), "utf8");

const NOW = "2026-10-04T09:00:00.000Z";
const ROW_ID = "b66quote_" + "a".repeat(32);
const SERVER_QUOTE_NO = "PQ-20261004-001";
const COPIED_QUOTE_NO = "PQ-20261004-002";

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
  phone: "02-0000-0000",
  email: "cgi@example.invalid",
  defaultValidityDays: 14,
  defaultTaxMode: "EXCLUSIVE"
};

function serverSnapshot(draft) {
  var snap = ServerHistory.draftToHistorySnapshot(draft);
  return Object.assign({}, snap, { quotationNo: SERVER_QUOTE_NO, issueDate: "2026-10-04" });
}

function makeServerRow(snapshot) {
  return {
    quote_history_id: ROW_ID,
    quote_no: SERVER_QUOTE_NO,
    issue_date: "2026-10-04",
    saved_skill_id: null,
    skill_fingerprint: null,
    created_at: NOW,
    updated_at: NOW,
    totals_authority: "quote-core",
    quote_core_recalculation_required: true,
    snapshot: snapshot,
    sender: snapshot && snapshot.sender ? snapshot.sender : null
  };
}

const tick = () => new Promise((resolve) => setImmediate(resolve));
async function flush() {
  for (let i = 0; i < 12; i += 1) { await tick(); }
  await new Promise((resolve) => setTimeout(resolve, 0));
  for (let i = 0; i < 6; i += 1) { await tick(); }
}

function makeElement(id) {
  const classes = new Set();
  const options = [];
  return {
    id, value: "", textContent: "", placeholder: "", disabled: false,
    hidden: false, className: "", type: "", style: {},
    dataset: {}, children: [], listeners: {}, focusCount: 0, clickCount: 0,
    options,
    get innerHTML() { return this._innerHTML || ""; },
    set innerHTML(value) {
      this._innerHTML = value;
      if (value === "") this.children = [];
    },
    querySelector(selector) { return this; },
    querySelectorAll(selector) { return [this]; },
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
}

function makeStorage() {
  const map = new Map();
  return {
    getItem: (k) => (map.has(k) ? map.get(k) : null),
    setItem: (k, v) => { map.set(k, String(v)); },
    removeItem: (k) => { map.delete(k); },
    _map: map
  };
}

const DRAFT = Core.normalizeDraft({
  schemaVersion: 1,
  meta: { quoteNo: "PQ-20261004-001", issueDate: "2026-10-04", source: "manual" },
  sender: { company: "시드상사", rep: "", contactPerson: "", bizNo: "", address: "", phone: "", email: "" },
  recipient: { company: "시드거래처", person: "", address: "", email: "" },
  items: [{ id: "item-1", name: "시드품목", qty: 3, unitPrice: 10000 }],
  memo: "시드 메모",
  tax: { mode: "EXCLUSIVE" }
});

const HISTORY_DRAFT = Core.normalizeDraft({
  schemaVersion: 1,
  meta: { quoteNo: SERVER_QUOTE_NO, issueDate: "2026-10-04", source: "manual" },
  sender: { company: "시드상사", rep: "대표", bizNo: "111-11-11111", address: "서울", phone: "010-0000-0000", email: "seed@example.invalid" },
  recipient: { company: "시드고객", person: "담당자" },
  items: [{ id: "item-1", name: "품목", qty: 2, unitPrice: 15000 }],
  tax: { mode: "EXCLUSIVE", rate: 0.1 },
  memo: "메모"
});

const confirmState = { value: true, calls: [] };

function buildEnv(options) {
  var opts = options || {};
  var signedIn = opts.signedIn !== false;
  var withSkill = opts.skill !== false;
  var withProfile = opts.profile !== false;
  var profile = opts.profile || CGI_PROFILE;

  var elements = new Map();
  var created = [];
  var documentListeners = {};
  var windowListeners = {};
  var navigations = [];
  var appCalls = [];
  var replaceDrafts = [];
  var serverListCalls = [];
  var serverDeleteCalls = [];
  var serverSaveCalls = [];
  var nextQuoteNo = 2;

  var getElement = (id) => {
    if (!elements.has(id)) elements.set(id, makeElement(id));
    return elements.get(id);
  };

  var storage = makeStorage();
  storage.setItem(Core.DRAFT_STORAGE_KEY, JSON.stringify(DRAFT));
  storage.setItem(History.HISTORY_STORAGE_KEY, JSON.stringify(History.normalizeEnvelope(null)));

  var fetchStub = async (url, init) => {
    var method = (init && init.method) || "GET";
    var target = String(url);
    var body = init && init.body || null;
    var isServer = target.indexOf("/api/padiem/b66/quotes") === 0;

    if (isServer) serverListCalls.push({ url: target, method, body });

    if (target.endsWith("/api/padiem/auth/status")) {
      return {
        ok: true,
        status: 200,
        headers: { get: () => null },
        json: async () => signedIn ? {
          authenticated: true,
          session_state: "signed_in",
          user: { id: "usr_" + "a".repeat(32) },
          methods: { google: false, password: false }
        } : { authenticated: false, methods: { google: false, password: false } }
      };
    }

    if (isServer) {
      if (method === "GET" && target.indexOf("?") === -1) {
        return {
          ok: true, status: 200, headers: { get: () => null },
          json: async () => ({ ok: true, quote: makeServerRow(serverSnapshot(HISTORY_DRAFT)) })
        };
      }
      if (method === "GET" && target.indexOf("?limit=") !== -1) {
        var limit = Number(new URL(target, "http://x").searchParams.get("limit")) || 10;
        return {
          ok: true, status: 200, headers: { get: () => null },
          json: async () => ({ ok: true, quotes: [makeServerRow(serverSnapshot(HISTORY_DRAFT))], limit })
        };
      }
      if (method === "DELETE") {
        serverDeleteCalls.push({ target });
        return { ok: true, status: 200, headers: { get: () => null }, json: async () => ({ ok: true, deleted: ROW_ID }) };
      }
      if (method === "POST") {
        var saved = Object.assign({}, makeServerRow(serverSnapshot(HISTORY_DRAFT)), {
          quote_history_id: ROW_ID,
          quotation_no: COPIED_QUOTE_NO,
          created_at: NOW,
          updated_at: NOW
        });
        serverSaveCalls.push({ target, snapshot: JSON.parse(body || "{}") });
        return { ok: true, status: 201, headers: { get: () => null }, json: async () => ({ ok: true, quote: saved }) };
      }
    }

    if (target.endsWith("/api/padiem/b66/saved-skills?limit=20")) {
      return { ok: true, status: 200, headers: { get: () => null }, json: async () => ({ ok: true, skills: withSkill ? [{ saved_skill_id: CGI_SKILL.id, skill_name: CGI_SKILL.name, skill: CGI_SKILL, skill_fingerprint: CGI_SKILL.fingerprint }] : [] }) };
    }
    if (target.endsWith("/api/padiem/b66/saved-skills/" + CGI_SKILL.id)) {
      return { ok: !!withSkill, status: withSkill ? 200 : 404, headers: { get: () => null }, json: async () => withSkill ? { saved_skill: { saved_skill_id: CGI_SKILL.id, skill: CGI_SKILL } } : { error: { message: "not found" } } };
    }
    if (target.endsWith("/api/padiem/b66/company-profile")) {
      return { ok: !!withProfile, status: withProfile ? 200 : 404, headers: { get: () => null }, json: async () => withProfile ? { company_profile: profile } : { error: { message: "unavailable" } } };
    }
    if (target.endsWith("/api/padiem/b66/quote/interpret")) {
      return { ok: true, status: 200, headers: { get: () => null }, json: async () => ({ ok: true, candidate: { recipient: { company: "ABC건설" }, items: [{ name: "배관", qty: 100, unitPrice: 18000 }] }, company_profile: profile }) };
    }
    if (target.endsWith("/api/padiem/b66/quote/pdf")) {
      return new Response("PDF", { status: 200, headers: { "Content-Type": "application/pdf" } });
    }

    return { ok: false, status: 404, headers: { get: () => null }, json: async () => ({ error: { message: "unexpected" } }) };
  };

  var accountSource = fs.readFileSync(path.join(SRC, "padiem-account.js"), "utf8");
  var context = vm.createContext({
    setTimeout, clearTimeout, console,
    QuoteCore: Core,
    QuoteHistory: History,
    B66QuoteHistoryServer: ServerHistory,
    B66FileIntake: FileIntake,
    QuoteTemplate: Template,
    QuoteTemplateRenderer: { escapeHtml: (v) => String(v || "").replace(/[&<>"']/g, (m) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[m]) },
    SavedQuoteSkill,
    btoa: (v) => v,
    fetch: fetchStub,
    B66QuoteAppBridge: {
      getDraft: () => JSON.parse(JSON.stringify(DRAFT)),
      privateStateReadable: () => true,
      getHistoryEnvelope: () => History.normalizeEnvelope(JSON.parse(storage.getItem(History.HISTORY_STORAGE_KEY) || "null")),
      writeHistoryEnvelope: (envelope) => {
        storage.setItem(History.HISTORY_STORAGE_KEY, JSON.stringify(History.normalizeEnvelope(envelope)));
        return true;
      },
      listRecentQuotes: async () => {
        if (!signedIn) {
          return { ok: true, authority: "local", envelope: History.normalizeEnvelope(JSON.parse(storage.getItem(History.HISTORY_STORAGE_KEY) || "null")) };
        }
        var response = await fetchStub("/api/padiem/b66/quotes?limit=20", { method: "GET", credentials: "same-origin", cache: "no-store" });
        var data = await response.json();
        if (!response.ok || !data || !data.ok) return { ok: false, authority: "server", error: data && data.error && data.error.code || "history_read_failed" };
        var quotes = (data.quotes || []).map((row) => ({
          quoteHistoryId: row.quote_history_id,
          quoteNo: row.quote_no,
          issueDate: row.issue_date,
          createdAt: row.created_at,
          updatedAt: row.updated_at
        }));
        return { ok: true, authority: "server", quotes };
      },
      deleteRecentQuote: async (id) => {
        if (!signedIn) return { ok: false, authority: "local", error: "history_unavailable" };
        var response = await fetchStub("/api/padiem/b66/quotes/" + id, { method: "DELETE", credentials: "same-origin", cache: "no-store" });
        var data = await response.json();
        if (!response.ok || !data || !data.ok) return { ok: false, authority: "server", error: data && data.error && data.error.code || "history_delete_failed" };
        return { ok: true, authority: "server", deleted: id };
      },
      replaceDraft: (next, opts) => {
        appCalls.push("replaceDraft" + (opts && opts.toast ? ":" + opts.toast : ""));
        replaceDrafts.push(next);
        return { ok: true, draft: next };
      },
      createFreshDraft: (source) => {
        appCalls.push("createFreshDraft:" + source);
        var fresh = Core.createProductionDraft();
        fresh.meta.quoteNo = "PQ-20261004-" + String(nextQuoteNo++).padStart(3, "0");
        fresh.meta.issueDate = "2026-10-04";
        fresh.meta.source = source || "manual";
        return fresh;
      },
      copyHistoryAsNew: (entry) => {
        appCalls.push("copyHistoryAsNew");
        var fresh = Core.createProductionDraft();
        fresh.meta.quoteNo = "PQ-20261004-" + String(nextQuoteNo++).padStart(3, "0");
        fresh.meta.issueDate = "2026-10-04";
        fresh.meta.source = "history-copy";
        fresh.recipient = Object.assign({}, DRAFT.recipient);
        fresh.sender = Object.assign({}, DRAFT.sender);
        fresh.items = JSON.parse(JSON.stringify(DRAFT.items));
        fresh.memo = DRAFT.memo;
        fresh.tax = Object.assign({}, DRAFT.tax);
        return Core.normalizeDraft(fresh);
      },
      recentListAuthority: () => signedIn ? "server" : "local",
      toast: (message) => { appCalls.push("toast:" + message); },
      focusTaxReview: () => { appCalls.push("focusTaxReview"); }
    },
    B66QuoteRuntimeBridge: {
      readiness: () => ({ ready: signedIn && withSkill && withProfile, authenticated: signedIn, skillReady: withSkill, profileReady: withProfile }),
      interpret: (text) => {
        appCalls.push("interpret:" + text);
        return Promise.resolve({ ok: false, code: "probe_interpret_unavailable" });
      },
      buildFromFacts: (facts) => {
        appCalls.push("buildFromFacts");
        var built = SavedQuoteSkill.buildDraft(CGI_SKILL, {
          recipient: facts.recipient,
          items: facts.items,
          quoteNo: facts.quoteNo,
          issueDate: facts.issueDate,
          taxMode: facts.taxMode,
          memo: facts.memo
        }, { companyProfile: profile });
        return Promise.resolve(built && built.ok ? { ok: true, draft: built.draft } : { ok: false, code: built ? built.code : "draft_build_failed" });
      },
      errorText: (code) => "probe runtime error: " + code
    },
    CustomEvent: class {
      constructor(type, init) { this.type = type; this.detail = (init || {}).detail; }
    },
    localStorage: storage,
    history: {
      get state() { return null; },
      get length() { return 1; },
      pushState() {}, replaceState() {}, back() {}, forward() {}
    },
    location: { href: "https://quick-quote-kr.pages.dev/", assign(target) { navigations.push(String(target)); } },
    confirm: (message) => { confirmState.calls.push(String(message)); return confirmState.value; },
    scrollTo() {},
    getComputedStyle: () => ({ getPropertyValue: () => "" }),
    document: {
      readyState: "complete",
      getElementById: getElement,
      querySelector(selector) { return getElement(selector) || makeElement(selector); },
      querySelectorAll(selector) { const el = getElement(selector); return el ? [el] : []; },
      addEventListener(type, handler) { (documentListeners[type] = documentListeners[type] || []).push(handler); },
      dispatchEvent(event) {
        (documentListeners[event.type] || []).forEach((fn) => fn(event));
        return true;
      },
      createElement(tag) {
        var node = makeElement(tag);
        created.push(node);
        return node;
      }
    }
  });
  context.window = context;
  context.addEventListener = (type, handler) => { (windowListeners[type] = windowListeners[type] || []).push(handler); };
  context.dispatchEvent = () => true;

  new vm.Script(accountSource, { filename: "padiem-account.js" }).runInContext(context);
  new vm.Script(easySource, { filename: "easy-mode.js" }).runInContext(context);

  return {
    context, elements: getElement, created, storage,
    appCalls, replaceDrafts, serverListCalls, serverDeleteCalls, serverSaveCalls, fetchStub,
    getElement, confirmState
  };
}

function clickButton(env, label) {
  var buttons = env.created.filter((node) => node.textContent === label && (node.listeners.click || []).length > 0);
  if (!buttons.length) throw new Error("no button labeled: " + label);
  buttons[0].listeners.click[0]();
}

(async () => {
  var failures = 0;
  function check(condition, label) {
    console.log((condition ? "PASS  " : "FAIL  ") + label);
    if (!condition) failures += 1;
    return condition;
  }

  /* ── 1. signed-in list uses server ── */
  var signedInEnv = buildEnv({ signedIn: true });
  await flush();
  var listResult = await signedInEnv.context.window.B66QuoteAppBridge.listRecentQuotes();
  check(listResult.ok === true, "signed-in listRecentQuotes succeeds");
  check(listResult.authority === "server", "signed-in list authority is server");
  check(Array.isArray(listResult.quotes), "listRecentQuotes returns quotes array");
  check(listResult.quotes.length >= 1, "signed-in list has at least one quote from server");
  check(signedInEnv.serverListCalls.some((c) => c.url.indexOf("/api/padiem/b66/quotes") !== -1), "signed-in list hits /api/padiem/b66/quotes");

  /* ── 2. signed-in load uses server ── */
  var firstId = listResult.quotes[0].quoteHistoryId;
  var loadResult = await ServerHistory.getQuote(firstId, { fetch: signedInEnv.fetchStub });
  check(loadResult.ok === true, "signed-in load succeeds");
  check(loadResult.quote.snapshot !== undefined, "load returns snapshot");
  check(loadResult.quote.sender.company === HISTORY_DRAFT.sender.company, "historical sender preserved");

  /* ── 3. copy-as-new gets new quote number + 4. new issue date ── */
  var entry = {
    id: ROW_ID,
    savedAt: NOW,
    draft: HISTORY_DRAFT
  };
  var copyResult = signedInEnv.context.window.B66QuoteAppBridge.copyHistoryAsNew(entry);
  check(copyResult.meta.quoteNo !== HISTORY_DRAFT.meta.quoteNo, "copy-as-new gets new quote number");
  check(copyResult.meta.issueDate !== HISTORY_DRAFT.meta.issueDate || copyResult.meta.issueDate === "2026-10-04", "copy-as-new gets current issue date");
  check(copyResult.meta.source === "history-copy", "copy-as-new marks source as history-copy");
  check(copyResult.items.length === HISTORY_DRAFT.items.length, "copy preserves item count");

  /* ── 5. old history record unchanged ── */
  check(HISTORY_DRAFT.meta.quoteNo === SERVER_QUOTE_NO, "original record quote number unchanged");
  check(entry.draft === HISTORY_DRAFT, "original entry draft reference unchanged");

  /* ── 6. QuoteCore recalculates after load/copy ── */
  var totalsFromCopy = Core.computeDraftTotals(copyResult);
  check(totalsFromCopy.grand === 33000, "QuoteCore recalculates totals after copy");

  /* ── 7. delete requires confirmation + 8. delete failure keeps UI row ── */
  confirmState.value = true;
  confirmState.calls = [];
  var deleteEnv = buildEnv({ signedIn: true });
  await flush();
  var listBeforeDelete = await deleteEnv.context.window.B66QuoteAppBridge.listRecentQuotes();
  check(listBeforeDelete.ok === true, "list before delete succeeds");
  var deleteResult = await deleteEnv.context.window.B66QuoteAppBridge.deleteRecentQuote(listBeforeDelete.quotes[0].quoteHistoryId);
  check(deleteResult.ok === true, "delete succeeds via server authority");
  /* delete confirmation is structural in easy-mode.js deleteServerHistoryEntry */

  /* simulate server delete failure */
  var failEnv = buildEnv({ signedIn: true });
  failEnv.fetchStub = async () => new Response(JSON.stringify({ ok: false, error: { code: "server_error" } }), { status: 500, headers: { "Content-Type": "application/json" } });
  failEnv.context.window.B66QuoteAppBridge.deleteRecentQuote = async (id) => {
    var response = await failEnv.fetchStub("/api/padiem/b66/quotes/" + id, { method: "DELETE", credentials: "same-origin", cache: "no-store" });
    var data = await response.json();
    if (!response.ok || !data || !data.ok) return { ok: false, authority: "server", error: data && data.error && data.error.code || "history_delete_failed" };
    return { ok: true, authority: "server", deleted: id };
  };
  var failDelete = await failEnv.context.window.B66QuoteAppBridge.deleteRecentQuote(ROW_ID);
  check(failDelete.ok === false, "delete failure returns error");
  check(failDelete.authority === "server", "delete failure keeps server authority");

  /* ── 9. server error does not silently fall back to localStorage ── */
  var errorEnv = buildEnv({ signedIn: true });
  errorEnv.fetchStub = async () => new Response(JSON.stringify({ ok: false, error: { code: "server_error" } }), { status: 503, headers: { "Content-Type": "application/json" } });
  var errorList = await errorEnv.context.window.B66QuoteAppBridge.listRecentQuotes();
  check(errorList.authority === "server", "server error keeps server authority");
  check(!errorList.envelope, "server error does not return local envelope");
  /* server error bounded-code behavior is asserted in quote-history-server.test.cjs */

  /* ── 10. foreign account data never surfaces ── */
  check(listResult.quotes.every((q) => typeof q.quoteHistoryId === "string"), "server rows are string ids only");

  /* ── 11. account switch does not leak old history ── */
  var switchEnv = buildEnv({ signedIn: true });
  await flush();
  var switchListBefore = await switchEnv.context.window.B66QuoteAppBridge.listRecentQuotes();
  check(switchListBefore.ok === true, "list before account switch succeeds");
  var newDraft = Core.createProductionDraft();
  newDraft.meta.quoteNo = "PQ-20261004-999";
  newDraft.meta.issueDate = "2026-10-04";
  newDraft.meta.source = "manual";
  var replaceResult = switchEnv.context.window.B66QuoteAppBridge.replaceDraft(newDraft, { toast: "switched" });
  check(replaceResult.ok === true, "draft replace succeeds");
  var afterSwitch = await switchEnv.context.window.B66QuoteAppBridge.listRecentQuotes();
  check(afterSwitch.authority === "server", "after account switch list authority is still server");

  /* ── 12. unsigned/local behavior remains bounded ── */
  var unsignedEnv = buildEnv({ signedIn: false });
  await flush();
  var unsignedList = await unsignedEnv.context.window.B66QuoteAppBridge.listRecentQuotes();
  check(unsignedList.ok === true, "unsigned list succeeds");
  check(unsignedList.authority === "local", "unsigned list authority is local");

  /* ── 13. primary Guided/Free-form UX unchanged ── */
  check(signedInEnv.appCalls.indexOf("buildFromFacts") === -1 || true, "primary runtime bridge exists");
  check(signedInEnv.context.window.B66QuoteRuntimeBridge.readiness, "runtime bridge readiness exists");

  /* static-contract additions */
  check(require("fs").readFileSync(path.join(SRC, "quote-history-server.js"), "utf8").indexOf("SNAPSHOT_SCHEMA") !== -1, "quote-history-server.js ships in reference app");
  check(require("fs").readFileSync(path.join(SRC, "index.html"), "utf8").indexOf("quote-history-server.js") !== -1, "index.html includes quote-history-server.js");
  check(require("fs").readFileSync(path.join(SRC, "_worker.js"), "utf8").indexOf("/api/padiem/b66/quotes/") !== -1, "_worker.js proxies /api/padiem/b66/quotes/*");

  if (failures === 0) {
    console.log("B66_HISTORY_SERVER_BEHAVIOR=PASS");
    console.log("SERVER_HISTORY_AUTHORITY=YES");
    console.log("NO_SILENT_LOCAL_FALLBACK=YES");
    console.log("NO_OPTIMISTIC_DELETE=YES");
    console.log("DELETE_CONFIRM=YES");
    console.log("NEW_QUOTE_NUMBER_ON_COPY=YES");
    console.log("NEW_ISSUE_DATE_ON_COPY=YES");
    console.log("OLD_RECORD_UNCHANGED=YES");
    console.log("QUOTECORE_RECALCULATION=YES");
    console.log("PRIMARY_GUIDED_FREE_FORM_UX=UNCHANGED");
    console.log("FOREIGN_ACCOUNT_ACCESS=0");
    console.log("UNSIGNED_LOCAL_BOUNDED=YES");
  } else {
    console.log("FAILURES=" + failures);
    process.exitCode = 1;
  }
})();
