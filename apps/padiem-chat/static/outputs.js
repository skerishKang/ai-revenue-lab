(() => {
  "use strict";

  const outputsNavButton = document.getElementById("outputsNavButton");
  const outputsBadge = document.getElementById("outputsBadge");
  const outputsSection = document.getElementById("outputsSection");
  const outputsList = document.getElementById("outputsList");
  const outputsEmpty = document.getElementById("outputsEmpty");
  const outputDialog = document.getElementById("savedOutputDialog");
  const outputDialogClose = document.getElementById("savedOutputClose");
  const outputTitleInput = document.getElementById("savedOutputTitleInput");
  const outputContent = document.getElementById("savedOutputContent");
  const outputStatus = document.getElementById("savedOutputStatus");
  const outputCopyButton = document.getElementById("savedOutputCopy");
  const outputDownloadButton = document.getElementById("savedOutputDownload");
  const outputRenameButton = document.getElementById("savedOutputRename");
  const outputDeleteButton = document.getElementById("savedOutputDelete");
  const messageList = document.getElementById("messageList");
  const loginButton = document.getElementById("loginButton");

  if (!outputDialog || !messageList) return;
  // #4462: the sidebar saved-answers button/section are removed from the
  // visible IA. Every sidebar touch below is optional so the saved-answer
  // data, dialog, per-answer save buttons and /api/outputs contract keep
  // working without a sidebar list surface.

  let outputsReady = false;
  let outputs = [];
  let activeOutput = null;
  let loadInFlight = false;
  let lastAuthenticated = false;

  function setStatus(text, state = "normal") {
    outputStatus.textContent = text || "";
    outputStatus.dataset.state = state;
  }

  function titleFromText(text) {
    const firstLine = String(text || "").split(/\r?\n/, 1)[0].replace(/\s+/g, " ").trim();
    return (firstLine || "저장한 답변").slice(0, 100);
  }

  function safeFilename(title) {
    const cleaned = String(title || "Padiem Chat 답변")
      .replace(/[\\/:*?"<>|\u0000-\u001f]/g, " ")
      .replace(/\s+/g, " ")
      .trim()
      .slice(0, 80);
    return `${cleaned || "Padiem Chat 답변"}.txt`;
  }

  async function copyText(text) {
    if (navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
      try {
        await navigator.clipboard.writeText(text);
        return true;
      } catch (_) {}
    }
    const textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.setAttribute("readonly", "");
    textarea.style.position = "fixed";
    textarea.style.left = "-9999px";
    document.body.appendChild(textarea);
    textarea.select();
    let copied = false;
    try {
      copied = typeof document.execCommand === "function" && document.execCommand("copy") === true;
    } catch (_) {
      copied = false;
    }
    textarea.remove();
    return copied;
  }

  function downloadText(text, title) {
    const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = safeFilename(title);
    anchor.hidden = true;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
  }

  function lifecycleApi() {
    return window.PadiemChatLifecycle || { isCompleted() { return false; } };
  }

  function removeAnswerActions(article) {
    stopArticleTts(article);
    article.querySelectorAll(".answer-actions").forEach((actions) => actions.remove());
    delete article.dataset.outputActions;
  }

  function updateSaveButtons() {
    // #4462: the saved-answers list surface is removed, so the per-answer
    // save entry stays hidden — saving would be write-only with no retrieval
    // path. Copy/download stay visible; saved data, the dialog and the
    // /api/outputs contract are preserved untouched.
    document.querySelectorAll(".answer-save").forEach((button) => {
      button.hidden = true;
      button.disabled = true;
    });
  }

  function disableOutputs() {
    outputsReady = false;
    outputs = [];
    if (outputsNavButton) {
      outputsNavButton.hidden = true;
      outputsNavButton.disabled = true;
      outputsNavButton.setAttribute("aria-disabled", "true");
    }
    if (outputsBadge) outputsBadge.textContent = "로그인 후";
    if (outputsSection) outputsSection.hidden = true;
    if (outputsList) outputsList.replaceChildren();
    if (outputsEmpty) outputsEmpty.hidden = true;
    updateSaveButtons();
    if (outputDialog.open) outputDialog.close();
    activeOutput = null;
  }

  function renderOutputs() {
    if (outputsList) outputsList.replaceChildren();
    if (outputsSection) outputsSection.hidden = false;
    if (outputsEmpty) outputsEmpty.hidden = outputs.length !== 0;
    if (!outputsList) {
      if (outputsBadge) outputsBadge.textContent = outputs.length ? String(outputs.length) : "비어 있음";
      return;
    }
    outputs.forEach((item) => {
      if (!item || typeof item.id !== "string" || typeof item.title !== "string") return;
      const button = document.createElement("button");
      button.type = "button";
      button.className = "recent-item output-item";
      button.dataset.outputId = item.id;
      button.textContent = item.title;
      button.setAttribute("aria-current", activeOutput && activeOutput.id === item.id ? "true" : "false");
      button.addEventListener("click", () => openOutput(item.id));
      outputsList.appendChild(button);
    });
    if (outputsBadge) outputsBadge.textContent = outputs.length ? String(outputs.length) : "비어 있음";
  }

  async function loadOutputs() {
    if (loadInFlight) return outputsReady;
    loadInFlight = true;
    try {
      const response = await fetch("/api/outputs", { headers: { "Accept": "application/json" }, cache: "no-store" });
      const data = await response.json().catch(() => null);
      if (!response.ok || !data || !Array.isArray(data.outputs)) throw new Error("saved outputs unavailable");
      outputs = data.outputs.filter((item) => item && typeof item.id === "string" && typeof item.title === "string");
      outputsReady = true;
      if (outputsNavButton) {
        outputsNavButton.hidden = false;
        outputsNavButton.disabled = false;
        outputsNavButton.setAttribute("aria-disabled", "false");
      }
      renderOutputs();
      updateSaveButtons();
      return true;
    } catch (_) {
      disableOutputs();
      return false;
    } finally {
      loadInFlight = false;
    }
  }

  function answerText(article) {
    const content = article.querySelector(".assistant-content");
    if (!content || content.querySelector(".typing") || content.querySelector(".error-box")) return "";
    const paragraph = Array.from(content.children).find((node) => node.tagName === "P");
    return paragraph && typeof paragraph.textContent === "string" ? paragraph.textContent.trim() : "";
  }

  function localeText(key, fallback) {
    try {
      if (window.__padiemLocale && typeof window.__padiemLocale.text === "function") {
        const value = window.__padiemLocale.text(key);
        if (value && value !== key) return value;
      }
    } catch (_) {}
    return fallback;
  }

  function feedbackButton(button, successText, originalText) {
    button.textContent = successText;
    window.setTimeout(() => {
      if (button.isConnected && button.dataset.saved !== "true") button.textContent = originalText;
    }, 1200);
  }

  function flashTitle(button, key, fallback) {
    const original = button.title;
    button.title = localeText(key, fallback);
    window.setTimeout(() => {
      if (button.isConnected) button.title = original;
    }, 1200);
  }

  function iconButton(cls, glyph, labelKey, labelFallback) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = cls;
    const label = localeText(labelKey, labelFallback);
    button.setAttribute("aria-label", label);
    button.title = label;
    button.dataset.localeAriaLabel = labelKey;
    button.dataset.localeTitle = labelKey;
    const icon = document.createElement("span");
    icon.className = "answer-action-glyph";
    icon.setAttribute("aria-hidden", "true");
    icon.textContent = glyph;
    button.appendChild(icon);
    return button;
  }

  function regenerateApi() {
    const hook = window.PadiemChatRegenerate;
    return hook && typeof hook.regenerate === "function" ? hook : null;
  }

  function ttsApi() {
    const lib = window.PadiemVoiceTTSOutput;
    if (!lib || typeof lib.create !== "function" || typeof lib.supported !== "function") return null;
    try {
      return lib.supported() ? lib : null;
    } catch (_) {
      return null;
    }
  }

  function shareAvailable() {
    try {
      if (typeof navigator !== "undefined" && typeof navigator.share === "function") return true;
      if (typeof navigator !== "undefined" && navigator.clipboard && typeof navigator.clipboard.writeText === "function") return true;
    } catch (_) {}
    return false;
  }

  function stopArticleTts(article) {
    const waiting = article && article._ttsWaiting ? article._ttsWaiting : null;
    if (waiting) {
      waiting.active = false;
      clearTimeout(waiting.timer);
      try { window.speechSynthesis.removeEventListener("voiceschanged", waiting.onVoices); } catch (_) {}
      article._ttsWaiting = null;
    }
    const player = article && article._ttsPlayer ? article._ttsPlayer : null;
    if (player) {
      try { player.stopOutput(); } catch (_) {}
      article._ttsPlayer = null;
    }
    const button = article ? article.querySelector(".answer-action.answer-listen") : null;
    if (button) {
      button.setAttribute("aria-pressed", "false");
      const label = localeText("answer-listen", "음성 듣기");
      button.setAttribute("aria-label", label);
      button.title = label;
    }
  }

  function toggleArticleTts(article, button, text) {
    if (article._ttsPlayer) {
      stopArticleTts(article);
      return;
    }
    const lib = ttsApi();
    if (!lib) return;
    const lang = (document.documentElement.lang || "ko").toLowerCase().startsWith("en") ? "en-US" : "ko-KR";
    const player = lib.create({
      lang,
      onEnd: () => stopArticleTts(article),
      onError: () => stopArticleTts(article),
    });
    article._ttsPlayer = player;
    // A native user click is mandatory; voice-list readiness must not trigger
    // speech unless the same explicit request is still active.
    player.start();
    function matchingVoiceReady() {
      try {
        return player.availableVoices().some((voice) =>
          voice && String(voice.lang || "").toLowerCase().split("-")[0] === lang.toLowerCase().split("-")[0]);
      } catch (_) { return false; }
    }
    function playWhenReady() {
      if (article._ttsPlayer !== player) return;
      if (!player.speakText(text)) {
        stopArticleTts(article);
        flashTitle(button, "answer-listen", "?? ?? ??");
        return;
      }
      const label = localeText("answer-listen-stop", "?? ??");
      button.setAttribute("aria-pressed", "true");
      button.setAttribute("aria-label", label);
      button.title = label;
    }
    if (matchingVoiceReady()) {
      playWhenReady();
      return;
    }
    // Chromium/Edge often populate getVoices() asynchronously after load.
    // Retry the explicit click at most once when voiceschanged arrives. The
    // pending request can always be cancelled by pressing the same button.
    const synth = window.speechSynthesis;
    if (!synth || typeof synth.addEventListener !== "function") {
      stopArticleTts(article);
      flashTitle(button, "answer-listen", "?? ?? ??");
      return;
    }
    const wait = {active: true, timer: null, onVoices: null};
    article._ttsWaiting = wait;
    function clearWait() {
      if (!wait.active) return false;
      wait.active = false;
      clearTimeout(wait.timer);
      try { synth.removeEventListener("voiceschanged", wait.onVoices); } catch (_) {}
      if (article._ttsWaiting === wait) article._ttsWaiting = null;
      return article._ttsPlayer === player;
    }
    wait.onVoices = () => {
      if (!wait.active || !matchingVoiceReady()) return;
      if (clearWait()) playWhenReady();
    };
    synth.addEventListener("voiceschanged", wait.onVoices);
    wait.timer = setTimeout(() => {
      if (clearWait()) {
        stopArticleTts(article);
        flashTitle(button, "answer-listen", "?? ?? ??");
      }
    }, 3000);
    button.setAttribute("aria-pressed", "false");
    button.setAttribute("aria-label", "?? ?? ?, ?? ??? ??");
    button.title = "?? ?? ?, ?? ??? ??";
    // Close the race in which getVoices() becomes populated immediately
    // before the voiceschanged handler was attached.
    wait.onVoices();
  }

  async function shareArticleText(button, text, title) {
    try {
      if (typeof navigator !== "undefined" && typeof navigator.share === "function") {
        await navigator.share({ title, text });
        flashTitle(button, "answer-shared", "공유했습니다");
        return;
      }
    } catch (error) {
      if (error && error.name === "AbortError") return;
    }
    const copied = await copyText(text);
    flashTitle(button, copied ? "copied" : "copy-failed", copied ? "복사됨" : "복사 실패");
  }

  function enhanceAssistantMessage(article) {
    if (!(article instanceof Element)) return;
    if (!lifecycleApi().isCompleted(article)) {
      removeAnswerActions(article);
      return;
    }
    if (article.dataset.outputActions === "true") return;
    const text = answerText(article);
    if (!text) return;
    const body = article.querySelector(".assistant-body");
    if (!body) return;

    const actions = document.createElement("div");
    actions.className = "answer-actions";
    actions.setAttribute("aria-label", localeText("answer-actions", "답변 작업"));

    // Exactly five functions in Glass icon style. No rating controls.
    // A button is rendered only when its capability actually exists.
    const copy = iconButton("answer-action answer-copy", "⧉", "answer-copy", "복사");
    copy.addEventListener("click", async () => {
      if (!lifecycleApi().isCompleted(article)) return;
      const copied = await copyText(text);
      flashTitle(copy, copied ? "copied" : "copy-failed", copied ? "복사됨" : "복사 실패");
    });
    actions.appendChild(copy);

    const regen = regenerateApi();
    if (regen) {
      const again = iconButton("answer-action answer-regenerate", "↻", "answer-regenerate", "다시 생성");
      again.addEventListener("click", () => {
        if (!lifecycleApi().isCompleted(article)) return;
        if (!regen.regenerate(article)) {
          flashTitle(again, "answer-regenerating", "답변 생성 중");
        }
      });
      actions.appendChild(again);
    }

    if (ttsApi()) {
      const listen = iconButton("answer-action answer-listen", "♪", "answer-listen", "음성 듣기");
      listen.setAttribute("aria-pressed", "false");
      listen.addEventListener("click", () => {
        if (!lifecycleApi().isCompleted(article)) return;
        toggleArticleTts(article, listen, text);
      });
      actions.appendChild(listen);
    }

    if (shareAvailable()) {
      const share = iconButton("answer-action answer-share", "↗", "answer-share", "공유");
      share.addEventListener("click", () => {
        if (!lifecycleApi().isCompleted(article)) return;
        void shareArticleText(share, text, titleFromText(text));
      });
      actions.appendChild(share);
    }

    const more = iconButton("answer-action answer-more", "···", "answer-more", "기타");
    more.setAttribute("aria-expanded", "false");
    const moreMenu = document.createElement("span");
    moreMenu.className = "answer-more-menu";
    moreMenu.hidden = true;
    const download = document.createElement("button");
    download.type = "button";
    download.className = "answer-action answer-download";
    download.textContent = localeText("answer-txt-download", "TXT 다운로드");
    download.dataset.localeKey = "answer-txt-download";
    download.addEventListener("click", () => {
      if (lifecycleApi().isCompleted(article)) downloadText(text, titleFromText(text));
    });
    moreMenu.appendChild(download);
    more.addEventListener("click", () => {
      moreMenu.hidden = !moreMenu.hidden;
      more.setAttribute("aria-expanded", moreMenu.hidden ? "false" : "true");
    });
    actions.append(more, moreMenu);

    const save = document.createElement("button");
    save.type = "button";
    save.className = "answer-action answer-save";
    save.textContent = "저장";
    save.hidden = true;
    save.disabled = true;
    save.addEventListener("click", async () => {
      if (!lifecycleApi().isCompleted(article) || !outputsReady || save.dataset.saved === "true") return;
      save.disabled = true;
      try {
        const response = await fetch("/api/outputs", {
          method: "POST",
          headers: { "Content-Type": "application/json", "Accept": "application/json" },
          body: JSON.stringify({ title: titleFromText(text), content: text }),
        });
        const data = await response.json().catch(() => null);
        if (!response.ok || !data || !data.output) {
          const message = data && data.error && typeof data.error.message === "string" ? data.error.message : "답변을 저장하지 못했습니다.";
          throw new Error(message);
        }
        save.dataset.saved = "true";
        save.textContent = "저장됨";
        save.disabled = true;
        await loadOutputs();
      } catch (_) {
        save.disabled = false;
        feedbackButton(save, "저장 실패", "저장");
      }
    });

    actions.appendChild(save);
    body.appendChild(actions);
    article.dataset.outputActions = "true";
  }

  function enhanceAllAnswers() {
    messageList.querySelectorAll(".assistant-message").forEach(enhanceAssistantMessage);
  }

  async function openOutput(id) {
    if (!outputsReady) return;
    try {
      const response = await fetch(`/api/outputs/${encodeURIComponent(id)}`, { headers: { "Accept": "application/json" }, cache: "no-store" });
      const data = await response.json().catch(() => null);
      if (!response.ok || !data || !data.output || typeof data.output.content !== "string") throw new Error("저장한 답변을 불러오지 못했습니다.");
      activeOutput = data.output;
      outputTitleInput.value = typeof activeOutput.title === "string" ? activeOutput.title : "저장한 답변";
      outputContent.textContent = activeOutput.content;
      setStatus("");
      renderOutputs();
      outputDialog.showModal();
      outputTitleInput.focus();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "저장한 답변을 불러오지 못했습니다.", "error");
    }
  }

  function closeOutput() {
    if (outputDialog.open) outputDialog.close();
    activeOutput = null;
    setStatus("");
    renderOutputs();
  }

  async function renameOutput() {
    if (!activeOutput || !outputsReady) return;
    const title = outputTitleInput.value.replace(/\s+/g, " ").trim();
    if (!title || title.length > 100) {
      setStatus("제목은 1자 이상 100자 이하로 입력해 주세요.", "error");
      return;
    }
    outputRenameButton.disabled = true;
    try {
      const response = await fetch(`/api/outputs/${encodeURIComponent(activeOutput.id)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json", "Accept": "application/json" },
        body: JSON.stringify({ title }),
      });
      const data = await response.json().catch(() => null);
      if (!response.ok || !data || !data.output) throw new Error("제목을 바꾸지 못했습니다.");
      activeOutput = data.output;
      outputTitleInput.value = activeOutput.title;
      setStatus("제목을 저장했습니다.");
      await loadOutputs();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "제목을 바꾸지 못했습니다.", "error");
    } finally {
      outputRenameButton.disabled = false;
    }
  }

  async function deleteOutput() {
    if (!activeOutput || !outputsReady) return;
    const confirmed = await window.PadiemConfirmDialog.confirm({
      title: "저장한 답변을 삭제할까요?",
      message: "저장한 답변만 삭제합니다. 원래 대화는 삭제되지 않습니다.",
      cancelLabel: "취소",
      confirmLabel: "삭제",
    });
    if (!confirmed) return;
    outputDeleteButton.disabled = true;
    try {
      const response = await fetch(`/api/outputs/${encodeURIComponent(activeOutput.id)}`, { method: "DELETE", headers: { "Accept": "application/json" } });
      const data = await response.json().catch(() => null);
      if (!response.ok || !data || data.deleted !== true) throw new Error("저장한 답변을 삭제하지 못했습니다.");
      closeOutput();
      await loadOutputs();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "저장한 답변을 삭제하지 못했습니다.", "error");
    } finally {
      outputDeleteButton.disabled = false;
    }
  }

  if (outputsNavButton) outputsNavButton.addEventListener("click", () => {
    if (outputsReady && outputsSection) outputsSection.scrollIntoView({ block: "nearest", behavior: "smooth" });
  });
  outputDialogClose.addEventListener("click", closeOutput);
  outputDialog.addEventListener("cancel", (event) => { event.preventDefault(); closeOutput(); });
  outputCopyButton.addEventListener("click", async () => {
    if (!activeOutput) return;
    const copied = await copyText(activeOutput.content);
    setStatus(copied ? "답변을 복사했습니다." : "복사하지 못했습니다.", copied ? "normal" : "error");
  });
  outputDownloadButton.addEventListener("click", () => { if (activeOutput) downloadText(activeOutput.content, activeOutput.title); });
  outputRenameButton.addEventListener("click", renameOutput);
  outputDeleteButton.addEventListener("click", deleteOutput);

  const messageObserver = new MutationObserver(enhanceAllAnswers);
  messageObserver.observe(messageList, { childList: true, subtree: true });
  messageList.addEventListener("padiem:message-lifecycle", enhanceAllAnswers);

  function normalizeAuthProjection() {
    if (!loginButton) return false;
    const raw = loginButton.textContent.trim();
    const accountState = loginButton.closest(".sidebar-account")?.dataset.accountState || "";
    let projectedState = loginButton.dataset.authenticated;
    if (raw === "로그아웃" || raw === "Log out") projectedState = "true";
    else if (raw === "로그인" || raw === "Log in" || raw === "다시 로그인" || raw === "Sign in again") projectedState = "false";
    if (projectedState && loginButton.dataset.authenticated !== projectedState) {
      loginButton.dataset.authenticated = projectedState;
    }
    const authenticated = loginButton.dataset.authenticated === "true" && loginButton.disabled === false;
    const locale = window.__padiemLocale;
    if (locale && typeof locale.text === "function") {
      const expired = accountState === "expired";
      const nextText = locale.text(expired ? "sign-in-again" : authenticated ? "logout" : "login");
      const nextTitle = locale.text(
        expired
          ? "expired-title"
          : loginButton.disabled
            ? "login-unavailable-title"
            : authenticated
              ? "logout-title"
              : "login-title"
      );
      if (loginButton.textContent !== nextText) loginButton.textContent = nextText;
      if (loginButton.title !== nextTitle) loginButton.title = nextTitle;
    }
    return authenticated;
  }

  function isAuthenticated() {
    const current = normalizeAuthProjection();
    if (current) lastAuthenticated = true;
    else if (loginButton && loginButton.dataset.authenticated === "false") lastAuthenticated = false;
    return current;
  }

  function preserveAuthenticatedLocaleProjection() {
    if (!lastAuthenticated || !loginButton || loginButton.disabled) {
      normalizeAuthProjection();
      return;
    }
    if (loginButton.dataset.authenticated !== "true") loginButton.dataset.authenticated = "true";
    normalizeAuthProjection();
  }

  if (loginButton) {
    const authObserver = new MutationObserver(() => {
      if (isAuthenticated()) loadOutputs();
      else disableOutputs();
    });
    authObserver.observe(loginButton, { childList: true, subtree: true, attributes: true });
    if (isAuthenticated()) loadOutputs();
    else disableOutputs();
    window.addEventListener("padiem:localechange", preserveAuthenticatedLocaleProjection);
  } else {
    disableOutputs();
  }

  enhanceAllAnswers();
})();