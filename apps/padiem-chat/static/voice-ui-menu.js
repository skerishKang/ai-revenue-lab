// #4816: unified voice mode toolbar for Chat(B62) and Claw(B54).
// Two icons only: microphone (M1 direct entry) and waveform picker (M2/M3/M4).
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

  let wave = null;
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
  function isTtsActive() { return currentMode === "live" && ttsOn === true; }
  function isCallActive() { return currentMode === "live" && callOn === true; }

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
      currentMode = "basic"; ttsOn = false; callOn = false;
      busySeen = false; outstandingKey = "";
    }
    if (typeof c.syncSessionGeneration === "function") {
      c.syncSessionGeneration(composerStatus().generation);
    }
  }

  function renderWaveform() {
    if (!wave) return;
    const c = controller ? controller.getState() : {};
    const on = currentMode === "live" && !c.invalidated && !c.cancelled && !!key();
    wave.setAttribute("aria-pressed", on ? "true" : "false");
    wave.setAttribute("data-voice-mode", currentMode);
    wave.disabled = !key() || !liveAPI || typeof liveAPI.create !== "function";
  }

  function escapeHtml(value) {
    return String(value || "")
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  function placeMenu() {
    if (!wave || !menu || !menuOpen) return;
    const rect = wave.getBoundingClientRect();
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
    wave.setAttribute("aria-expanded", "true");
    placeMenu();
    renderItems();
  }

  function closeMenu() {
    if (!menuOpen) return;
    menu.hidden = true;
    menuOpen = false;
    wave.setAttribute("aria-expanded", "false");
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
    if (m === "text") { currentMode = "live"; ttsOn = false; callOn = false; c.setMode("live"); }
    else if (m === "tts") { currentMode = "live"; ttsOn = true; callOn = false; c.setMode("live"); }
    else if (m === "call") { currentMode = "live"; ttsOn = false; callOn = true; c.setMode("live"); }
    renderWaveform(); renderItems();
    if (m === "call" && win.PadiemVoiceCall && typeof win.PadiemVoiceCall.show === "function") {
      win.PadiemVoiceCall.show();
    }
  }

  wave = doc.createElement("button");
  wave.type = "button";
  wave.id = "voiceWaveformButton";
  wave.className = "voice-waveform-button";
  wave.setAttribute("aria-label", pickerTitle());
  wave.setAttribute("data-locale-aria-label", "voice-mode");
  // Owner 2026-10-20: the hint uses the shared PADIEM chip tooltip.
  wave.setAttribute("data-padiem-tooltip", pickerTitle());
  wave.setAttribute("title", pickerTitle());
  wave.setAttribute("data-locale-title", "voice-mode");
  wave.setAttribute("aria-expanded", "false");
  wave.setAttribute("aria-haspopup", "menu");
  const svgNs = "http://www.w3.org/2000/svg";
  const svg = doc.createElementNS(svgNs, "svg");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("focusable", "false");
  svg.setAttribute("width", "20");
  svg.setAttribute("height", "20");
  svg.setAttribute("viewBox", "0 0 24 24");
  const path = doc.createElementNS(svgNs, "path");
  path.setAttribute("d", "M7 16v2a6 6 0 0 0 12 0v-2M12 20v1M7 10v2a4 4 0 0 0 8 0v-2M12 14v1M7 4v2a2 2 0 0 0 4 0v-2M12 8v1");
  path.setAttribute("stroke", "currentColor");
  path.setAttribute("stroke-width", "2.2");
  path.setAttribute("stroke-linecap", "round");
  path.setAttribute("stroke-linejoin", "round");
  path.setAttribute("fill", "none");
  svg.appendChild(path);
  wave.appendChild(svg);
  const srOnly = doc.createElement("span");
  srOnly.className = "sr-only";
  srOnly.textContent = pickerTitle();
  wave.appendChild(srOnly);
  const mic = doc.getElementById("voiceMicButton");
  if (mic && mic.parentNode === actions) actions.insertBefore(wave, mic.nextSibling);
  else actions.appendChild(wave);

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

  wave.addEventListener("click", function (event) {
    event.preventDefault();
    event.stopPropagation();
    if (wave.disabled) return;
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
    if (menuOpen && menu && !menu.contains(event.target) && event.target !== wave) closeMenu();
  });
  win.addEventListener("keydown", function (event) {
    if (menuOpen && event.key === "Escape") closeMenu();
  });
  win.addEventListener("padiem:auth-state", syncIdentityAndState);
  win.addEventListener("padiem:voice-identity", syncIdentityAndState);
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
    // The accepted turn may arrive while the microphone run is still open
    // (Mode 2/3/4 auto-send once per utterance) or right after it stopped.
    // The run authority is the generation/session pair, not the run state.
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
    selectMode: selectMode,
    closeMenu: closeMenu,
  };
  renderWaveform();
})(window, document);
