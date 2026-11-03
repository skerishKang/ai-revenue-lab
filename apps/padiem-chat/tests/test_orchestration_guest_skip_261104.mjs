// A guest session is already known on the page: the orchestration status
// answer can never be ready without authenticated === true, so every turn of
// a guest must not pay a serial status probe before the answer request. The
// probe still runs for a signed-in session and when no session state is known.
import test from "node:test";
import assert from "node:assert/strict";

globalThis.window = globalThis;
await import(new URL("../static/chat-transport.js", import.meta.url));

const transport = globalThis.PadiemChatTransport;
const PAYLOAD = { messages: [{ role: "user", content: "안녕" }] };

function jsonResponse(body, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
    headers: { get: () => "application/json" },
  };
}

function installFetch(handler) {
  const calls = [];
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url: String(url), method: options.method || "GET" });
    return handler(String(url), options, calls.length);
  };
  return calls;
}

const statusCalls = (calls) =>
  calls.filter((call) => call.url.endsWith("/api/orchestration/status")).length;

function setSession(auth) {
  globalThis.PadiemProductCapabilities = {
    get: () => ({ deployment: {}, auth }),
  };
}

test("a signed-out guest does not pay the orchestration status probe per turn", async () => {
  transport.invalidateOrchestrationReady();
  const calls = installFetch((url) => url.endsWith("/api/chat/stream")
    ? jsonResponse({ error: { code: "quota_exhausted", message: "한도에 도달했습니다." } }, 429)
    : jsonResponse({ orchestration_ready: false, authenticated: false }));
  setSession({ loaded: true, ready: true, authenticated: false, sessionState: "guest" });
  // The refusal reaches the caller directly, without a status round trip.
  await assert.rejects(() => transport.requestStreaming(PAYLOAD, null), (error) => {
    assert.equal(error.code, "quota_exhausted");
    return true;
  });
  assert.equal(statusCalls(calls), 0);
  assert.equal(calls.filter((call) => call.url.endsWith("/api/chat/stream")).length, 1);
  delete globalThis.PadiemProductCapabilities;
});

test("the probe still runs when no session state is known", async () => {
  transport.invalidateOrchestrationReady();
  const calls = installFetch((url) => url.endsWith("/api/orchestration/status")
    ? jsonResponse({ orchestration_ready: true, authenticated: true })
    : jsonResponse({ ok: true, answer: "응답" }));
  delete globalThis.PadiemProductCapabilities;
  await transport.requestStreaming(PAYLOAD, null);
  assert.equal(statusCalls(calls), 1, "an unknown session keeps asking the endpoint");
  transport.invalidateOrchestrationReady();
  assert.equal(statusCalls(calls), 1);
});

test("the probe still runs for a signed-in session", async () => {
  transport.invalidateOrchestrationReady();
  const calls = installFetch((url) => url.endsWith("/api/orchestration/status")
    ? jsonResponse({ orchestration_ready: true, authenticated: true })
    : jsonResponse({ ok: true, answer: "응답" }));
  setSession({ loaded: true, ready: true, authenticated: true, sessionState: "signed_in" });
  await transport.requestStreaming(PAYLOAD, null);
  assert.equal(statusCalls(calls), 1, "a signed-in session keeps asking the endpoint");
  delete globalThis.PadiemProductCapabilities;
});
