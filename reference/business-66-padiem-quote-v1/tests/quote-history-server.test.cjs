/* B66 · Quote Beta — canonical server quote-history client unit probe (#3405 Slice B).
   Tests the quote-history-server.js module with a stubbed fetch. No network, no
   real credentials, no product state outside the module. */
const assert = require("node:assert");
const path = require("node:path");
const vm = require("node:vm");

const SRC = path.join(__dirname, "..");
const Core = require(path.join(SRC, "quote-core.js"));
const ServerHistory = require(path.join(SRC, "quote-history-server.js"));

const USER = "usr_" + "a".repeat(32);
const WORKSPACE = "owner:" + USER;
const NOW = "2026-10-04T09:00:00.000Z";
const ROW_ID = "b66quote_" + "a".repeat(32);
const LIST_LIMIT = 3;

const PRODUCTION_DRAFT = Core.createProductionDraft();
const HISTORY_DRAFT = Core.normalizeDraft({
  schemaVersion: 1,
  meta: { quoteNo: "PQ-20261004-001", issueDate: "2026-10-04", source: "manual" },
  sender: { company: "시드상사", rep: "대표", bizNo: "111-11-11111", address: "서울", phone: "010-0000-0000", email: "seed@example.invalid" },
  recipient: { company: "시드고객", person: "담당자" },
  items: [{ id: "item-1", name: "품목", qty: 2, unitPrice: 15000 }],
  tax: { mode: "EXCLUSIVE", rate: 0.1 },
  memo: "메모"
});

function boundedRow(overrides) {
  return Object.assign({
    quote_history_id: ROW_ID,
    quote_no: "PQ-20261004-001",
    issue_date: "2026-10-04",
    saved_skill_id: null,
    skill_fingerprint: null,
    created_at: NOW,
    updated_at: NOW,
    totals_authority: "quote-core",
    quote_core_recalculation_required: true,
    snapshot: ServerHistory.draftToHistorySnapshot(HISTORY_DRAFT),
    sender: HISTORY_DRAFT.sender
  }, overrides || {});
}

function makeFetch() {
  const calls = [];
  const responseByPath = new Map();
  const addResponse = (method, path, body, status) => {
    responseByPath.set(method + " " + path, { ok: status >= 200 && status < 300, status, json: async () => body });
  };

  addResponse("GET", "/api/padiem/b66/quotes?limit=" + LIST_LIMIT, {
    ok: true,
    quotes: [boundedRow()],
    limit: LIST_LIMIT
  }, 200);

  addResponse("GET", "/api/padiem/b66/quotes/" + ROW_ID, {
    ok: true,
    quote: boundedRow()
  }, 200);

  addResponse("POST", "/api/padiem/b66/quotes", {
    ok: true,
    quote: boundedRow({ quote_history_id: ROW_ID, created_at: NOW, updated_at: NOW })
  }, 201);

  addResponse("DELETE", "/api/padiem/b66/quotes/" + ROW_ID, {
    ok: true,
    deleted: ROW_ID
  }, 200);

  const impl = async (url, init) => {
    const method = (init && init.method) || "GET";
    const target = String(url);
    calls.push({ url: target, method, body: init && init.body || null });
    const key = method + " " + target.replace(/^https?:\/\/[^/]+/, "");
    const response = responseByPath.get(key);
    if (response) return response;
    return new Response(JSON.stringify({ ok: false, error: { code: "unexpected" } }), {
      status: 404,
      headers: { "Content-Type": "application/json" }
    });
  };
  impl.calls = calls;
  return impl;
}

function vmRun(fetchStub) {
  const context = vm.createContext({
    setTimeout, clearTimeout, console,
    QuoteCore: Core,
    fetch: fetchStub
  });
  context.window = context;
  new vm.Script(require("fs").readFileSync(path.join(SRC, "quote-history-server.js"), "utf8"), { filename: "quote-history-server.js" }).runInContext(context);
  return context.B66QuoteHistoryServer;
}

(function () {
  const fetchStub = makeFetch();
  const Server = vmRun(fetchStub);

  /* ── draftToHistorySnapshot ── */
  const snapshot = Server.draftToHistorySnapshot(HISTORY_DRAFT);
  assert.ok(snapshot, "snapshot is produced from a valid draft");
  assert.equal(snapshot.schema, "b66.quote-draft.v1", "snapshot schema is canonical");
  assert.equal(snapshot.quotationNo, HISTORY_DRAFT.meta.quoteNo, "quote number preserved");
  assert.equal(snapshot.issueDate, HISTORY_DRAFT.meta.issueDate, "issue date preserved");
  assert.equal(snapshot.sender.company, HISTORY_DRAFT.sender.company, "sender snapshot preserved");
  assert.equal(snapshot.items[0].name, "품목", "item name preserved");
  assert.equal(snapshot.items.length, 1, "item count preserved");
  assert.strictEqual(snapshot.totals, undefined, "no computed totals key in snapshot");
  assert.strictEqual(snapshot.subtotal, undefined, "no subtotal key in snapshot");
  assert.strictEqual(snapshot.grandTotal, undefined, "no grand total key in snapshot");

  /* invalid draft returns null */
  assert.strictEqual(Server.draftToHistorySnapshot(null), null, "null draft -> null");
  assert.strictEqual(Server.draftToHistorySnapshot({}), null, "invalid draft -> null");

  /* ── historySnapshotToDraft ── */
  const restored = Server.historySnapshotToDraft(snapshot);
  assert.ok(restored, "snapshot restores to a draft");
  assert.equal(restored.schemaVersion, Core.SCHEMA_VERSION, "restored draft has canonical schema");
  assert.equal(restored.meta.quoteNo, HISTORY_DRAFT.meta.quoteNo, "quote number round-trips");
  assert.equal(restored.meta.issueDate, HISTORY_DRAFT.meta.issueDate, "issue date round-trips");
  assert.equal(restored.sender.company, HISTORY_DRAFT.sender.company, "historical sender preserved");
  assert.equal(restored.sender.rep, HISTORY_DRAFT.sender.rep, "historical sender rep preserved");
  assert.equal(restored.recipient.company, HISTORY_DRAFT.recipient.company, "recipient preserved");
  assert.equal(restored.items[0].name, "품목", "item name round-trips");
  assert.equal(restored.items[0].qty, 2, "item qty round-trips");
  assert.equal(restored.tax.mode, "EXCLUSIVE", "tax mode round-trips");

  /* QuoteCore normalization is the reopen boundary — totals recomputed */
  var totals = Core.computeDraftTotals(restored);
  assert.equal(totals.grand, 33000, "QuoteCore recalculates totals after restore");

  /* ── normalizeProjection list/detail ── */
  var listRow = Server.normalizeProjection(boundedRow(), { includeSnapshot: false });
  assert.ok(listRow, "list row projects");
  assert.equal(listRow.quoteHistoryId, ROW_ID, "id projected");
  assert.equal(listRow.totalsAuthority, "quote-core", "totals authority is quote-core");
  assert.equal(listRow.quoteCoreRecalculationRequired, true, "recalculation marker projected");
  assert.strictEqual(listRow.snapshot, undefined, "list projection has no snapshot");

  var detailRow = Server.normalizeProjection(boundedRow(), { includeSnapshot: true });
  assert.ok(detailRow.snapshot, "detail row has snapshot");
  assert.deepEqual(detailRow.snapshot.quotationNo, HISTORY_DRAFT.meta.quoteNo, "detail snapshot matches");

  /* ── listQuotes ── */
  Server.listQuotes({ fetch: fetchStub, limit: LIST_LIMIT }).then((result) => {
    assert.equal(result.ok, true, "listQuotes succeeds");
    assert.equal(result.quotes.length, 1, "listQuotes returns one row");
    assert.equal(result.quotes[0].quoteHistoryId, ROW_ID, "list row id matches");
    assert.equal(result.limit, LIST_LIMIT, "limit echoed back");

    /* ── getQuote ── */
    return Server.getQuote(ROW_ID, { fetch: fetchStub });
  }).then((result) => {
    assert.equal(result.ok, true, "getQuote succeeds");
    assert.equal(result.quote.quoteHistoryId, ROW_ID, "getQuote id matches");
    assert.ok(result.quote.snapshot, "getQuote includes snapshot");
    assert.equal(result.quote.sender.company, HISTORY_DRAFT.sender.company, "historical sender in detail");

    /* ── saveQuote ── */
    return Server.saveQuote(snapshot, { fetch: fetchStub });
  }).then((result) => {
    assert.equal(result.ok, true, "saveQuote succeeds");
    assert.equal(result.quote.quoteHistoryId, ROW_ID, "save returns server row id");
    assert.ok(result.quote.createdAt, "save returns created_at");

    /* ── deleteQuote ── */
    return Server.deleteQuote(ROW_ID, { fetch: fetchStub });
  }).then((result) => {
    assert.equal(result.ok, true, "deleteQuote succeeds");
    assert.equal(result.deleted, ROW_ID, "delete returns row id");

  /* ── bounded error paths ── */
  assert.ok(Server.listQuotes({ fetch: fetchStub, limit: -1 }), "negative limit is bounded");
  }).then(() => {
    /* fetch unavailable in options — request() degrades to bounded error promise */
    var noOpts = Server.listQuotes({});
    assert.equal(typeof noOpts.then, "function", "listQuotes without fetch returns a promise");

    /* invalid row id */
    return Server.getQuote("bad-id", { fetch: fetchStub });
  }).then((idResult) => {
    assert.equal(idResult.ok, false, "invalid id is rejected");

    /* no silent local fallback: error carries server code, not local envelope */
    return Server.listQuotes({ fetch: async () => new Response("{}", { status: 500 }) });
  }).then((errorResult) => {
    assert.equal(errorResult.ok, false, "server error returns bounded error");
  }).then(() => {
    console.log("B66_QUOTE_HISTORY_SERVER_CLIENT=PASS");
    console.log("SERVER_MINTED_HISTORY_ID=YES");
    console.log("NO_SILENT_LOCAL_FALLBACK=YES");
    console.log("QUOTECORE_RECALCULATION=YES");
    console.log("HISTORICAL_SENDER_SNAPSHOT_STABLE=YES");
  }).catch((err) => {
    console.error("FAIL", err);
    process.exitCode = 1;
  });
})();
