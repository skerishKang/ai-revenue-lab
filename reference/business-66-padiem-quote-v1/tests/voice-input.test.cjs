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

/* A transport whose connect() stays pending until the test releases it, which is the
   window CENTRAL reproduced both defects inside: a second press, or a stop, while the
   session handshake is still open. */
function slowTransport() {
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  const transport = {
    connects: 0,
    closes: 0,
    handlers: null,
    connect(handlers) {
      transport.connects += 1;
      transport.handlers = handlers;
      return gate.then(() => ({ connected: true }));
    },
    sendAudio() {},
    close() { transport.closes += 1; },
    release() { release(); }
  };
  return transport;
}

function countingAudio() {
  return {
    starts: 0,
    stops: 0,
    async start() { this.starts += 1; return { started: true }; },
    stop() { this.stops += 1; }
  };
}

function setupSlow(mode) {
  const { Stt, Voice } = loadVoiceModules();
  const host = createHost();
  const machine = Stt.createTranscriptMachine({ nextId: Stt.createIdSource(null) });
  const transport = slowTransport();
  const audio = countingAudio();
  const notices = [];
  const controller = Voice.createVoiceController({
    host, machine, mode, transport, audio,
    onNotice: (notice) => notices.push(notice)
  });
  return { Stt, Voice, host, machine, transport, audio, controller, notices };
}

/* Each connect() call gets its own gate, so a test can land attempt 1 after attempt 2 has
   already started — the ordering CENTRAL asked to be proven safe. */
function steppableTransport() {
  const gates = [];
  const handlers = [];
  const transport = {
    connects: 0,
    closes: 0,
    handlers,
    connect(handlers2) {
      const gate = { resolve: null };
      const promise = new Promise((resolve) => { gate.resolve = resolve; });
      gates.push(gate);
      handlers.push(handlers2);
      transport.connects += 1;
      return promise.then(() => ({ connected: true }));
    },
    sendAudio() {},
    close() { transport.closes += 1; },
    settle(index) { gates[index].resolve(); }
  };
  return transport;
}

function setupSteps(mode) {
  const { Stt, Voice } = loadVoiceModules();
  const host = createHost();
  const machine = Stt.createTranscriptMachine({ nextId: Stt.createIdSource(null) });
  const transport = steppableTransport();
  const audio = countingAudio();
  const notices = [];
  const controller = Voice.createVoiceController({
    host, machine, mode, transport, audio,
    onNotice: (notice) => notices.push(notice)
  });
  return { Stt, Voice, host, machine, transport, audio, controller, notices };
}

/* The minimum DOM surface createDomBindings needs, so a physical double press is
   tested through the same handler the page uses. */
function fakeElement() {
  const listeners = [];
  return {
    listeners,
    attrs: {},
    pressed: [],
    addEventListener(type, handler) { if (type === "click") listeners.push(handler); },
    setAttribute(name, value) { this.attrs[name] = value; if (name === "aria-pressed") this.pressed.push(value); },
    getAttribute(name) { return this.attrs[name]; },
    classList: { toggle() {} }
  };
}

function fakeDocument() {
  const elements = {
    easyVoiceMic: fakeElement(),
    easyVoiceStatus: fakeElement(),
    easyVoiceModeReview: fakeElement(),
    easyVoiceModeAuto: fakeElement()
  };
  elements.easyVoiceStatus.hidden = true;
  elements.easyVoiceStatus.textContent = "";
  elements.easyVoiceStatus.append = undefined;
  return {
    elements,
    addEventListener() {},
    getElementById: (id) => elements[id] || null
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

  /* --- CENTRAL defect 1: a press while connecting must not double-connect -- */
  {
    const t = setupSlow("REVIEW");
    const first = t.controller.start();
    /* Do not await the second press before releasing the handshake: an unfixed
       implementation leaves it pending, and a pending await is how a suite goes
       silently green. Record what it settles to instead. */
    let secondOutcome = "PENDING";
    const second = t.controller.start().then(
      (result) => { secondOutcome = result; },
      (error) => { secondOutcome = { thrown: String(error && error.message) }; }
    );
    t.transport.release();
    const firstResult = await first;
    await second;
    assert.equal(firstResult.started, true, "the original attempt completes");
    assert.deepEqual(secondOutcome, { started: false, reason: "already_connecting" },
      "a press while connecting opens no second session");
    assert.equal(t.transport.connects, 1, "connect() ran exactly once for two presses");
    assert.equal(t.audio.starts, 1, "audio.start() ran exactly once for two presses");
    assert.equal(t.controller.getState(), "LISTENING");
  }

  /* --- CENTRAL defect 1 through the page handler: double click ------------- */
  {
    const base = setupSlow("REVIEW");
    const doc = fakeDocument();
    base.Voice.createDomBindings({
      document: doc, host: base.host, controller: base.controller
    });
    const click = () => doc.elements.easyVoiceMic.listeners[0]();
    const first = click();
    const second = click();
    base.transport.release();
    await first;
    await second;
    assert.equal(base.transport.connects, 1, "two physical presses open one session");
    assert.equal(base.audio.starts, 0,
      "the second press reads as a stop, so capture never opens twice");
    assert.equal(base.controller.getState(), "STOPPED", "and the page ends stopped, not listening");
    const pressed = doc.elements.easyVoiceMic.pressed;
    assert.equal(pressed[0], "true", "the first press arms the microphone");
    assert.equal(pressed.filter((value) => value === "true").length, 1,
      "only the first press ever marks the microphone as live");
    assert.equal(pressed.slice(1).every((value) => value === "false"), true,
      "after the cancel the icon only ever reads off, so it cannot lie");
  }

  /* --- CENTRAL defect 2: stop during connect must not return to LISTENING -- */
  {
    const t = setupSlow("REVIEW");
    const pending = t.controller.start();
    t.controller.stop({ discard: false });
    assert.equal(t.controller.getState(), "STOPPED", "stop is authoritative immediately");
    t.transport.release();
    const result = await pending;
    assert.equal(result.started, false, "a connect that lands after stop does not start");
    assert.equal(result.reason, "stopped_while_connecting");
    assert.equal(t.controller.getState(), "STOPPED",
      "the delayed handshake must not resurrect LISTENING");
    assert.equal(t.controller.isLive(), false);
    assert.equal(t.audio.starts, 0, "capture is never opened for an abandoned attempt");
    /* Exactly one close: the user's stop. The session that lands late is closed by the
       transport that opened it — proven in tests/voice-stt.test.cjs, because after stop the
       controller no longer owns these resources and must not reach in. */
    assert.equal(t.transport.closes, 1, "the retired attempt does not close on behalf of others");
    /* and the mic is genuinely usable again afterwards */
    const retry = await t.controller.start();
    assert.equal(retry.started, true, "a later press starts a fresh session");
    assert.equal(t.transport.connects, 2);
  }

  /* --- a failure that lands after stop is reported as the stop ------------- */
  {
    const t = setupSlow("REVIEW");
    const pending = t.controller.start();
    t.controller.stop({ discard: false });
    t.transport.handlers.onError({ code: "voice_connection_closed" });
    assert.equal(t.controller.getState(), "STOPPED", "stop wins over a late error immediately");
    assert.deepEqual(t.notices.map((n) => n.code), [],
      "and the abandoned attempt raises no false alarm");
    t.transport.release();
    const result = await pending;
    assert.equal(result.started, false, "the abandoned attempt never reports success");
    assert.equal(t.controller.getState(), "STOPPED");
  }

  /* --- CENTRAL 1B: a superseded attempt may not disturb the newer one ----- */
  {
    const t = setupSteps("REVIEW");
    const first = t.controller.start();
    t.controller.stop({ discard: false });
    /* What the user's own stop already did; a retired attempt must add nothing here. */
    const closesAfterUserStop = t.transport.closes;
    const stopsAfterUserStop = t.audio.stops;
    assert.ok(closesAfterUserStop >= 1, "the stop itself closed the transport");
    const second = t.controller.start();
    t.transport.settle(0);
    const firstResult = await first;
    assert.deepEqual(firstResult, { started: false, reason: "stopped_while_connecting" });
    assert.equal(t.transport.closes, closesAfterUserStop,
      "only the user's stop closed a session; the retired attempt did not kill the new one");
    assert.equal(t.audio.stops, stopsAfterUserStop,
      "and it did not stop the new attempt's capture either");
    assert.equal(t.controller.getState(), "TRANSCRIBING",
      "the newer attempt is still connecting, not cancelled by the older one");
    assert.equal(t.controller.isConnecting(), true, "and still owns the connecting flag");
    t.transport.settle(1);
    const secondResult = await second;
    assert.equal(secondResult.started, true, "the newer attempt completes normally");
    assert.equal(t.audio.starts, 1, "capture started exactly once, for the newer attempt");
    assert.equal(t.controller.getState(), "LISTENING");
    assert.equal(t.controller.isLive(), true);
  }

  /* --- CENTRAL 1B: a retired click may not rewrite the microphone icon --- */
  {
    const base = setupSteps("REVIEW");
    const doc = fakeDocument();
    base.Voice.createDomBindings({
      document: doc, host: base.host, controller: base.controller
    });
    const mic = doc.elements.easyVoiceMic;
    const click = () => mic.listeners[mic.listeners.length - 1]();
    const attempt1 = click();
    base.controller.stop({ discard: false });
    const attempt3 = click();
    base.transport.settle(0);
    await attempt1;
    assert.equal(mic.attrs["aria-pressed"], "true",
      "the retired first click did not write a false over the live session's icon");
    base.transport.settle(1);
    await attempt3;
    assert.equal(mic.attrs["aria-pressed"], "true", "and the current session still reads live");
    assert.equal(base.controller.isLive(), true);
  }

  /* --- CENTRAL 1C: a fatal error during connect voids that attempt ------- */
  {
    const t = setupSteps("REVIEW");
    const pending = t.controller.start();
    let outcome = "PENDING";
    pending.then((value) => { outcome = value; });
    t.transport.handlers[0].onError({ code: "voice_connection_closed" });
    assert.equal(t.controller.getState(), "ERROR", "the error is reported immediately");
    t.transport.settle(0);
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(t.controller.getState(), "ERROR",
      "and the late handshake completion cannot return to LISTENING");
    assert.deepEqual(outcome, { started: false, reason: "voice_connection_closed" });
    assert.equal(t.audio.starts, 0, "capture is never opened after the fatal error");
    assert.equal(t.controller.isLive(), false);
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

/* A pending await that never settles would end the process with no output and exit code 0,
   which is a silent false green. The watchdog turns "it hung" into a loud failure. */
const watchdog = setTimeout(() => {
  console.error("B66_VOICE_INPUT=TIMEOUT");
  console.error("MEANING=main() never settled; an await has neither resolved nor rejected");
  process.exit(1);
}, 30000);

main().then(
  () => clearTimeout(watchdog),
  (error) => {
    clearTimeout(watchdog);
    console.error("B66_VOICE_INPUT=FAIL");
    console.error(error && error.stack ? error.stack : String(error));
    process.exit(1);
  }
);
