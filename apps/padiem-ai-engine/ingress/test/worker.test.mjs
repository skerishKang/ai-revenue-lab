import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { handleIngress, MAX_ENGINE_ATTEMPTS } from "../worker.mjs";

const EXECUTE_URL = "https://ingress.example/internal/v1/execute";
const INGRESS_SECRET = "s".repeat(64);
const ENGINE_CALLER_ID = "storymemory-b61";
const ENGINE_CALLER_SECRET = "e".repeat(64);
const ENGINE_CALLER_SECRET_NEXT = "n".repeat(64);
const ENGINE_CREDENTIAL_HEADER = "x-padiem-engine-credential";
const ENGINE_CALLER_HEADER = "x-padiem-engine-caller";

// A valid request supplies ONLY the ingress client credential. It also
// supplies caller-engineered Engine headers that MUST be ignored/stripped.
function validRequest(url = EXECUTE_URL, ingressCredential = INGRESS_SECRET) {
  return new Request(url, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-padiem-ingress-credential": ingressCredential,
      // (D/E) caller attempts to assert its own Engine identity:
      [ENGINE_CALLER_HEADER]: "attacker-caller",
      [ENGINE_CREDENTIAL_HEADER]: "attacker-credential-" + "z".repeat(50),
    },
    body: JSON.stringify({ app_id: "b61", messages: [{ role: "user", content: "hi" }] }),
  });
}

function fakeEnv(opts = {}) {
  const calls = [];
  const {
    ingressClientSecret = INGRESS_SECRET,
    engineCallerId = ENGINE_CALLER_ID,
    engineCallerSecret = ENGINE_CALLER_SECRET,
    response = new Response(JSON.stringify({ ok: true }), { status: 200 }),
    engineFetch,
  } = opts;

  const fetchImpl = async (request) => {
    calls.push(request);
    return engineFetch ? engineFetch(request) : response;
  };

  const env = {
    PADIEM_INGRESS_CLIENT_SECRET: ingressClientSecret,
    PADIEM_ENGINE_CALLER_ID: engineCallerId,
    PADIEM_ENGINE_CALLER_SECRET: engineCallerSecret,
    ENGINE: { fetch: fetchImpl },
  };

  return { calls, env };
}

test("A. valid ingress credential forwards exactly once to the fixed Engine target", async () => {
  const { calls, env } = fakeEnv();
  const response = await handleIngress(validRequest(), env);

  assert.equal(response.status, 200);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, "https://padiem-ai-engine/internal/v1/execute");
  assert.equal(calls[0].method, "POST");
  assert.equal(calls[0].headers.get("content-type"), "application/json");
});

test("B. missing ingress credential fails closed before Engine", async () => {
  const { calls, env } = fakeEnv();
  const request = new Request(EXECUTE_URL, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: "{}",
  });

  const response = await handleIngress(request, env);
  assert.equal(response.status, 401);
  assert.equal(calls.length, 0);
});

test("C. wrong ingress credential fails closed before Engine", async () => {
  const { calls, env } = fakeEnv();
  const request = validRequest(EXECUTE_URL, "wrong-credential-payload");

  const response = await handleIngress(request, env);
  assert.equal(response.status, 401);
  assert.equal(calls.length, 0);
});

test("D. caller-supplied X-Padiem-Engine-Credential is ignored and never forwarded", async () => {
  const { calls, env } = fakeEnv();
  await handleIngress(validRequest(), env);

  assert.equal(calls.length, 1);
  // The forwarded credential MUST be the env-owned secret, not the caller value.
  assert.equal(calls[0].headers.get(ENGINE_CREDENTIAL_HEADER), ENGINE_CALLER_SECRET);
  assert.notEqual(calls[0].headers.get(ENGINE_CREDENTIAL_HEADER), "attacker-credential-" + "z".repeat(50));
});

test("E. caller-supplied X-Padiem-Engine-Caller cannot override server identity", async () => {
  const { calls, env } = fakeEnv();
  await handleIngress(validRequest(), env);

  assert.equal(calls.length, 1);
  assert.equal(calls[0].headers.get(ENGINE_CALLER_HEADER), ENGINE_CALLER_ID);
  assert.notEqual(calls[0].headers.get(ENGINE_CALLER_HEADER), "attacker-caller");
});

test("F. Engine request receives only env-owned caller id and credential", async () => {
  const { calls, env } = fakeEnv({
    engineCallerId: "storymemory-b61",
    engineCallerSecret: ENGINE_CALLER_SECRET,
  });

  // Caller supplies spoofed values for both Engine headers.
  const request = new Request(EXECUTE_URL, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-padiem-ingress-credential": INGRESS_SECRET,
      [ENGINE_CALLER_HEADER]: "spoofed-id",
      [ENGINE_CREDENTIAL_HEADER]: "spoofed-secret",
    },
    body: "{}",
  });

  const response = await handleIngress(request, env);
  assert.equal(response.status, 200);
  assert.equal(calls[0].headers.get(ENGINE_CALLER_HEADER), "storymemory-b61");
  assert.equal(calls[0].headers.get(ENGINE_CREDENTIAL_HEADER), ENGINE_CALLER_SECRET);

  // No additional engine-related headers leak through.
  const forwardedHeaders = [...calls[0].headers.keys()]
    .filter((k) => /engine|caller/i.test(k))
    .sort();
  assert.deepEqual(forwardedHeaders, [ENGINE_CALLER_HEADER, ENGINE_CREDENTIAL_HEADER]);
});

test("G. Origin (browser) requests fail closed before Engine", async () => {
  const { calls, env } = fakeEnv();
  const request = validRequest();
  const headers = new Headers(request.headers);
  headers.set("origin", "https://storymemory.example");
  const browserRequest = new Request(request.url, {
    method: "POST",
    headers,
    body: await request.text(),
  });

  const response = await handleIngress(browserRequest, env);
  assert.equal(response.status, 403);
  assert.equal(calls.length, 0);
  assert.equal(response.headers.get("access-control-allow-origin"), null);
});

test("H. wrong path, method, media type, and oversized body are rejected before Engine", async () => {
  // wrong path
  const first = fakeEnv();
  const wrongPath = await handleIngress(validRequest("https://ingress.example/other"), first.env);
  assert.equal(wrongPath.status, 404);
  assert.equal(first.calls.length, 0);

  // wrong method
  const second = fakeEnv();
  const wrongMethod = await handleIngress(new Request(EXECUTE_URL, { method: "GET" }), second.env);
  assert.equal(wrongMethod.status, 405);
  assert.equal(second.calls.length, 0);

  // wrong content-type
  const third = fakeEnv();
  const wrongMedia = new Request(EXECUTE_URL, {
    method: "POST",
    headers: { "content-type": "text/plain", "x-padiem-ingress-credential": INGRESS_SECRET },
    body: "{}",
  });
  const mediaResp = await handleIngress(wrongMedia, third.env);
  assert.equal(mediaResp.status, 415);
  assert.equal(third.calls.length, 0);

  // oversized body
  const fourth = fakeEnv();
  const big = new Request(EXECUTE_URL, {
    method: "POST",
    headers: { "content-type": "application/json", "x-padiem-ingress-credential": INGRESS_SECRET },
    body: "x".repeat(128 * 1024 + 1),
  });
  const sizeResp = await handleIngress(big, fourth.env);
  assert.equal(sizeResp.status, 413);
  assert.equal(fourth.calls.length, 0);
});

test("I. forwards only to the fixed ENGINE binding", async () => {
  const { calls, env } = fakeEnv({
    engineFetch: (req) => {
      // Ensure the caller cannot redirect via query/origin header tricks.
      assert.equal(new URL(req.url).hostname, "padiem-ai-engine");
      return new Response(JSON.stringify({ ok: true }), { status: 200 });
    },
  });
  const response = await handleIngress(
    validRequest(`${EXECUTE_URL}?target=https://evil.example&service=B14`),
    env,
  );

  assert.equal(response.status, 200);
  assert.equal(calls.length, 1);
  assert.equal(new URL(calls[0].url).hostname, "padiem-ai-engine");
});

test("J. response does not reflect secrets or Engine-internal headers", async () => {
  const upstream = new Response(JSON.stringify({ ok: false }), {
    status: 422,
    headers: {
      "content-type": "application/json",
      "x-private-engine-header": "do-not-reflect",
      "set-cookie": "private=1",
    },
  });
  const { env } = fakeEnv({ response: upstream });
  const response = await handleIngress(validRequest(), env);

  assert.equal(response.status, 422);
  assert.equal(response.headers.get("x-private-engine-header"), null);
  assert.equal(response.headers.get("set-cookie"), null);
  assert.equal(response.headers.get("access-control-allow-origin"), null);
  assert.equal(response.headers.get("x-padiem-engine-caller"), null);
  assert.equal(response.headers.get("x-padiem-engine-credential"), null);
  assert.equal(response.headers.get("x-padiem-ingress-credential"), null);
});

test("K. canonical Engine wrangler.toml leaves Engine private (workers_dev=false)", () => {
  const here = dirname(fileURLToPath(import.meta.url));
  const engineConfig = readFileSync(join(here, "..", "..", "wrangler.toml"), "utf8");
  assert.match(engineConfig, /name\s*=\s*"padiem-ai-engine"/);
  assert.match(engineConfig, /workers_dev\s*=\s*false/);
});

test("L. ingress binding is only the canonical Engine (no B14/Provider binding)", () => {
  const here = dirname(fileURLToPath(import.meta.url));
  const ingressConfig = readFileSync(join(here, "..", "wrangler.toml"), "utf8");

  assert.match(ingressConfig, /name\s*=\s*"padiem-ai-engine-ingress"/);
  assert.match(ingressConfig, /service\s*=\s*"padiem-ai-engine"/);
  // No B14 or Provider service bindings.
  assert.doesNotMatch(ingressConfig, /B14_SERVICE|ai-revenue-korean-ai-platform/i);
  assert.doesNotMatch(ingressConfig, /openrouter|poolside|provider/i);
  // No secret values committed (only the non-secret caller id may appear).
  assert.doesNotMatch(ingressConfig, /PADIEM_ENGINE_CALLER_SECRET\s*=/i);
  assert.doesNotMatch(ingressConfig, /PADIEM_INGRESS_CLIENT_SECRET\s*=/i);
  // Canonical Engine identity is declared as a non-secret var.
  assert.match(ingressConfig, /PADIEM_ENGINE_CALLER_ID\s*=\s*"storymemory-b61"/);
});

test("M. ingress source carries no StoryMemory locator/provider routing semantics", () => {
  const here = dirname(fileURLToPath(import.meta.url));
  const ingressSource = readFileSync(join(here, "..", "worker.mjs"), "utf8");

  assert.doesNotMatch(ingressSource, /StoryMemory|bible:web|B14_SERVICE|openrouter|poolside/i);
  // The ingress must never READ caller-supplied Engine headers off the incoming
  // request. (Defining them as consts to mint forwarded headers is permitted.)
  assert.doesNotMatch(ingressSource, /request\.headers\.get\(\s*["']x-padiem-engine/i);
  assert.doesNotMatch(ingressSource, /request\.headers\.has\(\s*["']x-padiem-engine/i);
  assert.doesNotMatch(ingressSource, /boundedText\(\s*request\.headers\.get\(\s*["']x-padiem-engine/i);
  // The ONLY caller credential header the ingress reads is the ingress one.
  assert.match(ingressSource, /x-padiem-ingress-credential/i);
  // Engine headers are minted from env only.
  assert.match(ingressSource, /PADIEM_ENGINE_CALLER_ID/);
  assert.match(ingressSource, /PADIEM_ENGINE_CALLER_SECRET/);
  assert.match(ingressSource, /PADIEM_INGRESS_CLIENT_SECRET/);
});

// ---------------------------------------------------------------------------
// Dual-credential migration seam (#1753 A0): NEXT-first with exactly one
// CURRENT retry on the precise service_authentication_failed 401 signal.
// ---------------------------------------------------------------------------

// Scripted multi-attempt environment. responses may contain Response objects
// or Error instances (thrown to simulate timeout/engine fetch failure).
function scriptedEnv(engineCallerSecretNext, responses) {
  const calls = [];
  let index = 0;

  const env = {
    PADIEM_INGRESS_CLIENT_SECRET: INGRESS_SECRET,
    PADIEM_ENGINE_CALLER_ID: ENGINE_CALLER_ID,
    PADIEM_ENGINE_CALLER_SECRET: ENGINE_CALLER_SECRET,
    ENGINE: {
      fetch: async (request) => {
        calls.push(request);
        const next = responses[index++];
        if (next instanceof Error) throw next;
        return next ?? new Response(JSON.stringify({ ok: true }), { status: 200 });
      },
    },
  };

  // NEXT is either configured (string) or absent (null/undefined env entry).
  if (engineCallerSecretNext !== null && engineCallerSecretNext !== undefined) {
    env.PADIEM_ENGINE_CALLER_SECRET_NEXT = engineCallerSecretNext;
  }

  return { calls, env };
}

function authFailure401(code = "service_authentication_failed") {
  return new Response(JSON.stringify({ ok: false, error: { code } }), { status: 401 });
}

async function bodyOf(request) {
  return new Uint8Array(await request.clone().arrayBuffer());
}

function assertNoCredentialLeak(response, bodyText) {
  for (const secret of [INGRESS_SECRET, ENGINE_CALLER_SECRET, ENGINE_CALLER_SECRET_NEXT]) {
    assert.ok(!bodyText.includes(secret), "response body leaked a credential");
    for (const [, value] of response.headers) {
      assert.ok(!value.includes(secret), "response header leaked a credential");
    }
  }
}

test("N1. NEXT absent -> CURRENT used, exactly one Engine call", async () => {
  const { calls, env } = scriptedEnv(null, [
    new Response(JSON.stringify({ ok: true }), { status: 200 }),
  ]);
  const response = await handleIngress(validRequest(), env);

  assert.equal(response.status, 200);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].headers.get(ENGINE_CREDENTIAL_HEADER), ENGINE_CALLER_SECRET);
});

test("N2. NEXT present and accepted -> NEXT only, exactly one Engine call", async () => {
  const { calls, env } = scriptedEnv(ENGINE_CALLER_SECRET_NEXT, [
    new Response(JSON.stringify({ ok: true }), { status: 200 }),
  ]);
  const response = await handleIngress(validRequest(), env);

  assert.equal(response.status, 200);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].headers.get(ENGINE_CREDENTIAL_HEADER), ENGINE_CALLER_SECRET_NEXT);
});

test("N3. NEXT exact auth 401 + CURRENT succeeds -> exactly two calls, in order", async () => {
  const { calls, env } = scriptedEnv(ENGINE_CALLER_SECRET_NEXT, [
    authFailure401(),
    new Response(JSON.stringify({ ok: true, answer: "42" }), { status: 200 }),
  ]);
  const response = await handleIngress(validRequest(), env);

  assert.equal(response.status, 200);
  assert.equal(calls.length, 2);
  assert.deepEqual(JSON.parse(await response.text()), { ok: true, answer: "42" });
  assert.equal(calls[0].headers.get(ENGINE_CREDENTIAL_HEADER), ENGINE_CALLER_SECRET_NEXT);
  assert.equal(calls[1].headers.get(ENGINE_CREDENTIAL_HEADER), ENGINE_CALLER_SECRET);
});

test("N4. NEXT 403 (even with auth-failure body) -> no fallback", async () => {
  const { calls, env } = scriptedEnv(ENGINE_CALLER_SECRET_NEXT, [
    new Response(JSON.stringify({ ok: false, error: { code: "service_authentication_failed" } }), { status: 403 }),
  ]);
  const response = await handleIngress(validRequest(), env);

  assert.equal(response.status, 403);
  assert.equal(calls.length, 1);
});

test("N5. NEXT 500 -> no fallback, original response returned", async () => {
  const { calls, env } = scriptedEnv(ENGINE_CALLER_SECRET_NEXT, [
    new Response(JSON.stringify({ ok: false, error: { code: "boom" } }), { status: 500 }),
  ]);
  const response = await handleIngress(validRequest(), env);

  assert.equal(response.status, 500);
  assert.equal(calls.length, 1);
});

test("N6. NEXT fetch throws (timeout) -> no fallback, 503 fail-closed", async () => {
  const { calls, env } = scriptedEnv(ENGINE_CALLER_SECRET_NEXT, [
    new Error("simulated timeout"),
  ]);
  const response = await handleIngress(validRequest(), env);

  assert.equal(response.status, 503);
  assert.equal(calls.length, 1);
});

test("N7. NEXT 401 malformed JSON body -> no fallback", async () => {
  const { calls, env } = scriptedEnv(ENGINE_CALLER_SECRET_NEXT, [
    new Response("{not-json,,", { status: 401 }),
  ]);
  const response = await handleIngress(validRequest(), env);

  assert.equal(response.status, 401);
  assert.equal(calls.length, 1);
});

test("N8. NEXT 401 non-JSON body -> no fallback", async () => {
  const { calls, env } = scriptedEnv(ENGINE_CALLER_SECRET_NEXT, [
    new Response("<html>401</html>", { status: 401 }),
  ]);
  const response = await handleIngress(validRequest(), env);

  assert.equal(response.status, 401);
  assert.equal(calls.length, 1);
});

test("N9. NEXT 401 service_identity_unavailable -> no fallback", async () => {
  const { calls, env } = scriptedEnv(ENGINE_CALLER_SECRET_NEXT, [
    authFailure401("service_identity_unavailable"),
  ]);
  const response = await handleIngress(validRequest(), env);

  assert.equal(response.status, 401);
  assert.equal(calls.length, 1);
});

test("N10. NEXT 401 service_app_not_authorized -> no fallback", async () => {
  const { calls, env } = scriptedEnv(ENGINE_CALLER_SECRET_NEXT, [
    authFailure401("service_app_not_authorized"),
  ]);
  const response = await handleIngress(validRequest(), env);

  assert.equal(response.status, 401);
  assert.equal(calls.length, 1);
});

test("N10b. NEXT 401 JSON without error.code -> no fallback", async () => {
  const { calls, env } = scriptedEnv(ENGINE_CALLER_SECRET_NEXT, [
    new Response(JSON.stringify({ ok: false }), { status: 401 }),
    new Response(JSON.stringify({ ok: true }), { status: 200 }),
  ]);
  const response = await handleIngress(validRequest(), env);

  assert.equal(response.status, 401);
  assert.equal(calls.length, 1);
});

test("N11. fallback replays byte-identical request body on both attempts", async () => {
  const { calls, env } = scriptedEnv(ENGINE_CALLER_SECRET_NEXT, [
    authFailure401(),
    new Response(JSON.stringify({ ok: true }), { status: 200 }),
  ]);
  const inboundBody = new Uint8Array(
    await new Request(EXECUTE_URL, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "x-padiem-ingress-credential": INGRESS_SECRET,
      },
      body: JSON.stringify({ app_id: "b61", messages: [{ role: "user", content: "unicode ✓ éè 漢字" }] }),
    }).arrayBuffer(),
  );

  // validRequest()'s fixed payload for header assertions plus an explicit
  // byte comparison between the two Engine attempts.
  const response = await handleIngress(validRequest(), env);
  assert.equal(response.status, 200);
  assert.equal(calls.length, 2);

  const first = await bodyOf(calls[0]);
  const second = await bodyOf(calls[1]);
  assert.deepEqual(first, second);

  // And the replayed bytes equal the caller's original inbound body exactly.
  const fresh = fakeEnv();
  const passthrough = await handleIngress(
    new Request(EXECUTE_URL, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "x-padiem-ingress-credential": INGRESS_SECRET,
      },
      body: inboundBody,
    }),
    fresh.env,
  );
  assert.equal(passthrough.status, 200);
  assert.deepEqual(await bodyOf(fresh.calls[0]), inboundBody);
});

test("N12. caller id identical on both fallback attempts (and only that header set)", async () => {
  const { calls, env } = scriptedEnv(ENGINE_CALLER_SECRET_NEXT, [
    authFailure401(),
    new Response(JSON.stringify({ ok: true }), { status: 200 }),
  ]);
  await handleIngress(validRequest(), env);

  assert.equal(calls.length, 2);
  assert.equal(calls[0].headers.get(ENGINE_CALLER_HEADER), ENGINE_CALLER_ID);
  assert.equal(calls[1].headers.get(ENGINE_CALLER_HEADER), ENGINE_CALLER_ID);
  assert.equal(calls[0].url, calls[1].url);
  assert.equal(calls[1].url, "https://padiem-ai-engine/internal/v1/execute");
});

test("N13. NEXT credential appears ONLY on the first attempt", async () => {
  const { calls, env } = scriptedEnv(ENGINE_CALLER_SECRET_NEXT, [
    authFailure401(),
    authFailure401(),
    new Response(JSON.stringify({ ok: true }), { status: 200 }),
  ]);
  const response = await handleIngress(validRequest(), env);

  // CURRENT also fails: response returned as-is, no third attempt.
  assert.equal(response.status, 401);
  assert.equal(calls.length, 2);
  assert.equal(calls[0].headers.get(ENGINE_CREDENTIAL_HEADER), ENGINE_CALLER_SECRET_NEXT);
  assert.equal(calls[1].headers.get(ENGINE_CREDENTIAL_HEADER), ENGINE_CALLER_SECRET);
  assert.notEqual(calls[1].headers.get(ENGINE_CREDENTIAL_HEADER), ENGINE_CALLER_SECRET_NEXT);
});

test("N14. CURRENT credential used only in fallback or current-only paths", async () => {
  const fallbackCase = scriptedEnv(ENGINE_CALLER_SECRET_NEXT, [
    authFailure401(),
    new Response(JSON.stringify({ ok: true }), { status: 200 }),
  ]);
  await handleIngress(validRequest(), fallbackCase.env);
  assert.equal(fallbackCase.calls[0].headers.get(ENGINE_CREDENTIAL_HEADER), ENGINE_CALLER_SECRET_NEXT);
  assert.equal(fallbackCase.calls[1].headers.get(ENGINE_CREDENTIAL_HEADER), ENGINE_CALLER_SECRET);

  const currentOnly = scriptedEnv(null, [
    authFailure401(),
    new Response(JSON.stringify({ ok: true }), { status: 200 }),
  ]);
  const resp = await handleIngress(validRequest(), currentOnly.env);
  // NEXT absent: even a matching 401 signal produces exactly one CURRENT call.
  assert.equal(resp.status, 401);
  assert.equal(currentOnly.calls.length, 1);
  assert.equal(currentOnly.calls[0].headers.get(ENGINE_CREDENTIAL_HEADER), ENGINE_CALLER_SECRET);
});

test("N15. ingress client auth unchanged while NEXT configured", async () => {
  const missing = scriptedEnv(ENGINE_CALLER_SECRET_NEXT, []);
  const noCred = new Request(EXECUTE_URL, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: "{}",
  });
  const r1 = await handleIngress(noCred, missing.env);
  assert.equal(r1.status, 401);
  assert.equal(missing.calls.length, 0);

  const wrong = scriptedEnv(ENGINE_CALLER_SECRET_NEXT, []);
  const r2 = await handleIngress(validRequest(EXECUTE_URL, "wrong-" + INGRESS_SECRET), wrong.env);
  assert.equal(r2.status, 401);
  assert.equal(wrong.calls.length, 0);

  const good = scriptedEnv(ENGINE_CALLER_SECRET_NEXT, [
    new Response(JSON.stringify({ ok: true }), { status: 200 }),
  ]);
  const r3 = await handleIngress(validRequest(), good.env);
  assert.equal(r3.status, 200);
  assert.equal(good.calls.length, 1);
});

test("N16. caller-supplied Engine identity headers ignored across both attempts", async () => {
  const { calls, env } = scriptedEnv(ENGINE_CALLER_SECRET_NEXT, [
    authFailure401(),
    new Response(JSON.stringify({ ok: true }), { status: 200 }),
  ]);
  await handleIngress(validRequest(), env);

  assert.equal(calls.length, 2);
  for (const call of calls) {
    assert.notEqual(call.headers.get(ENGINE_CREDENTIAL_HEADER), "attacker-credential-" + "z".repeat(50));
    assert.notEqual(call.headers.get(ENGINE_CALLER_HEADER), "attacker-caller");
    const engineHeaders = [...call.headers.keys()].filter((k) => /engine|caller/i.test(k)).sort();
    assert.deepEqual(engineHeaders, [ENGINE_CALLER_HEADER, ENGINE_CREDENTIAL_HEADER]);
  }
});

test("N17. no credential plaintext in returned response (fallback accept + fail paths)", async () => {
  const ok = scriptedEnv(ENGINE_CALLER_SECRET_NEXT, [
    authFailure401(),
    new Response(JSON.stringify({ ok: true }), { status: 200 }),
  ]);
  const okResp = await handleIngress(validRequest(), ok.env);
  assertNoCredentialLeak(okResp, await okResp.text());

  const denied = scriptedEnv(ENGINE_CALLER_SECRET_NEXT, [
    authFailure401(),
    authFailure401("service_app_not_authorized"),
  ]);
  const deniedResp = await handleIngress(validRequest(), denied.env);
  assertNoCredentialLeak(deniedResp, await deniedResp.text());

  const thrown = scriptedEnv(ENGINE_CALLER_SECRET_NEXT, [new Error("timeout")]);
  const thrownResp = await handleIngress(validRequest(), thrown.env);
  assert.equal(thrownResp.status, 503);
  assertNoCredentialLeak(thrownResp, await thrownResp.text());
});

test("N18. oversized Engine 401-auth body stays fail-closed (502) with no fallback", async () => {
  const oversized = "u".repeat(1024 * 1024 + 8);
  const { calls, env } = scriptedEnv(ENGINE_CALLER_SECRET_NEXT, [
    new Response(oversized, { status: 401 }),
    new Response(JSON.stringify({ ok: true }), { status: 200 }),
  ]);
  const response = await handleIngress(validRequest(), env);

  assert.equal(response.status, 502);
  assert.deepEqual(JSON.parse(await response.text()).error.code, "engine_response_too_large");
  assert.equal(calls.length, 1);

  // Oversized response on the CURRENT fallback attempt also fails closed.
  const second = scriptedEnv(ENGINE_CALLER_SECRET_NEXT, [
    authFailure401(),
    new Response(oversized, { status: 200 }),
  ]);
  const response2 = await handleIngress(validRequest(), second.env);
  assert.equal(response2.status, 502);
  assert.equal(second.calls.length, 2);
});

test("N19. MAX_ENGINE_ATTEMPTS is 2 and never exceeded", async () => {
  assert.equal(MAX_ENGINE_ATTEMPTS, 2);

  for (const responses of [
    [authFailure401(), authFailure401(), new Response(JSON.stringify({ ok: true }), { status: 200 })],
    [authFailure401(), new Error("timeout after fallback")],
    [authFailure401(), authFailure401(), authFailure401(), authFailure401()],
  ]) {
    const { calls, env } = scriptedEnv(ENGINE_CALLER_SECRET_NEXT, responses);
    await handleIngress(validRequest(), env);
    assert.ok(calls.length <= MAX_ENGINE_ATTEMPTS, `attempt cap breached: ${calls.length}`);
    assert.equal(calls.length, 2);
  }

  // Timeout on the very first attempt stops all Engine work (no retry budget).
  const thrown = scriptedEnv(ENGINE_CALLER_SECRET_NEXT, [new Error("timeout"), authFailure401()]);
  const resp = await handleIngress(validRequest(), thrown.env);
  assert.equal(resp.status, 503);
  assert.equal(thrown.calls.length, 1);
});

test("N20. empty NEXT env behaves as absent (CURRENT only)", async () => {
  const { calls, env } = scriptedEnv("", [
    new Response(JSON.stringify({ ok: true }), { status: 200 }),
  ]);
  const response = await handleIngress(validRequest(), env);

  assert.equal(response.status, 200);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].headers.get(ENGINE_CREDENTIAL_HEADER), ENGINE_CALLER_SECRET);
});

test("N21. ingress source keeps dual-credential seam bounded and secret-clean", () => {
  const here = dirname(fileURLToPath(import.meta.url));
  const ingressSource = readFileSync(join(here, "..", "worker.mjs"), "utf8");

  assert.match(ingressSource, /PADIEM_ENGINE_CALLER_SECRET_NEXT/);
  assert.match(ingressSource, /MAX_ENGINE_ATTEMPTS\s*=\s*2/);
  // No generic retry machinery: no while/for retry loops in the seam.
  assert.doesNotMatch(ingressSource, /while\s*\(|for\s*\(\s*let\s+\w*attempt/i);
  // NEXT must remain an ingress-owner secret read (never caller-supplied).
  assert.doesNotMatch(ingressSource, /request\.headers\.get\(\s*["']x-padiem-engine-secret-next/i);
});
