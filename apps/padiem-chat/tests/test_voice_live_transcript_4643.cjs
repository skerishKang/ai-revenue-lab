"use strict";
/**
 * #4643 live (real-time) transcription engine contract.
 *
 * The engine is a port of the proven Global Classroom implementation, so
 * these tests assert the ported behaviour rather than a new algorithm:
 *
 * - the reviewed constants are the Global Classroom ones;
 * - the turn buffer and the merge rule are the SHARED adapter's, so the
 *   engine and the composer cannot drift apart;
 * - one Live turn is one committed utterance;
 * - a session rotation keeps the microphone frames captured during the swap
 *   and replays them into the incoming session;
 * - a retired session is drained with `audioStreamEnd`, so its tail is not
 *   lost;
 * - a stalled turn is flushed instead of being held forever;
 * - the browser never holds a long-lived provider key: the only credential
 *   is the single-use token the same-origin route returned.
 */
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const live = require("../static/voice-live-transcript.js");
const adapter = require("../static/voice-stt-input.js");

const STATIC = path.resolve(__dirname, "../static");

/* ------------------------------------------------------------------ */
/* Fakes                                                               */
/* ------------------------------------------------------------------ */

function makeSocketClass(sockets) {
  return class FakeWebSocket {
    constructor(url) {
      this.url = url;
      this.readyState = 0;
      this.sent = [];
      sockets.push(this);
      setTimeout(() => {
        this.readyState = 1;
        if (this.onopen) this.onopen();
      }, 0);
    }
    send(data) { this.sent.push(data); }
    close() { this.readyState = 3; if (this.onclose) this.onclose({ reason: "closed" }); }
    message(payload) {
      if (this.onmessage) this.onmessage({ data: JSON.stringify(payload) });
    }
  };
}

function makeAudioEnv(frames) {
  const source = { connect() {}, disconnect() {} };
  const gain = { gain: { value: 1 }, connect() {}, disconnect() {} };
  const processor = {
    onaudioprocess: null,
    connect() {},
    disconnect() {},
  };
  const context = {
    sampleRate: 0,
    destination: {},
    resume: async () => {},
    close: async () => {},
    createMediaStreamSource: () => source,
    createScriptProcessor: () => processor,
    createGain: () => gain,
  };
  return {
    context,
    processor,
    emit: function (samples) {
      if (!processor.onaudioprocess) return;
      processor.onaudioprocess({
        inputBuffer: { getChannelData: () => Float32Array.from(samples) },
      });
    },
  };
}

function makeEnv(options) {
  const opts = options || {};
  const sockets = [];
  const audio = makeAudioEnv();
  const tracks = [];
  const stream = { getTracks: () => tracks };
  const fetches = [];
  const win = {
    setTimeout,
    clearTimeout,
    AudioContext: function () { return audio.context; },
    WebSocket: makeSocketClass(sockets),
  };
  const fetchImpl = async function (path, init) {
    fetches.push({ path: path, init: init });
    if (opts.tokenDelayMs && fetches.length > 1) {
      await new Promise((resolve) => setTimeout(resolve, opts.tokenDelayMs));
    }
    if (opts.tokenStatus && opts.tokenStatus !== 200) {
      return { ok: false, status: opts.tokenStatus, json: async () => ({}) };
    }
    return {
      ok: true,
      status: 200,
      json: async () => ({
        ok: true,
        token: opts.token || "auth_tokens/test-token",
        expireTime: "2026-10-20T00:30:00Z",
        session: {
          model: "gemini-3.5-transcribe-live",
          vad_silence_ms: 1300,
          rotate_after_ms: opts.rotateAfterMs || 560000,
          response_modalities: ["TEXT"],
          input_audio_transcription_mode: "VERBATIM",
        },
      }),
    };
  };
  return { win, sockets, audio, stream, tracks, fetches, fetchImpl };
}

function makeFactory(env, extra) {
  // The engine keeps a long rotation timer and a tail-drain timer alive, so
  // the offline harness unrefs them instead of holding the process open.
  const setTimer = (cb, ms) => {
    const handle = setTimeout(cb, ms);
    if (handle && typeof handle.unref === "function") handle.unref();
    return handle;
  };
  return live.createRecognizerFactory(Object.assign({
    win: env.win,
    fetchImpl: env.fetchImpl,
    mediaDevices: { getUserMedia: async () => env.stream },
    liveTokenPath: "/api/voice/live-token",
    setTimeout: setTimer,
    clearTimeout: clearTimeout,
  }, extra || {}));
}

/* ------------------------------------------------------------------ */
/* Ported constants and helpers                                        */
/* ------------------------------------------------------------------ */

test("the reviewed Global Classroom constants are the ones in use", () => {
  assert.equal(live.LIVE_TRANSCRIBE_MODEL, "gemini-3.5-transcribe-live");
  assert.equal(live.LIVE_VAD_SILENCE_MS, 1300);
  assert.equal(live.LIVE_SESSION_ROTATE_MS, 9 * 60_000 + 20_000);
  assert.equal(live.LIVE_AUDIO_HANDOFF_FRAMES, 40);
  assert.equal(live.LIVE_TAIL_FLUSH_DRAIN_MS, 1200);
  assert.equal(live.TRANSCRIPT_TURN_STALL_MS, 2500);
  assert.equal(live.LIVE_PCM_MIME, "audio/pcm;rate=16000");
  assert.equal(live.LIVE_SAMPLE_RATE, 16000);
  assert.equal(live.LIVE_FRAME_SAMPLES, 2048);
});

test("the engine and the composer share one turn buffer authority", () => {
  const turn = live.createTranscriptTurnBuffer();
  turn.merge("Could you tell me");
  turn.merge(" which city");
  assert.equal(turn.pending, "Could you tell me which city");
  assert.equal(turn.finishTurn(), "Could you tell me which city");
  assert.equal(turn.finishTurn(), null);
  // The very same object the reviewed adapter produces.
  const shared = adapter.createTranscriptTurnBuffer();
  shared.merge("a");
  assert.equal(live.createTranscriptTurnBuffer().constructor.name, shared.constructor.name);
});

test("the merge rule accepts cumulative and delta hypotheses without duplication", () => {
  assert.equal(live.mergeLiveTranscriptChunk("", "hello"), "hello");
  assert.equal(live.mergeLiveTranscriptChunk("hel", "hello"), "hello");
  assert.equal(live.mergeLiveTranscriptChunk("hello", "lo"), "hello");
  assert.equal(live.mergeLiveTranscriptChunk("hi", " there"), "hi there");
});

test("the stall rule never preempts a normal turn boundary", () => {
  assert.equal(live.shouldFlushStalledTurn({ hasPending: false, sinceLastChunkMs: 60000 }), false);
  assert.equal(live.shouldFlushStalledTurn({ hasPending: true, sinceLastChunkMs: 2499 }), false);
  assert.equal(live.shouldFlushStalledTurn({ hasPending: true, sinceLastChunkMs: 2500 }), true);
  assert.ok(live.TRANSCRIPT_TURN_STALL_MS > live.LIVE_VAD_SILENCE_MS);
});

test("the audio handoff buffer is bounded and observable", () => {
  const buffer = live.createAudioHandoffBuffer(2);
  assert.equal(buffer.capturing, false);
  assert.equal(buffer.push({ a: 1 }), false, "nothing is captured before the swap starts");
  buffer.start();
  assert.equal(buffer.push({ a: 1 }), true);
  assert.equal(buffer.push({ a: 2 }), true);
  assert.equal(buffer.push({ a: 3 }), false, "the cap rejects the frame");
  assert.equal(buffer.droppedFrames, 1);
  assert.equal(buffer.size, 2);
  const frames = buffer.release();
  assert.equal(frames.length, 2);
  assert.deepEqual(frames.map((f) => f.a), [1, 2]);
  assert.equal(buffer.capturing, false);
  buffer.start();
  buffer.push({ a: 9 });
  buffer.reset();
  assert.equal(buffer.size, 0);
});

test("the tail flush asks the session to finalise and waits for a boundary", () => {
  const sent = [];
  let closed = false;
  const session = {
    sendRealtimeInput: (input) => sent.push(input),
    close: () => { closed = true; },
  };
  const settled = [];
  const flush = live.flushLiveTranscriptTail(session, {
    onSettled: (text) => settled.push(text),
    deadlineMs: 100000,
    setTimer: () => 1,
    clearTimer: () => {},
  });
  assert.equal(sent.length, 1);
  assert.equal(sent[0].audioStreamEnd, true);
  // A bare boundary without any text must not close an empty tail.
  assert.equal(flush.accept({ text: "", finished: true }), false);
  assert.equal(flush.armed, true);
  // The tail arrives as several deltas and only the boundary settles it.
  assert.equal(flush.accept({ text: "tail ", finished: false }), true);
  assert.equal(flush.accept({ text: "words", finished: false }), true);
  assert.equal(flush.accept({ text: "", finished: true }), true);
  assert.equal(flush.armed, false);
  assert.deepEqual(settled, ["tail words"]);
  assert.equal(closed, true);
});

test("the wire frames match the reviewed Live contract", () => {
  const setup = live.buildLiveSetupMessage({
    model: "gemini-3.5-transcribe-live",
    vadSilenceMs: 1300,
    responseModalities: ["TEXT"],
    inputAudioTranscriptionMode: "VERBATIM",
  });
  assert.equal(setup.setup.model, "gemini-3.5-transcribe-live");
  assert.deepEqual(setup.setup.generationConfig.responseModalities, ["TEXT"]);
  assert.deepEqual(setup.setup.inputAudioTranscription, { languageCodes: [], mode: "VERBATIM" });
  assert.equal(setup.setup.realtimeInputConfig.automaticActivityDetection.silenceDurationMs, 1300);

  const media = live.buildRealtimeInputMessage({ mimeType: "audio/pcm;rate=16000", data: "AAA" });
  assert.deepEqual(media.realtimeInput.mediaChunks, [{ mimeType: "audio/pcm;rate=16000", data: "AAA" }]);
  assert.deepEqual(live.buildAudioStreamEndMessage(), { realtimeInput: { audioStreamEnd: true } });

  const url = live.buildLiveSocketUrl("auth_tokens/abc");
  assert.ok(url.startsWith("wss://"));
  assert.ok(url.includes("BidiGenerateContentConstrained"));
  assert.ok(url.endsWith("?access_token=auth_tokens/abc"));
});

test("PCM conversion matches the reviewed audio utilities", () => {
  const pcm = live.float32ToInt16(Float32Array.from([0, 1, -1, 0.5]));
  assert.equal(pcm.length, 4);
  assert.equal(pcm[0], 0);
  assert.equal(pcm[1], 32767);
  assert.equal(pcm[2], -32768);
  assert.equal(pcm[3], 16383);
  assert.equal(live.arrayBufferToBase64(pcm.buffer), "AAD/fwCA/z8=");
});

/* ------------------------------------------------------------------ */
/* The recognizer                                                      */
/* ------------------------------------------------------------------ */

test("one Live turn is one committed utterance with its own id", async () => {
  const env = makeEnv();
  const finals = [];
  const turns = [];
  const interims = [];
  const factory = makeFactory(env);
  const session = factory({
    onInterim: (text) => interims.push(text),
    onFinal: (payload) => finals.push(payload),
    onTurnComplete: (event) => turns.push(event),
    onError: () => {},
    onEnd: () => {},
  }, { generation: 7, sessionToken: "sess-1" });
  assert.equal(typeof session.stop, "function");

  await new Promise((resolve) => setTimeout(resolve, 20));
  assert.equal(env.sockets.length, 1, "one Live session is opened");
  const socket = env.sockets[0];
  assert.ok(socket.url.includes("access_token=auth_tokens/test-token"));
  const setupFrame = JSON.parse(socket.sent[0]);
  assert.equal(setupFrame.setup.model, "gemini-3.5-transcribe-live");
  assert.equal(env.fetches[0].path, "/api/voice/live-token");
  assert.equal(env.fetches[0].init.credentials, "same-origin");

  // The interim is a live preview, not a final.
  socket.message({ serverContent: { interimInputTranscription: { text: "안녕" } } });
  assert.deepEqual(interims, ["안녕"]);
  assert.equal(finals.length, 0);

  // The confirmed turn closes the utterance.
  socket.message({
    serverContent: {
      inputTranscription: { text: "안녕하세요", finished: true },
      turnComplete: true,
    },
  });
  assert.equal(finals.length, 1);
  assert.equal(finals[0].text, "안녕하세요");
  assert.ok(finals[0].utteranceId.startsWith("live-7-sess-1-"));
  assert.equal(turns.length, 1);
  assert.equal(turns[0].accepted, true);
  assert.equal(turns[0].endOfTurn, true);
  assert.equal(turns[0].finalId, finals[0].utteranceId);

  // The next utterance is a new row, never a duplicate of the first.
  socket.message({ serverContent: { inputTranscription: { text: "다음 문장", finished: true } } });
  assert.equal(finals.length, 2);
  assert.notEqual(finals[1].utteranceId, finals[0].utteranceId);
});

test("the microphone audio is streamed as 16 kHz mono PCM", async () => {
  const env = makeEnv();
  const factory = makeFactory(env);
  factory({ onError: () => {} }, { generation: 1, sessionToken: "s" });
  await new Promise((resolve) => setTimeout(resolve, 20));
  const socket = env.sockets[0];
  env.audio.emit(new Array(2048).fill(0.5));
  const frame = JSON.parse(socket.sent[socket.sent.length - 1]);
  assert.equal(frame.realtimeInput.mediaChunks[0].mimeType, "audio/pcm;rate=16000");
  assert.ok(frame.realtimeInput.mediaChunks[0].data.length > 0);
});

test("a refused token is reported as provider-unavailable, not as a failure", async () => {
  const env = makeEnv({ tokenStatus: 403 });
  const unavailable = [];
  const errors = [];
  const factory = makeFactory(env);
  factory({
    onProviderUnavailable: (code) => unavailable.push(code),
    onError: (code) => errors.push(code),
  }, { generation: 1, sessionToken: "s" });
  await new Promise((resolve) => setTimeout(resolve, 30));
  assert.deepEqual(unavailable, ["live-token-unavailable"]);
  assert.deepEqual(errors, []);
});

test("a microphone denial is a bounded error and never a silent success", async () => {
  const env = makeEnv();
  const errors = [];
  const factory = live.createRecognizerFactory({
    win: env.win,
    fetchImpl: env.fetchImpl,
    mediaDevices: {
      getUserMedia: async () => {
        const error = new Error("denied");
        error.name = "NotAllowedError";
        throw error;
      },
    },
    liveTokenPath: "/api/voice/live-token",
  });
  factory({ onError: (code) => errors.push(code) }, { generation: 1, sessionToken: "s" });
  await new Promise((resolve) => setTimeout(resolve, 30));
  assert.deepEqual(errors, ["permission-denied"]);
});

test("a user stop drains the session tail before the run ends", async () => {
  const env = makeEnv();
  const finals = [];
  let ended = false;
  const factory = makeFactory(env);
  const session = factory({
    onFinal: (payload) => finals.push(payload),
    onError: () => {},
    onEnd: () => { ended = true; },
  }, { generation: 1, sessionToken: "s" });
  await new Promise((resolve) => setTimeout(resolve, 20));
  const socket = env.sockets[0];

  socket.message({ serverContent: { interimInputTranscription: { text: "마지막" } } });
  session.stop("user-stopped");

  // The session was asked to finalise the audio it still holds.
  const tailFrame = JSON.parse(socket.sent[socket.sent.length - 1]);
  assert.equal(tailFrame.realtimeInput.audioStreamEnd, true);

  // The retired session still delivers its tail, and it is committed.
  socket.message({ serverContent: { inputTranscription: { text: "마지막 문장", finished: true } } });
  assert.equal(finals.length, 1);
  assert.equal(finals[0].text, "마지막 문장");
  assert.equal(finals[0].stopped, true);
});

test("a cancel never transcribes a tail", async () => {
  const env = makeEnv();
  const finals = [];
  const factory = makeFactory(env);
  const session = factory({
    onFinal: (payload) => finals.push(payload),
    onError: () => {},
    onEnd: () => {},
  }, { generation: 1, sessionToken: "s" });
  await new Promise((resolve) => setTimeout(resolve, 20));
  session.stop("account-changed");
  env.sockets[0].message({ serverContent: { inputTranscription: { text: "늦은 전사", finished: true } } });
  assert.equal(finals.length, 0);
});

test("a session rotation keeps the utterance and replays the audio in the gap", async () => {
  const env = makeEnv({ rotateAfterMs: 200, tokenDelayMs: 120 });
  const finals = [];
  const factory = makeFactory(env);
  factory({
    onFinal: (payload) => finals.push(payload),
    onError: () => {},
    onEnd: () => {},
  }, { generation: 1, sessionToken: "s" });
  await new Promise((resolve) => setTimeout(resolve, 20));
  assert.equal(env.sockets.length, 1);
  const first = env.sockets[0];

  // One confirmed turn before the rotation boundary.
  first.message({ serverContent: { inputTranscription: { text: "확정 문장", finished: true } } });
  assert.equal(finals.length, 1);
  assert.equal(finals[0].text, "확정 문장");

  // A turn that is still open when the rotation boundary lands.
  first.message({ serverContent: { inputTranscription: { text: "마지막 단어" } } });

  // The rotation starts: a second token is minted and a new session opens.
  // While the new token is in flight the microphone belongs to neither
  // session, so its frames are captured for the incoming one.
  await new Promise((resolve) => setTimeout(resolve, 230));
  env.audio.emit(new Array(2048).fill(0.25));

  await new Promise((resolve) => setTimeout(resolve, 200));
  assert.equal(env.sockets.length, 2, "the session is rotated before the provider limit");
  assert.equal(env.fetches.length, 2, "one ephemeral token per Live session");

  // The turn that was open at the boundary is committed instead of being
  // dropped with the outgoing session, and the confirmed turn is not
  // committed twice.
  assert.equal(finals.length, 2);
  assert.equal(finals[1].text, "마지막 단어");
  assert.notEqual(finals[1].utteranceId, finals[0].utteranceId);

  // The microphone frames captured during the swap are replayed into the
  // incoming session, so the utterance that straddled the boundary is not
  // cut in half.
  const firstMedia = env.sockets[0].sent
    .map((frame) => JSON.parse(frame))
    .filter((frame) => frame.realtimeInput && frame.realtimeInput.mediaChunks);
  assert.equal(firstMedia.length, 0, "the frame captured in the gap is not sent to the retired session");
  const replayed = env.sockets[1].sent
    .map((frame) => JSON.parse(frame))
    .filter((frame) => frame.realtimeInput && frame.realtimeInput.mediaChunks);
  assert.equal(replayed.length, 1, "the frame captured in the gap is replayed into the new session");
  assert.equal(replayed[0].realtimeInput.mediaChunks[0].mimeType, "audio/pcm;rate=16000");
});

test("the browser holds no long-lived provider credential", () => {
  const source = fs.readFileSync(path.join(STATIC, "voice-live-transcript.js"), "utf8");
  const code = source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/[^\n]*/g, "");
  // The only provider credential is the ephemeral token the same-origin route
  // returned, and it is carried in the query string exactly as the reference
  // SDK carries it.
  for (const forbidden of ["PADIEM_GEMINI_API_KEY", "PADIEM_GROQ_API_KEY", "x-goog-api-key", "Authorization"]) {
    assert.ok(!code.includes(forbidden), "long-lived credential material present: " + forbidden);
  }
  // The private Worker is never addressed from the browser.
  assert.ok(!code.includes("padiem-voice-stt"));
  assert.ok(!code.includes("voice.stt."));
});
