// #4816: M4 "음성 통화" presentation layer over the shared turn state machine.
// Same conversation ID, model choice and account authority are preserved; no new
// conversation and no duplicate model request is created on view switch.
(function (win, doc) {
  "use strict";
  const menuAPI = win.PadiemVoiceMenu;
  const answerAPI = win.PadiemVoiceAnswer;
  const composerAPI = win.PadiemVoiceComposer;
  let panel = null;
  let stateChip = null;
  let transcript = null;

  function composerCtrl() {
    return composerAPI && composerAPI.getController ? composerAPI.getController() : null;
  }
  function isKo() { return /^ko/i.test(doc.documentElement.lang || "ko-KR"); }
  // Voice copy: the call copy comes from the existing locale catalogue. The
  // previous inline Korean literals were corrupted escape sequences that
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
  const STATE_LABEL_KEYS = Object.freeze({
    listening: "voice-call-listening",
    interim: "voice-call-transcribing",
    final: "voice-call-final",
    stopped: "voice-call-stopped",
    error: "voice-call-error",
    idle: "voice-call-idle",
  });
  function voiceLabel(state) {
    return localeText(STATE_LABEL_KEYS[state] || STATE_LABEL_KEYS.idle, isKo() ? "대기" : "Idle");
  }

  function refreshChip() {
    if (!stateChip) return;
    const c = composerCtrl();
    const st = c && c.getStatus ? c.getStatus() : {};
    stateChip.textContent = voiceLabel(st.voiceState || "idle");
    if (transcript && st.interim) transcript.textContent = st.interim;
  }

  function show() {
    if (panel) { panel.hidden = false; refreshChip(); return; }
    panel = doc.createElement("div");
    panel.id = "voiceCallPanel";
    panel.className = "voice-call-panel";
    panel.setAttribute("role", "dialog");
    panel.setAttribute("aria-modal", "true");
    panel.setAttribute("aria-label", localeText("voice-mode-call", isKo() ? "음성 통화" : "Voice call"));
    const stateEl = doc.createElement("div");
    stateEl.className = "voice-call-panel__state";
    stateEl.id = "voiceCallState";
    stateEl.textContent = voiceLabel("idle");
    panel.appendChild(stateEl);

    const muteBtn = doc.createElement("button");
    muteBtn.className = "voice-call-panel__btn";
    muteBtn.id = "voiceCallMute";
    muteBtn.type = "button";
    muteBtn.setAttribute("aria-pressed", "false");
    muteBtn.textContent = localeText("voice-call-mute", isKo() ? "음소거" : "Mute");
    panel.appendChild(muteBtn);

    const endBtn = doc.createElement("button");
    endBtn.className = "voice-call-panel__btn voice-call-panel__btn--end";
    endBtn.id = "voiceCallEnd";
    endBtn.type = "button";
    endBtn.textContent = localeText("voice-call-end", isKo() ? "통화 종료" : "End call");
    panel.appendChild(endBtn);

    const details = doc.createElement("details");
    details.className = "voice-call-panel__transcript open";
    const summary = doc.createElement("summary");
    summary.textContent = localeText("voice-call-transcript", isKo() ? "대화 내용 보기" : "View transcript");
    details.appendChild(summary);
    const transcriptDiv = doc.createElement("div");
    transcriptDiv.id = "voiceCallTranscript";
    transcriptDiv.setAttribute("aria-live", "polite");
    transcriptDiv.setAttribute("aria-atomic", "true");
    details.appendChild(transcriptDiv);
    panel.appendChild(details);
    doc.body.appendChild(panel);

    stateChip = doc.getElementById("voiceCallState");
    transcript = doc.getElementById("voiceCallTranscript");
    const mute = doc.getElementById("voiceCallMute");
    const endButton = doc.getElementById("voiceCallEnd");
    const mic = doc.getElementById("voiceMicButton");

    mute.addEventListener("click", function () {
      const c = composerCtrl();
      if (!c) return;
      const pressed = mute.getAttribute("aria-pressed") === "true";
      if (pressed) {
        // Unmute keeps the same conversation and audio session; it only opens
        // a fresh turn generation.
        if (menuAPI && typeof menuAPI.resumeTurn === "function") menuAPI.resumeTurn();
        c.start();
        mute.setAttribute("aria-pressed", "false");
        return;
      }
      // #4816: muting is a session boundary. Revoke the pending accepted turn
      // before the recognizer tail arrives, and stop M3 playback of an answer
      // that belongs to the muted session.
      if (menuAPI && typeof menuAPI.endTurn === "function") menuAPI.endTurn("muted");
      c.stop("user-muted");
      mute.setAttribute("aria-pressed", "true");
    });
    endButton.addEventListener("click", function () { hide(); });
    if (win.MutationObserver && mic) {
      new win.MutationObserver(refreshChip).observe(mic, {attributes: true, attributeFilter: ["data-voice-state", "aria-pressed"]});
    }
    panel.hidden = false;
    refreshChip();
    if (menuAPI && typeof menuAPI.setCallMode === "function") menuAPI.setCallMode(true);
    if (answerAPI && typeof answerAPI.stop === "function") answerAPI.stop();
  }

  function hide() {
    if (!panel) return;
    panel.hidden = true;
    // #4816: ending the call is a session boundary. Cancel the pending turn and
    // drop late STT/TTS before returning to the text conversation, which keeps
    // its existing conversation id and model choice.
    if (win.PadiemVoiceMenu && typeof win.PadiemVoiceMenu.endTurn === "function") {
      win.PadiemVoiceMenu.endTurn("call-ended");
    }
    const c = composerCtrl();
    if (c && typeof c.stop === "function") c.stop("call-ended");
    if (answerAPI && typeof answerAPI.stop === "function") answerAPI.stop();
    if (menuAPI && typeof menuAPI.setCallMode === "function") menuAPI.setCallMode(false);
    if (win.PadiemVoiceMenu && typeof win.PadiemVoiceMenu.closeMenu === "function") win.PadiemVoiceMenu.closeMenu();
  }

  win.PadiemVoiceCall = {show: show, hide: hide};
})(window, document);
