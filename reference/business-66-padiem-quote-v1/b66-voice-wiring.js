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
 * Mode 1(기본, 수동 전송): 마이크 시작 → 전사 → easyComposer 입력창에 기록
 *      (편집 가능) → 사용자가 easySend 버튼으로 전송
 * Mode 2(자동 전송): 최종 발화 확정 후 정확히 1회 자동 전송(중복·재전송 방지)
 *
 * UI 계약(#3404 본문 · B66 UI/VOICE 핸드오프 §66):
 *   - 마이크 옆이 아니라 컴포저 안에 Mode 1/2 세그먼트를 항상 노출한다.
 *   - 마이크는 unavailable/idle/starting/listening/transcribing 상태를
 *     data-voice-state로 표시하고, 상태줄이 같은 내용을 문장으로 안내한다.
 *   - easyComposerNote는 easy-mode가 소유하므로 음성 상태로 덮어쓰지 않는다.
 *     (데스크톱 B66에서 note는 display:none이라 오류가 보이지 않는다.)
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
  const MODE_GROUP_ID = "easyVoiceMode";
  const MODE_INPUT_ID = "easyVoiceModeInput";
  const MODE_AUTO_ID = "easyVoiceModeAuto";
  const STATUS_ID = "easyVoiceStatus";
  const COMPOSER_ID = "easyComposer";
  const SEND_ID = "easySend";

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
    modeGroup: "음성 입력 방식",
    modeInput: "입력창",
    modeAuto: "자동 대화",
    modeInputLabel: "모드 1: 전사문을 입력창에 적기",
    modeAutoLabel: "모드 2: 전사문을 대화로 바로 보내기",
    modeInputHint: "말하면 입력창에 적힙니다. 확인 후 보내세요.",
    modeAutoHint: "말하면 대화로 바로 전송합니다.",
    listeningBasic: "듣는 중… 말을 마치면 입력창에 적습니다.",
    listeningAuto: "듣는 중… 말을 마치면 바로 전송합니다.",
    transcribing: "전사 중…",
    finalBasic: "입력창에 넣었습니다. 확인 후 보내세요.",
    finalSent: "대화로 전송했습니다.",
    finalHeld: "전송하지 못했습니다. 입력창을 확인하세요.",
    stopped: "음성 입력이 중지되었습니다.",
    error: "음성 입력이 실패했습니다. 다시 시도하거나 직접 입력해 주세요.",
    errorPermission: "마이크 권한이 거부되었습니다. 브라우저 설정을 확인하거나 직접 입력해 주세요.",
    errorUnsupported: "이 브라우저는 음성 입력을 지원하지 않습니다. 직접 입력해 주세요.",
    errorUnavailable: "음성 입력 서비스를 사용할 수 없습니다. 직접 입력해 주세요.",
  };
  const EN = {
    mic: "Voice input",
    micStart: "Start voice input",
    micStop: "Stop voice input",
    modeGroup: "Voice input mode",
    modeInput: "Input box",
    modeAuto: "Auto chat",
    modeInputLabel: "Mode 1: put the transcript in the input box",
    modeAutoLabel: "Mode 2: send the transcript to the conversation",
    modeInputHint: "Speak and the transcript goes into the input box. Review, then send.",
    modeAutoHint: "Speak and the transcript is sent to the conversation.",
    listeningBasic: "Listening… the transcript will go into the input box.",
    listeningAuto: "Listening… the transcript will be sent right away.",
    transcribing: "Transcribing…",
    finalBasic: "Added to the input box. Review, then send.",
    finalSent: "Sent to the conversation.",
    finalHeld: "Not sent. Check the input box.",
    stopped: "Voice input stopped.",
    error: "Voice input failed. Try again or type instead.",
    errorPermission: "Microphone permission was denied. Check browser settings or type instead.",
    errorUnsupported: "This browser does not support voice input. Please type instead.",
    errorUnavailable: "Voice input service is unavailable. Please type instead.",
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
    function emitTranscribing(active) { try { if (typeof callbacks.onTranscribeState === "function") callbacks.onTranscribeState(active === true); } catch (e) {} }
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
      emitTranscribing(true);
      sendChunk(blob, utteranceId).then(function (text) {
        sending = false;
        emitTranscribing(false);
        if (cancelled) return;
        if (finalFlushPending) { finalFlushPending = false; flushChunk(true, true); }
        if (!text) return;
        try { if (typeof callbacks.onFinal === "function") callbacks.onFinal({ text, utteranceId, stopped: fromStop === true || halting }); } catch (e) {}
        if (!cancelled && typeof callbacks.onTurnComplete === "function") { try { callbacks.onTurnComplete({ accepted: true, endOfTurn: true, finalId: utteranceId }); } catch (e) {} }
      }, function () {
        sending = false;
        emitTranscribing(false);
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
      if (cancelled) return Promise.reject(new Error("voice-cancelled"));
      inflightController = typeof win.AbortController === "function" ? new win.AbortController() : null;
      // #4379: the recorded Blob is the request body. A FileReader pass to
      // base64 inflated every chunk by a third and held a second full copy in
      // memory; the Chat route already reads this raw-body contract (#5315),
      // so the bytes travel unchanged with their container and turn id.
      return Promise.resolve(fetchImpl(TRANSCRIBE_PATH, {
        method: "POST", credentials: "same-origin",
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
    let modeGroupEl = null, modeInputEl = null, modeAutoEl = null, statusEl = null, voiceBarEl = null;
    let transcribing = false;
    let lastStatus = "";
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
    function voiceState() {
      if (!sttAvailable || identityKey === "") return "unavailable";
      if (transcribing) return "transcribing";
      if (recognizer && captureStarted) return "listening";
      if (recognizer) return "starting";
      return "idle";
    }
    function statusText(state) {
      if (state === "unavailable") return t("errorUnavailable");
      if (state === "transcribing") return t("transcribing");
      if (state === "listening" || state === "starting") return mode === "live" ? t("listeningAuto") : t("listeningBasic");
      if (lastStatus) return lastStatus;
      return mode === "live" ? t("modeAutoHint") : t("modeInputHint");
    }
    function syncModeUi(ready) {
      if (voiceBarEl) voiceBarEl.setAttribute("data-voice-mode", mode);
      if (modeGroupEl) modeGroupEl.setAttribute("aria-disabled", String(!ready));
      const pairs = [[modeInputEl, "basic"], [modeAutoEl, "live"]];
      for (let i = 0; i < pairs.length; i += 1) {
        const el = pairs[i][0];
        if (!el) continue;
        el.disabled = !ready;
        el.setAttribute("aria-pressed", String(mode === pairs[i][1]));
      }
    }
    function updateMicState() {
      const ready = sttAvailable && identityKey !== "";
      const state = voiceState();
      mic.disabled = !ready;
      mic.setAttribute("aria-disabled", String(!ready));
      // 마이크 상태는 "요청됨"이 아니라 실제 캡처/전사 진행 시점에 맞춘다.
      const active = state === "listening" || state === "starting" || state === "transcribing";
      const label = ready ? (active ? t("micStop") : t("micStart")) : t("errorUnavailable");
      mic.setAttribute("aria-label", label);
      mic.setAttribute("title", label);
      mic.setAttribute("data-voice-state", state);
      mic.setAttribute("aria-pressed", String(active));
      composer.disabled = !ready;
      send.disabled = !ready;
      syncModeUi(ready);
      if (statusEl) statusEl.textContent = statusText(state);
      if (!ready) {
        recognizer = null;
        adapter = null;
        controller = null;
        captureStarted = false;
        transcribing = false;
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
            if (result && result.ok) {
              if (mode !== "live") lastStatus = t("finalBasic");
              try { composer.dispatchEvent(new win.Event("input", { bubbles: true })); } catch (e) {}
              updateMicState();
            }
          },
          onTranscribeState: function (active) {
            transcribing = active === true;
            updateMicState();
          },
          onTurnComplete: function (event) {
            if (mode !== "live" || !controller) return;
            // controller.submit 이 정확히 1회 전송을 수행한다. 여기서 다시 clickSend를
            // 호출하면 같은 발화가 두 번 전송되므로 결과만 소비한다.
            const result = controller.handleFinal({
              accepted: true,
              endOfTurn: true,
              accountKey: identityKey,
              sessionGeneration: controller.getState().sessionGeneration,
              finalId: event && event.finalId != null ? String(event.finalId) : "",
              text: composer.value.trim(),
            });
            lastStatus = result && result.submitted ? t("finalSent") : t("finalHeld");
            updateMicState();
          },
          onStart: function () {
            // The adapter only accepts finals while it is listening. Without
            // this, every chunk that arrives while the mic stays on is
            // rejected as "not-listening" and live auto-send never fires.
            if (adapter) adapter.start();
            captureStarted = true;
            transcribing = false;
            lastStatus = "";
            updateMicState();
          },
          onError: function (code) {
            recognizer = null;
            captureStarted = false;
            transcribing = false;
            lastStatus = t(code === "permission-denied" ? "errorPermission" : code === "unsupported-browser" ? "errorUnsupported" : "error");
            updateMicState();
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
      // 무장된 자동 전송 모드(Mode 2)는 발화 단위가 아니라 사용자가 바꿀 때까지 유지한다.
      controller.setMode(mode);
      captureStarted = false;
      recognizer = buildRecognizer();
      updateMicState();
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
      if (release !== true) lastStatus = t("stopped");
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
    function setMode(next) {
      if (!sttAvailable || identityKey === "") return;
      const normalized = next === "live" ? "live" : "basic";
      if (normalized === mode) return;
      mode = normalized;
      lastStatus = "";
      if (controller) controller.setMode(mode);
      // 모드 전환은 녹음을 끊지 않는다. 이후 확정되는 발화부터 새 모드가 적용된다.
      updateMicState();
    }
    function makeModeButton(id, label, ariaLabel, value) {
      const el = doc.createElement("button");
      el.id = id;
      el.type = "button";
      el.className = "b66-voice-mode-button";
      el.setAttribute("aria-label", ariaLabel);
      el.setAttribute("aria-pressed", "false");
      el.textContent = label;
      el.disabled = true;
      el.addEventListener("click", function () { setMode(value); });
      return el;
    }
    function mountVoiceBar() {
      modeGroupEl = doc.createElement("div");
      modeGroupEl.id = MODE_GROUP_ID;
      modeGroupEl.className = "b66-voice-mode";
      modeGroupEl.setAttribute("role", "group");
      modeGroupEl.setAttribute("aria-label", t("modeGroup"));
      modeInputEl = makeModeButton(MODE_INPUT_ID, t("modeInput"), t("modeInputLabel"), "basic");
      modeAutoEl = makeModeButton(MODE_AUTO_ID, t("modeAuto"), t("modeAutoLabel"), "live");
      modeGroupEl.insertBefore(modeInputEl, null);
      modeGroupEl.insertBefore(modeAutoEl, null);
      statusEl = doc.createElement("span");
      statusEl.id = STATUS_ID;
      statusEl.className = "b66-voice-status";
      statusEl.setAttribute("role", "status");
      statusEl.setAttribute("aria-live", "polite");
      voiceBarEl = doc.createElement("div");
      voiceBarEl.className = "b66-voice-bar";
      voiceBarEl.insertBefore(modeGroupEl, null);
      voiceBarEl.insertBefore(statusEl, null);
      // 컴포저 카드 안, 입력창 위에 둔다. easy-mode의 note(데스크톱 숨김)와 분리한다.
      // textarea의 자식 노드는 브라우저가 렌더하지 않으므로 상위 컨테이너에 삽입한다.
      const host = composer.parentElement || composer.parentNode || null;
      if (host && typeof host.insertBefore === "function") host.insertBefore(voiceBarEl, composer);
      else composer.insertBefore(voiceBarEl, null);
    }
    function invalidate() {
      stopRecognizer(true);
      controller = null;
      identityKey = "";
      announceIdentity("");
      sttAvailable = false;
      updateMicState();
    }

    mountVoiceBar();
    updateMicState();

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

    return {
      MIC_ID, COMPOSER_ID, SEND_ID, MODE_GROUP_ID, MODE_INPUT_ID, MODE_AUTO_ID, STATUS_ID,
      destroy: function () {
        wiringStopped = true;
        stopRecognizer(true);
        controller = null;
        listeners.forEach(function (entry) {
          if (typeof entry[0].removeEventListener === "function") entry[0].removeEventListener(entry[1], entry[2]);
        });
        listeners.length = 0;
        mic.disabled = true;
        if (voiceBarEl && voiceBarEl.parentNode && typeof voiceBarEl.parentNode.removeChild === "function") {
          voiceBarEl.parentNode.removeChild(voiceBarEl);
        }
        voiceBarEl = null; modeGroupEl = null; modeInputEl = null; modeAutoEl = null; statusEl = null;
      },
      getState: function () {
        return { mode, sttAvailable, identityKey: identityKey || "", recognizer: !!recognizer, state: voiceState(), transcribing };
      },
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
