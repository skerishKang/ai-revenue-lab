import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { handleIngress } from "../worker.mjs";

const EXECUTE_URL = "https://ingress.example/internal/v1/execute";
const INGRESS_SECRET = "s".repeat(64);
const ENGINE_CALLER_ID = "storymemory-b61";
const ENGINE_CALLER_SECRET = "e".repeat(64);
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
