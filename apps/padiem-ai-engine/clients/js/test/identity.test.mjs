import assert from "node:assert/strict";
import test from "node:test";

import { PadiemAiEngineClient } from "../padiem-ai-engine-client.mjs";

const RUN = {
  agent: {
    id: "general",
    title: "General",
    description: "General task",
    system_instruction: "Be useful.",
    task_type: "general",
    optimize_for: "balanced",
    max_tokens: 64,
  },
  messages: [{ role: "user", content: "hello" }],
};

function response(body, status = 200, headers = { "content-type": "application/json" }) {
  return new Response(JSON.stringify(body), { status, headers });
}

test("client sends fixed caller identity headers", async () => {
  let request;
  const binding = {
    fetch(input, init) {
      request = { input, init };
      return Promise.resolve(response({
        ok: true,
        answer: "ok",
        route: {},
        metadata: {},
      }));
    },
  };

  const client = new PadiemAiEngineClient({
    binding,
    appId: "padiem-chat",
    callerId: "b62-service",
    credential: "S".repeat(48),
  });

  const result = await client.execute(RUN);
  assert.equal(result.answer, "ok");
  assert.equal(request.init.headers["X-Padiem-Engine-Caller"], "b62-service");
  assert.equal(request.init.headers["X-Padiem-Engine-Credential"], "S".repeat(48));
  assert.match(request.input, /\/internal\/v1\/execute$/);
});

test("client rejects missing caller credential before fetch", () => {
  const binding = { fetch() { throw new Error("must not fetch"); } };
  assert.throws(
    () => new PadiemAiEngineClient({
      binding,
      appId: "padiem-chat",
      callerId: "b62-service",
      credential: "too-short",
    }),
    /credential must contain 32 to 512 characters/,
  );
});
