import test from "node:test";
import assert from "node:assert/strict";

await import(new URL("../static/chat-pc-result-recovery.js", import.meta.url));

const recoveryModule = globalThis.PadiemChatPcRecovery;
const RUN_ID = "chat_pcq_" + "a".repeat(32);
const OTHER_RUN_ID = "chat_pcq_" + "b".repeat(32);
const CONVERSATION_ID = "chat_" + "c".repeat(32);
const OTHER_CONVERSATION_ID = "chat_" + "d".repeat(32);

function response(status, body) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  };
}

function completedBody(overrides = {}) {
  return {ok: true, result: {
    run_id: RUN_ID,
    conversation_id: CONVERSATION_ID,
    status: "completed",
    answer: "stored answer",
    answer_source: "pc_command_result",
    ...overrides,
  }};
}

function recorder(handler) {
  const calls = [];
  const fetchImpl = async (url, options) => {
    calls.push({url, ...options});
    return handler(calls.length, url, options);
  };
  return {calls, fetchImpl};
}

test("normal final delivery returns the stored answer with a GET only", async () => {
  const fake = recorder(() => response(200, completedBody()));
  const recovery = recoveryModule.create({fetchImpl: fake.fetchImpl, sleep: async () => {}});
  const result = await recovery.recoverOnce({runId: RUN_ID, conversationId: CONVERSATION_ID});
  assert.equal(result.kind, "completed");
  assert.equal(result.answer, "stored answer");
  assert.equal(result.answerSource, "pc_command_result");
  assert.equal(fake.calls.length, 1);
  assert.ok(fake.calls.every((call) => call.method === "GET"));
  assert.match(fake.calls[0].url, /\/api\/claw\/runs\/chat_pcq_a+\/pending-result$/);
});

test("a saved result is recovered after the live connection was lost", async () => {
  const fake = recorder((count) => response(200, count === 1
    ? {ok: true, result: {
        run_id: RUN_ID, conversation_id: CONVERSATION_ID, status: "running"
      }}
    : completedBody()));
  const recovery = recoveryModule.create({fetchImpl: fake.fetchImpl, sleep: async () => {}});
  const first = await recovery.recoverOnce({runId: RUN_ID, conversationId: CONVERSATION_ID});
  assert.equal(first.kind, "pending");
  const final = await recovery.waitForResult({
    runId: RUN_ID, conversationId: CONVERSATION_ID, maxAttempts: 3, intervalMs: 0,
  });
  assert.equal(final.kind, "completed");
  assert.equal(final.answer, "stored answer");
  assert.equal(fake.calls.length, 2);
  assert.ok(fake.calls.every((call) => call.method === "GET"));
});

test("mid-stream disconnect without a final result stays pending or failed", async () => {
  const pending = recorder(() => response(200, {ok: true, result: {
    run_id: RUN_ID, conversation_id: CONVERSATION_ID, status: "pending"
  }}));
  const pendingRecovery = recoveryModule.create({fetchImpl: pending.fetchImpl, sleep: async () => {}});
  const pendingResult = await pendingRecovery.waitForResult({
    runId: RUN_ID, conversationId: CONVERSATION_ID, maxAttempts: 2, intervalMs: 0,
  });
  assert.equal(pendingResult.kind, "pending");
  assert.notEqual(pendingResult.kind, "completed");

  const failed = recorder(() => response(200, {ok: true, result: {
    run_id: RUN_ID, conversation_id: CONVERSATION_ID, status: "failed"
  }}));
  const failedRecovery = recoveryModule.create({fetchImpl: failed.fetchImpl, sleep: async () => {}});
  const failedResult = await failedRecovery.recoverOnce({runId: RUN_ID});
  assert.equal(failedResult.kind, "failed");
});

test("foreign owner, mismatched conversation and missing run are rejected", async () => {
  const foreign = recorder(() => response(200, completedBody({run_id: OTHER_RUN_ID})));
  const foreignResult = await recoveryModule.create({fetchImpl: foreign.fetchImpl}).recoverOnce({
    runId: RUN_ID, conversationId: CONVERSATION_ID,
  });
  assert.equal(foreignResult.kind, "rejected");

  const mismatch = recorder(() => response(200,
    completedBody({conversation_id: OTHER_CONVERSATION_ID})));
  const mismatchResult = await recoveryModule.create({fetchImpl: mismatch.fetchImpl}).recoverOnce({
    runId: RUN_ID, conversationId: CONVERSATION_ID,
  });
  assert.equal(mismatchResult.kind, "rejected");

  const missing = recorder(() => response(404, {ok: false}));
  const missingResult = await recoveryModule.create({fetchImpl: missing.fetchImpl}).recoverOnce({
    runId: RUN_ID, conversationId: CONVERSATION_ID,
  });
  assert.equal(missingResult.kind, "rejected");
});

test("reconnect does not fetch or execute the same run twice", async () => {
  const fake = recorder(() => response(200, completedBody()));
  const recovery = recoveryModule.create({fetchImpl: fake.fetchImpl});
  const first = await recovery.recoverOnce({runId: RUN_ID, conversationId: CONVERSATION_ID});
  assert.equal(first.kind, "completed");
  const callsAfterFirst = fake.calls.length;
  const second = await recovery.recoverOnce({runId: RUN_ID, conversationId: CONVERSATION_ID});
  assert.equal(second.kind, "duplicate");
  assert.equal(fake.calls.length, callsAfterFirst);
  assert.ok(fake.calls.every((call) => call.method === "GET"));
});
