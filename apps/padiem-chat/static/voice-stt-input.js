
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
    root.PadiemVoiceSttInput = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : (typeof window !== "undefined" ? window : this), function () {
  "use strict";

  /**
   * apps/padiem-chat/static/voice-stt-input.js
   *
   * Chat / Claw *thin* voice-input adapter. There is no STT engine here: the
   * recognizer life-cycle, the Gemini / Groq sessions and the microphone
   * plumbing live in Global Classroom and in the Cloudflare voice Worker (OFF).
   * This module only turns a verified transcription event into one input-candidate
   * and lets the user approve and send it.
   *
   * Source of the transcription algorithm (port, logic unchanged):
   *   skerishKang/global-classroom main
   *   - utils/liveTranscriptTurn.ts  -> mergeLiveTranscriptChunk, createTranscriptTurnBuffer
   *   - hooks/useInterviewLive.ts     -> utterance ids, generation gating, interim/final split
   * GLOBAL_CLASSROOM_DIRECT_PORT. No redesign of merge or turn-buffer semantics.
   */

  const STATES = Object.freeze({
    IDLE: "idle",
    LISTENING: "listening",
    INTERIM: "interim",
    FINAL: "final",
    STOPPED: "stopped",
    ERROR: "error",
  });

  /* #87 constants, verbatim from global-classroom/utils/liveTranscriptTurn.ts */
  const LIVE_VAD_SILENCE_MS = 1300;
  const LIVE_SESSION_ROTATE_MS = 9 * 60 * 1000 + 20 * 1000;
  const GROQ_MIN_CHUNK_MS = 4000;
  const GROQ_SILENCE_CUT_MS = 700;
  const GROQ_MAX_CHUNK_MS = 20000;
  const TRANSCRIPT_TURN_STALL_MS = 2500;

  function norm(value) {
    return value == null ? "" : String(value);
  }

  /**
   * Port of global-classroom `mergeLiveTranscriptChunk`. Cumulative vs. delta
   * hypotheses are both accepted without duplicating an already-seen
   * prefix/suffix.
   */
  function mergeLiveTranscriptChunk(previous, incoming) {
    const p = norm(previous);
    const inc = norm(incoming);
    if (!inc) return p;
    if (!p) return inc;
    if (inc.startsWith(p)) return inc;
    if (p.endsWith(inc)) return p;
    return p + inc;
  }

  /**
   * Port of global-classroom `createTranscriptTurnBuffer`. One turn accrues
   * chunks; only `finishTurn()` commits a single final row. Calling it twice
   * cannot duplicate a row because `pending` is cleared on commit.
   */
  function createTranscriptTurnBuffer() {
    let pending = "";
    return {
      get pending() { return pending; },
      merge(chunk) {
        if (!chunk) return pending;
        pending = mergeLiveTranscriptChunk(pending, String(chunk));
        return pending;
      },
      finishTurn() {
        const text = pending.trim();
        pending = "";
        return text || null;
      },
      reset() { pending = ""; },
    };
  }

  function normalizeText(text) {
    return norm(text).trim().toLowerCase().replace(/\s+/g, " ");
  }

  function makeToken() {
    return Date.now().toString(36) + "_" + Math.random().toString(36).slice(2, 10);
  }

  /**
   * Create an adapter bound to one recognizer run.
   *
   * Options:
   *   generation      number   recognizer run identity (from caller)
   *   sessionToken    string   session/account identity (from caller)
   *   onState(state)  fn
   *   onInterim(text) fn  -> UI preview only, never a message
   *   onFinalCandidate(text, utteranceId) fn -> one proposal per utterance id
   *   onError(code)   fn
   *   input           { getValue(), setValue(text) } | DOM element with .value
   *
   * The adapter never performs network I/O, never touches STT, and never calls
   * Send. Final candidates are proposed; the user decides.
   */
  function createVoiceInputAdapter(options) {
    options = options || {};
    const generation = options.generation == null ? 1 : options.generation;
    const sessionToken =
      options.sessionToken == null ? makeToken() : String(options.sessionToken);

    const cbState = typeof options.onState === "function" ? options.onState : function () {};
    const cbInterim =
      typeof options.onInterim === "function" ? options.onInterim : function () {};
    const cbFinal =
      typeof options.onFinalCandidate === "function" ? options.onFinalCandidate : function () {};
    const cbError = typeof options.onError === "function" ? options.onError : function () {};

    let input = options.input || null;
    if (input && typeof input.value === "string" && typeof input.setValue !== "function") {
      const el = input;
      input = {
        getValue: function () { return el.value; },
        setValue: function (v) { el.value = v; },
      };
    }

    const turnBuffer = createTranscriptTurnBuffer();
    const emittedUtterances = new Set();
    const emittedTextNoId = new Set();
    let state = STATES.IDLE;
    let currentUtteranceId = null;
    let startedAt = null;
    let stopped = false;
    let destroyed = false;
    let acceptedCount = 0;

    function emitState(next) {
      if (destroyed) return state;
      state = next;
      try { cbState(state); } catch (e) { /* swallow */ }
      return state;
    }

    function isStale(ctx) {
      ctx = ctx || {};
      if (ctx.generation != null && ctx.generation !== generation) return true;
      if (ctx.sessionToken != null && String(ctx.sessionToken) !== sessionToken) return true;
      if (ctx.destroyed === true) return true;
      return false;
    }

    function start() {
      if (destroyed || stopped) return false;
      if (state !== STATES.IDLE) return false; // refuse repeated active start
      turnBuffer.reset();
      emittedUtterances.clear();
      emittedTextNoId.clear();
      currentUtteranceId = null;
      acceptedCount = 0;
      startedAt = Date.now();
      stopped = false;
      return emitState(STATES.LISTENING) === STATES.LISTENING;
    }

    function canReceive(ctx) {
      if (destroyed || stopped) return false;
      if (state !== STATES.LISTENING && state !== STATES.INTERIM && state !== STATES.FINAL) return false;
      if (isStale(ctx)) return false;
      return true;
    }
    function feedInterim(text, ctx) {
      ctx = ctx || {};
      if (destroyed || stopped) return { ok: false, reason: "stopped" };
      if (state === STATES.ERROR) return { ok: false, reason: "error-state" };
      if (state !== STATES.LISTENING && state !== STATES.INTERIM && state !== STATES.FINAL) {
        return { ok: false, reason: "not-listening" };
      }
      if (ctx.generation != null && ctx.generation !== generation) {
        return { ok: false, reason: "stale-generation" };
      }
      if (ctx.sessionToken != null && String(ctx.sessionToken) !== sessionToken) {
        return { ok: false, reason: "stale-session" };
      }
      if (ctx.destroyed === true) return { ok: false, reason: "invalidated" };
      const t = norm(text);
      if (!t) return { ok: false, reason: "empty" };
      turnBuffer.merge(t);
      const preview = turnBuffer.pending;
      emitState(STATES.INTERIM);
      try { cbInterim(preview, ctx); } catch (e) { /* swallow */ }
      return { ok: true, preview: preview };
    }

    function commitFinal(opts) {
      opts = opts || {};
      if (destroyed || stopped) return { ok: false, reason: "stopped" };
      if (opts.generation != null && opts.generation !== generation) {
        return { ok: false, reason: "stale-generation" };
      }
      if (opts.sessionToken != null && String(opts.sessionToken) !== sessionToken) {
        return { ok: false, reason: "stale-session" };
      }
      const utteranceId =
        opts.utteranceId != null ? String(opts.utteranceId) : null;

      let text = opts.text != null ? String(opts.text) : turnBuffer.finishTurn();
      if (text == null) text = turnBuffer.finishTurn();
      text = norm(text).trim();
      if (!text) {
        turnBuffer.reset();
        return { ok: false, reason: "empty" };
      }

      // state gate: only active run can accept finals
      if (state !== STATES.LISTENING && state !== STATES.INTERIM && state !== STATES.FINAL) {
        turnBuffer.reset();
        return { ok: false, reason: "not-listening" };
      }
      // utterance-id de-dup: only same id is duplicate.
      if (utteranceId && emittedUtterances.has(utteranceId)) {
        turnBuffer.reset();
        return { ok: false, reason: "duplicate-utterance", utteranceId: utteranceId };
      }
      const fingerprint = normalizeText(text);
      // missing-id case: conservative text dedup only then
      if (!utteranceId && emittedTextNoId.has(fingerprint)) {
        turnBuffer.reset();
        return { ok: false, reason: "duplicate-text-no-id", utteranceId: utteranceId };
      }

      if (utteranceId) emittedUtterances.add(utteranceId);
      if (!utteranceId) emittedTextNoId.add(fingerprint);
      currentUtteranceId = utteranceId;
      acceptedCount += 1;
      emitState(STATES.FINAL);
      try { appendToInput(text); } catch (e) { /* swallow */ }
      try { cbFinal(text, utteranceId); } catch (e) { /* swallow */ }
      turnBuffer.reset();
      return { ok: true, text: text, utteranceId: utteranceId, acceptedCount: acceptedCount };
    }

    function stop(reason) {
      if (destroyed) return state;
      stopped = true;
      turnBuffer.reset();
      emitState(STATES.STOPPED);
      if (reason) { try { cbError(String(reason)); } catch (e) {} }
      return state;
    }

    function error(code) {
      if (destroyed) return state;
      turnBuffer.reset();
      emitState(STATES.ERROR);
      try { cbError(String(code || "voice_stt_error")); } catch (e) {}
      return state;
    }

    function invalidate(reason) {
      turnBuffer.reset();
      emitState(STATES.STOPPED);
      destroyed = true;
      try { cbError(String(reason || "invalidated")); } catch (e) {}
      return state;
    }

    function appendToInput(text, mode) {
      if (destroyed || stopped || state === STATES.ERROR) return null;
      text = norm(text);
      if (!text) return null;
      let current = "";
      if (input && typeof input.getValue === "function") current = norm(input.getValue());
      else if (input && typeof input.value !== "undefined") current = norm(input.value);
      let next = current;
      const modeN = mode || "append";
      if (modeN === "replace") {
        next = text;
      } else {
        if (current && !/\s$/.test(current)) next = current + " ";
        next = next + text;
      }
      if (input && typeof input.setValue === "function") input.setValue(next);
      else if (input) input.value = next;
      return next;
    }

    function getState() { return state; }
    function getGeneration() { return generation; }
    function getSessionToken() { return sessionToken; }
    function getAcceptedCount() { return acceptedCount; }
    function getCurrentUtteranceId() { return currentUtteranceId; }

    return {
      STATES: STATES,
      state: STATES.IDLE,
      generation: generation,
      sessionToken: sessionToken,
      start: start,
      feedInterim: feedInterim,
      commitFinal: commitFinal,
      stop: stop,
      error: error,
      invalidate: invalidate,
      appendToInput: appendToInput,
      isStale: isStale,
      getState: getState,
      getGeneration: getGeneration,
      getSessionToken: getSessionToken,
      getAcceptedCount: getAcceptedCount,
      getCurrentUtteranceId: getCurrentUtteranceId,
    };
  }

  return {
    STATES: STATES,
    mergeLiveTranscriptChunk: mergeLiveTranscriptChunk,
    createTranscriptTurnBuffer: createTranscriptTurnBuffer,
    createVoiceInputAdapter: createVoiceInputAdapter,
    constants: Object.freeze({
      LIVE_VAD_SILENCE_MS: LIVE_VAD_SILENCE_MS,
      LIVE_SESSION_ROTATE_MS: LIVE_SESSION_ROTATE_MS,
      GROQ_MIN_CHUNK_MS: GROQ_MIN_CHUNK_MS,
      GROQ_SILENCE_CUT_MS: GROQ_SILENCE_CUT_MS,
      GROQ_MAX_CHUNK_MS: GROQ_MAX_CHUNK_MS,
      TRANSCRIPT_TURN_STALL_MS: TRANSCRIPT_TURN_STALL_MS,
    }),
  };
});

