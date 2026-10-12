import assert from "node:assert/strict";

/* #4466 Pages relay for the authenticated B66 dialogue route.
   Offline only: the upstream is an in-memory stub, so no credential, network
   or Production action happens here. */

const PAGES_ORIGIN = "https://quick-quote-kr.pages.dev";
const CHAT_ORIGIN = "https://chat.padiem.net";
const SESSION = "padiem_session=opaque-test-token";

const calls = [];
const originalFetch = globalThis.fetch;
globalThis.fetch = async (target, init = {}) => {
  calls.push({ url: String(target), init });
  return new Response(
    JSON.stringify({ ok: true, answer: "synthetic dialogue", model_id: "synthetic/route" }),
    { status: 200, headers: { "Content-Type": "application/json" } }
  );
};

const { default: worker } = await import("../_worker.js");

function post(path, body, extraHeaders = {}) {
  return worker.fetch(
    new Request(`${PAGES_ORIGIN}${path}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Cookie": SESSION,
        "Origin": PAGES_ORIGIN,
        "Authorization": "Bearer must-not-leave-the-browser",
        ...extraHeaders
      },
      body: body
    }),
    {}
  );
}

/* One user turn padded to an exact JSON byte length, so a budget assertion
   proves the route's own ceiling instead of an incidental payload size. */
function dialogueBody(totalBytes) {
  const prefix = '{"model_id":"synthetic/route","messages":[{"role":"user","content":"';
  const suffix = '"}]}';
  return prefix + "x".repeat(totalBytes - prefix.length - suffix.length) + suffix;
}

try {
  // A conversation longer than the one-sentence quote payload still relays.
  const longTranscript = dialogueBody(64 * 1024);
  const relayed = await post("/api/padiem/b66/ai/chat", longTranscript);
  assert.equal(relayed.status, 200, "a 64KiB dialogue transcript must not be refused");
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, `${CHAT_ORIGIN}/api/b66/ai/chat`);
  assert.equal(calls[0].init.method, "POST");
  assert.equal(calls[0].init.headers.get("cookie"), SESSION);
  assert.equal(calls[0].init.headers.get("origin"), CHAT_ORIGIN);
  assert.equal(calls[0].init.headers.get("authorization"), null);
  console.log("B66_DIALOGUE_RELAY=PASS");

  // The widened budget belongs to this route alone.
  const quote = await post("/api/padiem/b66/quote/interpret", dialogueBody(64 * 1024));
  assert.equal(quote.status, 413);
  assert.equal((await quote.json()).error.code, "request_too_large");
  assert.equal(calls.length, 1, "an over-budget quote body must fail before upstream io");
  console.log("B66_RELAY_BUDGET_SCOPE=32KIB_FOR_OTHER_ROUTES");

  // Even the dialogue route stays bounded; this is not an unbounded proxy.
  const oversized = await post("/api/padiem/b66/ai/chat", dialogueBody(6 * 1024 * 1024 + 1024));
  assert.equal(oversized.status, 413);
  assert.equal(calls.length, 1);
  console.log("B66_DIALOGUE_BUDGET_CEILING=PASS");

  // Method pinning: the dialogue route is not readable through the relay.
  const got = await worker.fetch(
    new Request(`${PAGES_ORIGIN}/api/padiem/b66/ai/chat`, { headers: { "Cookie": SESSION } }),
    {}
  );
  assert.equal(got.status, 404);
  assert.equal((await got.json()).error.code, "padiem_route_not_allowed");
  assert.equal(calls.length, 1, "GET on the dialogue route reaches no upstream");
  console.log("B66_DIALOGUE_METHOD_PINNED=PASS");

  // Cross-origin mutation stays refused for the dialogue route as well.
  const foreign = await post(
    "/api/padiem/b66/ai/chat",
    dialogueBody(256),
    { "Origin": "https://evil.example" }
  );
  assert.equal(foreign.status, 403);
  assert.equal((await foreign.json()).error.code, "padiem_origin_rejected");
  assert.equal(calls.length, 1);
  console.log("B66_DIALOGUE_SAME_ORIGIN_GUARD=PASS");
} finally {
  globalThis.fetch = originalFetch;
}
console.log("B66_AI_CHAT_RELAY_RUNTIME=PASS");
console.log("PRODUCTION_MUTATION=0");
