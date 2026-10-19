"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const meeting = require("../static/meeting-capture.js");

function fixture() {
  let micOpens = 0, stoppedTracks = 0, mediaRecords = 0, speechStarts = 0;
  let latestRecognition = null;
  const reports = [], changes = [];
  class Recorder {
    static isTypeSupported(type) { return type === "audio/webm"; }
    constructor(stream, options) {
      assert.ok(stream);
      assert.equal(options.mimeType, "audio/webm");
      this.mimeType = options.mimeType;
      this.state = "inactive";
      mediaRecords += 1;
    }
    start() { this.state = "recording"; }
    stop() {
      this.state = "inactive";
      this.ondataavailable?.({ data: new Blob(["audio-sample"], { type: "audio/webm" }) });
      this.onstop?.({});
    }
  }
  class Recognition {
    constructor() { this.stops = 0; latestRecognition = this; }
    start() { speechStarts += 1; }
    stop() { this.stops += 1; this.onend?.(); }
    abort() { this.stops += 1; this.onend?.(); }
  }
  const controller = meeting.createController({
    MediaRecorder: Recorder,
    SpeechRecognition: Recognition,
    mediaDevices: {
      async getUserMedia() {
        micOpens += 1;
        return { getTracks() { return [{ stop() { stoppedTracks += 1; } }]; } };
      },
    },
    report: (msg) => reports.push(msg),
    change: (state) => changes.push(state),
  });
  return { controller, reports, changes,
    get latestRecognition() { return latestRecognition; },
    counts: () => ({ micOpens, stoppedTracks, mediaRecords, speechStarts }),
  };
}

test("Claw meeting setup recognizes intent and excludes unrelated questions", () => {
  assert.equal(meeting.isMeetingIntent("지금 회의할 테니 회의록 준비해 줘"), true);
  assert.equal(meeting.isMeetingIntent("회의할테니 회의록 준비해줘"), true);
  assert.equal(meeting.isMeetingIntent("회의록 준비해 줘"), true);
  assert.equal(meeting.isMeetingIntent("미팅 회의록 준비해줘"), true);
  assert.equal(meeting.isMeetingIntent("AI 모델을 검색해 줘"), false);
  assert.equal(meeting.isMeetingIntent("회의 날짜가 언제야?"), false);
});

test("record-only uses MediaRecorder without any STT provider call", async () => {
  const f = fixture();
  await f.controller.start("record");
  assert.equal(f.controller.snapshot().active, true);
  assert.deepEqual(f.counts(), { micOpens: 1, stoppedTracks: 0, mediaRecords: 1, speechStarts: 0 });
  const result = await f.controller.stop();
  assert.equal(result.active, false);
  assert.equal(result.artifact.type, "audio/webm");
  assert.equal(result.artifact.size, 12);
  assert.equal(result.transcript, "");
  assert.equal(f.counts().stoppedTracks, 1);
});

test("transcript-only uses SpeechRecognition and never records audio", async () => {
  const f = fixture();
  await f.controller.start("transcribe");
  const row = { 0: { transcript: "회의를 시작합니다" }, isFinal: true };
  f.latestRecognition.onresult({ resultIndex: 0, results: [row] });
  assert.equal(f.controller.snapshot().transcript, "회의를 시작합니다");
  f.latestRecognition.onresult({ resultIndex: 0, results: [row] });
  assert.equal(f.controller.snapshot().transcript, "회의를 시작합니다", "duplicate final must not repeat");
  const result = await f.controller.stop();
  assert.equal(result.artifact, null);
  assert.equal(result.transcript, "회의를 시작합니다");
  assert.deepEqual(f.counts(), { micOpens: 0, stoppedTracks: 0, mediaRecords: 0, speechStarts: 1 });
});

test("combined capture keeps audio when STT errors", async () => {
  const f = fixture();
  await f.controller.start("both");
  f.latestRecognition.onerror({ error: "network" });
  assert.equal(f.controller.snapshot().active, true);
  assert.equal(f.controller.snapshot().recognitionFailed, true);
  const result = await f.controller.stop();
  assert.ok(result.artifact);
  assert.ok(f.reports.some((msg) => msg.includes("transcription_error:network")));
  assert.equal(f.counts().stoppedTracks, 1);
});

test("unsupported STT and unauthorized mode fail without recording or provider calls", async () => {
  const f = fixture();
  await assert.rejects(f.controller.start("other"), /invalid_meeting_mode/);
  const noStt = meeting.createController({ MediaRecorder: class {}, mediaDevices: {} });
  await assert.rejects(noStt.start("transcribe"), /live_transcription_not_supported/);
  assert.equal(noStt.snapshot().active, false);
  assert.deepEqual(f.counts(), { micOpens: 0, stoppedTracks: 0, mediaRecords: 0, speechStarts: 0 });
});

test("repeated Stop is idempotent and does not duplicate the audio artifact", async () => {
  const f = fixture();
  await f.controller.start("record");
  const first = await f.controller.stop();
  const second = await f.controller.stop();
  assert.equal(first.artifact, second.artifact);
  assert.equal(f.counts().stoppedTracks, 1);
});
