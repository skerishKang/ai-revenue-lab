
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
   * PROVENANCE of the transcription algorithm — GLOBAL_CLASSROOM_DIRECT_PORT:
   *   static/voice-live-transcript-turn.js carries utils/liveTranscriptTurn.ts
   *   of skerishKang/global-classroom @ ffa27e6a verbatim, and it is the only
   *   copy in this app. Merge, turn boundary, chunk-cut and session constants
   *   are read from that authority instead of being restated here, because a
   *   second copy of this logic is the defect Global Classroom issue #87 fixed.
   *   - hooks/useInterviewLive.ts -> utterance ids, generation gating,
   *     interim/final split (PADIEM-specific seams kept below).
   * No redesign of merge or turn-buffer semantics.
   */

  const STATES = Object.freeze({
    IDLE: "idle",
    LISTENING: "listening",
    INTERIM: "interim",
    FINAL: "final",
    STOPPED: "stopped",
    ERROR: "error",
  });

  /**
   * The authority is loaded by index.html before this file, and reached through
   * CommonJS in the Node harnesses. It is deliberately not re-implemented here:
   * a second copy of the #87 turn logic is exactly what drifted before.
   */
  const turnAuthority = (function loadTurnAuthority() {
    const host = typeof globalThis !== "undefined" ? globalThis : null;
    if (host && host.PadiemVoiceLiveTranscriptTurn) return host.PadiemVoiceLiveTranscriptTurn;
    if (typeof require === "function") {
      try {
        return require("./voice-live-transcript-turn.js");
      } catch (e) { /* reported by the fail-closed throw below */ }
    }
    return null;
  })();

  if (!turnAuthority) {
    throw new Error("voice_live_transcript_turn_authority_missing");
  }

  /* #87 values come from the authority, never from a copy in this file. */
  const LIVE_TRANSCRIBE_MODEL = turnAuthority.LIVE_TRANSCRIBE_MODEL;
  const LIVE_VAD_SILENCE_MS = turnAuthority.LIVE_VAD_SILENCE_MS;
  const LIVE_SESSION_ROTATE_MS = turnAuthority.LIVE_SESSION_ROTATE_MS;
  const LIVE_AUDIO_HANDOFF_FRAMES = turnAuthority.LIVE_AUDIO_HANDOFF_FRAMES;
  const LIVE_TAIL_FLUSH_DRAIN_MS = turnAuthority.LIVE_TAIL_FLUSH_DRAIN_MS;
  const GROQ_MIN_CHUNK_MS = turnAuthority.GROQ_MIN_CHUNK_MS;
  const GROQ_SILENCE_CUT_MS = turnAuthority.GROQ_SILENCE_CUT_MS;
  const GROQ_MAX_CHUNK_MS = turnAuthority.GROQ_MAX_CHUNK_MS;
  const TRANSCRIPT_TURN_STALL_MS = turnAuthority.TRANSCRIPT_TURN_STALL_MS;

  function norm(value) {
    return value == null ? "" : String(value);
  }

  /**
   * Thin adapter over the authority's `mergeLiveTranscriptChunk`. The original's
   * TypeScript signature guarantees strings; a browser caller can hand this
   * boundary null or undefined, so the coercion lives here rather than growing a
   * fallback the original never had. Merge semantics are the original's.
   */
  function mergeLiveTranscriptChunk(previous, incoming) {
    return norm(
      turnAuthority.mergeLiveTranscriptChunk(norm(previous), norm(incoming)),
    );
  }

  /**
   * The authority's turn buffer, used unchanged: merging chunks never emits a
   * row, only the turn boundary commits one, and a repeated boundary cannot
   * duplicate it.
   */
  const createTranscriptTurnBuffer = turnAuthority.createTranscriptTurnBuffer;

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
      currentUtteranceId = null;
      acceptedCount = 0;
      startedAt = Date.now();
      stopped = false;
      return emitState(STATES.LISTENING) === STATES.LISTENING;
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
      if (destroyed) return { ok: false, reason: "stopped" };
      const stopFlush = opts && opts.stopped === true;
      if (stopped && !stopFlush) return { ok: false, reason: "stopped" };
      if (state === STATES.ERROR) return { ok: false, reason: "error-state" };
      if (stopFlush && stopped && (state === STATES.STOPPED || state === STATES.LISTENING || state === STATES.INTERIM || state === STATES.FINAL)) {
        // Allow the final transcribed chunk to land after a user-initiated stop.
      } else if (state !== STATES.LISTENING && state !== STATES.INTERIM && state !== STATES.FINAL) {
        return { ok: false, reason: "not-listening" };
      }
      if (opts.destroyed === true) return { ok: false, reason: "invalidated" };
      if (opts.generation != null && opts.generation !== generation) {
        return { ok: false, reason: "stale-generation" };
      }
      if (opts.sessionToken != null && String(opts.sessionToken) !== sessionToken) {
        return { ok: false, reason: "stale-session" };
      }
      const utteranceId =
        opts.utteranceId != null ? String(opts.utteranceId) : null;

      // Provider finals without a stable turn id cannot be de-duplicated across
      // turns. Only the buffered, turn-bounded finish path may omit the id.
      if (!utteranceId && opts.text != null) {
        return { ok: false, reason: "missing-utterance-id" };
      }
      // A late repeat must not erase an interim buffer for a newer utterance.
      if (utteranceId && emittedUtterances.has(utteranceId)) {
        return { ok: false, reason: "duplicate-utterance", utteranceId: utteranceId };
      }
      let text = opts.text != null ? String(opts.text) : turnBuffer.finishTurn();
      if (text == null) text = turnBuffer.finishTurn();
      text = norm(text).trim();
      if (!text) {
        turnBuffer.reset();
        return { ok: false, reason: "empty" };
      }
      if (utteranceId) emittedUtterances.add(utteranceId);
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
      if (destroyed) return null;
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
    /** The same authority object, so no consumer needs a third copy. */
    authority: turnAuthority,
    constants: Object.freeze({
      LIVE_TRANSCRIBE_MODEL: LIVE_TRANSCRIBE_MODEL,
      LIVE_VAD_SILENCE_MS: LIVE_VAD_SILENCE_MS,
      LIVE_SESSION_ROTATE_MS: LIVE_SESSION_ROTATE_MS,
      LIVE_AUDIO_HANDOFF_FRAMES: LIVE_AUDIO_HANDOFF_FRAMES,
      LIVE_TAIL_FLUSH_DRAIN_MS: LIVE_TAIL_FLUSH_DRAIN_MS,
      GROQ_MIN_CHUNK_MS: GROQ_MIN_CHUNK_MS,
      GROQ_SILENCE_CUT_MS: GROQ_SILENCE_CUT_MS,
      GROQ_MAX_CHUNK_MS: GROQ_MAX_CHUNK_MS,
      TRANSCRIPT_TURN_STALL_MS: TRANSCRIPT_TURN_STALL_MS,
    }),
  };
});
