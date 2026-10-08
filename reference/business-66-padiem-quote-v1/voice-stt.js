/* B66 · Quote Beta — Voice STT lane (#3404)
   Transcription only: this file never builds a quote, never calls the interpreter,
   and never touches a provider key. Ported from the Global Classroom interview flow
   as a hand-rolled protocol module, so no React/Netlify/@google/genai dependency is
   introduced and every path is testable without a network. */

(() => {
  "use strict";

  const MAX_TRANSCRIPT_CHARS = 4000;
  const MAX_UTTERANCES_TRACKED = 64;
  const PCM_FRAME_SAMPLES = 1024;
  const PCM_SAMPLE_RATE_HZ = 16000;

  function createIdSource(cryptoRef) {
    const subtle = cryptoRef && typeof cryptoRef.randomUUID === "function";
    let counter = 0;
    return function nextId(prefix) {
      counter += 1;
      if (subtle) return cryptoRef.randomUUID();
      return prefix + "-" + Date.now().toString(36) + "-" + counter.toString(36);
    };
  }

  /* Interim text is preview material and never becomes authoritative input: the only
     value a consumer may act on is a committed utterance. Committing on the first
     inputTranscription chunk (the reference app's interview path) would treat a
     mid-speech segment as final, so completion waits for the finish signal.
     The machine is the single source of truth for finals: transports feed it server
     messages and consumers listen here, so a final can never arrive twice from two
     places. */
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

    /* Stale frames from a retired connection are dropped rather than merged, which is
       what keeps one utterance from bleeding into the next. A source without a
       generation carries no opinion, so it is treated as current: the browser
       SpeechRecognition fallback produces exactly such events. */
    function isCurrent(source) {
      if (!turn) return false;
      if (!source || typeof source !== "object") return true;
      if (typeof source.generation === "number") return source.generation === generation.value;
      return true;
    }

    function interim(rawText, source) {
      if (!isCurrent(source)) return null;
      const text = String(rawText == null ? "" : rawText);
      if (!active()) return null;
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
      /* Repeated segment events replace the slot instead of appending: a partial
         segment is superseded by the longer one, and only finish commits. */
      current.text = text.slice(0, MAX_TRANSCRIPT_CHARS);
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
        /* A finish signal with nothing transcribed is an empty turn, not a final. */
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

    /* Server messages are mapped here and nowhere else: the transport calls this and
       only reads the outcome, so the meaning of one transcript field cannot drift
       between two copies of the same rule. */
    function handleServerContent(message, source) {
      const content = message && message.serverContent ? message.serverContent : message;
      const outcome = { committed: null, turnEnded: false };
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
          return outcome;
        }
      }
      if (content.turnComplete === true || content.generationComplete === true) {
        outcome.committed = finish(base);
        outcome.turnEnded = true;
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

  function float32ToInt16Le(input) {
    const out = new Int16Array(input.length);
    for (let i = 0; i < input.length; i += 1) {
      const s = Math.max(-1, Math.min(1, input[i]));
      out[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
    }
    return out;
  }

  function arrayBufferToBase64(buffer) {
    const bytes = new Uint8Array(buffer);
    let chunk = "";
    const step = 0x8000;
    for (let i = 0; i < bytes.length; i += step) {
      chunk += String.fromCharCode.apply(null, bytes.subarray(i, i + step));
    }
    return btoa(chunk);
  }

  /* 16 kHz mono Int16 little-endian, 1024-sample frames (~64 ms), with echo
     cancellation and noise suppression on: the mic must never hear the speaker. */
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

    async function start() {
      if (running) return { started: false, reason: "already_running" };
      if (typeof mediaStreamFactory !== "function" || typeof audioContextFactory !== "function") {
        throw new Error("audio_capture_unavailable");
      }
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
        onChunk({
          data: arrayBufferToBase64(float32ToInt16Le(channel).buffer),
          mimeType: "audio/pcm;rate=" + String(sampleRate)
        });
      };
      sourceNode.connect(processor);
      processor.connect(audioContext.destination);
      running = true;
      return { started: true, frameSamples, sampleRate };
    }

    function stop() {
      running = false;
      if (processor) {
        processor.onaudioprocess = null;
        if (typeof processor.disconnect === "function") processor.disconnect();
        processor = null;
      }
      if (sourceNode && typeof sourceNode.disconnect === "function") sourceNode.disconnect();
      sourceNode = null;
      if (stream && Array.isArray(stream.getTracks ? stream.getTracks() : [])) {
        stream.getTracks().forEach((track) => {
          if (track && typeof track.stop === "function") track.stop();
        });
      }
      stream = null;
      if (audioContext && typeof audioContext.close === "function") audioContext.close();
      audioContext = null;
      return { stopped: true };
    }

    return { start, stop, isRunning: () => running };
  }

  /* Live API frame shapes this module emits. `realtimeInput.mediaChunks` is
     deprecated upstream, so audio travels as realtimeInput.audio with the format
     carried per chunk, and the response modality is TEXT because this lane only
     transcribes and must never let the service answer back. */
  function buildSetupFrame(spec) {
    const model = String(spec.model || "");
    if (!model) throw new Error("stt_model_unspecified");
    const setup = {
      model: model.indexOf("models/") === 0 ? model : "models/" + model,
      responseModalities: ["TEXT"]
    };
    setup.inputAudioTranscription = {
      languageCodes: Array.isArray(spec.languageCodes) ? spec.languageCodes.slice(0, 8) : [],
      mode: spec.transcriptionMode === "SMART" ? "SMART" : "VERBATIM"
    };
    if (Array.isArray(spec.customVocabulary) && spec.customVocabulary.length) {
      setup.inputAudioTranscription.customVocabulary = spec.customVocabulary
        .map((term) => String(term).slice(0, 64))
        .filter(Boolean)
        .slice(0, 100);
    }
    setup.realtimeInputConfig = {
      automaticActivityDetection: {
        silenceDurationMs: Number(spec.silenceDurationMs) > 0
          ? Math.min(Number(spec.silenceDurationMs), 10000)
          : 650
      }
    };
    return { setup };
  }

  function buildAudioFrame(chunk) {
    if (!chunk || typeof chunk.data !== "string" || !chunk.data) return null;
    return {
      realtimeInput: {
        audio: { data: chunk.data, mimeType: String(chunk.mimeType || "audio/pcm;rate=16000") }
      }
    };
  }

  /* The ephemeral token comes from the Worker on every connect and is single-use, so
     a reconnect can never reuse it and the long-lived key never reaches the page. */
  function createLiveTransport(options) {
    const opts = options || {};
    const machine = opts.machine;
    const tokenEndpoint = opts.tokenEndpoint || "/api/b66/voice/token";
    const fetcher = opts.fetcher;
    const socketFactory = opts.socketFactory;
    const onNotice = typeof opts.onNotice === "function" ? opts.onNotice : () => {};
    const live = { socket: null, spec: null, handlers: null, closed: false, connects: 0 };

    function note(code) {
      onNotice({ code });
    }

    async function connect(handlers) {
      if (typeof fetcher !== "function" || typeof socketFactory !== "function") {
        throw new Error("stt_transport_unavailable");
      }
      live.handlers = handlers;
      live.closed = false;
      live.connects += 1;
      const response = await fetcher(tokenEndpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
        credentials: "same-origin"
      });
      if (!response || !response.ok) {
        const error = new Error("voice_token_unavailable");
        error.code = "voice_token_unavailable";
        throw error;
      }
      const granted = await response.json();
      if (!granted || granted.ok !== true || !granted.token || !granted.websocketUrl) {
        const error = new Error((granted && granted.error && granted.error.code) || "voice_token_unavailable");
        error.code = error.message;
        throw error;
      }
      live.spec = granted;
      const socket = socketFactory(granted.websocketUrl + "?access_token=" + encodeURIComponent(granted.token));
      live.socket = socket;
      return new Promise((resolve, reject) => {
        socket.onopen = () => {
          socket.send(JSON.stringify(buildSetupFrame(granted)));
          /* The turn belongs to the controller, not to the transport: opening it
             here would consume the slot the controller has already opened. */
          resolve({ connected: true, model: granted.model, expiresAt: granted.expiresAt || null });
        };
        socket.onmessage = (event) => receive(event && event.data);
        socket.onerror = () => {
          const error = new Error("voice_connection_failed");
          error.code = "voice_connection_failed";
          if (live.handlers && live.handlers.onError) live.handlers.onError(error);
          reject(error);
        };
        socket.onclose = () => {
          live.socket = null;
          if (live.closed) return;
          if (live.handlers && live.handlers.onError) {
            live.handlers.onError({ code: "voice_connection_closed" });
          }
        };
      });
    }

    function receive(raw) {
      let message = null;
      try {
        message = JSON.parse(String(raw || "{}"));
      } catch (_) {
        note("voice_response_unparsable");
        return { parsed: false };
      }
      if (!message || typeof message !== "object") return { parsed: false };
      if (message.setupComplete === true) return { setupComplete: true };
      if (message.goAway && message.goAway.timeLeft) {
        /* The service is ending the session. Closing here is what keeps a
           reconnect from silently carrying a used token. */
        note("voice_session_expiring");
        close();
        return { goAway: true };
      }
      if (!message.serverContent) return { ignored: true };
      const outcome = machine.handleServerContent(message);
      if (outcome.turnEnded) {
        if (live.handlers && live.handlers.onTurnEnd) live.handlers.onTurnEnd();
        /* The connection stays open: an ephemeral token authorizes one Live
           session, and a session carries many utterances. Closing per turn would
           spend a new token on every sentence and cut the conversation apart. */
      }
      return { parsed: true, turnEnded: outcome.turnEnded };
    }

    function sendAudio(chunk) {
      const frame = buildAudioFrame(chunk);
      if (!frame || !live.socket || typeof live.socket.send !== "function") return { sent: false };
      live.socket.send(JSON.stringify(frame));
      return { sent: true };
    }

    function close() {
      live.closed = true;
      const socket = live.socket;
      live.socket = null;
      if (socket && typeof socket.close === "function") socket.close();
      return { closed: true };
    }

    return { connect, sendAudio, close, connects: () => live.connects, spec: () => live.spec };
  }

  /* Explicitly a fallback: the caller announces it, because a different engine
     recognizing the same speech is a visible change, not a silent one. */
  function createBrowserFallbackTransport(options) {
    const opts = options || {};
    const machine = opts.machine;
    const recognizerFactory = opts.recognizerFactory;
    const language = opts.language || "ko-KR";
    const live = { recognizer: null, handlers: null, started: false };

    function connect(handlers) {
      if (typeof recognizerFactory !== "function") {
        const error = new Error("browser_stt_unavailable");
        error.code = "browser_stt_unavailable";
        throw error;
      }
      live.handlers = handlers;
      const recognizer = recognizerFactory();
      recognizer.continuous = true;
      recognizer.interimResults = true;
      recognizer.lang = language;
      recognizer.onresult = (event) => {
        let interimText = "";
        for (let index = 0; index < (event.results ? event.results.length : 0); index += 1) {
          const result = event.results[index];
          const spoken = result && result[0] ? String(result[0].transcript || "") : "";
          if (result && result.isFinal) machine.segment(spoken, {});
          else interimText += spoken;
        }
        if (interimText) machine.interim(interimText);
      };
      recognizer.onend = () => {
        if (!live.started) return;
        const committed = machine.finish({});
        if (committed && live.handlers && live.handlers.onTurnEnd) live.handlers.onTurnEnd();
      };
      recognizer.onerror = (event) => {
        live.started = false;
        if (live.handlers && live.handlers.onError) {
          live.handlers.onError({ code: "browser_stt_" + String((event && event.error) || "error") });
        }
      };
      recognizer.start();
      live.recognizer = recognizer;
      live.started = true;
      return Promise.resolve({ connected: true, fallback: true });
    }

    function close() {
      live.started = false;
      if (live.recognizer && typeof live.recognizer.stop === "function") live.recognizer.stop();
      live.recognizer = null;
      return { closed: true };
    }

    return { connect, sendAudio: () => ({ sent: false }), close };
  }

  /* Downgrade exactly once, and say so: a different recognition engine producing
     the transcript is a visible change, never a silent one. The turn in progress is
     discarded on the way over, so audio captured before the failure cannot be
     replayed into the next utterance. */
  function createFallbackChainTransport(options) {
    const opts = options || {};
    const machine = opts.machine;
    const onNotice = typeof opts.onNotice === "function" ? opts.onNotice : () => {};
    let primary = null;
    let active = null;
    let usedFallback = false;

    function wrap(handlers, isFallback) {
      return {
        onTurnEnd: handlers.onTurnEnd,
        onReconnected: handlers.onReconnected,
        onError: (error) => {
          const code = (error && error.code) || "voice_connection_closed";
          if (isFallback || usedFallback) {
            handlers.onError(error);
            return;
          }
          const recovered = downgrade(handlers, code);
          if (!recovered) handlers.onError(error);
        }
      };
    }

    function downgrade(handlers, code) {
      /* Shared by a connect-time refusal and a mid-session failure: one downgrade,
         announced, with the half-heard turn discarded so replay is impossible. */
      if (usedFallback || typeof opts.fallbackFactory !== "function") return null;
      usedFallback = true;
      if (active && typeof active.close === "function") active.close();
      if (machine) machine.reset();
      onNotice({ code: "fallback_browser_stt", from: String(code) });
      const next = opts.fallbackFactory({ machine, onNotice });
      if (!next) return null;
      active = next;
      return next.connect(wrap(handlers, true)).then(() => {
        if (handlers.onReconnected) handlers.onReconnected({ code: "fallback_ready" });
        return { via: "browser_fallback" };
      });
    }

    return {
      async connect(handlers) {
        primary = typeof opts.primaryFactory === "function"
          ? opts.primaryFactory({ machine, onNotice })
          : null;
        if (!primary) throw new Error("stt_transport_unavailable");
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
    createIdSource,
    createTranscriptMachine,
    createPcmSource,
    createLiveTransport,
    createFallbackChainTransport,
    createBrowserFallbackTransport,
    buildSetupFrame,
    buildAudioFrame,
    float32ToInt16Le,
    arrayBufferToBase64
  };
})();
