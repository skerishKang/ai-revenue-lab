// Unified browser UI: opt-in Mode 2 turn submission and click-to-play answer TTS.
// Reuses the existing authenticated composer form; never initiates a provider call.
(function (win, doc) {
  "use strict";
  const form = doc.getElementById("composerForm");
  const input = doc.getElementById("messageInput");
  const send = doc.getElementById("sendButton");
  const actions = form && form.querySelector(".composer-actions");
  const messages = doc.getElementById("messageList");
  if (!form || !input || !send || !actions) return;
  const liveAPI = win.PadiemVoiceLiveTurnController;
  const ttsAPI = win.PadiemVoiceTTSOutput;
  const composerAPI = win.PadiemVoiceComposer;
  const ko = () => /^ko/i.test(doc.documentElement.lang || "ko");
  const modeText = (on) => ko()
    ? (on ? "\uC74C\uC131 \uC790\uB3D9 \uBCF4\uB0B4\uAE30: \uCF1C\uC9D0" : "\uC74C\uC131 \uC790\uB3D9 \uBCF4\uB0B4\uAE30: \uAEBC\uC9D0")
    : (on ? "Voice auto-send: ON" : "Voice auto-send: OFF");
  const playText = () => ko() ? "\uC74C\uC131\uC73C\uB85C \uB4E3\uAE30" : "Listen";
  const stopText = () => ko() ? "\uC74C\uC131 \uC815\uC9C0" : "Stop audio";
  const errorText = () => ko() ? "\uC74C\uC131 \uC7AC\uC0DD \uBD88\uAC00" : "Speech unavailable";
  function composerStatus() {
    const controller = composerAPI && composerAPI.getController && composerAPI.getController();
    return controller && controller.getStatus ? controller.getStatus() : {};
  }
  function key() {
    const status = composerStatus();
    return status.authenticated === true && status.authKnown === true
      ? String(status.identityKey || "") : "";
  }

  let mode2 = null;
  let toggle = null;
  let busySeen = false;
  let outstandingKey = "";
  if (liveAPI && typeof liveAPI.create === "function") {
    mode2 = liveAPI.create({
      accountKey: key(),
      getAccountKey: key,
      getInFlight: () => input.disabled === true,
      getCanSubmit: () => input.disabled !== true && send.disabled !== true &&
        input.value.trim().length > 0,
      // The canonical voice composer has already committed the accepted final.
      // Never inject another copy or overwrite user input.
      commitText: (text) => input.value.trim() === text.trim(),
      submit: () => {
        form.requestSubmit();
        return true;
      }
    });
    toggle = doc.createElement("button");
    toggle.id = "voiceAutoSendToggle";
    toggle.type = "button";
    toggle.className = "voice-mode2-toggle";
    toggle.setAttribute("aria-pressed", "false");
    toggle.setAttribute("aria-label", modeText(false));
    const mic = doc.getElementById("voiceMicButton");
    if (mic && mic.parentNode === actions) actions.insertBefore(toggle, mic.nextSibling);
    else actions.appendChild(toggle);

    function syncIdentity() {
      const current = key();
      if (mode2.getState().accountKey !== current) {
        mode2.setAccountKey(current);
        mode2.setMode("basic");
        busySeen = false;
        outstandingKey = "";
      }
    }
    function render() {
      syncIdentity();
      const st = mode2.getState();
      const on = st.mode === "live" && !st.invalidated && !st.cancelled;
      toggle.textContent = modeText(on);
      toggle.setAttribute("aria-label", modeText(on));
      toggle.setAttribute("aria-pressed", on ? "true" : "false");
      const c = composerStatus();
      toggle.disabled = !key() || c.availability !== "ready" || c.active === true;
    }
    toggle.addEventListener("click", function () {
      syncIdentity();
      if (toggle.disabled) return;
      const enable = mode2.getState().mode !== "live";
      mode2.setMode(enable ? "live" : "basic");
      if (enable) mode2.reset();
      busySeen = false;
      outstandingKey = "";
      render();
    });
    input.addEventListener("compositionstart", () => mode2.setCompositionActive(true));
    input.addEventListener("compositionend", () => mode2.endComposition());
    win.addEventListener("padiem:auth-state", () => render());

    if (mic && win.MutationObserver) {
      new win.MutationObserver(() => render()).observe(mic, {
        attributes: true, attributeFilter: ["disabled", "aria-pressed", "data-voice-state"]
      });
    }
    win.addEventListener("padiem:voice-accepted-turn", function (event) {
      const info = event && event.detail;
      if (!info || !mode2 || !key()) return;
      syncIdentity();
      const c = composerStatus();
      if (c.active || c.generation !== info.composerGeneration ||
          c.sessionToken !== info.sessionToken || info.accountKey !== key() ||
          info.accepted !== true || info.endOfTurn !== true) return;
      const st = mode2.getState();
      const result = mode2.handleFinal({
        accepted: true, endOfTurn: true,
        accountKey: info.accountKey, sessionGeneration: st.sessionGeneration,
        finalId: info.finalId, text: info.text
      });
      if (result.submitted) {
        busySeen = input.disabled === true;
        outstandingKey = result.finalKey;
      }
      render();
    });
    if (win.MutationObserver) {
      new win.MutationObserver(() => {
        if (!outstandingKey) return;
        if (input.disabled) busySeen = true;
        else if (busySeen) {
          mode2.markAnswerSettled({accountKey: key(), finalKey: outstandingKey});
          outstandingKey = "";
          busySeen = false;
        }
      }).observe(input, {attributes: true, attributeFilter: ["disabled"]});
    }
    win.PadiemVoiceMode2UI = {
      isLiveActive: () => {
        if (!mode2) return false;
        const s = mode2.getState();
        return s.mode === "live" && !s.cancelled && !s.invalidated &&
          !!key() && s.accountKey === key() && composerStatus().active === true;
      },
      getState: () => mode2.getState()
    };
    render();
  }

  if (!messages || !ttsAPI || typeof ttsAPI.create !== "function") return;
  let currentButton = null;
  let pendingSpeech = [];
  function restorePlayButton() {
    if (currentButton) {
      currentButton.textContent = playText();
      currentButton.setAttribute("aria-label", playText());
      currentButton.setAttribute("aria-pressed", "false");
    }
    currentButton = null;
    pendingSpeech = [];
  }
  const tts = ttsAPI.create({
    lang: "ko-KR",
    onEnd: () => {
      if (currentButton && pendingSpeech.length) {
        const next = pendingSpeech.shift();
        if (!tts.speakText(next)) restorePlayButton();
      } else restorePlayButton();
    },
    onError: () => {
      if (currentButton) currentButton.textContent = errorText();
      pendingSpeech = [];
    }
  });
  function splitSpeech(text) {
    const parts = [];
    let left = String(text || "").trim();
    while (left) {
      if (left.length <= 1100) { parts.push(left); break; }
      let cut = left.lastIndexOf(" ", 1100);
      if (cut < 550) cut = 1100;
      parts.push(left.slice(0, cut).trim());
      left = left.slice(cut).trim();
    }
    return parts;
  }
  function wireAnswerButtons() {
    messages.querySelectorAll(".assistant-message").forEach(function (article) {
      if (article.querySelector(".voice-answer-listen")) return;
      const content = article.querySelector(".assistant-content");
      if (!content) return;
      const meta = article.querySelector(".assistant-meta") || content.parentNode;
      if (!meta) return;
      const b = doc.createElement("button");
      b.type = "button";
      b.className = "voice-answer-listen";
      b.setAttribute("aria-label", playText());
      b.setAttribute("aria-pressed", "false");
      b.textContent = playText();
      b.disabled = !tts.isSupported();
      meta.appendChild(b);
      b.addEventListener("click", function () {
        if (currentButton === b) {
          tts.stopOutput(); restorePlayButton(); return;
        }
        tts.cancel(); restorePlayButton();
        const parts = splitSpeech(content.innerText || content.textContent || "");
        if (!parts.length) return;
        currentButton = b;
        pendingSpeech = parts.slice(1);
        b.setAttribute("aria-pressed", "true");
        b.setAttribute("aria-label", stopText());
        b.textContent = stopText();
        tts.start(); // explicit user click only; no autoplay
        if (!tts.speakText(parts[0])) restorePlayButton();
      });
    });
  }
  wireAnswerButtons();
  if (win.MutationObserver) {
    new win.MutationObserver((changes) => {
      if (changes.some(change => change.type === "childList")) wireAnswerButtons();
    }).observe(messages, {childList: true, subtree: true});
  }
  win.addEventListener("padiem:auth-state", function (e) {
    if (!e.detail || e.detail.authenticated !== true) {
      tts.stopOutput(); restorePlayButton();
    }
  });
  win.PadiemVoiceAnswerUI = {isSupported: () => tts.isSupported()};
})(window, document);
