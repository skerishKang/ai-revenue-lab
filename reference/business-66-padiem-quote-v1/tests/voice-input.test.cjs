/* B66 voice lane (#3404) — controller, transcript machine and composer bindings.
   Everything here is network-free: the STT transport, the mic and the DOM are stubs,
   so no provider call and no credential can be involved. */
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const SRC = path.join(__dirname, "..");

function loadVoiceModules() {
  const sandbox = {
    window: {},
    document: null,
    console,
    Date,
    Math,
    Number,
    String,
    Boolean,
    Object,
    Array,
    JSON,
    Error,
    Promise,
    Set,
    Uint8Array,
    Int16Array,
    ArrayBuffer,
    Buffer,
    btoa: (value) => Buffer.from(value, "binary").toString("base64")
  };
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(path.join(SRC, "voice-stt.js"), "utf8"), sandbox);
  vm.runInContext(fs.readFileSync(path.join(SRC, "voice-input.js"), "utf8"), sandbox);
  return { Stt: sandbox.window.B66VoiceStt, Voice: sandbox.window.B66VoiceInput };
}

/* Mirrors the composer contract easy-mode.js hands to the voice lane. */
function createHost(options) {
  const opts = options || {};
  const log = [];
  let handler = opts.handler !== false ? (text) => log.push("INPUT:" + text) : null;
  return {
    log,
    value: opts.initial || "",
    disabled: false,
    setBusy(busy) {
      this.disabled = Boolean(busy);
      if (!busy) handler = (text) => log.push("INPUT:" + text);
    },
    stageText(text) {
      const value = String(text || "").trim();
      if (!value) return { staged: false, reason: "empty_transcript" };
      this.value = this.value ? this.value + " " + value : value;
      this.staged = this.value;
      return { staged: true, length: this.value.length };
    },
    clearStagedText() {
      this.value = "";
      this.staged = null;
      return { cleared: true };
    },
    hasUnsentStagedText() {
      return Boolean(this.staged) && this.value === this.staged;
    },
    canSubmit() {
      return !this.disabled && Boolean(handler);
    },
    submitStaged() {
      if (!this.canSubmit()) return { submitted: false, reason: "input_not_ready" };
      const text = this.value.trim();
      this.value = "";
      this.staged = null;
      handler(text);
      return { submitted: true };
    }
  };
}

function fakeTransport() {
  const calls = [];
  return {
    calls,
    handlers: null,
    async connect(handlers) {
      this.handlers = handlers;
      calls.push("connect");
      return { connected: true };
    },
    sendAudio(chunk) {
      calls.push("audio:" + String(chunk.mimeType));
    },
    close() {
      calls.push("close");
    }
  };
}

function fakeAudio() {
  const calls = [];
  return {
    calls,
    async start() {
      calls.push("start");
      return { started: true };
    },
    stop() {
      calls.push("stop");
    }
  };
}

function setup(mode, extra) {
  const { Stt, Voice } = loadVoiceModules();
  const host = createHost(extra || {});
  const machine = Stt.createTranscriptMachine({ nextId: Stt.createIdSource(null) });
  const transport = fakeTransport();
  const audio = fakeAudio();
  const notices = [];
  const states = [];
  const controller = Voice.createVoiceController(Object.assign({
    host,
    machine,
    mode,
    transport,
    audio,
    onNotice: (notice) => notices.push(notice),
    onChange: (snapshot) => states.push(snapshot.state)
  }, (extra && extra.controllerOptions) || {}));
  return { Stt, Voice, host, machine, transport, audio, controller, notices, states };
}

async function main() {
  /* --- transcript machine ------------------------------------------------ */
  {
    const { Stt } = loadVoiceModules();
    const events = [];
    const machine = Stt.createTranscriptMachine({ nextId: Stt.createIdSource(null) });
    machine.on("final", (payload) => events.push("final:" + payload.text));
    machine.on("interim", (payload) => events.push("interim:" + payload.text));
    machine.openTurn();
    machine.handleServerContent({ serverContent: { interimInputTranscription: { text: "대한건설에" } } });
    machine.handleServerContent({ serverContent: { inputTranscription: { text: "대한건설에 배관 100미터" } } });
    assert.equal(machine.state().committedCount, 0, "a segment alone is not a final");
    const committed = machine.handleServerContent({
      serverContent: { inputTranscription: { text: "대한건설에 배관 100미터, 미터당 18,000원", finished: true } }
    }).committed;
    assert.ok(committed && committed.utteranceId, "finish commits an utterance");
    assert.match(committed.text, /18,000원/, "final text is carried verbatim");
    assert.deepEqual(events, [
      "interim:대한건설에",
      "final:대한건설에 배관 100미터, 미터당 18,000원"
    ], "interim and final are separate signals");
    assert.equal(machine.state().open, false, "a committed turn is closed");
    const bleed = machine.handleServerContent({
      serverContent: { inputTranscription: { text: "늦게 도착한 이전 발화", finished: true } }
    });
    assert.equal(bleed.committed, null, "a frame after the turn closed cannot open a second submit");
  }

  /* --- stale generation is dropped, not merged --------------------------- */
  {
    const { Stt } = loadVoiceModules();
    const machine = Stt.createTranscriptMachine({ nextId: Stt.createIdSource(null) });
    machine.openTurn();
    const current = machine.state().generation;
    machine.segment("현재 발화", { generation: current });
    machine.segment("오래된 연결", { generation: current - 1 });
    assert.equal(machine.state().text, "현재 발화", "a stale generation cannot rewrite the slot");
    const committed = machine.finish({ generation: current - 1 });
    assert.equal(committed, null, "a stale generation cannot commit");
  }

  /* --- MODE A never reaches the interpreter ------------------------------ */
  {
    const t = setup("REVIEW");
    await t.controller.start();
    const committed = t.machine.handleServerContent({
      serverContent: { inputTranscription: { text: "배관 100미터, 미터당 18000원", finished: true } }
    }).committed;
    assert.ok(committed, "final committed");
    assert.equal(t.host.value, "배관 100미터, 미터당 18000원", "transcript is staged into the composer");
    assert.equal(t.host.log.length, 0, "MODE A must not call the quote path before the user sends");
    assert.equal(t.controller.getState(), "REVIEW_READY");
    assert.equal(t.controller.submittedCount(), 0);
  }

  /* --- MODE B sends exactly once, then waits for the answer -------------- */
  {
    const t = setup("AUTO");
    await t.controller.start();
    const first = t.machine.handleServerContent({
      serverContent: { inputTranscription: { text: "대한건설에 배관 100미터", finished: true } }
    }).committed;
    assert.ok(first && first.utteranceId, "MODE B commits the first utterance");
    assert.deepEqual(t.host.log, ["INPUT:대한건설에 배관 100미터"], "one submit through the existing path");
    assert.equal(t.controller.getState(), "B66_PROCESSING");
    assert.equal(t.controller.submittedCount(), 1);

    /* the same utterance can never be submitted twice, even if a finish repeats */
    const again = t.machine.handleServerContent({
      serverContent: { inputTranscription: { text: "대한건설에 배관 100미터", finished: true } }
    });
    assert.equal(again.committed, null);
    assert.equal(t.host.log.length, 1, "duplicate_final_submit=0");

    /* busy -> idle lets the next utterance through as its own turn. The composer
       is re-enabled before the ready signal, exactly as setInput does. */
    t.host.setBusy(true);
    t.host.setBusy(false);
    t.controller.onHostIdle();
    assert.equal(t.controller.getState(), "WAITING_NEXT_TURN");
    const second = t.machine.handleServerContent({
      serverContent: { inputTranscription: { text: "미터당 18000원, 부가세 별도", finished: true } }
    }).committed;
    assert.ok(second && second.utteranceId, "the next utterance commits its own turn");
    assert.deepEqual(t.host.log, [
      "INPUT:대한건설에 배관 100미터",
      "INPUT:미터당 18000원, 부가세 별도"
    ], "turns stay separate: no bleed, no merge");
    assert.notEqual(second.utteranceId, first.utteranceId,
      "each submit carries a distinct utterance id");
  }

  /* --- AUTO_SUBMIT_DURING_B66_PROCESSING = 0 ---------------------------- */
  {
    const t = setup("AUTO");
    await t.controller.start();
    t.host.setBusy(true);
    t.machine.handleServerContent({
      serverContent: { inputTranscription: { text: "단가 18000원", finished: true } }
    });
    assert.equal(t.host.log.length, 0, "no submit while B66 is processing");
    assert.equal(t.controller.submittedCount(), 0);
    assert.deepEqual(t.notices.map((n) => n.code), ["auto_submit_skipped_busy"]);
    assert.equal(t.controller.getState(), "REVIEW_READY", "the text survives as review material");
    t.host.setBusy(false);
    assert.equal(t.host.log.length, 0, "becoming idle must not flush a deferred submit");
  }

  /* --- an unsent transcript is never merged into the next auto-submit ----- */
  {
    const t = setup("AUTO");
    await t.controller.start();
    t.host.setBusy(true);
    t.machine.handleServerContent({
      serverContent: { inputTranscription: { text: "배관 100미터", finished: true } }
    });
    const turn = t.machine.state().open;
    assert.equal(turn, false, "the committed turn is closed");
    t.machine.openTurn();
    t.machine.handleServerContent({
      serverContent: { inputTranscription: { text: "단가 18000원", finished: true } }
    });
    assert.equal(t.host.log.length, 0, "no merged submit");
    assert.deepEqual(t.notices.map((n) => n.code), [
      "auto_submit_skipped_busy",
      "auto_submit_deferred_pending"
    ]);
    assert.equal(t.host.value, "배관 100미터 단가 18000원", "both transcripts stay visible and editable");
  }

  /* --- stop and cancel -------------------------------------------------- */
  {
    const t = setup("REVIEW");
    await t.controller.start();
    t.machine.handleServerContent({
      serverContent: { inputTranscription: { text: "배관 100미터", finished: true } }
    });
    const stopped = t.controller.stop({ discard: true });
    assert.equal(stopped.discarded, true);
    assert.equal(t.host.value, "", "cancel removes the staged transcript");
    assert.deepEqual(t.audio.calls, ["start", "stop"], "the microphone is released");
    assert.deepEqual(t.transport.calls, ["connect", "close"]);
    assert.equal(t.controller.getState(), "STOPPED");
  }

  /* --- typed text is preserved and nothing is auto-corrected ------------- */
  {
    const t = setup("REVIEW", { initial: "배관 100미터" });
    await t.controller.start();
    t.machine.handleServerContent({
      serverContent: { inputTranscription: { text: "미터당 18,000원", finished: true } }
    });
    assert.equal(t.host.value, "배관 100미터 미터당 18,000원", "voice appends instead of overwriting");
    assert.match(t.host.value, /18,000원/, "digits and separators survive verbatim");
  }

  /* --- permission denial is a visible stop, not a silent retry ----------- */
  {
    const { Stt, Voice } = loadVoiceModules();
    const host = createHost();
    const machine = Stt.createTranscriptMachine({ nextId: Stt.createIdSource(null) });
    const notices = [];
    const controller = Voice.createVoiceController({
      host,
      machine,
      transport: { connect: () => { const e = new Error("denied"); e.code = "microphone_denied"; return Promise.reject(e); }, close() {} },
      audio: { start: () => Promise.resolve({ started: true }), stop() {} },
      onNotice: (notice) => notices.push(notice)
    });
    const result = await controller.start();
    assert.equal(result.started, false);
    assert.equal(result.reason, "microphone_denied");
    assert.equal(controller.getState(), "ERROR");
    assert.deepEqual(notices.map((n) => n.code), ["microphone_denied"]);
    assert.equal(host.log.length, 0, "a denied microphone never reaches the quote path");
  }

  /* --- transport failure surfaces the notice and stops ------------------ */
  {
    const t = setup("AUTO");
    await t.controller.start();
    t.transport.handlers.onError({ code: "voice_connection_closed" });
    assert.equal(t.controller.getState(), "ERROR");
    assert.equal(t.controller.isLive(), false);
    assert.equal(t.host.log.length, 0);
  }

  /* --- browser fallback keeps the same final semantics ------------------ */
  {
    const t = setup("AUTO");
    await t.controller.start();
    /* a recognizer that reports isFinal frames without any generation metadata */
    t.machine.interim("부분 인식");
    t.machine.segment("전체 인식");
    const committed = t.machine.finish({});
    assert.equal(committed.text, "전체 인식");
    assert.deepEqual(t.host.log, ["INPUT:전체 인식"], "fallback finals behave like live finals");
  }

  /* --- PCM frame shape -------------------------------------------------- */
  {
    const { Stt } = loadVoiceModules();
    const chunks = [];
    const started = [];
    const audio = Stt.createPcmSource({
      mediaStreamFactory: async (constraints) => {
        started.push(constraints);
        return { getTracks: () => [{ stop() {} }] };
      },
      audioContextFactory: async () => ({
        createMediaStreamSource: () => ({ connect() {}, disconnect() {} }),
        createScriptProcessor: () => ({ onaudioprocess: null, connect() {}, disconnect() {} }),
        destination: {},
        close() {}
      }),
      onChunk: (chunk) => chunks.push(chunk)
    });
    const info = await audio.start();
    assert.equal(info.frameSamples, 1024);
    assert.equal(info.sampleRate, 16000);
    assert.equal(started[0].audio.channelCount, 1);
    assert.equal(started[0].audio.echoCancellation, true, "echo cancellation must be on");
    assert.equal(started[0].audio.noiseSuppression, true);
    const encoded = Stt.arrayBufferToBase64(Stt.float32ToInt16(new Float32Array([0, 0.5, -0.5, 1])).buffer);
    assert.equal(typeof encoded, "string");
    assert.ok(encoded.length > 0);
    audio.stop();
  }

  /* --- an empty turn is announced and never sent -------------------------- *
     CENTRAL §5: no auto-submit, an explicit notice, no claim that an older
     utterance was recovered. */
  {
    const t = setup("AUTO");
    await t.controller.start();
    t.machine.handleServerContent({ serverContent: { turnComplete: true } });
    assert.equal(t.host.log.length, 0, "nothing was transcribed, so nothing was sent");
    assert.deepEqual(t.notices.map((n) => n.code), ["turn_empty"], "the user is told the turn was empty");
    assert.equal(t.controller.submittedCount(), 0);
    assert.equal(t.host.value, "", "no stale text is presented as this turn's result");
    /* a following real utterance still behaves normally */
    t.machine.openTurn();
    t.machine.handleServerContent({
      serverContent: { inputTranscription: { text: "배관 100미터", finished: true } }
    });
    assert.deepEqual(t.host.log, ["INPUT:배관 100미터"], "the next utterance is unaffected");
  }

  /* --- a mid-session failure tears the mic and the session down ------------ */
  {
    const t = setup("AUTO");
    await t.controller.start();
    t.machine.handleServerContent({
      serverContent: { inputTranscription: { text: "배관 100미터", finished: true } }
    });
    assert.deepEqual(t.host.log, ["INPUT:배관 100미터"], "the first utterance went through");
    t.transport.handlers.onError({ code: "voice_connection_closed" });
    assert.equal(t.controller.getState(), "ERROR");
    assert.equal(t.controller.isLive(), false);
    assert.deepEqual(t.audio.calls, ["start", "stop"], "the microphone is released on failure");
    assert.deepEqual(t.transport.calls, ["connect", "close"], "the session is closed on failure");
    /* and a late frame from the dead session cannot smuggle a second submit */
    t.machine.openTurn();
    t.machine.handleServerContent({
      serverContent: { inputTranscription: { text: "미터당 18000원", finished: true } }
    });
    assert.equal(t.host.log.length, 1, "no auto-submit after the session died");
    assert.equal(t.host.value, "", "and the late text is not staged either");
    assert.equal(t.controller.submittedCount(), 1);
    assert.ok(t.notices.map((n) => n.code).includes("late_transcript_dropped"),
      "the drop is announced, never silent");
  }

  /* --- the announced notice for each failure family is real text ---------- */
  {
    const { Voice } = loadVoiceModules();
    for (const code of ["turn_empty", "browser_stt_not_allowed", "browser_stt_network",
      "browser_stt_service_not_allowed", "browser_stt_language_not_supported",
      "browser_stt_restart_limit", "sdk_unavailable", "sdk_live_unsupported",
      "voice_token_unavailable", "voice_token_missing", "voice_connection_failed",
      "voice_connection_closed", "fallback_browser_stt", "late_transcript_dropped",
      "auto_submit_skipped_busy", "auto_submit_deferred_pending", "duplicate_utterance_suppressed"]) {
      assert.equal(typeof Voice.NOTICE_TEXT[code], "string", `${code} has an announcement`);
      assert.ok(Voice.NOTICE_TEXT[code].length > 8, `${code} announcement is not a placeholder`);
      assert.equal(Voice.NOTICE_TEXT[code].includes("http"), false, `${code} says no URLs`);
    }
  }

  console.log("B66_VOICE_INPUT=PASS");
}

main().catch((error) => {
  console.error("B66_VOICE_INPUT=FAIL");
  console.error(error && error.stack ? error.stack : String(error));
  process.exit(1);
});
