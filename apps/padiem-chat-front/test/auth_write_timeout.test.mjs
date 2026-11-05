/**
 * The login write (/api/auth/*) used to ride the generic write window.
 *
 * The host answers a login only after an OAuth exchange, a JWKS-verified token
 * and the canonical identity RPC (resolve_or_create_product_link). Measured on
 * the host: 52 events over 3 days where that RPC alone ran past the 5s live
 * window and the front answered a cookie-less 504 while the session was created
 * right after it — the user saw a failed login for a session that existed. #6957
 * lightened the RPC; until its effect is measured, the login write gets its own
 * allowance. Every other write keeps the generic window.
 */
import test from "node:test";
import assert from "node:assert/strict";

import { createFront } from "../worker.mjs";

const ORIGIN = "https://chat-com2.padiem.net";
const sign = async (request) => new Headers(request.headers);

function front(ms) {
  return createFront({
    sign,
    fetchImpl: async (input) => {
      await new Promise((resolve) => setTimeout(resolve, ms));
      if (input.signal && input.signal.aborted) {
        throw new DOMException("aborted", "AbortError");
      }
      return new Response("session ready", {
        status: 200,
        headers: { "set-cookie": "padiem_session=synthetic; Path=/" },
      });
    },
  });
}

const env = (overrides = {}) => ({
  FRONT_ORIGIN: ORIGIN,
  FALLBACK_MODE: "static",
  COM2_CANONICAL: "off",
  HEALTH_TTL_MS: "10000",
  UPSTREAM_TIMEOUT_MS: "10",
  ...overrides,
});

const login = () => new Request("https://chat.padiem.net/api/auth/login", {
  method: "POST",
  headers: { "content-type": "application/json" },
  body: JSON.stringify({ synthetic: true }),
});

test("the login write is not cut by the generic write window", async () => {
  // 60ms of host work against a 10ms generic window: the old shape answered 504.
  const response = await front(60)(login(), env());
  assert.equal(response.status, 200);
  assert.ok((response.headers.get("set-cookie") || "").includes("padiem_session"));
});

test("its allowance is configurable and reports an honest timeout when used up", async () => {
  const response = await front(60)(login(), env({ AUTH_WRITE_TIMEOUT_MS: "10" }));
  assert.equal(response.status, 504);
  assert.equal((await response.json()).error.code, "upstream_timeout");
});

test("the default allowance is thirty seconds", async () => {
  const source = await import("node:fs/promises").then((fs) =>
    fs.readFile(new URL("../worker.mjs", import.meta.url), "utf8"));
  assert.match(source, /DEFAULT_AUTH_WRITE_TIMEOUT_MS = 30000/);
});

test("wrangler.toml declares the same contract", async () => {
  const toml = await import("node:fs/promises").then((fs) =>
    fs.readFile(new URL("../wrangler.toml", import.meta.url), "utf8"));
  assert.match(toml, /AUTH_WRITE_TIMEOUT_MS = "30000"/);
});

test("every other write keeps the generic window", async () => {
  const handle = front(60);
  for (const path of ["/api/projects/1/notes", "/api/account/settings"]) {
    const response = await handle(new Request("https://chat.padiem.net" + path, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ synthetic: true }),
    }), env());
    assert.equal(response.status, 504, path);
  }
});

test("an auth read still uses the API read allowance, not the write one", async () => {
  const response = await front(60)(
    new Request("https://chat.padiem.net/api/auth/status"),
    env({ API_READ_TIMEOUT_MS: "10" }),
  );
  assert.equal(response.status, 504);
});
