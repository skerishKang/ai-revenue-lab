// #3094 — guarded Web adapter for the "Connect this computer" handoff (Web/B62).
//
// WHAT THIS FILE IS
//   The single Web-side component allowed to (a) read the real server projection
//   for the #3084 panel and (b) act on that panel's PROCEED event by asking the
//   browser to open the opaque handoff link. It adapts two already-owned
//   authorities together and owns neither of them.
//
// NON-AUTHORITY CONTRACT (must stay true)
//   SOURCE_AUTHORITY=NO        It reads GET /api/claw/local-access and nothing
//                              else. It never derives, repairs or re-derives
//                              device state; an unreadable response is projected
//                              as "nothing known", which #3084 renders as not
//                              usable and hidden.
//   PAIRING_AUTHORITY=NO       It never mints, signs, parses, decodes, extends
//                              or stores a pairing token or device session. The
//                              handoff value stays opaque: a length bound plus a
//                              scheme *prefix test* only, never a parse.
//   DEVICE_SESSION_AUTHORITY=NO  No session store, no refresh, no revocation.
//   TRANSPORT_AUTHORITY=NO     One same-origin GET per refresh. No WebSocket, no
//                              EventSource, no timer-based polling.
//   EXECUTION_AUTHORITY=NO     No task admission, no approval decision, no local
//                              process invocation, no command material.
//   INSTALL_REGISTRATION_AUTHORITY=NO  Registering the OS protocol handler is
//                              #3092 plus Desktop. This file only asks the
//                              browser to open a link and reports the attempt;
//                              it never claims the open succeeded.
//
// FAILURE POSTURE
//   Every guard fails closed and reports a bounded reason code through the
//   `padiem:claw-local-adapter-result` event. The handoff value itself never
//   enters that event, a log, an attribute or storage: an activation reason is
//   support-visible, the value is a bearer credential.
//
// Correlated tickets: #3084 (panel/projection owner), #3080 (pairing/broker
// authority), #3092 (Windows scheme registration), #3093 (task-side trigger).
(() => {
  "use strict";

  const ADAPTER_CONTRACT_VERSION = "b62-claw-local-adapter/1";
  const HANDOFF_CONTRACT_VERSION = "b62-claw-local-handoff/1";
  const LOCAL_ACCESS_ENDPOINT = "/api/claw/local-access";

  // Only these URI schemes may be handed to the browser as a local-app handoff.
  // Anything else (http(s), javascript, blob, data, file) is refused: a chat
  // panel must never navigate the page or run script through a projection field.
  const ALLOWED_HANDOFF_SCHEMES = Object.freeze(["padiem:"]);
  const MAX_HANDOFF_LENGTH = 512;

  const GUARD_REASON_CODES = Object.freeze({
    OK: "ok",
    HANDOFF_ABSENT: "handoff_absent",
    HANDOFF_OVER_LENGTH: "handoff_over_length",
    HANDOFF_MALFORMED: "handoff_malformed",
    HANDOFF_MISMATCH: "handoff_mismatch",
    UNSUPPORTED_SCHEME: "unsupported_handoff_scheme",
    NOT_PROCEEDABLE: "not_proceedable",
    STALE_PROJECTION: "stale_projection",
    IDENTITY_MISMATCH: "identity_mismatch",
    DESKTOP_NOT_INSTALLED: "desktop_not_installed",
    NOT_USER_ACTIVATED: "not_user_activated",
    ALREADY_ACTIVATED: "already_activated",
    OPEN_FAILED: "handoff_open_failed",
    SUPERSEDED: "superseded",
    SOURCE_UNAVAILABLE: "source_unavailable",
    NO_CONVERSATION: "no_conversation",
    CONVERSATION_STALE: "conversation_stale",
  });

  function _isPlainObject(value) {
    return typeof value === "object" && value !== null && !Array.isArray(value);
  }

  function _cleanString(value, maxLength = 128) {
    if (typeof value !== "string") return null;
    const trimmed = value.trim();
    if (!trimmed) return null;
    return trimmed.length > maxLength ? trimmed.slice(0, maxLength) : trimmed;
  }

  // A prefix test, not a parse: whatever follows the scheme is the opaque
  // payload owned by #3080 and validated by the desktop shell's own deeplink
  // contract, so this file has no authority to interpret it.
  function _schemeOf(value) {
    const index = value.indexOf(":");
    if (index <= 0) return null;
    return value.slice(0, index + 1).toLowerCase();
  }

  function _carriesControlCharacters(value) {
    return /[\u0000-\u001f\u007f]/.test(value);
  }

  /**
   * Pure activation decision. Everything that could go wrong with "open this
   * link right now" is answered here, in one auditable order, so the guard is
   * testable without a browser.
   *
   * `viewModel` is the live #3084 view model re-read at click time: a panel that
   * was proceedable a moment ago but is not any more must not activate.
   */
  function evaluateActivation(input) {
    const source = _isPlainObject(input) ? input : {};
    const detail = _isPlainObject(source.detail) ? source.detail : {};
    const model = _isPlainObject(source.viewModel) ? source.viewModel : null;
    const codes = GUARD_REASON_CODES;

    const fail = (code) => ({ allowed: false, code, value: null });
    const handoffValue = detail.handoffValue;

    if (typeof handoffValue !== "string" || !handoffValue.trim()) return fail(codes.HANDOFF_ABSENT);
    if (handoffValue.length > MAX_HANDOFF_LENGTH) return fail(codes.HANDOFF_OVER_LENGTH);
    if (handoffValue !== handoffValue.trim() || _carriesControlCharacters(handoffValue)) {
      return fail(codes.HANDOFF_MALFORMED);
    }

    const scheme = _schemeOf(handoffValue);
    if (!scheme || !ALLOWED_HANDOFF_SCHEMES.includes(scheme)) return fail(codes.UNSUPPORTED_SCHEME);

    // The event alone is not evidence. The live projection must still say the
    // same thing, otherwise a click on a panel that already went stale would
    // open a link for a device the server no longer considers usable.
    if (!model) return fail(codes.STALE_PROJECTION);

    // The value must be the one the live projection is currently offering. A
    // synthetic event can carry any text in `handoffValue`, so only the value the
    // #3084 module actually holds may be opened: a forged detail cannot smuggle a
    // link through a panel that is legitimately proceedable.
    const liveHandoff = _isPlainObject(model.handoff) ? model.handoff : null;
    const liveValue =
      liveHandoff && liveHandoff.available === true
        ? _cleanString(liveHandoff.value, MAX_HANDOFF_LENGTH)
        : null;
    if (!liveValue || liveValue !== handoffValue) return fail(codes.HANDOFF_MISMATCH);

    if (model.canProceed !== true) return fail(codes.NOT_PROCEEDABLE);
    if (!_isPlainObject(model.device) || model.device.usable !== true) return fail(codes.NOT_PROCEEDABLE);
    if (model.showConnected !== true) return fail(codes.NOT_PROCEEDABLE);
    if (model.desktopInstalled !== true) return fail(codes.DESKTOP_NOT_INSTALLED);

    // Conversation continuity: the correlation ids carried by the event must be
    // the ids the projection was built for. A mismatch means the click belongs
    // to a different conversation than the one the handoff was minted for, so
    // continuing locally would resume the wrong task.
    const identity = _isPlainObject(model.identity) ? model.identity : {};
    const eventConversation = _cleanString(detail.conversationId);
    if (!eventConversation || !identity.conversationId) return fail(codes.IDENTITY_MISMATCH);
    if (eventConversation !== identity.conversationId) return fail(codes.IDENTITY_MISMATCH);
    if (detail.runId && identity.runId && _cleanString(detail.runId) !== identity.runId) {
      return fail(codes.IDENTITY_MISMATCH);
    }
    if (detail.taskId && identity.taskId && _cleanString(detail.taskId) !== identity.taskId) {
      return fail(codes.IDENTITY_MISMATCH);
    }

    // A custom-scheme open must come from a real user activation, or a browser
    // treats it as a drive-by navigation attempt.
    if (source.userActivated !== true) return fail(codes.NOT_USER_ACTIVATED);

    return { allowed: true, code: codes.OK, value: handoffValue };
  }

  /**
   * Build the adapter. Every ambient dependency is injected, so both halves are
   * testable without a browser and a missing dependency shows up as a bounded
   * fail-closed code instead of a silent no-op.
   */
  function createLocalHandoffAdapter(options) {
    const source = _isPlainObject(options) ? options : {};
    const codes = GUARD_REASON_CODES;

    // Resolved lazily: this file may be parsed before app.js installs the seam.
    const getSeam = typeof source.getSeam === "function" ? source.getSeam : () => source.seam;
    const fetcher = typeof source.fetcher === "function" ? source.fetcher : null;
    const opener = typeof source.opener === "function" ? source.opener : null;
    const dispatch = typeof source.dispatch === "function" ? source.dispatch : null;
    const isUserActivated =
      typeof source.isUserActivated === "function" ? source.isUserActivated : () => true;
    const getConversationId =
      typeof source.getConversationId === "function" ? source.getConversationId : () => null;

    const state = {
      refreshSeq: 0,
      // In-memory only, for the lifetime of the page, bounded. A handoff value
      // is a bearer credential: it is never written to storage or to a log.
      activated: [],
      lastResult: { ok: false, code: "not_started", conversationId: null, runId: null, taskId: null },
      lastSourceCode: "not_loaded",
    };

    function currentSeam() {
      const seam = getSeam();
      return _isPlainObject(seam) ? seam : null;
    }

    function report(code, identity) {
      const detail = _isPlainObject(identity) ? identity : {};
      const result = {
        ok: code === codes.OK,
        code,
        conversationId: _cleanString(detail.conversationId),
        runId: _cleanString(detail.runId),
        taskId: _cleanString(detail.taskId),
      };
      state.lastResult = result;
      if (dispatch) dispatch("padiem:claw-local-adapter-result", result);
      return result;
    }

    /** One same-origin GET for one conversation, last writer wins. */
    async function refresh(explicitConversationId) {
      const requested = ++state.refreshSeq;
      const conversationId = _cleanString(
        typeof explicitConversationId === "string" ? explicitConversationId : getConversationId(),
      );
      const seam = currentSeam();
      if (!conversationId) {
        state.lastSourceCode = codes.NO_CONVERSATION;
        if (seam && typeof seam.project === "function") seam.project({});
        return report(codes.NO_CONVERSATION, {});
      }

      let envelope = null;
      let code = codes.SOURCE_UNAVAILABLE;
      if (fetcher) {
        try {
          const url = `${LOCAL_ACCESS_ENDPOINT}?conversationId=${encodeURIComponent(conversationId)}`;
          const response = await fetcher(url, {
            method: "GET",
            credentials: "same-origin",
            cache: "no-store",
            headers: { Accept: "application/json" },
          });
          if (response && response.ok) {
            const parsed = await response.json();
            if (_isPlainObject(parsed) && parsed.ok === true) {
              envelope = _isPlainObject(parsed.projection) ? parsed.projection : null;
              code =
                parsed.available === true && envelope ? codes.OK : codes.SOURCE_UNAVAILABLE;
            }
          }
        } catch {
          envelope = null;
          code = codes.SOURCE_UNAVAILABLE;
        }
      }

      // A response that arrives after a newer refresh started is dropped rather
      // than painted over it: an out-of-order device state is a false claim.
      if (requested !== state.refreshSeq) return report(codes.SUPERSEDED, { conversationId });

      state.lastSourceCode = code;
      // An unreadable projection is projected as "nothing known", so #3084 hides
      // the panel and refuses proceed. Previously-shown device state is not kept
      // on screen, because a stuck "connected" panel is the exact failure this
      // slice exists to prevent.
      if (seam && typeof seam.project === "function") seam.project(envelope || {});
      return report(code, { conversationId });
    }

    /** The only place in the browser that may ask to open the local app. */
    async function activate(detail, activation) {
      const seam = currentSeam();
      const model = seam && typeof seam.getViewModel === "function" ? seam.getViewModel() : null;
      const userActivated =
        _isPlainObject(activation) && typeof activation.userActivated === "boolean"
          ? activation.userActivated
          : isUserActivated();

      const decision = evaluateActivation({ detail, viewModel: model, userActivated });
      const identity = _isPlainObject(detail) ? detail : {};
      if (!decision.allowed) return report(decision.code, identity);

      // Conversation drift. The panel builds its click detail out of the
      // projection it was handed, so a click made after the user moved to a
      // different conversation still carries the previous conversation's ids.
      // The live id is the only current truth available here: when it differs,
      // this click is refused and fresh truth is fetched, rather than resuming
      // one conversation's task while the user is looking at another.
      const liveConversationId = _cleanString(getConversationId());
      const clickedConversationId = _cleanString(identity.conversationId);
      if (
        liveConversationId
        && clickedConversationId
        && liveConversationId !== clickedConversationId
      ) {
        void refresh(liveConversationId);
        return report(codes.CONVERSATION_STALE, identity);
      }

      // Single-use per value: a replayed event must not open the desktop app
      // twice for one handoff.
      if (state.activated.includes(decision.value)) return report(codes.ALREADY_ACTIVATED, identity);
      state.activated.push(decision.value);
      if (state.activated.length > 16) state.activated.shift();

      if (!opener) return report(codes.OPEN_FAILED, identity);
      try {
        const outcome = opener(decision.value);
        if (outcome && typeof outcome.then === "function") await outcome;
      } catch {
        // The OS may have no handler yet (#3092 registers it). The attempt
        // failed; the panel keeps its guidance and nothing is claimed.
        return report(codes.OPEN_FAILED, identity);
      }
      return report(codes.OK, identity);
    }

    return Object.freeze({
      refresh,
      activate,
      lastResult: () => state.lastResult,
      lastSourceCode: () => state.lastSourceCode,
    });
  }

  // ---------------------------------------------------------------------------
  // Default browser installation.
  // ---------------------------------------------------------------------------

  const host = typeof window === "undefined" ? null : window;

  function _userActivated() {
    // `navigator.userActivation` is the real signal, because the CTA reaches this
    // adapter through a synthetic CustomEvent whose own isTrusted is false.
    const activation = host && host.navigator ? host.navigator.userActivation : null;
    if (activation && typeof activation.hasBeenActive === "boolean") return activation.hasBeenActive;
    return true; // Older engines: the click handler itself is the activation.
  }

  function _openHandoff(value) {
    if (!host || !host.location || typeof host.location.assign !== "function") {
      throw new Error("navigation unavailable");
    }
    host.location.assign(value);
  }

  const adapter = createLocalHandoffAdapter({
    getSeam: () => (host ? host.__padiemClawLocalHandoff : null),
    fetcher:
      host && typeof host.fetch === "function" ? (url, init) => host.fetch(url, init) : null,
    opener: _openHandoff,
    dispatch:
      host && typeof host.dispatchEvent === "function" && typeof CustomEvent === "function"
        ? (name, detail) => host.dispatchEvent(new CustomEvent(name, { detail }))
        : null,
    isUserActivated: _userActivated,
    getConversationId: () => {
      const seam = host ? host.__padiemClawLocalHandoff : null;
      return seam && typeof seam.getConversationId === "function"
        ? seam.getConversationId()
        : null;
    },
  });

  if (host) {
    host.addEventListener("padiem:claw-local-connect-requested", (event) => {
      const detail = event && _isPlainObject(event.detail) ? event.detail : {};
      void adapter.activate(detail);
    });
    host.addEventListener("padiem:claw-local-refresh", (event) => {
      const detail = event && _isPlainObject(event.detail) ? event.detail : {};
      void adapter.refresh(detail.conversationId);
    });

    // Coming back from the desktop app is exactly when device state can have
    // changed. This is an event, not a timer: no background polling exists here.
    const eventsTarget = host.document || host;
    eventsTarget.addEventListener("visibilitychange", () => {
      const visible = !host.document || host.document.visibilityState === "visible";
      if (visible) void adapter.refresh();
    });
    if (host.document && host.document.readyState === "loading") {
      host.document.addEventListener("DOMContentLoaded", () => {
        void adapter.refresh();
      });
    } else {
      void adapter.refresh();
    }
  }

  const exported = Object.freeze({
    ADAPTER_CONTRACT_VERSION,
    HANDOFF_CONTRACT_VERSION,
    LOCAL_ACCESS_ENDPOINT,
    ALLOWED_HANDOFF_SCHEMES,
    MAX_HANDOFF_LENGTH,
    GUARD_REASON_CODES,
    evaluateActivation,
    createLocalHandoffAdapter,
  });

  if (host) {
    host.PadiemClawLocalAdapter = exported;
    host.__padiemClawLocalAdapter = Object.freeze({
      contractVersion: ADAPTER_CONTRACT_VERSION,
      refresh: (conversationId) => adapter.refresh(conversationId),
      activate: (detail, activation) => adapter.activate(detail, activation),
      getResult: () => adapter.lastResult(),
      getSourceCode: () => adapter.lastSourceCode(),
    });
  } else {
    // A DOM-free harness still reaches the pure guard and the factory.
    globalThis.PadiemClawLocalAdapter = exported;
  }
})();



