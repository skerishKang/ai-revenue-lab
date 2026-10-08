/* B66 voice lane (#3404) — Live API frame shapes, session lifetime and fallback.
   The socket, the token endpoint and the recognizer are all fakes: no provider
   request is possible from this file. */
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const SRC = path.join(__dirname, "..");

function loadStt() {
  const sandbox = {
    window: {},
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
    Map,
    Uint8Array,
    Int16Array,
    Float32Array,
    ArrayBuffer,
    Buffer,
    encodeURIComponent,
    btoa: (value) => Buffer.from(value, "binary").toString("base64")
  };
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(path.join(SRC, "voice-stt.js"), "utf8"), sandbox);
  return sandbox.window.B66VoiceStt;
}

function fakeSocket() {
  const sent = [];
  return {
    sent,
    closed: 0,
    onopen: null,
    onmessage: null,
    onerror: null,
    onclose: null,
    send(data) { sent.push(JSON.parse(data)); },
    close() { this.closed += 1; }
  };
}

function tokenResponse(body) {
  return {
    ok: true,
    json: async () => Object.assign({
      ok: true,
      token: "ephemeral-token-value",
      websocketUrl: "wss://generativelanguage.googleapis.com/ws/x.BidiGenerateContent",
      model: "gemini-3.5-transcribe-live",
      languageCodes: [],
      silenceDurationMs: 650
    }, body || {})
  };
}

async function main() {
  const Stt = loadStt();

  /* --- setup frame ------------------------------------------------------- */
  {
    const frame = Stt.buildSetupFrame({ model: "gemini-3.5-transcribe-live", languageCodes: ["ko-KR"] });
    assert.equal(frame.setup.model, "models/gemini-3.5-transcribe-live", "model is namespaced");
    assert.deepEqual(frame.setup.responseModalities, ["TEXT"], "transcription only: no answer modality");
    assert.equal(frame.setup.inputAudioTranscription.mode, "VERBATIM");
    assert.deepEqual(frame.setup.inputAudioTranscription.languageCodes, ["ko-KR"]);
    assert.equal(frame.setup.realtimeInputConfig.automaticActivityDetection.silenceDurationMs, 650);
    assert.equal(JSON.stringify(frame).includes("translationConfig"), false, "no translation surface");
    assert.equal(Stt.buildSetupFrame({ model: "gemini-3.5-transcribe-live" }).setup.model.startsWith("models/"), true);
    assert.throws(() => Stt.buildSetupFrame({ model: "" }), /stt_model_unspecified/);
    const clamped = Stt.buildSetupFrame({ model: "m", silenceDurationMs: 999999 });
    assert.equal(clamped.setup.realtimeInputConfig.automaticActivityDetection.silenceDurationMs, 10000);
    const vocabulary = Stt.buildSetupFrame({ model: "m", customVocabulary: Array.from({ length: 400 }, (_, i) => "t" + i) });
    assert.equal(vocabulary.setup.inputAudioTranscription.customVocabulary.length, 100, "vocabulary stays bounded");
  }

  /* --- audio frame is the current shape, not the deprecated one ---------- */
  {
    const frame = Stt.buildAudioFrame({ data: "AAECAw==", mimeType: "audio/pcm;rate=16000" });
    assert.deepEqual(frame, { realtimeInput: { audio: { data: "AAECAw==", mimeType: "audio/pcm;rate=16000" } } });
    assert.equal(JSON.stringify(frame).includes("mediaChunks"), false, "mediaChunks is deprecated upstream");
    assert.equal(Stt.buildAudioFrame({ data: "" }), null, "an empty chunk is never sent");
    assert.equal(Stt.buildAudioFrame(null), null);
  }

  /* --- live transport: one session carries many turns -------------------- */
  {
    const machine = Stt.createTranscriptMachine({ nextId: Stt.createIdSource(null) });
    const socket = fakeSocket();
    const notices = [];
    const fetchCalls = [];
    const transport = Stt.createLiveTransport({
      machine,
      onNotice: (notice) => notices.push(notice),
      fetcher: (url, init) => { fetchCalls.push({ url, init }); return Promise.resolve(tokenResponse()); },
      socketFactory: (url) => { transport.url = url; return socket; }
    });
    const turns = [];
    /* The controller owns turn lifecycle, so the harness mirrors it: open on start,
       open again when a turn ends. */
    const pending = transport.connect({
      onTurnEnd: () => { turns.push(machine.state().generation); machine.openTurn(); },
      onError: (e) => notices.push(e)
    });
    /* the grant is fetched before the socket exists, so let that await settle */
    await new Promise((resolve) => setImmediate(resolve));
    socket.onopen();
    await pending;
    machine.openTurn();
    assert.equal(fetchCalls.length, 1, "the token is fetched once per session");
    assert.equal(fetchCalls[0].url, "/api/b66/voice/token");
    assert.match(transport.url, /access_token=ephemeral-token-value$/, "the grant rides on the socket URL");
    assert.equal(machine.state().open, true, "the first turn is open after connect");
    assert.equal(socket.sent[0].setup.responseModalities[0], "TEXT");

    socket.onmessage({ data: JSON.stringify({ setupComplete: true }) });
    socket.onmessage({ data: JSON.stringify({ serverContent: { interimInputTranscription: { text: "대한건설에" } } }) });
    socket.onmessage({ data: JSON.stringify({ serverContent: { inputTranscription: { text: "대한건설에 배관 100미터" } } }) });
    assert.equal(machine.state().committedCount, 0, "a segment alone is not a turn end");
    socket.onmessage({ data: JSON.stringify({ serverContent: { turnComplete: true } }) });
    assert.equal(machine.state().committedCount, 1, "turnComplete commits the utterance");
    assert.equal(socket.closed, 0, "the session survives the turn: one token, many utterances");
    assert.equal(transport.connects(), 1);
    assert.equal(turns.length, 1, "the controller was told the turn ended");

    /* second utterance on the same socket */
    socket.onmessage({ data: JSON.stringify({ serverContent: { inputTranscription: { text: "미터당 18,000원" } } }) });
    socket.onmessage({ data: JSON.stringify({ serverContent: { turnComplete: true } }) });
    assert.equal(machine.state().committedCount, 2, "second utterance is its own commit");
    assert.equal(fetchCalls.length, 1, "no extra token was spent mid-conversation");
    assert.equal(socket.closed, 0);

    transport.sendAudio({ data: "AA==", mimeType: "audio/pcm;rate=16000" });
    assert.equal(socket.sent.length, 2);

    socket.onmessage({ data: "not json at all" });
    assert.deepEqual(notices.map((n) => n.code).filter(Boolean), ["voice_response_unparsable"], "unparsable frames are bounded notices");
    socket.onmessage({ data: JSON.stringify({ serverContent: {}, goAway: { timeLeft: "10s" } }) });
    assert.ok(notices.map((n) => n.code).includes("voice_session_expiring"), "goAway is announced");
    assert.equal(socket.closed, 1, "the service ending the session closes it");
    assert.equal(transport.sendAudio({ data: "AA==" }).sent, false, "audio stops after close");
  }

  /* --- token failure is fatal for the session, not retried --------------- */
  {
    const machine = Stt.createTranscriptMachine({});
    let calls = 0;
    const transport = Stt.createLiveTransport({
      machine,
      fetcher: () => { calls += 1; return Promise.resolve({ ok: false, status: 401, json: async () => ({}) }); },
      socketFactory: () => fakeSocket()
    });
    await assert.rejects(transport.connect({ onError: () => {} }), /voice_token_unavailable/);
    assert.equal(calls, 1, "a refused grant is not retried");
  }

  /* --- missing grant fields never become a partial session --------------- */
  {
    const transport = Stt.createLiveTransport({
      machine: Stt.createTranscriptMachine({}),
      fetcher: () => Promise.resolve({ ok: true, json: async () => ({ ok: true }) }),
      socketFactory: () => fakeSocket()
    });
    await assert.rejects(transport.connect({ onError: () => {} }), /voice_token_unavailable/);
  }

  /* --- fallback: explicit, once, and it does not replay audio ------------ */
  {
    const machine = Stt.createTranscriptMachine({ nextId: Stt.createIdSource(null) });
    const notices = [];
    const sockets = [];
    const failing = {
      connect() { const e = new Error("nope"); e.code = "voice_token_unavailable"; throw e; }
    };
    const chain = Stt.createFallbackChainTransport({
      machine,
      onNotice: (notice) => notices.push(notice),
      primaryFactory: () => failing,
      fallbackFactory: (context) => Stt.createBrowserFallbackTransport({
        machine: context.machine,
        recognizerFactory: () => {
          const recognizer = {
            continuous: false, interimResults: false, lang: "",
            onresult: null, onend: null, onerror: null, started: 0, stopped: 0,
            start() { this.started += 1; }, stop() { this.stopped += 1; }
          };
          sockets.push(recognizer);
          return recognizer;
        }
      })
    });
    await chain.connect({
      onTurnEnd: () => machine.openTurn(),
      onReconnected: () => machine.openTurn(),
      onError: (e) => notices.push(e)
    });
    assert.equal(chain.usedFallback(), true, "the downgrade happened");
    assert.deepEqual(notices.map((n) => n.code), ["fallback_browser_stt"], "the downgrade was announced");
    const recognizer = sockets[0];
    assert.equal(recognizer.started, 1);
    assert.equal(recognizer.continuous, true);
    assert.equal(recognizer.interimResults, true);
    assert.equal(chain.sendAudio({ data: "AA==" }).sent, false, "no audio is replayed into the fallback");
    /* a real SpeechRecognitionResultList: results[i] is the result, results[i][0] the alternative */
    recognizer.onresult({ results: [{ 0: { transcript: "단가 18000원" }, isFinal: true }] });
    recognizer.onend();
    assert.equal(machine.state().committedCount, 1, "fallback produces a normal final");
    assert.equal(machine.state().text, "", "the committed turn is closed");
  }

  /* --- a runtime live failure downgrades once and keeps the session ------- */
  {
    const machine = Stt.createTranscriptMachine({});
    const notices = [];
    let fallbackUses = 0;
    const chain = Stt.createFallbackChainTransport({
      machine,
      onNotice: (notice) => notices.push(notice),
      primaryFactory: ({ machine: scoped, }) => ({
        connect(handlers) { chain.liveHandlers = handlers; return Promise.resolve({ connected: true }); },
        sendAudio: () => ({ sent: true }),
        close() {}
      }),
      fallbackFactory: (context) => {
        fallbackUses += 1;
        return {
          connect() { return Promise.resolve({ connected: true }); },
          sendAudio: () => ({ sent: false }),
          close() {}
        };
      }
    });
    await chain.connect({
      onError: (e) => notices.push({ code: String(e && e.code) }),
      onTurnEnd: () => machine.openTurn(),
      onReconnected: () => machine.openTurn()
    });
    machine.openTurn();
    chain.liveHandlers.onError({ code: "voice_connection_closed" });
    /* the fallback connects asynchronously, so the reopened turn lands a tick later */
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(fallbackUses, 1, "exactly one downgrade");
    assert.deepEqual(notices.map((n) => n.code), ["fallback_browser_stt"]);
    assert.equal(machine.state().open, true, "a fresh turn was opened after the reset");
  }

  /* --- no fallback engine available is a plain error -------------------- */
  {
    const chain = Stt.createFallbackChainTransport({
      machine: Stt.createTranscriptMachine({}),
      onNotice: () => {},
      primaryFactory: () => ({
        connect(handlers) { handlers.onError({ code: "voice_connection_closed" }); return Promise.resolve({}); },
        close() {}
      }),
      fallbackFactory: null
    });
    const seen = [];
    await chain.connect({ onError: (e) => seen.push(String(e.code)), onTurnEnd: () => {} });
    assert.deepEqual(seen, ["voice_connection_closed"], "with no fallback the failure surfaces as-is");
  }

  console.log("B66_VOICE_STT=PASS");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
