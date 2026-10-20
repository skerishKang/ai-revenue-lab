(function (root, factory) {
  "use strict";
  const api = factory(root);
  if (typeof module === "object" && module && module.exports) {
    module.exports = api;
  }
  if (typeof define === "function" && define.amd) {
    define(function () { return api; });
  }
  if (root) {
    root.PadiemVoiceLiveTranscript = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : (typeof window !== "undefined" ? window : this), function (root) {
  "use strict";

  /**
   * apps/padiem-chat/static/voice-live-transcript.js
   *
   * The live (real-time) transcription engine for Chat(B62) and Claw(B54).
   *
   * This is a port of the proven Global Classroom implementation, not a new
   * speech algorithm. Source of truth (skerishKang/global-classroom, main):
   *
   *   utils/liveTranscriptTurn.ts
   *     -> LIVE_VAD_SILENCE_MS, LIVE_SESSION_ROTATE_MS,
   *        LIVE_AUDIO_HANDOFF_FRAMES, LIVE_TAIL_FLUSH_DRAIN_MS,
   *        TRANSCRIPT_TURN_STALL_MS,
   *        mergeLiveTranscriptChunk, createTranscriptTurnBuffer,
   *        createAudioHandoffBuffer, flushLiveTranscriptTail,
   *        shouldFlushStalledTurn
   *   hooks/useInterviewLive.ts
   *     -> the Live transcription session: one turn is one row, the session
   *        rotates before the provider limit, the microphone frames captured
   *        during a rotation are replayed into the incoming session, and a
   *        retired session is drained with `audioStreamEnd` so its tail is not
   *        lost
   *   hooks/useTranscribeRecorder.ts / hooks/useGeminiLive.ts
   *     -> the microphone plumbing: 16 kHz mono PCM, one Live turn per
   *        utterance, interim hypotheses as a live preview and the confirmed
   *        text as the final
   *   netlify/functions/live-token.ts
   *     -> the server mints a short-lived, model-locked ephemeral token; the
   *        browser never holds the long-lived provider key
   *
   * PADIEM's own server contract already owns the token mint: the private
   * `padiem-voice-stt` Worker exposes `POST /internal/v1/voice/live-token`
   * and the Chat Worker forwards to it over a Service Binding. This module
   * therefore never sees a long-lived provider credential: it receives one
   * single-use, model-locked, one-minute-start ephemeral token from the
   * same-origin Chat route and uses it for exactly one Live session.
   *
   * Boundary: this module is a recognizer, not a sender. It never submits a
   * message, never writes a conversation and never changes the model route.
   */

  /* ------------------------------------------------------------------ */
  /* Shared authority: the turn buffer and the merge rule live in the    */
  /* reviewed adapter module, so there is exactly one of each.           */
  /* ------------------------------------------------------------------ */

  function sharedAdapter() {
    if (root && root.PadiemVoiceSttInput
        && typeof root.PadiemVoiceSttInput.createTranscriptTurnBuffer === "function") {
      return root.PadiemVoiceSttInput;
    }
    if (typeof module === "object" && module && module.exports) {
      try { return require("./voice-stt-input.js"); } catch (e) { /* not a Node host */ }
    }
    return null;
  }

  const shared = sharedAdapter();

  /** Port of global-classroom `mergeLiveTranscriptChunk`. */
  function mergeLiveTranscriptChunk(previous, incoming) {
    const head = previous == null ? "" : String(previous);
    const tail = incoming == null ? "" : String(incoming);
    if (!tail) return head;
    if (!head) return tail;
    if (tail.startsWith(head)) return tail;
    if (head.endsWith(tail)) return head;
    return head + tail;
  }

  /**
   * Port of global-classroom `createTranscriptTurnBuffer`, taken from the
   * shared adapter module when it is present so the merge/turn semantics
   * cannot drift between the engine and the adapter.
   */
  function createTranscriptTurnBuffer() {
    if (shared && typeof shared.createTranscriptTurnBuffer === "function") {
      return shared.createTranscriptTurnBuffer();
    }
    let pending = "";
    return {
      get pending() { return pending; },
      merge: function (chunk) {
        if (!chunk) return pending;
        pending = mergeLiveTranscriptChunk(pending, String(chunk));
        return pending;
      },
      finishTurn: function () {
        const text = pending.trim();
        pending = "";
        return text || null;
      },
      reset: function () { pending = ""; },
    };
  }

  /* ------------------------------------------------------------------ */
  /* Constants — verbatim from global-classroom/utils/liveTranscriptTurn.ts */
  /* ------------------------------------------------------------------ */

  /** The one Live transcription model the reviewed contract is bound to. */
  const LIVE_TRANSCRIBE_MODEL = "gemini-3.5-transcribe-live";

  /**
   * How much silence ends a turn. Gemini's automatic activity detection
   * defaults to 800ms; 650ms cut ordinary 0.7-1.5s thinking pauses into
   * separate utterances, so a long sentence was emitted as several final
   * rows. 1300ms keeps typical thinking pauses inside one utterance.
   */
  const LIVE_VAD_SILENCE_MS = 1300;

  /**
   * Live sessions have a vendor-documented duration limit (~10 minutes).
   * Rotate before it instead of letting the session end and permanently
   * dropping the microphone.
   */
  const LIVE_SESSION_ROTATE_MS = 9 * 60_000 + 20_000;

  /**
   * One microphone frame is 2048 samples (128ms at 16 kHz). 40 frames cover
   * ~5.1s of connect latency, which is far beyond a normal token fetch plus
   * WebSocket handshake while staying a bounded amount of memory.
   */
  const LIVE_AUDIO_HANDOFF_FRAMES = 40;

  /**
   * Finalise the audio a retired Live session still holds. Gemini's activity
   * detection closes a turn only after it has *received* enough silence, so a
   * stream that simply stops never delivers it and the tail of the sentence
   * stays cached inside the session. `audioStreamEnd` makes the session
   * finalise the audio it holds.
   */
  const LIVE_TAIL_FLUSH_DRAIN_MS = 1_200;

  /**
   * Safety net for the turn boundary: a turn whose boundary never arrives is
   * committed as-is instead of being held forever.
   */
  const TRANSCRIPT_TURN_STALL_MS = 2_500;

  /* ------------------------------------------------------------------ */
  /* Live wire format                                                    */
  /* ------------------------------------------------------------------ */

  /**
   * The Live WebSocket endpoint used with an ephemeral token.
   *
   * The reference SDK (`@google/genai`) switches to the constrained method and
   * the `access_token` query parameter as soon as the credential starts with
   * `auth_tokens/`, and it only supports that path in `v1alpha`. This is the
   * same endpoint, expressed directly so the Chat app needs no bundler.
   */
  const LIVE_WS_ORIGIN = "wss://generativelanguage.googleapis.com";
  const LIVE_WS_PATH =
    "/ws/google.ai.generativelanguage.v1alpha.GenerativeService.BidiGenerateContentConstrained";

  /** The Live API expects 16 kHz mono 16-bit PCM. */
  const LIVE_PCM_MIME = "audio/pcm;rate=16000";
  const LIVE_SAMPLE_RATE = 16000;
  const LIVE_FRAME_SAMPLES = 2048;

  /** The AudioWorklet module that converts mic floats into transferable PCM. */
  const LIVE_WORKLET_URL = "/voice-live-pcm-worklet.js";
  const LIVE_WORKLET_PROCESSOR = "padiem-voice-live-pcm";

  /** How many times one run may re-open a dropped Live session. */
  const LIVE_MAX_RECONNECTS = 3;

  const ERROR_CODES = Object.freeze({
    PERMISSION_DENIED: "permission-denied",
    NOT_ALLOWED: "not-allowed",
    UNSUPPORTED: "unsupported-browser",
    UNAVAILABLE: "capture-unavailable",
    START_FAILED: "capture-start-failed",
    TOKEN_UNAVAILABLE: "live-token-unavailable",
    CONNECT_FAILED: "live-connect-failed",
    TRANSCRIBE_FAILED: "transcribe-failed",
  });

  /**
   * Codes that mean "this browser cannot run the live engine at all".
   *
   * They are reported to the wiring stage as a provider-unavailable event so
   * the reviewed chunk fallback can take over instead of failing the run.
   */
  const PROVIDER_UNAVAILABLE_CODES = Object.freeze([
    ERROR_CODES.TOKEN_UNAVAILABLE,
    ERROR_CODES.CONNECT_FAILED,
    ERROR_CODES.UNSUPPORTED,
  ]);

  /**
   * Resolve one of this module's own error codes from an arbitrary message.
   *
   * The codes are the *values* of ERROR_CODES, so a lookup by key would never
   * match. Anything that is not one of them is not a code of this module.
   */
  function errorCodeFor(value) {
    const candidate = value == null ? "" : String(value);
    if (!candidate) return "";
    const names = Object.keys(ERROR_CODES);
    for (let index = 0; index < names.length; index += 1) {
      if (ERROR_CODES[names[index]] === candidate) return candidate;
    }
    return "";
  }

  /* ------------------------------------------------------------------ */
  /* Message builders                                                    */
  /* ------------------------------------------------------------------ */

  /** The `setup` frame that opens a Live transcription session. */
  function buildLiveSetupMessage(config) {
    const options = config || {};
    const model = options.model || LIVE_TRANSCRIBE_MODEL;
    const vadSilenceMs = typeof options.vadSilenceMs === "number"
      ? options.vadSilenceMs
      : LIVE_VAD_SILENCE_MS;
    const modes = Array.isArray(options.responseModalities) && options.responseModalities.length
      ? options.responseModalities
      : ["TEXT"];
    const transcriptionMode = options.inputAudioTranscriptionMode || "VERBATIM";
    return {
      setup: {
        model: model,
        generationConfig: { responseModalities: modes },
        inputAudioTranscription: { languageCodes: [], mode: transcriptionMode },
        realtimeInputConfig: {
          automaticActivityDetection: { silenceDurationMs: vadSilenceMs },
        },
      },
    };
  }

  /** One realtime input frame carrying a PCM16 chunk. */
  function buildRealtimeInputMessage(media) {
    return {
      realtimeInput: {
        mediaChunks: [{ mimeType: media.mimeType, data: media.data }],
      },
    };
  }

  /** The frame that tells the session to finalise the audio it holds. */
  function buildAudioStreamEndMessage() {
    return { realtimeInput: { audioStreamEnd: true } };
  }

  /**
   * The Live WebSocket URL for one ephemeral token.
   *
   * The token is single-use and model-locked, so it is carried in the query
   * string exactly as the reference SDK carries it.
   */
  function buildLiveSocketUrl(token, origin) {
    const base = origin || LIVE_WS_ORIGIN;
    return base + LIVE_WS_PATH + "?access_token=" + String(token);
  }

  /* ------------------------------------------------------------------ */
  /* PCM helpers — port of global-classroom/utils/audioUtils.ts          */
  /* ------------------------------------------------------------------ */

  function float32ToInt16(data) {
    const length = data.length;
    const out = new Int16Array(length);
    for (let index = 0; index < length; index += 1) {
      const sample = Math.max(-1, Math.min(1, data[index]));
      out[index] = sample < 0 ? sample * 0x8000 : sample * 0x7FFF;
    }
    return out;
  }

  function arrayBufferToBase64(buffer) {
    const bytes = new Uint8Array(buffer);
    let binary = "";
    for (let index = 0; index < bytes.byteLength; index += 1) {
      binary += String.fromCharCode(bytes[index]);
    }
    if (typeof btoa === "function") return btoa(binary);
    /* Node-only fallback for the offline unit tests. */
    return Buffer.from(binary, "binary").toString("base64");
  }

  /* ------------------------------------------------------------------ */
  /* Port of global-classroom createAudioHandoffBuffer                   */
  /* ------------------------------------------------------------------ */

  /**
   * Captures microphone frames while the Live transcription session is being
   * swapped.
   *
   * Rotating a session means awaiting a fresh ephemeral token and a new
   * WebSocket. The outgoing session is invalidated *before* that await, so any
   * frame handed to it during the gap is transcribed and then thrown away and
   * the incoming session never saw the start of the sentence. Buffering the
   * gap and replaying it into the new session keeps an utterance that
   * straddles the rotation boundary intact.
   *
   * The buffer is bounded on purpose: a stalled connect must degrade into a
   * measurable, reportable loss rather than unbounded memory growth.
   */
  function createAudioHandoffBuffer(maxFrames) {
    let frames = [];
    let capturing = false;
    let dropped = 0;
    const cap = typeof maxFrames === "number" && maxFrames > 0
      ? maxFrames
      : LIVE_AUDIO_HANDOFF_FRAMES;

    return {
      get capturing() { return capturing; },
      get size() { return frames.length; },
      get droppedFrames() { return dropped; },
      start: function () { capturing = true; },
      push: function (frame) {
        if (!capturing) return false;
        if (frames.length >= cap) {
          dropped += 1;
          return false;
        }
        frames.push(frame);
        return true;
      },
      release: function () {
        const pending = frames;
        frames = [];
        capturing = false;
        return pending;
      },
      reset: function () {
        frames = [];
        capturing = false;
      },
    };
  }

  /* ------------------------------------------------------------------ */
  /* Port of global-classroom flushLiveTranscriptTail                    */
  /* ------------------------------------------------------------------ */

  /**
   * Finalise the audio a retired Live session still holds.
   *
   * A backend may deliver the tail as several deltas *or* as cumulative
   * hypotheses, so chunks are merged and only a turn boundary settles:
   * closing on the first non-empty chunk would truncate the sentence.
   * Settling also requires content: a bare boundary that arrives before any
   * text must not close an empty tail.
   */
  function flushLiveTranscriptTail(session, options) {
    const opts = options || {};
    const onSettled = typeof opts.onSettled === "function" ? opts.onSettled : function () {};
    const deadlineMs = typeof opts.deadlineMs === "number" ? opts.deadlineMs : LIVE_TAIL_FLUSH_DRAIN_MS;
    const setTimer = typeof opts.setTimer === "function" ? opts.setTimer : defaultSetTimer;
    const clearTimer = typeof opts.clearTimer === "function" ? opts.clearTimer : defaultClearTimer;

    if (!session) {
      return { armed: false, accept: function () { return false; }, cancel: function () {} };
    }

    let settled = false;
    let tail = "";
    let timer = setTimer(function () { settle(); }, deadlineMs);

    function settle() {
      if (settled) return;
      settled = true;
      if (timer !== null) {
        clearTimer(timer);
        timer = null;
      }
      try { session.close(); } catch (e) { /* the socket is going away either way */ }
      onSettled(tail.trim() ? tail : null);
    }

    try {
      session.sendRealtimeInput({ audioStreamEnd: true });
    } catch (e) {
      settle();
    }

    return {
      get armed() { return !settled; },
      accept: function (chunk) {
        if (settled) return false;
        const text = chunk && typeof chunk.text === "string" ? chunk.text : "";
        if (!text.trim()) {
          // A bare boundary is only usable once some text has been captured.
          if (!chunk || !chunk.finished || !tail) return false;
          settle();
          return true;
        }
        tail = mergeLiveTranscriptChunk(tail, text);
        if (chunk.finished) settle();
        return true;
      },
      cancel: function () { settle(); },
    };
  }

  /* ------------------------------------------------------------------ */
  /* Port of global-classroom shouldFlushStalledTurn                     */
  /* ------------------------------------------------------------------ */

  function shouldFlushStalledTurn(input) {
    const options = input || {};
    return Boolean(options.hasPending) && (options.sinceLastChunkMs || 0) >= TRANSCRIPT_TURN_STALL_MS;
  }

  /* ------------------------------------------------------------------ */
  /* Timer helpers                                                       */
  /* ------------------------------------------------------------------ */

  function defaultSetTimer(callback, ms) {
    return setTimeout(callback, ms);
  }

  function defaultClearTimer(id) {
    return clearTimeout(id);
  }

  function nowMs(win) {
    const perf = win && win.performance && typeof win.performance.now === "function"
      ? win.performance
      : null;
    if (perf) return perf.now();
    return Date.now();
  }

  /* ------------------------------------------------------------------ */
  /* Microphone capture — port of global-classroom interviewAudioCapture */
  /* ------------------------------------------------------------------ */

  /**
   * Start the microphone capture and hand every PCM16 frame to `onPcm`.
   *
   * The AudioWorklet path is preferred (the reference implementation's
   * Interview mode) and the ScriptProcessor path is the documented browser
   * fallback. Both are muted before the destination, so the microphone is
   * never played back to the user.
   */
  async function startPcmCapture(context, stream, onPcm) {
    const worklet = context.audioWorklet;
    const WorkletNodeCtor = root && root.AudioWorkletNode ? root.AudioWorkletNode : null;

    if (worklet && typeof worklet.addModule === "function" && WorkletNodeCtor) {
      try {
        await worklet.addModule(LIVE_WORKLET_URL);
        const source = context.createMediaStreamSource(stream);
        const processor = new WorkletNodeCtor(context, LIVE_WORKLET_PROCESSOR, {
          numberOfInputs: 1,
          numberOfOutputs: 1,
          outputChannelCount: [1],
        });
        const mute = context.createGain();
        mute.gain.value = 0;
        processor.port.onmessage = function (event) {
          if (event && event.data instanceof ArrayBuffer) onPcm(event.data);
        };
        source.connect(processor);
        processor.connect(mute);
        mute.connect(context.destination);
        return {
          mode: "worklet",
          stop: function () {
            processor.port.onmessage = null;
            try { processor.port.postMessage("stop"); } catch (e) { /* already gone */ }
            try { source.disconnect(); } catch (e) { /* already gone */ }
            try { processor.disconnect(); } catch (e) { /* already gone */ }
            try { mute.disconnect(); } catch (e) { /* already gone */ }
          },
        };
      } catch (e) {
        /* Fall through to the legacy capture path. */
      }
    }

    const source = context.createMediaStreamSource(stream);
    const legacy = context.createScriptProcessor(LIVE_FRAME_SAMPLES, 1, 1);
    const mute = context.createGain();
    mute.gain.value = 0;
    legacy.onaudioprocess = function (event) {
      const input = event.inputBuffer.getChannelData(0);
      onPcm(float32ToInt16(input).buffer);
    };
    source.connect(legacy);
    legacy.connect(mute);
    mute.connect(context.destination);
    return {
      mode: "legacy",
      stop: function () {
        legacy.onaudioprocess = null;
        try { source.disconnect(); } catch (e) { /* already gone */ }
        try { legacy.disconnect(); } catch (e) { /* already gone */ }
        try { mute.disconnect(); } catch (e) { /* already gone */ }
      },
    };
  }

  /* ------------------------------------------------------------------ */
  /* The recognizer factory                                              */
  /* ------------------------------------------------------------------ */

  /**
   * Build the recognizer factory consumed by voice-composer.js.
   *
   * The factory signature is the one the composer already calls:
   *   factory({onInterim, onFinal, onError, onEnd, onTurnComplete},
   *           {generation, sessionToken}) -> session handle with .stop()
   *
   * One recognizer session == one microphone run. The composer owns run
   * identity and invalidation; this recognizer reports what it heard and
   * always tears its own capture down on stop.
   */
  function createRecognizerFactory(deps) {
    deps = deps || {};
    const win = deps.win;
    const fetchImpl = deps.fetchImpl;
    const mediaDevices = deps.mediaDevices;
    const liveTokenPath = deps.liveTokenPath;
    const WebSocketCtor = deps.WebSocketCtor || (win && win.WebSocket);
    const setTimer = typeof deps.setTimeout === "function" ? deps.setTimeout : defaultSetTimer;
    const clearTimer = typeof deps.clearTimeout === "function" ? deps.clearTimeout : defaultClearTimer;
    const now = typeof deps.now === "function" ? deps.now : function () { return nowMs(win); };

    return function liveRecognizerFactory(callbacks, runContext) {
      callbacks = callbacks || {};
      const run = runContext || {};

      let stopped = false;
      let closing = false;
      let cancelled = false;
      let stream = null;
      let audioContext = null;
      let capture = null;
      let session = null;
      let sessionGeneration = 0;
      let rotateTimer = null;
      let stallTimer = null;
      let tailFlush = null;
      let utteranceSeq = 0;
      let lastTurnChunkAt = 0;
      let liveConfig = null;
      let reconnects = 0;

      const handoff = createAudioHandoffBuffer(LIVE_AUDIO_HANDOFF_FRAMES);
      const turnBuffer = createTranscriptTurnBuffer();
      const interimBuffer = createTranscriptTurnBuffer();

      function emitError(code) {
        if (stopped) return;
        try { if (typeof callbacks.onError === "function") callbacks.onError(code); } catch (e) { /* swallow */ }
      }

      function emitProviderUnavailable(code) {
        if (stopped) return;
        try {
          if (typeof callbacks.onProviderUnavailable === "function") {
            callbacks.onProviderUnavailable(code);
          } else {
            emitError(code);
          }
        } catch (e) { /* swallow */ }
      }

      function emitEnd() {
        if (stopped) return;
        try { if (typeof callbacks.onEnd === "function") callbacks.onEnd(); } catch (e) { /* swallow */ }
      }

      function releaseCapture() {
        if (capture && typeof capture.stop === "function") {
          try { capture.stop(); } catch (e) { /* already gone */ }
        }
        capture = null;
        if (audioContext && typeof audioContext.close === "function") {
          try { audioContext.close(); } catch (e) { /* already closed */ }
        }
        audioContext = null;
        if (stream && typeof stream.getTracks === "function") {
          const tracks = stream.getTracks();
          for (let index = 0; index < tracks.length; index += 1) {
            try { tracks[index].stop(); } catch (e) { /* already stopped */ }
          }
        }
        stream = null;
      }

      function clearRotateTimer() {
        if (rotateTimer !== null) {
          clearTimer(rotateTimer);
          rotateTimer = null;
        }
      }

      function clearStallTimer() {
        if (stallTimer !== null) {
          clearTimer(stallTimer);
          stallTimer = null;
        }
      }

      /** One Live turn is one committed utterance. */
      function commitTurn(text, options) {
        const opts = options || {};
        clearStallTimer();
        interimBuffer.reset();
        const value = String(text == null ? "" : text).trim();
        if (!value) return null;
        utteranceSeq += 1;
        const utteranceId = "live-" + run.generation + "-"
          + String(run.sessionToken || "s") + "-" + utteranceSeq;
        const payload = { text: value, utteranceId: utteranceId };
        if (opts.stopped === true) payload.stopped = true;
        try { if (typeof callbacks.onFinal === "function") callbacks.onFinal(payload); } catch (e) { /* swallow */ }
        try {
          if (typeof callbacks.onTurnComplete === "function") {
            callbacks.onTurnComplete({ accepted: true, endOfTurn: true, finalId: utteranceId });
          }
        } catch (e) { /* swallow */ }
        return utteranceId;
      }

      function scheduleStallFlush() {
        clearStallTimer();
        stallTimer = setTimer(function () {
          stallTimer = null;
          if (stopped || cancelled) return;
          if (!shouldFlushStalledTurn({
            hasPending: Boolean(turnBuffer.pending),
            sinceLastChunkMs: now() - lastTurnChunkAt,
          })) return;
          commitTurn(turnBuffer.finishTurn());
        }, TRANSCRIPT_TURN_STALL_MS + 250);
      }

      function isCurrentSession(generation) {
        return generation === sessionGeneration && !stopped && !cancelled;
      }

      function handleServerMessage(generation, raw) {
        let message = null;
        try { message = JSON.parse(raw); } catch (e) { return; }
        if (!message) return;

        const content = message.serverContent;
        if (!content) return; // setupComplete and other control frames

        if (!isCurrentSession(generation)) {
          // This session was retired by a tail flush, so its chunks are the
          // speech the user actually said. Only that flush may consume them.
          const retiring = tailFlush;
          if (retiring && retiring.generation === generation) {
            const chunk = content.inputTranscription || null;
            retiring.flush.accept({
              text: chunk ? chunk.text : "",
              finished: Boolean(
                (chunk && chunk.finished) || content.turnComplete || content.generationComplete,
              ),
            });
          }
          return;
        }

        const interim = content.interimInputTranscription
          ? content.interimInputTranscription.text
          : "";
        const finalChunk = content.inputTranscription;

        if (interim) {
          const preview = interimBuffer.merge(String(interim));
          if (preview) {
            try { if (typeof callbacks.onInterim === "function") callbacks.onInterim(preview); }
            catch (e) { /* swallow */ }
          }
        }

        if (finalChunk && finalChunk.text) {
          turnBuffer.merge(String(finalChunk.text));
          lastTurnChunkAt = now();
        }

        const turnFinished = Boolean(
          (finalChunk && finalChunk.finished) || content.turnComplete || content.generationComplete,
        );
        if (turnFinished) {
          commitTurn(turnBuffer.finishTurn());
          return;
        }
        // The boundary has not arrived yet: keep the turn open, but never hold
        // a stalled turn forever.
        if (turnBuffer.pending) scheduleStallFlush();
      }

      function makeSession(generation, socket) {
        return {
          generation: generation,
          sendRealtimeInput: function (input) {
            if (!socket || socket.readyState !== 1) return;
            if (input && input.media) {
              socket.send(JSON.stringify(buildRealtimeInputMessage(input.media)));
              return;
            }
            if (input && input.audioStreamEnd) {
              socket.send(JSON.stringify(buildAudioStreamEndMessage()));
            }
          },
          close: function () {
            try { socket.close(); } catch (e) { /* already closed */ }
          },
        };
      }

      /** Mint one ephemeral token and open one Live session with it. */
      async function connectSession() {
        if (typeof fetchImpl !== "function") {
          throw new Error(ERROR_CODES.TOKEN_UNAVAILABLE);
        }
        if (typeof WebSocketCtor !== "function") {
          throw new Error(ERROR_CODES.UNSUPPORTED);
        }
        const response = await fetchImpl(liveTokenPath, {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json", Accept: "application/json" },
          body: JSON.stringify({ sessionId: String(run.sessionToken || "") }),
        });
        if (!response || !response.ok) {
          throw new Error(ERROR_CODES.TOKEN_UNAVAILABLE);
        }
        const payload = await response.json();
        const token = payload && typeof payload.token === "string" ? payload.token : "";
        if (!token) throw new Error(ERROR_CODES.TOKEN_UNAVAILABLE);
        if (payload && payload.session && typeof payload.session === "object") {
          liveConfig = payload.session;
        }

        const generation = sessionGeneration;
        const socket = new WebSocketCtor(buildLiveSocketUrl(token));
        const live = makeSession(generation, socket);

        socket.onmessage = function (event) {
          handleServerMessage(generation, event && event.data);
        };

        await new Promise(function (resolve, reject) {
          let settled = false;
          socket.onopen = function () {
            if (settled) return;
            settled = true;
            resolve();
          };
          socket.onerror = function () {
            if (settled) return;
            settled = true;
            reject(new Error(ERROR_CODES.CONNECT_FAILED));
          };
          socket.onclose = function () {
            if (settled) return;
            settled = true;
            reject(new Error(ERROR_CODES.CONNECT_FAILED));
          };
        });

        if (stopped || cancelled) {
          try { socket.close(); } catch (e) { /* already closed */ }
          throw new Error(ERROR_CODES.CONNECT_FAILED);
        }

        socket.onerror = function () {
          if (!isCurrentSession(generation)) return;
          handleSessionLoss(generation);
        };
        socket.onclose = function () {
          if (!isCurrentSession(generation)) return;
          handleSessionLoss(generation);
        };

        // The setup frame opens the session.
        socket.send(JSON.stringify(buildLiveSetupMessage({
          model: liveConfig && liveConfig.model,
          vadSilenceMs: liveConfig && liveConfig.vad_silence_ms,
          responseModalities: liveConfig && liveConfig.response_modalities,
          inputAudioTranscriptionMode: liveConfig && liveConfig.input_audio_transcription_mode,
        })));
        return live;
      }

      /**
       * The provider dropped the session.
       *
       * The microphone frames captured while a new session is opened are
       * replayed into it, so the utterance that was in flight survives the
       * drop instead of being lost.
       */
      function handleSessionLoss(generation) {
        if (stopped || cancelled) return;
        if (generation !== sessionGeneration) return;
        if (reconnects >= LIVE_MAX_RECONNECTS) {
          emitError(ERROR_CODES.TRANSCRIBE_FAILED);
          return;
        }
        reconnects += 1;
        void rotateSession();
      }

      function scheduleRotation() {
        clearRotateTimer();
        const rotateAfterMs = liveConfig && typeof liveConfig.rotate_after_ms === "number"
          ? liveConfig.rotate_after_ms
          : LIVE_SESSION_ROTATE_MS;
        rotateTimer = setTimer(function () {
          rotateTimer = null;
          void rotateSession();
        }, rotateAfterMs);
      }

      /**
       * Rotate the Live session before the provider limit.
       *
       * The microphone frames captured during the swap are replayed into the
       * incoming session so an utterance that straddled the boundary reaches
       * it from its first sample.
       */
      async function rotateSession() {
        if (stopped || cancelled) return;
        const previous = session;

        // Capture starts BEFORE anything is invalidated.
        handoff.start();

        // A rotation boundary can land mid-sentence; keep the transcript
        // already captured instead of dropping it with the outgoing session.
        const pendingBeforeRotation = turnBuffer.finishTurn();
        if (pendingBeforeRotation) commitTurn(pendingBeforeRotation);

        // Arm the retirement flush BEFORE the generation is invalidated and
        // before the new session is awaited.
        retireSession(previous, sessionGeneration, { stoppedFinal: false });

        sessionGeneration += 1;
        try {
          const next = await connectSession();
          if (stopped || cancelled) {
            handoff.reset();
            try { next.close(); } catch (e) { /* already closed */ }
            return;
          }
          session = next;
          reconnects = 0;
          for (const media of handoff.release()) {
            try { next.sendRealtimeInput({ media: media }); } catch (e) { /* the session owns errors */ }
          }
          scheduleRotation();
        } catch (e) {
          handoff.reset();
          emitError(ERROR_CODES.CONNECT_FAILED);
        }
      }

      /** Drain and close a retiring session so its tail is not lost. */
      function retireSession(previous, generation, options) {
        if (!previous) return null;
        const opts = options || {};
        const flush = flushLiveTranscriptTail(previous, {
          onSettled: function (text) {
            if (tailFlush && tailFlush.generation === generation) tailFlush.flush = null;
            if (text) commitTurn(text, { stopped: opts.stoppedFinal === true });
          },
          setTimer: setTimer,
          clearTimer: clearTimer,
        });
        tailFlush = { generation: generation, flush: flush };
        return flush;
      }

      function onPcmFrame(buffer) {
        if (stopped || cancelled || !session) return;
        const media = {
          data: arrayBufferToBase64(buffer),
          mimeType: LIVE_PCM_MIME,
        };
        // While a rotation is in flight the outgoing session is already
        // invalidated, so sending to it would transcribe this frame and
        // discard the result. Capture it and replay it into the new session.
        if (handoff.capturing) {
          handoff.push(media);
          return;
        }
        try { session.sendRealtimeInput({ media: media }); } catch (e) { /* the session owns errors */ }
      }

      async function openMicrophone() {
        if (!mediaDevices || typeof mediaDevices.getUserMedia !== "function") {
          throw new Error(ERROR_CODES.UNSUPPORTED);
        }
        const opened = await mediaDevices.getUserMedia({
          audio: {
            channelCount: 1,
            sampleRate: LIVE_SAMPLE_RATE,
            echoCancellation: true,
            noiseSuppression: true,
            autoGainControl: true,
          },
        });
        if (stopped || cancelled) {
          const tracks = opened.getTracks();
          for (let index = 0; index < tracks.length; index += 1) tracks[index].stop();
          throw new Error(ERROR_CODES.START_FAILED);
        }
        stream = opened;
        const Ctor = (win && (win.AudioContext || win.webkitAudioContext)) || null;
        if (!Ctor) {
          releaseCapture();
          throw new Error(ERROR_CODES.UNSUPPORTED);
        }
        audioContext = new Ctor({ sampleRate: LIVE_SAMPLE_RATE });
        if (typeof audioContext.resume === "function") await audioContext.resume();
        capture = await startPcmCapture(audioContext, stream, onPcmFrame);
      }

      async function start() {
        if (stopped || cancelled) return;
        try {
          await openMicrophone();
        } catch (e) {
          releaseCapture();
          const code = errorCodeFor(e && e.message) || (
            e && e.name === "NotAllowedError" ? ERROR_CODES.PERMISSION_DENIED
              : e && e.name === "NotFoundError" ? ERROR_CODES.NOT_ALLOWED
              : ERROR_CODES.START_FAILED
          );
          emitError(code);
          return;
        }
        if (stopped || cancelled) {
          releaseCapture();
          return;
        }
        try {
          session = await connectSession();
        } catch (e) {
          releaseCapture();
          const code = errorCodeFor(e && e.message) || ERROR_CODES.CONNECT_FAILED;
          // Nothing was transcribed yet, so the reviewed chunk fallback can
          // still take the run over without losing a word.
          emitProviderUnavailable(code);
          return;
        }
        if (stopped || cancelled) {
          releaseCapture();
          return;
        }
        scheduleRotation();
      }

      /** Wait until the tail flush settled, then report the end of the run. */
      function settleAfterTail(flush, done) {
        const tick = function () {
          if (stopped) return;
          if (flush.armed) {
            setTimer(tick, 100);
            return;
          }
          done();
        };
        setTimer(tick, 100);
      }

      const handle = {
        stop: function (reason) {
          if (closing) return;
          closing = true;
          if (reason !== "user-stopped" && reason != null) {
            // Cancel/logout/switch are not a user finish: never transcribe tail.
            cancelled = true;
            stopped = true;
            clearRotateTimer();
            clearStallTimer();
            handoff.reset();
            if (tailFlush) {
              try { tailFlush.flush.cancel(); } catch (e) { /* already settled */ }
              tailFlush = null;
            }
            if (session) {
              try { session.close(); } catch (e) { /* already closed */ }
              session = null;
            }
            releaseCapture();
            return;
          }
          // A user-initiated stop still transcribes what was already spoken.
          // The outgoing session is retired first, so its trailing chunks are
          // consumed by the tail flush instead of the normal turn path.
          const generation = sessionGeneration;
          sessionGeneration += 1;
          clearRotateTimer();
          const flush = retireSession(session, generation, { stoppedFinal: true });
          session = null;
          releaseCapture();
          if (flush && flush.armed) {
            settleAfterTail(flush, function () {
              if (stopped) return;
              stopped = true;
              emitEnd();
            });
            return;
          }
          stopped = true;
          emitEnd();
        },
      };

      void start();
      return handle;
    };
  }

  return {
    LIVE_TRANSCRIBE_MODEL: LIVE_TRANSCRIBE_MODEL,
    LIVE_VAD_SILENCE_MS: LIVE_VAD_SILENCE_MS,
    LIVE_SESSION_ROTATE_MS: LIVE_SESSION_ROTATE_MS,
    LIVE_AUDIO_HANDOFF_FRAMES: LIVE_AUDIO_HANDOFF_FRAMES,
    LIVE_TAIL_FLUSH_DRAIN_MS: LIVE_TAIL_FLUSH_DRAIN_MS,
    TRANSCRIPT_TURN_STALL_MS: TRANSCRIPT_TURN_STALL_MS,
    LIVE_PCM_MIME: LIVE_PCM_MIME,
    LIVE_SAMPLE_RATE: LIVE_SAMPLE_RATE,
    LIVE_FRAME_SAMPLES: LIVE_FRAME_SAMPLES,
    LIVE_WORKLET_URL: LIVE_WORKLET_URL,
    LIVE_MAX_RECONNECTS: LIVE_MAX_RECONNECTS,
    ERROR_CODES: ERROR_CODES,
    PROVIDER_UNAVAILABLE_CODES: PROVIDER_UNAVAILABLE_CODES,
    errorCodeFor: errorCodeFor,
    buildLiveSetupMessage: buildLiveSetupMessage,
    buildRealtimeInputMessage: buildRealtimeInputMessage,
    buildAudioStreamEndMessage: buildAudioStreamEndMessage,
    buildLiveSocketUrl: buildLiveSocketUrl,
    float32ToInt16: float32ToInt16,
    arrayBufferToBase64: arrayBufferToBase64,
    createAudioHandoffBuffer: createAudioHandoffBuffer,
    flushLiveTranscriptTail: flushLiveTranscriptTail,
    shouldFlushStalledTurn: shouldFlushStalledTurn,
    mergeLiveTranscriptChunk: mergeLiveTranscriptChunk,
    createTranscriptTurnBuffer: createTranscriptTurnBuffer,
    createRecognizerFactory: createRecognizerFactory,
  };
});
