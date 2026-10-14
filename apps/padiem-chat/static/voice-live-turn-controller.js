// Mode 2 real-time voice turn controller for #4643.
// This module may orchestrate submission decisions, but it must not own the
// transcript engine, network transport, or account permission logic.
(function (global) {
  "use strict";

  function normalizeMode(value) {
    return value === "live" ? "live" : "basic";
  }

  function normalizeText(value) {
    return typeof value === "string" ? value.trim() : "";
  }

  function keyOf(payload, accountKey) {
    const p = payload || {};
    const id = p.finalId || p.utteranceId || p.id || p.chunkId;
    if (id != null && String(id).trim() !== "") {
      return String(accountKey || "") + ":" + String(id);
    }
    return String(accountKey || "") + ":" + normalizeText(p.text || p.finalText || p.transcript || "");
  }

  function create(options) {
    const opts = options || {};
    const commitText = typeof opts.commitText === "function" ? opts.commitText : function () {};
    const submit = typeof opts.submit === "function" ? opts.submit : function () {};
    const getInFlight =
      typeof opts.getInFlight === "function" ? opts.getInFlight : function () {
        return false;
      };
    const getAccountKey =
      typeof opts.getAccountKey === "function" ? opts.getAccountKey : function () {
        return "";
      };
    const onPreview =
      typeof opts.onPreview === "function" ? opts.onPreview : function () {};
    const onStateChange =
      typeof opts.onStateChange === "function" ? opts.onStateChange : function () {};

    let mode = normalizeMode(opts.mode);
    let accountKey = String(opts.accountKey != null ? opts.accountKey : getAccountKey() || "");
    let sessionGeneration = Number.isFinite(opts.sessionGeneration) ? opts.sessionGeneration : 1;    let cancelled = false;
    let invalidated = false;
    let seen = new Set();
    let pending = null;
    let compositionActive = false;

    function report() {
      onStateChange({
        mode: mode,
        accountKey: accountKey,
        cancelled: cancelled,
        invalidated: invalidated,
        pending: pending !== null,
        inFlight: Boolean(getInFlight()),
        seenCount: seen.size,
      });
    }

    function invalidate() {
      seen = new Set();
      pending = null;
      invalidated = true;
      report();
    }

    function setAccountKey(next) {
      const value = String(next == null ? "" : next);
      if (value !== accountKey) {
        accountKey = value;
        seen = new Set();
        pending = null;
        invalidated = false;
        cancelled = false;
      }
      report();
    }

    function reset() {
      cancelled = false;
      invalidated = false;
      pending = null;
      seen = new Set();
      report();
    }

    function cancel() {
      cancelled = true;
      pending = null;
      report();
    }

    function setMode(next) {
      mode = normalizeMode(next);
      pending = null;
      cancelled = false;
      invalidated = false;
      report();
    }

    function handleInterim(payload) {
      const p = payload || {};
      if (mode !== "live" || cancelled || invalidated) {
        return { ok: false, reason: "mode-not-live", submitted: false };
      }
      const eventAccount = p.accountKey == null ? accountKey : String(p.accountKey);
      if (eventAccount !== accountKey) {
        return { ok: false, reason: "account-mismatch", submitted: false };
      }
      const text = normalizeText(p.text || p.transcript || p.interim);
      onPreview(text);
      return { ok: true, reason: "interim-preview", submitted: false };
    }

    function handleFinal(payload) {
      const p = payload || {};
      if (invalidated || cancelled) {
        return { ok: false, reason: "invalidated-or-cancelled", submitted: false };
      }
      if (mode !== "live") {
        return { ok: false, reason: "mode-not-live", submitted: false };
      }
      const eventAccount = p.accountKey == null ? accountKey : String(p.accountKey);
      if (eventAccount !== accountKey) {
        return { ok: false, reason: "account-mismatch", submitted: false };
      }
      const text = normalizeText(p.text || p.transcript || p.final || p.finalText);
      if (!text) {
        return { ok: false, reason: "empty-final", submitted: false };
      }
      const accepted = p.accepted === true || p.approved === true || p.finalAccepted === true;
      const incomingGeneration = Number.isFinite(p.sessionGeneration) ? p.sessionGeneration : null;
      if (!accepted) {
        return { ok: false, reason: "final-not-approved", submitted: false };
      }
      if (incomingGeneration !== null && incomingGeneration !== sessionGeneration) {
        return { ok: false, reason: "stale-session-generation", submitted: false };
      }
      const key = keyOf(p, accountKey);
      if (seen.has(key)) {
        return { ok: false, reason: "duplicate-final", submitted: false };
      }
      if (compositionActive) {
        return { ok: false, reason: "blocked-by-composition", submitted: false };
      }
      if (getInFlight()) {
        return { ok: false, reason: "blocked-by-in-flight", submitted: false };
      }
      seen.add(key);
      try {
        commitText(text);
      } catch (error) {
        return { ok: false, reason: "commit-failed", submitted: false, error: error };
      }
      try {
        submit(text, { finalKey: key, accountKey: accountKey });
      } catch (error) {
        return { ok: false, reason: "submit-failed", submitted: false, error: error };
      }
      return { ok: true, reason: "submitted", submitted: true, finalKey: key };
    }

    function flushPending() {
      if (mode !== "live" || cancelled || invalidated || !pending) {
        return { ok: false, reason: "nothing-pending", submitted: false };
      }
      if (getInFlight()) {
        return { ok: false, reason: "blocked-by-in-flight", submitted: false };
      }
      const next = pending;
      pending = null;
      const result = handleFinal({ text: next.text, finalId: next.key });
      if (!result.submitted && result.reason !== "duplicate-final") {
        pending = next;
      }
      return result;
    }

    const controller = {
      getState: function () {
        return {
          mode: mode,
          accountKey: accountKey,
          sessionGeneration: sessionGeneration,
          cancelled: cancelled,
          invalidated: invalidated,
          seenCount: seen.size,
          inFlight: Boolean(getInFlight()),
        };
      },
      setMode: setMode,
      setCompositionActive: function (value) { compositionActive = value === true; report(); },
      endComposition: function () { compositionActive = false; return flushPending(); },
      setAccountKey: setAccountKey,
      invalidate: invalidate,
      cancel: cancel,
      reset: reset,
      handleInterim: handleInterim,
      handleFinal: handleFinal,
      flushPending: flushPending,
    };

    if (opts.accountKey == null) {
      accountKey = String(getAccountKey() || "");
    }
    report();
    return controller;
  }

  const exported = {
    create: create,
    normalizeMode: normalizeMode,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = exported;
  }
  (typeof globalThis !== "undefined" ? globalThis : typeof window !== "undefined" ? window : this).PadiemVoiceLiveTurnController = exported;
})(typeof globalThis !== "undefined" ? globalThis : typeof window !== "undefined" ? window : this);