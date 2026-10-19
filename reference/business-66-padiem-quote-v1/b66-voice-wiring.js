/* #3404: B66 "한번에 말하기" 음성 입력 wiring
 *
 * 기존 Chat/Claw 공유 STT 계약(#4643)을 재사용한다:
 *   - POST /api/padiem/voice/transcribe, GET /api/padiem/voice/identity
 *     (B66 Pages 함수를 경유해 chat.padiem.net의 padiem-chat Worker와 동일한
 *      padiem_session 쿠폰/권한을 사용한다)
 *   - padiem:voice-identity 이벤트(계정 전환 감지), padiem:voice-accepted-turn
 *     이벤트(최종 발화)
 *   - GROQ_MIN_CHUNK_MS/GROQ_SILENCE_CUT_MS/GROQ_MAX_CHUNK_MS 청크 계약
 *   - STT는 기본 OFF: 서명된 세션과 voice_stt_available 이 모두 참일 때만
 *      마이크 사용 가능
 *
 * Mode A(기본, 수동 전송): 마이크 시작 → 전사 → easyComposer 입력창에 기록
 *      (편집 가능) → 사용자가 easySend 버튼으로 전송
 * Mode B(자동 전송): 라이브 모드 무장 시 최종 발화 확정 후 정확히 1회 자동
 *      전송(중복·재전송 방지)
 *
 * QuoteCore·Saved Quote Skill·견적 저장·PDF 경로는 건드리지 않는다.
 * #4816(Chat/Claw 음성 4모드 UI) 파일은 건드리지 않는다.
 */

(function (root, factory) {
  "use strict";
  const api = factory();
  if (typeof module === "object" && module && module.exports) module.exports = api;
  if (root) root.PadiemB66VoiceWiring = api;
})(typeof globalThis !== "undefined" ? globalThis : (typeof window !== "undefined" ? window : this), function () {
  "use strict";

  const MIC_ID = "easyVoiceMic";
  const LIVE_TOGGLE_ID = "easyVoiceLiveToggle";
  const COMPOSER_ID = "easyComposer";
  const SEND_ID = "easySend";
  const NOTE_ID = "easyComposerNote";

  const TRANSCRIBE_PATH = "/api/padiem/voice/transcribe";
  const IDENTITY_PATH = "/api/padiem/voice/identity";

  const GROQ_MIN_CHUNK_MS = 4000;
  const GROQ_SILENCE_CUT_MS = 700;
  const GROQ_MAX_CHUNK_MS = 20000;

  const ERROR_CODES = Object.freeze({
    PERMISSION_DENIED: "permission-denied",
    NOT_ALLOWED: "not-allowed",
    UNSUPPORTED: "unsupported-browser",
    UNAVAILABLE: "capture-unavailable",
    START_FAILED: "capture-start-failed",
    TRANSCRIBE_FAILED: "transcribe-failed",
    STT_UNAVAILABLE: "stt-unavailable",
  });

  const KO = {
    mic: "음성 입력",
    micStart: "음성 입력 시작",
    micStop: "음성 입력 중지",
    liveOff: "자동 전송 끔",
    liveOn: "자동 전송 켬",
    listening: "듣고 있습니다.",
    final: "전사문을 입력창에 추가했습니다. 검토 후 보내기를 눌러 주세요.",
    stopped: "음성 입력이 중지되었습니다.",
    error: "음성 입력이 실패했습니다. 다시 시도하거나 직접 입력해 주세요.",
    errorPermission: "마이크 권한이 거부되었습니다. 브라우저 설정을 확인하거나 직접 입력해 주세요.",
    errorUnsupported: "이 브라우저는 음성 입력을 지원하지 않습니다. 직접 입력해 주세요.",
    errorUnavailable: "음성 입력 서비스를 사용할 수 없습니다. 직접 입력해 주세요.",
    liveAutoSend: "최종 전사 확정 후 한 번만 자동 전송합니다.",
  };
  const EN = {
    mic: "Voice input",
    micStart: "Start voice input",
    micStop: "Stop voice input",
    liveOff: "Auto-send off",
    liveOn: "Auto-send on",
    listening: "Listening.",
    final: "Transcript added to the input. Review or edit it, then press send.",
    stopped: "Voice input stopped.",
    error: "Voice input failed. Try again or type instead.",
    errorPermission: "Microphone permission was denied. Check browser settings or type instead.",
    errorUnsupported: "This browser does not support voice input. Please type instead.",
    errorUnavailable: "Voice input service is unavailable. Please type instead.",
    liveAutoSend: "Send once automatically after the final utterance is confirmed.",
  };
  function t(key) {
    const ko = /^ko/i.test((typeof document !== "undefined" && document.documentElement) ? document.documentElement.lang || "ko" : "ko");
    return (ko ? KO : EN)[key] || key;
  }

  function norm(value) { return value == null ? "" : String(value); }

  function mergeChunk(previous, incoming) {
    const p = norm(previous); const inc = norm(incoming);
    if (!inc) return p; if (!p) return inc;
    if (inc.startsWith(p)) return inc; if (p.endsWith(inc)) return p;
    return p + inc;
  }
  function createTurnBuffer() {
    let pending = "";
    return {
      get pending() { return pending; },
      merge(chunk) { if (!chunk) return pending; pending = mergeChunk(pending, String(chunk)); return pending; },
      finishTurn() { const text = pending.trim(); pending = ""; return text || null; },
      reset() { pending = ""; },
    };
  }
  function makeToken() { return Date.now().toString(36) + "_" + Math.random().toString(36).slice(2, 10); }

  /* ---------- recognizer (MediaRecorder -> /api/padiem/voice/transcribe) ---------- */
  function pickMimeType(win) {
    const ctor = win && win.MediaRecorder;
    if (typeof ctor !== "function" || typeof ctor.isTypeSupported !== "function") return "";
    const candidates = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4"];
    for (let i = 0; i < candidates.length; i += 1) {
      try { if (ctor.isTypeSupported(candidates[i])) return candidates[i]; } catch (e) { /* try next */ }
    }
    return "";
  }
  function captureErrorCode(error) {
    const name = error && typeof error.name === "string" ? error.name : "";
    if (name === "NotAllowedError" || name === "SecurityError" || name === "PermissionDeniedError") return ERROR_CODES.PERMISSION_DENIED;
    if (name === "NotFoundError" || name === "DevicesNotFoundError" || name === "OverconstrainedError") return ERROR_CODES.NOT_ALLOWED;
    if (name === "NotReadableError" || name === "TrackStartError" || name === "AbortError") return ERROR_CODES.UNAVAILABLE;
    return ERROR_CODES.UNAVAILABLE;
  }
  function blobToBase64(blob) {
    const reader = new FileReader();
    return new Promise(function (resolve, reject) {
      reader.onerror = function () { reject(new Error("audio-read-failed")); };
      reader.onload = function () {
        const result = reader.result;
        if (typeof result !== "string") { reject(new Error("audio-read-failed")); return; }
        const comma = result.indexOf(",");
        resolve(comma === -1 ? "" : result.slice(comma + 1));
      };
      reader.readAsDataURL(blob);
    });
  }

  function createRecognizer(deps) {
    const win = deps.win;
    const fetchImpl = deps.fetchImpl;
    const mediaDevices = deps.mediaDevices;
    const now = typeof deps.now === "function" ? deps.now : Date.now;
    const setTimer = typeof deps.setTimeout === "function" ? deps.setTimeout : win.setTimeout.bind(win);
    const clearTimer = typeof deps.clearTimeout === "function" ? deps.clearTimeout : win.clearTimeout.bind(win);
    const callbacks = deps.callbacks || {};
    const generation = deps.generation == null ? 1 : deps.generation;
    const sessionToken = deps.sessionToken == null ? makeToken() : String(deps.sessionToken);

    let stopped = false, closing = false, halting = false, cancelled = false, sending = false;
    let finalFlushDone = false, finalFlushPending = false;
    let stream = null, recorder = null, audioContext = null, analyser = null;
    let rafHandle = null, tickHandle = null, inflightController = null;
    let chunks = [], chunkStartedAt = 0, speechSeenAt = 0, lastSpeechAt = 0;
    let utteranceSeq = 0;

    function emitError(code) { if (stopped) return; try { if (typeof callbacks.onError === "function") callbacks.onError(code); } catch (e) {} }
    function emitEnd() { if (stopped) return; try { if (typeof callbacks.onEnd === "function") callbacks.onEnd(); } catch (e) {} }
    function releaseCapture() {
      if (rafHandle != null && win.cancelAnimationFrame) { try { win.cancelAnimationFrame(rafHandle); } catch (e) {} }
      rafHandle = null;
      if (tickHandle != null) { try { clearTimer(tickHandle); } catch (e) {} }
      tickHandle = null;
      if (analyser && audioContext && typeof audioContext.close === "function") { try { audioContext.close(); } catch (e) {} }
      analyser = null; audioContext = null;
      if (stream && typeof stream.getTracks === "function") {
        const tracks = stream.getTracks();
        for (let i = 0; i < tracks.length; i += 1) { try { tracks[i].stop(); } catch (e) {} }
      }
      stream = null;
    }
    function retimeChunkWindow() {
      chunkStartedAt = now(); speechSeenAt = 0; lastSpeechAt = 0;
    }
    function startRecorderCycle() {
      // A timeslice continuation has no WebM init segment: only the first
      // dataavailable event of a recorder run carries the EBML header. Each
      // uploaded chunk therefore needs a fresh recorder run, or every chunk
      // after the first reaches the provider undecodable.
      chunks = [];
      retimeChunkWindow();
      const active = new win.MediaRecorder(stream);
      recorder = active;
      active.ondataavailable = function (event) {
        if (!event || !event.data || event.data.size === 0) return;
        chunks.push(event.data);
      };
      active.start(1000);
      return active;
    }
    function deliverChunk(held, fromStop) {
      if (!held.length) { sending = false; return; }
      utteranceSeq += 1;
      const utteranceId = "u" + generation + "-" + sessionToken + "-" + utteranceSeq;
      const blob = new win.Blob(held, { type: pickMimeType(win) || "audio/webm" });
      sendChunk(blob, utteranceId).then(function (text) {
        sending = false;
        if (cancelled) return;
        if (finalFlushPending) { finalFlushPending = false; flushChunk(true, true); }
        if (!text) return;
        try { if (typeof callbacks.onFinal === "function") callbacks.onFinal({ text, utteranceId, stopped: fromStop === true || halting }); } catch (e) {}
        if (!cancelled && typeof callbacks.onTurnComplete === "function") { try { callbacks.onTurnComplete({ accepted: true, endOfTurn: true, finalId: utteranceId }); } catch (e) {} }
      }, function () {
        sending = false;
        if (cancelled) return;
        if (finalFlushPending) { finalFlushPending = false; flushChunk(true, true); }
        emitError(ERROR_CODES.TRANSCRIBE_FAILED);
      });
    }
    function flushChunk(force, fromStop) {
      if (stopped && !force) return;
      if (halting && !force) return;
      if (force && finalFlushDone) return;
      if (sending) { if (force) finalFlushPending = true; return; }
      const active = recorder;
      if (!active || active.state === "inactive") {
        if (force && chunks.length) {
          const held = chunks; chunks = []; sending = true; deliverChunk(held, true);
        }
        return;
      }
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
      if (typeof fetchImpl !== "function") return Promise.reject(new Error("no-transport"));
      return blobToBase64(blob).then(function (audioBase64) {
        if (cancelled) throw new Error("voice-cancelled");
        inflightController = typeof win.AbortController === "function" ? new win.AbortController() : null;
        return fetchImpl(TRANSCRIBE_PATH, {
          method: "POST", credentials: "same-origin",
          signal: inflightController ? inflightController.signal : undefined,
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ audio_base64: audioBase64, mime_type: blob.type || "audio/webm", utterance_id: utteranceId }),
        });
      }).then(function (response) {
        if (cancelled) throw new Error("voice-cancelled");
        return response.json().then(function (payload) {
          if (!response.ok) { const code = payload && payload.error && payload.error.code; throw new Error(code || ERROR_CODES.TRANSCRIBE_FAILED); }
          return payload && typeof payload.text === "string" ? payload.text.trim() : "";
        });
      });
    }
    function tick() {
      if (halting) return;
      const level = rms(analyser);
      const at = now();
      if (level > 0.02) { if (!speechSeenAt) speechSeenAt = at; lastSpeechAt = at; }
      if (speechSeenAt && !sending && chunks.length) {
        const idle = at - lastSpeechAt;
        if (idle >= GROQ_SILENCE_CUT_MS || (chunkStartedAt && at - chunkStartedAt >= GROQ_MAX_CHUNK_MS)) {
          if (typeof callbacks.onAutoStopRequested === "function") callbacks.onAutoStopRequested();
          flushChunk(false);
        }
      }
    }
    function rms(node) {
      if (!node || typeof node.getFloatTimeDomainData !== "function") return 0;
      if (!node._padiemBuffer || node._padiemBuffer.length !== node.fftSize) { node._padiemBuffer = new Float32Array(node.fftSize); }
      let sum = 0;
      try { node.getFloatTimeDomainData(node._padiemBuffer); } catch (e) { return 0; }
      for (let i = 0; i < node._padiemBuffer.length; i += 1) sum += node._padiemBuffer[i] * node._padiemBuffer[i];
      return Math.sqrt(sum / node._padiemBuffer.length);
    }
    function start() {
      if (!mediaDevices || typeof mediaDevices.getUserMedia !== "function") { emitError(ERROR_CODES.UNSUPPORTED); return; }
      if (typeof win.MediaRecorder !== "function") { emitError(ERROR_CODES.UNSUPPORTED); return; }
      mediaDevices.getUserMedia({ audio: true }).then(function (opened) {
        if (halting) { try { opened.getTracks().forEach(function (t) { t.stop(); }); } catch (e) {} return; }
        stream = opened;
        try {
          const Ctor = win.AudioContext || win.webkitAudioContext;
          audioContext = new Ctor();
          const source = audioContext.createMediaStreamSource(stream);
          analyser = audioContext.createAnalyser(); analyser.fftSize = 1024;
          source.connect(analyser);
          startRecorderCycle();
          tickHandle = setTimer(tick, 200);
          if (typeof win.requestAnimationFrame === "function") {
            rafHandle = win.requestAnimationFrame(function loop() { if (halting) return; tick(); rafHandle = win.requestAnimationFrame(loop); });
          }
          if (typeof callbacks.onStart === "function") { try { callbacks.onStart(); } catch (e) {} }
        } catch (e) { releaseCapture(); emitError(ERROR_CODES.START_FAILED); }
      }, function (error) { if (!halting) emitError(captureErrorCode(error)); });
    }
    const handle = {
      stop: function (reason) {
        if (closing) return;
        closing = true; halting = true;
        if (reason !== "user-stopped" && reason != null) {
          cancelled = true; stopped = true; finalFlushPending = false; chunks = [];
          if (inflightController) { try { inflightController.abort(); } catch (e) {} }
          if (recorder && recorder.state !== "inactive") { try { recorder.stop(); } catch (e) {} }
          releaseCapture();
          return;
        }
        if (rafHandle != null && win.cancelAnimationFrame) { try { win.cancelAnimationFrame(rafHandle); } catch (e) {} }
        rafHandle = null;
        if (tickHandle != null) { try { clearTimer(tickHandle); } catch (e) {} }
        tickHandle = null;
        if (recorder && recorder.state !== "inactive") {
          const activeRecorder = recorder; recorder = null;
          activeRecorder.onstop = function () {
            if (!finalFlushDone) flushChunk(true, true);
            releaseCapture(); stopped = true; emitEnd();
          };
          try { activeRecorder.requestData(); } catch (e) {}
          try { activeRecorder.stop(); } catch (e) {}
          setTimer(function () {
            if (!stopped) { if (!finalFlushDone) flushChunk(true, true); releaseCapture(); stopped = true; emitEnd(); }
          }, 250);
        } else {
          if (!finalFlushDone) flushChunk(true, true);
          releaseCapture(); stopped = true; emitEnd();
        }
      },
    };
    if (typeof deps.verifyIdentity === "function") {
      Promise.resolve().then(deps.verifyIdentity).then(function (key) {
        if (halting) return;
        if (typeof key !== "string" || !key) { emitError(ERROR_CODES.NOT_ALLOWED); return; }
        start();
      }).catch(function () { if (!halting) emitError(ERROR_CODES.NOT_ALLOWED); });
    } else {
      start();
    }
    return handle;
  }

  /* ---------- adapter (turn buffer + dedup) ---------- */
  function createInputAdapter(options) {
    options = options || {};
    const generation = options.generation == null ? 1 : options.generation;
    const sessionToken = options.sessionToken == null ? makeToken() : String(options.sessionToken);
    const cbState = typeof options.onState === "function" ? options.onState : function () {};
    const cbInterim = typeof options.onInterim === "function" ? options.onInterim : function () {};
    const cbFinal = typeof options.onFinalCandidate === "function" ? options.onFinalCandidate : function () {};
    const cbError = typeof options.onError === "function" ? options.onError : function () {};
    let input = options.input || null;
    if (input && typeof input.value === "string" && typeof input.setValue !== "function") {
      const el = input; input = { getValue: function () { return el.value; }, setValue: function (v) { el.value = v; } };
    }
    const turnBuffer = createTurnBuffer();
    const emittedUtterances = new Set();
    let state = "idle";
    let currentUtteranceId = null;
    let stopped = false, destroyed = false;
    function emitState(next) { if (destroyed) return state; state = next; try { cbState(state); } catch (e) {} return state; }
    function start() { if (destroyed || stopped) return false; if (state !== "idle") return false; turnBuffer.reset(); emittedUtterances.clear(); currentUtteranceId = null; stopped = false; return emitState("listening") === "listening"; }
    function feedInterim(text, ctx) {
      ctx = ctx || {};
      if (destroyed || stopped) return { ok: false, reason: "stopped" };
      if (state === "error") return { ok: false, reason: "error-state" };
      if (state !== "listening" && state !== "interim" && state !== "final") return { ok: false, reason: "not-listening" };
      if (ctx.generation != null && ctx.generation !== generation) return { ok: false, reason: "stale-generation" };
      if (ctx.sessionToken != null && String(ctx.sessionToken) !== sessionToken) return { ok: false, reason: "stale-session" };
      if (ctx.destroyed === true) return { ok: false, reason: "invalidated" };
      const t = norm(text); if (!t) return { ok: false, reason: "empty" };
      turnBuffer.merge(t); const preview = turnBuffer.pending;
      emitState("interim"); try { cbInterim(preview, ctx); } catch (e) {}
      return { ok: true, preview: preview };
    }
    function commitFinal(opts) {
      opts = opts || {};
      if (destroyed) return { ok: false, reason: "stopped" };
      const stopFlush = opts && opts.stopped === true;
      if (stopped && !stopFlush) return { ok: false, reason: "stopped" };
      if (state === "error") return { ok: false, reason: "error-state" };
      if (stopFlush && stopped && (state === "stopped" || state === "listening" || state === "interim" || state === "final")) { /* allow final after user stop */ }
      else if (state !== "listening" && state !== "interim" && state !== "final") return { ok: false, reason: "not-listening" };
      if (opts.destroyed === true) return { ok: false, reason: "invalidated" };
      if (opts.generation != null && opts.generation !== generation) return { ok: false, reason: "stale-generation" };
      if (opts.sessionToken != null && String(opts.sessionToken) !== sessionToken) return { ok: false, reason: "stale-session" };
      const utteranceId = opts.utteranceId != null ? String(opts.utteranceId) : null;
      if (!utteranceId && opts.text != null) return { ok: false, reason: "missing-utterance-id" };
      if (utteranceId && emittedUtterances.has(utteranceId)) return { ok: false, reason: "duplicate-utterance", utteranceId: utteranceId };
      let text = opts.text != null ? String(opts.text) : turnBuffer.finishTurn();
      if (text == null) text = turnBuffer.finishTurn();
      text = norm(text).trim();
      if (!text) { turnBuffer.reset(); return { ok: false, reason: "empty" }; }
      if (utteranceId) emittedUtterances.add(utteranceId);
      currentUtteranceId = utteranceId;
      emitState("final");
      try { appendToInput(text, "append", stopFlush); } catch (e) {}
      try { cbFinal(text, utteranceId); } catch (e) {}
      turnBuffer.reset();
      return { ok: true, text: text, utteranceId: utteranceId };
    }
    function appendToInput(text, mode, flush) {
      if (destroyed || (stopped && !flush)) return null;
      text = norm(text); if (!text) return null;
      let current = "";
      if (input && typeof input.getValue === "function") current = norm(input.getValue());
      else if (input && typeof input.value !== "undefined") current = norm(input.value);
      let next = current;
      if ((mode || "append") === "replace") { next = text; }
      else { if (current && !/\s$/.test(current)) next = current + " "; next = next + text; }
      if (input && typeof input.setValue === "function") input.setValue(next);
      else if (input) input.value = next;
      return next;
    }
    function stop(reason) {
      if (destroyed) return state;
      stopped = true; turnBuffer.reset(); emitState("stopped");
      if (reason) { try { cbError(String(reason)); } catch (e) {} }
      return state;
    }
    function error(code) { if (destroyed) return state; turnBuffer.reset(); emitState("error"); try { cbError(String(code || "voice_stt_error")); } catch (e) {} return state; }
    function invalidate(reason) { turnBuffer.reset(); emitState("stopped"); destroyed = true; try { cbError(String(reason || "invalidated")); } catch (e) {} return state; }
    return { start, feedInterim, commitFinal, stop, error, invalidate, appendToInput, getState: function () { return state; }, getGeneration: function () { return generation; }, getSessionToken: function () { return sessionToken; } };
  }

  /* ---------- live-turn-controller (Mode B, exactly-once auto send) ---------- */
  function createLiveTurnController(opts) {
    opts = opts || {};
    const account = typeof opts.getAccountKey === "function" ? opts.getAccountKey : null;
    const busy = typeof opts.getInFlight === "function" ? opts.getInFlight : null;
    const canSend = typeof opts.getCanSubmit === "function" ? opts.getCanSubmit : null;
    const commit = typeof opts.commitText === "function" ? opts.commitText : null;
    const send = typeof opts.submit === "function" ? opts.submit : null;
    const preview = typeof opts.onPreview === "function" ? opts.onPreview : function () {};
    const notify = typeof opts.onStateChange === "function" ? opts.onStateChange : function () {};
    let key = String(opts.accountKey || "").trim();
    let generation = 1;
    let mode = "basic";
    let cancelled = false, revoked = false, composing = false;
    let seen = new Set(), outstanding = null;
    function auth() { if (!key || !account) return false; try { return String(account() || "").trim() === key; } catch (_) { return false; } }
    function ready() { if (!busy || !canSend || !commit || !send) return false; try { return busy() === false && canSend() === true; } catch (_) { return false; } }
    function report() { try { notify({ mode, accountKey: key, sessionGeneration: generation, cancelled, invalidated: revoked, composing, waitingForAnswer: !!outstanding, seenCount: seen.size }); } catch (_) {} }
    function blocked(reason) { return { ok: false, reason, submitted: false }; }
    function rotate() { generation += 1; seen = new Set(); }
    function validate(p) {
      if (!auth() || p.accountKey !== key) return "unauthenticated-or-account-mismatch";
      if (!Number.isSafeInteger(p.sessionGeneration) || p.sessionGeneration !== generation) return "missing-or-stale-generation";
      return "";
    }
    function setMode(v) { const n = v === "live" ? "live" : "basic"; if (n !== mode) { mode = n; rotate(); } cancelled = false; revoked = false; report(); }
    function setAccountKey(value) { const n = String(value || "").trim(); if (n !== key) { key = n; rotate(); outstanding = null; cancelled = true; revoked = true; } report(); }
    function setCompositionActive(v) { composing = v === true; report(); }
    function endComposition() { composing = false; report(); }
    function handleFinal(p) {
      p = p || {};
      if (mode !== "live" || cancelled || revoked) return blocked("mode-not-live-or-revoked");
      const error = validate(p);
      if (error) return blocked(error);
      if (p.accepted !== true || p.endOfTurn !== true) return blocked("not-accepted-end-of-turn");
      const id = String(p.finalId || "").trim();
      const value = norm(p.text || p.finalText);
      if (!id || !value) return blocked("missing-id-or-text");
      if (composing) return blocked("ime-active");
      // The app re-enables its send button when the previous answer lands; a
      // still-busy app is the only reason a later utterance must wait.
      if (outstanding && !ready()) return blocked("previous-answer-pending");
      if (!ready()) return blocked("not-ready");
      outstanding = null;
      const finalKey = key + ":" + generation + ":" + id;
      if (seen.has(finalKey)) return blocked("duplicate");
      if (seen.size >= 1024) return blocked("utterance-limit");
      seen.add(finalKey);
      try {
        if (commit(value) === false) return blocked("composer-rejected");
        if (!auth() || !ready() || revoked || cancelled) return blocked("state-changed");
        if (send(value, { finalKey, accountKey: key, sessionGeneration: generation }) === false) return blocked("send-rejected");
        outstanding = { finalKey, accountKey: key };
      } catch (_) { return blocked("send-or-commit-error"); }
      finally { report(); }
      return { ok: true, reason: "submitted", submitted: true, finalKey };
    }
    return { getState: function () { return { mode, accountKey: key, sessionGeneration: generation, cancelled, invalidated: revoked, composing, waitingForAnswer: !!outstanding, seenCount: seen.size }; }, setMode, setAccountKey, setCompositionActive, endComposition, handleFinal };
  }

  /* ---------- wiring ---------- */
  function createB66VoiceWiring(options) {
    options = options || {};
    const win = options.win || (typeof globalThis !== "undefined" ? globalThis : null);
    const doc = options.doc || (win ? win.document : null);
    if (!win || !doc) return null;
    const mic = doc.getElementById(MIC_ID);
    const composer = doc.getElementById(COMPOSER_ID);
    const send = doc.getElementById(SEND_ID);
    const note = doc.getElementById(NOTE_ID);
    if (!mic || !composer || !send) return null;

    const fetchImpl = options.fetchImpl || (typeof win.fetch === "function" ? win.fetch.bind(win) : null);
    const mediaDevices = options.mediaDevices || (win.navigator && win.navigator.mediaDevices ? win.navigator.mediaDevices : null);

    let identityKey = "";
    let identityRefreshSeq = 0;
    let sttAvailable = false;
    let wiringStopped = false;
    let recognizer = null;
    let adapter = null;
    let controller = null;
    let mode = "basic";
    let liveToggleEl = null;
    let captureStarted = false;
    let listeners = [];

    function listen(target, name, handler) {
      if (!target || typeof target.addEventListener !== "function") return;
      target.addEventListener(name, handler);
      listeners.push([target, name, handler]);
    }
    function announceIdentity(nextKey) {
      const value = nextKey == null ? "" : String(nextKey);
      const changed = identityKey !== "" && value !== identityKey;
      identityKey = value;
      try { if (typeof win.CustomEvent === "function") win.dispatchEvent(new win.CustomEvent("padiem:voice-identity", { detail: { identityKey: value } })); } catch (e) {}
      return changed;
    }
    function refreshIdentity() {
      if (wiringStopped || typeof fetchImpl !== "function") return Promise.resolve("");
      return fetchImpl(IDENTITY_PATH, { method: "GET", credentials: "same-origin", headers: { Accept: "application/json" } })
        .then(function (response) { if (!response.ok) return ""; return response.json().then(function (payload) { return payload && typeof payload.identity_key === "string" ? payload.identity_key : ""; }); })
        .catch(function () { return ""; });
    }
    function verifyIdentity() {
      if (wiringStopped) return Promise.resolve("");
      const sequence = ++identityRefreshSeq;
      return refreshIdentity().then(function (key) {
        if (wiringStopped || sequence !== identityRefreshSeq) return "";
        if (typeof key === "string" && key !== "") { if (key !== identityKey) announceIdentity(key); }
        else if (identityKey !== "") { announceIdentity(""); }
        return key;
      });
    }
    function updateMicState() {
      const ready = sttAvailable && identityKey !== "";
      mic.disabled = !ready;
      mic.setAttribute("aria-disabled", String(!ready));
      // 마이크 상태는 "요청됨"이 아니라 실제 캡처 시작 시점에 맞춘다.
      // getUserMedia 승인 전에 중지하면 듣고 있다고 표시하지 않는다.
      const listening = !!recognizer && captureStarted;
      mic.setAttribute("aria-label", ready ? (listening ? t("micStop") : t("micStart")) : t("errorUnavailable"));
      mic.setAttribute("title", mic.getAttribute("aria-label"));
      mic.setAttribute("data-voice-state", ready ? (listening ? "listening" : "starting") : "unavailable");
      mic.setAttribute("aria-pressed", String(listening));
      composer.disabled = !ready;
      send.disabled = !ready;
      if (liveToggleEl) liveToggleEl.disabled = !ready;
      if (!ready) {
        note.textContent = t("errorUnavailable");
        recognizer = null;
        adapter = null;
        controller = null;
        captureStarted = false;
      }
    }
    function checkAvailability() {
      return verifyIdentity().then(function (key) {
        const next = typeof key === "string" && key !== "";
        if (next === sttAvailable) return;
        sttAvailable = next;
        updateMicState();
      });
    }
    function setComposerText(text) {
      composer.value = text;
      try { composer.dispatchEvent(new win.Event("input", { bubbles: true })); } catch (e) {}
    }
    function clickSend() { try { send.click(); } catch (e) {} }

    function buildRecognizer() {
      return createRecognizer({
        win, doc, fetchImpl, mediaDevices,
        now: options.now,
        generation: 1,
        sessionToken: makeToken(),
        verifyIdentity,
        callbacks: {
          onInterim: function (chunk) {
            if (!adapter) return;
            const r = adapter.feedInterim(chunk, { generation: adapter.getGeneration(), sessionToken: adapter.getSessionToken() });
            if (r.ok) { try { const preview = doc.querySelector(".voice-interim-preview") || composer; if (preview) preview.textContent = r.preview; } catch (e) {} }
          },
          onFinal: function (payload) {
            if (!adapter) return;
            const opts = {
              generation: adapter.getGeneration(),
              sessionToken: adapter.getSessionToken(),
              // #3404: 사용자가 마이크를 끈 뒤 도착하는 최종 전사도 입력창에 반영한다.
              stopped: !!(payload && payload.stopped === true),
            };
            if (payload && payload.utteranceId != null) opts.utteranceId = String(payload.utteranceId);
            if (payload && typeof payload.text === "string") opts.text = payload.text;
            const result = adapter.commitFinal(opts);
            // commitFinal() already appended to the composer; re-setting it here
            // would replace earlier chunks with the newest one.
            if (result && result.ok) { try { composer.dispatchEvent(new win.Event("input", { bubbles: true })); } catch (e) {} }
          },
          onTurnComplete: function (event) {
            if (mode !== "live" || !controller) return;
            // controller.submit 이 정확히 1회 전송을 수행한다. 여기서 다시 clickSend를
            // 호출하면 같은 발화가 두 번 전송되므로 결과만 소비한다.
            controller.handleFinal({
              accepted: true,
              endOfTurn: true,
              accountKey: identityKey,
              sessionGeneration: controller.getState().sessionGeneration,
              finalId: event && event.finalId != null ? String(event.finalId) : "",
              text: composer.value.trim(),
            });
          },
          onStart: function () {
            // The adapter only accepts finals while it is listening. Without
            // this, every chunk that arrives while the mic stays on is
            // rejected as "not-listening" and live auto-send never fires.
            if (adapter) adapter.start();
            captureStarted = true;
            updateMicState();
          },
          onError: function (code) {
            recognizer = null;
            captureStarted = false;
            updateMicState();
            note.textContent = t(code === "permission-denied" ? "errorPermission" : code === "unsupported-browser" ? "errorUnsupported" : "error");
          },
          onEnd: function () { recognizer = null; captureStarted = false; updateMicState(); },
        },
      });
    }
    function startRecognizer() {
      if (recognizer) { recognizer.stop("user-stopped"); recognizer = null; }
      adapter = createInputAdapter({ generation: 1, sessionToken: makeToken(), input: composer });
      controller = createLiveTurnController({
        accountKey: identityKey,
        getAccountKey: function () { return identityKey; },
        getInFlight: function () { return send.disabled === true; },
        getCanSubmit: function () { return send.disabled !== true && composer.value.trim().length > 0; },
        commitText: function (text) { setComposerText(text); },
        submit: function () {
          const pending = composer.value;
          clickSend();
          // submitComposer() clears the input only when it actually dispatched;
          // a null inputHandler (busy or read-only view) leaves it untouched.
          return composer.value !== pending;
        },
        onPreview: function () {},
        onStateChange: function () { updateMicState(); },
      });
      // 무장된 자동 전송 모드(Mode B)는 발화 단위가 아니라 사용자가 끌 때까지 유지한다.
      controller.setMode(mode);
      captureStarted = false;
      recognizer = buildRecognizer();
      updateMicState();
      syncLiveToggle();
      return recognizer;
    }
    function stopRecognizer(release) {
      captureStarted = false;
      if (recognizer) { recognizer.stop("user-stopped"); recognizer = null; }
      // #3404: 전사 응답은 stop 이후 비동기로 도착한다. 어댑터를 즉시 버리면
      // 최종 전사가 입력창에 반영되지 않으므로, 세션 종료/계정 전환 때만 해제한다.
      if (adapter) {
        adapter.stop("user-stopped");
        if (release === true) adapter = null;
      }
      updateMicState();
    }
    function toggleMic() {
      if (!sttAvailable || identityKey === "") return false;
      if (recognizer) { stopRecognizer(false); return true; }
      return checkAvailability().then(function () {
        if (!sttAvailable || identityKey === "") return false;
        startRecognizer();
        return true;
      });
    }
    function syncLiveToggle() {
      if (!liveToggleEl) return;
      liveToggleEl.setAttribute("aria-pressed", mode === "live" ? "true" : "false");
      liveToggleEl.setAttribute("aria-label", mode === "live" ? t("liveOn") : t("liveOff"));
      liveToggleEl.textContent = mode === "live" ? t("liveOn") : t("liveOff");
    }
    function toggleLive() {
      if (!sttAvailable || identityKey === "") return;
      mode = mode === "basic" ? "live" : "basic";
      if (controller) controller.setMode(mode);
      syncLiveToggle();
      note.textContent = mode === "live" ? t("liveAutoSend") : "";
      if (mode === "basic" && recognizer) stopRecognizer(false);
    }
    function invalidate() {
      stopRecognizer(true);
      controller = null;
      identityKey = "";
      announceIdentity("");
      sttAvailable = false;
      updateMicState();
    }

    listen(win, "padiem:auth-state", function (event) {
      const detail = event && event.detail ? event.detail : {};
      const authenticated = detail.authenticated === true;
      if (!authenticated) { invalidate(); return; }
      verifyIdentity().then(function (key) {
        const next = typeof key === "string" && key !== "";
        if (next === sttAvailable) return;
        sttAvailable = next;
        updateMicState();
      });
    });
    listen(win, "focus", function () { verifyIdentity(); });
    listen(doc, "visibilitychange", function () { if (!doc.hidden) verifyIdentity(); });
    checkAvailability();

    mic.addEventListener("click", function () { Promise.resolve(toggleMic()); });

    liveToggleEl = doc.createElement("button");
    liveToggleEl.id = LIVE_TOGGLE_ID;
    liveToggleEl.type = "button";
    liveToggleEl.className = "voice-live-toggle";
    liveToggleEl.setAttribute("aria-pressed", "false");
    liveToggleEl.setAttribute("aria-label", t("liveOff"));
    liveToggleEl.textContent = t("liveOff");
    liveToggleEl.disabled = true;
    liveToggleEl.addEventListener("click", toggleLive);
    const micParent = mic.parentNode;
    if (micParent && typeof micParent.insertBefore === "function") micParent.insertBefore(liveToggleEl, mic.nextSibling);

    return {
      MIC_ID, COMPOSER_ID, SEND_ID,
      destroy: function () {
        wiringStopped = true;
        stopRecognizer(true);
        controller = null;
        listeners.forEach(function (entry) {
          if (typeof entry[0].removeEventListener === "function") entry[0].removeEventListener(entry[1], entry[2]);
        });
        listeners.length = 0;
        mic.disabled = true;
        if (liveToggleEl && liveToggleEl.parentNode && typeof liveToggleEl.parentNode.removeChild === "function") {
          liveToggleEl.parentNode.removeChild(liveToggleEl);
        }
        liveToggleEl = null;
      },
      getState: function () { return { mode, sttAvailable, identityKey: identityKey || "", recognizer: !!recognizer }; },
    };
  }

  function autoInit(root) {
    const targetWin = root || (typeof globalThis !== "undefined" ? globalThis : null);
    const targetDoc = targetWin ? targetWin.document : null;
    if (!targetWin || !targetDoc) return null;
    const run = function () { return createB66VoiceWiring({ win: targetWin, doc: targetDoc }); };
    if (targetDoc.readyState === "loading") {
      targetDoc.addEventListener("DOMContentLoaded", run, { once: true });
      return null;
    }
    return run();
  }
  if (typeof globalThis !== "undefined" && globalThis.document) { autoInit(globalThis); }
  return { createB66VoiceWiring, autoInit };
});
