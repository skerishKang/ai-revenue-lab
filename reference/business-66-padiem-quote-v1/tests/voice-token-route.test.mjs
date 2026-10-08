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

function headerValue(headers, name) {
  if (!headers) return undefined;
  if (typeof headers.get === "function") return headers.get(name);
  return headers[name];
}

function stubFetch(responder) {
  const calls = [];
  const previous = globalThis.fetch;
  globalThis.fetch = async (input, init) => {
    /* the auth probe is passed as fetch(urlObject, init), so the headers live on `init`
       while a Request-shaped call would carry them itself — read whichever has them */
    const url = typeof input === "string" ? input : String(input.url || input);
    const carrier = init || input || {};
    calls.push({
      url,
      method: carrier.method || (typeof input === "object" ? input.method : "GET"),
      headers: carrier.headers || (typeof input === "object" ? input.headers : undefined),
      cookie: headerValue(carrier.headers || (typeof input === "object" ? input.headers : undefined), "Cookie"),
      apiKey: headerValue(carrier.headers || (typeof input === "object" ? input.headers : undefined), "x-goog-api-key")
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
    assert.equal(granted.apiVersion, "v1alpha",
      "the version the pinned SDK pairs with an auth_tokens grant");
    assert.equal("websocketUrl" in granted, false,
      "no socket URL is handed out: the SDK assembles the constrained session itself");
    assert.equal(granted.singleUse, true, "uses:1 is surfaced so the client cannot reuse it");
    assert.deepEqual(granted.languageCodes, ["ko-KR"]);

    const mint = stub.calls.find((call) => call.url.includes("auth_tokens"));
    assert.ok(mint, "the documented token endpoint was used");
    assert.equal(mint.url, "https://generativelanguage.googleapis.com/v1alpha/auth_tokens");
    assert.equal(mint.apiKey, STUB_SECRET, "the key travels only in that header");
    assert.equal(mint.cookie || null, null, "the mint request carries no user session: only the key");
    assert.equal(mint.headers["Content-Type"], "application/json");
    stub.restore();
  }

  /* --- the mint host is pinned, so the key cannot be redirected --------- */
  {
    const hostile = [
      "https://attacker.example/v1alpha/auth_tokens",
      "http://generativelanguage.googleapis.com/v1alpha/auth_tokens",
      "https://generativelanguage.googleapis.com/v1beta/auth_tokens",
      "https://generativelanguage.googleapis.com/v1alpha/auth_tokens?key=leak",
      "https://generativelanguage.googleapis.com@attacker.example/v1alpha/auth_tokens",
      "//generativelanguage.googleapis.com/v1alpha/auth_tokens",
      "not a url"
    ];
    for (const value of hostile) {
      const stub = stubFetch(() => jsonResponse({}));
      const response = await worker.fetch(new Request(VOICE_URL, {
        method: "POST",
        headers: { Origin: "https://quick-quote-kr.pages.dev", Cookie: SESSION_COOKIE },
        body: "{}"
      }), baseEnv({ B66_STT_TOKEN_URL: value }));
      assert.equal(response.status, 503, `refused: ${value}`);
      assert.equal((await response.json()).error.code, "voice_config_unavailable");
      assert.equal(stub.calls.length, 0, `the key never travels for ${value}`);
      stub.restore();
    }

    /* the exact allowed endpoint is accepted, so the gate is a pin and not a block */
    const stub = stubFetch((url) => (url.includes("/api/auth/status")
      ? jsonResponse({ ok: true, authenticated: true, session_state: "signed_in" })
      : jsonResponse({ token: { name: "pinned-grant" } })));
    const ok = await worker.fetch(new Request(VOICE_URL, {
      method: "POST",
      headers: { Origin: "https://quick-quote-kr.pages.dev", Cookie: SESSION_COOKIE },
      body: "{}"
    }), baseEnv({ B66_STT_TOKEN_URL: "https://generativelanguage.googleapis.com/v1alpha/auth_tokens" }));
    assert.equal(ok.status, 200, "the pinned endpoint itself still works");
    stub.restore();
  }

  /* --- the grant follows THIS caller's session, never a blanket verdict -- */
  {
    const stub = stubFetch((url) => (url.includes("/api/auth/status")
      /* a different account's session simply does not verify here */
      ? jsonResponse({ ok: true, authenticated: false, session_state: "signed_out" })
      : jsonResponse({ token: { name: "must-not-be-minted" } })));
    const otherAccount = await worker.fetch(new Request(VOICE_URL, {
      method: "POST",
      headers: { Origin: "https://quick-quote-kr.pages.dev", Cookie: "padiem_session=someone-elses-session" },
      body: "{}"
    }), baseEnv());
    assert.equal(otherAccount.status, 401, "another account's session gets no grant");
    assert.equal(stub.calls.length, 1, "the caller's own cookie is what was verified");
    assert.equal(stub.calls[0].cookie, "padiem_session=someone-elses-session",
      "the probe carries the caller's session, not a service-wide one");
    assert.equal(stub.calls[0].apiKey || null, null, "the Gemini key is never attached to the auth probe");
    stub.restore();
  }

  {
    const stub = stubFetch((url) => (url.includes("/api/auth/status")
      ? jsonResponse({ ok: true, user: "someone" })
      : jsonResponse({ token: { name: "nope" } })));
    const response = await post(SESSION_COOKIE);
    assert.equal(response.status, 401, "an auth reply without the signed-in shape is not a grant");
    assert.equal(stub.calls.length, 1, "and it stopped before minting");
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
    /* The body is the wire shape the pinned SDK's createAuthTokenParametersToMldev sends:
       a config wrapper, with liveConnectConstraints carrying setup.model plus the
       constrained config. */
    assert.equal(typeof sentBody.config, "object", "the request is wrapped in config");
    const config = sentBody.config;
    assert.equal(config.uses, 1, "single-use grant");
    assert.equal(config.liveConnectConstraints.setup.model, "models/gemini-3.5-transcribe-live",
      "tModel prefixes the model exactly as the SDK does");
    assert.deepEqual(config.liveConnectConstraints.config.responseModalities, ["TEXT"],
      "the grant cannot authorize an answering model");
    assert.equal(config.liveConnectConstraints.config.inputAudioTranscription.mode, "VERBATIM");
    assert.equal(config.liveConnectConstraints.config.realtimeInputConfig
      .automaticActivityDetection.silenceDurationMs, 650);
    assert.ok(config.expireTime && config.newSessionExpireTime, "both lifetimes are declared");
    assert.equal(new Date(config.newSessionExpireTime) <= new Date(config.expireTime), true,
      "the session must open before the message window closes");
    assert.equal(JSON.stringify(sentBody).includes(STUB_SECRET), false,
      "the long-lived key is never in the mint body");
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

/* A pending await that never settles would end the process with no output and exit code 0,
   which is a silent false green. The watchdog turns "it hung" into a loud failure. */
const watchdog = setTimeout(() => {
  console.error("B66_VOICE_TOKEN_ROUTE=TIMEOUT");
  console.error("MEANING=main() never settled; an await has neither resolved nor rejected");
  process.exit(1);
}, 30000);

main().then(
  () => clearTimeout(watchdog),
  (error) => {
    clearTimeout(watchdog);
    console.error("B66_VOICE_TOKEN_ROUTE=FAIL");
    console.error(error && error.stack ? error.stack : String(error));
    process.exit(1);
  }
);
