// #4816: unified voice mode toolbar for Chat(B62) and Claw(B54).
// #5561: the voice waveform and the send arrow share ONE primary action slot
// (the send button). An empty composer shows the waveform and opens the
// M2/M3/M4 picker; a composer with text shows the arrow and sends.
// The M1 microphone stays a separate, smaller control in the same row.
// Shares one turn controller with the composer; never starts a provider call.
(function (win, doc) {
  "use strict";
  const form = doc.getElementById("composerForm");
  const input = doc.getElementById("messageInput");
  const send = doc.getElementById("sendButton");
  const actions = form && form.querySelector(".composer-actions");
  const shell = doc && typeof doc.querySelector === "function" ? doc.querySelector(".app-shell") : null;
  if (!form || !input || !send || !actions) return;

  const liveAPI = win.PadiemVoiceLiveTurnController;
  const composerAPI = win.PadiemVoiceComposer;
  const ko = () => /^ko/i.test(doc.documentElement.lang || "ko");
  // Voice copy: the voice mode copy comes from the existing locale catalogue.
  // The previous inline Korean literals were corrupted escape sequences that
  // rendered as a meaningless phrase instead of a real label.
  function localeText(key, fallback) {
    try {
      if (win.__padiemLocale && typeof win.__padiemLocale.text === "function") {
        const value = win.__padiemLocale.text(key);
        if (value && value !== key) return value;
      }
    } catch (_) {}
    return fallback;
  }
  const MODE_LABELS = Object.freeze({
    text: { key: "voice-mode-text", ko: "문자로 답변", en: "Text only" },
    tts: { key: "voice-mode-tts", ko: "문자 + 음성 함께", en: "Text + voice together" },
    call: { key: "voice-mode-call", ko: "음성 통화", en: "Voice call" },
  });
  function modeLabel(m) {
    const entry = MODE_LABELS[m] || MODE_LABELS.text;
    return localeText(entry.key, ko() ? entry.ko : entry.en);
  }
  const pickerTitle = () => localeText("voice-mode", ko() ? "음성 모드" : "Voice mode");
  const sendTitle = () => localeText("send-tooltip", ko() ? "메시지 전송" : "Send message");
  const sendLabel = () => localeText("send", ko() ? "메시지 보내기" : "Send message");

  let menu = null;
  let controller = null;
  let currentMode = "basic"; // basic | live
  let ttsOn = false;
  let callOn = false;
  let outstandingKey = "";
  let busySeen = false;
  let menuOpen = false;
  let composing = false;

  function composerStatus() {
    const controller = composerAPI && composerAPI.getController && composerAPI.getController();
    return controller && controller.getStatus ? controller.getStatus() : {};
  }
  function key() {
    const status = composerStatus();
    return status.authenticated === true && status.authKnown === true
      ? String(status.identityKey || "") : "";
  }
  // #4816 lifecycle: M3 auto-speech is only armed while the live voice session
  // is still valid. An ended, muted, cancelled or re-authenticated session must
  // not speak a late answer, and M2 must never auto-speak at all.
  function sessionValid() {
    if (!controller) return true;
    const st = controller.getState ? controller.getState() : null;
    if (!st) return true;
    return st.cancelled !== true && st.invalidated !== true;
  }
  function isTtsActive() {
    return currentMode === "live" && ttsOn === true && sessionValid();
  }
  function isCallActive() { return currentMode === "live" && callOn === true; }

  function stopAnswerSpeech() {
    const answer = win.PadiemVoiceAnswer;
    if (answer && typeof answer.stop === "function") answer.stop();
  }

  // One session boundary for 종료 · 음소거 · 취소 · 계정 전환. Cancelling the
  // shared turn controller revokes the pending accepted turn, so the recognizer
  // tail that arrives afterwards cannot auto-send. Playback started by M3 is
  // stopped with the same signal, and a queued (not yet spoken) answer is
  // dropped instead of playing after the session ended.
  function endTurn(reason) {
    closeMenu();
    outstandingKey = "";
    busySeen = false;
    const c = controller;
    if (c && typeof c.cancel === "function") c.cancel();
    stopAnswerSpeech();
    try {
      win.dispatchEvent(new win.CustomEvent("padiem:voice-end", {
        detail: {reason: reason || "voice-end"}
      }));
    } catch (_) { /* presentation only */ }
    renderWaveform(); renderItems();
  }

  // Unmuting or re-entering a voice mode resumes the same conversation with a
  // fresh turn generation: no re-authentication, no new conversation id.
  function resumeTurn() {
    const c = controller;
    if (c && typeof c.reset === "function") c.reset();
    renderWaveform(); renderItems();
  }

  function ensureController() {
    if (!controller && liveAPI && typeof liveAPI.create === "function") {
      controller = liveAPI.create({
        accountKey: key(),
        getAccountKey: key,
        getInFlight: () => input.disabled === true,
        getCanSubmit: () => input.disabled !== true && send.disabled !== true &&
          input.value.trim().length > 0,
        // The canonical voice composer has already committed the accepted final
        // into the input; never inject another copy or overwrite user input.
        commitText: (text) => input.value.trim() === text.trim(),
        submit: (value, meta) => {
          form.requestSubmit();
          return true;
        },
        onPreview: function () {},
        onStateChange: function () { renderWaveform(); },
      });
      if (typeof controller.syncSessionGeneration === "function") {
        controller.syncSessionGeneration(composerStatus().generation);
      }
    }
    return controller;
  }

  function syncIdentity() {
    const current = key();
    const c = controller;
    if (!c) return;
    if (c.getState().accountKey !== current) {
      c.setAccountKey(current);
      c.setMode("basic");
      // The controller returns to basic on an identity change; the module state
      // must follow, otherwise a M3 auto-speak armed for the previous account
      // stays armed for the new one (#4816).
      currentMode = "basic"; ttsOn = false; callOn = false;
      busySeen = false; outstandingKey = "";
      stopAnswerSpeech();
    }
    if (typeof c.syncSessionGeneration === "function") {
      c.syncSessionGeneration(composerStatus().generation);
    }
  }

  // The voice picker only exists when the product really has one: a live turn
  // controller and an account whose voice identity the server accepted.
  // Otherwise the primary action stays the honest send arrow.
  function voiceAvailable() {
    return Boolean(liveAPI && typeof liveAPI.create === "function" && key());
  }

  // The primary action is the voice picker only for a composer that can
  // actually take a voice turn: no text, no request in flight, no open IME
  // composition. Whitespace alone is still an empty composer.
  function isVoicePrimaryAction() {
    if (!voiceAvailable()) return false;
    if (input.disabled === true) return false;
    if (composing) return false;
    return String(input.value || "").trim() === "";
  }

  function renderWaveform() {
    send.setAttribute("data-voice-mode", currentMode);
    syncPrimaryAction();
  }

  // One slot, two faces: the waveform while the composer is empty, the arrow
  // once there is something to send. The slot itself never moves.
  //
  // The faces are <svg>, and an SVG element has no `hidden` IDL property —
  // assigning one writes a plain JS expando and never touches the content
  // attribute the CSS keys on. The attribute is what actually moves a face.
  function setFaceHidden(face, isHidden) {
    if (!face) return;
    if (isHidden) face.setAttribute("hidden", "");
    else face.removeAttribute("hidden");
  }

  function syncPrimaryAction() {
    const voice = isVoicePrimaryAction();
    const arrow = send.querySelector(".send-arrow-icon");
    const waveIcon = send.querySelector(".send-waveform-icon");
    // The face the slot is NOT showing is the one that carries the attribute.
    setFaceHidden(arrow, voice);
    setFaceHidden(waveIcon, !voice);
    send.dataset.primaryAction = voice ? "voice" : "send";
    if (voice) {
      send.setAttribute("aria-haspopup", "menu");
      send.setAttribute("aria-expanded", menuOpen ? "true" : "false");
      send.setAttribute("aria-label", pickerTitle());
      send.setAttribute("title", pickerTitle());
      send.setAttribute("data-padiem-tooltip", pickerTitle());
      send.setAttribute("aria-pressed", currentMode === "live" ? "true" : "false");
      return;
    }
    send.removeAttribute("aria-haspopup");
    send.setAttribute("aria-expanded", "false");
    send.removeAttribute("aria-pressed");
    send.setAttribute("aria-label", sendLabel());
    send.setAttribute("title", sendTitle());
    send.setAttribute("data-padiem-tooltip", sendTitle());
  }

  function escapeHtml(value) {
    return String(value || "")
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  function placeMenu() {
    if (!menu || !menuOpen) return;
    const rect = send.getBoundingClientRect();
    const top = rect.bottom + 6;
    const left = Math.max(4, Math.min(rect.left, doc.documentElement.clientWidth - menu.offsetWidth - 8));
    menu.style.left = left + "px";
    menu.style.top = top + "px";
    const bottom = top + menu.offsetHeight;
    if (bottom > doc.documentElement.clientHeight - 4 && rect.top - menu.offsetHeight - 6 >= 4) {
      menu.style.top = (rect.top - menu.offsetHeight - 6) + "px";
    }
  }

  function openMenu() {
    if (menuOpen) return;
    ensureController();
    syncIdentity();
    menu.hidden = false;
    menuOpen = true;
    send.setAttribute("aria-expanded", "true");
    placeMenu();
    renderItems();
  }

  function closeMenu() {
    if (!menuOpen) return;
    menu.hidden = true;
    menuOpen = false;
    send.setAttribute("aria-expanded", "false");
  }

  function renderItems() {
    if (!menu) return;
    menu.setAttribute("aria-label", pickerTitle());
    const items = menu.querySelectorAll('[data-mode]');
    items.forEach(function (item) {
      const m = item.getAttribute("data-mode");
      // Voice copy: the item label follows the active language.
      const label = modeLabel(m);
      if (item.textContent !== label) item.textContent = label;
      const active = currentMode === "live" && (
        (m === "text" && !ttsOn && !callOn) ||
        (m === "tts" && ttsOn && !callOn) ||
        (m === "call" && callOn && !ttsOn)
      );
      item.setAttribute("aria-checked", active ? "true" : "false");
      item.setAttribute("data-active", active ? "true" : "false");
    });
  }

  function selectMode(m) {
    closeMenu();
    ensureController();
    syncIdentity();
    const c = controller;
    if (!c) return;
    // A pending turn belongs to the mode that was active when it started.
    // Cancel it before arming the newly selected mode, otherwise the answer to
    // the old turn can be spoken or a late final can submit into the new mode.
    if (typeof c.cancel === "function") c.cancel();
    outstandingKey = "";
    busySeen = false;
    if (m !== "tts") stopAnswerSpeech();
    if (m === "text") { currentMode = "live"; ttsOn = false; callOn = false; c.setMode("live"); }
    else if (m === "tts") { currentMode = "live"; ttsOn = true; callOn = false; c.setMode("live"); }
    else if (m === "call") { currentMode = "live"; ttsOn = false; callOn = true; c.setMode("live"); }
    renderWaveform(); renderItems();
    if (m === "call" && win.PadiemVoiceCall && typeof win.PadiemVoiceCall.show === "function") {
      win.PadiemVoiceCall.show();
    }
  }

  menu = doc.createElement("div");
  menu.id = "voiceModeMenu";
  menu.className = "voice-mode-menu";
  menu.hidden = true;
  menu.setAttribute("role", "menu");
  menu.setAttribute("aria-label", pickerTitle());
  const menuItems = [
    {mode: "text"},
    {mode: "tts"},
    {mode: "call"},
  ];
  menuItems.forEach(function (item) {
    const div = doc.createElement("div");
    div.className = "voice-mode-menu-item";
    div.setAttribute("role", "menuitemradio");
    div.setAttribute("data-mode", item.mode);
    div.setAttribute("aria-checked", "false");
    div.textContent = modeLabel(item.mode);
    menu.appendChild(div);
  });
  doc.body.appendChild(menu);

  // The primary action slot: with an empty composer it opens the voice mode
  // picker, with text it is the ordinary send button.
  send.addEventListener("click", function (event) {
    if (!isVoicePrimaryAction()) return;
    event.preventDefault();
    if (menuOpen) closeMenu(); else openMenu();
  });

  menu.addEventListener("click", function (event) {
    const item = event.target.closest ? event.target.closest('[data-mode]') : null;
    if (!item) return;
    event.preventDefault();
    event.stopPropagation();
    selectMode(item.getAttribute("data-mode"));
  });

  function syncIdentityAndState() {
    syncIdentity();
    renderWaveform(); renderItems();
  }

  win.addEventListener("click", function (event) {
    if (!menuOpen || !menu) return;
    // A real click on the slot lands on the icon inside the button, not on the
    // button element itself. Comparing identity here closed the picker in the
    // same gesture that opened it, so the whole surface is the exclusion.
    if (menu.contains(event.target) || send.contains(event.target)) return;
    closeMenu();
  });
  win.addEventListener("keydown", function (event) {
    if (menuOpen && event.key === "Escape") closeMenu();
  });
  // A new microphone run is a new turn authority. Starting one clears the
  // cancelled/revoked window left by the previous end, mute or cancel, while the
  // composer still refuses the previous run's tail by run identity (#4816).
  const micButton = doc.getElementById("voiceMicButton");
  if (micButton) micButton.addEventListener("click", resumeTurn);

  win.addEventListener("padiem:auth-state", syncIdentityAndState);
  win.addEventListener("padiem:voice-identity", syncIdentityAndState);
  win.addEventListener("padiem:localechange", syncIdentityAndState);
  // The composer owns the input value; this module only reads it. Every
  // composer change (typing, IME, paste, a committed voice transcript, a
  // cleared composer) re-reads the value and moves the slot.
  input.addEventListener("input", syncPrimaryAction);
  input.addEventListener("compositionstart", function () { composing = true; syncPrimaryAction(); });
  input.addEventListener("compositionend", function () { composing = false; syncPrimaryAction(); });
  if (shell && win.MutationObserver) {
    new win.MutationObserver(syncIdentityAndState).observe(shell, {attributes: true, attributeFilter: ["data-state"]});
  }

  // Accepted-final bridge from the composer: commit already applied to the input,
  // then exactly one form.submit via composerForm.requestSubmit().
  win.addEventListener("padiem:voice-accepted-turn", function (event) {
    const info = event && event.detail;
    if (!info || !controller || !key()) return;
    syncIdentity();
    const c = composerStatus();
    /* #4643: the accepted turn may arrive while the microphone run is still
     * open (Mode 2/3/4 auto-send once per utterance) or right after it
     * stopped. The run authority is the generation/session pair, not the run
     * state, so an open run does not swallow its own turn. */
    if (c.generation !== info.composerGeneration ||
        c.sessionToken !== info.sessionToken || info.accountKey !== key() ||
        info.accepted !== true || info.endOfTurn !== true) return;
    const st = controller.getState();
    if (st.mode !== "live") return; // auto-send armed only for M2/M3/M4
    if (typeof controller.syncSessionGeneration === "function") {
      controller.syncSessionGeneration(info.composerGeneration);
    }
    const result = controller.handleFinal({
      accepted: true, endOfTurn: true,
      accountKey: info.accountKey, sessionGeneration: st.sessionGeneration,
      finalId: info.finalId, text: info.text
    });
    if (result.submitted) {
      busySeen = input.disabled === true;
      outstandingKey = result.finalKey;
    }
    renderWaveform();
  });

  if (win.MutationObserver) {
    new win.MutationObserver(function () {
      if (!outstandingKey) return;
      if (input.disabled) busySeen = true;
      else if (busySeen) {
        controller.markAnswerSettled({accountKey: key(), finalKey: outstandingKey});
        outstandingKey = "";
        busySeen = false;
      }
    }).observe(input, {attributes: true, attributeFilter: ["disabled"]});
  }

  win.PadiemVoiceMenu = {
    getController: function () { return controller; },
    getState: function () {
      return {mode: currentMode, ttsOn: ttsOn, callOn: callOn,
        live: currentMode === "live", busySeen: busySeen};
    },
    setCallMode: function (on) { callOn = on === true; renderItems(); },
    isTtsActive: isTtsActive,
    isCallActive: isCallActive,
    // #4816: one session boundary for 종료 · 음소거 · 취소; account changes and
    // mode switches use it too. Voice mode stays available afterwards.
    endTurn: endTurn,
    resumeTurn: resumeTurn,
    selectMode: selectMode,
    closeMenu: closeMenu,
    // #5561: the primary action slot is shared by the voice waveform and the
    // send arrow, so the composer authority asks this module for the state.
    isVoicePrimaryAction: isVoicePrimaryAction,
    syncPrimaryAction: syncPrimaryAction,
  };
  renderWaveform();
})(window, document);
