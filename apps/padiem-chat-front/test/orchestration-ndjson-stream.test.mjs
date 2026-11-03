import test from "node:test";
import assert from "node:assert/strict";
import { createFront as realCreateFront } from "../worker.mjs";

const createFront = (options = {}) => realCreateFront({
  sign: async (request) => new Headers(request.headers),
  ...options,
});

const orchestrationRequest = () => new Request("https://chat.example.test/api/orchestration", {
  method: "POST", body: '{"stream":1}', headers: { "content-type": "application/json" },
});

test("an NDJSON answer passes through while it is written, not when it ends", async () => {
  const encoder = new TextEncoder();
  let closed = false;
  const upstream = new Response(new ReadableStream({
    start(controller) {
      controller.enqueue(encoder.encode('{"type":"meta","stream":true}\n'));
      setTimeout(() => {
        controller.enqueue(encoder.encode('{"type":"done","done":true}\n'));
        closed = true;
        controller.close();
      }, 250);
    },
  }), { status: 200, headers: { "content-type": "application/x-ndjson; charset=utf-8" } });

  const handle = createFront({ fetchImpl: async () => upstream });
  const response = await handle(orchestrationRequest(), {
    FRONT_ORIGIN: "https://host.example", FALLBACK_MODE: "static",
  });

  assert.equal(response.headers.get("content-type"), "application/x-ndjson; charset=utf-8");
  assert.equal(response.headers.get("cache-control"), "no-store");
  const reader = response.body.getReader();
  const first = await Promise.race([
    reader.read(),
    new Promise((_, reject) => setTimeout(() => reject(new Error("first line was buffered")), 150)),
  ]);
  assert.match(new TextDecoder().decode(first.value), /"type":"meta"/);
  assert.equal(closed, false, "the first line arrived before the answer ended");
  // 끝까지 읽어 업스트림 타이머가 닫힌 컨트롤러에 쓰지 않게 한다.
  let rest = "";
  for (;;) {
    const chunk = await reader.read();
    if (chunk.done) break;
    rest += new TextDecoder().decode(chunk.value);
  }
  assert.match(rest, /"type":"done"/);
});

test("the 60s orchestration window covers the first byte, not the whole stream", async () => {
  const encoder = new TextEncoder();
  const upstream = new Response(new ReadableStream({
    start(controller) {
      controller.enqueue(encoder.encode('{"type":"meta"}\n'));
      setTimeout(() => {
        controller.enqueue(encoder.encode('{"type":"done","done":true}\n'));
        controller.close();
      }, 180);
    },
  }), { status: 200, headers: { "content-type": "application/x-ndjson" } });

  const handle = createFront({ fetchImpl: async () => upstream });
  const response = await handle(orchestrationRequest(), {
    FRONT_ORIGIN: "https://host.example", FALLBACK_MODE: "static",
    ORCHESTRATION_TIMEOUT_MS: "120",
  });
  assert.equal(response.status, 200);
  const text = await response.text();
  assert.match(text, /"type":"done"/, "the stream outlives the first-byte deadline");
});
