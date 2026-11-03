import test from "node:test";
import assert from "node:assert/strict";

import { createFront as realCreateFront } from "../worker.mjs";

const createFront = (options = {}) => realCreateFront({
  sign: async (request) => new Headers(request.headers),
  ...options,
});

const ORIGIN = "https://chat-com2.padiem.net";
const BASE = "https://chat.padiem.net";

const OAUTH_REQUESTS = [
  ["GET", "/.well-known/oauth-protected-resource"],
  ["GET", "/.well-known/oauth-protected-resource/api/mcp"],
  ["GET", "/.well-known/oauth-authorization-server"],
  ["GET", "/oauth/authorize?response_type=code&client_id=mcpc_x"],
  ["GET", "/oauth/authorize/info?response_type=code&client_id=mcpc_x"],
  ["POST", "/oauth/authorize"],
  ["POST", "/oauth/register"],
  ["POST", "/oauth/token"],
  ["POST", "/oauth/revoke"],
  ["OPTIONS", "/oauth/token"],
];

function baseEnv(overrides = {}) {
  return {
    FRONT_ORIGIN: ORIGIN,
    FALLBACK_MODE: "static",
    COM2_CANONICAL: "writes",
    HEALTH_TTL_MS: "10000",
    UPSTREAM_TIMEOUT_MS: "8000",
    API_READ_TIMEOUT_MS: "30000",
    ASSETS: {
      async fetch() {
        throw new Error("OAuth requests must not touch static assets");
      },
    },
    ...overrides,
  };
}

function recording(respond) {
  const calls = [];
  const impl = async (input) => {
    calls.push(input);
    return respond(input, calls.length);
  };
  impl.calls = calls;
  return impl;
}

function delayed(ms, response) {
  return (input) => new Promise((resolve, reject) => {
    const timer = setTimeout(() => resolve(response), ms);
    input.signal.addEventListener("abort", () => {
      clearTimeout(timer);
      reject(new Error("aborted"));
    });
  });
}

test("every MCP OAuth path reaches COM2 and bypasses the static cache", async () => {
  for (const [method, path] of OAUTH_REQUESTS) {
    const upstream = new Response(method === "OPTIONS" ? null : "ok", {
      status: method === "OPTIONS" ? 204 : 200,
      headers: { "cache-control": "no-store" },
    });
    const fetchImpl = recording(() => upstream);
    const handle = createFront({ fetchImpl });
    const request = new Request(BASE + path, {
      method,
      ...(method === "POST" ? { body: "a=1", headers: { "content-type": "application/x-www-form-urlencoded" } } : {}),
    });
    const response = await handle(request, baseEnv());
    assert.equal(response.status, upstream.status, `${method} ${path}`);
    assert.equal(response.headers.get("cache-control"), "no-store", `${method} ${path}`);
    assert.equal(fetchImpl.calls.length, 1, `${method} ${path} must reach COM2 once`);
    assert.equal(fetchImpl.calls[0].url, ORIGIN + path);
    assert.equal(fetchImpl.calls[0].method, method);
  }
});

test("OAuth POST body and the upstream response headers pass through", async () => {
  let seenBody = null;
  const upstream = new Response('{"access_token":"fixture"}', {
    status: 200,
    headers: { "content-type": "application/json", "cache-control": "no-store" },
  });
  const fetchImpl = async (input) => {
    seenBody = await input.text();
    return upstream;
  };
  const handle = createFront({ fetchImpl });
  const response = await handle(new Request(BASE + "/oauth/token", {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: "grant_type=authorization_code&code=fixture",
  }), baseEnv());
  assert.equal(response, upstream);
  assert.equal(seenBody, "grant_type=authorization_code&code=fixture");
  assert.equal(response.headers.get("cache-control"), "no-store");
});

test("OAuth 302 and Set-Cookie reach the browser unchanged", async () => {
  const headers = new Headers();
  headers.append("location", "/auth/shared/start");
  headers.append("set-cookie", "__Host-padiem-login-return=%2Foauth%2Fauthorize; Path=/; Secure; HttpOnly; SameSite=Lax");
  headers.set("cache-control", "no-store");
  const upstream = new Response(null, { status: 302, headers });
  const fetchImpl = recording(() => upstream);
  const handle = createFront({ fetchImpl });
  const response = await handle(new Request(
    BASE + "/oauth/authorize?response_type=code&client_id=mcpc_x",
  ), baseEnv());
  assert.equal(response, upstream);
  assert.equal(response.status, 302);
  assert.equal(response.headers.get("location"), "/auth/shared/start");
  assert.deepEqual(response.headers.getSetCookie(), [
    "__Host-padiem-login-return=%2Foauth%2Fauthorize; Path=/; Secure; HttpOnly; SameSite=Lax",
  ]);
  assert.equal(response.headers.get("cache-control"), "no-store");
});

test("OAuth OPTIONS preflight passes CORS headers through", async () => {
  const upstream = new Response(null, {
    status: 204,
    headers: {
      "access-control-allow-origin": "https://claude.ai",
      "access-control-allow-methods": "POST, OPTIONS",
      "access-control-allow-headers": "content-type",
      "cache-control": "no-store",
    },
  });
  const handle = createFront({ fetchImpl: recording(() => upstream) });
  const response = await handle(new Request(BASE + "/oauth/token", { method: "OPTIONS" }), baseEnv());
  assert.equal(response.status, 204);
  assert.equal(response.headers.get("access-control-allow-origin"), "https://claude.ai");
  assert.equal(response.headers.get("access-control-allow-methods"), "POST, OPTIONS");
  assert.equal(response.headers.get("cache-control"), "no-store");
});

test("OAuth uses the API read budget, not the generic 8s write/read deadline", async () => {
  const env = baseEnv({ API_READ_TIMEOUT_MS: "500", UPSTREAM_TIMEOUT_MS: "20" });
  const ok = new Response("ok", { headers: { "cache-control": "no-store" } });
  const handle = createFront({ fetchImpl: delayed(80, ok) });
  const getResponse = await handle(new Request(BASE + "/oauth/authorize"), env);
  assert.equal(getResponse.status, 200);
  const postHandle = createFront({ fetchImpl: delayed(80, ok) });
  const postResponse = await postHandle(new Request(BASE + "/oauth/token", {
    method: "POST", body: "a=1", headers: { "content-type": "application/x-www-form-urlencoded" },
  }), env);
  assert.equal(postResponse.status, 200);
});

test("other /.well-known paths are not broadened into the OAuth budget", async () => {
  const env = baseEnv({ API_READ_TIMEOUT_MS: "500", UPSTREAM_TIMEOUT_MS: "20" });
  const fetchImpl = recording(() => new Response("jwks"));
  const handle = createFront({ fetchImpl });
  const response = await handle(new Request(BASE + "/.well-known/jwks.json"), env);
  assert.equal(response.status, 200);
  assert.equal(fetchImpl.calls[0].url, ORIGIN + "/.well-known/jwks.json");
  // A slow non-OAuth well-known request keeps the generic deadline and times out.
  const slow = createFront({ fetchImpl: delayed(80, new Response("jwks")) });
  const timedOut = await slow(new Request(BASE + "/.well-known/jwks.json"), env);
  assert.equal(timedOut.status, 504);
});

test("the consent page's static assets stay on the front asset cache", async () => {
  const fetchImpl = recording(() => new Response("COM2 must not serve this asset"));
  const handle = createFront({ fetchImpl });
  const env = baseEnv({
    ASSETS: {
      async fetch() {
        return new Response("export default 1;", {
          headers: { "content-type": "text/javascript" },
        });
      },
    },
  });
  const response = await handle(new Request(BASE + "/mcp-oauth-consent.js"), env);
  assert.equal(response.headers.get("cache-control"), "private, max-age=300");
  assert.equal(fetchImpl.calls.length, 0);
});
