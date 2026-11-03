import test from "node:test";
import assert from "node:assert/strict";

// #6732: 탭 안에서 상태 확인 결과를 재사용한다. 실제 static/chat-transport.js를 그대로 불러온다.
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

test("readiness is asked once per tab and reused for the following turns", async () => {
  transport.invalidateOrchestrationReady();
  const calls = installFetch((url) => url.endsWith("/api/orchestration/status")
    ? jsonResponse({ orchestration_ready: true, authenticated: true })
    : jsonResponse({ ok: true, answer: "네" }));
  await transport.requestStreaming(PAYLOAD, null);
  await transport.requestStreaming(PAYLOAD, null);
  assert.equal(statusCalls(calls), 1, "one status probe for two answers");
  assert.equal(calls.filter((call) => call.method === "POST").length, 2);
});

test("a 401 from the lane drops the cached readiness", async () => {
  transport.invalidateOrchestrationReady();
  let allow = false;
  const calls = installFetch((url) => {
    if (url.endsWith("/api/orchestration/status")) {
      return jsonResponse({ orchestration_ready: true, authenticated: true });
    }
    return allow
      ? jsonResponse({ ok: true, answer: "네" })
      : jsonResponse({ error: { code: "unauthorized", message: "로그인이 필요합니다." } }, 401);
  });
  await assert.rejects(() => transport.requestStreaming(PAYLOAD, null));
  allow = true;
  await transport.requestStreaming(PAYLOAD, null);
  assert.equal(statusCalls(calls), 2, "the dropped cache must be re-asked, not assumed");
});

test("a not-ready status is never cached", async () => {
  transport.invalidateOrchestrationReady();
  const calls = installFetch(() => jsonResponse({ orchestration_ready: false, authenticated: true }));
  assert.equal(await transport.orchestrationReady(null), false);
  assert.equal(await transport.orchestrationReady(null), false);
  assert.equal(calls.length, 2);
});

test("the cached readiness expires after five minutes", async () => {
  transport.invalidateOrchestrationReady();
  const realNow = Date.now;
  let now = 1_000_000;
  Date.now = () => now;
  try {
    const calls = installFetch(() => jsonResponse({ orchestration_ready: true, authenticated: true }));
    assert.equal(await transport.orchestrationReady(null), true);
    assert.equal(await transport.orchestrationReady(null), true);
    assert.equal(calls.length, 1);
    now += 5 * 60 * 1000;
    assert.equal(await transport.orchestrationReady(null), true);
    assert.equal(calls.length, 2);
  } finally {
    Date.now = realNow;
  }
});
