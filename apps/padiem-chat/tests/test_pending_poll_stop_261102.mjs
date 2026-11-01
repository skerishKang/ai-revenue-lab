import test from "node:test";
import assert from "node:assert/strict";

// #pending-poll-stop 261102: after the submit POST itself was refused
// (502/503), the screen must not start pending-result checks for that run,
// and a check that sees 404 must stop for good -- a 404 says the result does
// not exist, not "not yet". The normal cut-stream recovery (#5895) stays.
globalThis.window = globalThis;
await import(new URL("../static/chat-transport.js", import.meta.url));
await import(new URL("../static/chat-pc-result-recovery.js", import.meta.url));

const transport = globalThis.PadiemChatTransport;
const recoveryModule = globalThis.PadiemChatPcRecovery;

const RUN_ID = "chat_pcq_" + "b".repeat(32);
const CONVERSATION_ID = "chat_" + "d".repeat(32);

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

test("a refused submit POST is marked rejected, a cut stream is not", () => {
  for (const status of [502, 503, 504]) {
    const error = transport.errorFor(null, "refused", status);
    assert.equal(error.submissionRejected, true, String(status));
  }
  const refusedBody = transport.errorFor(
    {ok: false, error: {code: "chat_pc_run_id_conflict"}}, "conflict", 409);
  assert.equal(refusedBody.submissionRejected, true);

  // A stream frame error carries no HTTP status: the run may exist server-side
  // and recovery must stay allowed for it (#5895 regression guard).
  const cut = transport.errorFor({error: {code: "invalid_engine_stream"}}, "cut");
  assert.notEqual(cut.submissionRejected, true);

  // An accepted-but-blank completion (status 200) is not a refusal either.
  const blank = transport.errorFor({ok: true}, "blank", 200);
  assert.notEqual(blank.submissionRejected, true);

  // terminalRecord still marks what it marked before.
  const unprocessable = transport.errorFor({error: {code: "input_schema_rejected"}}, "x", 422);
  assert.equal(unprocessable.terminalRecord, true);
});

test("a 404 stops the check and the same run is never read again", async () => {
  const fake = recorder(() => response(404, {ok: false, error: {code: "run_not_found"}}));
  const recovery = recoveryModule.create({fetchImpl: fake.fetchImpl, sleep: async () => {}});

  const first = await recovery.recoverOnce({runId: RUN_ID, conversationId: CONVERSATION_ID});
  assert.equal(first.kind, "rejected");
  assert.equal(first.gone, true);
  assert.equal(fake.calls.length, 1, "the missing run was read exactly once");

  await recovery.recoverOnce({runId: RUN_ID, conversationId: CONVERSATION_ID});
  assert.equal(fake.calls.length, 1, "a second attempt must not reach the network");

  const waited = await recovery.waitForResult({runId: RUN_ID, conversationId: CONVERSATION_ID});
  assert.notEqual(waited.kind, "pending");
  assert.equal(fake.calls.length, 1, "waiting on a gone run must not issue reads either");
});

test("a run that disappears mid-wait ends the wait with that one read", async () => {
  const fake = recorder((n) => (n === 1
    ? response(200, {ok: true, result: {
      run_id: RUN_ID, conversation_id: CONVERSATION_ID, status: "running",
    }})
    : response(404, {ok: false, error: {code: "run_not_found"}})));
  const recovery = recoveryModule.create({fetchImpl: fake.fetchImpl, sleep: async () => {}});

  const result = await recovery.waitForResult({runId: RUN_ID, conversationId: CONVERSATION_ID});
  assert.equal(result.kind, "rejected");
  assert.equal(result.gone, true);
  assert.equal(fake.calls.length, 2, "running read, then the 404 that ends it");

  const later = await recovery.recoverOnce({runId: RUN_ID, conversationId: CONVERSATION_ID});
  assert.equal(fake.calls.length, 2, "after the 404 nothing more is fetched for the run");
  assert.notEqual(later.kind, "pending");
});

test("normal flow regression: pending then completed still lands", async () => {
  const fake = recorder((n) => (n === 1
    ? response(200, {ok: true, result: {
      run_id: RUN_ID, conversation_id: CONVERSATION_ID, status: "pending",
    }})
    : response(200, {ok: true, result: {
      run_id: RUN_ID, conversation_id: CONVERSATION_ID, status: "completed",
      answer: "stored answer", answer_source: "pc_command_result",
    }})));
  const recovery = recoveryModule.create({fetchImpl: fake.fetchImpl, sleep: async () => {}});
  const result = await recovery.waitForResult({runId: RUN_ID, conversationId: CONVERSATION_ID});
  assert.equal(result.kind, "completed");
  assert.equal(result.answer, "stored answer");
});

test("a transient 503 is never recorded as gone", async () => {
  let n = 0;
  const fake = recorder(() => {
    n += 1;
    return n === 1
      ? response(503, {ok: false, error: {code: "run_result_unavailable"}})
      : response(200, {ok: true, result: {
        run_id: RUN_ID, conversation_id: CONVERSATION_ID, status: "completed",
        answer: "late answer", answer_source: "pc_command_result",
      }});
  });
  const recovery = recoveryModule.create({fetchImpl: fake.fetchImpl, sleep: async () => {}});
  const first = await recovery.recoverOnce({runId: RUN_ID, conversationId: CONVERSATION_ID});
  assert.equal(first.kind, "unavailable");
  assert.notEqual(first.gone, true);
  const second = await recovery.recoverOnce({runId: RUN_ID, conversationId: CONVERSATION_ID});
  // attempted bookkeeping makes a plain re-attempt a duplicate, not a new GET;
  // the point here is that a transient 503 is not remembered as gone.
  assert.equal(second.kind, "duplicate");
});
