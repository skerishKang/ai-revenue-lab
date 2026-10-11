/* B66 · Pages bridge — canonical server quote-history under the #3697 same-origin policy.
 *
 * Slice B adds four quote-history routes to the Pages bridge. POST and DELETE are mutating
 * methods, so they inherit #3697's authority exactly as every other mutating bridge route does:
 * a session-bearing mutation must present the Pages Origin, and the bridge stamps the canonical
 * chat Origin upstream. This probe pins that policy for the quote-history routes and proves the
 * browser client never forges Origin itself (it only uses the same-origin fetch contract).
 *
 * No network: globalThis.fetch is stubbed and counted. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import worker from "../_worker.js";
import { createRequire } from "node:module";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);
const ServerHistory = require(path.join(HERE, "..", "quote-history-server.js"));

const PAGES_ORIGIN = "https://quick-quote-kr.pages.dev";
const FOREIGN_ORIGIN = "https://evil.example.invalid";
const CHAT_ORIGIN = "https://chat.padiem.net";
const SESSION_COOKIE = "padiem_session=opaque-test-token";
const ROW_ID = "b66quote_" + "a".repeat(32);

const originalFetch = globalThis.fetch;
const calls = [];

function json(payload, init = {}) {
  const headers = new Headers(init.headers || {});
  headers.set("Content-Type", "application/json");
  return new Response(JSON.stringify(payload), { ...init, headers });
}

globalThis.fetch = async (target, init = {}) => {
  const headers = init.headers instanceof Headers ? init.headers : new Headers(init.headers || {});
  calls.push({ url: String(target), init, headers });
  const url = String(target);
  if (url.includes("/api/b66/quotes?")) {
    return json({ ok: true, quotes: [], limit: 20 });
  }
  if (url.endsWith("/api/b66/quotes/" + ROW_ID) && (init.method || "GET") === "GET") {
    return json({ ok: true, quote: { quote_history_id: ROW_ID, snapshot: { schema: ServerHistory.SNAPSHOT_SCHEMA } } });
  }
  if (url.endsWith("/api/b66/quotes") && init.method === "POST") {
    return json({ ok: true, quote: { quote_history_id: ROW_ID } }, { status: 201 });
  }
  if (url.endsWith("/api/b66/quotes/" + ROW_ID) && init.method === "DELETE") {
    return json({ ok: true, deleted: ROW_ID });
  }
  return json({ error: { code: "unexpected" } }, { status: 404 });
};

const bridgeCall = (pathname, init) => {
  const before = calls.length;
  const request = new Request(new URL(pathname, PAGES_ORIGIN), init);
  return worker.fetch(request, {}).then((response) => ({
    response,
    upstream: calls.slice(before)
  }));
};

const sessionHeaders = (extra = {}) => Object.assign({ Cookie: SESSION_COOKIE }, extra);

/* ── 1. a quote list read needs no Origin: GET is not a mutating method ─────────── */
{
  const { response, upstream } = await bridgeCall("/api/padiem/b66/quotes?limit=20", { method: "GET" });
  assert.equal(response.status, 200, "quote list read is allowed without an Origin header");
  assert.equal(upstream.length, 1, "quote list read reaches upstream exactly once");
  assert.equal(upstream[0].url, CHAT_ORIGIN + "/api/b66/quotes?limit=20",
    "quote list read is forwarded to the canonical server path");
}

/* ── 2. POST with a session cookie and the Pages Origin is allowed ───────────────── */
{
  calls.length = 0;
  const { response, upstream } = await bridgeCall("/api/padiem/b66/quotes", {
    method: "POST",
    headers: sessionHeaders({ Origin: PAGES_ORIGIN, "Content-Type": "application/json" }),
    body: JSON.stringify({ schema: ServerHistory.SNAPSHOT_SCHEMA, quotationNo: "PQ-20261008-001" })
  });
  assert.equal(response.status, 201, "a same-origin session POST is allowed");
  assert.equal(upstream.length, 1, "an allowed quote save reaches upstream exactly once");
  assert.equal(upstream[0].init.method, "POST", "the upstream method stays POST");
  assert.equal(upstream[0].url, CHAT_ORIGIN + "/api/b66/quotes", "the save targets the canonical quote-history path");
  assert.equal(upstream[0].headers.get("origin"), CHAT_ORIGIN,
    "the bridge stamps the canonical chat Origin on the upstream save");
  assert.equal(upstream[0].headers.get("cookie"), SESSION_COOKIE, "the session cookie is relayed unchanged");
}

/* ── 3. POST with a session cookie and no Origin is rejected before upstream ─────── */
{
  calls.length = 0;
  const { response, upstream } = await bridgeCall("/api/padiem/b66/quotes", {
    method: "POST",
    headers: sessionHeaders({ "Content-Type": "application/json" }),
    body: "{}"
  });
  assert.equal(response.status, 403, "a session save without an Origin is rejected");
  const body = await response.clone().json();
  assert.equal(body.error.code, "padiem_origin_rejected", "the rejection is the canonical origin error");
  assert.equal(upstream.length, 0, "a rejected save never reaches upstream");
}

/* ── 4. POST with a foreign Origin is rejected before upstream ────────────────────── */
{
  calls.length = 0;
  const { response, upstream } = await bridgeCall("/api/padiem/b66/quotes", {
    method: "POST",
    headers: sessionHeaders({ Origin: FOREIGN_ORIGIN, "Content-Type": "application/json" }),
    body: "{}"
  });
  assert.equal(response.status, 403, "a session save from a foreign Origin is rejected");
  assert.equal(upstream.length, 0, "a cross-origin save never reaches upstream");
}

/* ── 5. DELETE with a session cookie and the Pages Origin is allowed ─────────────── */
{
  calls.length = 0;
  const { response, upstream } = await bridgeCall("/api/padiem/b66/quotes/" + ROW_ID, {
    method: "DELETE",
    headers: sessionHeaders({ Origin: PAGES_ORIGIN })
  });
  assert.equal(response.status, 200, "a same-origin session DELETE is allowed");
  assert.equal(upstream.length, 1, "an allowed delete reaches upstream exactly once");
  assert.equal(upstream[0].url, CHAT_ORIGIN + "/api/b66/quotes/" + ROW_ID,
    "the delete targets the exact canonical row path");
  assert.equal(upstream[0].headers.get("origin"), CHAT_ORIGIN,
    "the bridge stamps the canonical chat Origin on the upstream delete");
}

/* ── 6. DELETE without a session Origin is rejected before upstream ───────────────── */
for (const originCase of [{}, { Origin: FOREIGN_ORIGIN }]) {
  calls.length = 0;
  const label = originCase.Origin ? "a foreign Origin" : "a missing Origin";
  const { response, upstream } = await bridgeCall("/api/padiem/b66/quotes/" + ROW_ID, {
    method: "DELETE",
    headers: sessionHeaders(originCase)
  });
  assert.equal(response.status, 403, "a session delete with " + label + " is rejected");
  assert.equal(upstream.length, 0, "a rejected delete with " + label + " never reaches upstream");
}

/* ── 7. an invalid quote row id is denied before upstream ────────────────────────── */
for (const badId of [
  "not-a-row",
  "../assets/b66asset_" + "a".repeat(32),
  ROW_ID + "/extra",
  ROW_ID.toUpperCase()
]) {
  calls.length = 0;
  const { response, upstream } = await bridgeCall("/api/padiem/b66/quotes/" + badId, {
    method: "DELETE",
    headers: sessionHeaders({ Origin: PAGES_ORIGIN })
  });
  assert.equal(response.status, 404, "an invalid quote row id is not routed (" + badId + ")");
  assert.equal(upstream.length, 0, "an invalid quote row id never reaches upstream (" + badId + ")");
}

/* ── 8. an out-of-range or malformed limit is denied before upstream ─────────────── */
for (const badLimit of ["51", "0", "999", "1e3", "20x", "-5"]) {
  calls.length = 0;
  const { response, upstream } = await bridgeCall("/api/padiem/b66/quotes?limit=" + badLimit, { method: "GET" });
  assert.equal(response.status, 404, "a rejected limit is not routed (limit=" + badLimit + ")");
  assert.equal(upstream.length, 0, "a rejected limit never reaches upstream (limit=" + badLimit + ")");
}

/* the boundary limits that must still be routable */
for (const okLimit of ["1", "50"]) {
  calls.length = 0;
  const { response, upstream } = await bridgeCall("/api/padiem/b66/quotes?limit=" + okLimit, { method: "GET" });
  assert.equal(response.status, 200, "a bounded limit stays routable (limit=" + okLimit + ")");
  assert.equal(upstream.length, 1, "a bounded limit reaches upstream once (limit=" + okLimit + ")");
  assert.equal(upstream[0].url, CHAT_ORIGIN + "/api/b66/quotes?limit=" + okLimit,
    "the canonical limit is preserved (limit=" + okLimit + ")");
}

/* ── 9. the browser client must not forge Origin ────────────────────────────────── */
{
  let seenInit = null;
  const capture = async (_url, init) => {
    seenInit = init || {};
    return json({ ok: true, quotes: [], limit: 20 });
  };
  await ServerHistory.listQuotes({ fetch: capture, limit: 5 });
  assert.ok(seenInit, "the quote list probe captured the client request");
  assert.equal(new Headers(seenInit.headers || {}).get("origin"), null,
    "the quote-history client never sets an Origin header on reads");
  assert.equal(seenInit.credentials, "same-origin",
    "the quote-history client relies on the same-origin fetch contract");

  const saveInit = await (async () => {
    let captured = null;
    await ServerHistory.saveQuote({ schema: ServerHistory.SNAPSHOT_SCHEMA }, {
      fetch: async (_url, init) => {
        captured = init || {};
        return json({ ok: true, quote: { quote_history_id: ROW_ID, snapshot: {} } }, { status: 201 });
      }
    });
    return captured;
  })();
  const saveHeaders = new Headers(saveInit.headers || {});
  assert.equal(saveHeaders.get("origin"), null,
    "the quote-history client never sets an Origin header on saves");
  assert.equal(saveInit.credentials, "same-origin",
    "the quote save relies on the same-origin fetch contract");

  /* structural backstop: the client source must not construct an Origin header at all */
  const clientSource = fs.readFileSync(path.join(HERE, "..", "quote-history-server.js"), "utf8");
  assert.doesNotMatch(clientSource, /["']origin["']\s*:/i,
    "quote-history-server.js contains no Origin header construction");
}

globalThis.fetch = originalFetch;

console.log("QUOTE_HISTORY_BRIDGE_ORIGIN=PASS");
console.log("QUOTE_HISTORY_ORIGIN_POLICY_REUSED=#3697");
console.log("MUTATING_METHODS_GATE=PASS");
console.log("UPSTREAM_ORIGIN_CANONICAL=PASS");
console.log("QUOTE_HISTORY_POST_ORIGIN_GATE=PASS");
console.log("QUOTE_HISTORY_DELETE_ORIGIN_GATE=PASS");
console.log("QUOTE_HISTORY_ROUTE_BOUNDARY=PASS");
console.log("QUOTE_HISTORY_LIMIT_BOUNDARY=PASS");
console.log("BROWSER_ORIGIN_FORGED=0");
console.log("UPSTREAM_CALLS_ON_REJECTION=0");
console.log("NETWORK_CALLS_OUTSIDE_STUB=0");