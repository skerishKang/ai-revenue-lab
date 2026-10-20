"use strict";
/**
 * #4643 the product wiring selects the live engine and falls back to the
 * reviewed chunk path.
 *
 * The chunk path is the reviewed fallback of the provider chain, so it must
 * take over when the live engine reports that it cannot run at all in this
 * browser or session. A live failure *after* words were captured is an error,
 * not a fallback, so a spoken sentence is never silently dropped.
 */
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const STATIC = path.resolve(__dirname, "../static");
const wiring = require(path.join(STATIC, "voice-stt-wiring.js"));

function installFakeLive(behaviour) {
  globalThis.PadiemVoiceLiveTranscript = {
    createRecognizerFactory: function (deps) {
      return function fakeLiveFactory(callbacks, runContext) {
        behaviour(deps, callbacks, runContext);
        return { stop: function () {} };
      };
    },
  };
}

function removeFakeLive() {
  delete globalThis.PadiemVoiceLiveTranscript;
}

/** A microphone that reports how often it was opened. */
function fakeMediaDevices() {
  const state = { opens: 0 };
  state.getUserMedia = async function () {
    state.opens += 1;
    return { getTracks: () => [{ stop() {} }] };
  };
  return state;
}

function fakeWin() {
  function FakeMediaRecorder() {
    this.state = "inactive";
    this.ondataavailable = null;
    this.onstop = null;
  }
  FakeMediaRecorder.prototype.start = function () { this.state = "recording"; };
  FakeMediaRecorder.prototype.requestData = function () {};
  FakeMediaRecorder.prototype.stop = function () {
    this.state = "inactive";
    if (this.onstop) this.onstop();
  };
  return {
    setTimeout,
    clearTimeout,
    MediaRecorder: FakeMediaRecorder,
    Blob: function () {},
    performance: { now: () => Date.now() },
    AudioContext: function () {
      return {
        sampleRate: 0,
        destination: {},
        resume: async () => {},
        close: async () => {},
        createMediaStreamSource: () => ({ connect() {}, disconnect() {} }),
        createAnalyser: () => ({
          fftSize: 0,
          getFloatTimeDomainData: () => {},
        }),
      };
    },
  };
}

test("the live engine is asked for the Chat live-token route", () => {
  const seen = {};
  installFakeLive(function (deps) { seen.path = deps.liveTokenPath; });
  try {
    const factory = wiring.createRecognizerFactory({
      win: fakeWin(),
      doc: { querySelector: () => null },
      fetchImpl: () => Promise.reject(new Error("unused")),
      mediaDevices: fakeMediaDevices(),
    });
    factory({}, { generation: 1, sessionToken: "s" });
    assert.equal(seen.path, "/api/voice/live-token");
  } finally {
    removeFakeLive();
  }
});

test("the Claw shell asks for the Claw live-token route", () => {
  const seen = {};
  installFakeLive(function (deps) { seen.path = deps.liveTokenPath; });
  try {
    const factory = wiring.createRecognizerFactory({
      win: fakeWin(),
      doc: { querySelector: () => ({ dataset: { state: "claw" } }) },
      fetchImpl: () => Promise.reject(new Error("unused")),
      mediaDevices: fakeMediaDevices(),
    });
    factory({}, { generation: 1, sessionToken: "s" });
    assert.equal(seen.path, "/api/claw/voice/live-token");
  } finally {
    removeFakeLive();
  }
});

test("a provider-unavailable live engine hands the run to the chunk fallback", async () => {
  const media = fakeMediaDevices();
  installFakeLive(function (deps, callbacks) {
    setTimeout(() => callbacks.onProviderUnavailable("live-token-unavailable"), 0);
  });
  try {
    const factory = wiring.createRecognizerFactory({
      win: fakeWin(),
      doc: { querySelector: () => null },
      fetchImpl: () => Promise.reject(new Error("offline")),
      mediaDevices: media,
    });
    factory({ onError: function () {} }, { generation: 1, sessionToken: "s" });
    await new Promise((resolve) => setTimeout(resolve, 40));
    // The chunk recognizer owns the microphone capture, so an opened
    // microphone proves the fallback took the run over.
    assert.equal(media.opens, 1, "the chunk fallback did not take the run over");
  } finally {
    removeFakeLive();
  }
});

test("without the live engine the reviewed chunk path is used directly", async () => {
  removeFakeLive();
  const media = fakeMediaDevices();
  const factory = wiring.createRecognizerFactory({
    win: fakeWin(),
    doc: { querySelector: () => null },
    fetchImpl: () => Promise.reject(new Error("offline")),
    mediaDevices: media,
  });
  factory({ onError: function () {} }, { generation: 1, sessionToken: "s" });
  await new Promise((resolve) => setTimeout(resolve, 40));
  assert.equal(media.opens, 1);
});

test("the wiring never sends a chat message", () => {
  const source = fs.readFileSync(path.join(STATIC, "voice-stt-wiring.js"), "utf8");
  for (const forbidden of ["composerForm.requestSubmit", "form.submit", "requestSubmit"]) {
    assert.ok(!source.includes(forbidden), "the wiring must never submit: " + forbidden);
  }
});
