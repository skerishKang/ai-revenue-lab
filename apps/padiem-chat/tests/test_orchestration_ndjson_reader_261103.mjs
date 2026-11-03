import test from "node:test";
import assert from "node:assert/strict";

// #6742: 서버 NDJSON 리더. 실제 static/chat-transport.js를 그대로 불러온다.
globalThis.window = globalThis;
await import(new URL("../static/chat-transport.js", import.meta.url));

const transport = globalThis.PadiemChatTransport;

function ndjsonResponse(chunks) {
  const encoder = new TextEncoder();
  let index = 0;
  return {
    ok: true,
    status: 200,
    headers: { get: () => "application/x-ndjson" },
    body: {
      getReader() {
        return {
          async read() {
            if (index >= chunks.length) return { done: true, value: undefined };
            return { done: false, value: encoder.encode(chunks[index++]) };
          },
          releaseLock() {},
        };
      },
    },
  };
}

test("one NDJSON line is one frame, even when a line is split across chunks", async () => {
  const frames = [];
  await transport.readOrchestrationNdjson(
    ndjsonResponse(['{"type":"meta","str', 'eam":true}\n{"type":"delta","text":"안"}\n']),
    (frame) => { frames.push(frame); return false; },
  );
  assert.deepEqual(frames.map((frame) => frame.type), ["meta", "delta"]);
  assert.equal(frames[1].text, "안");
});

test("a frame handler can stop the reader", async () => {
  const frames = [];
  await transport.readOrchestrationNdjson(
    ndjsonResponse(['{"type":"meta"}\n', '{"type":"delta","text":"무시"}\n']),
    (frame) => { frames.push(frame); return true; },
  );
  assert.deepEqual(frames.map((frame) => frame.type), ["meta"]);
});

test("a trailing line without a newline is still delivered", async () => {
  const frames = [];
  await transport.readOrchestrationNdjson(
    ndjsonResponse(['{"type":"done","done":true}']),
    (frame) => { frames.push(frame); return false; },
  );
  assert.equal(frames.length, 1);
  assert.equal(frames[0].done, true);
});

test("requestOrchestrationStream asks for NDJSON and returns null when the server answers JSON", async () => {
  transport.invalidateOrchestrationReady();
  const calls = [];
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url: String(url), headers: options.headers || {}, body: options.body });
    if (String(url).endsWith("/api/orchestration/status")) {
      return {
        ok: true, status: 200,
        json: async () => ({ orchestration_ready: true, authenticated: true }),
        headers: { get: () => "application/json" },
      };
    }
    return {
      ok: true, status: 200,
      json: async () => ({ ok: true, answer: "완성" }),
      headers: { get: () => "application/json" },
    };
  };
  const streamed = await transport.requestOrchestrationStream({ messages: [] }, null);
  assert.equal(streamed, null, "플래그가 꺼진 서버는 기존 JSON 경로를 쓴다");
  const post = calls.find((call) => call.url.endsWith("/api/orchestration"));
  assert.equal(post.headers.Accept, "application/x-ndjson");
  assert.equal(JSON.parse(post.body).stream, 1);
});
