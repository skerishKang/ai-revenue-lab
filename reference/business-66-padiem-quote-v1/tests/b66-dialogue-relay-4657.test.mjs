import assert from "node:assert/strict";

/* #4657: the Pages relay for the B66 previous-dialogue rail.
   Offline only: the upstream is an in-memory stub, so no credential, network or
   Production action happens here. The relay must bound the path, the query and
   the row id, and must never forward an owner, tenant or scope of the caller's
   choosing. */

const PAGES_ORIGIN = "https://quick-quote-kr.pages.dev";
const CHAT_ORIGIN = "https://chat.padiem.net";
const SESSION = "padiem_session=opaque-test-token";
const DIALOGUE_ID = "chat_" + "a".repeat(32);

const calls = [];
const originalFetch = globalThis.fetch;
globalThis.fetch = async (target, init = {}) => {
  calls.push({ url: String(target), init });
  return new Response(
    JSON.stringify({ ok: true, authority: "b66-dialogue", conversations: [] }),
    { status: 200, headers: { "Content-Type": "application/json" } }
  );
};

const { default: worker } = await import("../_worker.js");

function call(method, path, extraHeaders = {}) {
  return worker.fetch(
    new Request(`${PAGES_ORIGIN}${path}`, {
      method,
      headers: {
        "Cookie": SESSION,
        "Origin": PAGES_ORIGIN,
        "Authorization": "Bearer must-not-leave-the-browser",
        ...extraHeaders
      }
    }),
    {}
  );
}

try {
  // The bounded list relays, and the upstream is the Chat Worker's own path.
  const list = await call("GET", "/api/padiem/b66/ai/dialogues");
  assert.equal(list.status, 200);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, `${CHAT_ORIGIN}/api/b66/ai/dialogues`);
  assert.equal(calls[0].init.headers.get("cookie"), SESSION);
  assert.equal(calls[0].init.headers.get("authorization"), null,
    "the caller's bearer token must not leave the browser");
  console.log("B66_DIALOGUE_LIST_RELAY=PASS");

  // A bounded search query is forwarded verbatim.
  const search = await call("GET", "/api/padiem/b66/ai/dialogues?q=%EC%B2%A0%EA%B7%BC&limit=20");
  assert.equal(search.status, 200);
  assert.equal(calls.length, 2);
  assert.equal(calls[1].url, `${CHAT_ORIGIN}/api/b66/ai/dialogues?q=%EC%B2%A0%EA%B7%BC&limit=20`);
  console.log("B66_DIALOGUE_SEARCH_RELAY=PASS");

  // No other query parameter may be smuggled through the bridge.
  const smuggled = await call("GET", "/api/padiem/b66/ai/dialogues?owner=usr_" + "b".repeat(32));
  assert.equal(smuggled.status, 404);
  assert.equal((await smuggled.json()).error.code, "padiem_route_not_allowed");
  assert.equal(calls.length, 2, "a rejected query reaches no upstream");
  console.log("B66_DIALOGUE_QUERY_BOUNDED=PASS");

  const longQuery = await call("GET", "/api/padiem/b66/ai/dialogues?q=" + "a".repeat(200));
  assert.equal(longQuery.status, 404);
  const badLimit = await call("GET", "/api/padiem/b66/ai/dialogues?limit=9999");
  assert.equal(badLimit.status, 404);
  assert.equal(calls.length, 2);
  console.log("B66_DIALOGUE_QUERY_LIMITS=PASS");

  // Detail (restore) and delete relay for a canonical id only.
  const detail = await call("GET", `/api/padiem/b66/ai/dialogues/${DIALOGUE_ID}`);
  assert.equal(detail.status, 200);
  assert.equal(calls[2].url, `${CHAT_ORIGIN}/api/b66/ai/dialogues/${DIALOGUE_ID}`);
  const removed = await call("DELETE", `/api/padiem/b66/ai/dialogues/${DIALOGUE_ID}`);
  assert.equal(removed.status, 200);
  assert.equal(calls[3].url, `${CHAT_ORIGIN}/api/b66/ai/dialogues/${DIALOGUE_ID}`);
  assert.equal(calls[3].init.method, "DELETE");
  console.log("B66_DIALOGUE_DETAIL_AND_DELETE_RELAY=PASS");

  const malformed = await call("GET", "/api/padiem/b66/ai/dialogues/not-a-conversation");
  assert.equal(malformed.status, 404);
  const wrongShape = await call("GET", "/api/padiem/b66/ai/dialogues/b66quote_" + "a".repeat(32));
  assert.equal(wrongShape.status, 404);
  assert.equal(calls.length, 4, "a malformed id reaches no upstream");
  console.log("B66_DIALOGUE_ID_SHAPE_ENFORCED=PASS");

  // The rail is not writable through the relay.
  const post = await call("POST", "/api/padiem/b66/ai/dialogues", { "Content-Type": "application/json" });
  assert.equal(post.status, 404);
  assert.equal(calls.length, 4, "POST on the dialogue rail reaches no upstream");
  console.log("B66_DIALOGUE_METHOD_PINNED=PASS");

  // Cross-origin mutation stays refused.
  const foreign = await call("DELETE", `/api/padiem/b66/ai/dialogues/${DIALOGUE_ID}`,
    { "Origin": "https://evil.example" });
  assert.equal(foreign.status, 403);
  assert.equal((await foreign.json()).error.code, "padiem_origin_rejected");
  assert.equal(calls.length, 4);
  console.log("B66_DIALOGUE_SAME_ORIGIN_GUARD=PASS");
} finally {
  globalThis.fetch = originalFetch;
}
console.log("B66_DIALOGUE_RELAY_RUNTIME=PASS");
console.log("PRODUCTION_MUTATION=0");
