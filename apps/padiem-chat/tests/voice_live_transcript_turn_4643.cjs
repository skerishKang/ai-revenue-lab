"use strict";
/**
 * Ported Global Classroom #87 gates for the shared voice turn authority.
 *
 * Source of every case below:
 *   skerishKang/global-classroom main ffa27e6a93605614031fed314ef33571c85b8f18
 *   tests/unit/interviewTranscriptionTurn87.test.ts
 *   tests/unit/interviewSessionRotation87.test.ts  (the pure handoff-buffer and
 *   tail-flush describe blocks; the React-hook blocks need the Gemini Live
 *   session and are listed as not-ported in the PR)
 *
 * Titles are kept in the original's words so a drift between the two repos is
 * visible as a missing case rather than a renamed one.
 */
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const turn = require("../static/voice-live-transcript-turn.js");
const STATIC = path.resolve(__dirname, "../static");

const {
  LIVE_TRANSCRIBE_MODEL,
  LIVE_VAD_SILENCE_MS,
  LIVE_SESSION_ROTATE_MS,
  LIVE_AUDIO_HANDOFF_FRAMES,
  LIVE_TAIL_FLUSH_DRAIN_MS,
  GROQ_MIN_CHUNK_MS,
  GROQ_SILENCE_CUT_MS,
  GROQ_MAX_CHUNK_MS,
  TRANSCRIPT_TURN_STALL_MS,
  mergeLiveTranscriptChunk,
  createAudioHandoffBuffer,
  flushLiveTranscriptTail,
  createTranscriptTurnBuffer,
  shouldCutGroqChunk,
  shouldFlushStalledTurn,
  startSpeechSilenceProbe,
  resolveRecognitionLanguage,
} = turn;

/* ---------------- tests/unit/interviewTranscriptionTurn87.test.ts ---------------- */

test("delta and cumulative hypotheses merge without duplication", () => {
  assert.equal(mergeLiveTranscriptChunk("", "Could you tell me"), "Could you tell me");
  assert.equal(mergeLiveTranscriptChunk("Could you tell me", " which city"),
    "Could you tell me which city");
  // Cumulative hypothesis: the replay must replace, not append.
  assert.equal(mergeLiveTranscriptChunk("Could you tell me", "Could you tell me which city"),
    "Could you tell me which city");
  // Replayed delta: the duplicate must not be appended twice.
  assert.equal(mergeLiveTranscriptChunk("Could you tell me", "me"), "Could you tell me");
  assert.equal(mergeLiveTranscriptChunk("", ""), "");
});

test("two chunks of one Live turn produce exactly one final row", () => {
  const buffer = createTranscriptTurnBuffer();

  buffer.merge("Could you tell me");
  buffer.merge(" which city you grew up in?");
  // Merging chunks emits nothing: only the turn boundary creates a row.
  assert.equal(buffer.pending, "Could you tell me which city you grew up in?");
  assert.equal(buffer.finishTurn(), "Could you tell me which city you grew up in?");
  // A repeated boundary must not duplicate the row.
  assert.equal(buffer.finishTurn(), null);

  buffer.merge("Taste the refreshing");
  assert.equal(buffer.finishTurn(), "Taste the refreshing");
  assert.equal(buffer.finishTurn(), null);
});

test("a turn whose boundary never arrives is flushed instead of held forever", () => {
  assert.equal(shouldFlushStalledTurn({ hasPending: false, sinceLastChunkMs: 60000 }), false);
  assert.equal(
    shouldFlushStalledTurn({ hasPending: true, sinceLastChunkMs: TRANSCRIPT_TURN_STALL_MS - 1 }),
    false,
  );
  assert.equal(
    shouldFlushStalledTurn({ hasPending: true, sinceLastChunkMs: TRANSCRIPT_TURN_STALL_MS }),
    true,
  );
  // The stall window must never preempt a normal turn boundary.
  assert.ok(TRANSCRIPT_TURN_STALL_MS > LIVE_VAD_SILENCE_MS);
});

test("an empty or whitespace-only turn never creates a row", () => {
  const buffer = createTranscriptTurnBuffer();
  assert.equal(buffer.finishTurn(), null);
  buffer.merge("   ");
  assert.equal(buffer.finishTurn(), null);
});

test("the activity-detection window no longer ends a turn on a thinking pause", () => {
  // Issue #87 asked for a 1200-1600ms trial window instead of 650ms.
  assert.ok(LIVE_VAD_SILENCE_MS >= 1200 && LIVE_VAD_SILENCE_MS <= 1600);
});

test("the Live session rotates before the provider session limit", () => {
  assert.ok(LIVE_SESSION_ROTATE_MS < 10 * 60000);
  assert.ok(LIVE_SESSION_ROTATE_MS > 8 * 60000);
});

test("the Groq fallback cuts at a speech pause, not at a fixed clock", () => {
  const cutAt = (elapsedMs, silenceMs) => shouldCutGroqChunk({ elapsedMs, silenceMs });

  // The previous fixed 5500ms stop cut mid-sentence while speech continued.
  assert.equal(cutAt(5500, 0), false);
  assert.equal(cutAt(GROQ_MIN_CHUNK_MS - 1, 60000), false);
  assert.equal(cutAt(GROQ_MIN_CHUNK_MS, GROQ_SILENCE_CUT_MS - 1), false);
  assert.equal(cutAt(GROQ_MIN_CHUNK_MS, GROQ_SILENCE_CUT_MS), true);
  // A monologue that never pauses is still bounded.
  assert.equal(cutAt(GROQ_MAX_CHUNK_MS, 0), true);
});

test("the browser fallback language follows the hint, then the observed source", () => {
  assert.equal(
    resolveRecognitionLanguage({ hint: "en", observed: "ko", navigatorLanguage: "ko-KR" }),
    "en",
  );
  assert.equal(resolveRecognitionLanguage({ observed: "en", navigatorLanguage: "ko-KR" }), "en");
  assert.equal(resolveRecognitionLanguage({ navigatorLanguage: "en-US" }), "en-US");
  // `auto` is not a usable SpeechRecognition language tag.
  assert.equal(resolveRecognitionLanguage({ hint: "auto", navigatorLanguage: "ko-KR" }), "ko-KR");
});

test("the silence probe is inert without a browser AudioContext", () => {
  assert.equal(startSpeechSilenceProbe({}), null);
});

test("the transcriber model id is the one the original dispatches", () => {
  assert.equal(LIVE_TRANSCRIBE_MODEL, "gemini-3.5-transcribe-live");
});

/* ---------------- tests/unit/interviewSessionRotation87.test.ts ---------------- */

test("#87 handoff buffer semantics: capturing is off until a rotation starts, and off again after release", () => {
  const buffer = createAudioHandoffBuffer(3);
  assert.equal(buffer.capturing, false);
  assert.equal(buffer.push(1), false); // not capturing: caller keeps sending normally
  assert.equal(buffer.size, 0);

  buffer.start();
  assert.equal(buffer.capturing, true);
  assert.equal(buffer.push(1), true);
  assert.deepEqual(buffer.release(), [1]);
  assert.equal(buffer.capturing, false);
  assert.equal(buffer.push(2), false);
});

test("#87 handoff buffer semantics: release preserves arrival order and can only be drained once", () => {
  const buffer = createAudioHandoffBuffer(5);
  buffer.start();
  [1, 2, 3].forEach((frame) => buffer.push(frame));
  assert.deepEqual(buffer.release(), [1, 2, 3]);
  assert.deepEqual(buffer.release(), []);
});

test("#87 handoff buffer semantics: overflow is counted, never silent", () => {
  const buffer = createAudioHandoffBuffer(2);
  buffer.start();
  assert.equal(buffer.push(1), true);
  assert.equal(buffer.push(2), true);
  assert.equal(buffer.push(3), false);
  assert.equal(buffer.droppedFrames, 1);
  assert.deepEqual(buffer.release(), [1, 2]);
  // A bounded buffer must not grow past its cap over repeated rotations.
  assert.equal(buffer.size, 0);
});

test("#87 handoff buffer semantics: reset abandons captured frames without emitting them", () => {
  const buffer = createAudioHandoffBuffer(4);
  buffer.start();
  buffer.push(1);
  buffer.reset();
  assert.equal(buffer.size, 0);
  assert.equal(buffer.capturing, false);
  assert.deepEqual(buffer.release(), []);
});

test("#87 handoff buffer semantics: the cap covers several seconds of microphone audio", () => {
  // 2048 samples at 16kHz is 128ms per frame, so 40 frames is ~5.1s.
  assert.ok(LIVE_AUDIO_HANDOFF_FRAMES * 128 >= 5000);
  assert.ok(LIVE_AUDIO_HANDOFF_FRAMES * 128 < LIVE_SESSION_ROTATE_MS);
});

/** A clock the test drives, so a drain deadline is assertable without waiting. */
function manualTimers() {
  const queued = [];
  return {
    queued,
    setTimer: (callback, ms) => {
      const entry = { delay: ms, run: callback };
      queued.push(entry);
      return entry;
    },
    clearTimer: (handle) => {
      const index = queued.indexOf(handle);
      if (index >= 0) queued.splice(index, 1);
    },
    fireAll: () => queued.splice(0).forEach((entry) => entry.run()),
  };
}

function fakeSession(options) {
  const opts = options || {};
  const state = { signals: [], closes: 0 };
  return {
    state,
    session: {
      sendRealtimeInput: (signal) => {
        if (opts.throws) throw new Error("socket already gone");
        state.signals.push(signal);
      },
      close: () => { state.closes += 1; },
    },
  };
}

test("#87 tail flush mechanics: the outgoing session is told the stream ended, and only that", () => {
  const timers = manualTimers();
  const probe = fakeSession();
  flushLiveTranscriptTail(probe.session, {
    onSettled: () => {},
    setTimer: timers.setTimer,
    clearTimer: timers.clearTimer,
  });
  assert.deepEqual(probe.state.signals, [{ audioStreamEnd: true }]);
  assert.equal(probe.state.closes, 0);
});

test("#87 tail flush mechanics: deltas accumulate and only a turn boundary settles", () => {
  const timers = manualTimers();
  const probe = fakeSession();
  const settled = [];
  const flush = flushLiveTranscriptTail(probe.session, {
    onSettled: (text) => settled.push(text),
    setTimer: timers.setTimer,
    clearTimer: timers.clearTimer,
  });

  // An empty, unterminated hypothesis carries nothing.
  assert.equal(flush.accept({ text: "", finished: false }), false);
  assert.equal(flush.accept({ text: "   ", finished: false }), false);
  assert.equal(probe.state.closes, 0);

  // An unfinished delta must not close the session: the sentence is not over.
  assert.equal(flush.accept({ text: "and only after that did I ", finished: false }), true);
  assert.deepEqual(settled, []);
  assert.equal(probe.state.closes, 0);

  assert.equal(
    flush.accept({ text: "start investigating the root cause.", finished: true }), true);
  // Once settled, nothing else is consumed.
  assert.equal(
    flush.accept({ text: "start investigating the root cause.", finished: true }), false);

  assert.deepEqual(settled, ["and only after that did I start investigating the root cause."]);
  assert.equal(probe.state.closes, 1);
  assert.equal(timers.queued.length, 0);
});

test("#87 tail flush mechanics: a cumulative hypothesis replaces the prefix instead of duplicating it", () => {
  const timers = manualTimers();
  const probe = fakeSession();
  const settled = [];
  const flush = flushLiveTranscriptTail(probe.session, {
    onSettled: (text) => settled.push(text),
    setTimer: timers.setTimer,
    clearTimer: timers.clearTimer,
  });
  flush.accept({ text: "under a very tight", finished: false });
  flush.accept({ text: "under a very tight deadline.", finished: true });
  assert.deepEqual(settled, ["under a very tight deadline."]);
});

test("#87 tail flush mechanics: a boundary that arrives before any text cannot settle an empty tail", () => {
  const timers = manualTimers();
  const probe = fakeSession();
  const settled = [];
  const flush = flushLiveTranscriptTail(probe.session, {
    onSettled: (text) => settled.push(text),
    setTimer: timers.setTimer,
    clearTimer: timers.clearTimer,
  });
  assert.equal(flush.accept({ finished: true }), false);
  assert.equal(probe.state.closes, 0);
  assert.equal(flush.accept({ text: "root cause.", finished: true }), true);
  assert.deepEqual(settled, ["root cause."]);
});

test("#87 tail flush mechanics: an unfinished tail is still committed on the deadline", () => {
  const timers = manualTimers();
  const probe = fakeSession();
  const settled = [];
  flushLiveTranscriptTail(probe.session, {
    onSettled: (text) => settled.push(text),
    setTimer: timers.setTimer,
    clearTimer: timers.clearTimer,
  }).accept({ text: "a tail that never finalises", finished: false });
  assert.deepEqual(settled, []);
  timers.fireAll();
  assert.deepEqual(settled, ["a tail that never finalises"]);
  assert.equal(probe.state.closes, 1);
});

test("#87 tail flush mechanics: a session that never answers is closed on the bounded deadline", () => {
  const timers = manualTimers();
  const probe = fakeSession();
  const settled = [];
  flushLiveTranscriptTail(probe.session, {
    onSettled: (text) => settled.push(text),
    setTimer: timers.setTimer,
    clearTimer: timers.clearTimer,
  });
  assert.deepEqual(timers.queued.map((entry) => entry.delay), [LIVE_TAIL_FLUSH_DRAIN_MS]);
  timers.fireAll();
  // `null` still reports: teardown must commit what the session already said.
  assert.deepEqual(settled, [null]);
  assert.equal(probe.state.closes, 1);
  timers.fireAll();
  assert.equal(probe.state.closes, 1);
});

test("#87 tail flush mechanics: cancelling the wait keeps the words that were already captured", () => {
  const timers = manualTimers();
  const probe = fakeSession();
  const settled = [];
  const flush = flushLiveTranscriptTail(probe.session, {
    onSettled: (text) => settled.push(text),
    setTimer: timers.setTimer,
    clearTimer: timers.clearTimer,
  });
  flush.accept({ text: "half a sentence", finished: false });
  flush.cancel();
  assert.deepEqual(settled, ["half a sentence"]);
  assert.equal(probe.state.closes, 1);
  assert.equal(flush.accept({ text: "late", finished: true }), false);
  assert.equal(probe.state.closes, 1);
});

test("#87 tail flush mechanics: a session that cannot be signalled is closed instead of left open", () => {
  const timers = manualTimers();
  const probe = fakeSession({ throws: true });
  const settled = [];
  flushLiveTranscriptTail(probe.session, {
    onSettled: (text) => settled.push(text),
    setTimer: timers.setTimer,
    clearTimer: timers.clearTimer,
  });
  assert.deepEqual(settled, [null]);
  assert.equal(probe.state.closes, 1);
  assert.equal(timers.queued.length, 0);
});

test("#87 tail flush mechanics: nothing is armed when there is no session to flush", () => {
  const flush = flushLiveTranscriptTail(null, {
    onSettled: () => { throw new Error("a null session must not report"); },
  });
  assert.equal(flush.armed, false);
  assert.equal(flush.accept({ text: "x", finished: true }), false);
  flush.cancel();
});

test("#87 tail flush mechanics: an absent chunk is ignored, not thrown at", () => {
  // The original reads chunk fields through optional chaining; a callback that
  // fires with no payload must cost the drain nothing.
  const timers = manualTimers();
  const probe = fakeSession();
  const settled = [];
  const flush = flushLiveTranscriptTail(probe.session, {
    onSettled: (text) => settled.push(text),
    setTimer: timers.setTimer,
    clearTimer: timers.clearTimer,
  });
  assert.equal(flush.accept(null), false);
  assert.equal(flush.accept(undefined), false);
  assert.equal(probe.state.closes, 0);
  assert.equal(flush.accept({ text: "root cause.", finished: true }), true);
  assert.deepEqual(settled, ["root cause."]);
});

test("#87 tail flush mechanics: a session whose signal method is unusable is still closed", () => {
  const timers = manualTimers();
  const settled = [];
  let closes = 0;
  flushLiveTranscriptTail({ sendRealtimeInput: true, close: () => { closes += 1; } }, {
    onSettled: (text) => settled.push(text),
    setTimer: timers.setTimer,
    clearTimer: timers.clearTimer,
  });
  assert.equal(closes, 1, "a session that cannot accept the end signal must not stay open");
  assert.deepEqual(settled, [null]);
  assert.equal(timers.queued.length, 0);
});

test("#87 tail flush mechanics: the drain window covers the measured provider flush latency but stays short", () => {
  // Live provider, one 28.7s utterance: the tail chunk arrived 261ms after
  // `audioStreamEnd`. Teardown must not be pinned by a dead socket.
  assert.ok(LIVE_TAIL_FLUSH_DRAIN_MS >= 4 * 261);
  assert.ok(LIVE_TAIL_FLUSH_DRAIN_MS < 2000);
});

/* ---------------- PADIEM-side contract for the ported authority ---------------- */

test("the Chat/Claw adapter reads the turn logic from this authority instead of restating it", () => {
  const adapterApi = require("../static/voice-stt-input.js");

  // One object, not a copy: the adapter's buffer must be the authority's factory.
  assert.equal(adapterApi.authority, turn);
  assert.equal(adapterApi.createTranscriptTurnBuffer, createTranscriptTurnBuffer);
  assert.equal(adapterApi.constants.LIVE_VAD_SILENCE_MS, LIVE_VAD_SILENCE_MS);
  assert.equal(adapterApi.constants.TRANSCRIPT_TURN_STALL_MS, TRANSCRIPT_TURN_STALL_MS);

  // The adapter still owns the PADIEM-specific seam: one final per utterance id.
  const finals = [];
  const run = adapterApi.createVoiceInputAdapter({
    generation: 1, sessionToken: "s", onFinalCandidate: (text) => finals.push(text),
  });
  run.start();
  run.feedInterim("Then I rolled the service back", { generation: 1 });
  assert.equal(run.commitFinal({ generation: 1, sessionToken: "s", utteranceId: "u1" }).ok, true);
  assert.equal(run.commitFinal({ text: "x", utteranceId: "u1", generation: 1 }).reason,
    "duplicate-utterance");
  assert.deepEqual(finals, ["Then I rolled the service back"]);
});

test("the shipped page gives the adapter the authority through the browser global", () => {
  // index.html loads these two as plain <script> tags, so the adapter must find
  // the authority on the global object. The CommonJS require() path used by every
  // other case here would also pass if the tag order were wrong, so this case
  // runs the real files as scripts in a context with no require and no module.
  const vm = require("node:vm");
  const sandbox = { console: console };
  sandbox.globalThis = sandbox;
  const context = vm.createContext(sandbox);
  for (const file of ["voice-live-transcript-turn.js", "voice-stt-input.js"]) {
    const script = new vm.Script(fs.readFileSync(path.join(STATIC, file), "utf8"), { filename: file });
    script.runInContext(context);
  }
  assert.equal(typeof sandbox.PadiemVoiceLiveTranscriptTurn, "object", "authority never reached the global");
  assert.equal(typeof sandbox.require, "undefined", "the sandbox must not offer require");
  assert.equal(typeof sandbox.PadiemVoiceSttInput, "object", "the adapter did not load after the authority");
  // Same object through the global, not a second instance created by require().
  assert.equal(sandbox.PadiemVoiceSttInput.authority, sandbox.PadiemVoiceLiveTranscriptTurn);

  // And the adapter still produces one final row for a two-chunk turn.
  const finals = [];
  const run = sandbox.PadiemVoiceSttInput.createVoiceInputAdapter({
    generation: 7, sessionToken: "page-run", onFinalCandidate: (text) => finals.push(text),
  });
  run.start();
  run.feedInterim("Could you tell me", { generation: 7 });
  run.feedInterim(" which city you grew up in?", { generation: 7 });
  assert.equal(finals.length, 0, "an open turn must not emit a row");
  run.commitFinal({ generation: 7, sessionToken: "page-run", utteranceId: "u-1" });
  assert.deepEqual(finals, ["Could you tell me which city you grew up in?"]);
  run.commitFinal({ generation: 7, sessionToken: "page-run", utteranceId: "u-1" });
  assert.equal(finals.length, 1, "a repeated boundary must not duplicate the row");
});

test("the pre-#87 transcription behaviour is absent from the shipped voice modules", () => {
  const forbidden = [
    "silenceDurationMs: 650",
    "recognition.lang = navigator.language || 'ko-KR'",
    "}, 5500);",
  ];
  const files = fs.readdirSync(STATIC).filter((name) => name.startsWith("voice-") && name.endsWith(".js"));
  assert.ok(files.length >= 4, "the shipped voice modules must be inspected");
  for (const name of files) {
    const source = fs.readFileSync(path.join(STATIC, name), "utf8");
    for (const literal of forbidden) {
      assert.ok(!source.includes(literal), `${name} reintroduced the pre-#87 behaviour: ${literal}`);
    }
  }
});

test("no new copy of the #87 numeric contract appears outside the authority", () => {
  // A second numeric copy is how the two transcription paths drifted apart before
  // #87. The remaining duplicates are listed with the file that still owns them:
  // the list may only shrink, and shrinking it is what "removed the duplicate"
  // means. Any definition that is not the authority and not listed here fails.
  const PENDING_REMOVAL = new Set([
    // voice-stt-wiring.js re-declares the Groq chunk boundary and hand-rolls its
    // own silence gate instead of shouldCutGroqChunk()/startSpeechSilenceProbe().
    // It is owned by the open #4698 lane, so it is reported, not edited in parallel.
    "voice-stt-wiring.js:GROQ_MIN_CHUNK_MS",
    "voice-stt-wiring.js:GROQ_SILENCE_CUT_MS",
    "voice-stt-wiring.js:GROQ_MAX_CHUNK_MS",
  ]);
  const AUTHORITY = "voice-live-transcript-turn.js";
  const KEYS = ["LIVE_VAD_SILENCE_MS", "LIVE_SESSION_ROTATE_MS", "GROQ_MIN_CHUNK_MS",
    "GROQ_SILENCE_CUT_MS", "GROQ_MAX_CHUNK_MS", "TRANSCRIPT_TURN_STALL_MS",
    "LIVE_TAIL_FLUSH_DRAIN_MS", "LIVE_AUDIO_HANDOFF_FRAMES", "LIVE_TRANSCRIBE_MODEL"];

  const duplicates = [];
  const found = [];
  for (const name of fs.readdirSync(STATIC).filter((f) => f.startsWith("voice-") && f.endsWith(".js"))) {
    const source = fs.readFileSync(path.join(STATIC, name), "utf8");
    for (const key of KEYS) {
      if (!new RegExp(`(const|var|let) ${key} = [0-9'"]`).test(source)) continue;
      found.push(`${name}:${key}`);
      if (name !== AUTHORITY && !PENDING_REMOVAL.has(`${name}:${key}`)) duplicates.push(`${name}:${key}`);
    }
  }
  assert.deepEqual(duplicates, [], `unlisted duplicate of the shared voice authority: ${duplicates.join(", ")}`);
  // The authority must actually define what the gate claims it owns, or the gate
  // above would pass by deleting the original instead of the copies.
  const authorityKeys = found.filter((entry) => entry.startsWith(AUTHORITY + ":"));
  assert.deepEqual(authorityKeys.sort(), [
    "voice-live-transcript-turn.js:GROQ_MAX_CHUNK_MS",
    "voice-live-transcript-turn.js:GROQ_MIN_CHUNK_MS",
    "voice-live-transcript-turn.js:GROQ_SILENCE_CUT_MS",
    "voice-live-transcript-turn.js:LIVE_AUDIO_HANDOFF_FRAMES",
    "voice-live-transcript-turn.js:LIVE_SESSION_ROTATE_MS",
    "voice-live-transcript-turn.js:LIVE_TAIL_FLUSH_DRAIN_MS",
    "voice-live-transcript-turn.js:LIVE_TRANSCRIBE_MODEL",
    "voice-live-transcript-turn.js:LIVE_VAD_SILENCE_MS",
    "voice-live-transcript-turn.js:TRANSCRIPT_TURN_STALL_MS",
  ], "the authority lost a contract constant");
});
