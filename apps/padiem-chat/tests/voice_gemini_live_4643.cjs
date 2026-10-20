/*
 * #4643: the Gemini Live real-time transcription engine.
 *
 * Behavioural contract for apps/padiem-chat/static/voice-gemini-live.js:
 * the Live session, the real-time interim/final split, the turn commit, the
 * session rotation with the audio carry-over, the provider fallback and the
 * teardown that leaves nothing running.
 *
 * The engine is global-classroom's useGeminiLive ported to plain browser
 * JavaScript, so the expectations below are the original's behaviour.
 */
"use strict";

const assert = require("node:assert");
const path = require("node:path");

const STATIC = path.join(__dirname, "..", "static");
const engine = require(path.join(STATIC, "voice-gemini-live.js"));
const authority = require(path.join(STATIC, "voice-live-transcript-turn.js"));

let passed = 0;
let failed = 0;

function test(name, fn) {
  try {
    fn();
    passed += 1;
  } catch (error) {
    failed += 1;
    console.log("not ok - " + name);
    console.log("  " + (error && error.message ? error.message : error));
  }
}

/* ------------------------------------------------------------------ */
/* A fake browser: WebSocket, AudioContext, microphone, fetch.        */
/* ------------------------------------------------------------------ */

function makeFakeWindow(options) {
  const opts = options || {};
  const sockets = [];
  const fetches = [];
  const tracks = [];
  const closedContexts = [];

  class FakeSocket {
    constructor(url) {
      this.url = url;
      this.readyState = 0;
      this.sent = [];
      this.closed = false;
      sockets.push(this);
    }
    send(data) {
      this.sent.push(JSON.parse(data));
    }
    close() {
      this.closed = true;
      this.readyState = 3;
    }
    open() {
      this.readyState = 1;
      if (this.onopen) this.onopen();
    }
    message(payload) {
      if (this.onmessage) this.onmessage({ data: JSON.stringify(payload) });
    }
    fail() {
      if (this.onerror) this.onerror({});
    }
  }

  class FakeProcessor {
    constructor() {
      this.onaudioprocess = null;
    }
    connect() {}
    disconnect() {}
  }

  const fakeWindow = {
    WebSocket: FakeSocket,
    navigator: {
      mediaDevices: {
        getUserMedia: async function () {
          if (opts.getUserMediaError) throw opts.getUserMediaError;
          const track = { stopped: false, stop() { this.stopped = true; } };
          tracks.push(track);
          return { getTracks: () => [track] };
        },
      },
    },
    AudioContext: class {
      constructor() {
        this.sampleRate = 16000;
        this.state = "running";
        this.destination = {};
      }
      async resume() {}
      async close() {
        closedContexts.push(this);
      }
      createMediaStreamSource() {
        return { connect() {}, disconnect() {} };
      }
      createScriptProcessor() {
        const processor = new FakeProcessor();
        fakeWindow.__processor = processor;
        return processor;
      }
      createAnalyser() {
        return { fftSize: 256, connect() {}, disconnect() {} };
      }
    },
    fetch: async function (url, init) {
      fetches.push({ url: url, init: init });
      if (opts.tokenStatus && opts.tokenStatus !== 200) {
        return { ok: false, status: opts.tokenStatus, json: async () => ({}) };
      }
      return {
        ok: true,
        status: 200,
        json: async () => ({
          token: opts.token || "auth_tokens/test-token",
          session: opts.session || {
            model: "gemini-3.5-transcribe-live",
            vad_silence_ms: 1300,
            rotate_after_ms: 9 * 60 * 1000 + 20 * 1000,
            response_modalities: ["TEXT"],
            input_audio_transcription_mode: "VERBATIM",
          },
        }),
      };
    },
  };
  fakeWindow.__sockets = sockets;
  fakeWindow.__fetches = fetches;
  fakeWindow.__tracks = tracks;
  fakeWindow.__closedContexts = closedContexts;
  fakeWindow.PadiemVoiceLiveTranscriptTurn = authority;
  return fakeWindow;
}

function makeCallbacks() {
  const events = { interim: [], final: [], turn: [], error: [], end: 0 };
  return {
    events: events,
    callbacks: {
      onInterim: (text) => events.interim.push(text),
      onFinal: (payload) => events.final.push(payload),
      onTurnComplete: (payload) => events.turn.push(payload),
      onError: (code) => events.error.push(code),
      onEnd: () => { events.end += 1; },
    },
  };
}

function flush() {
  return new Promise((resolve) => setImmediate(resolve));
}

/* Several microtask turns: the token request, the socket open and the
 * microphone grant are three separate promises. */
async function settle() {
  for (let i = 0; i < 6; i += 1) await flush();
}

/* ------------------------------------------------------------------ */
/* The engine contract.                                                 */
/* ------------------------------------------------------------------ */

test("the Live URL is the constrained v1alpha session with the ephemeral token", function () {
  const url = engine.buildLiveUrl("auth_tokens/abc");
  assert.ok(url.indexOf("BidiGenerateContentConstrained") !== -1, url);
  assert.ok(url.indexOf("v1alpha") !== -1, url);
  assert.ok(url.indexOf("access_token=auth_tokens%2Fabc") !== -1, url);
  assert.ok(url.indexOf("generativelanguage.googleapis.com") !== -1, url);
  assert.strictEqual(url.indexOf("key="), -1, "the long-lived key must never be the query");
});

test("the setup message carries the server's session contract", function () {
  const setup = engine.buildLiveSetup({
    model: "gemini-3.5-transcribe-live",
    vad_silence_ms: 1300,
    response_modalities: ["TEXT"],
    input_audio_transcription_mode: "VERBATIM",
  }, authority);
  assert.strictEqual(setup.model, "models/gemini-3.5-transcribe-live");
  assert.deepStrictEqual(setup.generationConfig.responseModalities, ["TEXT"]);
  assert.strictEqual(setup.realtimeInputConfig.automaticActivityDetection.silenceDurationMs, 1300);
  assert.deepStrictEqual(setup.inputAudioTranscription, { languageCodes: [], mode: "VERBATIM" });
});

test("the adapter's PCM helpers are the original's", function () {
  const pcm = engine.float32ToInt16(new Float32Array([0, 1, -1, 0.5]));
  assert.deepStrictEqual(Array.from(pcm), [0, 32767, -32768, 16383]);
  assert.strictEqual(typeof engine.arrayBufferToBase64(pcm.buffer), "string");
});

test("a live session streams the microphone and reports interim then final", async function () {
  const win = makeFakeWindow();
  const { callbacks, events } = makeCallbacks();
  const factory = engine.createRecognizerFactory({ win: win, doc: { querySelector: () => null } });
  const handle = factory(callbacks, { generation: 1, sessionToken: "tok" });
  await settle();
  assert.strictEqual(win.__sockets.length, 1, "one Live socket");
  assert.strictEqual(win.__fetches.length, 1, "one token request");
  assert.strictEqual(win.__fetches[0].init.method, "POST");
  assert.strictEqual(win.__fetches[0].init.credentials, "same-origin");
  /* The token route is a JSON route: without the media type it answers 415
   * and the run falls back to the chunked provider for no reason. */
  assert.strictEqual(win.__fetches[0].init.headers["Content-Type"], "application/json");
  const socket = win.__sockets[0];
  socket.open();
  await settle();
  const setup = socket.sent[0];
  assert.ok(setup.setup, "the first frame is the setup");
  assert.strictEqual(setup.setup.model, "models/gemini-3.5-transcribe-live");
  // The capture starts and one frame reaches the socket as PCM media.
  win.__processor.onaudioprocess({ inputBuffer: { getChannelData: () => new Float32Array(4) } });
  const media = socket.sent.find((frame) => frame.realtimeInput);
  assert.ok(media, "a realtimeInput frame");
  assert.strictEqual(media.realtimeInput.mediaChunks[0].mimeType, "audio/pcm;rate=16000");

  socket.message({ serverContent: { interimInputTranscription: { text: "안녕" } } });
  assert.deepStrictEqual(events.interim, ["안녕"]);
  socket.message({ serverContent: { inputTranscription: { text: "안녕하세요" } } });
  assert.strictEqual(events.final.length, 0, "a hypothesis is not a final");
  socket.message({ serverContent: { inputTranscription: { text: "안녕하세요", finished: true } } });
  assert.strictEqual(events.final.length, 1);
  assert.strictEqual(events.final[0].text, "안녕하세요");
  assert.strictEqual(events.turn.length, 1, "one turn boundary");
  assert.strictEqual(events.turn[0].accepted, true);
  handle.stop();
});

test("the rotation carries the audio across the new session", async function () {
  const win = makeFakeWindow();
  const { callbacks } = makeCallbacks();
  let timer = null;
  const factory = engine.createRecognizerFactory({
    win: win,
    doc: { querySelector: () => null },
    setTimeout: (fn) => { timer = fn; return 1; },
    clearTimeout: () => { timer = null; },
  });
  const handle = factory(callbacks, { generation: 1, sessionToken: "tok" });
  await settle();
  win.__sockets[0].open();
  await settle();
  // Capture one frame, then rotate.
  win.__processor.onaudioprocess({ inputBuffer: { getChannelData: () => new Float32Array(4) } });
  const before = win.__sockets.length;
  assert.ok(timer, "a rotation timer is armed");
  timer();
  await settle();
  /* The microphone keeps running through the gap, so the frame captured now
   * is the one the new session has to receive. */
  win.__processor.onaudioprocess({ inputBuffer: { getChannelData: () => new Float32Array(4) } });
  assert.ok(win.__sockets.length > before, "a new Live session opened");
  const newSocket = win.__sockets[win.__sockets.length - 1];
  newSocket.open();
  const replayed = newSocket.sent.filter((frame) => frame.realtimeInput);
  assert.ok(replayed.length >= 1, "the buffered frame is replayed into the new session");
  handle.stop();
});

test("stop releases the socket, the microphone, the audio context and the timer", async function () {
  const win = makeFakeWindow();
  const { callbacks, events } = makeCallbacks();
  let timer = null;
  const factory = engine.createRecognizerFactory({
    win: win,
    doc: { querySelector: () => null },
    setTimeout: (fn) => { timer = fn; return 1; },
    clearTimeout: () => { timer = null; },
  });
  const handle = factory(callbacks, { generation: 1, sessionToken: "tok" });
  await settle();
  const socket = win.__sockets[0];
  socket.open();
  await settle();
  assert.strictEqual(timer !== null, true);
  handle.stop();
  assert.strictEqual(socket.closed, true, "the Live socket is closed");
  assert.strictEqual(win.__tracks[0].stopped, true, "the microphone track is stopped");
  assert.strictEqual(win.__closedContexts.length, 1, "the audio context is closed");
  assert.strictEqual(timer, null, "the rotation timer is cleared");
  const fetchesAfterStop = win.__fetches.length;
  await settle();
  assert.strictEqual(win.__fetches.length, fetchesAfterStop, "no provider call after stop");
});

test("a failed Live connection falls back to the next provider exactly once", async function () {
  const win = makeFakeWindow({ tokenStatus: 503 });
  const { callbacks, events } = makeCallbacks();
  let fallbackCalls = 0;
  let fallbackStopped = 0;
  const fallbackFactory = function () {
    fallbackCalls += 1;
    return { stop: () => { fallbackStopped += 1; } };
  };
  const factory = engine.createRecognizerFactory({
    win: win,
    doc: { querySelector: () => null },
    fallbackFactory: fallbackFactory,
  });
  const handle = factory(callbacks, { generation: 1, sessionToken: "tok" });
  await settle();
  assert.strictEqual(fallbackCalls, 1, "the fallback provider took the run");
  assert.strictEqual(events.error.length, 0, "a working fallback is not a mic error");
  handle.stop();
  assert.strictEqual(fallbackStopped, 1, "stopping the run stops the fallback too");
});

test("no Live session and no token request happen while the microphone is off", function () {
  const win = makeFakeWindow();
  const { callbacks } = makeCallbacks();
  const factory = engine.createRecognizerFactory({ win: win, doc: { querySelector: () => null } });
  // The factory is the microphone seam: nothing is opened until it is called.
  assert.strictEqual(win.__sockets.length, 0);
  assert.strictEqual(win.__fetches.length, 0);
  assert.strictEqual(typeof factory, "function");
  assert.strictEqual(typeof callbacks.onInterim, "function");
});

test("a permission denial is a mic error, not a provider fallback", async function () {
  const win = makeFakeWindow({
    getUserMediaError: Object.assign(new Error("denied"), { name: "NotAllowedError" }),
  });
  const { callbacks, events } = makeCallbacks();
  let fallbackCalls = 0;
  const factory = engine.createRecognizerFactory({
    win: win,
    doc: { querySelector: () => null },
    fallbackFactory: () => { fallbackCalls += 1; return { stop() {} }; },
  });
  const handle = factory(callbacks, { generation: 1, sessionToken: "tok" });
  await settle();
  win.__sockets[0].open();
  await settle();
  assert.deepStrictEqual(events.error, ["permission-denied"]);
  assert.strictEqual(fallbackCalls, 0, "a denied microphone is not a Live failure");
  handle.stop();
});

setTimeout(() => {
  console.log("# pass " + passed);
  console.log("# fail " + failed);
  process.exit(failed === 0 ? 0 : 1);
}, 50);
