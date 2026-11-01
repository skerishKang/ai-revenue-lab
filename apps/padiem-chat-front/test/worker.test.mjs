import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { createFront as realCreateFront, MAINTENANCE_HTML } from "../worker.mjs";

const createFront = (options = {}) => realCreateFront({
  ...options,
  sign: async (request) => new Headers(request.headers),
});

const HERE = dirname(fileURLToPath(import.meta.url));
const ORIGIN = "https://chat-com2.padiem.net";

function baseEnv(overrides = {}) {
  return {
    FRONT_ORIGIN: ORIGIN,
    FALLBACK_MODE: "static",
    COM2_CANONICAL: "off",
    HEALTH_TTL_MS: "10000",
    UPSTREAM_TIMEOUT_MS: "8000",
    ...overrides,
  };
}

function recordingFetch(respond) {
  const calls = [];
  const impl = async (input) => {
    calls.push(input);
    return respond(input, calls.length);
  };
  impl.calls = calls;
  return impl;
}

const reader = () => new Request("https://chat.padiem.net/api/conversations", {
  headers: { cookie: "padiem_session=abc", "cf-connecting-ip": "203.0.113.9" },
});

test("normal GET proxies to the tunnel origin with the exact response object", async () => {
  const upstream = new Response("{\"conversations\":[]}", {
    status: 200,
    headers: { "content-type": "application/json" },
  });
  const fetchImpl = recordingFetch(() => upstream);
  const handle = createFront({ fetchImpl });
  const response = await handle(reader(), baseEnv());

  assert.equal(response, upstream); // untouched body/status/headers object
  assert.equal(fetchImpl.calls.length, 1);
  const forwarded = fetchImpl.calls[0];
  assert.equal(forwarded.url, `${ORIGIN}/api/conversations`);
  assert.equal(forwarded.method, "GET");
  assert.equal(forwarded.headers.get("cookie"), "padiem_session=abc");
  assert.equal(forwarded.headers.get("x-forwarded-host"), "chat.padiem.net");
  assert.equal(forwarded.headers.get("x-forwarded-proto"), "https");
  assert.equal(forwarded.headers.get("x-forwarded-for"), "203.0.113.9");
  assert.equal(forwarded.headers.get("host"), null);
});

test("multiple Set-Cookie headers survive the proxy unchanged", async () => {
  const headers = new Headers();
  headers.append("set-cookie", "a=1; Path=/; HttpOnly");
  headers.append("set-cookie", "b=2; Path=/");
  const upstream = new Response("ok", { status: 200, headers });
  const handle = createFront({ fetchImpl: recordingFetch(() => upstream) });
  const response = await handle(reader(), baseEnv());
  assert.deepEqual(response.headers.getSetCookie(), [
    "a=1; Path=/; HttpOnly",
    "b=2; Path=/",
  ]);
});

test("SSE POST streams through without buffering", async () => {
  const encoder = new TextEncoder();
  const upstream = new Response(new ReadableStream({
    start(controller) {
      controller.enqueue(encoder.encode("event: delta\ndata: {\"d\":1}\n\n"));
      controller.enqueue(encoder.encode("event: done\ndata: {\"done\":true}\n\n"));
      controller.close();
    },
  }), { status: 200, headers: { "content-type": "text/event-stream" } });
  const fetchImpl = recordingFetch(() => upstream);
  const handle = createFront({ fetchImpl });
  const request = new Request("https://chat.padiem.net/api/chat/stream", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ messages: [{ role: "user", content: "hi" }] }),
  });

  const response = await handle(request, baseEnv());
  assert.equal(response.status, 200);
  assert.equal(response.headers.get("content-type"), "text/event-stream");
  const text = await response.text();
  assert.match(text, /event: delta/);
  assert.match(text, /event: done/);
  assert.equal(fetchImpl.calls.length, 1);
  assert.equal(await fetchImpl.calls[0].text(), JSON.stringify({ messages: [{ role: "user", content: "hi" }] }));
});

test("a redirect reaches the browser instead of being followed", async () => {
  const upstream = new Response(null, {
    status: 302,
    headers: { location: "https://accounts.google.com/o/oauth2/auth" },
  });
  const handle = createFront({ fetchImpl: recordingFetch(() => upstream) });
  const response = await handle(
    new Request("https://chat.padiem.net/auth/google/start"), baseEnv(),
  );
  assert.equal(response.status, 302);
  assert.equal(response.headers.get("location"), "https://accounts.google.com/o/oauth2/auth");
});

test("a WebSocket upgrade response is passed through as-is", async () => {
  const marker = { status: 101, webSocket: { accept() {} }, headers: new Headers() };
  const fetchImpl = recordingFetch(() => marker);
  const handle = createFront({ fetchImpl });
  const request = new Request("https://chat.padiem.net/api/connector/ws", {
    headers: { upgrade: "websocket", connection: "Upgrade", "sec-websocket-key": "abc" },
  });
  const response = await handle(request, baseEnv());
  assert.equal(response, marker);
  const forwarded = fetchImpl.calls[0];
  assert.equal(forwarded.headers.get("upgrade"), "websocket");
  assert.equal(forwarded.headers.get("sec-websocket-key"), "abc");
});

test("com2 down: reads fall back to the Python Worker in service mode", async () => {
  const fallbackResponse = new Response("python", { status: 200 });
  const chatWorker = { calls: 0, async fetch(request) { this.calls += 1; return fallbackResponse; } };
  const fetchImpl = recordingFetch(() => { throw new Error("connect failed"); });
  const handle = createFront({ fetchImpl });
  const response = await handle(reader(), baseEnv({ FALLBACK_MODE: "service", CHAT_WORKER: chatWorker }));
  assert.equal(response, fallbackResponse);
  assert.equal(chatWorker.calls, 1);
});

test("com2 down: reads get the maintenance page in static mode", async () => {
  const fetchImpl = recordingFetch(() => { throw new Error("connect failed"); });
  const handle = createFront({ fetchImpl });
  const response = await handle(reader(), baseEnv({ FALLBACK_MODE: "static" }));
  assert.equal(response.status, 503);
  assert.equal(response.headers.get("retry-after"), "120");
  assert.equal(await response.text(), MAINTENANCE_HTML);
});

test("repeated API 503 responses pass through without poisoning other reads", async () => {
  const fetchImpl = recordingFetch((request) => {
    const path = new URL(request.url).pathname;
    return path === "/api/pc/pairings" || path === "/api/chat/custom/credential"
      ? new Response('{"error":"component unavailable"}', { status: 503, headers: { "content-type": "application/json" } })
      : new Response('{"authenticated":true}', { status: 200 });
  });
  const handle = createFront({ fetchImpl });
  for (const path of ["/api/pc/pairings", "/api/chat/custom/credential", "/api/pc/pairings"]) {
    const response = await handle(new Request("https://chat.padiem.net" + path), baseEnv());
    assert.equal(response.status, 503);
    assert.equal(await response.text(), '{"error":"component unavailable"}');
    assert.equal(response.headers.get("x-padiem-front"), null);
  }
  const auth = await handle(new Request("https://chat.padiem.net/api/auth/status"), baseEnv());
  assert.equal(auth.status, 200);
  assert.equal(await auth.text(), '{"authenticated":true}');
  assert.equal(fetchImpl.calls.length, 4);
});

test("a local signing failure fails closed without poisoning origin health", async () => {
  let signingFailures = 1;
  let calls = 0;
  const handle = realCreateFront({
    sign: async (request) => {
      if (signingFailures-- > 0) throw new Error("missing signing configuration");
      return new Headers(request.headers);
    },
    fetchImpl: async () => { calls += 1; return new Response("ok"); },
  });
  assert.equal((await handle(reader(), baseEnv())).status, 503);
  assert.equal(calls, 0);
  assert.equal((await handle(reader(), baseEnv())).status, 200);
  assert.equal(calls, 1);
});

test("failed /health probe opens the short cache and later retries", async () => {
  let now = 1_000;
  let healthStatus = 503;
  const fetchImpl = recordingFetch((request) =>
    new URL(request.url).pathname === "/health"
      ? new Response("health", { status: healthStatus })
      : new Response("auth", { status: 200 })
  );
  const handle = createFront({ fetchImpl, now: () => now });
  const env = baseEnv({ HEALTH_TTL_MS: "10000" });
  const health = () => new Request("https://chat.padiem.net/health");

  assert.equal((await handle(health(), env)).headers.get("x-padiem-front"), "read_fallback_static");
  now += 5_000;
  assert.equal((await handle(reader(), env)).headers.get("x-padiem-front"), "read_fallback_static");
  assert.equal(fetchImpl.calls.length, 1);
  now += 10_000;
  healthStatus = 200;
  assert.equal((await handle(health(), env)).status, 200);
  assert.equal((await handle(reader(), env)).status, 200);
  assert.equal(fetchImpl.calls.length, 3);
});

test("writes before canonical may fall back; after canonical they never reach Python", async () => {
  const writeRequest = () => new Request("https://chat.padiem.net/api/chat/stream", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: "{}",
  });
  const chatWorker = { calls: 0, async fetch() { this.calls += 1; return new Response("python"); } };
  const downFetch = () => { throw new Error("connect failed"); };

  const preCanonical = createFront({ fetchImpl: recordingFetch(downFetch) });
  const pre = await preCanonical(writeRequest(), baseEnv({
    FALLBACK_MODE: "service", COM2_CANONICAL: "off", CHAT_WORKER: chatWorker,
  }));
  assert.equal(pre.status, 200);
  assert.equal(chatWorker.calls, 1);

  const postCanonical = createFront({ fetchImpl: recordingFetch(downFetch) });
  const post = await postCanonical(writeRequest(), baseEnv({
    FALLBACK_MODE: "service", COM2_CANONICAL: "writes", CHAT_WORKER: chatWorker,
  }));
  assert.equal(post.status, 503);
  assert.equal(post.headers.get("x-padiem-front"), "write_com2_canonical_refused");
  assert.equal(chatWorker.calls, 1, "a canonical write must never fall back to the Python Worker");
});

test("a canonical write returns the upstream 5xx unchanged", async () => {
  const upstream = new Response('{"error":"unavailable"}', { status: 500 });
  const chatWorker = { calls: 0, async fetch() { this.calls += 1; return new Response("python"); } };
  const handle = createFront({ fetchImpl: recordingFetch(() => upstream) });
  const response = await handle(new Request("https://chat.padiem.net/api/chat/stream", {
    method: "POST", body: "{}",
  }), baseEnv({ COM2_CANONICAL: "writes", FALLBACK_MODE: "service", CHAT_WORKER: chatWorker }));
  assert.equal(response, upstream);
  assert.equal(await response.text(), '{"error":"unavailable"}');
  assert.equal(chatWorker.calls, 0);
});

test("the worker stays inside a proxy-only CPU shape", () => {
  const source = readFileSync(join(HERE, "..", "worker.mjs"), "utf8");
  for (const forbidden of [".text()", ".json(", ".arrayBuffer(", "crypto.", "atob(", "btoa(", "TextDecoder", "TextEncoder"]) {
    assert.equal(source.includes(forbidden), false, `proxy must not use ${forbidden}`);
  }
  // One upstream fetch call site; the service fallback has its own binding call.
  assert.equal((source.match(/await fetchImpl\(/g) || []).length, 1);
  assert.equal((source.match(/await env\.CHAT_WORKER\.fetch\(/g) || []).length, 1);
});

test("static assets stay on Cloudflare and dynamic requests use real signing", async () => {
  const cryptoModule = await import("node:crypto");
  if (!globalThis.crypto) globalThis.crypto = cryptoModule.webcrypto;
  const fetchImpl = recordingFetch(() => new Response("dynamic"));
  const handle = realCreateFront({ fetchImpl });
  const env = baseEnv({
    PADIEM_COM2_EDGE_SECRET: "synthetic-only-secret-0123456789",
    ASSETS: { fetch: async () => new Response("asset") },
  });
  assert.equal(await (await handle(new Request("https://chat.padiem.net/app.js"), env)).text(), "asset");
  assert.equal(fetchImpl.calls.length, 0);
  const api = new Request("https://chat.padiem.net/api/status", { headers: { "x-padiem-edge-proof": "forged" } });
  api.cf = { tlsVersion: "TLSv1.3" };
  assert.equal((await handle(api, env)).status, 200);
  assert.match(fetchImpl.calls[0].headers.get("x-padiem-edge-proof"), /^v1=[0-9a-f]{64}$/);
  assert.notEqual(fetchImpl.calls[0].headers.get("x-padiem-edge-proof"), "forged");
});

test("front vars match the verified non-secret production contract", () => {
  // Snapshot of production version b45fb8f5-7cad-4c0c-9a3b-ef5ae55e18cf,
  // verified 2026-11-01. Secrets are deliberately excluded.
  const expected = {
    FRONT_ORIGIN: "https://chat-com2.padiem.net",
    FALLBACK_MODE: "static",
    COM2_CANONICAL: "writes",
    HEALTH_TTL_MS: "10000",
    UPSTREAM_TIMEOUT_MS: "8000",
    API_READ_TIMEOUT_MS: "30000",
  };
  const config = readFileSync(join(HERE, "..", "wrangler.toml"), "utf8");
  const sections = config.split(/^\[vars\]\s*$/m);
  assert.equal(sections.length, 2, "wrangler.toml must declare exactly one [vars]");
  const varsText = sections[1].split(/^\[/m)[0];
  const configured = {};
  for (const line of varsText.split(/\r?\n/)) {
    if (!line.trim() || line.trimStart().startsWith("#")) continue;
    const match = line.match(/^\s*([A-Z_][A-Z0-9_]*)\s*=\s*("(?:[^"\\]|\\.)*")\s*(?:#.*)?$/);
    assert.ok(match, "invalid or unsupported [vars] line: " + line);
    assert.equal(Object.hasOwn(configured, match[1]), false, "duplicate variable " + match[1]);
    configured[match[1]] = JSON.parse(match[2]);
  }
  assert.deepEqual(configured, expected);
  // Supply the current non-secret live vars as JSON for an actual live comparison.
  if (process.env.PADIEM_FRONT_LIVE_VARS_JSON) {
    assert.deepEqual(configured, JSON.parse(process.env.PADIEM_FRONT_LIVE_VARS_JSON));
  }
});
