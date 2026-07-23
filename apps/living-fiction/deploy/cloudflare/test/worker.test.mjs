/**
 * Runtime tests for the Living Fiction Cloudflare proxy worker.
 *
 * These run the REAL worker script inside Miniflare (the Workers runtime) and
 * drive its outbound fetch with a custom `outboundService`. The outbound
 * service records the exact request the worker sends upstream (method, path,
 * query, headers — including Host — and body) and returns a hand-built Response
 * whose headers (multiple Set-Cookie, Location, …) are under our control. This
 * exercises real runtime behaviour — header rewriting, proxy authentication,
 * CORS, cookie preservation, redirect rewriting, and fail-closed
 * misconfiguration — rather than asserting on source text.
 *
 * `compatibilityDate` is pinned to match wrangler.toml.example. This matters:
 * Headers.getSetCookie() (used by the worker to preserve every Set-Cookie) is
 * only available under a recent compatibility date, so the tests must run under
 * the same date as production to be faithful.
 *
 * The shared proxy secret is generated at runtime (CSPRNG); no secret literal is
 * committed. Run with: npm test   (node --test)
 */

import assert from "node:assert/strict";
import { webcrypto } from "node:crypto";
import path from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import { Miniflare } from "miniflare";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SCRIPT_PATH = path.join(__dirname, "..", "src", "index.js");

// Must match compatibility_date in wrangler.toml.example.
const COMPATIBILITY_DATE = "2025-01-01";

const UPSTREAM = "https://upstream.internal.example.com";
const UPSTREAM_HOST = new URL(UPSTREAM).host;
const WORKER_ORIGIN = "https://reader.example.com";

function genSecret() {
  const bytes = new Uint8Array(32);
  webcrypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

const SECRET = genSecret();

/**
 * Boot the worker in Miniflare with a controllable upstream.
 *
 * Options:
 *  - `secret`: value for UPSTREAM_PROXY_SECRET. Omit the key entirely to use the
 *    default strong SECRET; pass `{ secret: undefined }` to leave the binding
 *    unset (exercising the missing-secret, fail-closed path).
 *  - `upstream`: value for UPSTREAM_ORIGIN (defaults to UPSTREAM).
 *  - `upstreamResponse`: `{ status, body, headers }` the fake upstream returns;
 *    `headers` is an array of [name, value] tuples so multiple Set-Cookie
 *    headers survive. Defaults to a plain 200 "ok".
 *
 * Returns the Miniflare instance plus a `captured` object recording the last
 * request the worker sent upstream (method, path, headers, body).
 */
async function makeWorker(opts = {}) {
  const upstream = opts.upstream ?? UPSTREAM;
  const upstreamResponse = opts.upstreamResponse;
  const secret = "secret" in opts ? opts.secret : SECRET;

  const captured = {};
  const outboundService = async (req) => {
    captured.method = req.method;
    const u = new URL(req.url);
    captured.path = u.pathname + u.search;
    captured.headers = {};
    for (const [k, v] of req.headers.entries()) {
      captured.headers[k.toLowerCase()] = v;
    }
    captured.body = await req.text();
    if (upstreamResponse) {
      return new Response(upstreamResponse.body ?? "", {
        status: upstreamResponse.status ?? 200,
        headers: upstreamResponse.headers ?? [],
      });
    }
    return new Response("ok", {
      status: 200,
      headers: [["content-type", "text/plain"]],
    });
  };

  const bindings = { UPSTREAM_ORIGIN: upstream };
  if (secret !== undefined) {
    bindings.UPSTREAM_PROXY_SECRET = secret;
  }

  const mf = new Miniflare({
    scriptPath: SCRIPT_PATH,
    modules: true,
    compatibilityDate: COMPATIBILITY_DATE,
    outboundService,
    bindings,
  });
  return { mf, captured };
}

async function withWorker(opts, requestPath, init, fn) {
  const { mf, captured } = await makeWorker(opts);
  try {
    const response = await mf.dispatchFetch(`${WORKER_ORIGIN}${requestPath}`, init);
    await fn(response, captured);
  } finally {
    await mf.dispose();
  }
}

// ── Fail-closed misconfiguration ──────────────────────────────────────────

test("missing proxy secret fails closed with generic 500", async () => {
  await withWorker({ secret: undefined }, "/x", {}, async (res) => {
    assert.equal(res.status, 500);
    const body = await res.text();
    assert.equal(body, "proxy misconfigured");
    assert.ok(!body.includes(UPSTREAM));
    assert.ok(!body.includes(SECRET));
  });
});

test("weak proxy secret fails closed", async () => {
  await withWorker({ secret: "short" }, "/x", {}, async (res) => {
    assert.equal(res.status, 500);
  });
});

test("non-https upstream origin fails closed", async () => {
  await withWorker(
    { upstream: "http://upstream.internal.example.com" },
    "/x",
    {},
    async (res) => assert.equal(res.status, 500),
  );
});

test("upstream origin with a path fails closed", async () => {
  await withWorker(
    { upstream: "https://upstream.internal.example.com/app" },
    "/x",
    {},
    async (res) => assert.equal(res.status, 500),
  );
});

test("upstream origin with credentials fails closed", async () => {
  await withWorker(
    { upstream: "https://user:pass@upstream.internal.example.com" },
    "/x",
    {},
    async (res) => assert.equal(res.status, 500),
  );
});

test("upstream origin with query fails closed", async () => {
  await withWorker(
    { upstream: "https://upstream.internal.example.com/?x=1" },
    "/x",
    {},
    async (res) => assert.equal(res.status, 500),
  );
});

// ── Proxy authentication + forwarded headers ──────────────────────────────

test("worker authenticates to upstream and sets forwarded headers", async () => {
  await withWorker({}, "/feed?a=1", {}, async (res, captured) => {
    assert.equal(res.status, 200);
    assert.equal(captured.headers["x-lf-proxy-auth"], SECRET);
    assert.equal(captured.headers["x-forwarded-host"], "reader.example.com");
    assert.equal(captured.headers["x-forwarded-proto"], "https");
    assert.equal(captured.headers["host"], UPSTREAM_HOST);
  });
});

test("worker strips a client-spoofed proxy auth header", async () => {
  await withWorker(
    {},
    "/x",
    { headers: { "X-LF-Proxy-Auth": "forged-by-client" } },
    async (res, captured) => {
      assert.equal(captured.headers["x-lf-proxy-auth"], SECRET);
      assert.notEqual(captured.headers["x-lf-proxy-auth"], "forged-by-client");
    },
  );
});

test("worker overwrites client-spoofed forwarded host and proto", async () => {
  await withWorker(
    {},
    "/x",
    {
      headers: {
        "X-Forwarded-Host": "evil.example.com",
        "X-Forwarded-Proto": "http",
      },
    },
    async (res, captured) => {
      assert.equal(captured.headers["x-forwarded-host"], "reader.example.com");
      assert.equal(captured.headers["x-forwarded-proto"], "https");
    },
  );
});

// ── Request preservation ──────────────────────────────────────────────────

test("method, query, and body are preserved to the upstream", async () => {
  await withWorker(
    {},
    "/choice?slot=2",
    { method: "POST", body: "reader-choice-payload" },
    async (res, captured) => {
      assert.equal(captured.method, "POST");
      assert.ok(captured.path.includes("/choice"));
      assert.ok(captured.path.includes("slot=2"));
      assert.equal(captured.body, "reader-choice-payload");
    },
  );
});

// ── Response handling ─────────────────────────────────────────────────────

test("multiple Set-Cookie headers are preserved", async () => {
  await withWorker(
    {
      upstreamResponse: {
        status: 200,
        body: "ok",
        headers: [
          ["set-cookie", "session=abc; Path=/; HttpOnly"],
          ["set-cookie", "csrf=xyz; Path=/"],
        ],
      },
    },
    "/x",
    {},
    async (res) => {
      const cookies = res.headers.getSetCookie();
      assert.equal(cookies.length, 2);
      assert.ok(cookies.some((c) => c.startsWith("session=abc")));
      assert.ok(cookies.some((c) => c.startsWith("csrf=xyz")));
    },
  );
});

test("absolute upstream Location is rewritten to a relative reference", async () => {
  await withWorker(
    {
      upstreamResponse: {
        status: 303,
        body: "",
        headers: [
          ["location", "https://upstream.internal.example.com/reader/home?done=1"],
        ],
      },
    },
    "/x",
    { redirect: "manual" },
    async (res) => {
      assert.equal(res.headers.get("location"), "/reader/home?done=1");
    },
  );
});

test("non-upstream Location is left untouched", async () => {
  await withWorker(
    {
      upstreamResponse: {
        status: 302,
        body: "",
        headers: [["location", "https://other.example.com/elsewhere"]],
      },
    },
    "/x",
    { redirect: "manual" },
    async (res) => {
      assert.equal(res.headers.get("location"), "https://other.example.com/elsewhere");
    },
  );
});

test("responses are never cached", async () => {
  await withWorker({}, "/x", {}, async (res) => {
    assert.equal(res.headers.get("cache-control"), "no-store");
  });
});

// ── CORS preflight (full-origin comparison) ───────────────────────────────

test("same full-origin preflight is answered 204", async () => {
  await withWorker(
    {},
    "/x",
    { method: "OPTIONS", headers: { Origin: WORKER_ORIGIN } },
    async (res) => {
      assert.equal(res.status, 204);
      assert.equal(res.headers.get("access-control-allow-origin"), WORKER_ORIGIN);
    },
  );
});

test("different-origin preflight is not answered as same-origin", async () => {
  await withWorker(
    {},
    "/x",
    { method: "OPTIONS", headers: { Origin: "https://evil.example.com" } },
    async (res) => {
      // Not the 204 same-origin preflight; it is forwarded upstream (200 ok).
      assert.notEqual(res.status, 204);
      assert.equal(res.headers.get("access-control-allow-origin"), null);
    },
  );
});

test("scheme-mismatched origin preflight is rejected (full-origin, not host-only)", async () => {
  await withWorker(
    {},
    "/x",
    { method: "OPTIONS", headers: { Origin: "http://reader.example.com" } },
    async (res) => {
      // http origin must not satisfy the https worker origin.
      assert.notEqual(res.status, 204);
    },
  );
});

// ── Upstream failure: generic, no leak ────────────────────────────────────

test("upstream failure yields generic 502 with no URL or secret", async () => {
  // Point at a closed localhost port with NO outbound service, so workerd makes
  // a real (refused) connection and the worker's own catch path runs — exactly
  // as in production when the upstream is unreachable. (Miniflare's outbound
  // mocking converts a thrown outbound error into a 500 response, which would
  // bypass the worker's catch, so it is deliberately not used here.)
  const deadUpstream = "https://127.0.0.1:9";
  const mf = new Miniflare({
    scriptPath: SCRIPT_PATH,
    modules: true,
    compatibilityDate: COMPATIBILITY_DATE,
    bindings: { UPSTREAM_ORIGIN: deadUpstream, UPSTREAM_PROXY_SECRET: SECRET },
  });
  try {
    const res = await mf.dispatchFetch(`${WORKER_ORIGIN}/x`);
    assert.equal(res.status, 502);
    const body = await res.text();
    assert.equal(body, "upstream unavailable");
    assert.ok(!body.includes(deadUpstream));
    assert.ok(!body.includes(SECRET));
  } finally {
    await mf.dispose();
  }
});
