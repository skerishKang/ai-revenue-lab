(() => {
  "use strict";

  const form = document.getElementById("composerForm");
  const input = document.getElementById("messageInput");
  const sendButton = document.getElementById("sendButton");
  const cancelButton = document.getElementById("cancelStreamButton");
  const attachmentInput = document.getElementById("attachmentFileInput");
  const attachmentButton = document.getElementById("attachmentButton");
  const documentStarter = document.getElementById("documentStarterButton");
  const removeAttachment = document.getElementById("removeAttachment");
  const attachmentTray = document.getElementById("attachmentTray");
  const attachmentName = document.getElementById("attachmentName");
  const runtimeNote = document.getElementById("runtimeNote");
  const messageList = document.getElementById("messageList");
  if (!form || !input || !sendButton || !cancelButton || !attachmentInput || !attachmentButton || !runtimeNote || !messageList) return;

  const phases = Object.freeze({
    IDLE: "idle",
    ATTACHMENT_LOADING: "attachment_loading",
    PREPARING: "preparing",
    STREAMING: "streaming",
    CANCELLING: "cancelling",
  });
  const terminalStates = new Set(["completed", "failed", "cancelled", "timed_out"]);
  const requestPhases = new Set([phases.PREPARING, phases.STREAMING, phases.CANCELLING]);
  let phase = phases.IDLE;
  let attachmentLoading = false;
  let terminalSettling = false;

  function copy(ko, en) {
    return (document.documentElement.lang || "ko").toLowerCase().startsWith("en") ? en : ko;
  }

  function ensureStyles() {
    if (document.querySelector("link[data-interaction-polish-styles]")) return;
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = "./interaction-polish.css";
    link.dataset.interactionPolishStyles = "true";
    document.head.appendChild(link);
  }

  function ensureStatus() {
    let status = document.getElementById("composerInteractionStatus");
    if (status) return status;
    status = document.createElement("p");
    status.id = "composerInteractionStatus";
    status.className = "composer-interaction-status";
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");
    status.setAttribute("aria-atomic", "true");
    status.hidden = true;
    runtimeNote.parentElement.insertBefore(status, runtimeNote);
    return status;
  }

  const statusNode = ensureStatus();
  ensureStyles();

  function phaseText(next) {
    if (next === phases.ATTACHMENT_LOADING) return copy("파일을 안전하게 확인하고 있습니다.", "Checking the file before attaching it.");
    if (next === phases.PREPARING) return copy("요청을 준비하고 있습니다.", "Preparing your request.");
    if (next === phases.STREAMING) return copy("답변을 전달하고 있습니다. 필요하면 취소할 수 있습니다.", "Delivering the response. You can cancel if needed.");
    if (next === phases.CANCELLING) return copy("답변 생성을 취소하고 있습니다.", "Cancelling response generation.");
    return "";
  }

  function setPhase(next) {
    if (!Object.values(phases).includes(next)) return;
    const changed = phase !== next;
    phase = next;
    form.dataset.interactionPhase = next;
    form.setAttribute("aria-busy", next === phases.IDLE ? "false" : "true");
    statusNode.dataset.phase = next;
    statusNode.textContent = phaseText(next);
    statusNode.hidden = next === phases.IDLE;
    if (changed) {
      document.dispatchEvent(new CustomEvent("padiem:interaction-phase", {
        detail: { phase: next },
      }));
    }
  }

  function latestAssistant() {
    const items = messageList.querySelectorAll(".assistant-message");
    return items.length ? items[items.length - 1] : null;
  }

  function restoreComposerControls() {
    const requestBusy = !cancelButton.hidden || (input.disabled && !attachmentLoading);
    attachmentButton.disabled = requestBusy;
    if (documentStarter) documentStarter.disabled = requestBusy;
    if (removeAttachment) removeAttachment.disabled = requestBusy;
    if (!requestBusy) sendButton.disabled = input.value.trim().length === 0;
  }

  function guardAttachmentControls() {
    if (!attachmentLoading) return;
    attachmentButton.disabled = true;
    if (documentStarter) documentStarter.disabled = true;
    if (removeAttachment) removeAttachment.disabled = true;
    sendButton.disabled = true;
  }

  function focusComposer() {
    if (input.disabled) return;
    const dialog = document.activeElement && document.activeElement.closest ? document.activeElement.closest("dialog") : null;
    if (dialog && dialog.open) return;
    queueMicrotask(() => {
      if (!input.disabled && input.isConnected) input.focus();
    });
  }

  function normalizeTerminalCopy(article, state) {
    if (!article) return;
    article.dataset.terminalActionsSafe = state === "completed" ? "true" : "false";
    if (state !== "timed_out") return;
    const box = article.querySelector(".error-box");
    if (!box) return;
    const heading = box.querySelector("strong");
    const body = box.querySelector("p");
    if (heading) heading.textContent = copy("응답 시간이 지났습니다.", "The response timed out.");
    if (body) body.textContent = copy(
      "정해진 시간 안에 응답이 완료되지 않았습니다. 다시 시도할 수 있습니다.",
      "The response did not finish in time. You can try again."
    );
  }

  function handleLifecycle(event) {
    const article = event.target instanceof Element ? event.target.closest(".assistant-message") : null;
    const state = event.detail && typeof event.detail.state === "string" ? event.detail.state : "";
    if (!article) return;
    if (state === "streaming") {
      article.dataset.terminalActionsSafe = "false";
      queueMicrotask(syncRequestFromDom);
      return;
    }
    if (!terminalStates.has(state)) return;
    normalizeTerminalCopy(article, state);
    terminalSettling = true;
    setPhase(phases.IDLE);
    cancelButton.setAttribute("aria-busy", "false");
    cancelButton.textContent = copy("취소", "Cancel");
    window.setTimeout(() => {
      syncRequestFromDom();
      focusComposer();
    }, 0);
  }

  function syncRequestFromDom() {
    if (attachmentLoading) {
      guardAttachmentControls();
      return;
    }

    const requestBusy = !cancelButton.hidden || input.disabled;
    if (terminalSettling) {
      if (!requestBusy) {
        terminalSettling = false;
        setPhase(phases.IDLE);
        restoreComposerControls();
      }
      return;
    }

    if (!requestBusy) {
      if (requestPhases.has(phase)) setPhase(phases.IDLE);
      restoreComposerControls();
      return;
    }
    if (phase === phases.CANCELLING) return;

    const article = latestAssistant();
    const preparing = Boolean(article && article.querySelector(".typing"));
    setPhase(preparing ? phases.PREPARING : phases.STREAMING);
  }

  function finishAttachment(success) {
    if (!attachmentLoading) return;
    attachmentLoading = false;
    setPhase(phases.IDLE);
    restoreComposerControls();
    if (success) focusComposer();
    else if (attachmentButton.isConnected) attachmentButton.focus();
  }

  function maybeFinishAttachment() {
    if (!attachmentLoading) return;
    const failed = runtimeNote.dataset.state === "error";
    const selected = !attachmentTray.hidden && Boolean(attachmentName && attachmentName.textContent.trim());
    if (failed) finishAttachment(false);
    else if (selected) finishAttachment(true);
  }

  attachmentInput.addEventListener("change", () => {
    const files = attachmentInput.files || [];
    if (!files.length) return;
    attachmentLoading = true;
    setPhase(phases.ATTACHMENT_LOADING);
    guardAttachmentControls();
  }, true);

  input.addEventListener("input", () => {
    queueMicrotask(() => {
      if (attachmentLoading) guardAttachmentControls();
      else syncRequestFromDom();
    });
  });

  cancelButton.addEventListener("click", () => {
    if (cancelButton.hidden) return;
    setPhase(phases.CANCELLING);
    cancelButton.disabled = true;
    cancelButton.setAttribute("aria-disabled", "true");
    cancelButton.setAttribute("aria-busy", "true");
    cancelButton.textContent = copy("취소 중…", "Cancelling…");
  }, true);

  messageList.addEventListener("click", (event) => {
    const retry = event.target instanceof Element ? event.target.closest(".retry-button") : null;
    if (!retry || retry.disabled) return;
    retry.disabled = true;
    retry.setAttribute("aria-disabled", "true");
    retry.setAttribute("aria-busy", "true");
    retry.textContent = copy("다시 시도 중…", "Retrying…");
    queueMicrotask(syncRequestFromDom);
  }, true);

  messageList.addEventListener("padiem:message-lifecycle", handleLifecycle);

  const requestObserver = new MutationObserver(syncRequestFromDom);
  requestObserver.observe(cancelButton, { attributes: true, attributeFilter: ["hidden", "disabled"] });
  requestObserver.observe(input, { attributes: true, attributeFilter: ["disabled"] });
  requestObserver.observe(messageList, { childList: true, subtree: true });

  const attachmentObserver = new MutationObserver(() => queueMicrotask(maybeFinishAttachment));
  attachmentObserver.observe(runtimeNote, { childList: true, subtree: true, attributes: true, attributeFilter: ["data-state"] });
  attachmentObserver.observe(attachmentTray, { attributes: true, attributeFilter: ["hidden"] });
  if (attachmentName) attachmentObserver.observe(attachmentName, { childList: true, subtree: true });

  window.addEventListener("padiem:localechange", () => {
    if (phase !== phases.IDLE) statusNode.textContent = phaseText(phase);
    if (phase === phases.CANCELLING) cancelButton.textContent = copy("취소 중…", "Cancelling…");
  });

  window.PadiemChatInteractionPresentation = Object.freeze({
    phases,
    currentPhase() { return phase; },
    terminalStates: Object.freeze(Array.from(terminalStates)),
  });

  form.dataset.interactionPhase = phases.IDLE;
  form.setAttribute("aria-busy", "false");
  syncRequestFromDom();
})();
