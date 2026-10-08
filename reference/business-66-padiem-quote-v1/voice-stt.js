/* B66 · Quote Beta — Voice STT lane (#3404)
   Transcription only: this file never builds a quote, never calls the interpreter, and
   never touches a provider key.

   The Gemini Live protocol is NOT implemented here. The pinned `@google/genai` browser
   bundle (voice-sdk → vendor, served from this origin) owns the websocket URL, the setup
   frame, the audio frame shape and the constrained-session choice for an `auth_tokens/`
   grant. Audio capture, transcript merging and the fallback behaviour are ported from
   skerishKang/global-classroom@299c8e7830f6e4aa0c5202ca5591f240487c5c38; the citations
   name the upstream file and line so a future reader can diff against the origin. */

(() => {
  "use strict";

  const MAX_TRANSCRIPT_CHARS = 4000;
  const MAX_UTTERANCES_TRACKED = 64;
  const PCM_FRAME_SAMPLES = 1024;
  const PCM_SAMPLE_RATE_HZ = 16000;
  const WARMUP_SAMPLES = 1600;               /* 100 ms @16 kHz — upstream warm-up */
  const SDK_API_VERSION = "v1alpha";         /* the SDK requires this for ephemeral grants */
  const SDK_ARTIFACT_PATH = "/vendor/genai-live-2.24.0.js";
  const BROWSER_RESTART_MS = 150;            /* upstream SpeechRecognition restart delay */
  const MAX_BROWSER_RESTARTS = 20;

  /* ------------------------------------------------------------------ *
   * Ported from global-classroom                                       *
   * ------------------------------------------------------------------ */

  /* useGeminiLive.ts:17-25 — some Live backends emit cumulative hypotheses while others
     emit deltas, so the transcript slot must accept both without duplicating an
     already-seen prefix or suffix. Without this, a delta backend loses every word that
     came before the newest segment. */
  function mergeLiveTranscriptChunk(previous, incoming) {
    if (!incoming) return previous;
    if (!previous) return incoming;
    if (incoming.startsWith(previous)) return incoming;
    if (previous.endsWith(incoming)) return previous;
    return previous + incoming;
  }

  /* audioUtils.ts:23-31 */
  function float32ToInt16(data) {
    const l = data.length;
    const int16 = new Int16Array(l);
    for (let i = 0; i < l; i += 1) {
      const s = Math.max(-1, Math.min(1, data[i]));
      int16[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
    }
    return int16;
  }

  /* audioUtils.ts:13-21 */
  function arrayBufferToBase64(buffer) {
    let binary = "";
    const bytes = new Uint8Array(buffer);
    const len = bytes.byteLength;
    for (let i = 0; i < len; i += 1) {
      binary += String.fromCharCode(bytes[i]);
    }
    return btoa(binary);
  }

  /* useGeminiLive.ts:27-40 — responseModalities stays TEXT because this lane only
     transcribes and must never let the service answer back into the transcript. */
  function buildTranscribeConfig(spec) {
    const opts = spec || {};
    const silence = Number(opts.silenceDurationMs);
    const config = {
      responseModalities: ["TEXT"],
      realtimeInputConfig: {
        automaticActivityDetection: {
          silenceDurationMs: Number.isFinite(silence) && silence > 0 ? Math.min(silence, 10000) : 650
        }
      },
      inputAudioTranscription: {
        languageCodes: Array.isArray(opts.languageCodes) ? opts.languageCodes.slice(0, 8) : [],
        mode: opts.transcriptionMode === "SMART" ? "SMART" : "VERBATIM"
      }
    };
    if (Array.isArray(opts.customVocabulary) && opts.customVocabulary.length) {
      const seen = [];
      opts.customVocabulary.forEach((term) => {
        const value = String(term).slice(0, 64);
        if (value && seen.indexOf(value) === -1) seen.push(value);
      });
      config.inputAudioTranscription.customVocabulary = seen.slice(0, 100);
    }
    return config;
  }

  function createIdSource(cryptoRef) {
    const subtle = cryptoRef && typeof cryptoRef.randomUUID === "function";
    let counter = 0;
    return function nextId(prefix) {
      counter += 1;
      if (subtle) return cryptoRef.randomUUID();
      return prefix + "-" + Date.now().toString(36) + "-" + counter.toString(36);
    };
  }

  /* Interim text is preview material and never becomes authoritative input: the only value
     a consumer may act on is a committed utterance. Message meaning is mapped here and
     nowhere else, following the upstream order — interim, merged segment, `finished`
     commits at most once, `turnComplete` rescues an uncommitted turn or reports the turn
     as empty. B66 adds one thing on top of the upstream shape: a per-utterance id, which
     upstream only had because it read it from its translation sessions. */
  function createTranscriptMachine(options) {
    const opts = options || {};
    const listeners = { interim: [], segment: [], final: [], empty: [] };
    const nextId = opts.nextId || createIdSource(null);
    const finishedFlagName = opts.finishedFlagName || "finished";

    function emit(event, payload) {
      const handlers = listeners[event];
      if (!handlers) return;
      handlers.forEach((handler) => { handler(payload); });
    }

    function on(event, handler) {
      if (!listeners[event] || typeof handler !== "function") return false;
      listeners[event].push(handler);
      return true;
    }

    let turn = null;
    const generation = { value: 0 };
    const committedIds = [];

    function open() {
      generation.value += 1;
      turn = {
        id: nextId("utt"),
        generation: generation.value,
        text: "",
        interim: "",
        committed: false
      };
      return { utteranceId: turn.id, generation: turn.generation };
    }

    function active() {
      return turn && !turn.committed ? turn : null;
    }

    /* Stale frames from a retired connection are dropped rather than merged, which is what
       keeps one utterance from bleeding into the next. A source without a generation
       carries no opinion, so it is treated as current: the browser SpeechRecognition
       fallback produces exactly such events. */
    function isCurrent(source) {
      if (!turn) return false;
      if (!source || typeof source !== "object") return true;
      if (typeof source.generation === "number") return source.generation === generation.value;
      return true;
    }

    function interim(rawText, source) {
      if (!isCurrent(source)) return null;
      if (!active()) return null;
      const text = String(rawText == null ? "" : rawText);
      turn.interim = text.slice(0, MAX_TRANSCRIPT_CHARS);
      emit("interim", { utteranceId: turn.id, text: turn.interim });
      return turn.interim;
    }

    function segment(rawText, source) {
      if (!isCurrent(source)) return null;
      const current = active();
      if (!current) return null;
      const text = String(rawText == null ? "" : rawText);
      if (!text) return null;
      current.text = mergeLiveTranscriptChunk(current.text, text).slice(0, MAX_TRANSCRIPT_CHARS);
      if (source && typeof source.languageCode === "string" && source.languageCode) {
        current.languageCode = source.languageCode;
      }
      emit("segment", { utteranceId: current.id, text: current.text });
      return current.text;
    }

    function finish(source) {
      if (!isCurrent(source)) return null;
      const current = active();
      if (!current) return null;
      if (!current.text) {
        /* A finish signal with nothing transcribed is an empty turn, not a final. B66 keeps
           no second-provider audio recovery by design, so the turn closes and the caller
           announces that the utterance was not captured. */
        current.interim = "";
        emit("empty", { utteranceId: current.id });
        turn = null;
        return null;
      }
      current.committed = true;
      committedIds.push(current.id);
      if (committedIds.length > MAX_UTTERANCES_TRACKED) committedIds.shift();
      const committed = {
        utteranceId: current.id,
        text: current.text,
        languageCode: current.languageCode || null,
        generation: current.generation
      };
      emit("final", committed);
      turn = null;
      return committed;
    }

    function handleServerContent(message, source) {
      const content = message && message.serverContent ? message.serverContent : message;
      const outcome = { committed: null, turnEnded: false, empty: false };
      if (!content || typeof content !== "object") return outcome;
      const base = source || {};
      if (content.interimInputTranscription &&
        typeof content.interimInputTranscription.text === "string") {
        interim(content.interimInputTranscription.text, base);
      }
      if (content.inputTranscription && typeof content.inputTranscription === "object") {
        const part = content.inputTranscription;
        if (typeof part.text === "string" && part.text) {
          segment(part.text, Object.assign({}, base, {
            languageCode: typeof part.language_code === "string" ? part.language_code : part.languageCode
          }));
        }
        if (part[finishedFlagName] === true) {
          outcome.committed = finish(base);
          outcome.turnEnded = true;
          outcome.empty = !outcome.committed;
          return outcome;
        }
      }
      if (content.turnComplete === true || content.generationComplete === true) {
        outcome.committed = finish(base);
        outcome.turnEnded = true;
        outcome.empty = !outcome.committed;
      }
      return outcome;
    }

    function reset() {
      turn = null;
    }

    function alreadyCommitted(utteranceId) {
      return committedIds.indexOf(utteranceId) !== -1;
    }

    function state() {
      const current = active();
      return {
        generation: generation.value,
        committedCount: committedIds.length,
        open: Boolean(current),
        utteranceId: current ? current.id : null,
        text: current ? current.text : ""
      };
    }

    return {
      on,
      open,
      openTurn: open,
      interim,
      segment,
      finish,
      handleServerContent,
      reset,
      alreadyCommitted,
      state
    };
  }

  /* ------------------------------------------------------------------ *
   * Audio capture                                                      *
   * ------------------------------------------------------------------ */

  /* 16 kHz mono Int16 little-endian, 1024-sample frames (~64 ms), echo cancellation, noise
     suppression and gain control on: the mic must never hear the speaker. The silent
     warm-up chunk is useGeminiLive.ts:516-527, which keeps the first spoken slice from
     being lost while the session settles. */
  function createPcmSource(options) {
    const opts = options || {};
    const mediaStreamFactory = opts.mediaStreamFactory;
    const audioContextFactory = opts.audioContextFactory;
    const onChunk = typeof opts.onChunk === "function" ? opts.onChunk : () => {};
    const onLevel = typeof opts.onLevel === "function" ? opts.onLevel : () => {};
    const frameSamples = opts.frameSamples || PCM_FRAME_SAMPLES;
    const sampleRate = opts.sampleRate || PCM_SAMPLE_RATE_HZ;

    let stream = null;
    let audioContext = null;
    let processor = null;
    let sourceNode = null;
    let running = false;

    function chunkOf(samples) {
      return {
        data: arrayBufferToBase64(float32ToInt16(samples).buffer),
        mimeType: "audio/pcm;rate=" + String(sampleRate)
      };
    }

    async function start() {
      if (running) return { started: false, reason: "already_running" };
      if (typeof mediaStreamFactory !== "function" || typeof audioContextFactory !== "function") {
        throw new Error("audio_capture_unavailable");
      }
      /* useInterviewLive.ts:567-584 */
      stream = await mediaStreamFactory({
        audio: {
          channelCount: 1,
          sampleRate: sampleRate,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true
        },
        video: false
      });
      audioContext = await audioContextFactory({ sampleRate });
      if (audioContext.state === "suspended" && typeof audioContext.resume === "function") {
        await audioContext.resume();
      }
      sourceNode = audioContext.createMediaStreamSource(stream);
      processor = audioContext.createScriptProcessor(frameSamples, 1, 1);
      processor.onaudioprocess = (event) => {
        if (!running) return;
        const channel = event.inputBuffer.getChannelData(0);
        let peak = 0;
        for (let i = 0; i < channel.length; i += 2) {
          const magnitude = Math.abs(channel[i]);
          if (magnitude > peak) peak = magnitude;
        }
        onLevel(peak);
        onChunk(chunkOf(channel));
      };
      sourceNode.connect(processor);
      processor.connect(audioContext.destination);
      running = true;
      onChunk(chunkOf(new Float32Array(WARMUP_SAMPLES)));
      return { started: true, frameSamples, sampleRate, warmupSamples: WARMUP_SAMPLES };
    }

    /* Teardown is best-effort per resource and never aborts halfway: a mic left hot after a
       failure is worse than a redundant disconnect call. */
    function stop() {
      running = false;
      const report = { tracksStopped: 0, processorClosed: false, contextClosed: false };
      if (processor) {
        try {
          processor.onaudioprocess = null;
          if (typeof processor.disconnect === "function") processor.disconnect();
          report.processorClosed = true;
        } catch (_) { /* already gone */ }
        processor = null;
      }
      if (sourceNode && typeof sourceNode.disconnect === "function") {
        try { sourceNode.disconnect(); } catch (_) { /* already gone */ }
      }
      sourceNode = null;
      if (stream && typeof stream.getTracks === "function") {
        stream.getTracks().forEach((track) => {
          if (track && typeof track.stop === "function") {
            try {
              track.stop();
              report.tracksStopped += 1;
            } catch (_) { /* already stopped */ }
          }
        });
      }
      stream = null;
      if (audioContext && typeof audioContext.close === "function") {
        try {
          audioContext.close();
          report.contextClosed = true;
        } catch (_) { /* already closed */ }
      }
      audioContext = null;
      return Object.assign({ stopped: true }, report);
    }

    return { start, stop, isRunning: () => running };
  }

  /* ------------------------------------------------------------------ *
   * Transports                                                         *
   * ------------------------------------------------------------------ */

  function coded(code, message) {
    const error = new Error(message || code);
    error.code = code;
    return error;
  }

  function defaultSdkLoader() {
    /* A dynamic import keeps the ~0.9 MB bundle off the page load: it is fetched only once
       the user actually presses the microphone, and only from this origin. */
    return import(SDK_ARTIFACT_PATH);
  }

  /* One ephemeral grant per connect: the Worker mints it single-use, and the SDK chooses the
     constrained Live session from the `auth_tokens/` shape. This module never assembles a
     websocket URL, a setup frame or an audio frame — the pinned SDK owns those. */
  function createSdkLiveTransport(options) {
    const opts = options || {};
    const machine = opts.machine;
    const tokenEndpoint = opts.tokenEndpoint || "/api/b66/voice/token";
    const fetcher = opts.fetcher;
    const sdkLoader = typeof opts.sdkLoader === "function" ? opts.sdkLoader : defaultSdkLoader;
    const onNotice = typeof opts.onNotice === "function" ? opts.onNotice : () => {};

    const live = { session: null, handlers: null, closed: false, connects: 0, model: null };

    async function fetchGrant() {
      if (typeof fetcher !== "function") throw coded("stt_transport_unavailable", "no fetcher");
      let response = null;
      try {
        response = await fetcher(tokenEndpoint, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: "{}",
          credentials: "same-origin"
        });
      } catch (_) {
        throw coded("voice_token_unavailable", "voice token request failed");
      }
      if (!response || !response.ok) throw coded("voice_token_unavailable", "voice token rejected");
      let granted = null;
      try {
        granted = await response.json();
      } catch (_) {
        throw coded("voice_token_unparsable", "voice token unparsable");
      }
      if (!granted || granted.ok !== true || !granted.token || !granted.model) {
        throw coded((granted && granted.error && granted.error.code) || "voice_token_missing",
          "voice token missing");
      }
      return granted;
    }

    async function connect(handlers) {
      live.handlers = handlers;
      live.closed = false;
      live.connects += 1;

      const granted = await fetchGrant();
      const sdk = await sdkLoader();
      if (!sdk || typeof sdk.GoogleGenAI !== "function") {
        throw coded("sdk_unavailable", "gemini live sdk bundle unavailable");
      }

      const ai = new sdk.GoogleGenAI({
        apiKey: granted.token,
        httpOptions: { apiVersion: SDK_API_VERSION }
      });
      if (!ai.live || typeof ai.live.connect !== "function") {
        throw coded("sdk_live_unsupported", "gemini live sdk cannot open a session");
      }
      live.model = granted.model;

      const session = await ai.live.connect({
        model: granted.model,
        config: buildTranscribeConfig({
          languageCodes: granted.languageCodes,
          silenceDurationMs: granted.silenceDurationMs,
          transcriptionMode: granted.transcriptionMode
        }),
        callbacks: {
          onopen: () => {},
          onmessage: (message) => {
            if (live.closed) return;
            const outcome = machine.handleServerContent(message);
            if (outcome.turnEnded && live.handlers && live.handlers.onTurnEnd) {
              /* The session stays open: one grant authorizes one Live session and a session
                 carries many utterances. Closing per turn would spend a new grant on every
                 sentence. */
              live.handlers.onTurnEnd({ committed: outcome.committed, empty: outcome.empty });
            }
          },
          onerror: (error) => {
            if (live.handlers && live.handlers.onError) {
              live.handlers.onError(coded("voice_connection_failed",
                (error && error.message) || String(error)));
            }
          },
          onclose: (reason) => {
            live.session = null;
            if (live.closed) return;
            if (live.handlers && live.handlers.onError) {
              live.handlers.onError(coded("voice_connection_closed",
                (reason && reason.reason) || "connection closed"));
            }
          }
        }
      });

      live.session = session;
      return {
        connected: true,
        transport: "gemini_live_sdk",
        model: granted.model,
        expiresAt: granted.expiresAt || null
      };
    }

    function sendAudio(chunk) {
      if (!live.session || typeof live.session.sendRealtimeInput !== "function") {
        return { sent: false };
      }
      if (!chunk || typeof chunk.data !== "string" || !chunk.data) return { sent: false };
      live.session.sendRealtimeInput({
        media: { data: chunk.data, mimeType: chunk.mimeType || "audio/pcm;rate=16000" }
      });
      return { sent: true };
    }

    function close() {
      live.closed = true;
      const session = live.session;
      live.session = null;
      if (session && typeof session.close === "function") {
        try { session.close(); } catch (_) { /* already closed */ }
      }
      return { closed: true };
    }

    return { connect, sendAudio, close, connects: () => live.connects, model: () => live.model };
  }

  /* SpeechRecognition error codes are hyphenated ("not-allowed"); the announcement table
     is keyed by identifier-safe slugs, so the code is normalised here rather than at every
     call site. */
  function browserNoticeCode(code) {
    return "browser_stt_" + String(code).replace(/[^A-Za-z0-9]+/g, "_");
  }

  /* Browser SpeechRecognition, ported from useGeminiLive.ts:305-379 and
     useInterviewLive.ts:316-394: it restarts itself after Chrome ends a silent session, and
     it routes unrecoverable engine errors upward instead of looping. B66 has no second
     provider, so an unrecoverable error ends voice with an announcement; the restart bound
     keeps a persistently failing engine from spinning forever. */
  function createBrowserFallbackTransport(options) {
    const opts = options || {};
    const machine = opts.machine;
    const recognizerFactory = opts.recognizerFactory;
    const windowRef = opts.window || null;
    const language = opts.language ||
      ((windowRef && windowRef.navigator && windowRef.navigator.language) || "ko-KR");
    const restartDelayMs = typeof opts.restartDelayMs === "number"
      ? opts.restartDelayMs
      : BROWSER_RESTART_MS;
    const timerHost = opts.timerHost || {
      setTimeout: (fn, ms) => setTimeout(fn, ms),
      clearTimeout: (id) => clearTimeout(id)
    };

    const live = { recognizer: null, handlers: null, started: false, restarts: 0, timer: null };

    function commitFinal(text) {
      machine.segment(text, {});
      const committed = machine.finish({});
      if (committed && live.handlers && live.handlers.onTurnEnd) {
        live.handlers.onTurnEnd({ committed });
      }
    }

    function runRecognition() {
      live.timer = null;
      if (!live.started || !live.recognizer) return;
      const recognition = live.recognizer;
      recognition.onstart = () => {
        live.restarts = 0;
      };
      recognition.onresult = (event) => {
        let interimText = "";
        const results = event && event.results ? event.results : [];
        const from = event && typeof event.resultIndex === "number" ? event.resultIndex : 0;
        for (let index = from; index < results.length; index += 1) {
          const result = results[index];
          const spoken = result && result[0] ? String(result[0].transcript || "") : "";
          if (result && result.isFinal) commitFinal(spoken);
          else interimText += spoken;
        }
        if (interimText) machine.interim(interimText, {});
      };
      recognition.onerror = (event) => {
        const code = String((event && event.error) || "unknown");
        if (!live.started) return;
        if (["network", "service-not-allowed", "language-not-supported", "not-allowed"].indexOf(code) !== -1) {
          live.started = false;
          if (live.handlers && live.handlers.onError) {
            live.handlers.onError(coded(browserNoticeCode(code), code));
          }
          return;
        }
        if (live.handlers && live.handlers.onNotice) {
          live.handlers.onNotice({ code: browserNoticeCode(code) });
        }
      };
      recognition.onend = () => {
        if (!live.started) return;
        if (live.restarts >= MAX_BROWSER_RESTARTS) {
          live.started = false;
          if (live.handlers && live.handlers.onError) {
            live.handlers.onError(coded("browser_stt_restart_limit", "restart limit reached"));
          }
          return;
        }
        live.restarts += 1;
        live.timer = timerHost.setTimeout(runRecognition, restartDelayMs);
      };
      try {
        recognition.start();
      } catch (_) {
        live.started = false;
        if (live.handlers && live.handlers.onError) {
          live.handlers.onError(coded("browser_stt_start_failed", "recognition start failed"));
        }
      }
    }

    function connect(handlers) {
      if (typeof recognizerFactory !== "function") {
        throw coded("browser_stt_unavailable", "browser stt unavailable");
      }
      live.handlers = handlers;
      const recognizer = recognizerFactory();
      recognizer.continuous = true;
      recognizer.interimResults = true;
      recognizer.lang = language;
      live.recognizer = recognizer;
      live.started = true;
      live.restarts = 0;
      runRecognition();
      return Promise.resolve({ connected: true, fallback: true, lang: language });
    }

    function close() {
      live.started = false;
      if (live.timer !== null && live.timer !== undefined) {
        try { timerHost.clearTimeout(live.timer); } catch (_) { /* already cleared */ }
        live.timer = null;
      }
      const recognizer = live.recognizer;
      live.recognizer = null;
      if (recognizer && typeof recognizer.stop === "function") {
        recognizer.onend = null;
        recognizer.onerror = null;
        recognizer.onresult = null;
        try { recognizer.stop(); } catch (_) { /* already stopped */ }
      }
      return { closed: true };
    }

    return { connect, sendAudio: () => ({ sent: false }), close, restarts: () => live.restarts };
  }

  /* Downgrade exactly once, and say so: a different recognition engine producing the
     transcript is a visible change, never a silent one. The turn in progress is discarded on
     the way over, so audio captured before the failure cannot be replayed into the next
     utterance. */
  function createFallbackChainTransport(options) {
    const opts = options || {};
    const machine = opts.machine;
    const onNotice = typeof opts.onNotice === "function" ? opts.onNotice : () => {};
    let active = null;
    let usedFallback = false;

    function wrap(handlers, isFallback) {
      return {
        onTurnEnd: handlers.onTurnEnd,
        onReconnected: handlers.onReconnected,
        onNotice: handlers.onNotice,
        onError: (error) => {
          const code = (error && error.code) || "voice_connection_closed";
          if (isFallback || usedFallback) {
            if (handlers.onError) handlers.onError(error);
            return;
          }
          downgrade(handlers, code).then((recovered) => {
            if (!recovered && handlers.onError) handlers.onError(error);
          }, () => {
            if (handlers.onError) handlers.onError(error);
          });
        }
      };
    }

    function downgrade(handlers, code) {
      /* Shared by a connect-time refusal and a mid-session failure: one downgrade,
         announced, with the half-heard turn discarded so replay is impossible. */
      if (usedFallback || typeof opts.fallbackFactory !== "function") return Promise.resolve(null);
      usedFallback = true;
      if (active && typeof active.close === "function") active.close();
      if (machine) machine.reset();
      onNotice({ code: "fallback_browser_stt", from: String(code) });
      const next = opts.fallbackFactory({ machine, onNotice });
      if (!next) return Promise.resolve(null);
      active = next;
      return Promise.resolve()
        .then(() => next.connect(wrap(handlers, true)))
        .then(() => {
          if (handlers.onReconnected) handlers.onReconnected({ code: "fallback_ready" });
          return { via: "browser_fallback" };
        });
    }

    return {
      async connect(handlers) {
        const primary = typeof opts.primaryFactory === "function"
          ? opts.primaryFactory({ machine, onNotice })
          : null;
        if (!primary) throw coded("stt_transport_unavailable", "stt transport unavailable");
        active = primary;
        try {
          const result = await primary.connect(wrap(handlers, false));
          return Object.assign({ via: "live" }, result);
        } catch (error) {
          let recovered = null;
          try {
            recovered = await downgrade(handlers, (error && error.code) || "voice_connection_failed");
          } catch (_) {
            recovered = null;
          }
          if (recovered) return recovered;
          throw error;
        }
      },
      sendAudio(chunk) {
        if (!active || typeof active.sendAudio !== "function") return { sent: false };
        return active.sendAudio(chunk);
      },
      close() {
        if (active && typeof active.close === "function") active.close();
        active = null;
        return { closed: true };
      },
      usedFallback: () => usedFallback
    };
  }

  window.B66VoiceStt = {
    MAX_TRANSCRIPT_CHARS,
    PCM_FRAME_SAMPLES,
    PCM_SAMPLE_RATE_HZ,
    WARMUP_SAMPLES,
    SDK_API_VERSION,
    SDK_ARTIFACT_PATH,
    BROWSER_RESTART_MS,
    createIdSource,
    createTranscriptMachine,
    createPcmSource,
    createSdkLiveTransport,
    createFallbackChainTransport,
    createBrowserFallbackTransport,
    buildTranscribeConfig,
    mergeLiveTranscriptChunk,
    float32ToInt16,
    arrayBufferToBase64
  };
})();
