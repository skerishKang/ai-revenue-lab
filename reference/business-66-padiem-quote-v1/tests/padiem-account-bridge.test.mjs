import assert from "node:assert/strict";
import worker from "../_worker.js";

const originalFetch = globalThis.fetch;
const calls = [];

function json(payload, init = {}) {
  const headers = new Headers(init.headers || {});
  headers.set("Content-Type", "application/json");
  return new Response(JSON.stringify(payload), { ...init, headers });
}

globalThis.fetch = async (target, init = {}) => {
  const url = String(target);
  const headers = init.headers instanceof Headers ? init.headers : new Headers(init.headers || {});
  calls.push({ url, init, headers });

  if (url.endsWith("/api/auth/password/login")) {
    return json(
      { ok: true, user: { id: "usr_test" } },
      {
        status: 200,
        headers: {
          "Set-Cookie": "padiem_session=opaque-test-token; Path=/; HttpOnly; Secure; SameSite=Lax"
        }
      }
    );
  }
  if (url.endsWith("/api/auth/status")) {
    return json({
      authenticated: true,
      session_state: "signed_in",
      user: { id: "usr_test", name: "Test User" }
    });
  }
  if (url.endsWith("/api/b66/saved-skills?limit=20")) {
    return json({ ok: true, skills: [] });
  }
  if (url.endsWith("/api/auth/google/start")) {
    return new Response(null, {
      status: 302,
      headers: { "Location": "https://accounts.google.com/o/oauth2/auth?provider=google" }
    });
  }
  if (url.endsWith("/api/auth/google/callback")) {
    return new Response(null, { status: 302, headers: { "Location": "/" } });
  }
  throw new Error("unexpected upstream: " + url);
};

try {
  const assets = { fetch() { throw new Error("assets must not receive bridge routes"); } };
  const env = { ASSETS: assets };

  const login = await worker.fetch(
    new Request("https://quick-quote-kr.pages.dev/api/padiem/auth/password/login", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": "Bearer browser-forged"
      },
      body: JSON.stringify({ identifier: "demo@example.test", password: "not-a-real-secret" })
    }),
    env
  );
  assert.equal(login.status, 200);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, "https://chat.padiem.net/api/auth/password/login");
  assert.equal(calls[0].headers.get("authorization"), null);
  assert.equal(calls[0].headers.get("cookie"), null);
  assert.match(login.headers.get("set-cookie") || "", /^padiem_session=/);
  assert.match(login.headers.get("set-cookie") || "", /HttpOnly/i);
  assert.match(login.headers.get("set-cookie") || "", /Secure/i);

  const status = await worker.fetch(
    new Request("https://quick-quote-kr.pages.dev/api/padiem/auth/status", {
      headers: {
        "Cookie": "padiem_session=opaque-test-token",
        "Authorization": "Bearer browser-forged"
      }
    }),
    env
  );
  assert.equal(status.status, 200);
  assert.equal(calls.length, 2);
  assert.equal(calls[1].url, "https://chat.padiem.net/api/auth/status");
  assert.equal(calls[1].headers.get("cookie"), "padiem_session=opaque-test-token");
  assert.equal(calls[1].headers.get("authorization"), null);

  const list = await worker.fetch(
    new Request("https://quick-quote-kr.pages.dev/api/padiem/b66/saved-skills?limit=20", {
      headers: { "Cookie": "padiem_session=opaque-test-token" }
    }),
    env
  );
  assert.equal(list.status, 200);
  assert.equal(calls.length, 3);
  assert.equal(calls[2].url, "https://chat.padiem.net/api/b66/saved-skills?limit=20");

  const countBeforeDeny = calls.length;
  for (const request of [
    new Request("https://quick-quote-kr.pages.dev/api/padiem/admin/anything"),
    new Request("https://quick-quote-kr.pages.dev/api/padiem/b66/saved-skills/not-an-id"),
    new Request("https://quick-quote-kr.pages.dev/api/padiem/auth/status", { method: "POST" })
  ]) {
    const denied = await worker.fetch(request, env);
    assert.equal(denied.status, 404);
  }
  assert.equal(calls.length, countBeforeDeny);

  const googleStart = await worker.fetch(
    new Request("https://quick-quote-kr.pages.dev/api/padiem/auth/google/start"),
    env
  );
  assert.equal(googleStart.status, 302);
  assert.equal(googleStart.headers.get("location"), "https://accounts.google.com/o/oauth2/auth?provider=google");

  const googleCallback = await worker.fetch(
    new Request("https://quick-quote-kr.pages.dev/api/padiem/auth/google/callback?code=x&state=y"),
    env
  );
  assert.equal(googleCallback.status, 302);
  assert.equal(googleCallback.headers.get("location"), "/");

  let serviceCalls = 0;
  const serviceEnv = {
    ASSETS: assets,
    PADIEM_CHAT_SERVICE: {
      async fetch(request) {
        serviceCalls += 1;
        assert.equal(request.url, "https://chat.padiem.net/api/auth/status");
        assert.equal(request.headers.get("cookie"), "padiem_session=service-token");
        return json({
          authenticated: true,
          session_state: "signed_in",
          user: { id: "usr_service" }
        });
      }
    }
  };
  const networkCallsBeforeService = calls.length;
  const viaService = await worker.fetch(
    new Request("https://quick-quote-kr.pages.dev/api/padiem/auth/status", {
      headers: { "Cookie": "padiem_session=service-token" }
    }),
    serviceEnv
  );
  assert.equal(viaService.status, 200);
  assert.equal(serviceCalls, 1);
  assert.equal(calls.length, networkCallsBeforeService);

  const oversized = await worker.fetch(
    new Request("https://quick-quote-kr.pages.dev/api/padiem/auth/password/login", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Content-Length": String(33 * 1024)
      },
      body: JSON.stringify({ identifier: "x", password: "y" })
    }),
    env
  );
  assert.equal(oversized.status, 413);

  console.log("PADIEM_ACCOUNT_BRIDGE_RUNTIME=PASS");
  console.log("ARBITRARY_UPSTREAM_PROXY=0");
  console.log("AUTHORIZATION_HEADER_FORWARD=0");
  console.log("OPAQUE_SESSION_COOKIE_RELAY=PASS");
  console.log("SERVICE_BINDING_PRIORITY=PASS");
  console.log("PRODUCTION_MUTATION=0");
} finally {
  globalThis.fetch = originalFetch;
}
