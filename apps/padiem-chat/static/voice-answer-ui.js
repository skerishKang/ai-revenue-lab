// #4816: answer listen/stop for M3 ("문자 + 음성 재생").
// Existing browser speechSynthesis only; explicit user click starts playback.
// Auto-speaks newly arrived answers only while M3 is the active mode.
//
// #5559: the answer used to carry two identical playback controls, one next to
// the product name and one in the answer action row. The action row is the one
// that stays, so this module owns the M3 auto-speech only. It marks the turn
// as speaking, and the single answer action can stop it.
(function (win, doc) {
  "use strict";
  const ttsAPI = win.PadiemVoiceTTSOutput;
  const menuAPI = win.PadiemVoiceMenu;
  const messages = doc.getElementById("messageList") || doc.body;
  if (!ttsAPI || typeof ttsAPI.create !== "function") return;

  let tts = null;
  let currentArticle = null;
  let pendingSpeech = [];
  let lastAutoText = "";
  // #4816 lifecycle token. Every stop/end/account change bumps it, so a speak
  // that was scheduled for a session that already ended is dropped instead of
  // starting later.
  let speakToken = 0;
  let knownIdentity = null;
  const ko = () => /^ko/i.test(doc.documentElement.lang || "ko");
  // Chat/Claw separation: the listen/stop/error copy comes from the existing locale
  // catalogue. The previous inline Korean literals were corrupted escape
  // sequences that rendered as "의식의발 통한" instead of a real label.
  function localeText(key, fallback) {
    try {
      if (win.__padiemLocale && typeof win.__padiemLocale.text === "function") {
        const value = win.__padiemLocale.text(key);
        if (value && value !== key) return value;
      }
    } catch (_) {}
    return fallback;
  }
  const errorText = () => localeText("voice-speech-unavailable", ko() ? "음성 재생 불가" : "Speech unavailable");

  function resetButton() {
    // The single answer action at the bottom of the answer owns the playback
    // control, so there is no second button to relabel here.
    if (currentArticle) currentArticle.dataset.ttsSpeaking = "false";
    currentArticle = null;
    pendingSpeech = [];
  }

  function speakText(text, article) {
    const parts = [];
    let left = String(text || "").trim();
    while (left) {
      if (left.length <= 1100) { parts.push(left); break; }
      let cut = left.lastIndexOf(" ", 1100);
      if (cut < 550) cut = 1100;
      parts.push(left.slice(0, cut).trim());
      left = left.slice(cut).trim();
    }
    if (!parts.length) return false;
    tts.start();
    pendingSpeech = parts.slice(1);
    if (article) {
      currentArticle = article;
      article.dataset.ttsSpeaking = "true";
    }
    return tts.speakText(parts[0]) !== false;
  }

  function autoSpeakAllowed() {
    return !!(menuAPI && typeof menuAPI.isTtsActive === "function" && menuAPI.isTtsActive());
  }

  function stopPlayback() {
    speakToken += 1;
    tts.stopOutput();
    resetButton();
  }

  function handleAnswer(article) {
    if (!article || article.nodeType !== 1) return;
    const content = article.querySelector(".assistant-content");
    const text = content ? (content.innerText || content.textContent || "").trim() : "";
    if (!autoSpeakAllowed() || !text || text === lastAutoText) return;
    lastAutoText = text;
    const token = speakToken;
    setTimeout(function () {
      // Fire-time authority: the session may have ended (call end, mute,
      // cancel, mode switch, account change) between the answer insert and this
      // task. Re-check both the token and the live mode before speaking.
      if (token !== speakToken || !autoSpeakAllowed()) return;
      speakText(text, article);
    }, 0);
  }

  if (win.MutationObserver) {
    new win.MutationObserver(function (changes) {
      changes.forEach(function (change) {
        if (change.type !== "childList") return;
        for (let i = 0; i < change.addedNodes.length; i += 1) {
          const node = change.addedNodes[i];
          if (node.nodeType !== 1) continue;
          if (node.classList && node.classList.contains("assistant-message")) {
            handleAnswer(node);
          } else if (typeof node.querySelectorAll === "function") {
            node.querySelectorAll(".assistant-message").forEach(handleAnswer);
          }
        }
      });
    }).observe(messages, {childList: true, subtree: true});
  }

  tts = ttsAPI.create({  // single shared instance; overrides placeholder above
    lang: "ko-KR",
    onEnd: function () {
      if (currentArticle && pendingSpeech.length) {
        const next = pendingSpeech.shift();
        if (!tts.speakText(next)) resetButton();
      } else resetButton();
    },
    onError: function () {
      if (currentArticle) currentArticle.dataset.ttsSpeaking = "false";
      pendingSpeech = [];
    }
  });
  // Re-attach any answers rendered before this module loaded.
  if (typeof messages.querySelectorAll === "function") {
    messages.querySelectorAll(".assistant-message").forEach(handleAnswer);
  }

  win.addEventListener("padiem:auth-state", function (event) {
    if (!event.detail || event.detail.authenticated !== true) stopPlayback();
  });
  // #4816 session boundaries: the voice session ended (call end, mute, mode
  // switch) or the signed-in identity changed. Late TTS belongs to a session
  // that no longer owns the answer.
  win.addEventListener("padiem:voice-end", stopPlayback);
  win.addEventListener("padiem:voice-identity", function (event) {
    const next = event && event.detail && event.detail.identityKey != null
      ? String(event.detail.identityKey) : "";
    if (knownIdentity !== null && next !== knownIdentity) stopPlayback();
    knownIdentity = next;
  });

  win.PadiemVoiceAnswer = {
    isSupported: tts.isSupported,
    speak: function (text) { return speakText(text, null); },
    stop: stopPlayback,
    getState: tts.getState ? tts.getState() : {supported: tts.isSupported()}
  };
})(window, document);
