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
   * Provider chain (the order the shared STT contract already declares):
   *
   *   1. gemini_live  -- real-time transcription. The browser asks this app for
   *      a short-lived, model-locked Live token over the same-origin route,
   *      and this app forwards that request to the private STT Worker over
   *      its Service Binding. The browser then holds ONE single-use ephemeral
   *      token for the length of one Live session and never a provider key.
   *      Interim hypotheses reach the composer input while the user speaks;
   *      one Live turn is one confirmed sentence.
   *   2. groq_whisper -- the reviewed chunk fallback. One completed audio
   *      chunk -> one candidate transcript over the same-origin route.
   *
   * The fallback is used only when the live engine cannot run at all in this
   * browser or session (no token, no WebSocket, refused session). A live
   * failure *after* words were captured is reported as an error instead, so a
   * spoken sentence is never silently dropped.
   *
   * Boundaries this file deliberately keeps:
   * - Nothing here sends a chat message. A final transcript is a *candidate*
   *   that the shared adapter places in the existing input; the user reviews
   *   or edits it and presses the existing send button.
   * - The browser never holds a provider key and never speaks to the private
   *   STT Worker directly: that Worker is private and reachable only over a
   *   Service Binding from the Chat Worker.
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
  const LIVE_TOKEN_PATH = "/api/voice/live-token";
  const CLAW_TRANSCRIBE_PATH = "/api/claw/voice/transcribe";
  const CLAW_IDENTITY_PATH = "/api/claw/voice/identity";
  const CLAW_LIVE_TOKEN_PATH = "/api/claw/voice/live-token";

  function routeForShell(doc, chatPath, clawPath) {
    const shell = doc && typeof doc.querySelector === "function" ? doc.querySelector(".app-shell") : null;
    return shell && shell.dataset && shell.dataset.state === "claw" ? clawPath : chatPath;
  }

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

  /**
   * Build the chunk recognizer factory (the reviewed fallback).
   *
   * The factory signature is the one the composer already calls:
   *   factory({onInterim, onFinal, onError, onEnd}, {generation, sessionToken})
   *     -> session handle with .stop()
   *
   * One recognizer session == one microphone run. The composer owns run
   * identity and invalidation; this recognizer only reports what it heard and
   * always tears its own capture down on stop.
   */
  function createChunkRecognizerFactory(deps) {
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
      let closing = false;
      let halting = false;
      let finalFlushDone = false;
      let finalFlushPending = false;
      let cancelled = false;
      let inflightController = null;
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
      const transcribeRoute = routeForShell(doc, TRANSCRIBE_PATH, CLAW_TRANSCRIBE_PATH);

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

      function retimeChunkWindow() {
        chunkStartedAt = now();
        speechSeenAt = 0;
        lastSpeechAt = 0;
      }

      /**
       * Start a fresh recorder run for the next chunk.
       *
       * A MediaRecorder timeslice continuation carries no WebM init segment:
       * only the first dataavailable event of a run has the EBML header. One
       * long-lived recorder therefore makes every upload after the first
       * undecodable at the provider. Each chunk gets its own run.
       */
      function startRecorderCycle() {
        chunks = [];
        retimeChunkWindow();
        const active = new win.MediaRecorder(stream);
        recorder = active;
        active.ondataavailable = function (event) {
          if (stopped || !event || !event.data || event.data.size === 0) return;
          chunks.push(event.data);
        };
        active.start(1000);
        return active;
      }

      /** Transcribe one assembled chunk and report it as one final utterance. */
      function deliverChunk(held, fromStop) {
        if (!held.length) { sending = false; return; } // silence never spends a provider call
        utteranceSeq += 1;
        const utteranceId = "u" + run.generation + "-" + run.sessionToken + "-" + utteranceSeq;
        const blob = new win.Blob(held, { type: pickMimeType(win) || "audio/webm" });
        sendChunk(blob, utteranceId).then(
          function (text) {
            sending = false;
            if (cancelled) return;
            if (finalFlushPending) {
              finalFlushPending = false;
              flushChunk(true, true);
            }
            if (!text) return;
            try {
              if (typeof callbacks.onFinal === "function") {
                callbacks.onFinal({ text: text, utteranceId: utteranceId, stopped: fromStop === true || halting });
              }
            } catch (e) { /* swallow */ }
            if (!cancelled && typeof callbacks.onTurnComplete === "function") {
              callbacks.onTurnComplete({ accepted: true, endOfTurn: true, finalId: utteranceId });
            }
          },
          function () {
            sending = false;
            if (cancelled) return;
            if (finalFlushPending) {
              finalFlushPending = false;
              flushChunk(true, true);
            }
            emitError(ERROR_CODES.TRANSCRIBE_FAILED);
          }
        );
      }

      function flushChunk(force, fromStop) {
        if (stopped && !force) return;
        if (halting && !force) return;
        if (force && finalFlushDone) return;
        if (sending) {
          if (force) finalFlushPending = true;
          return;
        }
        const active = recorder;
        if (!active || active.state === "inactive") {
          if (force && chunks.length) {
            const held = chunks;
            chunks = [];
            sending = true;
            deliverChunk(held, true);
          }
          return;
        }
        // A chunk shorter than the reviewed minimum is held back unless the
        // user explicitly ended the run, so one-word fragments are not billed
        // as separate transcriptions.
        const elapsed = chunkStartedAt ? now() - chunkStartedAt : 0;
        if (!force && elapsed < GROQ_MIN_CHUNK_MS) return;
        if (force) finalFlushDone = true;
        sending = true;
        recorder = null;
        active.onstop = function () {
          const held = chunks;
          chunks = [];
          // Restart before the upload resolves so speech during the request is
          // still captured, each time with its own init segment.
          if (!halting && !stopped && !cancelled) {
            try { startRecorderCycle(); } catch (e) { emitError(ERROR_CODES.START_FAILED); }
          }
          deliverChunk(held, fromStop === true);
        };
        try { active.requestData(); } catch (e) { /* best effort */ }
        try { active.stop(); } catch (e) { active.onstop(); }
      }

      function sendChunk(blob, utteranceId) {
        if (typeof fetchImpl !== "function") {
          return Promise.reject(new Error("no-transport"));
        }
        if (cancelled) return Promise.reject(new Error("voice-cancelled"));
        inflightController = typeof win.AbortController === "function" ? new win.AbortController() : null;
        return Promise.resolve(fetchImpl(transcribeRoute, {
          method: "POST",
          credentials: "same-origin",
          signal: inflightController ? inflightController.signal : undefined,
          headers: {
            "Content-Type": "application/octet-stream",
            "X-Padiem-Audio-Type": (blob.type || "audio/webm").split(";", 1)[0],
            "X-Padiem-Utterance-Id": utteranceId,
          },
          body: blob,
        })).then(function (response) {
          if (cancelled) throw new Error("voice-cancelled");
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
        if (halting) return;
        const level = rms(analyser);
        const at = now();
        if (level > 0.02) {
          if (!speechSeenAt) speechSeenAt = at;
          lastSpeechAt = at;
        }
        if (speechSeenAt && !sending && chunks.length) {
          const idle = at - lastSpeechAt;
          if (idle >= GROQ_SILENCE_CUT_MS || (chunkStartedAt && at - chunkStartedAt >= GROQ_MAX_CHUNK_MS)) {
            if (typeof callbacks.onAutoStopRequested === "function") {
              callbacks.onAutoStopRequested();
            }
            flushChunk(false);
          }
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
            if (halting) {
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
              startRecorderCycle();
              tickHandle = setTimer(tick, 200);
              if (typeof win.requestAnimationFrame === "function") {
                rafHandle = win.requestAnimationFrame(function loop() {
                  if (halting) return;
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
            if (halting) return;
            emitError(captureErrorCode(error));
          }
        );
      }

      const handle = {
        stop: function (reason) {
          if (closing) return;
          closing = true;
          halting = true;
          if (reason !== "user-stopped" && reason != null) {
            // Cancel/logout/switch are not a user finish: never transcribe tail.
            cancelled = true;
            stopped = true;
            finalFlushPending = false;
            chunks = [];
            if (inflightController) {
              try { inflightController.abort(); } catch (e) { /* already aborted */ }
            }
            if (recorder && recorder.state !== "inactive") {
              try { recorder.stop(); } catch (e) { /* already stopped */ }
            }
            releaseCapture();
            return;
          }
          if (rafHandle != null && win.cancelAnimationFrame) {
            try { win.cancelAnimationFrame(rafHandle); } catch (e) { /* already gone */ }
          }
          rafHandle = null;
          if (tickHandle != null) {
            try { clearTimer(tickHandle); } catch (e) { /* already fired */ }
          }
          tickHandle = null;
          // A user-initiated stop still transcribes what was already spoken.
          if (recorder && recorder.state !== "inactive") {
            const activeRecorder = recorder;
            recorder = null;
            activeRecorder.onstop = function () {
              if (!finalFlushDone) {
                flushChunk(true, true);
              }
              releaseCapture();
              stopped = true;
              emitEnd();
            };
            try { activeRecorder.requestData(); } catch (e) { /* best effort */ }
            try { activeRecorder.stop(); } catch (e) { /* already stopped */ }
            win.setTimeout(function () {
              if (!stopped) {
                if (!finalFlushDone) {
                  flushChunk(true, true);
                }
                releaseCapture();
                stopped = true;
                emitEnd();
              }
            }, 250);
          } else {
            if (!finalFlushDone) {
              flushChunk(true, true);
            }
            releaseCapture();
            stopped = true;
            emitEnd();
          }
        },
      };

      // Verify the current signed-in identity before microphone access.
      // Direct stand-alone recognizer tests have no identity authority.
      if (typeof deps.verifyIdentity === "function") {
        Promise.resolve().then(deps.verifyIdentity).then(function (key) {
          if (halting) return;
          if (typeof key !== "string" || !key) {
            emitError(ERROR_CODES.NOT_ALLOWED);
            return;
          }
          start();
        }).catch(function () {
          if (!halting) emitError(ERROR_CODES.NOT_ALLOWED);
        });
      } else {
        start();
      }
      return handle;
    };
  }

  /**
   * The live engine, loaded next to this module.
   *
   * It is optional so this module keeps working (with the reviewed chunk
   * fallback) when the live script is absent, e.g. in an isolated harness.
   */
  function liveEngine() {
    const scope = typeof globalThis !== "undefined" ? globalThis : null;
    return scope && scope.PadiemVoiceLiveTranscript
      && typeof scope.PadiemVoiceLiveTranscript.createRecognizerFactory === "function"
      ? scope.PadiemVoiceLiveTranscript
      : null;
  }

  /**
   * Build the recognizer factory consumed by voice-composer.js.
   *
   * The composer-facing contract is unchanged:
   *   factory({onInterim, onFinal, onError, onEnd, onTurnComplete},
   *           {generation, sessionToken}) -> session handle with .stop()
   *
   * The live engine is tried first, because real-time transcription is the
   * behaviour the product asks for. The reviewed chunk recognizer takes over
   * only when the live engine reports that it cannot run at all, so a run is
   * never lost and a spoken sentence is never silently dropped.
   */
  function createRecognizerFactory(deps) {
    deps = deps || {};
    const win = deps.win;
    const doc = deps.doc;

    // The identity is verified once for the whole run, so the fallback does
    // not repeat the request.
    const chunkDeps = Object.assign({}, deps);
    delete chunkDeps.verifyIdentity;
    const chunkFactory = createChunkRecognizerFactory(chunkDeps);

    const live = liveEngine();
    const liveFactory = live
      ? live.createRecognizerFactory({
        win: win,
        fetchImpl: deps.fetchImpl,
        mediaDevices: deps.mediaDevices,
        liveTokenPath: routeForShell(doc, LIVE_TOKEN_PATH, CLAW_LIVE_TOKEN_PATH),
        WebSocketCtor: deps.WebSocketCtor,
        now: deps.now,
        setTimeout: deps.setTimeout,
        clearTimeout: deps.clearTimeout,
      })
      : null;

    return function recognizerFactory(callbacks, runContext) {
      callbacks = callbacks || {};
      const run = runContext || {};
      let active = null;
      let cancelled = false;

      function attach(providerHandle) {
        if (!providerHandle || typeof providerHandle.stop !== "function") return false;
        if (cancelled) {
          try { providerHandle.stop("cancelled"); } catch (e) { /* already gone */ }
          return false;
        }
        active = providerHandle;
        return true;
      }

      function reportError(code) {
        try { if (typeof callbacks.onError === "function") callbacks.onError(code); }
        catch (e) { /* swallow */ }
      }

      function startChunk() {
        attach(chunkFactory(callbacks, run));
      }

      function startLive() {
        if (!liveFactory) {
          startChunk();
          return;
        }
        const liveCallbacks = {
          onInterim: callbacks.onInterim,
          onFinal: callbacks.onFinal,
          onEnd: callbacks.onEnd,
          onTurnComplete: callbacks.onTurnComplete,
          onAutoStopRequested: callbacks.onAutoStopRequested,
          onError: callbacks.onError,
          onProviderUnavailable: function () {
            // The live engine cannot run in this browser or session. Nothing
            // was transcribed yet, so the reviewed chunk fallback takes the
            // run over without losing a word. The live handle is released
            // first, otherwise it would still own the run.
            if (cancelled) return;
            if (active) {
              try { active.stop("provider-unavailable"); } catch (e) { /* already gone */ }
              active = null;
            }
            startChunk();
          },
        };
        attach(liveFactory(liveCallbacks, run));
      }

      const handle = {
        stop: function (reason) {
          cancelled = true;
          if (active && typeof active.stop === "function") {
            try { active.stop(reason); } catch (e) { /* the recognizer is already gone */ }
          }
          active = null;
        },
      };

      // Verify the current signed-in identity before microphone access.
      // Direct stand-alone recognizer tests have no identity authority.
      if (typeof deps.verifyIdentity === "function") {
        Promise.resolve().then(deps.verifyIdentity).then(function (key) {
          if (cancelled) return;
          if (typeof key !== "string" || !key) {
            reportError(ERROR_CODES.NOT_ALLOWED);
            return;
          }
          startLive();
        }).catch(function () {
          if (!cancelled) reportError(ERROR_CODES.NOT_ALLOWED);
        });
      } else {
        startLive();
      }
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
    let identityRefreshSeq = 0;
    const identityListeners = [];

    const factory = createRecognizerFactory({
      win: win,
      doc: doc,
      fetchImpl: fetchImpl,
      mediaDevices: mediaDevices,
      now: options.now,
      WebSocketCtor: options.WebSocketCtor,
      verifyIdentity: function () { return verifyIdentity(); },
    });
    // The live engine needs a WebSocket and a microphone; the chunk fallback
    // needs a microphone only.
    const canCapture = !!(mediaDevices && typeof win.MediaRecorder === "function");

    function registerFactory(available) {
      composer.registerRecognizerFactory(available && canCapture ? factory : null);
    }

    // STT stays default-off until the same-origin Chat app reports that its
    // private STT transport is actually configured. This prevents a signed-in
    // browser from showing a ready microphone when the server cannot transcribe.
    registerFactory(false);
    if (typeof fetchImpl === "function") {
      fetchImpl("/health", { method: "GET", credentials: "same-origin" })
        .then(function (response) {
          if (!response || !response.ok) { registerFactory(false); return null; }
          return response.json();
        })
        .then(function (payload) {
          registerFactory(payload && payload.voice_stt_available === true);
        })
        .catch(function () { registerFactory(false); });
    }

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
      return fetchImpl(routeForShell(doc, IDENTITY_PATH, CLAW_IDENTITY_PATH), {
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

    // #4979: account verification follows lifecycle events, not an idle timer.
    // Sequence fencing prevents a late response from an old login from
    // overwriting the newest account identity.
    function verifyIdentity() {
      if (stopped) return Promise.resolve("");
      const sequence = ++identityRefreshSeq;
      const pending = refreshIdentity().then(function (key) {
        if (stopped || sequence !== identityRefreshSeq) return "";
        announceIdentity(key);
        return key;
      });
      return pending;
    }

    function listen(target, name, handler) {
      if (!target || typeof target.addEventListener !== "function") return;
      target.addEventListener(name, handler);
      identityListeners.push([target, name, handler]);
    }
    const onAuthChange = function () { verifyIdentity(); };
    for (const eventName of ["padiem:auth-state", "padiem:auth-changed", "padiem:account-changed"]) {
      listen(win, eventName, onAuthChange);
    }
    // Cross-tab sign-in changes become observable at tab reactivation, without
    // using identity material in browser storage.
    listen(win, "focus", onAuthChange);
    listen(doc, "visibilitychange", function () {
      if (!doc.hidden) verifyIdentity();
    });
    verifyIdentity();

    return {
      factory: factory,
      refreshIdentity: verifyIdentity,
      getIdentityKey: function () { return identityKey; },
      destroy: function () {
        stopped = true;
        identityRefreshSeq += 1;
        for (const entry of identityListeners) {
          if (typeof entry[0].removeEventListener === "function") {
            entry[0].removeEventListener(entry[1], entry[2]);
          }
        }
        identityListeners.length = 0;
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
    CLAW_TRANSCRIBE_PATH: CLAW_TRANSCRIBE_PATH,
    CLAW_IDENTITY_PATH: CLAW_IDENTITY_PATH,
    IDENTITY_PATH: IDENTITY_PATH,
    LIVE_TOKEN_PATH: LIVE_TOKEN_PATH,
    CLAW_LIVE_TOKEN_PATH: CLAW_LIVE_TOKEN_PATH,
    ERROR_CODES: ERROR_CODES,
    createRecognizerFactory: createRecognizerFactory,
    createChunkRecognizerFactory: createChunkRecognizerFactory,
    createVoiceSttWiring: createVoiceSttWiring,
    autoInit: autoInit,
  };
});
