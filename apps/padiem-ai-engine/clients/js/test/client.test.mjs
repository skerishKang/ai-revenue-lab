import assert from "node:assert/strict";
import test from "node:test";

import {
  ENGINE_CONTRACT_MAJOR,
  ENGINE_CONTRACT_VERSION,
  ENGINE_EXECUTE_PATH,
  ENGINE_HEALTH_PATH,
  ENGINE_STREAM_PATH,
  PadiemAiEngineClient,
  PadiemAiEngineClientError,
} from "../padiem-ai-engine-client.mjs";

const CALLER_ID = "b62-service";
const CREDENTIAL = "C".repeat(48);

function agent() {
  return {
    id: "agent-runtime:test",
    title: "Test",
    description: "Test agent",
    system_instruction: "Be bounded.",
    task_type: "general",
    optimize_for: "balanced",
    max_tokens: 256,
  };
}

function run(overrides = {}) {
  return {
    agent: agent(),
    messages: [{ role: "user", content: "hello" }],
    trace_id: "trace_1",
    ...overrides,
  };
}

function binding(handler) {
  const calls = [];
  return {
    calls,
    async fetch(input, init = {}) {
      calls.push({ input: String(input), init });
      return handler(String(input), init);
    },
  };
}

function client(fake, appId = "lovetree") {
  return new PadiemAiEngineClient({
    binding: fake,
    appId,
    callerId: CALLER_ID,
    credential: CREDENTIAL,
  });
}

test("client locks existing v1 contract constants", () => {
  assert.equal(ENGINE_CONTRACT_MAJOR, 1);
  assert.equal(ENGINE_CONTRACT_VERSION, "1.0");
  assert.equal(ENGINE_EXECUTE_PATH, "/internal/v1/execute");
  assert.equal(ENGINE_STREAM_PATH, "/internal/v1/stream");
  assert.equal(ENGINE_HEALTH_PATH, "/internal/v1/health");
});

test("execute uses fixed internal origin, server-owned app id and caller identity headers", async () => {
  const fake = binding(async () =>
    new Response(
      JSON.stringify({ ok: true, answer: "done", route: {}, metadata: {} }),
      { status: 200, headers: { "content-type": "application/json" } },
    ),
  );
  const engine = client(fake);

  const result = await engine.execute(run());

  assert.equal(result.answer, "done");
  assert.equal(fake.calls.length, 1);
  assert.equal(fake.calls[0].input, "https://padiem-ai-engine.internal/internal/v1/execute");
  assert.equal(fake.calls[0].init.headers["X-Padiem-Engine-Caller"], CALLER_ID);
  assert.equal(fake.calls[0].init.headers["X-Padiem-Engine-Credential"], CREDENTIAL);
  const body = JSON.parse(fake.calls[0].init.body);
  assert.equal(body.app_id, "lovetree");
  assert.equal(body.trace_id, "trace_1");
});

test("execute propagates normalized execution context", async () => {
  const fake = binding(async () =>
    new Response(
      JSON.stringify({ ok: true, answer: "done", route: {}, metadata: {} }),
      { status: 200, headers: { "content-type": "application/json" } },
    ),
  );
  const engine = client(fake);

  await engine.execute(
    run({
      execution_context: {
        trace_id: "trace_ctx",
        idempotency_key: "idem_ctx",
        timeout_seconds: 7,
      },
    }),
  );

  const body = JSON.parse(fake.calls[0].init.body);
  assert.deepEqual(body.execution_context, {
    trace_id: "trace_ctx",
    idempotency_key: "idem_ctx",
    timeout_seconds: 7,
  });
});

test("execution context requires trace id and rejects unsupported fields", async () => {
  const fake = binding(async () => new Response("{}", { status: 500 }));
  const engine = client(fake);

  await assert.rejects(
    engine.execute(run({ execution_context: { timeout_seconds: 5 } })),
    (error) =>
      error instanceof PadiemAiEngineClientError &&
      error.code === "invalid_engine_request",
  );
  await assert.rejects(
    engine.execute(run({ execution_context: { trace_id: "trace", provider: "openai" } })),
    (error) =>
      error instanceof PadiemAiEngineClientError &&
      error.code === "invalid_engine_request",
  );
  assert.equal(fake.calls.length, 0);
});

test("caller cannot override app id or choose arbitrary target URL", async () => {
  const fake = binding(async () => new Response("{}", { status: 500 }));
  const engine = client(fake);

  await assert.rejects(
    engine.execute({ ...run(), app_id: "b62" }),
    (error) =>
      error instanceof PadiemAiEngineClientError &&
      error.code === "invalid_engine_request",
  );
  assert.equal(fake.calls.length, 0);
  assert.equal("baseUrl" in engine, false);
});

test("safe Engine errors are normalized without exposing response internals", async () => {
  const fake = binding(async () =>
    new Response(
      JSON.stringify({
        ok: false,
        error: {
          code: "policy_blocked",
          message: "Request was blocked.",
          retryable: false,
          metadata: { status: "policy_blocked" },
        },
      }),
      { status: 422, headers: { "content-type": "application/json" } },
    ),
  );
  const engine = client(fake);

  await assert.rejects(
    engine.execute(run()),
    (error) => {
      assert(error instanceof PadiemAiEngineClientError);
      assert.equal(error.code, "policy_blocked");
      assert.equal(error.status, 422);
      assert.equal(error.retryable, false);
      return true;
    },
  );
});

test("stream parses incremental NDJSON, preserves auth headers and event objects", async () => {
  const encoder = new TextEncoder();
  const stream = new ReadableStream({
    start(controller) {
      controller.enqueue(encoder.encode('{"ok":true,"event":{"delta_content":"Hel","done":false}}\n'));
      controller.enqueue(encoder.encode('{"ok":true,"event":{"answer":"Hello","finish_reason":"stop","done":true}}\n'));
      controller.close();
    },
  });
  const fake = binding(async () =>
    new Response(stream, {
      status: 200,
      headers: { "content-type": "application/x-ndjson; charset=utf-8" },
    }),
  );
  const engine = client(fake, "lovebud");

  const events = [];
  for await (const event of engine.stream(run())) events.push(event);

  assert.deepEqual(events, [
    { delta_content: "Hel", done: false },
    { answer: "Hello", finish_reason: "stop", done: true },
  ]);
  assert.equal(fake.calls[0].input, "https://padiem-ai-engine.internal/internal/v1/stream");
  assert.equal(fake.calls[0].init.headers["X-Padiem-Engine-Caller"], CALLER_ID);
  assert.equal(fake.calls[0].init.headers["X-Padiem-Engine-Credential"], CREDENTIAL);
});

test("stream terminal error line becomes client error", async () => {
  const fake = binding(async () =>
    new Response(
      '{"ok":false,"error":{"code":"upstream_timeout","message":"Timed out.","retryable":true,"metadata":null}}\n',
      { status: 200, headers: { "content-type": "application/x-ndjson" } },
    ),
  );
  const engine = client(fake);

  await assert.rejects(
    async () => {
      for await (const _event of engine.stream(run())) {
        // consume
      }
    },
    (error) =>
      error instanceof PadiemAiEngineClientError &&
      error.code === "upstream_timeout" &&
      error.retryable === true,
  );
});

test("health uses fixed health path without caller credential headers", async () => {
  const fake = binding(async () =>
    new Response(
      JSON.stringify({
        status: "ok",
        service: "padiem-ai-engine",
        core_available: true,
        b14_service_bound: true,
        completed_run: true,
        streaming_run: true,
      }),
      { status: 200, headers: { "content-type": "application/json" } },
    ),
  );
  const engine = client(fake);

  const health = await engine.health();
  assert.equal(health.service, "padiem-ai-engine");
  assert.equal(fake.calls[0].input, "https://padiem-ai-engine.internal/internal/v1/health");
  assert.equal(fake.calls[0].init.headers, undefined);
});

test("invalid binding, app id, caller id and credential fail before network", () => {
  assert.throws(
    () => new PadiemAiEngineClient({ binding: {}, appId: "lovetree", callerId: CALLER_ID, credential: CREDENTIAL }),
    PadiemAiEngineClientError,
  );
  assert.throws(
    () => new PadiemAiEngineClient({ binding: { fetch() {} }, appId: "bad app", callerId: CALLER_ID, credential: CREDENTIAL }),
    PadiemAiEngineClientError,
  );
  assert.throws(
    () => new PadiemAiEngineClient({ binding: { fetch() {} }, appId: "lovetree", callerId: "bad caller", credential: CREDENTIAL }),
    PadiemAiEngineClientError,
  );
  assert.throws(
    () => new PadiemAiEngineClient({ binding: { fetch() {} }, appId: "lovetree", callerId: CALLER_ID, credential: "short" }),
    PadiemAiEngineClientError,
  );
});
