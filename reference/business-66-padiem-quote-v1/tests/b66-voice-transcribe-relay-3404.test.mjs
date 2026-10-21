import assert from "node:assert/strict";

/* #3404 Pages relay for the B66 voice transcription route.
   Offline only: the upstream is an in-memory stub, so no credential, network,
   provider call or Production action happens here.

   The regression this file protects: a real 4-20s utterance arrives as
   130-260KiB of audio. While the relay applied the 32KiB bridge default to
   this route, every real chunk was answered 413 request_too_large before it
   reached the Chat Worker, so the microphone started, captured speech and then
   produced no transcript at all.

   #4379: the front now uploads the recorded Blob as the raw body. The relay
   must forward the audio-type and utterance-id headers for this route only,
   and must leave the bytes untouched; the legacy JSON envelope stays relayed
   unchanged for a browser that has not reloaded the new front. */

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

function postAudio(path, bytes, extraHeaders = {}) {
  return post(path, bytes, {
    "Content-Type": "application/octet-stream",
    "X-Padiem-Audio-Type": "audio/webm;codecs=opus",
    "X-Padiem-Utterance-Id": "u1-1",
    ...extraHeaders
  });
}

/* A legacy transcribe envelope padded to an exact JSON byte length. The relay
   bounds bytes and the stub upstream never decodes the audio, so the base64
   filler only has to be the right size — it is not claimed to be valid audio. */
function legacyTranscribeBody(totalBytes) {
  const prefix = '{"audio_base64":"';
  const suffix = '","mime_type":"audio/webm","utterance_id":"u1-1"}';
  return prefix + "A".repeat(totalBytes - prefix.length - suffix.length) + suffix;
}

try {
  // Real captured chunk sizes observed in Production (131KB-262KB). These are
  // sent as raw bytes now; the relay budget is shape-agnostic.
  for (const size of [131600, 262012]) {
    const chunk = new Uint8Array(size);
    chunk.set([0x1a, 0x45, 0xdf, 0xa3, 0x9f, 0x42, 0x86, 0x81], 0); // EBML magic
    const relayed = await postAudio("/api/padiem/voice/transcribe", chunk);
    assert.equal(relayed.status, 200, `a ${size}-byte voice chunk must not be refused by the relay`);
    const call = calls[calls.length - 1];
    assert.equal(call.url, `${CHAT_ORIGIN}/api/voice/transcribe`);
    assert.equal(call.init.method, "POST");
    assert.equal(call.init.headers.get("content-type"), "application/octet-stream");
    assert.equal(call.init.headers.get("x-padiem-audio-type"), "audio/webm;codecs=opus");
    assert.equal(call.init.headers.get("x-padiem-utterance-id"), "u1-1");
    assert.equal(call.init.headers.get("cookie"), SESSION);
    assert.equal(call.init.headers.get("origin"), CHAT_ORIGIN);
    assert.equal(call.init.headers.get("authorization"), null, "browser credentials never leave the browser");
    const forwarded = new Uint8Array(call.init.body);
    assert.equal(forwarded.byteLength, size, "the audio body is forwarded byte-for-byte");
    assert.deepEqual(Array.from(forwarded.slice(0, 8)), [0x1a, 0x45, 0xdf, 0xa3, 0x9f, 0x42, 0x86, 0x81]);
  }
  console.log("B66_VOICE_CHUNK_RELAY=PASS");

  // A browser still running the old front keeps working: the legacy JSON
  // envelope is relayed with its own content type.
  const legacy = await post("/api/padiem/voice/transcribe", legacyTranscribeBody(4096));
  assert.equal(legacy.status, 200);
  const legacyCall = calls[calls.length - 1];
  assert.equal(legacyCall.init.headers.get("content-type"), "application/json");
  assert.equal(legacyCall.init.headers.get("x-padiem-audio-type"), null);
  console.log("B66_VOICE_LEGACY_JSON_RELAY=PASS");

  // The widened budget stays finite and equals what the Chat Worker accepts:
  // 5MiB envelope + 64KiB JSON wrapper.
  const before = calls.length;
  const oversized = await post(
    "/api/padiem/voice/transcribe",
    legacyTranscribeBody(5 * 1024 * 1024 + 64 * 1024 + 1)
  );
  assert.equal(oversized.status, 413);
  assert.equal((await oversized.json()).error.code, "request_too_large");
  assert.equal(calls.length, before, "an over-budget voice body must fail before upstream io");
  console.log("B66_VOICE_BUDGET_CEILING=PASS");

  // The widened budget belongs to the voice route alone.
  const quote = await post("/api/padiem/b66/quote/interpret", legacyTranscribeBody(64 * 1024));
  assert.equal(quote.status, 413);
  assert.equal((await quote.json()).error.code, "request_too_large");
  assert.equal(calls.length, before);
  console.log("B66_VOICE_BUDGET_SCOPE=32KIB_FOR_OTHER_ROUTES");

  // The audio headers belong to the voice route alone: another allowlisted
  // bridge route must not carry them upstream.
  const other = await postAudio(
    "/api/padiem/b66/quote/interpret",
    new Uint8Array(64),
    { "Content-Type": "application/json" }
  );
  assert.equal(other.status, 200);
  const otherCall = calls[calls.length - 1];
  assert.equal(otherCall.url, `${CHAT_ORIGIN}/api/b66/quote/interpret`);
  assert.equal(otherCall.init.headers.get("x-padiem-audio-type"), null);
  assert.equal(otherCall.init.headers.get("x-padiem-utterance-id"), null);
  console.log("B66_VOICE_HEADER_SCOPE=PASS");

  // Identity lookup and method pinning are unchanged.
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
  const foreign = await postAudio(
    "/api/padiem/voice/transcribe",
    new Uint8Array(4096),
    { "Origin": "https://evil.example" }
  );
  assert.equal(foreign.status, 403);
  console.log("B66_VOICE_ORIGIN_GUARD=PASS");
} finally {
  globalThis.fetch = originalFetch;
}
