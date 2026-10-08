/* B66 voice lane (#3404) — the SDK owns the Gemini Live protocol; this file proves
   this lane does not re-implement it, and proves the ported reference behaviour.
   The SDK module, the token endpoint and the recognizer are all fakes: no provider
   request is possible from this file. */
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const SRC = path.join(__dirname, "..");
const STT_SOURCE = fs.readFileSync(path.join(SRC, "voice-stt.js"), "utf8");

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
  vm.runInContext(STT_SOURCE, sandbox);
  return sandbox.window.B66VoiceStt;
}

function grant(body) {
  return {
    ok: true,
    json: async () => Object.assign({
      ok: true,
      token: "auth_tokens/ephemeral-grant",
      model: "gemini-3.5-transcribe-live",
      apiVersion: "v1alpha",
      languageCodes: ["ko-KR"],
      transcriptionMode: "VERBATIM",
      silenceDurationMs: 650,
      expiresAt: "2026-10-08T12:00:00.000Z"
    }, body || {})
  };
}

/* The fake stands in for the pinned bundle: it records the public API call shape this
   lane makes, which is exactly the contract the real SDK turns into wire frames. */
function fakeSdk() {
  const calls = { clients: [], connects: [], sent: [], closed: 0 };
  class GoogleGenAI {
    constructor(options) {
      calls.clients.push(options);
      this.live = {
        connect: async (params) => {
          calls.connects.push(params);
          params.callbacks.onopen();
          return {
            sendRealtimeInput: (input) => { calls.sent.push(input); },
            close: () => { calls.closed += 1; }
          };
        }
      };
    }
  }
  return { calls, module: { GoogleGenAI } };
}

function fakeRecognizer() {
  return {
    continuous: false, interimResults: false, lang: "",
    onstart: null, onresult: null, onend: null, onerror: null,
    starts: 0, stops: 0,
    start() { this.starts += 1; },
    stop() { this.stops += 1; }
  };
}

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

/* A fake bundle whose live.connect() stays pending, so a session can arrive after the
   caller has already cancelled — the case that must leak nothing. */
function pendingSdk() {
  const calls = { clients: [], connects: [], sent: [], sessions: [] };
  const pending = deferred();
  class GoogleGenAI {
    constructor(options) {
      calls.clients.push(options);
      this.live = {
        connect: async (params) => {
          calls.connects.push(params);
          const session = {
            closed: 0,
            sendRealtimeInput: (input) => { calls.sent.push(input); },
            close: () => { session.closed += 1; }
          };
          calls.sessions.push(session);
          calls.params = params;
          return pending.promise;
        }
      };
    }
  }
  return {
    calls,
    module: { GoogleGenAI },
    settle() { return pending.resolve(calls.sessions[calls.sessions.length - 1]); },
    fail(error) { return pending.reject(error); }
  };
}

function fakeTimers() {
  const due = [];
  return {
    due,
    setTimeout: (fn, ms) => { due.push({ fn, ms }); return due.length - 1; },
    clearTimeout: (id) => { if (due[id]) due[id] = { fn: null, ms: 0, cleared: true }; }
  };
}

async function tick() {
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));
}

async function main() {
  const Stt = loadStt();

  /* --- CENTRAL 1A: a cancellation is never answered by switching engines -- */
  {
    const machine = Stt.createTranscriptMachine({});
    let fallbackUses = 0;
    const notices = [];
    const errors = [];
    const chain = Stt.createFallbackChainTransport({
      machine,
      onNotice: (notice) => notices.push(notice.code),
      primaryFactory: () => ({
        connect() {
          const error = new Error("cancelled");
          error.code = "voice_connect_cancelled";
          return Promise.reject(error);
        },
        sendAudio: () => ({ sent: false }),
        close() {}
      }),
      fallbackFactory: () => {
        fallbackUses += 1;
        return {
          connect: () => Promise.resolve({ connected: true }),
          sendAudio: () => ({ sent: false }),
          close() {}
        };
      }
    });
    await assert.rejects(
      chain.connect({ onError: (e) => errors.push(e.code), onTurnEnd: () => {}, onReconnected: () => {} }),
      (error) => error.code === "voice_connect_cancelled"
    );
    assert.equal(fallbackUses, 0, "a cancelled handshake does not buy a browser engine");
    assert.deepEqual(notices, [], "and nothing is announced as a downgrade");
    assert.deepEqual(errors, [],
      "a rejected connect is reported once, through the rejection, not also as a callback");
  }

  {
    const machine = Stt.createTranscriptMachine({});
    let fallbackUses = 0;
    const notices = [];
    const chain = Stt.createFallbackChainTransport({
      machine,
      onNotice: (notice) => notices.push(notice.code),
      primaryFactory: () => ({
        connect(handlers) { chain.handlers = handlers; return Promise.resolve({ connected: true }); },
        sendAudio: () => ({ sent: true }),
        close() {}
      }),
      fallbackFactory: () => {
        fallbackUses += 1;
        return {
          connect: () => Promise.resolve({ connected: true }),
          sendAudio: () => ({ sent: false }),
          close() {}
        };
      }
    });
    await chain.connect({ onError: () => {}, onTurnEnd: () => {}, onReconnected: () => {} });
    chain.handlers.onError({ code: "voice_connect_cancelled" });
    await tick();
    assert.equal(fallbackUses, 0, "a cancellation reported mid-session also stops there");
    assert.deepEqual(notices, []);
  }

  /* --- this lane must not hand-assemble the protocol --------------------- *
     These assertions are about OUR source, not about what the service accepts:
     the wire contract belongs to the pinned SDK, so a hand-built frame here is
     a duplicate implementation regardless of which field name is current.
     `realtimeInputConfig` / `inputAudioTranscription` are legitimate SDK *config*
     keys (upstream passes them too), so the guard names frame assembly and socket
     plumbing instead of any field the Live API happens to use. */
  {
    for (const forbidden of ["WebSocket", "wss://", "BidiGenerateContent", "realtimeInput:",
      "mediaChunks", "access_token", "setupComplete", "goAway"]) {
      assert.equal(STT_SOURCE.includes(forbidden), false,
        `voice-stt.js must not hand-roll the protocol: found ${forbidden}`);
    }
    assert.equal(STT_SOURCE.includes("live.connect("), true, "the SDK session call is used");
    assert.equal(STT_SOURCE.includes("sendRealtimeInput("), true, "audio goes through the SDK");
    assert.equal(STT_SOURCE.includes("apiVersion: SDK_API_VERSION"), true,
      "the ephemeral grant is paired with the version the SDK requires");
    assert.equal(Stt.SDK_API_VERSION, "v1alpha");
    assert.equal(Stt.SDK_ARTIFACT_PATH.startsWith("/vendor/"), true, "same-origin artifact only");
    assert.equal(/https?:\/\/[^"'\s]*(cdn|jsdelivr|unpkg|esm\.sh)/i.test(STT_SOURCE), false,
      "no runtime CDN import");
  }

  /* --- ported reference helpers keep upstream behaviour ------------------ */
  {
    assert.equal(Stt.mergeLiveTranscriptChunk("", "배관 100미터"), "배관 100미터");
    assert.equal(Stt.mergeLiveTranscriptChunk("배관", ""), "배관", "an empty chunk changes nothing");
    assert.equal(Stt.mergeLiveTranscriptChunk("대한건설에", "대한건설에 배관"),
      "대한건설에 배관", "a cumulative hypothesis replaces the shorter prefix");
    assert.equal(Stt.mergeLiveTranscriptChunk("배관 100미터", "100미터"),
      "배관 100미터", "a trailing chunk already present is not appended twice");
    assert.equal(Stt.mergeLiveTranscriptChunk("미터당", "18000원"), "미터당18000원",
      "a true delta is appended");

    const pcm = Stt.float32ToInt16(new Float32Array([0, 0.5, -0.5, 1, -1, 2]));
    assert.deepEqual(Array.from(pcm), [0, 16383, -16384, 32767, -32768, 32767],
      "clamping and scaling match audioUtils.ts:23-31");
    const encoded = Stt.arrayBufferToBase64(pcm.buffer);
    assert.equal(encoded, Buffer.from(pcm.buffer).toString("base64"),
      "base64 fidelity of exactly these bytes (audioUtils.ts:13-21)");
    assert.equal(Buffer.from(encoded, "base64").readInt16LE(2), 16383,
      "Int16 little-endian on the wire, 16 kHz mono");
    assert.equal(Buffer.from(encoded, "base64").readInt16LE(4), -16384);
  }

  /* --- a delta stream keeps every word it was given ---------------------- *
     This is the case the ported merge exists for: a backend that sends only the
     newest slice would otherwise lose everything before it. */
  {
    const machine = Stt.createTranscriptMachine({ nextId: Stt.createIdSource(null) });
    const finals = [];
    machine.on("final", (payload) => finals.push(payload));
    machine.openTurn();
    machine.handleServerContent({ serverContent: { inputTranscription: { text: "대한건설에" } } });
    machine.handleServerContent({ serverContent: { inputTranscription: { text: " 배관 100미터" } } });
    machine.handleServerContent({ serverContent: { inputTranscription: { text: ", 미터당 18000원" } } });
    machine.handleServerContent({ serverContent: { turnComplete: true } });
    assert.equal(finals.length, 1, "one commit for the turn");
    assert.equal(finals[0].text, "대한건설에 배관 100미터, 미터당 18000원",
      "every delta survives to the final");
  }

  /* --- SDK config is the transcription-only contract --------------------- */
  {
    const config = Stt.buildTranscribeConfig({ languageCodes: ["ko-KR"], silenceDurationMs: 650 });
    assert.deepEqual(config.responseModalities, ["TEXT"], "transcription only: no answer modality");
    assert.equal(config.inputAudioTranscription.mode, "VERBATIM");
    assert.deepEqual(config.inputAudioTranscription.languageCodes, ["ko-KR"]);
    assert.equal(config.realtimeInputConfig.automaticActivityDetection.silenceDurationMs, 650);
    assert.equal(JSON.stringify(config).includes("translationConfig"), false, "no translation surface");
    assert.equal(JSON.stringify(config).includes("AUDIO"), false, "never asks the service to speak");
    assert.equal(Stt.buildTranscribeConfig({ silenceDurationMs: 999999 })
      .realtimeInputConfig.automaticActivityDetection.silenceDurationMs, 10000, "silence stays bounded");
    const vocabulary = Stt.buildTranscribeConfig({
      customVocabulary: Array.from({ length: 400 }, (_, i) => "t" + i)
    });
    assert.equal(vocabulary.inputAudioTranscription.customVocabulary.length, 100,
      "vocabulary stays bounded, like upstream's Set + slice(0, 100)");
    assert.deepEqual(Stt.buildTranscribeConfig({ customVocabulary: ["배관", "배관", "미터당", "미터당"] })
      .inputAudioTranscription.customVocabulary, ["배관", "미터당"], "vocabulary is deduplicated");
    assert.deepEqual(Stt.buildTranscribeConfig({ customVocabulary: ["", "배관"] })
      .inputAudioTranscription.customVocabulary, ["배관"], "an empty term is never sent");
    const truncated = Stt.buildTranscribeConfig({ customVocabulary: ["배".repeat(100)] })
      .inputAudioTranscription.customVocabulary;
    assert.equal(truncated[0].length, 64, "B66 bounds one term to 64 chars");
    assert.equal(Stt.buildTranscribeConfig({}).inputAudioTranscription.languageCodes.length, 0);
  }

  /* --- connect hands the grant to the SDK, one session carries many turns - */
  {
    const machine = Stt.createTranscriptMachine({ nextId: Stt.createIdSource(null) });
    const sdk = fakeSdk();
    const fetchCalls = [];
    const turns = [];
    const notices = [];
    const transport = Stt.createSdkLiveTransport({
      machine,
      fetcher: (url, init) => {
        fetchCalls.push({ url, init });
        return Promise.resolve(grant());
      },
      sdkLoader: () => Promise.resolve(sdk.module),
      onNotice: (notice) => notices.push(notice)
    });

    const result = await transport.connect({
      onTurnEnd: (info) => { turns.push(info); machine.openTurn(); },
      onError: (e) => notices.push(e)
    });
    machine.openTurn();

    assert.equal(fetchCalls.length, 1, "one grant per session");
    assert.equal(fetchCalls[0].url, "/api/b66/voice/token");
    assert.equal(fetchCalls[0].init.method, "POST");
    assert.equal(fetchCalls[0].init.credentials, "same-origin");
    assert.equal(sdk.calls.clients[0].apiKey, "auth_tokens/ephemeral-grant",
      "the ephemeral grant is the client key: the long-lived key never appears here");
    assert.deepEqual(sdk.calls.clients[0].httpOptions, { apiVersion: "v1alpha" });
    assert.equal(sdk.calls.connects[0].model, "gemini-3.5-transcribe-live",
      "the model name is passed to the SDK, which namespaces it itself");
    assert.equal(sdk.calls.connects[0].config.responseModalities[0], "TEXT");
    assert.equal(result.transport, "gemini_live_sdk");
    assert.equal(result.model, "gemini-3.5-transcribe-live");

    const cb = sdk.calls.connects[0].callbacks;
    cb.onmessage({ serverContent: { interimInputTranscription: { text: "대한건설에" } } });
    cb.onmessage({ serverContent: { inputTranscription: { text: "대한건설에 배관 100미터" } } });
    assert.equal(machine.state().committedCount, 0, "a segment alone does not end the turn");
    cb.onmessage({ serverContent: { turnComplete: true } });
    assert.equal(machine.state().committedCount, 1, "turnComplete commits the utterance");
    assert.equal(turns.length, 1);
    assert.equal(turns[0].empty, false, "a committed turn is not reported as empty");
    assert.equal(sdk.calls.closed, 0, "the session survives the turn: one grant, many utterances");

    cb.onmessage({ serverContent: { inputTranscription: { text: "미터당 18,000원" } } });
    cb.onmessage({ serverContent: { turnComplete: true } });
    assert.equal(machine.state().committedCount, 2, "the second utterance is its own commit");
    assert.equal(fetchCalls.length, 1, "no extra grant was spent mid-conversation");

    /* cumulative and delta hypotheses both reach the same slot without duplication */
    machine.openTurn();
    cb.onmessage({ serverContent: { inputTranscription: { text: "부가세" } } });
    cb.onmessage({ serverContent: { inputTranscription: { text: " 별도" } } });
    cb.onmessage({ serverContent: { inputTranscription: { text: "부가세 별도", finished: true } } });
    assert.equal(turns.length, 3);
    assert.equal(turns[2].committed.text, "부가세 별도", "merged, not triplicated");

    /* finished commits exactly once even when turnComplete follows in the same message */
    machine.openTurn();
    cb.onmessage({
      serverContent: {
        inputTranscription: { text: "미터당 18000원", finished: true },
        turnComplete: true
      }
    });
    assert.equal(machine.state().committedCount, 4, "one commit for a finished+complete frame");

    transport.sendAudio({ data: "AAECAw==", mimeType: "audio/pcm;rate=16000" });
    assert.deepEqual(sdk.calls.sent[0], {
      media: { data: "AAECAw==", mimeType: "audio/pcm;rate=16000" }
    }, "audio travels through the SDK's public realtime-input shape");
    assert.equal(transport.sendAudio({ data: "" }).sent, false, "an empty chunk is never sent");
    assert.equal(transport.sendAudio(null).sent, false);

    transport.close();
    assert.equal(sdk.calls.closed, 1, "close reaches the session");
    assert.equal(transport.sendAudio({ data: "AA==" }).sent, false, "audio stops after close");
    cb.onmessage({ serverContent: { inputTranscription: { text: "끊긴 뒤 도착한 발화" }, turnComplete: true } });
    assert.equal(machine.state().committedCount, 4, "a closed session cannot commit");
  }

  /* --- a reconnect never re-spends the single-use grant ------------------ */
  {
    const machine = Stt.createTranscriptMachine({});
    const sdk = fakeSdk();
    const fetchCalls = [];
    const transport = Stt.createSdkLiveTransport({
      machine,
      fetcher: () => { fetchCalls.push(1); return Promise.resolve(grant()); },
      sdkLoader: () => Promise.resolve(sdk.module)
    });
    await transport.connect({ onTurnEnd: () => {}, onError: () => {} });
    transport.close();
    await transport.connect({ onTurnEnd: () => {}, onError: () => {} });
    assert.equal(fetchCalls.length, 2,
      "a used grant cannot be replayed, so the second connect asks for a new one");
    assert.equal(sdk.calls.clients.length, 2, "each session gets its own client and key");
    assert.equal(sdk.calls.connects.length, 2);
  }

  /* --- CENTRAL 1A: a cancel during the grant must not reach the SDK ------ */
  {
    const gate = deferred();
    const sdk = fakeSdk();
    let loaderCalls = 0;
    const transport = Stt.createSdkLiveTransport({
      machine: Stt.createTranscriptMachine({}),
      fetcher: () => gate.promise.then(() => grant()),
      sdkLoader: () => { loaderCalls += 1; return Promise.resolve(sdk.module); }
    });
    const pending = transport.connect({ onTurnEnd: () => {}, onError: () => {} });
    let settled = "PENDING";
    pending.then((value) => { settled = { resolved: value }; },
      (error) => { settled = { code: error.code }; });
    transport.close();
    gate.resolve();
    await new Promise((resolve) => setImmediate(resolve));
    assert.deepEqual(settled, { code: "voice_connect_cancelled" },
      "the cancelled attempt reports cancellation, not a session");
    assert.equal(loaderCalls, 0, "the SDK bundle is not even loaded for a cancelled attempt");
    assert.equal(sdk.calls.clients.length, 0, "no client constructed");
    assert.equal(sdk.calls.connects.length, 0, "no Live session opened");
  }

  /* --- CENTRAL 1A: a session that lands after the cancel is closed ------- */
  {
    const sdk = pendingSdk();
    const transport = Stt.createSdkLiveTransport({
      machine: Stt.createTranscriptMachine({}),
      fetcher: () => Promise.resolve(grant()),
      sdkLoader: () => Promise.resolve(sdk.module)
    });
    const pending = transport.connect({ onTurnEnd: () => {}, onError: () => {} });
    let outcome = "PENDING";
    pending.then((value) => { outcome = { resolved: value }; },
      (error) => { outcome = { code: error.code }; });
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(sdk.calls.connects.length, 1, "the Live session request is in flight");
    transport.close();
    sdk.settle();
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(sdk.calls.sessions.length, 1, "the late session did arrive");
    assert.equal(sdk.calls.sessions[0].closed, 1, "and it is closed immediately, never adopted");
    assert.equal(transport.isLive(), false, "the transport does not consider itself live");
    assert.deepEqual(outcome, { code: "voice_connect_cancelled" });
    assert.equal(transport.sendAudio({ data: "AA==" }).sent, false);
    assert.equal(sdk.calls.sent.length, 0, "nothing was sent into the leaked session");
  }

  /* --- CENTRAL 1A: a closed session's error must not start browser STT --- */
  {
    const machine = Stt.createTranscriptMachine({});
    const sdk = fakeSdk();
    let fallbackUses = 0;
    const notices = [];
    const transport = Stt.createSdkLiveTransport({
      machine,
      fetcher: () => Promise.resolve(grant()),
      sdkLoader: () => Promise.resolve(sdk.module)
    });
    const chain = Stt.createFallbackChainTransport({
      machine,
      onNotice: (notice) => notices.push(notice.code),
      primaryFactory: () => transport,
      fallbackFactory: (context) => {
        fallbackUses += 1;
        return {
          connect: () => Promise.resolve({ connected: true }),
          sendAudio: () => ({ sent: false }),
          close: () => ({ closed: true })
        };
      }
    });
    await chain.connect({ onTurnEnd: () => {}, onReconnected: () => {}, onError: () => {} });
    chain.close();
    sdk.calls.connects[0].callbacks.onerror(new Error("socket closed after cancel"));
    sdk.calls.connects[0].callbacks.onclose({ reason: "cancelled" });
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(fallbackUses, 0, "a cancelled session does not buy a fallback");
    assert.deepEqual(notices, [], "and announces nothing");
  }

  /* --- CENTRAL 1C: stop while getUserMedia is awaited -------------------- */
  {
    const gate = deferred();
    const tracks = [{ stopped: 0, stop() { this.stopped += 1; } }];
    const stream = { getTracks: () => tracks };
    const chunks = [];
    let contextsCreated = 0;
    const audio = Stt.createPcmSource({
      mediaStreamFactory: () => gate.promise.then(() => stream),
      audioContextFactory: () => { contextsCreated += 1; return Promise.resolve({ state: "running", destination: {}, createMediaStreamSource: () => ({ connect() {}, disconnect() {} }), createScriptProcessor: () => ({ onaudioprocess: null, connect() {}, disconnect() {} }), close() {} }); },
      onChunk: (chunk) => chunks.push(chunk)
    });
    const pending = audio.start();
    let startedResult = "PENDING";
    pending.then((value) => { startedResult = value; });
    audio.stop();
    gate.resolve();
    await new Promise((resolve) => setImmediate(resolve));
    assert.deepEqual(startedResult, { started: false, reason: "stopped_before_capture" },
      "the late getUserMedia does not resurrect capture");
    assert.equal(tracks[0].stopped, 1, "the late MediaStream is released immediately");
    assert.equal(contextsCreated, 0, "and no AudioContext is even built for an abandoned start");
    assert.equal(chunks.length, 0, "no warm-up or frame is emitted");
    assert.equal(audio.isRunning(), false);
  }

  /* --- CENTRAL 1C: stop while the AudioContext is awaited ---------------- */
  {
    const tracks = [{ stopped: 0, stop() { this.stopped += 1; } }];
    const stream = { getTracks: () => tracks };
    const ctxGate = deferred();
    const chunks = [];
    const context = {
      state: "running",
      closed: 0,
      createMediaStreamSource: () => ({ connect() {}, disconnect() {} }),
      createScriptProcessor: () => ({ onaudioprocess: null, connect() {}, disconnect() {} }),
      close() { this.closed += 1; },
      destination: {}
    };
    const audio = Stt.createPcmSource({
      mediaStreamFactory: () => Promise.resolve(stream),
      audioContextFactory: () => ctxGate.promise.then(() => context),
      onChunk: (chunk) => chunks.push(chunk)
    });
    const pending = audio.start();
    let startedResult = "PENDING";
    pending.then((value) => { startedResult = value; });
    await new Promise((resolve) => setImmediate(resolve));
    audio.stop();
    ctxGate.resolve();
    await new Promise((resolve) => setImmediate(resolve));
    assert.deepEqual(startedResult, { started: false, reason: "stopped_before_capture" },
      "a context that arrives after stop is not adopted");
    assert.equal(tracks[0].stopped, 1, "the microphone acquired earlier is released");
    assert.equal(context.closed, 1, "and the late context is closed");
    assert.equal(chunks.length, 0, "no frame is emitted");
    assert.equal(audio.isRunning(), false);
  }

  /* --- an empty turn is reported, never committed ------------------------ */
  {
    const machine = Stt.createTranscriptMachine({});
    const empties = [];
    machine.on("empty", (payload) => empties.push(payload));
    const sdk = fakeSdk();
    const turns = [];
    const transport = Stt.createSdkLiveTransport({
      machine,
      fetcher: () => Promise.resolve(grant()),
      sdkLoader: () => Promise.resolve(sdk.module)
    });
    await transport.connect({ onTurnEnd: (info) => turns.push(info), onError: () => {} });
    machine.openTurn();
    sdk.calls.connects[0].callbacks.onmessage({ serverContent: { turnComplete: true } });
    assert.equal(machine.state().committedCount, 0, "nothing was transcribed, nothing committed");
    assert.equal(empties.length, 1, "the empty turn is its own signal");
    assert.equal(turns.length, 1);
    assert.equal(turns[0].empty, true, "the caller is told so it can announce and ask for a repeat");
    assert.equal(turns[0].committed, null);
    assert.equal(sdk.calls.closed, 0, "an empty turn does not end the session");
  }

  /* --- a grant failure is fatal, never retried --------------------------- *
     The controller routes on error.code, so the assertions read the code rather
     than the human-readable message. */
  {
    let calls = 0;
    const transport = Stt.createSdkLiveTransport({
      machine: Stt.createTranscriptMachine({}),
      fetcher: () => { calls += 1; return Promise.resolve({ ok: false, status: 401, json: async () => ({}) }); },
      sdkLoader: () => Promise.resolve(fakeSdk().module)
    });
    await assert.rejects(transport.connect({ onError: () => {} }),
      (error) => error.code === "voice_token_unavailable");
    assert.equal(calls, 1, "a refused grant is not retried");
  }

  {
    const transport = Stt.createSdkLiveTransport({
      machine: Stt.createTranscriptMachine({}),
      fetcher: () => Promise.resolve({ ok: true, json: async () => ({ ok: true }) }),
      sdkLoader: () => Promise.resolve(fakeSdk().module)
    });
    await assert.rejects(transport.connect({ onError: () => {} }),
      (error) => error.code === "voice_token_missing");
  }

  /* --- a bundle that will not load is a coded failure, not a silent one --- */
  {
    const transport = Stt.createSdkLiveTransport({
      machine: Stt.createTranscriptMachine({}),
      fetcher: () => Promise.resolve(grant()),
      sdkLoader: () => Promise.reject(new Error("failed to fetch /vendor/genai-live-2.24.0.js"))
    });
    await assert.rejects(transport.connect({ onError: () => {} }), /failed to fetch/);
  }

  {
    const transport = Stt.createSdkLiveTransport({
      machine: Stt.createTranscriptMachine({}),
      fetcher: () => Promise.resolve(grant()),
      sdkLoader: () => Promise.resolve({})
    });
    await assert.rejects(transport.connect({ onError: () => {} }),
      (error) => error.code === "sdk_unavailable");
  }

  /* --- browser fallback: restarts, announces, never replays audio -------- */
  {
    const machine = Stt.createTranscriptMachine({ nextId: Stt.createIdSource(null) });
    const recognizers = [];
    const timers = fakeTimers();
    const notices = [];
    const fallback = Stt.createBrowserFallbackTransport({
      machine,
      window: { navigator: { language: "ko-KR" } },
      recognizerFactory: () => { const r = fakeRecognizer(); recognizers.push(r); return r; },
      timerHost: timers
    });
    const turns = [];
    machine.openTurn();
    await fallback.connect({ onTurnEnd: (info) => turns.push(info), onError: (e) => notices.push(e.code) });
    const recognizer = recognizers[0];
    assert.equal(recognizer.starts, 1);
    assert.equal(recognizer.continuous, true, "upstream keeps recognition continuous");
    assert.equal(recognizer.interimResults, true);
    assert.equal(recognizer.lang, "ko-KR", "navigator.language is the upstream default");
    assert.equal(fallback.sendAudio({ data: "AA==" }).sent, false, "no audio is replayed into the fallback");

    recognizer.onresult({ results: [{ 0: { transcript: "단가 18000원" }, isFinal: true }], resultIndex: 0 });
    assert.equal(machine.state().committedCount, 1, "a browser final commits");
    assert.equal(turns.length, 1, "and reports the turn end like the live path");

    /* Chrome ends the session after silence; upstream restarts it after 150 ms */
    machine.openTurn();
    recognizer.onend();
    assert.equal(timers.due.length, 1);
    assert.equal(timers.due[0].ms, 150, "upstream restart delay");
    timers.due[0].fn();
    assert.equal(recognizer.starts, 2, "recognition restarted, so dictation keeps going");

    /* an unrecoverable engine error surfaces instead of looping */
    recognizer.onerror({ error: "not-allowed" });
    assert.deepEqual(notices, ["browser_stt_not_allowed"]);
    recognizer.onend();
    assert.equal(timers.due.length, 1, "a stopped engine is not restarted");

    fallback.close();
    assert.equal(recognizer.stops, 1);
  }

  /* --- a persistently ending engine is bounded, not an infinite loop ----- */
  {
    const machine = Stt.createTranscriptMachine({});
    const timers = fakeTimers();
    const recognizer = fakeRecognizer();
    const errors = [];
    const fallback = Stt.createBrowserFallbackTransport({
      machine,
      recognizerFactory: () => recognizer,
      timerHost: timers
    });
    machine.openTurn();
    await fallback.connect({ onError: (e) => errors.push(e.code), onTurnEnd: () => machine.openTurn() });
    for (let round = 0; round < 60 && !errors.length; round += 1) {
      const due = timers.due.filter((slot) => slot.fn);
      timers.due.length = 0;
      due.forEach((slot) => slot.fn());
      recognizer.onend();
    }
    assert.ok(errors.includes("browser_stt_restart_limit"), "the restart loop is bounded");
    assert.equal(fallback.restarts(), 20, "no more than the bound is attempted");
    assert.equal(timers.due.filter((slot) => slot.fn).length, 0, "and nothing is left scheduled");
  }

  /* --- the chain downgrades once, announces, and surfaces a dead end ----- */
  {
    const machine = Stt.createTranscriptMachine({});
    const notices = [];
    let fallbackUses = 0;
    const chain = Stt.createFallbackChainTransport({
      machine,
      onNotice: (notice) => notices.push(notice.code),
      primaryFactory: () => ({
        connect(handlers) { chain.handlers = handlers; return Promise.resolve({ connected: true }); },
        sendAudio: () => ({ sent: true }),
        close() { chain.primaryClosed = (chain.primaryClosed || 0) + 1; }
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
    machine.openTurn();
    const connected = await chain.connect({
      onTurnEnd: () => machine.openTurn(),
      onReconnected: () => machine.openTurn(),
      onError: (e) => notices.push(e.code)
    });
    assert.equal(connected.via, "live");
    chain.handlers.onError({ code: "voice_connection_closed" });
    await tick();
    assert.equal(fallbackUses, 1, "exactly one downgrade");
    assert.equal(chain.usedFallback(), true);
    assert.deepEqual(notices, ["fallback_browser_stt"], "the downgrade was announced");
    assert.equal(chain.primaryClosed, 1, "the dead live session was closed on the way out");
    assert.equal(chain.sendAudio({ data: "AA==" }).sent, false, "audio no longer reaches the dead session");
    assert.equal(machine.state().open, true, "a fresh turn was opened after the reset");
  }

  {
    const seen = [];
    const chain = Stt.createFallbackChainTransport({
      machine: Stt.createTranscriptMachine({}),
      onNotice: () => {},
      primaryFactory: () => ({
        connect() { const e = new Error("no token"); e.code = "voice_token_unavailable"; throw e; },
        close() {}
      }),
      fallbackFactory: null
    });
    await assert.rejects(chain.connect({ onError: (e) => seen.push(e.code), onTurnEnd: () => {} }),
      /no token/);
    assert.deepEqual(seen, [], "with no fallback engine the connect error surfaces once");
  }

  /* --- capture: warm-up first, then teardown of every resource ----------- */
  {
    const chunks = [];
    const tracks = [{ stopped: 0, stop() { this.stopped += 1; } }];
    const stream = { getTracks: () => tracks };
    const connections = [];
    const context = {
      state: "suspended",
      resumed: 0,
      closed: 0,
      async resume() { this.resumed += 1; this.state = "running"; },
      createMediaStreamSource: () => ({ connect: (target) => connections.push(["source", target]) }),
      createScriptProcessor: (size) => {
        const node = { bufferSize: size, onaudioprocess: null, connect: (t) => connections.push(["processor", t]) };
        context.processor = node;
        return node;
      },
      close() { this.closed += 1; },
      destination: "destination"
    };
    const audio = Stt.createPcmSource({
      mediaStreamFactory: () => Promise.resolve(stream),
      audioContextFactory: () => Promise.resolve(context),
      onChunk: (chunk) => chunks.push(chunk)
    });
    const started = await audio.start();
    assert.equal(started.started, true);
    assert.equal(context.resumed, 1, "a suspended context is resumed before capture (iOS)");
    assert.equal(chunks.length, 1, "the warm-up chunk is emitted first");
    assert.equal(Buffer.from(chunks[0].data, "base64").length, Stt.WARMUP_SAMPLES * 2,
      "100 ms of 16 kHz mono Int16 silence, so the first spoken slice is not lost");
    assert.equal(chunks[0].mimeType, "audio/pcm;rate=16000");
    assert.equal(context.processor.bufferSize, 1024, "upstream frame size");

    context.processor.onaudioprocess({ inputBuffer: { getChannelData: () => new Float32Array(1024).fill(0.5) } });
    assert.equal(chunks.length, 2);

    /* A browser can still deliver a queued frame after disconnect, so the guard is the
       running flag, not only the detached callback: capture the handler before teardown
       and fire it afterwards. */
    const late = context.processor.onaudioprocess;
    const stopped = audio.stop();
    assert.equal(context.processor.onaudioprocess, null, "the capture callback is detached on stop");
    late({ inputBuffer: { getChannelData: () => new Float32Array(1024).fill(0.25) } });
    assert.equal(chunks.length, 2, "a queued callback after stop still emits nothing");
    assert.equal(stopped.stopped, true);
    assert.equal(stopped.tracksStopped, 1, "the microphone is released");
    assert.equal(tracks[0].stopped, 1);
    assert.equal(stopped.processorClosed, true);
    assert.equal(stopped.contextClosed, true);
    assert.equal(context.closed, 1, "the AudioContext is closed exactly once");
    assert.equal(audio.isRunning(), false);
  }

  /* --- a hostile teardown still releases what it can --------------------- */
  {
    const tracks = [{
      stop() { throw new Error("track already gone"); },
    }, { stop() { this.stopped = true; }, stopped: false }];
    const audio = Stt.createPcmSource({
      mediaStreamFactory: () => Promise.resolve({ getTracks: () => tracks }),
      audioContextFactory: () => Promise.resolve({
        state: "running",
        createMediaStreamSource: () => ({ connect() {} }),
        createScriptProcessor: () => ({ connect() {}, onaudioprocess: null }),
        destination: {},
        close() { throw new Error("context busy"); }
      }),
      onChunk: () => {}
    });
    await audio.start();
    const stopped = audio.stop();
    assert.equal(stopped.stopped, true, "stop never throws out to the caller");
    assert.equal(stopped.contextClosed, false, "and reports honestly what failed");
    assert.equal(tracks[1].stopped, true, "the second track was still stopped after the first threw");
  }

  console.log("B66_VOICE_STT=PASS");
}

/* A pending await that never settles would end the process with no output and exit code 0,
   which is a silent false green. The watchdog turns "it hung" into a loud failure. */
const watchdog = setTimeout(() => {
  console.error("B66_VOICE_STT=TIMEOUT");
  console.error("MEANING=main() never settled; an await has neither resolved nor rejected");
  process.exit(1);
}, 30000);

main().then(
  () => clearTimeout(watchdog),
  (error) => {
    clearTimeout(watchdog);
    console.error("B66_VOICE_STT=FAIL");
    console.error(error && error.stack ? error.stack : String(error));
    process.exit(1);
  }
);
