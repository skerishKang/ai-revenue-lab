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
    root.PadiemVoiceSttWiring = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : (typeof window !== "undefined" ? window : this), function () {
  "use strict";

  /**
   * apps/padiem-chat/static/voice-stt-wiring.js
   *
   * The product wiring stage for the shared Chat/Claw microphone (#4643).
   *
   * voice-composer.js deliberately owns no transport: it renders the mic
   * button and waits for someone to call registerRecognizerFactory(). This
   * module is that someone. It supplies exactly one thing the composer asked
   * for -- a recognizer factory -- and adds nothing else to the composer.
   *
   * Transport shape (no redesign of the reviewed pieces):
   *   getUserMedia -> MediaRecorder -> same-origin POST /api/voice/transcribe
   *   -> Chat Worker (authenticates the existing `padiem_session` cookie,
   *      resolves the canonical Control Plane session, calls the private
   *      `padiem-voice-stt` Worker over its Service Binding)
   *   -> Groq Whisper, paid only after the STT Worker's own canonical
   *      caller/tenant/cost guard admits the request.
   *
   * The browser never holds a provider key. The browser never speaks to the
   * STT Worker directly: that Worker is private and reachable only over a
   * Service Binding from the Chat Worker.
   *
   * Boundaries this file deliberately keeps:
   * - Nothing here sends a chat message. A final transcript is a *candidate*
   *   that the shared adapter places in the existing input; the user reviews
   *   or edits it and presses the existing send button.
   * - No interim text is invented. Groq transcribes a completed chunk, so the
   *   interim preview stays empty until a real final arrives rather than
   *   showing fabricated partial text.
   * - The STT Worker deployment gate, the canonical Control Plane bindings and
   *   the `voice.stt.*` entitlement grants are NOT enabled here. Until CENTRAL
   *   activates them the server answers one bounded error and this module
   *   surfaces it as a truthful mic error instead of pretending to work.
   */

  /* #87 chunking constants, verbatim from global-classroom/utils/liveTranscriptTurn.ts */
  const GROQ_MIN_CHUNK_MS = 4000;
  const GROQ_SILENCE_CUT_MS = 700;
  const GROQ_MAX_CHUNK_MS = 20000;

  const TRANSCRIBE_PATH = "/api/voice/transcribe";
  const IDENTITY_PATH = "/api/voice/identity";

  /** Best-effort MIME selection; the server accepts audio/* and re-encodes. */
  const PREFERRED_MIME_TYPES = [
    "audio/webm;codecs=opus",
    "audio/webm",
    "audio/ogg;codecs=opus",
    "audio/mp4",
  ];

  const ERROR_CODES = Object.freeze({
    PERMISSION_DENIED: "permission-denied",
    NOT_ALLOWED: "not-allowed",
    NOT_FOUND: "not-allowed",
    UNSUPPORTED: "unsupported-browser",
    UNAVAILABLE: "capture-unavailable",
    START_FAILED: "capture-start-failed",
    TRANSCRIBE_FAILED: "transcribe-failed",
  });

  function nowMs(win) {
    const perf = win && win.performance && typeof win.performance.now === "function"
      ? win.performance
      : null;
    if (perf) return perf.now();
    return Date.now();
  }

  function pickMimeType(win) {
    const ctor = win && win.MediaRecorder;
    if (typeof ctor !== "function" || typeof ctor.isTypeSupported !== "function") return "";
    for (let index = 0; index < PREFERRED_MIME_TYPES.length; index += 1) {
      const candidate = PREFERRED_MIME_TYPES[index];
      try {
        if (ctor.isTypeSupported(candidate)) return candidate;
      } catch (e) { /* try the next candidate */ }
    }
    return "";
  }

  /** Map a DOMException / Error from getUserMedia onto the composer's codes. */
  function captureErrorCode(error) {
    const name = error && typeof error.name === "string" ? error.name : "";
    if (name === "NotAllowedError" || name === "SecurityError" || name === "PermissionDeniedError") {
      return ERROR_CODES.PERMISSION_DENIED;
    }
    if (name === "NotFoundError" || name === "DevicesNotFoundError" || name === "OverconstrainedError") {
      return ERROR_CODES.NOT_ALLOWED;
    }
    if (name === "NotReadableError" || name === "TrackStartError" || name === "AbortError") {
      return ERROR_CODES.UNAVAILABLE;
    }
    return ERROR_CODES.UNAVAILABLE;
  }

  function blobToBase64(blob) {
    const reader = new FileReader();
    return new Promise(function (resolve, reject) {
      reader.onerror = function () { reject(new Error("audio-read-failed")); };
      reader.onload = function () {
        const result = reader.result;
        if (typeof result !== "string") {
          reject(new Error("audio-read-failed"));
          return;
        }
        const comma = result.indexOf(",");
        resolve(comma === -1 ? "" : result.slice(comma + 1));
      };
      reader.readAsDataURL(blob);
    });
  }

  /**
   * Build the recognizer factory consumed by voice-composer.js.
   *
   * The factory signature is the one the composer already calls:
   *   factory({onInterim, onFinal, onError, onEnd}, {generation, sessionToken})
   *     -> session handle with .stop()
   *
   * One recognizer session == one microphone run. The composer owns run
   * identity and invalidation; this recognizer only reports what it heard and
   * always tears its own capture down on stop.
   */
  function createRecognizerFactory(deps) {
    deps = deps || {};
    const win = deps.win;
    const doc = deps.doc;
    const fetchImpl = deps.fetchImpl;
    const mediaDevices = deps.mediaDevices;
    const now = typeof deps.now === "function" ? deps.now : function () { return nowMs(win); };
    const setTimer = typeof deps.setTimeout === "function" ? deps.setTimeout : win.setTimeout.bind(win);
    const clearTimer = typeof deps.clearTimeout === "function" ? deps.clearTimeout : win.clearTimeout.bind(win);

    return function recognizerFactory(callbacks, runContext) {
      callbacks = callbacks || {};
      const run = runContext || {};
      let stopped = false;
      let stream = null;
      let recorder = null;
      let audioContext = null;
      let analyser = null;
      let rafHandle = null;
      let tickHandle = null;

      // One chunk in flight at a time keeps request ordering and cost bounded.
      let chunks = [];
      let chunkStartedAt = 0;
      let speechSeenAt = 0;
      let lastSpeechAt = 0;
      let sending = false;
      let utteranceSeq = 0;
      let utteranceActive = null;

      function emitError(code) {
        if (stopped) return;
        try { if (typeof callbacks.onError === "function") callbacks.onError(code); } catch (e) { /* swallow */ }
      }

      function emitEnd() {
        if (stopped) return;
        try { if (typeof callbacks.onEnd === "function") callbacks.onEnd(); } catch (e) { /* swallow */ }
      }

      function releaseCapture() {
        if (rafHandle != null && win.cancelAnimationFrame) {
          try { win.cancelAnimationFrame(rafHandle); } catch (e) { /* already gone */ }
        }
        rafHandle = null;
        if (tickHandle != null) {
          try { clearTimer(tickHandle); } catch (e) { /* already fired */ }
        }
        tickHandle = null;
        if (analyser && audioContext && typeof audioContext.close === "function") {
          try { audioContext.close(); } catch (e) { /* already closed */ }
        }
        analyser = null;
        audioContext = null;
        if (stream && typeof stream.getTracks === "function") {
          const tracks = stream.getTracks();
          for (let index = 0; index < tracks.length; index += 1) {
            try { tracks[index].stop(); } catch (e) { /* already stopped */ }
          }
        }
        stream = null;
      }

      /** Transcribe one assembled chunk and report it as one final utterance. */
      function flushChunk(force) {
        if (stopped) return;
        if (sending) return;
        if (!chunks.length) return;
        const held = chunks;
        const elapsed = chunkStartedAt ? now() - chunkStartedAt : 0;
        chunks = [];
        chunkStartedAt = now();
        speechSeenAt = 0;
        lastSpeechAt = 0;
        // A chunk shorter than the reviewed minimum is held back unless the
        // user explicitly ended the run, so one-word fragments are not billed
        // as separate transcriptions.
        if (!force && elapsed < GROQ_MIN_CHUNK_MS) {
          chunks = held;
          return;
        }
        if (utteranceActive === null) {
          utteranceSeq += 1;
          utteranceActive = "u" + run.generation + "-" + run.sessionToken + "-" + utteranceSeq;
        }
        const blob = new win.Blob(held, { type: pickMimeType(win) || "audio/webm" });
        sending = true;
        const utteranceId = utteranceActive;
        sendChunk(blob, utteranceId).then(
          function (text) {
            sending = false;
            if (stopped) return;
            utteranceActive = null;
            if (!text) return;
            try {
              if (typeof callbacks.onFinal === "function") {
                callbacks.onFinal({ text: text, utteranceId: utteranceId });
              }
            } catch (e) { /* swallow */ }
          },
          function () {
            sending = false;
            if (stopped) return;
            utteranceActive = null;
            emitError(ERROR_CODES.TRANSCRIBE_FAILED);
          }
        );
      }

      function sendChunk(blob, utteranceId) {
        if (typeof fetchImpl !== "function") {
          return Promise.reject(new Error("no-transport"));
        }
        return blobToBase64(blob).then(function (audioBase64) {
          return fetchImpl(TRANSCRIBE_PATH, {
            method: "POST",
            credentials: "same-origin",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              audio_base64: audioBase64,
              mime_type: blob.type || "audio/webm",
              utterance_id: utteranceId,
            }),
          });
        }).then(function (response) {
          return response.json().then(function (payload) {
            if (!response.ok) {
              const code = payload && payload.error && payload.error.code;
              throw new Error(code || ERROR_CODES.TRANSCRIBE_FAILED);
            }
            return payload && typeof payload.text === "string" ? payload.text.trim() : "";
          });
        });
      }

      /** Energy gate: cut a chunk after reviewed silence, or force-cut at max. */
      function tick() {
        if (stopped) return;
        const level = rms(analyser);
        const at = now();
        if (level > 0.02) {
          if (!speechSeenAt) speechSeenAt = at;
          lastSpeechAt = at;
        }
        if (speechSeenAt && !sending && chunks.length) {
          const idle = at - lastSpeechAt;
          if (idle >= GROQ_SILENCE_CUT_MS) flushChunk(false);
          else if (chunkStartedAt && at - chunkStartedAt >= GROQ_MAX_CHUNK_MS) flushChunk(false);
        }
      }

      function rms(node) {
        if (!node || typeof node.getFloatTimeDomainData !== "function") return 0;
        if (!node._padiemBuffer || node._padiemBuffer.length !== node.fftSize) {
          node._padiemBuffer = new Float32Array(node.fftSize);
        }
        let sum = 0;
        try { node.getFloatTimeDomainData(node._padiemBuffer); } catch (e) { return 0; }
        for (let index = 0; index < node._padiemBuffer.length; index += 1) {
          sum += node._padiemBuffer[index] * node._padiemBuffer[index];
        }
        return Math.sqrt(sum / node._padiemBuffer.length);
      }

      function start() {
        if (!mediaDevices || typeof mediaDevices.getUserMedia !== "function") {
          emitError(ERROR_CODES.UNSUPPORTED);
          return;
        }
        if (typeof win.MediaRecorder !== "function") {
          emitError(ERROR_CODES.UNSUPPORTED);
          return;
        }
        let opening;
        try {
          opening = mediaDevices.getUserMedia({ audio: true });
        } catch (e) {
          emitError(captureErrorCode(e));
          return;
        }
        Promise.resolve(opening).then(
          function (opened) {
            if (stopped) {
              const tracks = opened.getTracks();
              for (let index = 0; index < tracks.length; index += 1) tracks[index].stop();
              return;
            }
            stream = opened;
            try {
              const Ctor = win.AudioContext || win.webkitAudioContext;
              audioContext = new Ctor();
              const source = audioContext.createMediaStreamSource(stream);
              analyser = audioContext.createAnalyser();
              analyser.fftSize = 1024;
              source.connect(analyser);
              chunkStartedAt = now();
              recorder = new win.MediaRecorder(stream);
              recorder.ondataavailable = function (event) {
                if (stopped || !event || !event.data || event.data.size === 0) return;
                chunks.push(event.data);
              };
              recorder.start(1000);
              tickHandle = setTimer(tick, 200);
              if (typeof win.requestAnimationFrame === "function") {
                rafHandle = win.requestAnimationFrame(function loop() {
                  if (stopped) return;
                  tick();
                  rafHandle = win.requestAnimationFrame(loop);
                });
              }
            } catch (e) {
              releaseCapture();
              emitError(ERROR_CODES.START_FAILED);
            }
          },
          function (error) {
            if (stopped) return;
            emitError(captureErrorCode(error));
          }
        );
      }

      const handle = {
        stop: function () {
          if (stopped) return;
          stopped = true;
          // A user-initiated stop still transcribes what was already spoken.
          if (recorder && recorder.state !== "inactive") {
            try { recorder.requestData(); } catch (e) { /* best effort */ }
            try { recorder.stop(); } catch (e) { /* already stopped */ }
          }
          flushChunk(true);
          releaseCapture();
          emitEnd();
        },
      };

      start();
      return handle;
    };
  }

  /**
   * Install the wiring: register the recognizer factory and keep the composer
   * informed when the *identity* behind a still-signed-in session changes.
   *
   * The identity key is an opaque value minted by /api/voice/identity. It is
   * not a user id, tenant id, email or credential -- it exists only so an
   * account switch can be detected while `authenticated` stays true. That is
   * the #3790 boolean-only auth event's blind spot.
   */
  function createVoiceSttWiring(options) {
    options = options || {};
    const win = options.win || (typeof globalThis !== "undefined" ? globalThis : null);
    const doc = options.doc || (win ? win.document : null);
    if (!win || !doc) return null;
    const composer = options.composer || win.PadiemVoiceComposer;
    if (!composer || typeof composer.registerRecognizerFactory !== "function") return null;
    const fetchImpl =
      options.fetchImpl ||
      (typeof win.fetch === "function" ? win.fetch.bind(win) : null);
    const mediaDevices =
      options.mediaDevices ||
      (win.navigator && win.navigator.mediaDevices ? win.navigator.mediaDevices : null);

    let stopped = false;
    let identityKey = "";
    let pollHandle = null;

    const factory = createRecognizerFactory({
      win: win,
      doc: doc,
      fetchImpl: fetchImpl,
      mediaDevices: mediaDevices,
      now: options.now,
    });
    composer.registerRecognizerFactory(mediaDevices && typeof win.MediaRecorder === "function" ? factory : null);

    function announceIdentity(nextKey) {
      const value = nextKey == null ? "" : String(nextKey);
      const changed = identityKey !== "" && value !== identityKey;
      identityKey = value;
      try {
        if (typeof win.CustomEvent === "function") {
          win.dispatchEvent(new win.CustomEvent("padiem:voice-identity", {
            detail: { identityKey: value },
          }));
        }
      } catch (e) { /* the composer is optional */ }
      return changed;
    }

    function refreshIdentity() {
      if (stopped || typeof fetchImpl !== "function") return Promise.resolve("");
      return fetchImpl(IDENTITY_PATH, {
        method: "GET",
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      }).then(function (response) {
        if (!response.ok) return "";
        return response.json().then(function (payload) {
          return payload && typeof payload.identity_key === "string" ? payload.identity_key : "";
        });
      }).catch(function () { return ""; });
    }

    function poll() {
      if (stopped) return;
      refreshIdentity().then(function (key) {
        if (stopped) return;
        announceIdentity(key);
        pollHandle = win.setTimeout(poll, options.intervalMs || 15000);
      });
    }

    refreshIdentity().then(function (key) {
      announceIdentity(key);
      pollHandle = win.setTimeout(poll, options.intervalMs || 15000);
    });

    return {
      factory: factory,
      refreshIdentity: refreshIdentity,
      getIdentityKey: function () { return identityKey; },
      destroy: function () {
        stopped = true;
        if (pollHandle != null) {
          try { win.clearTimeout(pollHandle); } catch (e) { /* already fired */ }
        }
        pollHandle = null;
        composer.registerRecognizerFactory(null);
      },
    };
  }

  function autoInit(root) {
    const targetWin = root || (typeof globalThis !== "undefined" ? globalThis : null);
    if (!targetWin) return null;
    const run = function () {
      return createVoiceSttWiring({ win: targetWin, doc: targetWin.document });
    };
    if (targetWin.document && targetWin.document.readyState === "loading") {
      targetWin.document.addEventListener("DOMContentLoaded", run, { once: true });
      return null;
    }
    return run();
  }

  if (typeof globalThis !== "undefined" && globalThis.document) {
    autoInit(globalThis);
  }

  return {
    GROQ_MIN_CHUNK_MS: GROQ_MIN_CHUNK_MS,
    GROQ_SILENCE_CUT_MS: GROQ_SILENCE_CUT_MS,
    GROQ_MAX_CHUNK_MS: GROQ_MAX_CHUNK_MS,
    TRANSCRIBE_PATH: TRANSCRIBE_PATH,
    IDENTITY_PATH: IDENTITY_PATH,
    ERROR_CODES: ERROR_CODES,
    createRecognizerFactory: createRecognizerFactory,
    createVoiceSttWiring: createVoiceSttWiring,
    autoInit: autoInit,
  };
});