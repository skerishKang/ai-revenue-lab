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

test("duplicate text dropped even with different ids", () => {
  const finals = [];
  const a = adapter.createVoiceInputAdapter({
    generation: 1, sessionToken: "sess-A",
    onFinalCandidate: (t) => finals.push(t),
  });
  a.start();
  a.commitFinal({ text: "same words", utteranceId: "u1" });
  const dup = a.commitFinal({ text: "  SAME   WORDS ", utteranceId: "u2" });
  assert.equal(dup.ok, false);
  assert.equal(dup.reason, "duplicate-text");
  assert.deepEqual(finals, ["same words"]);
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

test("CommonJS require works and STATES complete", () => {
  assert.equal(typeof adapter.createVoiceInputAdapter, "function");
  assert.equal(typeof adapter.STATES, "object");
  assert.equal(adapter.STATES.IDLE, "idle");
  assert.equal(adapter.STATES.FINAL, "final");
  const keys = Object.keys(adapter.STATES).sort();
  assert.deepEqual(keys, ["ERROR", "FINAL", "IDLE", "INTERIM", "LISTENING", "STOPPED"]);
});
