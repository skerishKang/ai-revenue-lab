import test from "node:test";
import assert from "node:assert/strict";

import {
  ENGINE_CONTRACT_MAJOR,
  ENGINE_CONTRACT_VERSION,
  ENGINE_ORCHESTRATE_PATH,
  ENGINE_ORCHESTRATE_RESUME_PATH,
  ENGINE_ORCHESTRATE_CANCEL_PATH,
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
    pause: { pause_id: "p1", requirement: "user_confirmation", step_index: 1 },
    decision: { decision_id: "d1", pause_id: "p1", outcome: "approved" },
  };

  const res = await client.resumeOrchestration(req);
  assert.equal(capturedUrl, "https://padiem-ai-engine.internal/internal/v1/orchestrate/resume");
  assert.equal(capturedBody.pause.pause_id, "p1");
  assert.equal(capturedBody.decision.outcome, "approved");
  assert.equal(res.execution.answer, "resumed answer");
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
    pause: { pause_id: "p1", requirement: "user_confirmation", step_index: 1 },
    reason: "user_cancel",
  });
  assert.equal(capturedUrl, "https://padiem-ai-engine.internal/internal/v1/orchestrate/cancel");
  assert.equal(res.ok, true);
  assert.equal(res.status, "cancelled");
});
