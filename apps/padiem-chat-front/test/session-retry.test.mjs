import test from 'node:test';
import assert from 'node:assert/strict';

// Load the browser helper with a minimal window stub; the helper attaches
// window.PadiemSharedSession at import time.
const windowStub = {};
globalThis.window = windowStub;
await import("../../padiem-chat/static/shared-session-retry.js");
const { refreshOnce, fetchWithSessionRetry } = windowStub.PadiemSharedSession;

const calls = [];
function stubFetch(handler) {
  globalThis.fetch = async (url, init) => handler(url, init);
  calls.length = 0;
}

test("a 401 triggers exactly one refresh and one retry that succeeds", async () => {
  stubFetch((url) => {
    calls.push(url);
    if (url === "/auth/shared/refresh") return Promise.resolve(new Response('{"ok":true}', { status: 200 }));
    return Promise.resolve(new Response('{"error":"unauthorized"}', { status: calls.length <= 2 ? 401 : 200 }));
  });
  const response = await fetchWithSessionRetry("/api/pc/pairings", { method: "GET" });
  assert.equal(response.status, 200);
  assert.deepEqual(calls, [
    "/api/pc/pairings",          // first call: access cookie expired
    "/auth/shared/refresh",      // one silent refresh
    "/api/pc/pairings",          // one retry
  ]);
});

test("a failed refresh returns the original 401 and never loops", async () => {
  stubFetch((url) => {
    calls.push(url);
    if (url === "/auth/shared/refresh") return Promise.resolve(new Response('{"ok":false}', { status: 503 }));
    return Promise.resolve(new Response('{"error":"unauthorized"}', { status: 401 }));
  });
  const response = await fetchWithSessionRetry("/api/account/pc-delegations", { method: "GET" });
  assert.equal(response.status, 401);
  assert.deepEqual(calls, ["/api/account/pc-delegations", "/auth/shared/refresh"]);
});

test("a 200 answer never touches the refresh endpoint", async () => {
  stubFetch((url) => {
    calls.push(url);
    return Promise.resolve(new Response('{"ok":true}', { status: 200 }));
  });
  const response = await fetchWithSessionRetry("/api/pc/pairings", { method: "GET" });
  assert.equal(response.status, 200);
  assert.deepEqual(calls, ["/api/pc/pairings"]);
});
