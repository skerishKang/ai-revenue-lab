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
    root.PadiemVoiceLiveTranscriptTurn = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : (typeof window !== "undefined" ? window : this), function () {
  "use strict";

  /**
   * apps/padiem-chat/static/voice-live-transcript-turn.js
   *
   * The shared voice turn authority for Chat, Claw, B66 and meeting capture.
   *
   * PROVENANCE — GLOBAL_CLASSROOM_DIRECT_PORT, logic unchanged:
   *   skerishKang/global-classroom main ffa27e6a93605614031fed314ef33571c85b8f18
   *   utils/liveTranscriptTurn.ts (added by the #87 fix commit 8c61e0d9)
   * Translated from TypeScript to plain JavaScript only: types, generics and
   * non-null assertions are erased. Every constant value, comparison and side
   * effect is the original's. Do not "improve" a value here; the numbers below
   * are measurements recorded against the live provider, and the original's
   * tests gate them.
   *
   * Normal Global Classroom voice input and Interview mode both consume the same
   * `gemini-3.5-transcribe-live` session, so the chunk handling, the turn boundary
   * and the activity-detection window must live in one place. Diverging copies of
   * this logic are what produced the Interview-mode "multiple partial English
   * rows" regression (issue #87).
   */

  const LIVE_TRANSCRIBE_MODEL = "gemini-3.5-transcribe-live";

  /**
   * How much silence ends a turn. Gemini's automatic activity detection defaults
   * to 800ms; 650ms cut ordinary 0.7-1.5s thinking pauses into separate
   * utterances, so a long sentence was emitted as several final rows. 1300ms keeps
   * typical thinking pauses inside one utterance at the cost of ~0.5s of extra
   * final-row latency.
   */
  const LIVE_VAD_SILENCE_MS = 1300;

  /**
   * Live sessions have a vendor-documented duration limit (~10 minutes). Rotate
   * before it instead of letting the session end and permanently dropping the
   * microphone to Browser/Groq speech recognition.
   */
  const LIVE_SESSION_ROTATE_MS = 9 * 60 * 1000 + 20 * 1000;

  /**
   * Some Live backends emit cumulative hypotheses while others emit deltas.
   * Accept both without duplicating an already-seen prefix/suffix.
   */
  function mergeLiveTranscriptChunk(previous, incoming) {
    if (!incoming) return previous;
    if (!previous) return incoming;
    if (incoming.startsWith(previous)) return incoming;
    if (previous.endsWith(incoming)) return previous;
    return previous + incoming;
  }

  /**
   * Captures microphone frames while the Live transcription session is being
   * swapped (#87).
   *
   * Rotating a session means `await`ing a fresh ephemeral token and a new
   * WebSocket. The outgoing session is invalidated *before* that await, because an
   * old session's callbacks must never be mistaken for a provider failure — so any
   * frame handed to it during the gap is transcribed and then thrown away, and the
   * incoming session never saw the start of the sentence. Buffering the gap and
   * replaying it into the new session is what keeps a long utterance that straddles
   * the rotation boundary intact.
   *
   * The buffer is bounded on purpose. A stalled connect must degrade into a
   * measurable, reportable loss rather than unbounded memory growth, so overflow is
   * counted and never silent.
   */
  function createAudioHandoffBuffer(maxFrames) {
    let frames = [];
    let capturing = false;
    let dropped = 0;

    return {
      get capturing() { return capturing; },
      get size() { return frames.length; },
      get droppedFrames() { return dropped; },
      start() {
        capturing = true;
      },
      /**
       * Capture one frame. Returns true when it was buffered (so the caller must not
       * also send it), and false when the cap was reached and it was dropped.
       */
      push(frame) {
        if (!capturing) return false;
        if (frames.length >= maxFrames) {
          dropped += 1;
          return false;
        }
        frames.push(frame);
        return true;
      },
      /** Hand every captured frame to the caller in arrival order and stop capturing. */
      release() {
        const pending = frames;
        frames = [];
        capturing = false;
        return pending;
      },
      /** Abandon everything captured (teardown, or a rotation that will not be used). */
      reset() {
        frames = [];
        capturing = false;
      },
    };
  }

  /**
   * One microphone frame is 2048 samples (both the AudioWorklet and the legacy
   * ScriptProcessor path), i.e. 128ms at the 16kHz the Live API expects. 40 frames
   * therefore cover ~5.1s of connect latency, which is far beyond a normal token
   * fetch plus WebSocket handshake while staying a bounded amount of memory.
   */
  const LIVE_AUDIO_HANDOFF_FRAMES = 40;

  /**
   * Finalise the audio a retired Live session still holds (#87).
   *
   * Gemini's activity detection closes a turn only after it has *received* enough
   * silence. A microphone stream that simply stops — a mute, a teardown, or the
   * outgoing half of a rotation — never delivers that silence, so the tail of the
   * sentence stays cached inside the session and dies with the socket. Measured
   * against the live provider on one 28.7s utterance: stopping the stream with no
   * signal transcribed 51/64 ground-truth words and lost the whole final clause,
   * while the identical audio plus `audioStreamEnd` transcribed 62/64 with the
   * final chunk 261ms later.
   *
   * The drain window is deliberately generous against that 261ms observation but
   * bounded: a socket that never answers must not pin the teardown path.
   */
  const LIVE_TAIL_FLUSH_DRAIN_MS = 1200;

  function flushLiveTranscriptTail(session, options) {
    const opts = options || {};
    const onSettled = opts.onSettled;
    const deadlineMs = opts.deadlineMs == null ? LIVE_TAIL_FLUSH_DRAIN_MS : opts.deadlineMs;
    const setTimer = typeof opts.setTimer === "function"
      ? opts.setTimer
      : function (callback, ms) { return setTimeout(callback, ms); };
    const clearTimer = typeof opts.clearTimer === "function"
      ? opts.clearTimer
      : function (id) { return clearTimeout(id); };

    if (!session) {
      return { armed: false, accept: function () { return false; }, cancel: function () {} };
    }

    let settled = false;
    let tail = "";
    let timer = setTimer(function () { settle(); }, deadlineMs);

    /** Close the session and hand over everything received, whether or not it was finalised. */
    function settle() {
      if (settled) return;
      settled = true;
      if (timer !== null) {
        clearTimer(timer);
        timer = null;
      }
      try {
        if (typeof session.close === "function") session.close();
      } catch (e) {
        // The socket is going away either way.
      }
      onSettled(tail.trim() ? tail : null);
    }

    try {
      // The original calls the method whenever it is present: a session object
      // that cannot be signalled throws here and is closed instead of being
      // left open holding audio.
      if (session.sendRealtimeInput) session.sendRealtimeInput({ audioStreamEnd: true });
    } catch (e) {
      settle();
    }

    return {
      get armed() {
        return !settled;
      },
      /**
       * Feed one chunk observed on the draining session. A backend may deliver the tail
       * as several deltas *or* as cumulative hypotheses, so chunks are merged and only a
       * turn boundary settles — closing on the first non-empty chunk would truncate the
       * sentence, which is the very loss this flush exists to prevent. Settling also
       * requires content: a bare boundary that arrives before any text must not close an
       * empty tail.
       *
       * Returns true when the chunk was taken into account, false when it was ignored
       * (already settled, or nothing usable in it).
       */
      accept(chunk) {
        if (settled) return false;
        // The original reads these through optional chaining, so a chunk that is
        // null or undefined is "nothing usable in it" rather than a throw.
        const observed = chunk || {};
        const text = typeof observed.text === "string" ? observed.text : "";
        if (!text.trim()) {
          // A bare boundary is only usable once some text has been captured.
          if (!observed.finished || !tail) return false;
          settle();
          return true;
        }
        tail = mergeLiveTranscriptChunk(tail, text);
        if (observed.finished) settle();
        return true;
      },
      /**
       * Stop waiting for a tail (restart, fallback) and close the session. Anything
       * already captured is still reported: cancelling the wait must not discard words
       * the provider was given, or muting and immediately un-muting would re-open the
       * exact loss this flush exists to close.
       */
      cancel() {
        settle();
      },
    };
  }

  function createTranscriptTurnBuffer() {
    let pending = "";

    return {
      get pending() {
        return pending;
      },
      /**
       * Merge one `inputTranscription` chunk into the open turn. Merging alone never
       * emits a row; only the turn boundary does.
       */
      merge(chunk) {
        if (!chunk) return pending;
        pending = mergeLiveTranscriptChunk(pending, String(chunk));
        return pending;
      },
      /**
       * Turn boundary (`finished` / `turnComplete` / `generationComplete`): returns
       * the single final row for this turn (null when the turn was empty) and opens
       * a fresh turn, so calling it twice cannot duplicate a row.
       */
      finishTurn() {
        const text = pending.trim();
        pending = "";
        return text || null;
      },
      /** Drop the open turn without emitting it (teardown). */
      reset() {
        pending = "";
      },
    };
  }

  /**
   * Groq Whisper fallback chunk boundary (#87).
   *
   * The previous fixed 5500ms stop clipped speech mid-sentence regardless of what
   * was being said. Cut at a speech boundary instead: wait for a real pause once a
   * minimum window has been captured, and keep a hard maximum so the payload
   * stays bounded.
   */
  const GROQ_MIN_CHUNK_MS = 4000;
  const GROQ_SILENCE_CUT_MS = 700;
  const GROQ_MAX_CHUNK_MS = 20000;

  function shouldCutGroqChunk(input) {
    const elapsedMs = input.elapsedMs;
    const silenceMs = input.silenceMs;
    if (elapsedMs >= GROQ_MAX_CHUNK_MS) return true;
    if (elapsedMs < GROQ_MIN_CHUNK_MS) return false;
    return silenceMs >= GROQ_SILENCE_CUT_MS;
  }

  /**
   * Safety net for the turn boundary. Google documents `input_transcription` as
   * the finalized transcript of one speech segment, emitted on a pause; the Live
   * turn boundary (`finished` / `turnComplete`) is what closes a turn. If that
   * boundary never arrives, a stalled turn must still surface instead of being
   * held forever, so a turn whose last chunk is older than this window and that
   * still has pending text is committed as-is.
   */
  const TRANSCRIPT_TURN_STALL_MS = 2500;

  function shouldFlushStalledTurn(input) {
    return input.hasPending && input.sinceLastChunkMs >= TRANSCRIPT_TURN_STALL_MS;
  }

  /**
   * Lightweight RMS probe used by the Groq fallback to cut a chunk at a real
   * speech pause (#87). A MediaRecorder stream carries no voice-activity signal,
   * so this is the only local boundary available. Returns null when the browser
   * cannot provide an AudioContext; the bounded maximum still cuts the chunk.
   */
  function startSpeechSilenceProbe(stream, options) {
    if (typeof window === "undefined") return null;
    const AudioContextCtor = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextCtor) return null;

    const opts = options || {};
    let lastVoiceAt = Date.now();
    let stopped = false;
    let timer = null;

    try {
      const context = new AudioContextCtor();
      const source = context.createMediaStreamSource(stream);
      const analyser = context.createAnalyser();
      analyser.fftSize = 512;
      source.connect(analyser);
      const samples = new Uint8Array(analyser.fftSize);
      const threshold = opts.threshold == null ? 0.02 : opts.threshold;

      timer = window.setInterval(function () {
        if (stopped) return;
        analyser.getByteTimeDomainData(samples);
        let sum = 0;
        for (let index = 0; index < samples.length; index += 1) {
          const centered = (samples[index] - 128) / 128;
          sum += centered * centered;
        }
        if (Math.sqrt(sum / samples.length) > threshold) lastVoiceAt = Date.now();
      }, opts.intervalMs == null ? 150 : opts.intervalMs);

      return {
        silenceMs: function () { return Date.now() - lastVoiceAt; },
        stop: function () {
          if (stopped) return;
          stopped = true;
          if (timer !== null) window.clearInterval(timer);
          try {
            source.disconnect();
          } catch (e) {
            // no-op
          }
          Promise.resolve(context.close()).catch(function () {});
        },
      };
    } catch (e) {
      return null;
    }
  }

  /**
   * Browser SpeechRecognition has no language identity of its own. Prefer the
   * explicit Interview hint, then the source language the Live transcriber or the
   * detector actually observed, and only then the browser locale.
   */
  function resolveRecognitionLanguage(input) {
    const candidate = input.hint || input.observed;
    if (candidate && candidate !== "auto") return candidate;
    return input.navigatorLanguage || "ko-KR";
  }

  return Object.freeze({
    LIVE_TRANSCRIBE_MODEL: LIVE_TRANSCRIBE_MODEL,
    LIVE_VAD_SILENCE_MS: LIVE_VAD_SILENCE_MS,
    LIVE_SESSION_ROTATE_MS: LIVE_SESSION_ROTATE_MS,
    LIVE_AUDIO_HANDOFF_FRAMES: LIVE_AUDIO_HANDOFF_FRAMES,
    LIVE_TAIL_FLUSH_DRAIN_MS: LIVE_TAIL_FLUSH_DRAIN_MS,
    GROQ_MIN_CHUNK_MS: GROQ_MIN_CHUNK_MS,
    GROQ_SILENCE_CUT_MS: GROQ_SILENCE_CUT_MS,
    GROQ_MAX_CHUNK_MS: GROQ_MAX_CHUNK_MS,
    TRANSCRIPT_TURN_STALL_MS: TRANSCRIPT_TURN_STALL_MS,
    mergeLiveTranscriptChunk: mergeLiveTranscriptChunk,
    createAudioHandoffBuffer: createAudioHandoffBuffer,
    flushLiveTranscriptTail: flushLiveTranscriptTail,
    createTranscriptTurnBuffer: createTranscriptTurnBuffer,
    shouldCutGroqChunk: shouldCutGroqChunk,
    shouldFlushStalledTurn: shouldFlushStalledTurn,
    startSpeechSilenceProbe: startSpeechSilenceProbe,
    resolveRecognitionLanguage: resolveRecognitionLanguage,
  });
});
