"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const meeting = require("../static/meeting-capture.js");

const CHROME_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
  + "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36";

function makeTrack(kind) {
  const listeners = {};
  return {
    kind, stopped: 0, listeners,
    stop() { this.stopped += 1; },
    addEventListener(name, fn) { (listeners[name] ||= []).push(fn); },
    removeEventListener(name, fn) { listeners[name] = (listeners[name] || []).filter((row) => row !== fn); },
    end() { (listeners.ended || []).forEach((fn) => fn()); },
  };
}

function makeStream(tracks) {
  return { getTracks: () => tracks.slice(), getAudioTracks: () => tracks.filter((t) => t.kind === "audio"), getVideoTracks: () => tracks.filter((t) => t.kind === "video") };
}

function fixture(options = {}) {
  const display = options.display || "ok";
  const recorders = [], recognizers = [], micCalls = [], displayCalls = [], fetchCalls = [], contexts = [], callOrder = [];
  const micTrack = makeTrack("audio");
  const micStream = makeStream([micTrack]);
  let displayVideo = null, displayAudio = null;
  let endDisplay = null;

  class Recorder {
    static isTypeSupported(type) { return type === "audio/webm" || type === "audio/webm;codecs=opus"; }
    constructor(stream, opts) {
      assert.ok(stream, "recorder needs a stream");
      this.stream = stream;
      this.mimeType = opts?.mimeType || "audio/webm";
      this.state = "inactive";
      recorders.push(this);
    }
    start() { this.state = "recording"; }
    requestData() {}
    stop() {
      if (this.state === "inactive") return;
      this.state = "inactive";
      this.ondataavailable?.({ data: new Blob(["chunk-" + recorders.length], { type: this.mimeType }) });
      this.onstop?.({});
    }
  }
  class Recognition {
    constructor() { this.starts = 0; this.stops = 0; recognizers.push(this); }
    start() { this.starts += 1; }
    stop() { this.stops += 1; this.onend?.(); }
    abort() { this.stops += 1; this.onend?.(); }
  }
  class AudioContext {
    constructor() { this.state = "running"; this.closed = 0; this.destination = null; contexts.push(this); }
    createMediaStreamDestination() {
      const track = makeTrack("audio");
      this.destination = makeStream([track]);
      return { stream: this.destination };
    }
    createMediaStreamSource(stream) { return { stream, connect() {}, disconnect() {} }; }
    resume() { this.state = "running"; return Promise.resolve(); }
    close() { this.closed += 1; }
  }

  const mediaDevices = {
    async getUserMedia(constraints) { callOrder.push("microphone"); micCalls.push(constraints); return micStream; },
    async getDisplayMedia(constraints) {
      callOrder.push("display");
      displayCalls.push(constraints);
      if (display === "deny") {
        const error = new Error("denied");
        error.name = "NotAllowedError";
        throw error;
      }
      displayVideo = makeTrack("video");
      displayAudio = display === "no-audio" ? null : makeTrack("audio");
      return makeStream(displayAudio ? [displayVideo, displayAudio] : [displayVideo]);
    },
  };
  const win = {
    navigator: { userAgent: options.userAgent === undefined ? CHROME_UA : options.userAgent, mediaDevices },
    MediaRecorder: Recorder,
    SpeechRecognition: Recognition,
    AudioContext,
    isSecureContext: true,
    fetch: async (url, opts) => {
      fetchCalls.push({ url, opts });
      return { ok: true, status: 200, json: async () => ({ text: "컴퓨터 발화" }) };
    },
  };
  const controller = meeting.createController({
    MediaRecorder: win.MediaRecorder,
    SpeechRecognition: win.SpeechRecognition,
    mediaDevices,
    navigator: win.navigator,
    AudioContext,
    isSecureContext: true,
    fetch: win.fetch,
    report: () => {},
    change: () => {},
  });
  endDisplay = () => displayAudio?.end();
  return {
    controller,
    displayCalls,
    fetchCalls,
    recorders,
    recognizers,
    micCalls,
    contexts,
    callOrder,
    micTrack,
    micStream,
    get displayAudio() { return displayAudio; },
    get displayVideo() { return displayVideo; },
    get recognitionSeen() { return recognizers.length > 0; },
    endDisplay,
  };
}

test("computer audio support is limited to desktop Chrome and Edge", () => {
  const base = {
    navigator: { userAgent: CHROME_UA, mediaDevices: { getDisplayMedia() {} } },
    AudioContext: function () {},
    isSecureContext: true,
  };
  assert.equal(meeting.supportsComputerAudio(base), true);
  assert.equal(meeting.supportsComputerAudio({ ...base, navigator: { ...base.navigator, userAgent: CHROME_UA.replace("Chrome/", "Edg/") } }), true);
  assert.equal(meeting.supportsComputerAudio({ ...base, navigator: { ...base.navigator, userAgent: "Mozilla/5.0 Firefox/131.0" } }), false);
  assert.equal(meeting.supportsComputerAudio({ ...base, navigator: { ...base.navigator, userAgent: CHROME_UA.replace("Windows NT 10.0; Win64; x64", "Linux; Android 14") } }), false);
  assert.equal(meeting.supportsComputerAudio({ ...base, isSecureContext: false }), false);
});

test("off keeps the existing microphone-only SpeechRecognition path", async () => {
  const f = fixture();
  await f.controller.start("both", { computerAudio: false });
  assert.equal(f.displayCalls.length, 0);
  assert.equal(f.controller.snapshot().computerAudio, "off");
  assert.equal(f.recognitionSeen, true);
  assert.equal(f.controller.snapshot().active, true);
  const result = await f.controller.stop();
  assert.equal(result.artifact.type, "audio/webm;codecs=opus");
  assert.equal(f.fetchCalls.length, 0, "off mode never uploads audio");
});

test("missing shared audio falls back to the microphone and says why", async () => {
  const f = fixture({ display: "no-audio" });
  await f.controller.start("both", { computerAudio: true });
  assert.equal(f.displayCalls.length, 1);
  assert.equal(f.displayVideo.stopped, 1, "video stops as soon as it arrives");
  assert.equal(f.controller.snapshot().active, true);
  assert.equal(f.controller.snapshot().computerAudio, "mic-only");
  assert.match(f.controller.snapshot().computerAudioNotice, /소리 공유가 선택되지 않아/);
  await f.controller.stop();
  assert.equal(f.micTrack.stopped, 1);
});

test("denied screen share falls back to the microphone and says why", async () => {
  const f = fixture({ display: "deny" });
  await f.controller.start("both", { computerAudio: true });
  assert.equal(f.controller.snapshot().active, true);
  assert.equal(f.controller.snapshot().computerAudio, "mic-only");
  assert.match(f.controller.snapshot().computerAudioNotice, /화면 공유를 거절해/);
  await f.controller.stop();
  assert.equal(f.micTrack.stopped, 1);
});

test("ending the shared audio mid-meeting keeps the microphone running", async () => {
  const f = fixture();
  await f.controller.start("both", { computerAudio: true });
  assert.equal(f.controller.snapshot().computerAudio, "active");
  f.endDisplay();
  assert.equal(f.controller.snapshot().active, true);
  assert.equal(f.controller.snapshot().computerAudio, "mic-only");
  assert.match(f.controller.snapshot().computerAudioNotice, /공유가 끝나/);
  assert.equal(f.displayAudio.stopped, 1);
  await f.controller.stop();
  assert.equal(f.micTrack.stopped, 1);
});

test("stop closes microphone, display share and AudioContext", async () => {
  const f = fixture();
  await f.controller.start("both", { computerAudio: true });
  assert.equal(f.displayVideo.stopped, 1);
  await f.controller.stop();
  assert.equal(f.micTrack.stopped, 1);
  assert.equal(f.displayAudio.stopped, 1);
  assert.equal(f.contexts.length, 1);
  assert.equal(f.contexts[0].closed, 1);
  assert.equal(f.controller.snapshot().active, false);
});

test("enabled transcription posts only to the existing voice transcribe route", async () => {
  const f = fixture();
  await f.controller.start("transcribe", { computerAudio: true });
  await f.controller.stop();
  assert.deepEqual(f.callOrder, ["display", "microphone"], "display needs the click activation before the mic prompt");
  assert.equal(f.fetchCalls.length, 1);
  const call = f.fetchCalls[0];
  assert.equal(call.url, "/api/voice/transcribe");
  assert.equal(call.opts.method, "POST");
  assert.equal(call.opts.credentials, "same-origin");
  assert.equal(call.opts.headers["Content-Type"], "application/octet-stream");
  assert.match(call.opts.headers["X-Padiem-Audio-Type"], /^audio\//);
  assert.ok(call.opts.body instanceof Blob);
  assert.equal(f.controller.snapshot().transcript, "컴퓨터 발화");
});

test("record-only with computer audio records the mix without uploading", async () => {
  const f = fixture();
  await f.controller.start("record", { computerAudio: true });
  assert.equal(f.fetchCalls.length, 0);
  await f.controller.stop();
  assert.equal(f.fetchCalls.length, 0);
  assert.ok(f.recorders[0].stream !== f.micStream, "the artifact is recorded from the mixed stream");
  assert.ok(f.controller.snapshot().artifact);
});
