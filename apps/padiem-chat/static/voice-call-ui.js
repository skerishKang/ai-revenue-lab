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
  let historyEl = null;
  let interimEl = null;
  let timerEl = null;
  let timerHandle = null;
  let startedAtMs = 0;
  let turnStartIndex = 0;
  let listObserver = null;
  let historySignature = "";
  let pageHideBound = false;

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

  // #4816 M4-②: call elapsed time. Presentation only — the conversation, model
  // and account are untouched, and the ticker stops with the call.
  function formatElapsed(ms) {
    const total = Math.max(0, Math.floor(ms / 1000));
    return String(Math.floor(total / 60)).padStart(2, "0") + ":" +
      String(total % 60).padStart(2, "0");
  }
  function updateTimer() {
    if (timerEl) timerEl.textContent = formatElapsed(Date.now() - startedAtMs);
  }

  // #4816 M4-①: per-turn history. The conversation already lives in the page's
  // own message list, so this view re-reads it from the call's first turn
  // instead of keeping a second transcript store.
  function callMessages() {
    const list = doc.getElementById("messageList");
    if (!list) return [];
    const nodes = Array.prototype.slice.call(
      list.querySelectorAll("article.user-message, article.assistant-message"));
    return nodes.slice(turnStartIndex);
  }
  function messageRole(node) {
    if (node.classList.contains("user-message")) return "user";
    if (node.classList.contains("assistant-message")) return "assistant";
    return "";
  }
  function messageText(node) {
    const target = node.querySelector(".message-bubble") ||
      node.querySelector(".assistant-content") || node;
    return (target.textContent || "").replace(/\s+/g, " ").trim();
  }
  function renderHistory() {
    if (!historyEl) return;
    const entries = callMessages();
    const signature = entries.map(function (node) {
      return messageRole(node) + "|" + messageText(node);
    }).join("\n");
    if (signature === historySignature) return;
    historySignature = signature;
    const rows = [];
    entries.forEach(function (node) {
      const role = messageRole(node);
      const text = messageText(node);
      if (!role || !text) return;
      const row = doc.createElement("div");
      row.className = "voice-call-turn voice-call-turn--" + role;
      const who = doc.createElement("span");
      who.className = "voice-call-turn__role";
      who.textContent = role === "user"
        ? localeText("voice-call-role-user", isKo() ? "사용자" : "You")
        : localeText("voice-call-role-assistant", "AI");
      const what = doc.createElement("span");
      what.className = "voice-call-turn__text";
      what.textContent = text;
      row.appendChild(who);
      row.appendChild(what);
      rows.push(row);
    });
    historyEl.replaceChildren.apply(historyEl, rows);
  }

  function beginSession() {
    startedAtMs = Date.now();
    updateTimer();
    if (timerHandle) win.clearInterval(timerHandle);
    timerHandle = win.setInterval(updateTimer, 1000);
    const list = doc.getElementById("messageList");
    turnStartIndex = list
      ? list.querySelectorAll("article.user-message, article.assistant-message").length : 0;
    historySignature = "";
    renderHistory();
    if (list && win.MutationObserver && !listObserver) {
      // New turns and streamed answer text both land in this list, so the view
      // re-reads it rather than copying anything out of the conversation.
      listObserver = new win.MutationObserver(renderHistory);
      listObserver.observe(list, {childList: true, subtree: true, characterData: true});
    }
    bindPageHide();
  }
  function endSession() {
    if (timerHandle) { win.clearInterval(timerHandle); timerHandle = null; }
    if (listObserver) { listObserver.disconnect(); listObserver = null; }
  }
  // #4816 M4-③: closing or reloading the tab ends the call through the same
  // session boundary as the end button, so no late STT/TTS or auto-send
  // survives the page going away.
  function bindPageHide() {
    if (pageHideBound) return;
    pageHideBound = true;
    win.addEventListener("pagehide", function () {
      if (!panel || panel.hidden) return;
      hide();
    });
  }

  function refreshChip() {
    if (!stateChip) return;
    const c = composerCtrl();
    const st = c && c.getStatus ? c.getStatus() : {};
    stateChip.textContent = voiceLabel(st.voiceState || "idle");
    if (interimEl) interimEl.textContent = st.interim || "";
  }

  function show() {
    if (panel) {
      panel.hidden = false;
      refreshChip();
      // Re-entering the call screen starts a new elapsed-time count and a new
      // first-turn marker; the conversation itself is never re-created.
      beginSession();
      if (menuAPI && typeof menuAPI.setCallMode === "function") menuAPI.setCallMode(true);
      if (answerAPI && typeof answerAPI.stop === "function") answerAPI.stop();
      return;
    }
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

    // #4816 M4-②: elapsed call time. role="timer" is silent unless asked for,
    // so a one-second tick cannot fight the answer being read aloud.
    const timer = doc.createElement("div");
    timer.className = "voice-call-panel__timer";
    timer.id = "voiceCallTimer";
    timer.setAttribute("role", "timer");
    timer.setAttribute("aria-live", "off");
    timer.setAttribute("aria-label", localeText("voice-call-duration", isKo() ? "통화 시간" : "Call time"));
    timer.textContent = "00:00";
    panel.appendChild(timer);

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
    transcriptDiv.setAttribute("aria-atomic", "false");
    // #4816 M4-①: the turn-by-turn history re-read from the conversation, then
    // the live interim line underneath it.
    const historyStack = doc.createElement("div");
    historyStack.id = "voiceCallHistory";
    historyStack.className = "voice-call-history";
    transcriptDiv.appendChild(historyStack);
    const interim = doc.createElement("p");
    interim.id = "voiceCallInterim";
    interim.className = "voice-call-interim";
    transcriptDiv.appendChild(interim);
    details.appendChild(transcriptDiv);
    panel.appendChild(details);
    doc.body.appendChild(panel);

    stateChip = doc.getElementById("voiceCallState");
    transcript = doc.getElementById("voiceCallTranscript");
    historyEl = doc.getElementById("voiceCallHistory");
    interimEl = doc.getElementById("voiceCallInterim");
    timerEl = doc.getElementById("voiceCallTimer");
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
    beginSession();
    if (menuAPI && typeof menuAPI.setCallMode === "function") menuAPI.setCallMode(true);
    if (answerAPI && typeof answerAPI.stop === "function") answerAPI.stop();
  }

  function hide() {
    if (!panel) return;
    panel.hidden = true;
    endSession();
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
