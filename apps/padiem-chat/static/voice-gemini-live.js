
(function (root, factory) {
  "use strict";
  const api = factory();
  if (typeof module === "object" && module && module.exports) {
    module.exports = api;
  }
  if (typeof define === "function" && define.amd) {
    define(function () { return api; });
  }
  if (root) {
    root.PadiemVoiceGeminiLive = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : (typeof window !== "undefined" ? window : this), function () {
  "use strict";

  /**
   * apps/padiem-chat/static/voice-gemini-live.js
   *
   * The Gemini Live real-time transcription engine for PADIEM Chat / Claw.
   *
   * PROVENANCE - GLOBAL_CLASSROOM_DIRECT_PORT, logic unchanged:
   *   skerishKang/global-classroom main ffa27e6a93605614031fed314ef33571c85b8f18
   *   hooks/useGeminiLive.ts     -> the Live session, the real-time audio path,
   *                                  the interim/final split, the turn commit,
   *                                  the session rotation with the audio
   *                                  carry-over, the provider fallback order
   *   utils/liveTranscriptTurn.ts -> the turn/merge/handoff/tail authority, which
   *                                  already ships as
   *                                  static/voice-live-transcript-turn.js
   *   utils/audioUtils.ts        -> float32ToInt16, arrayBufferToBase64
   *
   * What is NOT copied: the React hook and the @google/genai SDK. PADIEM's
   * shell is plain browser JavaScript with no build step, so the SDK's Live
   * transport is replaced by the very WebSocket the SDK speaks:
   *
   *   wss://generativelanguage.googleapis.com/ws/
   *     google.ai.generativelanguage.v1alpha.GenerativeService.
   *     BidiGenerateContentConstrained?access_token=<ephemeral token>
   *
   * The server owns the long-lived provider key. The browser only ever holds
   * the short-lived, model-locked ephemeral token minted by
   * /api/voice/live-token, exactly like Global Classroom's live-token
   * function. The model, the activity-detection window and the transcription
   * mode come from the server's browser-safe session contract; nothing here
   * selects a provider or a model.
   */

  const LIVE_WS_BASE = "wss://generativelanguage.googleapis.com";
  const LIVE_WS_PATH =
    "/ws/google.ai.generativelanguage.v1alpha.GenerativeService." +
    "BidiGenerateContentConstrained";
  const PCM_MIME = "audio/pcm;rate=16000";
  const SAMPLE_RATE = 16000;
  const PROCESSOR_BUFFER = 1024;

  /**
   * A Live session that fails is not retried forever. The original retries
   * inside one microphone run only while the user still wants the microphone;
   * this bound is the same intent expressed as a number: three consecutive
   * connect attempts, then the provider fallback owns the run.
   */
  const MAX_CONNECT_ATTEMPTS = 3;

  /**
   * Global Classroom's `utils/audioUtils.ts`, verbatim.
   */
  function float32ToInt16(data) {
    const l = data.length;
    const int16 = new Int16Array(l);
    for (let i = 0; i < l; i++) {
      const s = Math.max(-1, Math.min(1, data[i]));
      int16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
    }
    return int16;
  }

  function arrayBufferToBase64(buffer) {
    let binary = "";
    const bytes = new Uint8Array(buffer);
    const len = bytes.byteLength;
    for (let i = 0; i < len; i++) {
      binary += String.fromCharCode(bytes[i]);
    }
    return btoa(binary);
  }

  function turnAuthority(win) {
    return (win && win.PadiemVoiceLiveTranscriptTurn) || null;
  }

  /**
   * The Live session setup, built from the server's browser-safe contract.
   * Global Classroom's `buildGlobalTranscribeConfig` with the same fields; the
   * values themselves are the server's, not this module's.
   */
  function buildLiveSetup(session, authority) {
    const cfg = session || {};
    const source = authority || {};
    const model = cfg.model || source.LIVE_TRANSCRIBE_MODEL || "";
    const modalities =
      Array.isArray(cfg.response_modalities) && cfg.response_modalities.length
        ? cfg.response_modalities.slice()
        : ["TEXT"];
    const silenceMs = Number.isFinite(cfg.vad_silence_ms)
      ? cfg.vad_silence_ms
      : source.LIVE_VAD_SILENCE_MS;
    const mode =
      cfg.input_audio_transcription_mode || source.INPUT_AUDIO_TRANSCRIPTION_MODE || "VERBATIM";
    return {
      model: model ? "models/" + model : model,
      generationConfig: { responseModalities: modalities },
      realtimeInputConfig: {
        automaticActivityDetection: { silenceDurationMs: silenceMs },
      },
      inputAudioTranscription: { languageCodes: [], mode: mode },
    };
  }

  function buildLiveUrl(token) {
    return LIVE_WS_BASE + LIVE_WS_PATH + "?access_token=" + encodeURIComponent(token);
  }

  /**
   * The server writes the Live frames as binary JSON. Ask the socket for
   * ArrayBuffers and decode the UTF-8 payload before parsing; a text frame
   * still parses directly. An undecodable frame is dropped, never thrown.
   */
  function decodeLiveFrame(win, data) {
    if (typeof data === "string") return data;
    if (!data) return "";
    const scope = win || globalThis;
    const AB = typeof scope.ArrayBuffer === "function" ? scope.ArrayBuffer : globalThis.ArrayBuffer;
    const View = typeof scope.Uint8Array === "function" ? scope.Uint8Array : globalThis.Uint8Array;
    const Decoder = typeof scope.TextDecoder === "function" ? scope.TextDecoder : globalThis.TextDecoder;
    try {
      if (typeof AB === "function" && data instanceof AB) {
        return new Decoder("utf-8").decode(new View(data));
      }
      if (AB && typeof AB.isView === "function" && AB.isView(data)) {
        return new Decoder("utf-8").decode(data);
      }
    } catch (e) {
      return "";
    }
    return "";
  }

  /**
   * One Live WebSocket, shaped like the SDK session the original drives:
   * `sendRealtimeInput(message)` and `close()`.
   */
  function openLiveSession(options) {
    const win = options.win;
    const Ctor = win && win.WebSocket;
    if (typeof Ctor !== "function") return null;
    let socket;
    try {
      socket = new Ctor(options.url);
      /* The server writes every frame as binary JSON; without this the
       * socket hands back Blobs and every message is dropped as unparsable. */
      socket.binaryType = "arraybuffer";
    } catch (e) {
      return null;
    }
    let open = false;
    socket.onopen = function () { open = true; options.onOpen(); };
    socket.onmessage = function (event) {
      let payload = null;
      try {
        const text = decodeLiveFrame(win, event.data);
        payload = text ? JSON.parse(text) : event.data;
      } catch (e) {
        return;
      }
      options.onMessage(payload);
    };
    socket.onerror = function (event) { options.onError(event); };
    socket.onclose = function (event) { options.onClose(event); };
    return {
      isOpen: function () { return open && socket.readyState === 1; },
      send: function (message) {
        if (!open || socket.readyState !== 1) return false;
        try { socket.send(JSON.stringify(message)); return true; } catch (e) { return false; }
      },
      close: function () {
        open = false;
        try { socket.close(); } catch (e) { /* the socket is going away */ }
      },
    };
  }

  /**
   * Build the recognizer factory consumed by voice-composer.js.
   *
   * The seam is the one the composer already calls:
   *   factory({onInterim, onFinal, onError, onEnd, onTurnComplete},
   *           {generation, sessionToken}) -> handle with .stop()
   *
   * One recognizer session == one microphone run. Nothing is opened before the
   * factory is called, so a signed-in browser that never presses the
   * microphone never opens a Live session and never spends a provider call.
   *
   * Options:
   *   win, doc, fetchImpl, mediaDevices  the browser seams
   *   liveTokenPath(liveTokenPath)       the same-origin token route
   *   fallbackFactory                    the next provider in the chain
   *   now, setTimeout, clearTimeout      the clock seams
   */
  function createRecognizerFactory(deps) {
    deps = deps || {};
    const win = deps.win || (typeof globalThis !== "undefined" ? globalThis : null);
    const doc = deps.doc || (win ? win.document : null);
    if (!win || !doc) return null;
    const fetchImpl =
      deps.fetchImpl || (typeof win.fetch === "function" ? win.fetch.bind(win) : null);
    const mediaDevices =
      deps.mediaDevices ||
      (win.navigator && win.navigator.mediaDevices ? win.navigator.mediaDevices : null);
    const now = typeof deps.now === "function" ? deps.now : function () { return Date.now(); };
    const setTimer =
      typeof deps.setTimeout === "function"
        ? deps.setTimeout
        : (typeof win.setTimeout === "function" ? win.setTimeout.bind(win) : setTimeout);
    const clearTimer =
      typeof deps.clearTimeout === "function"
        ? deps.clearTimeout
        : (typeof win.clearTimeout === "function" ? win.clearTimeout.bind(win) : clearTimeout);
    const authority = turnAuthority(win);
    const fallbackFactory =
      typeof deps.fallbackFactory === "function" ? deps.fallbackFactory : null;
    const tokenPathFor =
      typeof deps.liveTokenPath === "function"
        ? deps.liveTokenPath
        : function () { return "/api/voice/live-token"; };

    return function geminiLiveRecognizerFactory(callbacks, runContext) {
      callbacks = callbacks || {};
      const run = runContext || {};

      let stopped = false;
      let micDesired = false;
      let session = null;
      let socket = null;
      let stream = null;
      let audioContext = null;
      let processor = null;
      let source = null;
      let connectAttempts = 0;
      let rotateTimer = null;
      let fallback = null;
      let fallbackStarted = false;
      let currentTurnText = "";
      let currentTurnCommitted = false;
      let utteranceSeq = 0;
      let rotationStartedAt = 0;
      let sessionSeq = 0;
      const handoff =
        authority && typeof authority.createAudioHandoffBuffer === "function"
          ? authority.createAudioHandoffBuffer(
              authority.LIVE_AUDIO_HANDOFF_FRAMES || 40
            )
          : null;

      function emitError(code) {
        if (stopped) return;
        try {
          if (typeof callbacks.onError === "function") callbacks.onError(code);
        } catch (e) { /* an error never controls the transport */ }
      }

      function emitEnd() {
        if (stopped) return;
        try { if (typeof callbacks.onEnd === "function") callbacks.onEnd(); } catch (e) { /* swallow */ }
      }

      function emitInterim(text) {
        if (stopped || !text) return;
        try {
          if (typeof callbacks.onInterim === "function") callbacks.onInterim(text);
        } catch (e) { /* swallow */ }
      }

      function emitFinal(text, stoppedFlag) {
        if (stopped || !text) return;
        utteranceSeq += 1;
        const utteranceId =
          "u" + run.generation + "-" + run.sessionToken + "-live-" + utteranceSeq;
        try {
          if (typeof callbacks.onFinal === "function") {
            callbacks.onFinal({
              text: text,
              utteranceId: utteranceId,
              stopped: stoppedFlag === true,
            });
          }
        } catch (e) { /* swallow */ }
        try {
          if (typeof callbacks.onTurnComplete === "function") {
            callbacks.onTurnComplete({ accepted: true, endOfTurn: true, finalId: utteranceId });
          }
        } catch (e) { /* swallow */ }
      }

      function resetTurn() {
        currentTurnText = "";
        currentTurnCommitted = false;
      }

      /**
       * Global Classroom's merge: the Live backends send either cumulative
       * hypotheses or deltas, and the turn authority accepts both without
       * duplicating a seen prefix.
       */
      function mergeChunk(previous, incoming) {
        if (authority && typeof authority.mergeLiveTranscriptChunk === "function") {
          return authority.mergeLiveTranscriptChunk(previous, incoming);
        }
        const p = previous ? String(previous) : "";
        const inc = incoming ? String(incoming) : "";
        if (!inc) return p;
        if (!p) return inc;
        if (inc.indexOf(p) === 0) return inc;
        if (p.slice(-inc.length) === inc) return p;
        return p + inc;
      }

      function handleServerMessage(payload) {
        if (stopped || !payload) return;
        if (payload.setupComplete) return;
        const content = payload.serverContent;
        if (!content) return;
        const interim = content.interimInputTranscription && content.interimInputTranscription.text;
        if (interim) {
          emitInterim(String(interim).trim());
        }
        const final = content.inputTranscription;
        if (final && final.text) {
          currentTurnText = mergeChunk(currentTurnText, String(final.text));
          const text = currentTurnText.trim();
          if (text) emitInterim(text);
        }
        if (final && final.finished && currentTurnText.trim() && !currentTurnCommitted) {
          currentTurnCommitted = true;
          emitFinal(currentTurnText.trim(), false);
          resetTurn();
        }
        if (content.turnComplete) {
          if (currentTurnCommitted) {
            resetTurn();
            return;
          }
          if (currentTurnText.trim()) {
            emitFinal(currentTurnText.trim(), false);
            resetTurn();
          }
        }
      }

      function releaseCapture() {
        if (processor) {
          try { processor.onaudioprocess = null; processor.disconnect(); } catch (e) { /* gone */ }
          processor = null;
        }
        if (source) {
          try { source.disconnect(); } catch (e) { /* gone */ }
          source = null;
        }
        if (audioContext) {
          try { audioContext.close(); } catch (e) { /* already closed */ }
          audioContext = null;
        }
        if (stream && typeof stream.getTracks === "function") {
          const tracks = stream.getTracks();
          for (let i = 0; i < tracks.length; i += 1) {
            try { tracks[i].stop(); } catch (e) { /* already stopped */ }
          }
        }
        stream = null;
      }

      function releaseSocket() {
        if (socket) {
          try { socket.close(); } catch (e) { /* already closed */ }
          socket = null;
        }
        session = null;
      }

      function stopRotation() {
        if (rotateTimer != null) {
          clearTimer(rotateTimer);
          rotateTimer = null;
        }
      }

      /**
       * Start the microphone capture and stream it to the Live session.
       * Global Classroom's `useGeminiLive` onopen path, with the same 16 kHz
       * mono capture and the same 1024-frame processor.
       */
      function startCapture() {
        if (!mediaDevices || typeof mediaDevices.getUserMedia !== "function") {
          emitError("capture-unavailable");
          return;
        }
        /* The microphone is never held open twice: a rotation replaces the
         * previous capture instead of stacking a second one. */
        releaseCapture();
        mediaDevices
          .getUserMedia({ audio: { channelCount: 1, sampleRate: SAMPLE_RATE } })
          .then(function (activeStream) {
            if (stopped || !micDesired) {
              const tracks = activeStream.getTracks();
              for (let i = 0; i < tracks.length; i += 1) {
                try { tracks[i].stop(); } catch (e) { /* already stopped */ }
              }
              return;
            }
            stream = activeStream;
            const Ctor = win.AudioContext || win.webkitAudioContext;
            if (typeof Ctor !== "function") {
              emitError("capture-unavailable");
              return;
            }
            audioContext = new Ctor({ sampleRate: SAMPLE_RATE });
            const resume = audioContext.resume();
            if (resume && typeof resume.then === "function") {
              resume.catch(function () { /* the browser may still allow capture */ });
            }
            source = audioContext.createMediaStreamSource(stream);
            processor = audioContext.createScriptProcessor(PROCESSOR_BUFFER, 1, 1);
            processor.onaudioprocess = function (event) {
              if (stopped || !micDesired) return;
              try {
                const input = event.inputBuffer.getChannelData(0);
                const pcm = float32ToInt16(input);
                const media = {
                  data: arrayBufferToBase64(pcm.buffer),
                  mimeType: PCM_MIME,
                };
                /* The rotation gap: frames captured while the new session is
                 * connecting are buffered and replayed into it, so a sentence
                 * that straddles the boundary is not lost. */
                if (handoff && handoff.capturing) {
                  handoff.push(media);
                  return;
                }
                if (!session || !session.isOpen()) return;
                session.send({ realtimeInput: { mediaChunks: [media] } });
              } catch (e) { /* a dropped frame must not end the run */ }
            };
            source.connect(processor);
            processor.connect(audioContext.destination);
          })
          .catch(function (error) {
            if (stopped) return;
            const name = error && error.name ? error.name : "";
            if (name === "NotAllowedError" || name === "SecurityError" ||
                name === "PermissionDeniedError") {
              emitError("permission-denied");
              return;
            }
            emitError("capture-unavailable");
          });
      }

      /**
       * The provider fallback. Global Classroom's `beginFallback`: the Live
       * session is torn down on purpose, the user's microphone intent is
       * restored, and the next provider in the chain takes the same run. The
       * chain is one-way: it never returns to Gemini inside one run.
       */
      function beginFallback(reason) {
        if (stopped) return;
        if (fallbackStarted) return;
        fallbackStarted = true;
        micDesired = false;
        stopRotation();
        releaseCapture();
        releaseSocket();
        resetTurn();
        if (!fallbackFactory) {
          stopped = true;
          emitError(reason || "live-unavailable");
          emitEnd();
          return;
        }
        micDesired = true;
        try {
          fallback = fallbackFactory(callbacks, run);
        } catch (e) {
          fallback = null;
        }
        if (!fallback || typeof fallback.stop !== "function") {
          stopped = true;
          emitError(reason || "live-unavailable");
          emitEnd();
        }
      }

      function fetchLiveToken() {
        if (typeof fetchImpl !== "function") {
          return Promise.reject(new Error("live-token-unavailable"));
        }
        return fetchImpl(tokenPathFor(doc), {
          method: "POST",
          credentials: "same-origin",
          /* The route is a JSON route: without the media type it answers one
           * bounded 415 and the run falls back to the chunked provider for no
           * reason. */
          headers: { Accept: "application/json", "Content-Type": "application/json" },
          body: "{}",
        }).then(function (response) {
          if (!response || !response.ok) throw new Error("live-token-unavailable");
          return response.json();
        }).then(function (payload) {
          const token = payload && payload.token ? String(payload.token) : "";
          if (!token) throw new Error("live-token-unavailable");
          return { token: token, session: (payload && payload.session) || {} };
        });
      }

      function openSession(token, liveSession) {
        /* Session identity: an outgoing session's callbacks must never be
         * mistaken for a provider failure, so only the current session may
         * report one. This is what makes a deliberate rotation a rotation and
         * not a fallback. */
        sessionSeq += 1;
        const seq = sessionSeq;
        socket = openLiveSession({
          win: win,
          url: buildLiveUrl(token),
          onOpen: function () {
            if (seq !== sessionSeq || stopped || !micDesired) return;
            const setup = buildLiveSetup(liveSession, authority);
            if (!socket || !socket.send({ setup: setup })) {
              beginFallback("live-unavailable");
              return;
            }
            startCapture();
            /* The rotation gap: the frames captured while the new session was
             * connecting are replayed into it, so a sentence that straddles
             * the boundary is not lost. */
            if (handoff) {
              const pending = handoff.release();
              for (let i = 0; i < pending.length; i += 1) {
                if (session && session.isOpen()) {
                  session.send({ realtimeInput: { mediaChunks: [pending[i]] } });
                }
              }
            }
          },
          onMessage: function (payload) {
            if (seq !== sessionSeq) return;
            handleServerMessage(payload);
          },
          onError: function () {
            if (seq !== sessionSeq || stopped || !micDesired) return;
            beginFallback("live-unavailable");
          },
          onClose: function () {
            if (seq !== sessionSeq || stopped || !micDesired) return;
            beginFallback("live-unavailable");
          },
        });
        if (!socket) {
          beginFallback("live-unavailable");
          return;
        }
        session = {
          isOpen: function () { return Boolean(socket && socket.isOpen()); },
          send: function (message) { return Boolean(socket && socket.send(message)); },
          close: function () { if (socket) socket.close(); },
        };
      }

      /**
       * The live session has a vendor duration limit. Global Classroom rotates
       * the session before that and carries the audio across the boundary.
       */
      function scheduleRotation(liveSession) {
        stopRotation();
        const rotateAfter = Number.isFinite(liveSession.rotate_after_ms)
          ? liveSession.rotate_after_ms
          : (authority && authority.LIVE_SESSION_ROTATE_MS) || 0;
        if (!rotateAfter) return;
        rotationStartedAt = now();
        rotateTimer = setTimer(function () {
          rotateTimer = null;
          if (stopped || !micDesired) return;
          rotateSession(liveSession);
        }, rotateAfter);
      }

      function rotateSession(liveSession) {
        /* The microphone keeps running through the gap; the frames captured
         * while the new session connects are buffered by the handoff. */
        if (handoff) handoff.start();
        stopRotation();
        releaseSocket();
        connectAttempts += 1;
        if (connectAttempts > MAX_CONNECT_ATTEMPTS) {
          beginFallback("live-unavailable");
          return;
        }
        fetchLiveToken()
          .then(function (result) {
            if (stopped || !micDesired) return;
            openSession(result.token, result.session);
            scheduleRotation(result.session);
          })
          .catch(function () {
            if (stopped || !micDesired) return;
            beginFallback("live-unavailable");
          });
      }

      function connect() {
        if (stopped || !micDesired) return;
        connectAttempts += 1;
        if (connectAttempts > MAX_CONNECT_ATTEMPTS) {
          beginFallback("live-unavailable");
          return;
        }
        fetchLiveToken()
          .then(function (result) {
            if (stopped || !micDesired) return;
            openSession(result.token, result.session);
            scheduleRotation(result.session);
          })
          .catch(function () {
            if (stopped || !micDesired) return;
            beginFallback("live-unavailable");
          });
      }

      /**
       * Stop: the tail is flushed, every resource is released and nothing is
       * left behind. The Live session, the microphone stream, the audio
       * context, the processor and the rotation timer all go away here.
       */
      function stop() {
        if (stopped) return;
        stopped = true;
        micDesired = false;
        stopRotation();
        if (handoff) handoff.reset();
        if (session && authority && typeof authority.flushLiveTranscriptTail === "function") {
          authority.flushLiveTranscriptTail(session, {
            onSettled: function (tail) {
              if (tail) emitFinal(tail, true);
            },
          });
        }
        releaseCapture();
        releaseSocket();
        if (fallback && typeof fallback.stop === "function") {
          try { fallback.stop(); } catch (e) { /* already stopped */ }
          fallback = null;
        }
        resetTurn();
      }

      micDesired = true;
      connect();

      return { stop: stop };
    };
  }

  return {
    LIVE_WS_BASE: LIVE_WS_BASE,
    LIVE_WS_PATH: LIVE_WS_PATH,
    PCM_MIME: PCM_MIME,
    SAMPLE_RATE: SAMPLE_RATE,
    MAX_CONNECT_ATTEMPTS: MAX_CONNECT_ATTEMPTS,
    float32ToInt16: float32ToInt16,
    arrayBufferToBase64: arrayBufferToBase64,
    buildLiveSetup: buildLiveSetup,
    buildLiveUrl: buildLiveUrl,
    openLiveSession: openLiveSession,
    createRecognizerFactory: createRecognizerFactory,
  };
});
