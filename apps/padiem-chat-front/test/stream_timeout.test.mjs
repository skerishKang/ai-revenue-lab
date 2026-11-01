/**
 * The front's UPSTREAM_TIMEOUT_MS is a *response header* deadline.
 *
 * worker.mjs forward(): an AbortController is armed before the upstream fetch
 * and cleared the moment the fetch resolves (headers in). The returned
 * Response object keeps its body stream, so SSE / NDJSON chat answers are not
 * cut at the timeout. These tests pin that reading, and pin what happens when
 * the deadline really does fire: the request falls back before any body byte
 * is forwarded, so a stream never mixes two origins.
 *
 * Nothing here is slow: the timeout is lowered instead of waiting 8 seconds.
 */
import test from "node:test";
import assert from "node:assert/strict";

import { createFront as realCreateFront } from "../worker.mjs";
const createFront = (options = {}) => realCreateFront({
  ...options,
  sign: async (request) => new Headers(request.headers),
});

const ORIGIN = "https://chat-com2.padiem.net";

function baseEnv(overrides = {}) {
  return {
    FRONT_ORIGIN: ORIGIN,
    FALLBACK_MODE: "static",
    COM2_CANONICAL: "off",
    HEALTH_TTL_MS: "10000",
    UPSTREAM_TIMEOUT_MS: "50",
    ...overrides,
  };
}

function trickle(chunks, gapMs) {
  const encoder = new TextEncoder();
  let index = 0;
  return new ReadableStream({
    async pull(controller) {
      if (index >= chunks.length) {
        controller.close();
        return;
      }
      await new Promise((resolve) => setTimeout(resolve, gapMs));
      controller.enqueue(encoder.encode(chunks[index]));
      index += 1;
    },
  });
}

async function drain(response) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let text = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) return text;
    text += decoder.decode(value, { stream: true });
  }
}

test("a body that trickles past UPSTREAM_TIMEOUT_MS still arrives complete", async () => {
  // 6 chunks x 60ms = ~360ms of body on a 50ms deadline.
  const upstream = new Response(trickle(["a", "b", "c", "d", "e", "f"], 60), {
    status: 200,
    headers: { "content-type": "text/event-stream" },
  });
  const handle = createFront({ fetchImpl: async () => upstream });
  const response = await handle(
    new Request("https://chat.padiem.net/api/chat/stream", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: "{}",
    }),
    baseEnv(),
  );

  assert.equal(response.status, 200);
  assert.equal(await drain(response), "abcdef");
});

test("the deadline only covers the header wait: a late header aborts and falls back", async () => {
  const handle = createFront({
    fetchImpl: async (input) => {
      await new Promise((resolve) => setTimeout(resolve, 200));
      if (input.signal && input.signal.aborted) {
        throw new DOMException("aborted", "AbortError");
      }
      return new Response("late", { status: 200 });
    },
  });

  const response = await handle(
    new Request("https://chat.padiem.net/health"),
    baseEnv({ UPSTREAM_TIMEOUT_MS: "50" }),
  );

  assert.equal(response.status, 503);
  assert.equal(response.headers.get("x-padiem-front"), "read_fallback_static");
});

test("a 5xx response passes through without mixing origins", async () => {
  const upstream = new Response(trickle(["partial-upstream"], 10), { status: 502 });
  const handle = createFront({ fetchImpl: async () => upstream });
  const response = await handle(
    new Request("https://chat.padiem.net/api/conversations"), baseEnv(),
  );
  assert.equal(response, upstream);
  assert.equal(response.status, 502);
  assert.equal(await response.text(), "partial-upstream");
});

test("a started stream is returned untouched, so no fallback can append to it", async () => {
  let fallbackCalls = 0;
  const chatWorker = {
    async fetch() {
      fallbackCalls += 1;
      return new Response("python", { status: 200 });
    },
  };
  const upstream = new Response(trickle(["one", "two"], 40), { status: 200 });
  const handle = createFront({ fetchImpl: async () => upstream });

  const response = await handle(
    new Request("https://chat.padiem.net/api/chat/stream", { method: "POST", body: "{}" }),
    baseEnv({ FALLBACK_MODE: "service", CHAT_WORKER: chatWorker }),
  );

  assert.equal(response.status, 200);
  assert.equal(await drain(response), "onetwo");
  assert.equal(fallbackCalls, 0);
});

test("an upgrade response is handed back as the same object", async () => {
  // A 101 cannot be built as a Response in Node; the proxy must not copy it.
  const marker = { status: 101, webSocket: { accept() {} }, headers: new Headers() };
  const handle = createFront({ fetchImpl: async () => marker });
  const request = new Request("https://chat.padiem.net/api/connector/ws", {
    headers: { upgrade: "websocket", connection: "Upgrade", "sec-websocket-key": "abc" },
  });

  const response = await handle(request, baseEnv());
  assert.equal(response, marker);
});
