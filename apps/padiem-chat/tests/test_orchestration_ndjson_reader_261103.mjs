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

test("requestOrchestrationStream asks for NDJSON and adapts a JSON fallback to the old SSE answer", async () => {
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
  assert.equal(streamed.headers.get("content-type").startsWith("text/event-stream"), true);
  const frames = [];
  await transport.readSseEvents(streamed, (frame) => { frames.push(frame); return false; });
  assert.deepEqual(frames.map((frame) => frame.event), ["delta", "done"]);
  assert.equal(JSON.parse(frames[0].data).delta, "완성");
  const post = calls.find((call) => call.url.endsWith("/api/orchestration"));
  assert.equal(post.headers.Accept, "application/x-ndjson");
  assert.equal(Object.hasOwn(JSON.parse(post.body), "stream"), false);
});

test("the browser switch off keeps the legacy JSON request shape", async () => {
  transport.invalidateOrchestrationReady();
  globalThis.PADIEM_CHAT_ORCHESTRATION_STREAM = false;
  const calls = [];
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url: String(url), headers: options.headers || {}, body: options.body });
    if (String(url).endsWith("/api/orchestration/status")) {
      return { ok: true, status: 200, json: async () => ({ orchestration_ready: true, authenticated: true }), headers: { get: () => "application/json" } };
    }
    return { ok: true, status: 200, json: async () => ({ answer: "기존 응답" }), headers: { get: () => "application/json" } };
  };
  try {
    const response = await transport.requestStreaming({ messages: [] }, null);
    assert.equal(response.headers.get("content-type").startsWith("text/event-stream"), true);
    const post = calls.find((call) => call.url.endsWith("/api/orchestration"));
    assert.equal(post.headers.Accept, "application/json");
    assert.equal(Object.hasOwn(JSON.parse(post.body), "stream"), false);
  } finally {
    delete globalThis.PADIEM_CHAT_ORCHESTRATION_STREAM;
  }
});

function streamResponse(records, contentType = "application/x-ndjson", signal = null) {
  const encoder = new TextEncoder();
  let index = 0;
  let cancelCount = 0;
  const chunks = records.map((record) => encoder.encode(record));
  return {
    ok: true,
    status: 200,
    headers: { get: () => contentType },
    get cancelCount() { return cancelCount; },
    body: {
      getReader() {
        return {
          async read() {
            if (index < chunks.length) return { done: false, value: chunks[index++] };
            if (signal?.aborted) throw new DOMException("Aborted", "AbortError");
            return { done: true, value: undefined };
          },
          async cancel() { cancelCount += 1; },
          releaseLock() {},
          get cancelCount() { return cancelCount; },
        };
      },
    },
  };
}

function jsonReply(body) {
  return { ok: true, status: 200, headers: { get: () => "application/json" }, json: async () => body };
}

test("fake NDJSON server streams each delta and maps status, tool and completion records", async () => {
  transport.invalidateOrchestrationReady();
  const calls = [];
  const server = streamResponse([
    '{"type":"meta","stream":true}\n',
    '{"type":"event","event":{"kind":"tool_started","event_id":"private-1"}}\n',
    '{"type":"tool","tool":{"id":"web_search","name":"private tool name"}}\n',
    '{"type":"thought_summary","summary":"safe summary"}\n',
    '{"type":"delta","text":"길게 "}\n',
    '{"type":"delta","text":"도착"}\n',
    '{"type":"done","done":true,"conversation_id":"chat_1"}\n',
  ]);
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url: String(url), headers: options.headers || {}, body: options.body });
    if (String(url).endsWith("/api/orchestration/status")) return jsonReply({ orchestration_ready: true, authenticated: true });
    return server;
  };
  const response = await transport.requestStreaming({ messages: [] }, null);
  const seen = [];
  let answer = "";
  await transport.readSseEvents(response, (frame) => {
    seen.push(frame.event);
    if (frame.event === "delta") answer += JSON.parse(frame.data).delta;
    return false;
  });
  assert.equal(answer, "길게 도착");
  assert.deepEqual(seen, ["meta", "orchestration_event", "tool", "thought_summary", "delta", "delta", "done"]);
  const post = calls.find((call) => call.url.endsWith("/api/orchestration"));
  assert.equal(post.headers.Accept, "application/x-ndjson");
  assert.equal(Object.hasOwn(JSON.parse(post.body), "stream"), false);
});

test("a mid-stream error maps to the existing Korean timeout and error copy", async () => {
  for (const [code, expected] of [
    ["upstream_timeout", "응답 시간이 초과되었습니다. 다시 시도해 주세요."],
    ["invalid_engine_stream", "요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요."],
  ]) {
    const response = streamResponse([
      '{"type":"delta","text":"일부"}\n',
      JSON.stringify({ type: "error", code }) + "\n",
    ]);
    const events = [];
    await transport.readSseEvents(response, (frame) => { events.push(frame); return false; });
    assert.deepEqual(events.map((frame) => frame.event), ["delta", "error"]);
    const errorData = JSON.parse(events[1].data);
    assert.equal(errorData.error.code, code);
    assert.equal(transport.streamErrorMessage(errorData), expected);
  }
});

test("a malformed NDJSON line rejects and cancels the reader", async () => {
  const response = streamResponse(["not-json\n"]);
  await assert.rejects(
    () => transport.readSseEvents(response, () => false),
    SyntaxError,
  );
  assert.equal(response.cancelCount, 1);
});

test("abort stops reading and leaves the received partial answer available", async () => {
  const controller = new AbortController();
  let cancelled = false;
  const response = streamResponse([
    '{"type":"delta","text":"남길 부분"}\n',
  ], "application/x-ndjson", controller.signal);
  const originalReader = response.body.getReader;
  response.body.getReader = () => {
    const reader = originalReader();
    return { ...reader, async read() {
      const item = await reader.read();
      if (!item.done && controller.signal.aborted) throw new DOMException("Aborted", "AbortError");
      return item;
    }, async cancel() { cancelled = true; } };
  };
  let answer = "";
  await assert.rejects(() => transport.readSseEvents(response, (frame) => {
    if (frame.event === "delta") {
      answer += JSON.parse(frame.data).delta;
      controller.abort();
    }
    return false;
  }), (error) => error.name === "AbortError");
  assert.equal(answer, "남길 부분");
  assert.equal(cancelled, true);
});

test("an immediate resend after cancellation completes as a second request", async () => {
  transport.invalidateOrchestrationReady();
  let postCount = 0;
  globalThis.fetch = async (url, options = {}) => {
    if (String(url).endsWith("/api/orchestration/status")) return jsonReply({ orchestration_ready: true, authenticated: true });
    postCount += 1;
    if (postCount === 1) {
      return streamResponse(['{"type":"delta","text":"partial"}\n'], "application/x-ndjson", options.signal);
    }
    return streamResponse([
      '{"type":"delta","text":"second answer"}\n',
      '{"type":"done","done":true}\n',
    ], "application/x-ndjson", options.signal);
  };

  const firstController = new AbortController();
  const firstResponse = await transport.requestStreaming({ messages: [] }, firstController.signal);
  let partial = "";
  await assert.rejects(() => transport.readSseEvents(firstResponse, (frame) => {
    if (frame.event === "delta") {
      partial += JSON.parse(frame.data).delta;
      firstController.abort();
    }
    return false;
  }), (error) => error.name === "AbortError");
  assert.equal(partial, "partial");

  const secondResponse = await transport.requestStreaming({ messages: [] }, new AbortController().signal);
  const secondEvents = [];
  let secondAnswer = "";
  await transport.readSseEvents(secondResponse, (frame) => {
    secondEvents.push(frame.event);
    if (frame.event === "delta") secondAnswer += JSON.parse(frame.data).delta;
    return false;
  });
  assert.equal(postCount, 2);
  assert.equal(secondAnswer, "second answer");
  assert.deepEqual(secondEvents, ["delta", "done"]);
});

test("long answers are accumulated without truncating NDJSON deltas", async () => {
  const part = "가나다라마바사".repeat(12000);
  const expected = part + part + part;
  const response = streamResponse([
    JSON.stringify({ type: "delta", text: part }) + "\n",
    JSON.stringify({ type: "delta", text: part }) + "\n",
    JSON.stringify({ type: "delta", text: part }) + "\n",
    '{"type":"done","done":true}\n',
  ]);
  let answer = "";
  await transport.readSseEvents(response, (frame) => {
    if (frame.event === "delta") answer += JSON.parse(frame.data).delta;
    return false;
  });
  assert.equal(answer.length, expected.length);
  assert.equal(answer, expected);
});
