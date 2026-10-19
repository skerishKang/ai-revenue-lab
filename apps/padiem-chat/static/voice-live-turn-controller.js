// #4816: Mode 2/3/4 authenticated turn coordinator. Never a network sender.
// The app owner must supply an accepted-final callback and EXISTING form submit.
// Shared by Chat(B62) and Claw(B54): one state machine for every voice mode.
// Mode 1 stays manual (no auto-send); M2/M3 arm auto-send via setMode("live").
(function (root) {
  "use strict";
  // Dedup cache bound. Memory stays bounded; it is never a turn quota.
  const DEDUP_LIMIT = 1024;

  function normalizeMode(v) { return v === "live" ? "live" : "basic"; }
  function textOf(v) { return typeof v === "string" ? v.trim() : ""; }

  function create(opts) {
    opts = opts || {};
    const account = typeof opts.getAccountKey === "function" ? opts.getAccountKey : null;
    const busy = typeof opts.getInFlight === "function" ? opts.getInFlight : null;
    const canSend = typeof opts.getCanSubmit === "function" ? opts.getCanSubmit : null;
    const commit = typeof opts.commitText === "function" ? opts.commitText : null;
    const send = typeof opts.submit === "function" ? opts.submit : null;
    const preview = typeof opts.onPreview === "function" ? opts.onPreview : function () {};
    const notify = typeof opts.onStateChange === "function" ? opts.onStateChange : function () {};
    let key = String(opts.accountKey || "").trim();
    let generation = Number.isSafeInteger(opts.sessionGeneration) && opts.sessionGeneration > 0
      ? opts.sessionGeneration : 1;
    let mode = "basic"; // Constructor cannot enable auto-send.
    let cancelled = false, revoked = false, composing = false;
    let seen = new Set(), outstanding = null;

    function auth() {
      if (!key || !account) return false;
      try { return String(account() || "").trim() === key; }
      catch (_) { return false; }
    }
    function ready() {
      if (!busy || !canSend || !commit || !send) return false;
      try { return busy() === false && canSend() === true; }
      catch (_) { return false; }
    }
    function report() {
      try { notify({mode: mode, accountKey: key, sessionGeneration: generation,
        cancelled: cancelled, invalidated: revoked, composing: composing,
        waitingForAnswer: !!outstanding, seenCount: seen.size}); }
      catch (_) { /* observability never controls transport */ } }
    function blocked(reason) { return {ok: false, reason: reason, submitted: false}; }
    function rotate() { generation += 1; seen = new Set(); }
    function validate(p) {
      if (!auth() || p.accountKey !== key) return "unauthenticated-or-account-mismatch";
      if (!Number.isSafeInteger(p.sessionGeneration) || p.sessionGeneration !== generation)
        return "missing-or-stale-generation";
      return "";
    }
    function setMode(v) {
      const newMode = normalizeMode(v);
      if (newMode !== mode) { mode = newMode; rotate(); }
      cancelled = false; revoked = false; report(); }
    function setAccountKey(value) {
      const next = String(value || "").trim();
      if (next !== key) {
        key = next; rotate(); outstanding = null; cancelled = true; revoked = true;
      }
      report(); }
    // Monotonic generation sync with the composer run that owns the turn.
    // Never resets the dedup cache: the same logical run keeps its ids.
    function syncSessionGeneration(next) {
      if (next == null) return;
      const n = Number(next);
      if (Number.isSafeInteger(n) && n > 0) generation = n;
    }
    function cancel() { rotate(); cancelled = true; report(); }
    function invalidate() { rotate(); cancelled = true; revoked = true; report(); }
    function reset() { rotate(); cancelled = false; revoked = false; report(); }

    function handleInterim(p) {
      p = p || {};
      if (mode !== "live" || cancelled || revoked) return blocked("mode-not-live");
      const error = validate(p);
      if (error) return blocked(error);
      if (p.isInterim !== true) return blocked("not-confirmed-interim");
      const value = textOf(p.text || p.transcript);
      if (!value) return blocked("empty-interim");
      try { preview(value); } catch (_) { return blocked("preview-failed"); }
      return {ok: true, reason: "preview", submitted: false}; }
    function handleFinal(p) {
      p = p || {};
      if (mode !== "live" || cancelled || revoked) return blocked("mode-not-live-or-revoked");
      const error = validate(p);
      if (error) return blocked(error);
      if (p.accepted !== true || p.endOfTurn !== true) return blocked("not-accepted-end-of-turn");
      const id = textOf(p.finalId);
      const value = textOf(p.text || p.finalText);
      if (!id || !value) return blocked("missing-id-or-text");
      if (composing) return blocked("ime-active");
      if (outstanding) return blocked("previous-answer-pending");
      if (!ready()) return blocked("not-ready");
      const finalKey = key + ":" + generation + ":" + id;
      if (seen.has(finalKey)) return blocked("duplicate");
      // A long live session that keeps one generation must not stop sending
      // once the cache fills: evict the oldest id instead of refusing a real
      // final. A final that old cannot arrive again in a live turn.
      if (seen.size >= DEDUP_LIMIT) {
        const oldest = seen.values().next().value;
        if (oldest !== undefined) seen.delete(oldest);
      }
      seen.add(finalKey); // no replay after partial failure
      try {
        if (commit(value) === false) return blocked("composer-rejected");
        if (!auth() || !ready() || revoked || cancelled) return blocked("state-changed");
        outstanding = {finalKey: finalKey, accountKey: key};
        // The adapter MUST reuse composerForm.requestSubmit; no bespoke HTTP call.
        if (send(value, {finalKey: finalKey, accountKey: key, sessionGeneration: generation}) === false)
          return blocked("send-rejected");
      } catch (_) { return blocked("send-or-commit-error"); }
      finally { report(); }
      return {ok: true, reason: "submitted", submitted: true, finalKey: finalKey}; }
    function markAnswerSettled(p) {
      p = p || {};
      if (!outstanding) return blocked("no-outstanding-answer");
      if (!auth() || p.accountKey !== key || p.finalKey !== outstanding.finalKey)
        return blocked("wrong-answer");
      outstanding = null; report();
      return {ok: true, reason: "settled", submitted: false}; }
    const controller = {
      getState: function () { return {mode: mode, accountKey: key,
        sessionGeneration: generation, cancelled: cancelled, invalidated: revoked,
        waitingForAnswer: !!outstanding, seenCount: seen.size}; },
      setMode: setMode, setAccountKey: setAccountKey, reset: reset,
      cancel: cancel, invalidate: invalidate,
      syncSessionGeneration: syncSessionGeneration,
      setCompositionActive: function (v) { composing = v === true; report(); },
      endComposition: function () { composing = false; report(); },
      handleInterim: handleInterim, handleFinal: handleFinal,
      markAnswerSettled: markAnswerSettled
    };
    report();
    return controller; }
  const api = {create: create, normalizeMode: normalizeMode};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  (typeof globalThis !== "undefined" ? globalThis : root).PadiemVoiceLiveTurnController = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
