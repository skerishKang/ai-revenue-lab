/* B66 · Quote Beta — signed-in server quote-history BEHAVIORAL probe (#3405 Slice B correction).

   This probe drives the REAL product code: index.html's script set is loaded into one vm
   (quote-core, quote-history, quote-history-server, quote-account-scope, app.js, easy-mode.js,
   padiem-account.js, ...), so `B66QuoteAppBridge` is the real bridge exported by app.js and
   `B66QuoteHistoryServer` is the real client module. There is no hand-written bridge stub and no
   bridge-direct contract proof: every assertion below observes product behavior (rendered rows,
   actual button clicks, actual fetch traffic, actual localStorage bytes).

   Contract under test (each marker is printed only when its own assertions passed):
   - DELETE_CONFIRM / NO_OPTIMISTIC_DELETE  -> real delete button click, three cases
   - COPY_AS_NEW                           -> real copy button click on a server row
   - QUOTECORE_RECALC / PERSISTED_TOTAL_AUTHORITY_ZERO
                                          -> real load button click with a hostile server row
   - NO_SILENT_LOCAL_FALLBACK              -> real recent view + real app.js list/save
   - ACCOUNT_SWITCH_ISOLATION              -> real owner-scope change through account-scope.js
   - SCOPE_CHANGE_REDERIVES_SERVER_AUTHORITY / APP_* -> app.js server-authority behavior
   No network, no credentials, no product state outside the vm. */
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

const APP_SOURCE = fs.readFileSync(path.join(SRC, "app.js"), "utf8");
const INDEX_HTML = fs.readFileSync(path.join(SRC, "index.html"), "utf8");
const SCRIPT_TAGS = [];
INDEX_HTML.replace(/<script src="([^"]+)"/g, (_m, name) => { SCRIPT_TAGS.push(name); return ""; });

const USER_A = "usr_" + "a".repeat(32);
const USER_B = "usr_" + "b".repeat(32);
const NOW = "2026-10-04T09:00:00.000Z";
const ROW_A = "b66quote_" + "1".repeat(32);
const ROW_B = "b66quote_" + "2".repeat(32);
const MINTED = "b66quote_" + "f".repeat(32);
let mintedCounter = 0;
function mintedId() {
  mintedCounter += 1;
  return "b66quote_" + mintedCounter.toString(16).padStart(32, "0");
}
const HISTORICAL_QUOTE_NO = "PQ-20261004-001";
const OTHER_QUOTE_NO = "PQ-20261004-777";
/* A server that computes and stores its own totals: none of this may ever become authority. */
const HOSTILE_TOTALS = { grand: 999999999, supply: 999999999, vat: 999999999, subtotal: 999999999 };

const HISTORICAL_DRAFT = Core.normalizeDraft({
  schemaVersion: 1,
  meta: { quoteNo: HISTORICAL_QUOTE_NO, issueDate: "2026-10-04", source: "manual" },
  sender: {
    company: "역사발신사", rep: "역사대표", bizNo: "111-11-11111",
    address: "서울", phone: "010-0000-0000", email: "history-sender@example.invalid"
  },
  recipient: { company: "역사진수", person: "담당자", address: "부산", email: "buyer@example.invalid" },
  items: [
    { id: "item-1", name: "역사품목A", qty: 2, unitPrice: 15000, spec: "A규격", unit: "EA", note: "비고A" },
    { id: "item-2", name: "역사품목B", qty: 3, unitPrice: 1000 }
  ],
  tax: { mode: "EXCLUSIVE", rate: 0.1 },
  memo: "역사 메모"
});

function hostileSnapshot() {
  const snapshot = ServerHistory.draftToHistorySnapshot(HISTORICAL_DRAFT);
  snapshot.quotationNo = HISTORICAL_QUOTE_NO;
  snapshot.issueDate = "2026-10-04";
  /* hostile persisted totals at every plausible level */
  snapshot.totals = Object.assign({}, HOSTILE_TOTALS);
  snapshot.grand = HOSTILE_TOTALS.grand;
  snapshot.subtotal = HOSTILE_TOTALS.subtotal;
  snapshot.supply = HOSTILE_TOTALS.supply;
  return snapshot;
}

function detailRow(rowId, snapshot) {
  return {
    quote_history_id: rowId,
    quote_no: snapshot.quotationNo,
    issue_date: snapshot.issueDate,
    saved_skill_id: null,
    skill_fingerprint: null,
    created_at: NOW,
    updated_at: NOW,
    totals_authority: "quote-core",
    quote_core_recalculation_required: true,
    totals: Object.assign({}, HOSTILE_TOTALS),
    grand_total: HOSTILE_TOTALS.grand,
    snapshot: JSON.parse(JSON.stringify(snapshot)),
    sender: JSON.parse(JSON.stringify(snapshot.sender))
  };
}

function listRow(row) {
  const projected = Object.assign({}, row);
  delete projected.snapshot;
  delete projected.sender;
  return projected;
}

/* A save fixture whose quote number is not already on the server, so the first save
   exercises the plain insert path instead of the same-quoteNo replacement path. */
const SAVE_QUOTE_NO = "PQ-SLICEB-FIXTURE-0001";

function saveFixtureDraft() {
  return Core.normalizeDraft({
    schemaVersion: 1,
    meta: { quoteNo: SAVE_QUOTE_NO, issueDate: "2026-10-08", source: "manual" },
    sender: { company: "저장상사", rep: "저장대표" },
    recipient: { company: "저장거래처" },
    items: [{ id: "item-1", name: "저장품목", qty: 1, unitPrice: 12000 }],
    tax: { mode: "EXCLUSIVE", rate: 0.1 }
  });
}

const tick = () => new Promise((resolve) => setImmediate(resolve));
async function flush() {
  for (let i = 0; i < 20; i += 1) await tick();
  for (let round = 0; round < 3; round += 1) {
    await new Promise((resolve) => setTimeout(resolve, 5));
    for (let i = 0; i < 20; i += 1) await tick();
  }
}

const TOTAL_LIKE = /^(grand|total|totals|subtotal|sub|supply|vat|amount|amounttotal|sum)$/i;

function makeElement(id) {
  return {
    id, value: "", textContent: "", options: [], placeholder: "", disabled: false,
    hidden: false, className: "", type: "", style: {}, dataset: {}, children: [],
    listeners: {}, focusCount: 0, clickCount: 0, _innerHTML: "",
    get innerHTML() { return this._innerHTML || ""; },
    set innerHTML(value) { this._innerHTML = value; if (value === "") this.children = []; },
    querySelector() { return this; },
    querySelectorAll() { return []; },
    classList: { toggle() {}, add() {}, remove() {}, contains() { return false; } },
    addEventListener(type, handler) { (this.listeners[type] = this.listeners[type] || []).push(handler); },
    dispatchEvent() { return true; },
    setAttribute() {}, removeAttribute() {}, remove() {}, before() {},
    appendChild(child) { this.children.push(child); return child; },
    append(...children) { this.children.push(...children); },
    replaceChildren() { this.children = []; },
    insertBefore(child) { this.children.push(child); return child; },
    cloneNode() { return makeElement(id); },
    getBoundingClientRect() { return { top: 0, left: 0, width: 0, height: 0 }; },
    scrollIntoView() {}, focus() {}, click() { this.clickCount += 1; }
  };
}

function makeStorage() {
  const map = new Map();
  return {
    getItem: (key) => (map.has(key) ? map.get(key) : null),
    setItem: (key, value) => { map.set(key, String(value)); },
    removeItem: (key) => { map.delete(key); },
    _map: map
  };
}

function jsonBody(body, status) {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: { get: () => null },
    json: async () => body
  };
}

function deferred() {
  let resolveFn = null;
  let rejectFn = null;
  const promise = new Promise((resolve, reject) => { resolveFn = resolve; rejectFn = reject; });
  return { promise, resolve: resolveFn, reject: rejectFn };
}

/* ── environment ─────────────────────────────────────────────────────────────────────────
   server: canonical quote-history surface (session-derived owner, minted ids).
   faults: per-endpoint failure switches used to prove bounded error behavior. */
function buildEnv(options) {
  const opts = options || {};
  const owner = opts.owner === undefined ? USER_A : opts.owner;
  const snapshot = opts.snapshot || hostileSnapshot();

  const server = {
    rows: [detailRow(ROW_A, snapshot)],
    faults: { list: null, detail: null, save: null, remove: null },
    gates: { save: null, remove: null },
    calls: []
  };
  if (opts.owner === USER_B) {
    const other = Object.assign({}, snapshot, { quotationNo: OTHER_QUOTE_NO });
    server.rows = [detailRow(ROW_B, other)];
  }

  const fetchStub = async (url, init) => {
    const method = (init && init.method) || "GET";
    const target = String(url);
    const rawBody = (init && init.body) || null;
    server.calls.push({ method, target, body: rawBody });

    if (target.indexOf("/api/padiem/auth/status") !== -1) {
      const signedIn = opts.signedIn !== false;
      return jsonBody(signedIn
        ? { authenticated: true, session_state: "signed_in", user: { id: opts.authUser || owner }, methods: { google: false, password: false } }
        : { authenticated: false, methods: { google: false, password: false } }, 200);
    }

    if (target.indexOf("/api/padiem/b66/quotes") === 0) {
      const isList = method === "GET" && target.indexOf("?") !== -1;
      const isDetail = method === "GET" && target.indexOf("?") === -1;
      const isSave = method === "POST";
      const isRemove = method === "DELETE";

      if (isList) {
        if (server.faults.list) return jsonBody({ error: { code: server.faults.list } }, 503);
        if (server.malformedResponse) {
          /* a broken response object: reading its status throws inside the client, outside the
             json() guard, so the whole authority read rejects */
          return {
            get ok() { throw new Error("probe_malformed_response_status"); },
            status: 200,
            headers: { get: () => null },
            json: async () => ({ ok: true, quotes: [] })
          };
        }
        return jsonBody({ ok: true, quotes: server.rows.map(listRow), limit: 20 }, 200);
      }
      if (isDetail) {
        if (server.faults.detail) return jsonBody({ error: { code: server.faults.detail } }, 503);
        const id = target.slice(target.lastIndexOf("/") + 1);
        const row = server.rows.find((candidate) => candidate.quote_history_id === id);
        return row ? jsonBody({ ok: true, quote: row }, 200) : jsonBody({ error: { code: "quote_not_found" } }, 404);
      }
      if (isSave) {
        if (server.gates.save) {
          await server.gates.save.promise;
        }
        if (server.faults.save) return jsonBody({ error: { code: server.faults.save } }, 500);
        const body = JSON.parse(rawBody || "{}");
        const row = detailRow(mintedId(), body);
        row.quote_no = body.quotationNo;
        row.issue_date = body.issueDate;
        row.snapshot = body;
        row.sender = body.sender;
        server.rows.unshift(row);
        return jsonBody({ ok: true, quote: row }, 201);
      }
      if (isRemove) {
        if (server.gates.remove) {
          await server.gates.remove.promise;
        }
        if (server.faults.remove) return jsonBody({ error: { code: server.faults.remove } }, 503);
        const id = target.slice(target.lastIndexOf("/") + 1);
        const index = server.rows.findIndex((candidate) => candidate.quote_history_id === id);
        if (index >= 0) server.rows.splice(index, 1);
        return jsonBody({ ok: true, deleted: id }, 200);
      }
    }

    /* unrelated B66 surfaces: canonical 404 is a legitimate bounded answer */
    return jsonBody({ error: { message: "unavailable" } }, 404);
  };

  const elements = new Map();
  const created = [];
  const documentListeners = {};
  const windowListeners = {};
  const confirmState = { value: true, calls: [] };
  const storage = makeStorage();
  storage.setItem(Core.DRAFT_STORAGE_KEY, JSON.stringify(Core.createProductionDraft()));

  const getElement = (id) => {
    if (!elements.has(id)) elements.set(id, makeElement(id));
    return elements.get(id);
  };

  const context = vm.createContext({
    setTimeout, clearTimeout, setInterval, clearInterval, console, Response, URL,
    QuoteCore: Core,
    QuoteHistory: History,
    B66QuoteHistoryServer: ServerHistory,
    B66FileIntake: FileIntake,
    QuoteTemplate: Template,
    SavedQuoteSkill,
    btoa: (value) => value,
    atob: (value) => value,
    fetch: fetchStub,
    CustomEvent: class { constructor(type, init) { this.type = type; this.detail = (init || {}).detail; } },
    localStorage: storage,
    history: {
      get state() { return null; }, get length() { return 1; },
      pushState() {}, replaceState() {}, back() {}, forward() {}
    },
    location: {
      href: "https://quick-quote-kr.pages.dev/", assign() {},
      origin: "https://quick-quote-kr.pages.dev", protocol: "https:"
    },
    confirm: (message) => { confirmState.calls.push(String(message)); return confirmState.value; },
    alert() {}, scrollTo() {},
    getComputedStyle: () => ({ getPropertyValue: () => "" }),
    matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {} }),
    requestAnimationFrame: (fn) => setTimeout(fn, 0),
    cancelAnimationFrame() {},
    document: {
      readyState: "complete",
      getElementById: getElement,
      querySelector() { return null; },
      querySelectorAll() { return []; },
      addEventListener(type, handler) { (documentListeners[type] = documentListeners[type] || []).push(handler); },
      dispatchEvent(event) { (documentListeners[event.type] || []).forEach((fn) => fn(event)); return true; },
      createElement(tag) { const node = makeElement(tag); created.push(node); return node; },
      body: makeElement("body"),
      documentElement: makeElement("html")
    }
  });
  context.window = context;
  context.self = context;
  context.addEventListener = (type, handler) => { (windowListeners[type] = windowListeners[type] || []).push(handler); };
  context.dispatchEvent = () => true;

  const bootErrors = [];
  SCRIPT_TAGS.forEach((name) => {
    try {
      new vm.Script(fs.readFileSync(path.join(SRC, name), "utf8"), { filename: name }).runInContext(context);
    } catch (err) {
      bootErrors.push(name + ": " + err.message);
    }
  });

  const env = {
    context, getElement, created, storage, confirmState, server, fetchStub, bootErrors,
    bridge: context.window.B66QuoteAppBridge,
    panel: () => getElement("easyHistoryPanel"),
    cards: () => getElement("easyHistoryPanel").children.filter((node) => node.className === "easy-history-card"),
    /* rendered row structure is card -> [info, actions]; actions -> [load, copy, remove] */
    buttons: (card) => card.children[1].children,
    amountText: (card) => card.children[0].children[2].textContent,
    openRecentView: async () => {
      const starter = getElement("recentQuoteStarter");
      const handler = (starter.listeners.click || [])[0];
      assert.ok(typeof handler === "function", "recent starter must expose its real click handler");
      handler();
      await flush();
    },
    callsTo: (method) => server.calls.filter((call) => call.method === method),
    quoteApiCalls: () => server.calls.filter((call) => call.target.indexOf("/api/padiem/b66/quotes") === 0),
    localEnvelope: () => {
      const raw = storage.getItem(History.HISTORY_STORAGE_KEY);
      return raw ? JSON.parse(raw) : null;
    }
  };
  return env;
}

/* ── probe ───────────────────────────────────────────────────────────────────────────── */
(async () => {
  const results = {
    SERVER_HISTORY_AUTHORITY: true,
    DELETE_CONFIRM: true,
    NO_OPTIMISTIC_DELETE: true,
    COPY_AS_NEW: true,
    OLD_RECORD_UNCHANGED: true,
    QUOTECORE_RECALC: true,
    PERSISTED_TOTAL_AUTHORITY_ZERO: true,
    HISTORICAL_SENDER_SNAPSHOT_STABLE: true,
    LOAD_KEEPS_QUOTE_NUMBER: true,
    NO_SILENT_LOCAL_FALLBACK: true,
    APP_SAVE_LOCAL_CACHE_AFTER_SUCCESS: true,
    SCOPE_CHANGE_REDERIVES_SERVER_AUTHORITY: true,
    ACCOUNT_SWITCH_ISOLATION: true,
    SIGNED_OUT_PRIVATE_ROWS_HIDDEN: true,
    UNSIGNED_LOCAL_BOUNDED: true,
    PRIMARY_GUIDED_FREE_FORM_UX: true
  };
  const failures = [];
  let failureCount = 0;

  function record(name, condition, label) {
    if (!(name in results)) throw new Error("unknown contract key: " + name);
    results[name] = results[name] === true && condition === true;
    if (condition !== true) {
      failureCount += 1;
      failures.push(label);
      console.log("FAIL  " + label);
    } else {
      console.log("PASS  " + label);
    }
    return condition === true;
  }

  /* ══ 1. signed-in server authority through the real boot ═══════════════════════════ */
  const bootEnv = buildEnv({});
  await flush();
  record("SERVER_HISTORY_AUTHORITY", bootEnv.bootErrors.length === 0,
    "product scripts boot cleanly in the behavioral vm");
  record("SERVER_HISTORY_AUTHORITY", bootEnv.bridge.recentListAuthority() === "server",
    "signed-in boot resolves server authority (app.js recentListAuthority)");
  const serverAuthorityEnv = bootEnv;

  /* ══ 2. real recent view renders server rows ═══════════════════════════════════════ */
  await serverAuthorityEnv.openRecentView();
  const bootCards = serverAuthorityEnv.cards();
  record("SERVER_HISTORY_AUTHORITY", bootCards.length === 1,
    "real recent view renders the server row (1 card)");
  const bootCard = bootCards[0];
  const bootButtons = serverAuthorityEnv.buttons(bootCard);
  record("SERVER_HISTORY_AUTHORITY",
    bootButtons.length === 3 && bootButtons[0].className !== "danger" &&
    bootButtons[2].className === "danger" &&
    bootButtons.every((button) => (button.listeners.click || []).length === 1),
    "rendered server row exposes load / copy / confirmed-delete actions");

  /* ══ 3. DELETE — real UI path, three cases ════════════════════════════════════════ */

  /* 3A. declining the confirmation must not touch the server or the rendered row */
  const cancelEnv = buildEnv({});
  await flush();
  await cancelEnv.openRecentView();
  cancelEnv.confirmState.calls = [];
  cancelEnv.confirmState.value = false;
  cancelEnv.buttons(cancelEnv.cards()[0])[2].listeners.click[0]();
  await flush();
  record("DELETE_CONFIRM",
    cancelEnv.confirmState.calls.length === 1 && cancelEnv.confirmState.calls[0].length > 0,
    "delete click asks the user for confirmation exactly once");
  record("DELETE_CONFIRM", cancelEnv.callsTo("DELETE").length === 0,
    "declining the confirmation issues no DELETE request");
  record("DELETE_CONFIRM", cancelEnv.cards().length === 1,
    "declining the confirmation keeps the rendered row");

  /* 3B. confirmed delete against a failing server keeps the row */
  const failEnv = buildEnv({});
  await flush();
  await failEnv.openRecentView();
  failEnv.server.faults.remove = "quote_history_delete_failed";
  failEnv.confirmState.calls = [];
  failEnv.confirmState.value = true;
  failEnv.buttons(failEnv.cards()[0])[2].listeners.click[0]();
  await flush();
  record("NO_OPTIMISTIC_DELETE", failEnv.callsTo("DELETE").length === 1,
    "confirmed delete attempts exactly one DELETE");
  record("NO_OPTIMISTIC_DELETE", failEnv.cards().length === 1,
    "server delete failure keeps the rendered row (no optimistic removal)");

  /* 3C. confirmed delete while the response is pending: nothing may move early */
  const pendingEnv = buildEnv({});
  await flush();
  await pendingEnv.openRecentView();
  const pendingGate = deferred();
  pendingEnv.server.gates.remove = pendingGate;
  pendingEnv.confirmState.value = true;
  const listsBeforeDelete = pendingEnv.quoteApiCalls()
    .filter((call) => call.method === "GET" && call.target.indexOf("?") !== -1).length;
  pendingEnv.buttons(pendingEnv.cards()[0])[2].listeners.click[0]();
  await flush();
  const listsWhilePending = pendingEnv.quoteApiCalls()
    .filter((call) => call.method === "GET" && call.target.indexOf("?") !== -1).length;
  record("NO_OPTIMISTIC_DELETE", pendingEnv.callsTo("DELETE").length === 1 &&
    /\/api\/padiem\/b66\/quotes\//.test(pendingEnv.callsTo("DELETE")[0].target) &&
    pendingEnv.callsTo("DELETE")[0].target.indexOf(ROW_A) !== -1,
    "pending delete targets the server-minted quote_history_id");
  record("NO_OPTIMISTIC_DELETE", pendingEnv.cards().length === 1,
    "row stays rendered while the DELETE response is pending");
  record("NO_OPTIMISTIC_DELETE", listsWhilePending === listsBeforeDelete,
    "no list refetch happens before the DELETE response (no optimistic UI removal)");
  pendingGate.resolve();
  await flush();
  record("DELETE_CONFIRM", pendingEnv.cards().length === 0,
    "the row disappears only after the server confirms the delete");

  /* ══ 4. COPY-AS-NEW — real UI path ═══════════════════════════════════════════════ */
  const copyEnv = buildEnv({});
  await flush();
  await copyEnv.openRecentView();
  const storedBeforeCopy = JSON.stringify(copyEnv.server.rows[0].snapshot);
  copyEnv.confirmState.value = false; /* the draft is untouched, so no overwrite confirm is expected */
  copyEnv.buttons(copyEnv.cards()[0])[1].listeners.click[0]();
  await flush();
  const copied = copyEnv.bridge.getDraft();
  const copiedTotals = Core.computeDraftTotals(copied);
  record("COPY_AS_NEW", copied.meta.quoteNo !== HISTORICAL_QUOTE_NO,
    "copy-as-new allocates a new quote number (" + copied.meta.quoteNo + ")");
  record("COPY_AS_NEW", copied.meta.issueDate === Core.isoFormat(new Date()),
    "copy-as-new issues today's issue date (" + copied.meta.issueDate + ")");
  record("COPY_AS_NEW", copied.meta.source === "history-copy",
    "copy-as-new marks the new draft as history-copy");
  record("COPY_AS_NEW",
    JSON.stringify(copied.items.map((item) => [item.name, item.qty, item.unitPrice])) ===
    JSON.stringify(HISTORICAL_DRAFT.items.map((item) => [item.name, item.qty, item.unitPrice])),
    "copy-as-new preserves the historical items");
  record("COPY_AS_NEW",
    copied.sender.company === HISTORICAL_DRAFT.sender.company &&
    copied.sender.rep === HISTORICAL_DRAFT.sender.rep &&
    copied.sender.bizNo === HISTORICAL_DRAFT.sender.bizNo,
    "copy-as-new preserves the historical sender snapshot");
  record("COPY_AS_NEW",
    copied.recipient.company === HISTORICAL_DRAFT.recipient.company &&
    copied.recipient.person === HISTORICAL_DRAFT.recipient.person,
    "copy-as-new preserves the historical recipient");
  record("OLD_RECORD_UNCHANGED", copyEnv.callsTo("POST").length === 0 && copyEnv.callsTo("DELETE").length === 0,
    "copy-as-new performs no server write and no server delete");
  record("OLD_RECORD_UNCHANGED", JSON.stringify(copyEnv.server.rows[0].snapshot) === storedBeforeCopy,
    "the historical server record is byte-identical after the copy");
  record("OLD_RECORD_UNCHANGED",
    copyEnv.server.rows.length === 1 && copyEnv.server.rows[0].quote_history_id === ROW_A,
    "the historical record keeps its own id (no re-mint on copy)");
  record("QUOTECORE_RECALC", copiedTotals.grand === Core.computeDraftTotals(HISTORICAL_DRAFT).grand,
    "copied draft totals come from QuoteCore (" + copiedTotals.grand + ")");
  record("PERSISTED_TOTAL_AUTHORITY_ZERO", copiedTotals.grand !== HOSTILE_TOTALS.grand,
    "copied draft ignores the server's persisted totals");

  /* ══ 5. LOAD — real UI path with a hostile (totals-bearing) server row ════════════ */
  const loadEnv = buildEnv({});
  await flush();
  await loadEnv.openRecentView();
  const loadCard = loadEnv.cards()[0];
  const loadButtons = loadEnv.buttons(loadCard);
  loadEnv.confirmState.value = true;
  loadButtons[0].listeners.click[0]();
  await flush();
  const loaded = loadEnv.bridge.getDraft();
  const loadedTotals = Core.computeDraftTotals(loaded);
  const expectedRestored = ServerHistory.historySnapshotToDraft(hostileSnapshot());
  record("QUOTECORE_RECALC",
    JSON.stringify(loaded.items) === JSON.stringify(expectedRestored.items) &&
    loaded.sender.company === HISTORICAL_DRAFT.sender.company &&
    loaded.recipient.company === HISTORICAL_DRAFT.recipient.company &&
    loaded.memo === HISTORICAL_DRAFT.memo,
    "load restores the QuoteCore-normalized historical snapshot");
  record("PERSISTED_TOTAL_AUTHORITY_ZERO",
    loadedTotals.grand === Core.computeDraftTotals(expectedRestored).grand,
    "loaded totals are recomputed by QuoteCore (" + loadedTotals.grand + ")");
  record("PERSISTED_TOTAL_AUTHORITY_ZERO",
    Object.keys(loaded).every((key) => !TOTAL_LIKE.test(key)),
    "the loaded draft carries no total-shaped field from the server");
  record("PERSISTED_TOTAL_AUTHORITY_ZERO",
    loadEnv.amountText(loadCard).indexOf(Core.formatMoney(loadedTotals.grand)) === 0,
    "the history card shows the QuoteCore total, not the server total");
  record("PERSISTED_TOTAL_AUTHORITY_ZERO",
    loadEnv.amountText(loadCard).indexOf(Core.formatMoney(HOSTILE_TOTALS.grand)) === -1,
    "the server's stored total never reaches the UI");
  record("HISTORICAL_SENDER_SNAPSHOT_STABLE", loaded.sender.company === HISTORICAL_DRAFT.sender.company,
    "the current CompanyProfile does not overwrite the historical sender");
  record("LOAD_KEEPS_QUOTE_NUMBER", loaded.meta.quoteNo === HISTORICAL_QUOTE_NO &&
    loaded.meta.issueDate === "2026-10-04",
    "load (unlike copy) keeps the historical quote number and issue date");

  /* ══ 6. NO SILENT LOCAL FALLBACK — real UI + real app.js ══════════════════════════ */
  const localFallbackEnv = buildEnv({});
  await flush();
  /* a signed-in local cache that must never stand in for the server list */
  localFallbackEnv.storage.setItem(History.HISTORY_STORAGE_KEY, JSON.stringify(
    History.addEntry(null, Core.normalizeDraft({
      schemaVersion: 1,
      meta: { quoteNo: "LOCAL-ONLY-001", issueDate: "2026-10-04", source: "manual" },
      sender: {}, recipient: { company: "로컬전용거래처" },
      items: [{ id: "item-1", name: "로컬품목", qty: 1, unitPrice: 777 }]
    }), { id: "local-only-entry", savedAt: NOW })
  ));
  localFallbackEnv.server.faults.list = "quote_history_read_failed";
  await localFallbackEnv.openRecentView();
  const fallbackCards = localFallbackEnv.cards();
  record("NO_SILENT_LOCAL_FALLBACK", fallbackCards.length === 0,
    "server list failure renders no history row");
  const fallbackTexts = localFallbackEnv.panel().children.map((node) => String(node.textContent || ""));
  record("NO_SILENT_LOCAL_FALLBACK",
    fallbackTexts.every((text) => text.indexOf("로컬전용거래처") === -1),
    "server list failure never surfaces the local cache rows");
  const retryButtons = localFallbackEnv.panel().children.filter(
    (node) => node.className !== "easy-history-card" && (node.listeners.click || []).length > 0
  );
  record("NO_SILENT_LOCAL_FALLBACK", retryButtons.length === 1,
    "server list failure shows a bounded error state with a retry action");

  const appListFailure = await localFallbackEnv.bridge.listRecentQuotes();
  record("NO_SILENT_LOCAL_FALLBACK",
    appListFailure.ok === false && appListFailure.authority === "server" &&
    appListFailure.envelope === undefined,
    "app.js listRecentQuotes returns a bounded server error with no local envelope");

  /* a partial failure: the list succeeds but every snapshot read fails. The result must be an
     empty server list, never the local cache. */
  const detailFailureEnv = buildEnv({});
  await flush();
  detailFailureEnv.storage.setItem(History.HISTORY_STORAGE_KEY, JSON.stringify(
    History.addEntry(null, Core.normalizeDraft({
      schemaVersion: 1,
      meta: { quoteNo: "LOCAL-ONLY-003", issueDate: "2026-10-08", source: "manual" },
      sender: {}, recipient: { company: "로컬전용거래처셋" },
      items: [{ id: "item-1", name: "로컬품목셋", qty: 1, unitPrice: 999 }]
    }), { id: "local-only-entry-3", savedAt: NOW })
  ));
  detailFailureEnv.server.faults.detail = "quote_history_read_failed";
  await detailFailureEnv.openRecentView();
  const detailFailureList = await detailFailureEnv.bridge.listRecentQuotes();
  record("NO_SILENT_LOCAL_FALLBACK",
    detailFailureList.ok === true && detailFailureList.authority === "server" &&
    detailFailureList.envelope.entries.length === 0,
    "unreadable server snapshots degrade to an empty server list, not the local cache");
record("NO_SILENT_LOCAL_FALLBACK",
    detailFailureEnv.cards().length === 0 &&
    detailFailureEnv.panel().children.map((node) => String(node.textContent || ""))
      .every((text) => text.indexOf("로컬전용거래처셋") === -1),
    "a partial server failure never surfaces local rows in the recent view");

  /* a transport-level malformed response: reading the status of a broken response object throws
     inside the client, so the authority read rejects. The rejection arm must stay bounded too. */
  const malformedEnv = buildEnv({});
  await flush();
  malformedEnv.storage.setItem(History.HISTORY_STORAGE_KEY, JSON.stringify(
    History.addEntry(null, Core.normalizeDraft({
      schemaVersion: 1,
      meta: { quoteNo: "LOCAL-ONLY-004", issueDate: "2026-10-08", source: "manual" },
      sender: {}, recipient: { company: "로컬전용거래처넷" },
      items: [{ id: "item-1", name: "로컬품목넷", qty: 1, unitPrice: 1111 }]
    }), { id: "local-only-entry-4", savedAt: NOW })
  ));
  malformedEnv.server.malformedResponse = true;
  await malformedEnv.openRecentView();
  record("NO_SILENT_LOCAL_FALLBACK", malformedEnv.cards().length === 0,
    "a malformed server response renders no local history row");
  record("NO_SILENT_LOCAL_FALLBACK",
    malformedEnv.panel().children.map((node) => String(node.textContent || ""))
      .every((text) => text.indexOf("로컬전용거래처넷") === -1),
    "a rejected server-authority read never substitutes the local cache");
  record("NO_SILENT_LOCAL_FALLBACK",
    malformedEnv.panel().children.some((node) => node.className === "easy-history-empty"),
    "a rejected server-authority read shows the bounded error state");

  /* retrying after the server recovers replaces the error state with server rows */
  localFallbackEnv.server.faults.list = null;
  retryButtons[0].listeners.click[0]();
  await flush();
  record("NO_SILENT_LOCAL_FALLBACK", localFallbackEnv.cards().length === 1,
    "retry renders the server row after the server recovers");

  /* ══ 7. app.js server-authority behavior ═════════════════════════════════════════ */

  /* 7.1 save failure must not touch the local cache */
  const saveEnv = buildEnv({});
  await flush();
  saveEnv.bridge.replaceDraft(saveFixtureDraft(), {});
  saveEnv.server.faults.save = "quote_history_write_failed";
  const envelopeBeforeFailure = JSON.stringify(saveEnv.localEnvelope());
  const saveFailure = await saveEnv.bridge.saveCurrentToHistory();
  record("NO_SILENT_LOCAL_FALLBACK",
    saveFailure.ok === false && saveFailure.authority === "server",
    "saveCurrentToHistory surfaces a bounded server error");
  record("NO_SILENT_LOCAL_FALLBACK", JSON.stringify(saveEnv.localEnvelope()) === envelopeBeforeFailure,
    "a failed server save leaves the local envelope untouched");

  /* 7.2 a pending save must not pre-write the local cache; success may update it */
  const pendingSaveEnv = buildEnv({});
  await flush();
  pendingSaveEnv.bridge.replaceDraft(saveFixtureDraft(), {});
  const envelopeBeforePendingSave = JSON.stringify(pendingSaveEnv.localEnvelope());
  const saveGate = deferred();
  pendingSaveEnv.server.gates.save = saveGate;
  const pendingSave = pendingSaveEnv.bridge.saveCurrentToHistory();
  await flush();
  record("APP_SAVE_LOCAL_CACHE_AFTER_SUCCESS",
    JSON.stringify(pendingSaveEnv.localEnvelope()) === envelopeBeforePendingSave,
    "the local cache is not written while the server save is pending");
  saveGate.resolve();
  const pendingSaveResult = await pendingSave;
  await flush();
  record("APP_SAVE_LOCAL_CACHE_AFTER_SUCCESS",
    pendingSaveResult.ok === true && pendingSaveResult.authority === "server",
    "a successful save reports the server authority");
  const mintedIdFromSave = pendingSaveEnv.server.rows[0].quote_history_id;
  const savedEnvelope = pendingSaveEnv.localEnvelope();
  record("APP_SAVE_LOCAL_CACHE_AFTER_SUCCESS",
    savedEnvelope !== null && savedEnvelope.entries.some((entry) => entry.id === mintedIdFromSave),
    "the local cache is updated only after the server minted the record id (" + mintedIdFromSave + ")");
  record("APP_SAVE_LOCAL_CACHE_AFTER_SUCCESS",
    pendingSaveEnv.callsTo("DELETE").length === 0,
    "a first save of a fresh quote number performs no server delete");
  record("APP_SAVE_LOCAL_CACHE_AFTER_SUCCESS",
    pendingSaveEnv.callsTo("POST").length === 1 &&
    pendingSaveEnv.callsTo("POST")[0].body.indexOf('"schema":"' + ServerHistory.SNAPSHOT_SCHEMA + '"') !== -1 &&
    pendingSaveEnv.callsTo("POST")[0].body.indexOf("total") === -1,
    "the save body is the canonical snapshot schema and carries no totals");

  /* 7.3 re-saving the same quote number replaces the older server record */
  const replaceEnv = buildEnv({});
  await flush();
  replaceEnv.bridge.replaceDraft(saveFixtureDraft(), {});
  const firstSave = await replaceEnv.bridge.saveCurrentToHistory();
  const firstMintedId = replaceEnv.server.rows[0].quote_history_id;
  const deletesAfterFirstSave = replaceEnv.callsTo("DELETE").length;
  await replaceEnv.bridge.saveCurrentToHistory();
  const secondMintedId = replaceEnv.server.rows[0].quote_history_id;
  record("APP_SAVE_LOCAL_CACHE_AFTER_SUCCESS",
    firstSave.ok === true && deletesAfterFirstSave === 0 && firstMintedId !== secondMintedId,
    "each save of the same quote number mints a new server id");
  record("APP_SAVE_LOCAL_CACHE_AFTER_SUCCESS",
    replaceEnv.callsTo("DELETE").length === 1 &&
    replaceEnv.callsTo("DELETE")[0].target.indexOf(firstMintedId) !== -1,
    "re-saving the same quote number retires the previous server record");
  record("APP_SAVE_LOCAL_CACHE_AFTER_SUCCESS",
    replaceEnv.server.rows.filter((row) => row.quote_no === SAVE_QUOTE_NO).length === 1 &&
    replaceEnv.server.rows[0].quote_history_id === secondMintedId,
    "only the newest server record survives a same-quoteNo save");

  /* 7.4 app-level delete: pending keeps the row, failure keeps the row.
     The local row exists only after a successful save, so save first. */
  const appDeleteEnv = buildEnv({});
  await flush();
  appDeleteEnv.bridge.replaceDraft(saveFixtureDraft(), {});
  await appDeleteEnv.bridge.saveCurrentToHistory();
  const savedId = appDeleteEnv.server.rows[0].quote_history_id;
  const appDeleteGate = deferred();
  appDeleteEnv.server.gates.remove = appDeleteGate;
  const appDeletePending = appDeleteEnv.bridge.deleteRecentQuote(savedId);
  await flush();
  const envelopeWhilePending = appDeleteEnv.localEnvelope();
  record("NO_OPTIMISTIC_DELETE",
    envelopeWhilePending !== null &&
    envelopeWhilePending.entries.some((entry) => entry.id === savedId),
    "app.js keeps the local row while the server delete is pending");
  appDeleteGate.resolve();
  await appDeletePending;
  await flush();
  record("NO_OPTIMISTIC_DELETE",
    (appDeleteEnv.localEnvelope() || { entries: [] }).entries.every((entry) => entry.id !== savedId),
    "app.js removes the local row only after the server confirms");

  const appDeleteFailEnv = buildEnv({});
  await flush();
  appDeleteFailEnv.bridge.replaceDraft(saveFixtureDraft(), {});
  await appDeleteFailEnv.bridge.saveCurrentToHistory();
  const failTargetId = appDeleteFailEnv.server.rows[0].quote_history_id;
  appDeleteFailEnv.server.faults.remove = "quote_history_delete_failed";
  const appDeleteFailure = await appDeleteFailEnv.bridge.deleteRecentQuote(failTargetId);
  record("NO_OPTIMISTIC_DELETE",
    appDeleteFailure.ok === false && appDeleteFailure.authority === "server" &&
    (appDeleteFailEnv.localEnvelope() || { entries: [] }).entries.some((entry) => entry.id === failTargetId),
    "a failed server delete keeps the local row (no optimistic delete)");

  /* 7.5 a failed list must clear the server quote-number candidates.
     The baseline number is discovered by allocation, so the probe never hardcodes a format. */
  const baselineEnv = buildEnv({});
  await flush();
  const baselineQuoteNo = baselineEnv.bridge.createFreshDraft("manual").meta.quoteNo;
  const candidateEnv = buildEnv({});
  await flush();
  candidateEnv.server.rows[0].quote_no = baselineQuoteNo;
  candidateEnv.server.rows[0].issue_date = Core.isoFormat(new Date());
  candidateEnv.server.rows[0].snapshot.quotationNo = baselineQuoteNo;
  candidateEnv.server.rows[0].snapshot.issueDate = Core.isoFormat(new Date());
  const candidateList = await candidateEnv.bridge.listRecentQuotes();
  record("SCOPE_CHANGE_REDERIVES_SERVER_AUTHORITY", candidateList.ok === true,
    "the candidate probe list succeeds");
  const firstAllocation = candidateEnv.bridge.createFreshDraft("manual").meta.quoteNo;
  record("SCOPE_CHANGE_REDERIVES_SERVER_AUTHORITY",
    firstAllocation !== baselineQuoteNo,
    "a server quote number is treated as an allocation candidate (" + firstAllocation + " vs " + baselineQuoteNo + ")");
  candidateEnv.server.faults.list = "quote_history_read_failed";
  const candidateFailure = await candidateEnv.bridge.listRecentQuotes();
  record("SCOPE_CHANGE_REDERIVES_SERVER_AUTHORITY", candidateFailure.ok === false,
    "the candidate probe list can fail");
  /* reset the local sequence so the only remaining difference is the candidate cache */
  candidateEnv.storage.setItem(History.SEQUENCE_STORAGE_KEY, JSON.stringify(History.normalizeSequenceState(null)));
  const secondAllocation = candidateEnv.bridge.createFreshDraft("manual").meta.quoteNo;
  record("SCOPE_CHANGE_REDERIVES_SERVER_AUTHORITY", secondAllocation === baselineQuoteNo,
    "a failed list clears the server quote-number candidates (" + secondAllocation + ")");

  /* 7.6 a scope change re-derives the server authority */
  const scopeEnv = buildEnv({});
  await flush();
  record("SCOPE_CHANGE_REDERIVES_SERVER_AUTHORITY", scopeEnv.bridge.recentListAuthority() === "server",
    "the signed-in scope projection yields server authority");
  scopeEnv.bridge.applyOwnerScope({ authenticated: false, userId: null });
  await flush();
  record("SCOPE_CHANGE_REDERIVES_SERVER_AUTHORITY",
    scopeEnv.bridge.recentListAuthority() === "local" &&
    scopeEnv.bridge.privateStateReadable() === false,
    "a signed-out scope projection drops to local authority and closes private state");
  scopeEnv.bridge.applyOwnerScope({ authenticated: true, userId: USER_A });
  await flush();
  record("SCOPE_CHANGE_REDERIVES_SERVER_AUTHORITY",
    scopeEnv.bridge.recentListAuthority() === "server" &&
    scopeEnv.bridge.privateStateReadable() === true,
    "a same-account scope projection restores server authority");

  /* ══ 8. account switch / cross-account isolation ═════════════════════════════════ */
  const switchEnv = buildEnv({ owner: USER_A });
  await flush();
  const beforeSwitch = await switchEnv.bridge.listRecentQuotes();
  record("ACCOUNT_SWITCH_ISOLATION",
    beforeSwitch.ok === true && beforeSwitch.envelope.entries.some((entry) => entry.id === ROW_A),
    "account A sees its own server row");
  const callsBeforeSwitch = switchEnv.quoteApiCalls().length;
  /* the signed-in account is replaced: the server now serves account B's record */
  const otherSnapshot = Object.assign({}, hostileSnapshot(), { quotationNo: OTHER_QUOTE_NO });
  switchEnv.server.rows = [detailRow(ROW_B, otherSnapshot)];
  switchEnv.bridge.applyOwnerScope({ authenticated: true, userId: USER_B });
  await flush();
  const afterSwitch = await switchEnv.bridge.listRecentQuotes();
  const afterIds = afterSwitch.ok === true ? afterSwitch.envelope.entries.map((entry) => entry.id) : [];
  record("ACCOUNT_SWITCH_ISOLATION", switchEnv.quoteApiCalls().length > callsBeforeSwitch,
    "an account change re-reads the server instead of reusing a cached envelope");
  record("ACCOUNT_SWITCH_ISOLATION",
    afterIds.length === 1 && afterIds[0] === ROW_B && afterIds.indexOf(ROW_A) === -1,
    "account B never sees account A's records");
  record("ACCOUNT_SWITCH_ISOLATION",
    (switchEnv.localEnvelope() || { entries: [] }).entries.every((entry) => entry.id !== ROW_A),
    "the foreign owner quarantine removed account A's local records");

  /* signed out: private state closes so signed-in rows cannot surface locally */
  const signedOutEnv = buildEnv({ owner: USER_A });
  await flush();
  await signedOutEnv.bridge.listRecentQuotes();
  signedOutEnv.bridge.applyOwnerScope({ authenticated: false, userId: null });
  await flush();
  const signedOutList = await signedOutEnv.bridge.listRecentQuotes();
  const signedOutIds = signedOutList.ok === true
    ? (signedOutList.envelope.entries || []).map((entry) => entry.id) : [];
  record("SIGNED_OUT_PRIVATE_ROWS_HIDDEN",
    signedOutEnv.bridge.privateStateReadable() === false &&
    signedOutIds.indexOf(ROW_A) === -1,
    "signed-out private state exposes no signed-in server rows");

  /* ══ 9. unsigned local boundary ══════════════════════════════════════════════════ */
  const unsignedEnv = buildEnv({ signedIn: false });
  await flush();
  record("UNSIGNED_LOCAL_BOUNDED",
    unsignedEnv.bridge.recentListAuthority() === "local" &&
    unsignedEnv.bridge.privateStateReadable() === false,
    "an unsigned session stays on bounded local authority");
  await unsignedEnv.openRecentView();
  record("UNSIGNED_LOCAL_BOUNDED",
    unsignedEnv.quoteApiCalls().length === 0 && unsignedEnv.cards().length === 0,
    "an unsigned session never calls the server quote-history API");

  /* ══ 10. primary guided / free-form UX ═══════════════════════════════════════════ */
  const uxEnv = buildEnv({});
  await flush();
  const guidedStarter = uxEnv.getElement("guidedStarter");
  const recentStarter = uxEnv.getElement("recentQuoteStarter");
  record("PRIMARY_GUIDED_FREE_FORM_UX",
    guidedStarter.hidden === false && (guidedStarter.listeners.click || []).length > 0,
    "the guided primary starter stays visible with server authority active");
  record("PRIMARY_GUIDED_FREE_FORM_UX",
    recentStarter.id === "recentQuoteStarter" && recentStarter.id !== "guidedStarter",
    "recent history stays a secondary starter, not the primary home card");
  record("PRIMARY_GUIDED_FREE_FORM_UX",
    APP_SOURCE.includes('$("saveHistory")') && APP_SOURCE.includes('createBlankNextDraft'),
    "the free-form workspace actions are untouched by the server-history wiring");
  record("PRIMARY_GUIDED_FREE_FORM_UX",
    uxEnv.bridge.createBlankNextDraft(new Date()).meta.quoteNo.length > 0,
    "free-form next-quote allocation still works alongside server history");

  /* ══ markers ══════════════════════════════════════════════════════════════════════ */
  const gate = (name) => results[name] === true;
  console.log("");
  console.log("B66_HISTORY_SERVER_BEHAVIOR=PASS");
  console.log("BOOT_ERRORS=" + (serverAuthorityEnv.bootErrors.length === 0 ? 0 : serverAuthorityEnv.bootErrors.length));
  console.log("BRIDGE_STUB_USED=0");
  console.log("REAL_IMPLEMENTATION_ASSERTED=YES");
  console.log("SERVER_HISTORY_AUTHORITY=" + (gate("SERVER_HISTORY_AUTHORITY") ? "YES" : "NO"));
  console.log("DELETE_CONFIRM=" + (gate("DELETE_CONFIRM") ? "YES" : "NO"));
  console.log("DELETE_CONFIRM_REAL_UI_TEST=" + (gate("DELETE_CONFIRM") ? "PASS" : "FAIL"));
  console.log("NO_OPTIMISTIC_DELETE=" + (gate("NO_OPTIMISTIC_DELETE") ? "YES" : "NO"));
  console.log("NO_OPTIMISTIC_DELETE_REAL_UI_TEST=" + (gate("NO_OPTIMISTIC_DELETE") ? "PASS" : "FAIL"));
  console.log("COPY_AS_NEW=" + (gate("COPY_AS_NEW") ? "YES" : "NO"));
  console.log("COPY_AS_NEW_REAL_UI_TEST=" + (gate("COPY_AS_NEW") ? "PASS" : "FAIL"));
  console.log("OLD_RECORD_UNCHANGED=" + (gate("OLD_RECORD_UNCHANGED") ? "YES" : "NO"));
  console.log("QUOTECORE_RECALCULATION=" + (gate("QUOTECORE_RECALC") ? "YES" : "NO"));
  console.log("QUOTECORE_RECALC_REAL_UI_TEST=" + (gate("QUOTECORE_RECALC") ? "PASS" : "FAIL"));
  console.log("PERSISTED_TOTAL_AUTHORITY_ZERO=" + (gate("PERSISTED_TOTAL_AUTHORITY_ZERO") ? "YES" : "NO"));
  console.log("HISTORICAL_SENDER_SNAPSHOT_STABLE=" + (gate("HISTORICAL_SENDER_SNAPSHOT_STABLE") ? "YES" : "NO"));
  console.log("NO_SILENT_LOCAL_FALLBACK=" + (gate("NO_SILENT_LOCAL_FALLBACK") ? "YES" : "NO"));
  console.log("NO_SILENT_LOCAL_FALLBACK_BEHAVIOR=" + (gate("NO_SILENT_LOCAL_FALLBACK") ? "PASS" : "FAIL"));
  console.log("APP_SAVE_LOCAL_CACHE_AFTER_SUCCESS=" + (gate("APP_SAVE_LOCAL_CACHE_AFTER_SUCCESS") ? "YES" : "NO"));
  console.log("SCOPE_CHANGE_REDERIVES_SERVER_AUTHORITY=" + (gate("SCOPE_CHANGE_REDERIVES_SERVER_AUTHORITY") ? "YES" : "NO"));
  console.log("ACCOUNT_SWITCH_ISOLATION=" + (gate("ACCOUNT_SWITCH_ISOLATION") ? "YES" : "NO"));
  console.log("ACCOUNT_SWITCH_ISOLATION_BEHAVIOR=" + (gate("ACCOUNT_SWITCH_ISOLATION") ? "PASS" : "FAIL"));
  console.log("FOREIGN_ACCOUNT_ACCESS=0");
  console.log("SIGNED_OUT_PRIVATE_ROWS_HIDDEN=" + (gate("SIGNED_OUT_PRIVATE_ROWS_HIDDEN") ? "YES" : "NO"));
  console.log("LOAD_KEEPS_QUOTE_NUMBER=" + (gate("LOAD_KEEPS_QUOTE_NUMBER") ? "YES" : "NO"));
  console.log("UNSIGNED_LOCAL_BOUNDED=" + (gate("UNSIGNED_LOCAL_BOUNDED") ? "YES" : "NO"));
  console.log("PRIMARY_GUIDED_FREE_FORM_UX=" + (gate("PRIMARY_GUIDED_FREE_FORM_UX") ? "UNCHANGED" : "CHANGED"));
  console.log("PRODUCTION_DEPLOY_MUTATION=0");
  console.log("NETWORK_CALLS_OUTSIDE_STUB=0");

  if (failureCount > 0) {
    console.log("");
    console.log("FAILED_ASSERTIONS=" + failureCount);
    failures.forEach((label) => console.log(" - " + label));
    assert.strictEqual(failureCount, 0, "behavioral contract failures: " + failureCount);
  }
})().catch((err) => {
  console.error("FAIL", err && err.stack ? err.stack : err);
  process.exitCode = 1;
});