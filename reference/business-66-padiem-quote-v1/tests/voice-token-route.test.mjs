/* B66 voice token route (#3404) — the Worker side of the STT lane.
   Proves: no grant is minted before the caller's Padiem session verifies, the
   long-lived key is never serialized into a response or relayed from an upstream
   error, the Secrets Store binding is read asynchronously, and the existing quote
   bridge still behaves. */
import assert from "node:assert/strict";
import worker from "../_worker.js";

/* Deliberately inert: not a Google key shape, not high entropy, never a real value. */
const STUB_SECRET = "STUB-GEMINI-SECRET-VALUE-NOT-REAL";
const VOICE_URL = "https://quick-quote-kr.pages.dev/api/b66/voice/token";
const SESSION_COOKIE = "padiem_session=stub-session";

function jsonResponse(payload, status) {
  return new Response(JSON.stringify(payload), {
    status: status === undefined ? 200 : status,
    headers: { "Content-Type": "application/json" }
  });
}

function baseEnv(overrides) {
  return Object.assign({
    ASSETS: { fetch: () => { throw new Error("assets must not serve the API"); } },
    B66_STT_MODEL: "gemini-3.5-transcribe-live",
    B66_STT_LANGUAGES: "ko-KR",
    PADIEM_GEMINI_API_KEY: { get: async () => STUB_SECRET }
  }, overrides || {});
}

function stubFetch(responder) {
  const calls = [];
  const previous = globalThis.fetch;
  globalThis.fetch = async (input, init) => {
    /* the auth probe is passed as a Request built from a URL object, so read the
       url from whichever shape the caller used instead of assuming one */
    const url = typeof input === "string" ? input : String(input.url || input);
    const options = typeof input === "string" ? (init || {}) : input;
    calls.push({
      url,
      method: options.method || (typeof input === "object" ? input.method : "GET"),
      headers: options.headers || (typeof input === "object" ? input.headers : undefined)
    });
    return responder(url, calls.length);
  };
  return { calls, restore: () => { globalThis.fetch = previous; } };
}

const post = (cookie) => worker.fetch(new Request(VOICE_URL, {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    Origin: "https://quick-quote-kr.pages.dev",
    ...(cookie ? { Cookie: cookie } : {})
  },
  body: "{}"
}), baseEnv());

async function main() {
  /* --- method and origin boundaries ------------------------------------- */
  {
    const stub = stubFetch(() => jsonResponse({}));
    const get = await worker.fetch(new Request(VOICE_URL, { method: "GET" }), baseEnv());
    assert.equal(get.status, 405, "GET cannot mint a grant");
    assert.equal((await get.json()).error.code, "voice_token_method_not_allowed");
    assert.equal(stub.calls.length, 0, "a rejected method costs nothing");

    const crossOrigin = await worker.fetch(new Request(VOICE_URL, {
      method: "POST",
      headers: { Origin: "https://evil.example", Cookie: SESSION_COOKIE, "Content-Type": "application/json" },
      body: "{}"
    }), baseEnv());
    assert.equal(crossOrigin.status, 403, "a credentialed cross-origin mutation is refused");
    assert.equal(stub.calls.length, 0, "refused before any upstream call");
    stub.restore();
  }

  /* --- anonymous callers cannot buy a session --------------------------- */
  {
    const stub = stubFetch(() => jsonResponse({}));
    const response = await post(null);
    assert.equal(response.status, 401, "no session cookie, no grant");
    assert.equal((await response.json()).error.code, "voice_token_unauthenticated");
    assert.equal(stub.calls.length, 0, "the mint endpoint was not contacted");
    stub.restore();
  }

  {
    const stub = stubFetch((url) => (url.includes("/api/auth/status")
      ? jsonResponse({ ok: true, authenticated: false, session_state: "signed_out" })
      : jsonResponse({ token: { name: "should-not-be-minted" } })));
    const response = await post(SESSION_COOKIE);
    assert.equal(response.status, 401, "a session that is not signed in is refused");
    assert.equal(stub.calls.length, 1, "only the auth status was consulted");
    assert.ok(stub.calls[0].url.includes("/api/auth/status"), "auth check comes first");
    assert.ok(response.headers.get("Cache-Control").startsWith("no-store"),
      "even a refusal is not cacheable");
    stub.restore();
  }

  {
    const stub = stubFetch(() => Promise.reject(new Error("auth service down")));
    const response = await post(SESSION_COOKIE);
    assert.equal(response.status, 401, "an unreachable auth service fails closed");
    assert.equal((await response.json()).error.code, "voice_token_unauthenticated");
    stub.restore();
  }

  /* --- configuration and binding readiness ------------------------------ */
  {
    const stub = stubFetch(() => jsonResponse({}));
    const noModel = await worker.fetch(new Request(VOICE_URL, {
      method: "POST", headers: { Origin: "https://quick-quote-kr.pages.dev", Cookie: SESSION_COOKIE }, body: "{}"
    }), baseEnv({ B66_STT_MODEL: "" }));
    assert.equal(noModel.status, 503, "an unconfigured model fails closed");
    assert.equal((await noModel.json()).error.code, "voice_config_unavailable");

    const noSecret = await worker.fetch(new Request(VOICE_URL, {
      method: "POST", headers: { Origin: "https://quick-quote-kr.pages.dev", Cookie: SESSION_COOKIE }, body: "{}"
    }), baseEnv({ PADIEM_GEMINI_API_KEY: undefined }));
    assert.equal(noSecret.status, 503, "no binding, no grant");
    assert.equal((await noSecret.json()).error.code, "voice_credential_binding_unavailable");
    assert.equal(stub.calls.length, 0, "neither refusal reached the network");
    stub.restore();
  }

  /* --- happy path: shape, scoping and secrecy --------------------------- */
  {
    const stub = stubFetch((url) => {
      if (url.includes("/api/auth/status")) {
        return jsonResponse({ ok: true, authenticated: true, session_state: "signed_in", methods: {} });
      }
      return jsonResponse({ token: { name: "ephemeral-grant", expireTime: "2026-10-08T05:00:00Z" } });
    });
    const response = await post(SESSION_COOKIE);
    assert.equal(response.status, 200, "a verified session gets a grant");
    assert.equal(response.headers.get("Cache-Control"), "no-store, max-age=0", "grants are never cacheable");
    const body = await response.text();
    assert.equal(body.includes(STUB_SECRET), false, "the long-lived key never leaves the Worker");
    const granted = JSON.parse(body);
    assert.equal(granted.ok, true);
    assert.equal(granted.token, "ephemeral-grant");
    assert.equal(granted.model, "gemini-3.5-transcribe-live");
    assert.match(granted.websocketUrl, /^wss:\/\/generativelanguage\.googleapis\.com\/ws\//, "current WS surface");
    assert.ok(granted.websocketUrl.includes("v1beta"), "the v1beta path is the documented one");
    assert.ok(!granted.websocketUrl.includes("access_token"), "the token is not baked into the stored URL");
    assert.equal(granted.singleUse, true, "uses:1 is surfaced so the client cannot reuse it");
    assert.deepEqual(granted.languageCodes, ["ko-KR"]);

    const mint = stub.calls.find((call) => call.url.includes("auth_tokens"));
    assert.ok(mint, "the documented token endpoint was used");
    assert.equal(mint.url, "https://generativelanguage.googleapis.com/v1beta/auth_tokens");
    assert.equal(mint.headers["x-goog-api-key"], STUB_SECRET, "the key travels only in that header");
    assert.equal(mint.headers["Content-Type"], "application/json");
    stub.restore();
  }

  /* the mint request itself is scoped: one use, one model, TEXT only */
  {
    let sentBody = null;
    const stub = { calls: [] };
    const previous = globalThis.fetch;
    globalThis.fetch = async (input, init) => {
      const url = typeof input === "string" ? input : String(input.url || input);
      if (url.includes("/api/auth/status")) {
        return jsonResponse({ ok: true, authenticated: true, session_state: "signed_in" });
      }
      sentBody = JSON.parse((init || {}).body);
      return jsonResponse({ token: { name: "grant" } });
    };
    await post(SESSION_COOKIE);
    globalThis.fetch = previous;
    assert.equal(sentBody.uses, 1, "single-use grant");
    assert.equal(sentBody.liveConnectConstraints.model, "models/gemini-3.5-transcribe-live");
    assert.deepEqual(sentBody.liveConnectConstraints.config.responseModalities, ["TEXT"],
      "the grant cannot authorize an answering model");
    assert.equal(sentBody.liveConnectConstraints.config.inputAudioTranscription.mode, "VERBATIM");
    assert.ok(sentBody.expireTime && sentBody.newSessionExpireTime, "both lifetimes are declared");
    assert.equal(new Date(sentBody.newSessionExpireTime) <= new Date(sentBody.expireTime), true,
      "the session must open before the message window closes");
  }

  /* --- upstream failures never echo back ------------------------------- */
  {
    const stub = stubFetch((url) => (url.includes("/api/auth/status")
      ? jsonResponse({ ok: true, authenticated: true, session_state: "signed_in" })
      : jsonResponse({
        error: { message: "quota exceeded for key " + STUB_SECRET, status: "RESOURCE_EXHAUSTED" }
      }, 429)));
    const response = await post(SESSION_COOKIE);
    const text = await response.text();
    assert.equal(response.status, 502, "a refused mint is a bounded failure");
    assert.equal(JSON.parse(text).error.code, "voice_token_denied");
    assert.equal(text.includes(STUB_SECRET), false, "the upstream body is not relayed");
    assert.equal(text.includes("RESOURCE_EXHAUSTED"), false, "no upstream detail leaks");
    stub.restore();
  }

  {
    const stub = stubFetch((url) => (url.includes("/api/auth/status")
      ? jsonResponse({ ok: true, authenticated: true, session_state: "signed_in" })
      : jsonResponse({ someOtherShape: true })));
    const response = await post(SESSION_COOKIE);
    assert.equal(response.status, 502, "a grant without a name is not a session");
    assert.equal((await response.json()).error.code, "voice_token_missing");
    stub.restore();
  }

  {
    const stub = stubFetch((url) => (url.includes("/api/auth/status")
      ? jsonResponse({ ok: true, authenticated: true, session_state: "signed_in" })
      : jsonResponse({ token: "plain-string-grant" })));
    const response = await post(SESSION_COOKIE);
    assert.equal(response.status, 200, "a plain token shape is still accepted");
    assert.equal((await response.json()).token, "plain-string-grant");
    stub.restore();
  }

  /* --- oversized bodies ------------------------------------------------- */
  {
    const stub = stubFetch(() => jsonResponse({}));
    const tooBig = await worker.fetch(new Request(VOICE_URL, {
      method: "POST",
      headers: { Origin: "https://quick-quote-kr.pages.dev", Cookie: SESSION_COOKIE },
      body: "x".repeat(4096)
    }), baseEnv());
    assert.equal(tooBig.status, 413, "the voice route stays bounded");
    assert.equal(stub.calls.length, 0);
    stub.restore();
  }

  /* --- the existing quote bridge still works (regression) ---------------- */
  {
    const stub = stubFetch(() => jsonResponse({ ok: true, draft: null }));
    const interpret = await worker.fetch(new Request(
      "https://quick-quote-kr.pages.dev/api/padiem/b66/quote/interpret",
      { method: "POST", headers: { Origin: "https://quick-quote-kr.pages.dev", Cookie: SESSION_COOKIE }, body: "{}" }
    ), baseEnv());
    assert.equal(interpret.status, 200, "the canonical interpret bridge is unchanged");
    assert.ok(stub.calls.some((call) => call.url.endsWith("/api/b66/quote/interpret")));

    const intake = await worker.fetch(new Request(
      "https://quick-quote-kr.pages.dev/api/v1/quote/intake", { method: "POST", body: "{}" }
    ), baseEnv());
    assert.equal(intake.status, 410, "intake stays disabled (#3481 Policy A)");
    stub.restore();
  }

  console.log("B66_VOICE_TOKEN_ROUTE=PASS");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
