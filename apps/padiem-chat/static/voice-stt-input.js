
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
   *   GLOBAL_CLASSROOM_DIRECT_PORT. No redesign of merge or turn-buffer semantics.
   *
   * Live draft (#4643 Owner instruction, 2026-10-20)
   * ----------------------------------------------------
   * The Owner asked for the Global Classroom behaviour verbatim: while the user
   * speaks, the recognised text must appear **in the composer input** in real
   * time, and the confirmed sentence must replace that draft in place without
   * touching the text the user typed. The previous chunk-only recognizer never
   * produced an interim at all, so the interim preview line was the whole
   * interim surface and the input stayed untouched until a final arrived.
   *
   * The draft therefore owns exactly the tail it wrote, and nothing else:
   *   - a write replaces only the tail this adapter last wrote, so any user
   *     text before it survives;
   *   - a user edit of that tail makes the adapter append instead of replace,
   *     so a transcription never erases what the user wrote;
   *   - the final replaces the draft with the confirmed sentence.
   *
   * Interim text is still never a final candidate and never a message: only a
   * confirmed final can be proposed or submitted.
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
    // Live draft ownership (#4643 Owner instruction).
    //
    // ``draftPrefix`` is the input content before the provisional draft,
    // ``ownedTail`` is the provisional (unconfirmed) text this adapter wrote
    // and may replace, and ``lastWritten`` is the exact input content this
    // adapter last produced. With all three, a draft can replace itself, the
    // confirmed sentence can take the draft's place, and a user edit is never
    // overwritten.
    let draftPrefix = "";
    let ownedTail = "";
    let lastWritten = null;

    function emitState(next) {
      if (destroyed) return state;
      state = next;
      try { cbState(state); } catch (e) { /* swallow */ }
      return state;
    }

    function readInput() {
      if (!input) return "";
      if (typeof input.getValue === "function") return norm(input.getValue());
      if (typeof input.value !== "undefined") return norm(input.value);
      return "";
    }

    function setInput(value) {
      if (!input) return;
      if (typeof input.setValue === "function") input.setValue(value);
      else if (typeof input.value !== "undefined") input.value = value;
    }

    /** Join a prefix and a new segment without gluing words together. */
    function joinText(prefix, suffix) {
      const head = norm(prefix);
      const tail = norm(suffix);
      if (!head) return tail;
      if (!tail) return head;
      if (/\s$/.test(head)) return head + tail;
      return head + " " + tail;
    }

    /**
     * Write the live draft.
     *
     * The draft replaces the provisional text this adapter owns. When the user
     * changed the input since the last write, the draft stops touching the
     * input entirely: a transcription may add text, never remove the user's.
     */
    function writeDraft(next) {
      const text = norm(next);
      if (!text || !input) return null;
      const current = readInput();

      if (ownedTail) {
        if (current !== joinText(draftPrefix, ownedTail)) {
          // The user changed the text this adapter owns: never overwrite it.
          return null;
        }
        const value = joinText(draftPrefix, text);
        setInput(value);
        ownedTail = text;
        lastWritten = value;
        return value;
      }

      if (lastWritten !== null && current !== lastWritten) {
        if (current !== "") {
          // The user edited the input: the live draft yields to them.
          return null;
        }
        // The input was cleared (for example after a send): start a new base.
        lastWritten = null;
      }

      const value = joinText(current, text);
      setInput(value);
      draftPrefix = current;
      ownedTail = text;
      lastWritten = value;
      return value;
    }

    /**
     * Commit the confirmed sentence.
     *
     * The confirmed text takes the place of the provisional draft. When the
     * user changed the input in the meantime, the confirmed text is appended
     * instead, so the user's edit is never erased.
     */
    function commitDraft(next) {
      const text = norm(next);
      if (!text || !input) return null;
      const current = readInput();
      let value;
      if (ownedTail && current === joinText(draftPrefix, ownedTail)) {
        value = joinText(draftPrefix, text);
      } else {
        value = joinText(current, text);
      }
      setInput(value);
      draftPrefix = value;
      ownedTail = "";
      lastWritten = value;
      return value;
    }

    /**
     * Drop the provisional draft of an abandoned session.
     *
     * A session that is invalidated (sign-out, account switch, Chat/Claw
     * switch) or that failed leaves no half-transcribed text behind. A user
     * stop keeps the text: the microphone was switched off, not abandoned.
     */
    function dropDraft() {
      if (!input) return null;
      const current = readInput();
      const tail = ownedTail;
      ownedTail = "";
      if (!tail) return null;
      if (current !== joinText(draftPrefix, tail)) return null;
      setInput(draftPrefix);
      lastWritten = draftPrefix;
      return draftPrefix;
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
      draftPrefix = "";
      ownedTail = "";
      lastWritten = null;
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
      // #4643 Owner instruction: the live partial belongs in the composer
      // input, not only in a preview line.
      writeDraft(preview);
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
      // The confirmed sentence takes the place of the live draft.
      try { commitDraft(text); } catch (e) { /* swallow */ }
      try { cbFinal(text, utteranceId); } catch (e) { /* swallow */ }
      turnBuffer.reset();
      return { ok: true, text: text, utteranceId: utteranceId, acceptedCount: acceptedCount };
    }

    function stop(reason) {
      if (destroyed) return state;
      stopped = true;
      turnBuffer.reset();
      // The microphone was switched off, not abandoned: the text spoken so far
      // stays in the input for review.
      emitState(STATES.STOPPED);
      if (reason) { try { cbError(String(reason)); } catch (e) {} }
      return state;
    }

    function error(code) {
      if (destroyed) return state;
      turnBuffer.reset();
      try { dropDraft(); } catch (e) { /* swallow */ }
      emitState(STATES.ERROR);
      try { cbError(String(code || "voice_stt_error")); } catch (e) {}
      return state;
    }

    function invalidate(reason) {
      turnBuffer.reset();
      try { dropDraft(); } catch (e) { /* swallow */ }
      emitState(STATES.STOPPED);
      destroyed = true;
      try { cbError(String(reason || "invalidated")); } catch (e) {}
      return state;
    }

    function appendToInput(text, mode, flush) {
      if (destroyed || (stopped && !flush)) return null;
      text = norm(text);
      if (!text) return null;
      const current = readInput();
      const modeN = mode || "append";
      const next = modeN === "replace" ? text : joinText(current, text);
      setInput(next);
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
