/**
 * 보안 응답 헤더 일괄 부착: the front door is the real public entry, so every
 * front answer — proxied upstream response, static asset, maintenance page and
 * front-generated error — carries the reviewed header set. The policy values
 * mirror apps/padiem-chat/app/worker_config.py (see worker.mjs); this file is
 * the front-response contract the security-headers workflow runs on.
 */
import test from "node:test";
import assert from "node:assert/strict";

import { createFront as realCreateFront } from "../worker.mjs";

const createFront = (options = {}) => realCreateFront({
  sign: async (request) => new Headers(request.headers),
  ...options,
});

// The report-only body policy: pinned to the reviewed Worker configuration so
// the front and the legacy entry cannot drift apart (the python contract test
// pins the same string back onto worker.mjs).
const CSP_REPORT_ONLY = (
  "default-src 'self'; " +
  "base-uri 'none'; " +
  "object-src 'none'; " +
  "frame-src blob:; " +
  "frame-ancestors 'none'; " +
  "script-src 'self'; " +
  "connect-src 'self' https://www.googleapis.com; " +
  "img-src 'self' data: blob:; " +
  "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com; " +
  "font-src 'self' data: https://cdn.jsdelivr.net https://fonts.gstatic.com; " +
  "form-action 'self'"
);

const FRAME_CSP = "frame-ancestors 'none'";
const PERMISSIONS_POLICY = "camera=(), microphone=(self), geolocation=()";

function assertSecurityHeaders(response) {
  assert.equal(response.headers.get("x-content-type-options"), "nosniff");
  assert.equal(response.headers.get("referrer-policy"), "strict-origin-when-cross-origin");
  assert.equal(response.headers.get("permissions-policy"), PERMISSIONS_POLICY);
  assert.equal(response.headers.get("x-frame-options"), "DENY");
  assert.equal(response.headers.get("content-security-policy"), FRAME_CSP);
  assert.equal(response.headers.get("content-security-policy-report-only"), CSP_REPORT_ONLY);
}

const ENV = { FRONT_ORIGIN: "https://host.example", FALLBACK_MODE: "static" };

function jsonUpstream(extraHeaders = {}) {
  return new Response('{"ok":true}', {
    status: 200,
    headers: { "content-type": "application/json", ...extraHeaders },
  });
}

test("a proxied read answer carries the whole security header set", async () => {
  const handle = createFront({ fetchImpl: async () => jsonUpstream() });
  const response = await handle(new Request("https://chat.example.test/api/auth/status"), ENV);
  assert.equal(response.status, 200);
  assertSecurityHeaders(response);
});

test("a proxied write answer carries the whole security header set", async () => {
  const handle = createFront({ fetchImpl: async () => jsonUpstream() });
  const response = await handle(
    new Request("https://chat.example.test/api/projects", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ name: "x" }),
    }),
    ENV,
  );
  assert.equal(response.status, 200);
  assertSecurityHeaders(response);
});

test("a static asset answer carries the whole security header set", async () => {
  const handle = createFront({ fetchImpl: async () => { throw new Error("static must not reach COM2"); } });
  const response = await handle(new Request("https://chat.example.test/static/app.js"), {
    ...ENV,
    ASSETS: {
      async fetch() {
        return new Response("export default 1;", {
          headers: { "content-type": "text/javascript" },
        });
      },
    },
  });
  assert.equal(response.status, 200);
  assertSecurityHeaders(response);
});

test("the maintenance page carries the header set too", async () => {
  // A connection-refused write on the static fallback mode ends in the
  // maintenance page: the front's own answer, not an upstream one.
  const refused = new Error("connect ECONNREFUSED 10.0.0.1:443");
  refused.code = "ECONNREFUSED";
  const handle = createFront({ fetchImpl: async () => { throw refused; } });
  const maintenance = await handle(
    new Request("https://chat.example.test/api/projects", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ name: "x" }),
    }),
    ENV,
  );
  assert.equal(maintenance.status, 503);
  assertSecurityHeaders(maintenance);
});

test("a transport failure error page carries the header set", async () => {
  const handle = createFront({ fetchImpl: async () => { throw new Error("com2 down"); } });
  const readFailure = await handle(new Request("https://chat.example.test/api/auth/status"), ENV);
  assert.equal(readFailure.status, 502);
  assertSecurityHeaders(readFailure);

  const navigation = await handle(
    new Request("https://chat.example.test/api/chat", {
      method: "POST",
      headers: { "content-type": "application/json", "accept": "text/html" },
      body: JSON.stringify({}),
    }),
    ENV,
  );
  assert.equal(navigation.status, 502);
  assertSecurityHeaders(navigation);
});

test("multiple upstream set-cookie headers survive the header attachment", async () => {
  // The proxy passes the upstream response through untouched to keep multiple
  // Set-Cookie values (logout clears six); the header wrapper must not merge
  // them.
  const upstream = jsonUpstream();
  upstream.headers.append("set-cookie", "padiem_session=one; Path=/");
  upstream.headers.append("set-cookie", "padiem_shared_refresh=two; Path=/auth/shared");
  upstream.headers.append("set-cookie", "third=three; Path=/");
  const handle = createFront({ fetchImpl: async () => upstream });
  const response = await handle(new Request("https://chat.example.test/api/auth/logout", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({}),
  }), ENV);
  assert.equal(response.headers.getSetCookie().length, 3);
  assertSecurityHeaders(response);
});

test("a websocket upgrade passes through untouched", async () => {
  // Rebuilding a 101 would break the protocol pairing: the raw upstream answer
  // goes back as-is, without the document header set. (Node's Response
  // constructor cannot build a 101, so the upgrade answer is a plain shape.)
  const upstream = {
    status: 101,
    statusText: "Switching Protocols",
    headers: new Headers({ upgrade: "websocket" }),
    body: null,
    webSocket: {},
  };
  const handle = createFront({ fetchImpl: async () => upstream });
  const response = await handle(new Request("https://chat.example.test/ws/voice", {
    headers: { upgrade: "websocket", connection: "upgrade" },
  }), ENV);
  assert.equal(response.status, 101);
  assert.equal(response, upstream);
});

test("an upstream-provided security header is replaced, never doubled", async () => {
  const upstream = jsonUpstream({
    "x-frame-options": "SAMEORIGIN",
    "content-security-policy": "default-src *",
  });
  const handle = createFront({ fetchImpl: async () => upstream });
  const response = await handle(new Request("https://chat.example.test/api/auth/status"), ENV);
  const values = [...response.headers.entries()].filter(([name]) => name === "x-frame-options");
  assert.equal(values.length, 1);
  assert.equal(values[0][1], "DENY");
  assert.equal(response.headers.get("content-security-policy"), FRAME_CSP);
});

test("an answer-stream wrapper keeps the header set", async () => {
  // The orchestration branch rebuilds the response for the timing wrapper; the
  // headers must survive that second reconstruction.
  const handle = createFront({ fetchImpl: async () => jsonUpstream() });
  const response = await handle(
    new Request("https://chat.example.test/api/orchestration", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ messages: [{ role: "user", content: "ping" }] }),
    }),
    { ...ENV, ORCHESTRATION_TIMEOUT_MS: "45000" },
  );
  assert.equal(response.status, 200);
  assertSecurityHeaders(response);
  assert.ok(response.headers.get("x-padiem-orchestration-ttfb-ms"));
});
