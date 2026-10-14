"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const adapter = require("../static/voice-stt-input.js");
const S = adapter.STATES;

function makeInput() { return { value: "" }; }

test("exports ported merge and turn-buffer", () => {
  assert.equal(typeof adapter.mergeLiveTranscriptChunk, "function");
  assert.equal(typeof adapter.createTranscriptTurnBuffer, "function");
  assert.equal(adapter.mergeLiveTranscriptChunk("", "hello"), "hello");
  assert.equal(adapter.mergeLiveTranscriptChunk("hel", "hello"), "hello");
  assert.equal(adapter.mergeLiveTranscriptChunk("hello", "lo"), "hello");
  assert.equal(adapter.mergeLiveTranscriptChunk("hi", " there"), "hi there");
  const tb = adapter.createTranscriptTurnBuffer();
  tb.merge("hi");
  assert.equal(tb.pending, "hi");
  assert.equal(tb.finishTurn(), "hi");
  assert.equal(tb.pending, "");
  assert.equal(tb.finishTurn(), null);
});

test("constants match Global Classroom #87", () => {
  const c = adapter.constants;
  assert.equal(c.LIVE_VAD_SILENCE_MS, 1300);
  assert.equal(c.GROQ_MIN_CHUNK_MS, 4000);
  assert.equal(c.GROQ_SILENCE_CUT_MS, 700);
  assert.equal(c.GROQ_MAX_CHUNK_MS, 20000);
  assert.equal(c.TRANSCRIPT_TURN_STALL_MS, 2500);
});

test("interim is preview only, never final candidate", () => {
  const finals = [];
  const a = adapter.createVoiceInputAdapter({
    generation: 1, sessionToken: "sess-A",
    onInterim: () => {}, onFinalCandidate: (t) => finals.push(t),
  });
  a.start();
  a.feedInterim("partial");
  assert.equal(a.getState(), S.INTERIM);
  assert.deepEqual(finals, []);
  a.feedInterim("partial more");
  assert.deepEqual(finals, []);
});

test("final commit proposes one candidate (no auto-send)", () => {
  const finals = [];
  const input = makeInput();
  const a = adapter.createVoiceInputAdapter({
    generation: 1, sessionToken: "sess-A", input,
    onFinalCandidate: (t, id) => finals.push({ text: t, id }),
  });
  a.start();
  a.feedInterim("hello");
  const r = a.commitFinal({ text: "hello world", utteranceId: "u1" });
  assert.equal(r.ok, true);
  assert.equal(r.text, "hello world");
  assert.deepEqual(finals, [{ text: "hello world", id: "u1" }]);
  assert.equal(a.getState(), S.FINAL);
  assert.equal(input.value, "hello world");
  input.value = "hello world (edited)";
  assert.equal(input.value, "hello world (edited)");
});

test("duplicate utteranceId dropped", () => {
  const finals = [];
  const a = adapter.createVoiceInputAdapter({
    generation: 1, sessionToken: "sess-A",
    onFinalCandidate: (t) => finals.push(t),
  });
  a.start();
  a.commitFinal({ text: "first", utteranceId: "u1" });
  const dup = a.commitFinal({ text: "again", utteranceId: "u1" });
  assert.equal(dup.ok, false);
  assert.equal(dup.reason, "duplicate-utterance");
  assert.deepEqual(finals, ["first"]);
  assert.equal(a.getAcceptedCount(), 1);
});

test("valid repeated utterance with different ids both accepted", () => {
  const finals = [];
  const a = adapter.createVoiceInputAdapter({
    generation: 1, sessionToken: "sess-A",
    onFinalCandidate: (t) => finals.push(t),
  });
  a.start();
  a.commitFinal({ text: "네", utteranceId: "u1" });
  const second = a.commitFinal({ text: "  네  ", utteranceId: "u2" });
  assert.equal(second.ok, true);
  assert.deepEqual(finals, ["네", "네"]);
  assert.equal(a.getAcceptedCount(), 2);
});
test("duplicate utteranceId only dropped, not different-id repeat", () => {
  const finals = [];
  const a = adapter.createVoiceInputAdapter({
    generation: 1, sessionToken: "sess-A",
    onFinalCandidate: (t) => finals.push(t),
  });
  a.start();
  a.commitFinal({ text: "same words", utteranceId: "u1" });
  const dup = a.commitFinal({ text: "again", utteranceId: "u1" });
  assert.equal(dup.ok, false);
  assert.equal(dup.reason, "duplicate-utterance");
  assert.deepEqual(finals, ["same words"]);
  assert.equal(a.getAcceptedCount(), 1);
});
test("ambiguous final without utterance id cannot bypass turn boundary", () => {
  const finals = [];
  const a = adapter.createVoiceInputAdapter({ onFinalCandidate: (t) => finals.push(t) });
  a.start();
  const rejected = a.commitFinal({ text: "네" });
  assert.equal(rejected.ok, false);
  assert.equal(rejected.reason, "missing-utterance-id");
  assert.deepEqual(finals, []);
});

test("idless buffered turns can legitimately repeat identical speech", () => {
  const finals = [];
  const a = adapter.createVoiceInputAdapter({ onFinalCandidate: (t) => finals.push(t) });
  a.start();
  a.feedInterim("네");
  assert.equal(a.commitFinal({}).ok, true);
  assert.equal(a.commitFinal({}).ok, false);
  a.feedInterim("네");
  assert.equal(a.commitFinal({}).ok, true);
  assert.deepEqual(finals, ["네", "네"]);
});

test("late duplicate final cannot flush a newer turn buffer", () => {
  const finals = [];
  const a = adapter.createVoiceInputAdapter({ onFinalCandidate: (t) => finals.push(t) });
  a.start();
  a.feedInterim("first");
  assert.equal(a.commitFinal({ utteranceId: "u1" }).ok, true);
  a.feedInterim("next");
  const duplicate = a.commitFinal({ text: "first", utteranceId: "u1" });
  assert.equal(duplicate.reason, "duplicate-utterance");
  const next = a.commitFinal({ utteranceId: "u2" });
  assert.equal(next.ok, true);
  assert.deepEqual(finals, ["first", "next"]);
});

test("context-marked destroyed final cannot modify a live input", () => {
  const input = makeInput();
  const a = adapter.createVoiceInputAdapter({ input });
  a.start();
  const result = a.commitFinal({ text: "stale", utteranceId: "u1", destroyed: true });
  assert.equal(result.ok, false);
  assert.equal(result.reason, "invalidated");
  assert.equal(input.value, "");
});

test("stopped adapter late events cannot reach a newly started adapter input", () => {
  const input = makeInput();
  const oldRun = adapter.createVoiceInputAdapter({ input, generation: 1, sessionToken: "A" });
  assert.equal(oldRun.start(), true);
  oldRun.stop();
  const newRun = adapter.createVoiceInputAdapter({ input, generation: 2, sessionToken: "B" });
  assert.equal(newRun.start(), true);
  assert.equal(oldRun.feedInterim("old", { generation: 1, sessionToken: "A" }).ok, false);
  assert.equal(oldRun.commitFinal({ text: "old", utteranceId: "old", generation: 1, sessionToken: "A" }).ok, false);
  assert.equal(oldRun.appendToInput("old"), null);
  newRun.feedInterim("new", { generation: 2, sessionToken: "B" });
  assert.equal(newRun.commitFinal({ utteranceId: "u2", generation: 2, sessionToken: "B" }).ok, true);
  assert.equal(input.value, "new");
});

test("turn buffer commits once even if called twice", () => {
  const finals = [];
  const a = adapter.createVoiceInputAdapter({
    generation: 1, sessionToken: "sess-A",
    onFinalCandidate: (t) => finals.push(t),
  });
  a.start();
  a.feedInterim("part one");
  a.feedInterim("part one part two");
  a.commitFinal({});
  assert.deepEqual(finals, ["part one part two"]);
  const second = a.commitFinal({});
  assert.equal(second.ok, false);
  assert.equal(second.reason, "empty");
  assert.equal(finals.length, 1);
});

test("stale generation discarded", () => {
  const finals = [];
  const a = adapter.createVoiceInputAdapter({
    generation: 7, sessionToken: "sess-A",
    onFinalCandidate: (t) => finals.push(t),
  });
  a.start();
  const r = a.commitFinal({ text: "late", utteranceId: "u9", generation: 3 });
  assert.equal(r.ok, false);
  assert.equal(r.reason, "stale-generation");
  assert.deepEqual(finals, []);
});

test("stale session token discarded (account switch)", () => {
  const finals = [];
  const a = adapter.createVoiceInputAdapter({
    generation: 7, sessionToken: "sess-A",
    onFinalCandidate: (t) => finals.push(t),
  });
  a.start();
  const r = a.commitFinal({ text: "late", utteranceId: "u9", sessionToken: "sess-B" });
  assert.equal(r.ok, false);
  assert.equal(r.reason, "stale-session");
  assert.deepEqual(finals, []);
});

test("invalidate() drops a later final", () => {
  const finals = [];
  const a = adapter.createVoiceInputAdapter({
    generation: 7, sessionToken: "sess-A",
    onFinalCandidate: (t) => finals.push(t),
  });
  a.start();
  a.invalidate("new-conversation");
  assert.equal(a.getState(), S.STOPPED);
  assert.equal(a.isStale({ destroyed: true }), true);
  const r = a.commitFinal({ text: "should not arrive" });
  assert.equal(r.ok, false);
  assert.deepEqual(finals, []);
});

test("stop / denial / unsupported browser states recover", () => {
  const errors = [];
  const a = adapter.createVoiceInputAdapter({ onError: (c) => errors.push(c) });
  a.start();
  a.stop("user-denied");
  assert.equal(a.getState(), S.STOPPED);
  assert.equal(a.feedInterim("x").ok, false);
  const b = adapter.createVoiceInputAdapter({ onError: (c) => errors.push(c) });
  b.error("speech-recognition-unsupported");
  assert.equal(b.getState(), S.ERROR);
  assert.ok(errors.includes("speech-recognition-unsupported"));
});

test("appendToInput appends and preserves user edits", () => {
  const input = makeInput();
  const a = adapter.createVoiceInputAdapter({ input });
  input.value = "typed by user";
  const next = a.appendToInput("transcribed text");
  assert.equal(next, "typed by user transcribed text");
  assert.equal(input.value, "typed by user transcribed text");
  input.value = "user changed it";
  assert.equal(input.value, "user changed it");
});

test("appendToInput replace mode", () => {
  const input = makeInput();
  input.value = "old";
  const a = adapter.createVoiceInputAdapter({ input });
  a.appendToInput("new text", "replace");
  assert.equal(input.value, "new text");
});

test("appendToInput supports {getValue, setValue} handle", () => {
  let v = "start";
  const handle = { getValue() { return v; }, setValue(x) { v = x; } };
  const a = adapter.createVoiceInputAdapter({ input: handle });
  a.appendToInput("final");
  assert.equal(v, "start final");
});

test("interim never mutates input until commitFinal", () => {
  const input = makeInput();
  const a = adapter.createVoiceInputAdapter({ input });
  a.start();
  a.feedInterim("partial");
  assert.equal(input.value, "");
  a.feedInterim("partial more");
  assert.equal(input.value, "");
});

test("late final on stale session is dropped", () => {
  const finals = [];
  const a = adapter.createVoiceInputAdapter({
    generation: 1, sessionToken: "sess-A",
    onFinalCandidate: (t) => finals.push(t),
  });
  a.start();
  const late = a.commitFinal({ text: "old tail", sessionToken: "sess-Z" });
  assert.equal(late.ok, false);
  assert.equal(late.reason, "stale-session");
  assert.deepEqual(finals, []);
});

test("no network/provider primitives in module", () => {
  const fs = require("node:fs");
  const path = require("node:path");
  const src = fs.readFileSync(path.resolve(__dirname, "../static/voice-stt-input.js"), "utf8");
  for (const token of ["fetch(", "XMLHttpRequest", "WebSocket", "SpeechRecognition"]) {
    assert.ok(!src.includes(token), "primitive present: " + token);
  }
  assert.ok(!/require\(["']https?:/.test(src));
});

test("idle/stop/error state rejects interim and final", () => {
  const finals = [];
  const a = adapter.createVoiceInputAdapter({
    generation: 1, sessionToken: "sess-A",
    onFinalCandidate: (t) => finals.push(t),
  });
  assert.deepEqual(a.feedInterim("hello"), { ok: false, reason: "not-listening" });
  assert.deepEqual(a.commitFinal({ text: "x" }), { ok: false, reason: "not-listening" });
  a.start();
  a.stop();
  assert.deepEqual(a.feedInterim("hello"), { ok: false, reason: "stopped" });
  assert.deepEqual(a.commitFinal({ text: "x" }), { ok: false, reason: "stopped" });
});

test("final then interim starts next utterance (same run)", () => {
  const finals = [];
  const previews = [];
  const a = adapter.createVoiceInputAdapter({
    generation: 1, sessionToken: "sess-A",
    onFinalCandidate: (t) => finals.push(t),
    onInterim: (t) => previews.push(t),
  });
  a.start();
  a.feedInterim("hello");
  assert.equal(a.commitFinal({ text: "hello", utteranceId: "u1" }).ok, true);
  assert.equal(a.getState(), "final");
  const r = a.feedInterim("world");
  assert.equal(r.ok, true);
  assert.equal(a.getState(), "interim");
  assert.equal(a.commitFinal({ text: "world", utteranceId: "u2" }).ok, true);
  assert.deepEqual(finals, ["hello", "world"]);
});

test("stale interim discarded after new session", () => {
  const a = adapter.createVoiceInputAdapter({
    generation: 1, sessionToken: "sess-A",
  });
  a.start();
  const old = a;
  const r0 = a.feedInterim("hello", { generation: 1, sessionToken: "sess-A" });
  assert.equal(r0.ok, true);
  const bad = a.feedInterim("stale", { generation: 2, sessionToken: "sess-A" });
  assert.equal(bad.ok, false);
  assert.equal(bad.reason, "stale-generation");
});

test("repeat start while active refuses reset", () => {
  const a = adapter.createVoiceInputAdapter({ generation: 1, sessionToken: "sess-A" });
  a.start();
  a.commitFinal({ text: "first", utteranceId: "u1" });
  a.feedInterim("second");
  const before = a.getAcceptedCount();
  const second = a.start();
  assert.equal(second, false);
  assert.equal(a.getAcceptedCount(), before);
});

test("error state ignores late callbacks", () => {
  const finals = [];
  const a = adapter.createVoiceInputAdapter({
    generation: 1, sessionToken: "sess-A",
    onFinalCandidate: (t) => finals.push(t),
  });
  a.start();
  a.error("boom");
  assert.equal(a.commitFinal({ text: "late", utteranceId: "u2" }).ok, false);
  assert.equal(a.feedInterim("late").ok, false);
  assert.deepEqual(finals, []);
});

test("appendToInput no-op after invalidate", () => {
  const el = { value: "" };
  const a = adapter.createVoiceInputAdapter({
    generation: 1, sessionToken: "sess-A",
    input: el,
  });
  a.start();
  assert.equal(a.appendToInput("hello"), "hello");
  a.invalidate("new-conversation");
  assert.equal(a.appendToInput("late"), null);
  assert.equal(el.value, "hello");
});

test("appendToInput no-op after stop", () => {
  const el = { value: "" };
  const a = adapter.createVoiceInputAdapter({
    generation: 1, sessionToken: "sess-A",
    input: el,
  });
  a.start();
  a.stop("done");
  assert.equal(a.appendToInput("late"), null);
  assert.equal(el.value, "");
});

test("CommonJS require works and STATES complete", () => {
  assert.equal(typeof adapter.createVoiceInputAdapter, "function");
  assert.equal(typeof adapter.STATES, "object");
  assert.equal(adapter.STATES.IDLE, "idle");
  assert.equal(adapter.STATES.FINAL, "final");
  const keys = Object.keys(adapter.STATES).sort();
  assert.deepEqual(keys, ["ERROR", "FINAL", "IDLE", "INTERIM", "LISTENING", "STOPPED"]);
});
