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
    root.PadiemVoiceComposer = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : (typeof window !== "undefined" ? window : this), function () {
  "use strict";

  /**
   * apps/padiem-chat/static/voice-composer.js
   *
   * Thin Chat and Claw microphone entry for the shared composer (#4643).
   *
   * This module owns no speech engine and no network transport. It renders one
   * accessible mic button plus one interim preview inside the existing
   * composer, and delegates the transcript life-cycle to the reviewed adapter
   * (window.PadiemVoiceSttInput, #4679).
   *
   * A recognizer is only ever attached by an explicit
   * registerRecognizerFactory() call from the product wiring stage -- the
   * layer that owns server-granted voice authority and any transport. While
   * no factory is registered, or while no signed-in session exists, the mic
   * stays disabled and this module performs no request of any kind.
   *
   * Enforced product rules:
   * - Only an authoritative FINAL transcript reaches the existing editable
   *   input. The user reviews or edits it and presses the existing send
   *   control; nothing here submits, approves, or executes anything.
   * - Interim text is a preview only and never becomes user input.
   * - Text typed by the user, including an active IME composition, survives.
   *   A final that arrives mid-composition or while the composer is disabled
   *   is held and flushed when the composer is writable again; if the run ends
   *   first it is dropped rather than injected late.
   * - After stop, sign-out, or a Chat/Claw switch, late interim/final events
   *   are dropped by both a run identity check and the adapter generation and
   *   session-token checks.
   */

  const MIC_BUTTON_ID = "voiceMicButton";
  const INTERIM_ID = "voiceInterimPreview";
  const STATUS_ID = "voiceStatus";

  const STATUS_KEYS = Object.freeze({
    UNAVAILABLE_WIRING: "voice-unavailable-wiring",
    UNAVAILABLE_SIGNIN: "voice-unavailable-signin",
    READY: "voice-ready",
    LISTENING: "voice-listening",
    INTERIM: "voice-interim",
    FINAL: "voice-final",
    STOPPED: "voice-stopped",
    ENDED: "voice-ended",
    DEFERRED: "voice-deferred",
    ERROR: "voice-error",
    ERROR_PERMISSION: "voice-error-permission",
    ERROR_UNSUPPORTED: "voice-error-unsupported",
    MIC_START: "voice-mic-start",
    MIC_STOP: "voice-mic-stop",
  });

  /* English fallbacks only: the shipped Korean/English copy lives in
   * locale.js, and this table keeps the module readable when locale.js has
   * not applied yet (or is absent in an offline harness). */
  const EN_FALLBACK = Object.freeze({
    "voice-mic": "Voice input",
    "voice-mic-start": "Start voice input",
    "voice-mic-stop": "Stop voice input",
    "voice-unavailable-wiring": "Voice input is not connected yet.",
    "voice-unavailable-signin": "Sign in to use voice input.",
    "voice-ready": "Press the microphone button to start voice input.",
    "voice-listening": "Listening.",
    "voice-interim": "Transcribing.",
    "voice-final": "Added the transcript to the input. Review or edit it, then press send.",
    "voice-stopped": "Voice input stopped.",
    "voice-ended": "Voice input ended. Press the microphone button to start again.",
    "voice-deferred": "The transcript will be added after your current typing is finished.",
    "voice-error": "Voice input failed. Try again or type instead.",
    "voice-error-permission": "Microphone permission was denied. Check the browser settings or type instead.",
    "voice-error-unsupported": "This browser does not support voice input. Please type instead.",
  });

  const ERROR_KEY_BY_CODE = Object.freeze({
    "permission-denied": STATUS_KEYS.ERROR_PERMISSION,
    "not-allowed": STATUS_KEYS.ERROR_PERMISSION,
    "user-denied": STATUS_KEYS.ERROR_PERMISSION,
    "unsupported": STATUS_KEYS.ERROR_UNSUPPORTED,
    "speech-recognition-unsupported": STATUS_KEYS.ERROR_UNSUPPORTED,
  });

  function makeToken(win) {
    const now = typeof win.Date === "function" ? win.Date.now() : Date.now();
    return "vc_" + now.toString(36) + "_" + Math.random().toString(36).slice(2, 10);
  }

  function createVoiceComposer(win, doc, options) {
    options = options || {};
    const form = doc && typeof doc.getElementById === "function" ? doc.getElementById("composerForm") : null;
    const input = doc && typeof doc.getElementById === "function" ? doc.getElementById("messageInput") : null;
    const actions = form && typeof form.querySelector === "function" ? form.querySelector(".composer-actions") : null;
    const shell = doc && typeof doc.querySelector === "function" ? doc.querySelector(".app-shell") : null;

    const nodes = { button: null, label: null, preview: null, status: null };
    let factory = typeof options.recognizerFactory === "function" ? options.recognizerFactory : null;
    let run = null;
    let deferredFinals = [];
    let observer = null;
    let destroyed = false;
    let mounted = false;

    const state = {
      authenticated: false,
      authKnown: false,
      identityKey: "",
      composing: false,
      inputDisabled: false,
      generation: 0,
      sessionToken: "",
      voiceState: "idle",
      interim: "",
      idleKey: "",
    };

    function text(key) {
      try {
        const locale = win && win.__padiemLocale;
        if (locale && typeof locale.text === "function") {
          const value = locale.text(key);
          if (value && value !== key) return value;
        }
      } catch (e) { /* fall through to the English fallback */ }
      return EN_FALLBACK[key] || key;
    }

    function availability() {
      if (destroyed || !mounted) return "unavailable";
      if (typeof factory !== "function") return "unavailable";
      if (state.authKnown !== true || state.authenticated !== true) return "unavailable";
      return "ready";
    }

    function availabilityReason() {
      if (typeof factory !== "function") return "wiring";
      return "signin";
    }

    function isReady() {
      return availability() === "ready";
    }

    function isActiveRun() {
      return run !== null;
    }

    function currentStatusKey() {
      if (!isReady()) {
        return availabilityReason() === "signin"
          ? STATUS_KEYS.UNAVAILABLE_SIGNIN
          : STATUS_KEYS.UNAVAILABLE_WIRING;
      }
      if (state.voiceState === "interim") return STATUS_KEYS.INTERIM;
      if (state.voiceState === "deferred") return STATUS_KEYS.DEFERRED;
      if (state.voiceState === "idle") return state.idleKey || STATUS_KEYS.READY;
      // A live run that has committed its turn keeps reporting the final
      // copy until the next utterance or the end of the session.
      return state.idleKey || STATUS_KEYS.LISTENING;
    }

    function render() {
      if (!mounted || destroyed) return;
      const button = nodes.button;
      const ready = isReady();
      const active = isActiveRun() && (state.voiceState === "listening" || state.voiceState === "interim" || state.voiceState === "deferred");
      button.disabled = !ready;
      button.setAttribute("aria-disabled", ready ? "false" : "true");
      button.setAttribute("aria-pressed", active ? "true" : "false");
      button.setAttribute("data-voice-state", !ready ? "unavailable" : active ? "active" : "ready");
      const copyKey = active ? STATUS_KEYS.MIC_STOP : STATUS_KEYS.MIC_START;
      button.setAttribute("aria-label", text(copyKey));
      button.setAttribute("title", text(copyKey));
      button.setAttribute("data-locale-aria-label", copyKey);
      button.setAttribute("data-locale-title", copyKey);
      if (nodes.label) nodes.label.textContent = text("voice-mic");
      if (nodes.status) {
        const key = currentStatusKey();
        nodes.status.setAttribute("data-locale-key", key);
        nodes.status.textContent = text(key);
      }
      if (nodes.preview) {
        const showPreview = ready && state.voiceState === "interim" && state.interim !== "";
        nodes.preview.textContent = showPreview ? state.interim : "";
        nodes.preview.hidden = !showPreview;
      }
    }

    function writeInput(next) {
      if (!input) return;
      input.value = next;
      // Mirror a user edit: app.js re-enables the existing send button and
      // resizes the textarea from this event. Nothing is submitted here.
      try {
        if (typeof win.Event === "function" && typeof input.dispatchEvent === "function") {
          input.dispatchEvent(new win.Event("input", { bubbles: true }));
        }
      } catch (e) { /* the value is already written; the event is best effort */ }
    }

    function inputHandle() {
      return {
        getValue: function () { return input ? input.value : ""; },
        setValue: function (value) { writeInput(value); },
      };
    }

    function runContext(myRun) {
      return { generation: myRun.generation, sessionToken: myRun.sessionToken };
    }

    function isSameRun(myRun) {
      return myRun !== null && run === myRun;
    }

    function commitPayload(payload) {
      if (!run) return null;
      const opts = { generation: run.generation, sessionToken: run.sessionToken };
      if (payload && payload.utteranceId != null) opts.utteranceId = String(payload.utteranceId);
      if (payload && typeof payload.text === "string") opts.text = payload.text;
      return run.adapter.commitFinal(opts);
    }

    function handleAdapterState(next) {
      if (next === "listening") {
        state.voiceState = "listening";
      } else if (next === "interim") {
        state.voiceState = "interim";
      } else if (next === "final") {
        // `final` is an utterance boundary, not the end of the recognizer
        // session: the microphone stays open and the button keeps its stop
        // affordance so the user can end it explicitly. The session ends only
        // through stop(), invalidate(), or the recognizer's own onEnd().
        state.voiceState = run ? "listening" : "idle";
        state.interim = "";
        state.idleKey = STATUS_KEYS.FINAL;
      } else if (next === "stopped") {
        state.voiceState = "idle";
      } else if (next === "error") {
        state.voiceState = "idle";
        state.interim = "";
      }
      render();
    }

    function handleInterim(preview) {
      state.interim = typeof preview === "string" ? preview : "";
      render();
    }

    function submitFinal(payload) {
      if (!run) return;
      if (state.composing || state.inputDisabled) {
        deferredFinals.push(payload || {});
        state.voiceState = "deferred";
        render();
        return;
      }
      const result = commitPayload(payload);
      if (result && result.ok) {
        state.interim = "";
        state.idleKey = STATUS_KEYS.FINAL;
      }
      render();
    }

    function flushDeferred() {
      if (!deferredFinals.length || !run || state.composing || state.inputDisabled) return;
      const queue = deferredFinals;
      deferredFinals = [];
      for (let index = 0; index < queue.length; index += 1) {
        if (!run) break;
        const result = commitPayload(queue[index]);
        if (result && result.ok) {
          state.interim = "";
          state.idleKey = STATUS_KEYS.FINAL;
        }
      }
      if (state.voiceState === "deferred") state.voiceState = run ? "listening" : "idle";
      render();
    }

    function stopSession() {
      const myRun = run;
      if (!myRun) return;
      const session = myRun.session;
      myRun.session = null;
      stopSessionHandle(session);
    }

    function start() {
      if (destroyed || !mounted || !isReady() || isActiveRun()) return false;
      const adapterApi = win ? win.PadiemVoiceSttInput : null;
      if (!adapterApi || typeof adapterApi.createVoiceInputAdapter !== "function") {
        state.idleKey = STATUS_KEYS.ERROR;
        render();
        return false;
      }
      state.generation += 1;
      state.sessionToken = makeToken(win || {});
      state.interim = "";
      state.idleKey = "";
      deferredFinals = [];
      const myRun = { generation: state.generation, sessionToken: state.sessionToken, adapter: null, session: null };
      const adapter = adapterApi.createVoiceInputAdapter({
        generation: myRun.generation,
        sessionToken: myRun.sessionToken,
        input: inputHandle(),
        onState: handleAdapterState,
        onInterim: handleInterim,
      });
      myRun.adapter = adapter;
      if (adapter.start() !== true) {
        state.idleKey = STATUS_KEYS.ERROR;
        render();
        return false;
      }
      run = myRun;
      let session = null;
      try {
        session = factory({
          onInterim: function (chunk) {
            if (isSameRun(myRun)) myRun.adapter.feedInterim(chunk, runContext(myRun));
          },
          onFinal: function (payload) {
            if (isSameRun(myRun)) submitFinal(payload);
          },
          onError: function (code) {
            if (isSameRun(myRun)) recognizerFailed(code);
          },
          onEnd: function () {
            if (isSameRun(myRun)) recognizerEnded();
          },
        }, { generation: myRun.generation, sessionToken: myRun.sessionToken });
      } catch (e) {
        session = null;
      }
      // A recognizer factory that ends or fails its run synchronously, before
      // returning, has already torn that run down. The handle it returns must
      // not be attached to a dead run, and the ended/failed render must not be
      // overwritten by a listening state that nothing listens to.
      if (!isSameRun(myRun)) {
        stopSessionHandle(session);
        return false;
      }
      if (!session || typeof session.stop !== "function") {
        const myRunCheck = isSameRun(myRun);
        run = null;
        myRun.adapter.error("voice-start-failed");
        if (myRunCheck) {
          deferredFinals = [];
          state.voiceState = "idle";
          state.idleKey = STATUS_KEYS.ERROR;
          render();
        }
        return false;
      }
      myRun.session = session;
      state.voiceState = "listening";
      render();
      return true;
    }

    function stop(reason) {
      if (destroyed) return false;
      const stoppedRun = run;
      if (!stoppedRun) {
        render();
        return false;
      }
      // Detach the run before calling recognizer.stop(): implementations may
      // synchronously emit `end` from stop(), and that callback must not
      // recursively stop the same run or mutate the next one.
      run = null;
      stopSessionOnStage(stoppedRun);
      stoppedRun.adapter.stop(reason || "user-stopped");
      // A final held for a composition or a disabled composer belongs to the
      // run that just ended; it is dropped rather than injected afterwards.
      deferredFinals = [];
      state.voiceState = "idle";
      state.interim = "";
      state.idleKey = reason === "recognizer-ended" ? STATUS_KEYS.ENDED : STATUS_KEYS.STOPPED;
      render();
      return true;
    }

    function recognizerEnded() {
      stop("recognizer-ended");
    }

    function recognizerFailed(code) {
      const stage = run;
      if (!stage) return;
      run = null;
      // A failed recognizer must release the microphone, not stay open behind
      // an error state.
      stopSessionOnStage(stage);
      stage.adapter.error(code || "voice-stt-error");
      deferredFinals = [];
      state.voiceState = "idle";
      state.interim = "";
      state.idleKey = ERROR_KEY_BY_CODE[String(code)] || STATUS_KEYS.ERROR;
      render();
    }

    function toggle() {
      if (isActiveRun()) return stop("user-stopped");
      return start();
    }

    function invalidate(reason) {
      if (destroyed) return;
      const stage = run;
      run = null;
      if (stage) {
        stopSessionOnStage(stage);
        stage.adapter.invalidate(reason || "invalidated");
      }
      deferredFinals = [];
      state.voiceState = "idle";
      state.interim = "";
      state.sessionToken = makeToken(win || {});
      render();
    }

    function stopSessionOnStage(stage) {
      if (!stage || !stage.session) return;
      const session = stage.session;
      stage.session = null;
      stopSessionHandle(session);
    }

    function stopSessionHandle(session) {
      if (!session || typeof session.stop !== "function") return;
      try { session.stop(); } catch (e) { /* the recognizer is already gone */ }
    }

    function setRecognizerFactory(next) {
      const resolved = typeof next === "function" ? next : null;
      if (resolved === factory) return false;
      factory = resolved;
      if (!factory) invalidate("recognizer-detached");
      render();
      return true;
    }

    // #4643: `padiem:auth-state` deliberately carries only a boolean (#3790),
    // so it cannot see an account switch between two signed-in states. The
    // wiring stage therefore supplies a separate opaque `identityKey` that
    // changes whenever the account or session identity changes. Comparing the
    // key is what makes a same-boolean account switch invalidate the run; the
    // key is never a user id, a tenant id or a credential, and is held only to
    // test "changed / unchanged".
    function handleIdentityKey(identityKey) {
      const next = identityKey == null ? "" : String(identityKey);
      const changed = state.identityKey !== "" && next !== state.identityKey;
      state.identityKey = next;
      if (changed && state.authenticated) invalidate("account-changed");
      render();
    }

    function handleAuthState(authenticated, identityKey) {
      const next = authenticated === true;
      const switched = state.authKnown && next !== state.authenticated;
      const previousKey = state.identityKey;
      state.authKnown = true;
      state.authenticated = next;
      if (identityKey != null) state.identityKey = String(identityKey);
      // Same boolean, different account: still a different voice identity.
      const rekeyed =
        previousKey !== "" && state.identityKey !== "" && previousKey !== state.identityKey;
      if (switched || rekeyed) invalidate(next ? "session-changed" : "signed-out");
      render();
    }

    function handleShellState() {
      invalidate("shell-state-changed");
    }

    function handleCompositionStart() {
      state.composing = true;
      render();
    }

    function handleCompositionEnd() {
      state.composing = false;
      flushDeferred();
      render();
    }

    function handleInputDisabled() {
      state.inputDisabled = input ? input.disabled === true : false;
      if (!state.inputDisabled) flushDeferred();
      render();
    }

    function listen(target, type, handler) {
      if (target && typeof target.addEventListener === "function") {
        target.addEventListener(type, handler);
        return function () {
          if (typeof target.removeEventListener === "function") target.removeEventListener(type, handler);
        };
      }
      return function () {};
    }

    const detach = [];

    function mount() {
      if (mounted || destroyed) return mounted;
      if (!form || !input || !actions || !doc.createElement) return false;
      const button = doc.createElement("button");
      button.id = MIC_BUTTON_ID;
      button.type = "button";
      button.className = "voice-mic-button";
      button.disabled = true;
      button.setAttribute("aria-pressed", "false");
      button.setAttribute("aria-disabled", "true");
      button.setAttribute("data-voice-state", "unavailable");
      const icon = doc.createElement("span");
      icon.setAttribute("aria-hidden", "true");
      icon.textContent = "\u25c9";
      const label = doc.createElement("span");
      label.setAttribute("data-locale-key", "voice-mic");
      label.textContent = text("voice-mic");
      button.appendChild(icon);
      button.appendChild(label);

      const cancel = doc.getElementById("cancelStreamButton");
      if (cancel && cancel.parentNode === actions) actions.insertBefore(button, cancel);
      else actions.appendChild(button);

      const preview = doc.createElement("p");
      preview.id = INTERIM_ID;
      preview.className = "voice-interim-preview";
      preview.setAttribute("aria-hidden", "true");
      preview.hidden = true;
      preview.textContent = "";

      const status = doc.createElement("p");
      status.id = STATUS_ID;
      status.className = "voice-status sr-only";
      status.setAttribute("role", "status");
      status.setAttribute("aria-live", "polite");
      status.setAttribute("aria-atomic", "true");
      status.textContent = "";

      form.insertBefore(preview, actions);
      form.insertBefore(status, actions);

      nodes.button = button;
      nodes.label = label;
      nodes.preview = preview;
      nodes.status = status;
      state.inputDisabled = input.disabled === true;
      mounted = true;

      detach.push(listen(button, "click", function () { toggle(); }));
      detach.push(listen(input, "compositionstart", handleCompositionStart));
      detach.push(listen(input, "compositionend", handleCompositionEnd));
      detach.push(listen(win, "padiem:auth-state", function (event) {
        const detail = event && event.detail ? event.detail : {};
        handleAuthState(detail.authenticated, detail.identityKey);
      }));
      // #4643: the wiring stage announces an opaque identity-change key here.
      detach.push(listen(win, "padiem:voice-identity", function (event) {
        const detail = event && event.detail ? event.detail : {};
        if (detail && typeof detail.identityKey === "string") handleIdentityKey(detail.identityKey);
      }));
      detach.push(listen(win, "padiem:localechange", function () { render(); }));

      if (shell && typeof win.MutationObserver === "function") {
        observer = new win.MutationObserver(function () { handleShellState(); });
        observer.observe(shell, { attributes: true, attributeFilter: ["data-state"] });
      }
      if (input && typeof win.MutationObserver === "function") {
        const inputObserver = new win.MutationObserver(function () { handleInputDisabled(); });
        inputObserver.observe(input, { attributes: true, attributeFilter: ["disabled"] });
        detach.push(function () {
          if (typeof inputObserver.disconnect === "function") inputObserver.disconnect();
        });
      }
      render();
      return true;
    }

    function destroy() {
      if (destroyed) return;
      const stage = run;
      run = null;
      if (stage) {
        stopSessionOnStage(stage);
        stage.adapter.invalidate("destroyed");
      }
      deferredFinals = [];
      detach.forEach(function (off) { try { off(); } catch (e) { /* already detached */ } });
      detach.length = 0;
      if (observer && typeof observer.disconnect === "function") observer.disconnect();
      observer = null;
      if (nodes.button && nodes.button.parentNode) nodes.button.parentNode.removeChild(nodes.button);
      if (nodes.preview && nodes.preview.parentNode) nodes.preview.parentNode.removeChild(nodes.preview);
      if (nodes.status && nodes.status.parentNode) nodes.status.parentNode.removeChild(nodes.status);
      nodes.button = null;
      nodes.label = null;
      nodes.preview = null;
      nodes.status = null;
      mounted = false;
      destroyed = true;
    }

    function getStatus() {
      return {
        mounted: mounted,
        destroyed: destroyed,
        availability: availability(),
        availabilityReason: availabilityReason(),
        voiceState: state.voiceState,
        statusKey: currentStatusKey(),
        authKnown: state.authKnown,
        authenticated: state.authenticated,
        identityKey: state.identityKey,
        generation: state.generation,
        sessionToken: state.sessionToken,
        active: isActiveRun(),
        deferred: deferredFinals.length,
        interim: state.interim,
      };
    }

    mount();

    return {
      MIC_BUTTON_ID: MIC_BUTTON_ID,
      INTERIM_ID: INTERIM_ID,
      STATUS_ID: STATUS_ID,
      STATUS_KEYS: STATUS_KEYS,
      mount: mount,
      start: start,
      stop: stop,
      toggle: toggle,
      invalidate: invalidate,
      setRecognizerFactory: setRecognizerFactory,
      handleIdentityKey: handleIdentityKey,
      destroy: destroy,
      getStatus: getStatus,
    };
  }

  let controller = null;

  function init(win, doc, options) {
    const targetWin = win || (typeof globalThis !== "undefined" ? globalThis : null);
    const targetDoc = doc || (targetWin ? targetWin.document : null);
    if (!targetWin || !targetDoc) return null;
    if (controller && !controller.getStatus().destroyed) return controller;
    controller = createVoiceComposer(targetWin, targetDoc, options);
    // A head-placed script would run before the composer exists; retry once the
    // parsed document is complete instead of silently staying unmounted.
    if (!controller.getStatus().mounted && typeof targetDoc.addEventListener === "function") {
      targetDoc.addEventListener("DOMContentLoaded", function () {
        if (controller && !controller.getStatus().mounted) controller.mount();
      }, { once: true });
    }
    return controller;
  }

  function registerRecognizerFactory(fn) {
    if (controller) return controller.setRecognizerFactory(fn);
    return false;
  }

  function autoInit(root) {
    const doc = root && root.document ? root.document : null;
    if (!doc || typeof doc.getElementById !== "function") return null;
    if (!doc.getElementById("composerForm")) return null;
    return init(root, doc);
  }

  if (typeof globalThis !== "undefined" && globalThis.document && typeof globalThis.document.getElementById === "function") {
    autoInit(globalThis);
  }

  return {
    MIC_BUTTON_ID: MIC_BUTTON_ID,
    INTERIM_ID: INTERIM_ID,
    STATUS_ID: STATUS_ID,
    STATUS_KEYS: STATUS_KEYS,
    EN_FALLBACK: EN_FALLBACK,
    createVoiceComposer: createVoiceComposer,
    init: init,
    registerRecognizerFactory: registerRecognizerFactory,
    autoInit: autoInit,
    getController: function () { return controller; },
  };
});