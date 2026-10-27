import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

// #5895: a PC turn that takes minutes is the same turn. The screen keeps
// saying "working on your PC — elapsed" and the stored answer lands in the
// conversation that started it, also when the tab was closed and reopened.
//
// The evaluated bytes are the shipped static files: the recovery controller is
// imported as it ships, and the three resume helpers are sliced out of
// static/app.js and run against stubs for fetch, the note, the locale lookup
// and the conversation reopen. Nothing here re-runs a PC turn.
globalThis.window = globalThis;
await import(new URL("../static/chat-pc-result-recovery.js", import.meta.url));
const recoveryModule = globalThis.PadiemChatPcRecovery;

const STATIC = join(fileURLToPath(new URL(".", import.meta.url)), "..", "static");
const APP = readFileSync(join(STATIC, "app.js"), "utf8");
const LIFECYCLE = readFileSync(join(STATIC, "message-lifecycle.js"), "utf8");
const LOCALE = readFileSync(join(STATIC, "locale.js"), "utf8");

const RUN_ID = "chat_pcq_" + "a".repeat(32);
const CONVERSATION_ID = "chat_" + "c".repeat(32);
const STARTED = Date.UTC(2026, 9, 27, 8, 0, 0);
const NOW = STARTED + 221_000;
const ELAPSED = "03:41";

function blockEnd(source, openIndex) {
  let depth = 0;
  for (let index = openIndex; index < source.length; index += 1) {
    if (source[index] === "{") depth += 1;
    else if (source[index] === "}") {
      depth -= 1;
      if (depth === 0) return index + 1;
    }
  }
  throw new Error("unbalanced block in the shipped bytes");
}

function shippedFn(source, name) {
  const match = new RegExp(`(async )?function ${name}\\(`).exec(source);
  assert.ok(match, `${name} is missing from the shipped bytes`);
  const open = source.indexOf("{", source.indexOf(")", match.index));
  return source.slice(match.index, blockEnd(source, open));
}

const RESUME_BLOCK = [
  shippedFn(APP, "pcWaitElapsed"),
  shippedFn(APP, "findUnfinishedPcRun"),
  shippedFn(APP, "resumeUnfinishedPcRun"),
].join("\n");
const CLOCK_BLOCK = shippedFn(LIFECYCLE, "elapsedClockText");

function localeText(key, variables = null) {
  const found = [...LOCALE.matchAll(new RegExp(`"${key}": "([^"]*)"`, "g"))];
  assert.ok(found.length >= 1, `${key} is missing from locale.js`);
  let value = found[0][1];
  Object.entries(variables || {}).forEach(([name, replacement]) => {
    value = value.replaceAll(`{${name}}`, String(replacement));
  });
  return value;
}

function pendingBody(status = "running") {
  return { ok: true, result: {
    run_id: RUN_ID, conversation_id: CONVERSATION_ID, status,
  } };
}

function completedBody(answer = "stored answer") {
  return { ok: true, result: {
    run_id: RUN_ID, conversation_id: CONVERSATION_ID, status: "completed",
    answer, answer_source: "pc_command_result",
  } };
}

function jsonResponse(body) {
  return { ok: true, status: 200, json: async () => body };
}

function runRow(overrides = {}) {
  return {
    run_id: RUN_ID, status: "running", channel: "pc", title: "PC 작업",
    created_at: new Date(STARTED).toISOString(),
    session: { conversation_id: CONVERSATION_ID },
    ...overrides,
  };
}

function appHarness(options) {
  const notes = [];
  const reopened = [];
  const handles = [];
  const reads = [];
  const fetchImpl = options.fetchFailure
    ? async () => { throw new TypeError("offline"); }
    : async (url, init) => {
      reads.push({ url, ...(init || {}) });
      return jsonResponse({ ok: true, runs: options.runs || [] });
    };
  const sandbox = {
    fetch: fetchImpl,
    setNote: (text, state) => { notes.push({ text, state }); },
    uiT: (key, variables) => localeText(key, variables),
    resolvedPcRuns: options.resolvedPcRuns || new Set(),
    pcResultRecovery: {
      waitForResult: async (handle) => {
        handles.push(handle);
        return options.result || { kind: "pending", conversationId: CONVERSATION_ID };
      },
    },
    openSavedConversation: async (id) => { reopened.push(id); return true; },
    window: {},
    Date: { parse: (value) => Date.parse(value), now: () => NOW },
  };
  const resume = vm.runInNewContext(
    `${CLOCK_BLOCK}\n`
    + "window.PadiemChatLifecycle = { elapsedClockText };\n"
    + "window.PadiemChatPcRecovery = { validRunId: validRunIdRef };\n"
    + `${RESUME_BLOCK}\nresumeUnfinishedPcRun;\n`,
    { ...sandbox, validRunIdRef: recoveryModule.validRunId },
    { filename: "static/app.js#resumeUnfinishedPcRun" },
  );
  return {
    resume: () => resume(CONVERSATION_ID),
    notes, reopened, handles, reads,
    resolvedPcRuns: sandbox.resolvedPcRuns,
  };
}

test("a PC answer that lands after minutes is a completed turn, never a failure", async () => {
  const lateReads = 180;
  const calls = [];
  const sleeps = [];
  const recovery = recoveryModule.create({
    fetchImpl: async (url, options) => {
      calls.push({ url, ...options });
      return jsonResponse(calls.length > lateReads
        ? completedBody()
        : pendingBody());
    },
    sleep: async (ms) => { sleeps.push(ms); },
  });
  const pendingStates = [];
  const result = await recovery.waitForResult({
    runId: RUN_ID,
    conversationId: CONVERSATION_ID,
    onPending: (state) => pendingStates.push(state),
  });
  assert.equal(result.kind, "completed");
  assert.equal(result.answer, "stored answer");
  assert.equal(calls.length, lateReads + 1);
  assert.ok(calls.every((call) => call.method === "GET"), "read-back is GET only");
  assert.deepEqual(sleeps, new Array(lateReads).fill(2000), "the existing poll interval");
  assert.equal(pendingStates.length, lateReads);
  assert.ok(pendingStates.every((state) => state.kind === "pending"));
});

test("the read-back stops only when the answer lands or the caller moves on", async () => {
  const controller = new AbortController();
  let reads = 0;
  const recovery = recoveryModule.create({
    fetchImpl: async () => { reads += 1; return jsonResponse(pendingBody()); },
    sleep: async () => { if (reads >= 400) controller.abort(); },
  });
  await assert.rejects(
    recovery.waitForResult({
      runId: RUN_ID, conversationId: CONVERSATION_ID, signal: controller.signal,
    }),
    (error) => error.name === "AbortError",
  );
  assert.ok(reads >= 400, `the wait stopped after ${reads} reads`);
});

test("reopening the conversation keeps showing PC work in progress with elapsed time", async () => {
  const harness = appHarness({ runs: [runRow()] });
  await harness.resume();
  assert.equal(harness.reads.length, 1);
  assert.equal(harness.reads[0].url, "/api/claw/runs");
  assert.ok(!harness.reads[0].url.includes("limit="), "the server owns the page size");
  assert.ok(!("method" in harness.reads[0]), "nothing is submitted from the read");
  assert.equal(harness.notes.length, 1);
  assert.equal(harness.notes[0].state, "status");
  assert.match(harness.notes[0].text, /PC에서 작업 중/);
  assert.ok(harness.notes[0].text.includes(ELAPSED), harness.notes[0].text);
  assert.ok(!/실패|오류|retr|다시 시도/.test(harness.notes[0].text), harness.notes[0].text);
  assert.equal(harness.handles.length, 1);
  assert.equal(harness.handles[0].runId, RUN_ID);
  assert.equal(harness.handles[0].conversationId, CONVERSATION_ID);
  assert.equal(typeof harness.handles[0].onPending, "function");
  assert.ok(!("maxAttempts" in harness.handles[0]), "no client-side give-up is chosen");
  assert.deepEqual(harness.reopened, [], "an unfinished run inserts no answer");
  harness.handles[0].onPending({ kind: "pending", status: "running" });
  assert.equal(harness.notes.length, 2);
  assert.equal(harness.notes[1].text, harness.notes[0].text);
});

test("the stored answer lands in the same conversation and is not waited on twice", async () => {
  const resolved = new Set();
  const harness = appHarness({ runs: [runRow()], result: {
    kind: "completed", conversationId: CONVERSATION_ID, answer: "stored answer",
  } });
  await harness.resume();
  assert.deepEqual(harness.reopened, [CONVERSATION_ID]);
  assert.equal(harness.resolvedPcRuns.has(RUN_ID), true);

  // The history read can still list the run as running while the stored answer
  // is already completed; that must not restart the wait after it landed.
  const again = appHarness({ runs: [runRow()], resolvedPcRuns: resolved, result: {
    kind: "completed", conversationId: CONVERSATION_ID, answer: "stored answer",
  } });
  await again.resume();
  assert.equal(again.handles.length, 1);
  assert.deepEqual(again.reopened, [CONVERSATION_ID]);
  await again.resume();
  assert.equal(again.handles.length, 1);
  assert.deepEqual(again.reopened, [CONVERSATION_ID]);
});

test("a finished, foreign or non-PC run continues nothing", async () => {
  for (const row of [
    runRow({ status: "completed" }),
    runRow({ session: { conversation_id: "chat_" + "d".repeat(32) } }),
    runRow({ run_id: "chat_" + "a".repeat(32) }),
    runRow({ session: null }),
  ]) {
    const harness = appHarness({ runs: [row] });
    await harness.resume();
    assert.deepEqual(harness.notes, []);
    assert.deepEqual(harness.handles, []);
    assert.deepEqual(harness.reopened, []);
    assert.equal(harness.reads.length, 1);
  }
});

test("an unreadable history adds no verdict and replays nothing", async () => {
  const harness = appHarness({ runs: [runRow()], fetchFailure: true });
  await harness.resume();
  assert.deepEqual(harness.reads, []);
  assert.deepEqual(harness.notes, []);
  assert.deepEqual(harness.handles, []);
  assert.deepEqual(harness.reopened, []);
});
