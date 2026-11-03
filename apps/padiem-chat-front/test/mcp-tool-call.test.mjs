/**
 * A PC tool call is answered when the PC answers, not at the write deadline.
 *
 * POST /api/mcp holds the request while the user's own PC runs the command:
 * pc_shell waits inside the caller's window (120s default) and hands a longer
 * command back as a job. Under the plain 8s write deadline the front answered
 * 504 for a command that was running normally, and an external connector that
 * retries on 504 would run it a second time. Only this path gets the long
 * allowance; every other write keeps the short one.
 *
 * The same file answers the always-connected channel question: the connector
 * gateway WebSocket must reach COM2 as an upgrade, because an attached PC is the
 * one PC that can answer a tool call immediately.
 */
import test from "node:test";
import assert from "node:assert/strict";

import { createFront } from "../worker.mjs";

const ORIGIN = "https://chat-com2.padiem.net";
const BASE = "https://chat.padiem.net";
const GATEWAY = "/api/claw/connector/gateway/session";
const sign = async (request) => new Headers(request.headers);

const env = (overrides = {}) => ({
  FRONT_ORIGIN: ORIGIN,
  FALLBACK_MODE: "static",
  COM2_CANONICAL: "writes",
  HEALTH_TTL_MS: "10000",
  UPSTREAM_TIMEOUT_MS: "10",
  ...overrides,
});

function delayed(ms, build) {
  return async (input) => new Promise((resolve, reject) => {
    const timer = setTimeout(() => resolve(build()), ms);
    input.signal.addEventListener("abort", () => {
      clearTimeout(timer);
      reject(new DOMException("aborted", "AbortError"));
    }, { once: true });
  });
}

const mcpRequest = (body = '{"jsonrpc":"2.0","method":"tools/call","id":"1"}') => new Request(
  BASE + "/api/mcp",
  { method: "POST", headers: { "content-type": "application/json", authorization: "Bearer fixture" }, body },
);

test("a slow PC tool call on /api/mcp is not cut at the write deadline", async () => {
  const handle = createFront({ sign, fetchImpl: delayed(60, () =>
    new Response('{"jsonrpc":"2.0","result":{"status":"completed"}}', {
      status: 200, headers: { "content-type": "application/json", "cache-control": "no-store" },
    })) });
  const response = await handle(mcpRequest(), env());
  assert.equal(response.status, 200);
  assert.equal(response.headers.get("cache-control"), "no-store");
});

test("MCP_TIMEOUT_MS overrides the allowance and answers an honest timeout", async () => {
  const slow = delayed(60, () => new Response("{}", { status: 200 }));
  const handle = createFront({ sign, fetchImpl: slow });
  const response = await handle(mcpRequest(), env({ MCP_TIMEOUT_MS: "10" }));
  assert.equal(response.status, 504);
  assert.equal((await response.json()).error.code, "upstream_timeout");
});

test("the default allowance is one hundred and eighty seconds", async () => {
  const source = await import("node:fs/promises").then((fs) =>
    fs.readFile(new URL("../worker.mjs", import.meta.url), "utf8"));
  assert.match(source, /const DEFAULT_MCP_TIMEOUT_MS = 180000;/);
  // No new production variable: the allowance ships as a code default, like TUS.
  const { readFileSync } = await import("node:fs");
  const toml = readFileSync(new URL("../wrangler.toml", import.meta.url), "utf8");
  assert.equal(/MCP_TIMEOUT_MS/.test(toml), false);
});

test("every other write keeps the short write deadline", async () => {
  const handle = createFront({ sign, fetchImpl: delayed(60, () => new Response("{}", { status: 200 })) });
  for (const path of ["/api/conversations", "/api/projects/p1/files/tus/other", "/api/bookai/records"]) {
    const response = await handle(new Request(BASE + path, { method: "POST", body: "{}" }),
      env({ TUS_UPLOAD_TIMEOUT_MS: "10", APPS_AI_TIMEOUT_MS: "10", AUTH_CALLBACK_TIMEOUT_MS: "10" }));
    assert.equal(response.status, 504, path);
  }
});

test("the MCP call reaches the COM2 origin with its body untouched", async () => {
  const seen = [];
  const handle = createFront({ sign, fetchImpl: async (input) => {
    seen.push({ url: input.url, method: input.method, body: await input.text(),
                 authorization: input.headers.get("authorization") });
    return new Response("{}", { status: 200 });
  } });
  const body = '{"jsonrpc":"2.0","method":"tools/call","params":{"name":"pc_shell_start"}}';
  await handle(mcpRequest(body), env());
  assert.equal(seen.length, 1);
  assert.equal(seen[0].url, ORIGIN + "/api/mcp");
  assert.equal(seen[0].method, "POST");
  assert.equal(seen[0].body, body);
  assert.equal(seen[0].authorization, "Bearer fixture");
});

test("the connector gateway upgrade reaches COM2 and the 101 is handed back as-is", async () => {
  // A 101 cannot be reconstructed as a Response; the front must return the very
  // object fetch produced, or the always-connected PC never gets its socket.
  const marker = { status: 101, statusText: "Switching Protocols", webSocket: { accept() {} },
                   headers: new Headers({ "sec-websocket-accept": "synthetic" }) };
  const seen = [];
  const assets = { calls: 0, fetch() { assets.calls += 1; return new Response("static", { status: 200 }); } };
  const handle = createFront({ sign, fetchImpl: async (input) => {
    seen.push({ url: input.url, upgrade: input.headers.get("upgrade"),
                key: input.headers.get("sec-websocket-key") });
    return marker;
  } });
  const request = new Request(BASE + GATEWAY, {
    headers: { upgrade: "websocket", connection: "Upgrade", "sec-websocket-key": "abc",
               "x-padiem-edge-proof": "forged" },
  });
  const response = await handle(request, env({ ASSETS: assets }));
  assert.equal(response, marker);
  assert.equal(seen.length, 1);
  assert.equal(seen[0].url, ORIGIN + GATEWAY);
  assert.equal(seen[0].upgrade, "websocket");
  assert.equal(seen[0].key, "abc");
  assert.equal(assets.calls, 0, "a socket upgrade is never a static asset");
});

test("a gateway read without an upgrade still reaches COM2, not the static branch", async () => {
  const seen = [];
  const assets = { calls: 0, fetch() { assets.calls += 1; return new Response("static", { status: 200 }); } };
  const handle = createFront({ sign, fetchImpl: async (input) => {
    seen.push(input.url);
    return new Response('{"ok":true}', { status: 200 });
  } });
  const response = await handle(new Request(BASE + GATEWAY), env({ ASSETS: assets }));
  assert.equal(response.status, 200);
  assert.deepEqual(seen, [ORIGIN + GATEWAY]);
  assert.equal(assets.calls, 0);
});
