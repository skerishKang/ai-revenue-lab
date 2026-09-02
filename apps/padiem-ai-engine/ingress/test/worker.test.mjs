import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { handleIngress } from "../worker.mjs";

const EXECUTE_URL = "https://ingress.example/internal/v1/execute";

function validRequest(url = EXECUTE_URL) {
  return new Request(url, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-padiem-engine-caller": "storymemory-b61",
      "x-padiem-engine-credential": "x".repeat(64),
    },
    body: JSON.stringify({ app_id: "b61", messages: [{ role: "user", content: "hi" }] }),
  });
}

function fakeEnv(response = new Response(JSON.stringify({ ok: true }), { status: 200 })) {
  const calls = [];
  return {
    calls,
    env: {
      ENGINE: {
        async fetch(request) {
          calls.push(request);
          return response;
        },
      },
    },
  };
}

test("valid execution request forwards exactly once to the fixed Engine target", async () => {
  const { calls, env } = fakeEnv();
  const response = await handleIngress(validRequest(), env);

  assert.equal(response.status, 200);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, "https://padiem-ai-engine/internal/v1/execute");
  assert.equal(calls[0].method, "POST");
  assert.equal(calls[0].headers.get("x-padiem-engine-caller"), "storymemory-b61");
  assert.equal(calls[0].headers.get("x-padiem-engine-credential"), "x".repeat(64));
  assert.equal(calls[0].headers.get("content-type"), "application/json");
});

test("missing service credential fails closed before Engine", async () => {
  const { calls, env } = fakeEnv();
  const request = new Request(EXECUTE_URL, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-padiem-engine-caller": "storymemory-b61",
    },
    body: "{}",
  });

  const response = await handleIngress(request, env);
  assert.equal(response.status, 401);
  assert.equal(calls.length, 0);
});

test("browser-origin requests fail closed before Engine", async () => {
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

test("unsupported path and method are rejected before Engine", async () => {
  const first = fakeEnv();
  const missing = await handleIngress(validRequest("https://ingress.example/other"), first.env);
  assert.equal(missing.status, 404);
  assert.equal(first.calls.length, 0);

  const second = fakeEnv();
  const get = new Request(EXECUTE_URL, { method: "GET" });
  const method = await handleIngress(get, second.env);
  assert.equal(method.status, 405);
  assert.equal(second.calls.length, 0);
});

test("oversized body is rejected before Engine", async () => {
  const { calls, env } = fakeEnv();
  const request = new Request(EXECUTE_URL, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-padiem-engine-caller": "storymemory-b61",
      "x-padiem-engine-credential": "x".repeat(64),
    },
    body: "x".repeat(128 * 1024 + 1),
  });

  const response = await handleIngress(request, env);
  assert.equal(response.status, 413);
  assert.equal(calls.length, 0);
});

test("caller-supplied query target cannot change the fixed Engine destination", async () => {
  const { calls, env } = fakeEnv();
  const response = await handleIngress(
    validRequest(`${EXECUTE_URL}?target=https://evil.example&service=B14`),
    env,
  );

  assert.equal(response.status, 200);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, "https://padiem-ai-engine/internal/v1/execute");
});

test("Engine response headers are not reflected across the ingress", async () => {
  const upstream = new Response(JSON.stringify({ ok: false }), {
    status: 422,
    headers: {
      "content-type": "application/json",
      "x-private-engine-header": "do-not-reflect",
      "set-cookie": "private=1",
    },
  });
  const { env } = fakeEnv(upstream);
  const response = await handleIngress(validRequest(), env);

  assert.equal(response.status, 422);
  assert.equal(response.headers.get("x-private-engine-header"), null);
  assert.equal(response.headers.get("set-cookie"), null);
  assert.equal(response.headers.get("access-control-allow-origin"), null);
});

test("ingress config binds only to canonical Engine and leaves canonical Engine private", () => {
  const here = dirname(fileURLToPath(import.meta.url));
  const ingressConfig = readFileSync(join(here, "..", "wrangler.toml"), "utf8");
  const ingressSource = readFileSync(join(here, "..", "worker.mjs"), "utf8");
  const engineConfig = readFileSync(join(here, "..", "..", "wrangler.toml"), "utf8");

  assert.match(ingressConfig, /service\s*=\s*"padiem-ai-engine"/);
  assert.doesNotMatch(ingressConfig, /B14_SERVICE|ai-revenue-korean-ai-platform/i);
  assert.doesNotMatch(ingressSource, /StoryMemory|bible:web|B14_SERVICE|openrouter|poolside/i);
  assert.match(engineConfig, /name\s*=\s*"padiem-ai-engine"/);
  assert.match(engineConfig, /workers_dev\s*=\s*false/);
});
