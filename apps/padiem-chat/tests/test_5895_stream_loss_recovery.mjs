import test from "node:test";
import assert from "node:assert/strict";

// #5895: a long PC turn can outlive the browser connection. The Chat relay calls
// that a stream loss, never a refusal, and the turn must then be read back from
// the stored run result with GETs only. This test joins the two halves that the
// separate #5015 and #3930 tests each covered on their own.
globalThis.window = globalThis;
await import(new URL("../static/chat-transport.js", import.meta.url));
await import(new URL("../static/chat-pc-result-recovery.js", import.meta.url));

const transport = globalThis.PadiemChatTransport;
const recoveryModule = globalThis.PadiemChatPcRecovery;

const RUN_ID = "chat_pcq_" + "a".repeat(32);
const CONVERSATION_ID = "chat_" + "c".repeat(32);

function response(status, body) {
  return {ok: status >= 200 && status < 300, status, json: async () => body};
}

function recorder(handler) {
  const calls = [];
  return {
    calls,
    fetchImpl: async (url, options) => {
      calls.push({url, ...options});
      return handler(calls.length, url, options);
    },
  };
}

test("only a stream that stopped without a result counts as a stream loss", () => {
  assert.equal(transport.isStreamLoss({error: {code: "invalid_engine_stream"}}), true);
  assert.equal(transport.isStreamLoss({error: {code: "invalid_engine_stream_event"}}), true);
  for (const code of [
    "unauthorized", "tier_not_available", "chat_pc_run_id_conflict",
    "engine_execution_failed", "orchestration_unavailable", "upstream_timeout",
  ]) {
    assert.equal(transport.isStreamLoss({error: {code}}), false, code);
  }
  assert.equal(transport.isStreamLoss(undefined), false);
});

test("a cut PC stream is recovered from the stored answer with GETs only", async () => {
  const frame = {error: {code: "invalid_engine_stream", message: "AI 작업 스트림을 확인할 수 없습니다."}};
  assert.equal(transport.isStreamLoss(frame), true);
  const fake = recorder(() => response(200, {ok: true, result: {
    run_id: RUN_ID,
    conversation_id: CONVERSATION_ID,
    status: "completed",
    answer: "stored answer",
    answer_source: "pc_command_result",
  }}));
  const recovery = recoveryModule.create({fetchImpl: fake.fetchImpl, sleep: async () => {}});
  const recovered = await recovery.recoverOnce({runId: RUN_ID, conversationId: CONVERSATION_ID});
  assert.equal(recovered.kind, "completed");
  assert.equal(recovered.answer, "stored answer");
  assert.equal(recovered.answerSource, "pc_command_result");
  assert.ok(fake.calls.every((call) => call.method === "GET"));
  assert.match(fake.calls[0].url, /\/api\/claw\/runs\/chat_pcq_a+\/pending-result$/);
});

test("a run still executing after the cut is reported as pending, never failed", async () => {
  const fake = recorder(() => response(200, {ok: true, result: {
    run_id: RUN_ID, conversation_id: CONVERSATION_ID, status: "running",
  }}));
  const recovery = recoveryModule.create({fetchImpl: fake.fetchImpl, sleep: async () => {}});
  const first = await recovery.recoverOnce({runId: RUN_ID, conversationId: CONVERSATION_ID});
  assert.equal(first.kind, "pending");
  assert.equal(first.status, "running");
});
