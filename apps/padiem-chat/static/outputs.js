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

  if (!outputsNavButton || !outputsSection || !outputsList || !outputDialog || !messageList) return;

  let outputsReady = false;
  let outputs = [];
  let activeOutput = null;
  let loadInFlight = false;

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
      } catch (_) {
        // Continue to the local fallback below.
      }
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

  function updateSaveButtons() {
    document.querySelectorAll(".answer-save").forEach((button) => {
      button.hidden = !outputsReady;
      button.disabled = !outputsReady || button.dataset.saved === "true";
    });
  }

  function disableOutputs() {
    outputsReady = false;
    outputs = [];
    outputsNavButton.hidden = true;
    outputsNavButton.disabled = true;
    outputsNavButton.setAttribute("aria-disabled", "true");
    outputsBadge.textContent = "로그인 후";
    outputsSection.hidden = true;
    outputsList.replaceChildren();
    outputsEmpty.hidden = true;
    updateSaveButtons();
    if (outputDialog.open) outputDialog.close();
    activeOutput = null;
  }

  function renderOutputs() {
    outputsList.replaceChildren();
    outputsSection.hidden = false;
    outputsEmpty.hidden = outputs.length !== 0;
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
    outputsBadge.textContent = outputs.length ? String(outputs.length) : "비어 있음";
  }

  async function loadOutputs() {
    if (loadInFlight) return outputsReady;
    loadInFlight = true;
    try {
      const response = await fetch("/api/outputs", {
        headers: { "Accept": "application/json" },
        cache: "no-store",
      });
      const data = await response.json().catch(() => null);
      if (!response.ok || !data || !Array.isArray(data.outputs)) throw new Error("saved outputs unavailable");
      outputs = data.outputs.filter((item) => item && typeof item.id === "string" && typeof item.title === "string");
      outputsReady = true;
      outputsNavButton.hidden = false;
      outputsNavButton.disabled = false;
      outputsNavButton.setAttribute("aria-disabled", "false");
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

  function feedbackButton(button, successText, originalText) {
    button.textContent = successText;
    window.setTimeout(() => {
      if (button.isConnected && button.dataset.saved !== "true") button.textContent = originalText;
    }, 1200);
  }

  function enhanceAssistantMessage(article) {
    if (!(article instanceof Element) || article.dataset.outputActions === "true") return;
    const text = answerText(article);
    if (!text) return;
    const body = article.querySelector(".assistant-body");
    if (!body) return;

    const actions = document.createElement("div");
    actions.className = "answer-actions";
    actions.setAttribute("aria-label", "답변 작업");

    const copy = document.createElement("button");
    copy.type = "button";
    copy.className = "answer-action answer-copy";
    copy.textContent = "복사";
    copy.addEventListener("click", async () => {
      const copied = await copyText(text);
      feedbackButton(copy, copied ? "복사됨" : "복사 실패", "복사");
    });

    const download = document.createElement("button");
    download.type = "button";
    download.className = "answer-action answer-download";
    download.textContent = "다운로드";
    download.addEventListener("click", () => downloadText(text, titleFromText(text)));

    const save = document.createElement("button");
    save.type = "button";
    save.className = "answer-action answer-save";
    save.textContent = "저장";
    save.hidden = !outputsReady;
    save.disabled = !outputsReady;
    save.addEventListener("click", async () => {
      if (!outputsReady || save.dataset.saved === "true") return;
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

    actions.append(copy, download, save);
    body.appendChild(actions);
    article.dataset.outputActions = "true";
  }

  function enhanceAllAnswers() {
    messageList.querySelectorAll(".assistant-message").forEach(enhanceAssistantMessage);
  }

  async function openOutput(id) {
    if (!outputsReady) return;
    try {
      const response = await fetch(`/api/outputs/${encodeURIComponent(id)}`, {
        headers: { "Accept": "application/json" },
        cache: "no-store",
      });
      const data = await response.json().catch(() => null);
      if (!response.ok || !data || !data.output || typeof data.output.content !== "string") {
        throw new Error("저장한 답변을 불러오지 못했습니다.");
      }
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
    if (!window.confirm("이 저장한 답변을 삭제할까요? 원래 대화는 삭제되지 않습니다.")) return;
    outputDeleteButton.disabled = true;
    try {
      const response = await fetch(`/api/outputs/${encodeURIComponent(activeOutput.id)}`, {
        method: "DELETE",
        headers: { "Accept": "application/json" },
      });
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

  outputsNavButton.addEventListener("click", () => {
    if (outputsReady) outputsSection.scrollIntoView({ block: "nearest", behavior: "smooth" });
  });
  outputDialogClose.addEventListener("click", closeOutput);
  outputDialog.addEventListener("cancel", (event) => {
    event.preventDefault();
    closeOutput();
  });
  outputCopyButton.addEventListener("click", async () => {
    if (!activeOutput) return;
    const copied = await copyText(activeOutput.content);
    setStatus(copied ? "답변을 복사했습니다." : "복사하지 못했습니다.", copied ? "normal" : "error");
  });
  outputDownloadButton.addEventListener("click", () => {
    if (activeOutput) downloadText(activeOutput.content, activeOutput.title);
  });
  outputRenameButton.addEventListener("click", renameOutput);
  outputDeleteButton.addEventListener("click", deleteOutput);

  const messageObserver = new MutationObserver(enhanceAllAnswers);
  messageObserver.observe(messageList, { childList: true, subtree: true });

  if (loginButton) {
    const authObserver = new MutationObserver(() => {
      const loggedIn = loginButton.textContent.trim() === "로그아웃" && loginButton.disabled === false;
      if (loggedIn) loadOutputs();
      else disableOutputs();
    });
    authObserver.observe(loginButton, { childList: true, subtree: true, attributes: true });
    if (loginButton.textContent.trim() === "로그아웃" && loginButton.disabled === false) loadOutputs();
    else disableOutputs();
  } else {
    disableOutputs();
  }

  enhanceAllAnswers();
})();
