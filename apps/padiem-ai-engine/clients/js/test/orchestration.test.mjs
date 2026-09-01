import test from "node:test";
import assert from "node:assert/strict";

import {
  ENGINE_CONTRACT_MAJOR,
  ENGINE_CONTRACT_VERSION,
  ENGINE_ORCHESTRATE_PATH,
  ENGINE_ORCHESTRATE_RESUME_PATH,
  ENGINE_ORCHESTRATE_CANCEL_PATH,
  ORCHESTRATION_FIELD_PARITY,
  PadiemAiEngineClient,
  PadiemAiEngineClientError,
} from "../padiem-ai-engine-client.mjs";

const VALID_APP_ID = "b62";
const VALID_CALLER_ID = "b62_web_app";
const VALID_CREDENTIAL = "x".repeat(48);

function makeValidRequest() {
  return {
    agent: {
      id: "agent:padiem:orchestrator@1",
      title: "Orchestrator",
      description: "Desc",
      system_instruction: "Inst",
      task_type: "general",
      optimize_for: "balanced",
      max_tokens: 2048,
    },
    messages: [{ role: "user", content: "Hello orchestration" }],
    trace_id: "tr_js_orch",
    execution_context: {
      trace_id: "tr_js_orch",
      timeout_seconds: 15,
    },
  };
}

test("orchestrate sends authenticated request and parses orchestration result", async () => {
  let capturedUrl;
  let capturedHeaders;
  let capturedBody;

  const mockBinding = {
    async fetch(url, init) {
      capturedUrl = String(url);
      capturedHeaders = init.headers;
      capturedBody = JSON.parse(init.body);
      return new Response(
        JSON.stringify({
          ok: true,
          orchestration: {
            execution: { answer: "orchestrated answer", route: {}, metadata: {} },
            context: { trace_id: "tr_js_orch" },
            app_id: VALID_APP_ID,
            resolved_tool_ids: [],
            evidence: {},
            events: [{ kind: "run_started" }, { kind: "run_completed" }],
            state_machine: { current_state: "completed", transitions: [] },
          },
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    },
  };

  const client = new PadiemAiEngineClient({
    binding: mockBinding,
    appId: VALID_APP_ID,
    callerId: VALID_CALLER_ID,
    credential: VALID_CREDENTIAL,
  });

  const res = await client.orchestrate(makeValidRequest());
  assert.equal(capturedUrl, "https://padiem-ai-engine.internal/internal/v1/orchestrate");
  assert.equal(capturedHeaders["X-Padiem-Engine-Caller"], VALID_CALLER_ID);
  assert.equal(capturedHeaders["X-Padiem-Engine-Credential"], VALID_CREDENTIAL);
  assert.equal(capturedBody.app_id, VALID_APP_ID);
  assert.equal(res.execution.answer, "orchestrated answer");
  assert.equal(res.state_machine.current_state, "completed");
});

test("resumeOrchestration sends authenticated resume request", async () => {
  let capturedUrl;
  let capturedBody;

  const mockBinding = {
    async fetch(url, init) {
      capturedUrl = String(url);
      capturedBody = JSON.parse(init.body);
      return new Response(
        JSON.stringify({
          ok: true,
          orchestration: {
            execution: { answer: "resumed answer", route: {}, metadata: {} },
            context: { trace_id: "tr_js_orch" },
            app_id: VALID_APP_ID,
            resolved_tool_ids: [],
            evidence: {},
            events: [{ kind: "run_resumed" }, { kind: "run_completed" }],
            state_machine: { current_state: "completed", transitions: [] },
          },
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    },
  };

  const client = new PadiemAiEngineClient({
    binding: mockBinding,
    appId: VALID_APP_ID,
    callerId: VALID_CALLER_ID,
    credential: VALID_CREDENTIAL,
  });

  const req = {
    ...makeValidRequest(),
    continuation_ref: "cont_server_opaque_ref",
    decision: {
      decision_id: "d1",
      pause_id: "p1",
      outcome: "approved",
      authority_ref: "user:admin",
      evidence_ref: "session:auth",
      decided_at: "2026-01-01T00:00:00+00:00",
    },
  };

  const res = await client.resumeOrchestration(req);
  assert.equal(capturedUrl, "https://padiem-ai-engine.internal/internal/v1/orchestrate/resume");
  assert.equal(capturedBody.continuation_ref, "cont_server_opaque_ref");
  assert.equal(capturedBody.decision.outcome, "approved");
  assert.equal(res.execution.answer, "resumed answer");
});

test("resumeOrchestration rejects serialized pause state", async () => {
  const fake = {
    async fetch() {
      return new Response("{}", { status: 500 });
    },
  };
  const client = new PadiemAiEngineClient({
    binding: fake,
    appId: VALID_APP_ID,
    callerId: VALID_CALLER_ID,
    credential: VALID_CREDENTIAL,
  });

  await assert.rejects(
    client.resumeOrchestration({
      ...makeValidRequest(),
      pause: { pause_id: "p1" },
      decision: { decision_id: "d1", pause_id: "p1", outcome: "approved" },
    }),
    (error) => error instanceof PadiemAiEngineClientError && error.code === "unsupported_orchestration_field",
  );
});

test("cancelOrchestrationPause sends cancel request", async () => {
  let capturedUrl;
  let capturedBody;

  const mockBinding = {
    async fetch(url, init) {
      capturedUrl = String(url);
      capturedBody = JSON.parse(init.body);
      return new Response(
        JSON.stringify({
          ok: true,
          status: "cancelled",
          events: [{ kind: "run_cancelled" }],
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    },
  };

  const client = new PadiemAiEngineClient({
    binding: mockBinding,
    appId: VALID_APP_ID,
    callerId: VALID_CALLER_ID,
    credential: VALID_CREDENTIAL,
  });

  const res = await client.cancelOrchestrationPause({
    continuation_ref: "cont_server_opaque_ref",
    reason: "user_cancel",
  });
  assert.equal(capturedUrl, "https://padiem-ai-engine.internal/internal/v1/orchestrate/cancel");
  assert.equal(capturedBody.app_id, VALID_APP_ID);
  assert.equal(capturedBody.continuation_ref, "cont_server_opaque_ref");
  assert.equal(res.ok, true);
  assert.equal(res.status, "cancelled");
});

test("cancelOrchestrationPause keeps app identity client-owned and rejects extra fields", async () => {
  const fake = {
    calls: [],
    async fetch() {
      return new Response(
        JSON.stringify({ ok: true, status: "cancelled", events: [] }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    },
  };
  const client = new PadiemAiEngineClient({
    binding: fake,
    appId: VALID_APP_ID,
    callerId: VALID_CALLER_ID,
    credential: VALID_CREDENTIAL,
  });

  await assert.rejects(
    client.cancelOrchestrationPause({
      continuation_ref: "cont_server_opaque_ref",
      app_id: "other-app",
    }),
    (error) => error instanceof PadiemAiEngineClientError && error.code === "invalid_engine_request",
  );
  assert.equal(fake.calls.length, 0);
});

test("orchestrate rejects deferred authority-bearing fields before fetch", async () => {
  const fake = {
    calls: [],
    async fetch(...args) {
      this.calls.push(args);
      return new Response("{}", { status: 500 });
    },
  };
  const client = new PadiemAiEngineClient({
    binding: fake,
    appId: VALID_APP_ID,
    callerId: VALID_CALLER_ID,
    credential: VALID_CREDENTIAL,
  });

  for (const field of ["agent_definition", "compiled_agent_profile", "tool_authorization"]) {
    await assert.rejects(
      client.orchestrate({
        ...makeValidRequest(),
        [field]: { caller_supplied: true },
      }),
      (error) => error instanceof PadiemAiEngineClientError && error.code === "unsupported_orchestration_field",
    );
  }
  assert.equal(fake.calls.length, 0);
});

test("execute and stream do not expose orchestration-only fields", async () => {
  const fake = {
    calls: [],
    async fetch(...args) {
      this.calls.push(args);
      return new Response("{}", { status: 500 });
    },
  };
  const client = new PadiemAiEngineClient({
    binding: fake,
    appId: VALID_APP_ID,
    callerId: VALID_CALLER_ID,
    credential: VALID_CREDENTIAL,
  });

  await assert.rejects(
    client.execute({ ...makeValidRequest(), subject_id: "user:alice" }),
    (error) => error instanceof PadiemAiEngineClientError && error.code === "invalid_engine_request",
  );

  const stream = client.stream({ ...makeValidRequest(), agent_plan: { agent_id: "agent:padiem:orchestrator@1", steps: [] } });
  await assert.rejects(
    async () => {
      for await (const _event of stream) {
        // Should fail before a fetch occurs.
      }
    },
    (error) => error instanceof PadiemAiEngineClientError && error.code === "invalid_engine_request",
  );

  assert.equal(fake.calls.length, 0);
});

test("orchestration field parity table marks unsupported authority fields explicitly", () => {
  assert.equal(ORCHESTRATION_FIELD_PARITY.agent_definition, "EXPLICITLY_DEFERRED_AND_REJECTED");
  assert.equal(ORCHESTRATION_FIELD_PARITY.compiled_agent_profile, "EXPLICITLY_DEFERRED_AND_REJECTED");
  assert.equal(ORCHESTRATION_FIELD_PARITY.tool_authorization, "EXPLICITLY_DEFERRED_AND_REJECTED");
  assert.equal(ORCHESTRATION_FIELD_PARITY.agent_plan, "SUPPORTED_AND_MAPPED");
  assert.equal(ORCHESTRATION_FIELD_PARITY.decision, "RESUME_ONLY_SUPPORTED_AND_MAPPED");
  assert.equal(ORCHESTRATION_FIELD_PARITY.reason, "CANCEL_ONLY_SUPPORTED_AND_MAPPED");
});
