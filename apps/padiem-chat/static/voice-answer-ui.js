// #4816: answer listen/stop for M3 ("\ub3d9\uc758 + \uc758\uc2dd \ud5c8\ub3d9").
// Existing browser speechSynthesis only; explicit user click starts playback.
// Auto-speaks newly arrived answers only while M3 is the active mode.
(function (win, doc) {
  "use strict";
  const ttsAPI = win.PadiemVoiceTTSOutput;
  const menuAPI = win.PadiemVoiceMenu;
  const messages = doc.getElementById("messageList") || doc.body;
  if (!ttsAPI || typeof ttsAPI.create !== "function") return;

  let tts = null;
  let currentButton = null;
  let pendingSpeech = [];
  let lastAutoText = "";
  const ko = () => /^ko/i.test(doc.documentElement.lang || "ko");
  const playText = () => ko() ? "\uc758\uc2dd\uc758\ubc1c \ud1b5\ud55c" : "Listen";
  const stopText = () => ko() ? "\uc758\uc2dd \uc815\ubcf4" : "Stop audio";
  const errorText = () => ko() ? "\uc758\uc2dd \uc7ac\ub300 \ubd88\uac00" : "Speech unavailable";

  function resetButton() {
    if (currentButton) {
      currentButton.textContent = playText();
      currentButton.setAttribute("aria-label", playText());
      currentButton.setAttribute("aria-pressed", "false");
    }
    currentButton = null;
    pendingSpeech = [];
  }

  function speakText(text) {
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
    return tts.speakText(parts[0]) !== false;
  }

  function attach(article) {
    if (article.querySelector(".voice-answer-listen")) return;
    const content = article.querySelector(".assistant-content");
    if (!content) return;
    const meta = article.querySelector(".assistant-meta") || content.parentNode;
    if (!meta) return;
    const b = doc.createElement("button");
    b.type = "button";
    b.className = "voice-answer-listen";
    b.setAttribute("aria-label", playText());
    window.PadiemSharedTooltip?.label?.(b, playText());
    b.setAttribute("aria-pressed", "false");
    b.textContent = playText();
    b.disabled = !tts.isSupported();
    b.addEventListener("click", function () {
      if (currentButton === b) { tts.stopOutput(); resetButton(); return; }
      tts.cancel(); resetButton();
      const text = content.innerText || content.textContent || "";
      if (!text) return;
      currentButton = b;
      b.setAttribute("aria-pressed", "true");
      b.setAttribute("aria-label", stopText());
      window.PadiemSharedTooltip?.label?.(b, stopText());
      b.textContent = stopText();
      speakText(text);
    });
    meta.appendChild(b);
  }

  function handleAnswer(article) {
    if (!article || article.nodeType !== 1) return;
    attach(article);
    const content = article.querySelector(".assistant-content");
    const text = content ? (content.innerText || content.textContent || "").trim() : "";
    if (menuAPI && typeof menuAPI.isTtsActive === "function" && menuAPI.isTtsActive() &&
        text && text !== lastAutoText) {
      lastAutoText = text;
      setTimeout(function () { speakText(text); }, 0);
    }
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
      if (currentButton && pendingSpeech.length) {
        const next = pendingSpeech.shift();
        if (!tts.speakText(next)) resetButton();
      } else resetButton();
    },
    onError: function () {
      if (currentButton) currentButton.textContent = errorText();
      pendingSpeech = [];
    }
  });
  // Re-attach any answers rendered before this module loaded.
  if (typeof messages.querySelectorAll === "function") {
    messages.querySelectorAll(".assistant-message").forEach(handleAnswer);
  }

  win.addEventListener("padiem:auth-state", function (event) {
    if (!event.detail || event.detail.authenticated !== true) {
      tts.stopOutput(); resetButton();
    }
  });

  win.PadiemVoiceAnswer = {
    isSupported: tts.isSupported,
    speak: speakText,
    stop: function () { tts.stopOutput(); resetButton(); },
    getState: tts.getState ? tts.getState() : {supported: tts.isSupported()}
  };
})(window, document);
