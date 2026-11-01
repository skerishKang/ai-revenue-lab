/**
 * The common-login callback used to be cut by the plain read deadline.
 *
 * COM2 answers /auth/shared/callback only after an OAuth exchange against
 * auth.padiem.net, a JWKS-verified access token and an identity RPC. Measured on the
 * host: 14.3 seconds, while the front gave a non-API read 8 — the browser saw
 * upstream_timeout and the login half-finished. Only this path gets the longer
 * header wait; every other /auth/* and the API reads keep their own deadlines.
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
      return new Response("login complete", { status: 302 });
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

const callback = () => new Request(
  "https://chat.padiem.net/auth/shared/callback?state=synthetic&code=synthetic");

test("the shared-login callback is not cut at the read deadline", async () => {
  const response = await front(60)(callback(), env());
  assert.equal(response.status, 302);
});

test("its allowance is configurable and reports an honest timeout when used up", async () => {
  const response = await front(60)(callback(), env({ AUTH_CALLBACK_TIMEOUT_MS: "10" }));
  assert.equal(response.status, 504);
  assert.equal((await response.json()).error.code, "upstream_timeout");
});

test("the default allowance is thirty seconds", async () => {
  const source = await import("node:fs/promises").then((fs) =>
    fs.readFile(new URL("../worker.mjs", import.meta.url), "utf8"));
  assert.match(source, /DEFAULT_AUTH_CALLBACK_TIMEOUT_MS = 30000/);
});

test("every other /auth path keeps the short deadline", async () => {
  const handle = front(60);
  for (const path of ["/auth/shared/start", "/auth/shared/logout", "/auth/google/start"]) {
    const response = await handle(new Request("https://chat.padiem.net" + path), env());
    assert.notEqual(response.status, 302, path);
    assert.equal(response.status, 504, path);
  }
});

test("an API read still uses the API allowance, not the callback one", async () => {
  const response = await front(60)(
    new Request("https://chat.padiem.net/api/conversations"),
    env({ API_READ_TIMEOUT_MS: "10" }),
  );
  assert.equal(response.status, 504);
});
