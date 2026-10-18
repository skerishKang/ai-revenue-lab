import assert from "node:assert/strict";

/* #3404 Pages relay budget for the B66 voice transcription route.
   Offline only: the upstream is an in-memory stub, so no credential, network,
   provider call or Production action happens here.

   The regression this file protects: a real 4-20s utterance arrives as
   130-260KiB of base64 audio. While the relay applied the 32KiB bridge default
   to this route, every real chunk was answered 413 request_too_large before it
   reached the Chat Worker, so the microphone started, captured speech and then
   produced no transcript at all. */

const PAGES_ORIGIN = "https://quick-quote-kr.pages.dev";
const CHAT_ORIGIN = "https://chat.padiem.net";
const SESSION = "padiem_session=opaque-test-token";

const calls = [];
const originalFetch = globalThis.fetch;
globalThis.fetch = async (target, init = {}) => {
  calls.push({ url: String(target), init });
  return new Response(
    JSON.stringify({ ok: true, text: "안녕하세요. 견적서 만들어 주세요." }),
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

/* A transcribe envelope padded to an exact JSON byte length. The relay bounds
   bytes, and the stub upstream never decodes the audio, so the base64 filler
   only has to be the right size — it is not claimed to be valid audio. */
function transcribeBody(totalBytes) {
  const prefix = '{"audio_base64":"';
  const suffix = '","mime_type":"audio/webm","utterance_id":"u1-1"}';
  return prefix + "A".repeat(totalBytes - prefix.length - suffix.length) + suffix;
}

try {
  // Real captured chunk sizes observed in Production (131KB-262KB).
  for (const size of [131600, 262012]) {
    const relayed = await post("/api/padiem/voice/transcribe", transcribeBody(size));
    assert.equal(relayed.status, 200, `a ${size}-byte voice chunk must not be refused by the relay`);
    const call = calls[calls.length - 1];
    assert.equal(call.url, `${CHAT_ORIGIN}/api/voice/transcribe`);
    assert.equal(call.init.method, "POST");
    assert.equal(call.init.headers.get("cookie"), SESSION);
    assert.equal(call.init.headers.get("origin"), CHAT_ORIGIN);
    assert.equal(call.init.headers.get("authorization"), null, "browser credentials never leave the browser");
  }
  console.log("B66_VOICE_CHUNK_RELAY=PASS");

  // The widened budget stays finite and equals what the Chat Worker accepts:
  // 5MiB base64 envelope + 64KiB JSON wrapper.
  const before = calls.length;
  const oversized = await post(
    "/api/padiem/voice/transcribe",
    transcribeBody(5 * 1024 * 1024 + 64 * 1024 + 1)
  );
  assert.equal(oversized.status, 413);
  assert.equal((await oversized.json()).error.code, "request_too_large");
  assert.equal(calls.length, before, "an over-budget voice body must fail before upstream io");
  console.log("B66_VOICE_BUDGET_CEILING=PASS");

  // The widened budget belongs to the voice route alone.
  const quote = await post("/api/padiem/b66/quote/interpret", transcribeBody(64 * 1024));
  assert.equal(quote.status, 413);
  assert.equal((await quote.json()).error.code, "request_too_large");
  assert.equal(calls.length, before);
  console.log("B66_VOICE_BUDGET_SCOPE=32KIB_FOR_OTHER_ROUTES");

  // Identity lookup and method pinning are unchanged by the budget widening.
  const identity = await worker.fetch(
    new Request(`${PAGES_ORIGIN}/api/padiem/voice/identity`, { headers: { "Cookie": SESSION } }),
    {}
  );
  assert.equal(identity.status, 200);
  assert.equal(calls[calls.length - 1].url, `${CHAT_ORIGIN}/api/voice/identity`);
  console.log("B66_VOICE_IDENTITY_RELAY=PASS");

  const got = await worker.fetch(
    new Request(`${PAGES_ORIGIN}/api/padiem/voice/transcribe`, { headers: { "Cookie": SESSION } }),
    {}
  );
  assert.equal(got.status, 404);
  assert.equal((await got.json()).error.code, "padiem_route_not_allowed");
  console.log("B66_VOICE_METHOD_PINNED=PASS");

  // Cross-origin mutation stays refused on the widened route.
  const foreign = await post(
    "/api/padiem/voice/transcribe",
    transcribeBody(4096),
    { "Origin": "https://evil.example" }
  );
  assert.equal(foreign.status, 403);
  console.log("B66_VOICE_ORIGIN_GUARD=PASS");
} finally {
  globalThis.fetch = originalFetch;
}
