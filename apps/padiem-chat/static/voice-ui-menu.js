// #4816: unified voice mode toolbar for Chat(B62) and Claw(B54).
// Owner 2026-10-31 (A안): the microphone (M1) and the voice waveform picker
// (M2/M3/M4) are TWO persistent icons in the composer row. The waveform never
// borrows the send slot, so typing text cannot make it disappear, and the send
// slot is always the arrow. #5561's empty-composer waveform CTA is retired by
// that decision: an icon that moves is harder to find than a fixed one.
// The M1 microphone stays its own control, created by voice-composer.js.
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

  // The waveform picker is its own control, mounted beside the microphone.
  // Both icons exist in every state; only what they can do differs, so nobody
  // has to hunt for an icon that moved because they started typing.
  const SVG_NS = "http://www.w3.org/2000/svg";
  const waveform = doc.createElement("button");
  waveform.id = "voiceWaveformButton";
  waveform.type = "button";
  waveform.className = "voice-waveform-button";
  waveform.setAttribute("aria-haspopup", "menu");
  waveform.setAttribute("aria-expanded", "false");
  const glyph = doc.createElementNS(SVG_NS, "svg");
  glyph.setAttribute("class", "voice-waveform-glyph");
  glyph.setAttribute("aria-hidden", "true");
  glyph.setAttribute("viewBox", "0 0 24 24");
  glyph.setAttribute("fill", "none");
  glyph.setAttribute("focusable", "false");
  const glyphPath = doc.createElementNS(SVG_NS, "path");
  glyphPath.setAttribute("d", "M4 10v4M8 6v12M12 3v18M16 7v10M20 10v4");
  glyphPath.setAttribute("stroke", "currentColor");
  glyphPath.setAttribute("stroke-width", "2.2");
  glyphPath.setAttribute("stroke-linecap", "round");
  glyphPath.setAttribute("stroke-linejoin", "round");
  glyph.appendChild(glyphPath);
  waveform.appendChild(glyph);
  const waveformLabel = doc.createElement("span");
  waveformLabel.className = "sr-only";
  waveformLabel.setAttribute("data-locale-key", "voice-mode");
  waveformLabel.textContent = pickerTitle();
  waveform.appendChild(waveformLabel);
  // An inactive control explains itself when pressed, the same rule the
  // microphone follows. The explanation is spoken, not only hinted.
  const waveformNotice = doc.createElement("span");
  waveformNotice.id = "voiceWaveformNotice";
  waveformNotice.className = "sr-only";
  waveformNotice.setAttribute("role", "status");
  waveformNotice.setAttribute("aria-live", "polite");
  waveformNotice.setAttribute("aria-atomic", "true");
  const micControl = doc.getElementById("voiceMicButton");
  if (micControl && micControl.parentNode === actions) {
    actions.insertBefore(waveform, micControl.nextSibling);
  } else {
    actions.insertBefore(waveform, send);
  }
  actions.insertBefore(waveformNotice, waveform.nextSibling);

  // Why the picker cannot take a turn right now. The inputs are the ones the
  // composer already uses to decide a voice turn is possible: the turn
  // controller, a known account, and the opaque voice identity the server
  // accepted. Nothing here invents a permission or a tier.
  function voiceReason() {
    if (!liveAPI || typeof liveAPI.create !== "function") return "wiring";
    const status = composerStatus();
    if (status.authKnown !== true || status.authenticated !== true) return "signin";
    if (!key()) return "wiring";
    return "";
  }

  function voiceAvailable() {
    return voiceReason() === "";
  }

  function voiceReasonText(reason) {
    if (reason === "signin") {
      return localeText("voice-unavailable-signin",
        ko() ? "로그인 후 음성 입력을 사용할 수 있습니다." : "Sign in to use voice input.");
    }
    return localeText("voice-unavailable-wiring",
      ko() ? "음성 입력은 아직 연결되지 않았습니다." : "Voice input is not connected yet.");
  }

  function renderWaveform() {
    syncControls();
  }

  // The faces are <svg>, and an SVG element has no `hidden` IDL property —
  // assigning one writes a plain JS expando and never touches the content
  // attribute the CSS keys on. The attribute is what actually moves a face.
  function setFaceHidden(face, isHidden) {
    if (!face) return;
    if (isHidden) face.setAttribute("hidden", "");
    else face.removeAttribute("hidden");
  }

  // The send slot keeps one face for good: typing text must never remove an
  // icon from the row. The waveform SVG still present inside the send button
  // in index.html is pinned hidden here, so stale markup cannot resurrect the
  // old swap.
  function syncControls() {
    setFaceHidden(send.querySelector(".send-arrow-icon"), false);
    setFaceHidden(send.querySelector(".send-waveform-icon"), true);
    send.dataset.primaryAction = "send";
    send.removeAttribute("aria-haspopup");
    send.setAttribute("aria-expanded", "false");
    send.removeAttribute("aria-pressed");
    send.setAttribute("aria-label", sendLabel());
    send.setAttribute("title", sendTitle());
    send.setAttribute("data-padiem-tooltip", sendTitle());

    const reason = voiceReason();
    const available = reason === "";
    const copy = available ? pickerTitle() : voiceReasonText(reason);
    waveform.setAttribute("data-voice-mode", currentMode);
    waveform.setAttribute(
      "data-voice-state",
      !available ? "unavailable" : currentMode === "live" ? "active" : "ready",
    );
    // Same rule as the microphone (voice-composer.js): the control stays
    // pressable and explains itself, rather than becoming a dead button whose
    // reason only lives in a hover tooltip a phone never shows.
    waveform.setAttribute("aria-disabled", "false");
    waveform.setAttribute("aria-pressed", currentMode === "live" ? "true" : "false");
    waveform.setAttribute("aria-label", copy);
    waveform.setAttribute("title", copy);
    waveform.setAttribute("data-padiem-tooltip", copy);
    waveform.setAttribute("aria-expanded", menuOpen ? "true" : "false");
    waveformLabel.textContent = pickerTitle();
  }

  function escapeHtml(value) {
    return String(value || "")
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  function placeMenu() {
    if (!menu || !menuOpen) return;
    // Anchored to the waveform control that owns it, not to the send button.
    const rect = waveform.getBoundingClientRect();
    const top = rect.bottom + 6;
    const left = Math.max(4, Math.min(rect.left, doc.documentElement.clientWidth - menu.offsetWidth - 8));
    menu.style.left = left + "px";
    menu.style.top = top + "px";
    const bottom = top + menu.offsetHeight;
    if (bottom > doc.documentElement.clientHeight - 4 && rect.top - menu.offsetHeight - 6 >= 4) {
      menu.style.top = (rect.top - menu.offsetHeight - 6) + "px";
    }
  }

  function focusMenuItem(index) {
    const items = menu ? Array.prototype.slice.call(menu.querySelectorAll('[data-mode]')) : [];
    if (!items.length) return;
    const target = Math.max(0, Math.min(index, items.length - 1));
    items.forEach(function (item, i) {
      item.setAttribute("tabindex", i === target ? "0" : "-1");
    });
    items[target].focus();
  }

  function openMenu(focusFirst) {
    if (menuOpen) return;
    ensureController();
    syncIdentity();
    menu.hidden = false;
    menuOpen = true;
    waveform.setAttribute("aria-expanded", "true");
    placeMenu();
    renderItems();
    if (focusFirst) focusMenuItem(0);
  }

  function closeMenu(returnFocus) {
    if (!menuOpen) return;
    menu.hidden = true;
    menuOpen = false;
    waveform.setAttribute("aria-expanded", "false");
    if (returnFocus) waveform.focus();
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

  function selectMode(m, returnFocus) {
    closeMenu(returnFocus === true);
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
  menuItems.forEach(function (item, index) {
    const div = doc.createElement("div");
    div.className = "voice-mode-menu-item";
    div.id = "voiceModeMenuItem-" + item.mode;
    div.setAttribute("role", "menuitemradio");
    div.setAttribute("data-mode", item.mode);
    div.setAttribute("aria-checked", "false");
    // Roving focus: the items are real focus targets, so a keyboard user lands
    // on them with the arrow keys and reads them with a screen reader.
    div.setAttribute("tabindex", index === 0 ? "0" : "-1");
    div.textContent = modeLabel(item.mode);
    menu.appendChild(div);
  });
  doc.body.appendChild(menu);

  // The waveform button owns the picker now. The send button is only ever the
  // send button, so typing text can neither hide an icon nor change what a
  // press means.
  waveform.addEventListener("click", function (event) {
    event.preventDefault();
    const reason = voiceReason();
    if (reason !== "") {
      waveformNotice.textContent = voiceReasonText(reason);
      return;
    }
    if (menuOpen) closeMenu(true); else openMenu(true);
  });

  menu.addEventListener("click", function (event) {
    const item = event.target.closest ? event.target.closest('[data-mode]') : null;
    if (!item) return;
    event.preventDefault();
    event.stopPropagation();
    selectMode(item.getAttribute("data-mode"));
  });

  // Keyboard operation for the picker: arrows move, Home/End jump, Enter or
  // Space picks, Escape closes and returns focus to the button that opened it.
  menu.addEventListener("keydown", function (event) {
    const items = Array.prototype.slice.call(menu.querySelectorAll('[data-mode]'));
    if (!items.length) return;
    const current = items.indexOf(doc.activeElement);
    const key = event.key;
    function focusAt(index) {
      items.forEach(function (item, i) {
        item.setAttribute("tabindex", i === index ? "0" : "-1");
      });
      items[index].focus();
    }
    if (key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      closeMenu(true);
      return;
    }
    if (key === "ArrowDown" || key === "ArrowUp" || key === "Home" || key === "End") {
      event.preventDefault();
      let next;
      if (key === "Home") next = 0;
      else if (key === "End") next = items.length - 1;
      else if (key === "ArrowDown") next = current < 0 ? 0 : (current + 1) % items.length;
      else next = current <= 0 ? items.length - 1 : current - 1;
      focusAt(next);
      return;
    }
    if ((key === "Enter" || key === " " || key === "Spacebar") && current >= 0) {
      event.preventDefault();
      // selectMode closes the picker and puts focus back on the waveform
      // button, so the keyboard user stays where the interaction started.
      selectMode(items[current].getAttribute("data-mode"), true);
    }
  });

  function syncIdentityAndState() {
    syncIdentity();
    renderWaveform(); renderItems();
  }

  win.addEventListener("click", function (event) {
    if (!menuOpen || !menu) return;
    // A real click on a control lands on an icon inside the button, not on the
    // button element itself. Comparing identity here closed the picker in the
    // same gesture that opened it, so the whole surface is the exclusion.
    if (menu.contains(event.target) ||
        waveform.contains(event.target) || event.target === waveform) return;
    closeMenu();
  });
  win.addEventListener("keydown", function (event) {
    if (menuOpen && event.key === "Escape") closeMenu(true);
  });
  // A new microphone run is a new turn authority. Starting one clears the
  // cancelled/revoked window left by the previous end, mute or cancel, while the
  // composer still refuses the previous run's tail by run identity (#4816).
  const micButton = doc.getElementById("voiceMicButton");
  if (micButton) micButton.addEventListener("click", resumeTurn);

  win.addEventListener("padiem:auth-state", syncIdentityAndState);
  win.addEventListener("padiem:voice-identity", syncIdentityAndState);
  win.addEventListener("padiem:localechange", syncIdentityAndState);
  // No composer-input listener is needed any more: which icons exist and what
  // they can do no longer depends on the text in the box (Owner 2026-10-31).
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
    // Owner 2026-10-31: the waveform is its own control, so there is no
    // "primary action" question to answer any more. `syncControls` re-reads
    // the account and voice availability; the composer may call it freely.
    syncControls: syncControls,
    isVoiceAvailable: voiceAvailable,
  };
  renderWaveform();
})(window, document);
