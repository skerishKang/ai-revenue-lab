import assert from "node:assert/strict";
import test from "node:test";

import {
  ORCHESTRATION_FIELD_PARITY,
  PadiemAiEngineClient,
  PadiemAiEngineClientError,
} from "../padiem-ai-engine-client.mjs";

const CALLER_ID = "b61-service";
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
    trace_id: "trace_permission",
    ...overrides,
  };
}

function contextPermission() {
  return {
    envelope: {
      request_id: "request_permission",
      source_quality_gate_applied: true,
      candidates: [
        {
          id: "context_1",
          scope_id: "project_alpha",
          resource_ref: "doc_alpha",
          provenance: ["trusted_product_projection"],
          source_quality_selected: true,
        },
      ],
    },
    boundary: {
      allowed_scope_ids: ["project_alpha"],
      allowed_resource_refs: ["doc_alpha"],
      boundary_available: true,
      max_allowed_context: 4,
      policy_version: "context-permission:v1",
    },
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

function client(fake) {
  return new PadiemAiEngineClient({
    binding: fake,
    appId: "storymemory",
    callerId: CALLER_ID,
    credential: CREDENTIAL,
  });
}

function assertInvalidEngineRequest(error) {
  return (
    error instanceof PadiemAiEngineClientError &&
    error.code === "invalid_engine_request"
  );
}

test("execute passes trusted context permission wire fields without interpreting them", async () => {
  const diagnostics = {
    boundary_disposition: "permitted",
    policy_version: "context-permission:v1",
    allowed_count: 1,
    filtered_count: 0,
  };
  const fake = binding(async () =>
    new Response(
      JSON.stringify({
        ok: true,
        answer: "done",
        route: {},
        metadata: {},
        context_permission: diagnostics,
      }),
      { status: 200, headers: { "content-type": "application/json" } },
    ),
  );
  const engine = client(fake);
  const permission = contextPermission();

  const result = await engine.execute(
    run({
      context_permission: permission,
      context_permission_required: true,
    }),
  );

  assert.equal(fake.calls.length, 1);
  assert.equal(
    fake.calls[0].input,
    "https://padiem-ai-engine.internal/internal/v1/execute",
  );
  assert.equal(fake.calls[0].init.headers["X-Padiem-Engine-Caller"], CALLER_ID);
  assert.equal(fake.calls[0].init.headers["X-Padiem-Engine-Credential"], CREDENTIAL);

  const body = JSON.parse(fake.calls[0].init.body);
  assert.deepEqual(body.context_permission, permission);
  assert.equal(body.context_permission_required, true);
  assert.deepEqual(result.context_permission, diagnostics);
  assert.equal(
    ORCHESTRATION_FIELD_PARITY.context_permission,
    "EXECUTE_ONLY_SUPPORTED_AND_MAPPED",
  );
  assert.equal(
    ORCHESTRATION_FIELD_PARITY.context_permission_required,
    "EXECUTE_ONLY_SUPPORTED_AND_MAPPED",
  );
});

test("stream rejects context permission fields before Service Binding call", async () => {
  const fake = binding(async () => new Response("{}", { status: 500 }));
  const engine = client(fake);

  await assert.rejects(
    async () => {
      for await (const _event of engine.stream(
        run({ context_permission: contextPermission() }),
      )) {
        // consume
      }
    },
    assertInvalidEngineRequest,
  );

  assert.equal(fake.calls.length, 0);
});

test("orchestration routes reject execute-only context permission fields", async () => {
  const fake = binding(async () => new Response("{}", { status: 500 }));
  const engine = client(fake);

  await assert.rejects(
    engine.orchestrate(run({ context_permission: contextPermission() })),
    assertInvalidEngineRequest,
  );

  await assert.rejects(
    engine.resumeOrchestration(
      run({
        continuation_ref: "cont_permission_1",
        decision: { outcome: "approved" },
        context_permission_required: true,
      }),
    ),
    assertInvalidEngineRequest,
  );

  assert.equal(fake.calls.length, 0);
});

test("execute still rejects unknown authority-bearing lookalike fields", async () => {
  const fake = binding(async () => new Response("{}", { status: 500 }));
  const engine = client(fake);

  await assert.rejects(
    engine.execute(
      run({
        context_permission_grant: { allow_all: true },
      }),
    ),
    assertInvalidEngineRequest,
  );

  assert.equal(fake.calls.length, 0);
});
