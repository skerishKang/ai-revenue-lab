// #4816: M4 "\uc758\uc2dd \ud1b5\ud55c" presentation layer over the shared turn state machine.
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
  function voiceLabel(state) {
    switch (state) {
      case "listening": return isKo() ? "\ud1b5\ud55c \ub4f1\ub85d\ubc1c\ubcf4" : "Listening";
      case "interim": return isKo() ? "\uc774\ud504\ub97c \ud480\uc774\ubcf4" : "Transcribing";
      case "final": return isKo() ? "\uc7ac\ucc38\ub41c \ubb3c\ud130" : "Final transcript";
      case "stopped": return isKo() ? "\ub4f1\ub85d\ubc1c\ubcf4" : "Stopped";
      case "error": return isKo() ? "\uc7ac\ub300" : "Error";
      default: return isKo() ? "\ub300\uae30\ub9ac" : "Idle";
    }
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
    panel.setAttribute("aria-label", isKo() ? "\uc758\uc2dd \ud1b5\ud55c" : "Voice call");
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
    muteBtn.textContent = isKo() ? "\uc788\uc6a9\uae08" : "Mute";
    panel.appendChild(muteBtn);

    const endBtn = doc.createElement("button");
    endBtn.className = "voice-call-panel__btn voice-call-panel__btn--end";
    endBtn.id = "voiceCallEnd";
    endBtn.type = "button";
    endBtn.textContent = isKo() ? "\ud1b5\ud55c \ubd88\ud130" : "End call";
    panel.appendChild(endBtn);

    const details = doc.createElement("details");
    details.className = "voice-call-panel__transcript open";
    const summary = doc.createElement("summary");
    summary.textContent = isKo() ? "\ub17c\ubb3c \ubcf8\uae30" : "View transcript";
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
      if (pressed) { c.start(); mute.setAttribute("aria-pressed", "false"); }
      else { c.stop("user-muted"); mute.setAttribute("aria-pressed", "true"); }
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
    const c = composerCtrl();
    if (c && typeof c.stop === "function") c.stop("call-ended");
    if (menuAPI && typeof menuAPI.setCallMode === "function") menuAPI.setCallMode(false);
    if (win.PadiemVoiceMenu && typeof win.PadiemVoiceMenu.closeMenu === "function") win.PadiemVoiceMenu.closeMenu();
  }

  win.PadiemVoiceCall = {show: show, hide: hide};
})(window, document);
