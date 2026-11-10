// #7216 R5 - conversation section (moved out of the app.js closure).
// No behavior, copy, DOM id or event name change. Shared state and DOM refs are
// read/written only through the deps getters/setters. app.js keeps the same-named
// one-line forwarders.
(() => {
  "use strict";
  window.PadiemChatConversationModule = {
    create(deps) {
  function attachmentCopy() {
    return deps.attachmentCapabilities.copy(document.documentElement.lang);
  }
  function showComposerInlineHint(key) {
    if (!deps.composerInlineHint) return;
    deps.composerInlineHint.textContent = deps.uiT(key);
    deps.composerInlineHint.hidden = false;
    if (deps.composerInlineHintTimer !== null) window.clearTimeout(deps.composerInlineHintTimer);
    deps.composerInlineHintTimer = window.setTimeout(() => {
      deps.composerInlineHint.hidden = true;
      deps.composerInlineHint.textContent = "";
      deps.composerInlineHintTimer = null;
    }, 3000);
  }
  function updateComposer() {
    // Empty clicks are allowed; submitPrompt() already ignores blank or busy submissions.
    deps.sendButton.disabled = false;
    deps.input.disabled = deps.inFlight;
    deps.attachmentButton.disabled = deps.inFlight;
    deps.attachmentChipList?.querySelectorAll(".attachment-remove").forEach((button) => {
      button.disabled = deps.inFlight;
    });
    deps.editProjectButton.disabled = deps.inFlight;
    deps.exitProjectButton.disabled = deps.inFlight;
    deps.cancelStreamButton.hidden = !deps.inFlight;
    deps.cancelStreamButton.disabled = !deps.inFlight;
    deps.cancelStreamButton.setAttribute("aria-disabled", deps.inFlight ? "false" : "true");
    // #5561: the primary action slot shows the voice waveform for an empty
    // composer and the send arrow once there is text. The composer is the
    // authority for the input value, so it asks the voice module to re-read it.
    window.PadiemVoiceMenu?.syncPrimaryAction?.();
    if (window.PadiemConversationComposer?.resizeTextarea) {
      window.PadiemConversationComposer.resizeTextarea(deps.input, { maxHeight: 180 });
    } else {
      deps.input.style.height = "auto";
      deps.input.style.height = `${Math.min(deps.input.scrollHeight, 180)}px`;
    }
  }
  function showConversation({ preserveClaw = false, restoreSaved = false } = {}) {
    const conversationPanel = deps.messageList.closest(".conversation");
    // #2505: a Chat send moves to the Chat lane. The switch happens before the
    // landing rule is read, and it keeps the shared conversation.
    if (!preserveClaw) deps.switchConversationProduct(deps.PRODUCT_CHAT);
    const startingOnLanding = !restoreSaved
      && !deps.emptyState.hidden
      && deps.messageList.childElementCount === 0
      && (deps.shell.dataset.state === "home"
        || (preserveClaw && deps.shell.dataset.state === "claw"));
    const continuingLanding = !restoreSaved
      && conversationPanel?.dataset.continuousThread === "true";
    const keepLanding = startingOnLanding || continuingLanding;
    if (conversationPanel) {
      if (keepLanding) conversationPanel.dataset.continuousThread = "true";
      else delete conversationPanel.dataset.continuousThread;
    }
    deps.emptyState.hidden = !keepLanding;
    deps.messageList.hidden = false;
    // #3931: Keep an in-flight Claw conversation in the Claw workspace.
    // Saved Chat conversations and ordinary Chat sends still use Chat.
    if (!preserveClaw) {
      deps.shell.dataset.state = "chat";
      // Switching from Claw to ordinary Chat must not carry the Claw
      // execution-history disclosure into a customer conversation.
      // Do not erase the server-owned history, only reset this view.
      for (const id of ["clawRunHistoryDisclosure", "clawRunHistory",
                        "clawApprovedDisclosure", "clawApprovedMemory"]) {
        const node = document.getElementById(id);
        if (!node) continue;
        node.hidden = true;
        if (node.tagName === "DETAILS") node.open = false;
      }
    } else if (restoreSaved && typeof document.getElementById === "function") {
      for (const id of ["clawRunHistoryDisclosure", "clawApprovedDisclosure"]) {
        const node = document.getElementById(id);
        if (node && node.tagName === "DETAILS") node.open = false;
      }
    }
    deps.setNavActive();
  }
  function addUserMessage(text, attachment, options) {
    const restored = Boolean(options && options.restored);
    const fragment = document.getElementById("userMessageTemplate").content.cloneNode(true);
    const bubble = fragment.querySelector(".message-bubble");
    bubble.textContent = text;
    const attachmentItems = Array.isArray(attachment) ? attachment : (attachment ? [attachment] : []);
    for (const item of attachmentItems) {
      const meta = document.createElement("span");
      meta.className = "message-attachment-meta";
      const label = item.type === "image" ? deps.uiT("attachment-photo") : deps.uiT("attachment-document");
      meta.textContent = `${label} · ${item.name} · ${deps.formatBytes(item.byteSize)}`;
      bubble.appendChild(meta);
    }
    // Plan 4 (Glass only, shown via CSS): profile chip mirrors the signed-in
    // account name at send time; hidden account (signed out) drops the chip.
    const chip = fragment.querySelector(".user-profile-chip");
    const avatar = fragment.querySelector(".user-avatar");
    if (chip) {
      const name = deps.accountName && !deps.accountName.hidden ? deps.accountName.textContent.trim() : "";
      if (name) {
        chip.textContent = name;
        // The small person glyph becomes the account-name initial in the
        // same 32x32 plate the Padiem "P" avatar uses.
        if (avatar) avatar.textContent = deps.accountInitial(name);
      } else {
        chip.remove();
      }
    }
    // Owner 2026-10-20: the stamp belongs to the live turn. A restored
    // conversation carries no stored per-message time, so no time is
    // invented for it.
    const clock = fragment.querySelector(".user-action-time");
    if (clock) {
      if (restored) {
        clock.remove();
      } else {
        const now = new Date();
        const stamp = deps.formatClockTime(now);
        clock.textContent = stamp;
        clock.setAttribute("datetime", now.toISOString());
        clock.setAttribute("data-padiem-tooltip", stamp);
      }
    }
    const copyBtn = fragment.querySelector(".user-action-copy");
    if (copyBtn) {
      copyBtn.setAttribute("aria-label", deps.uiT("answer-copy"));
      copyBtn.setAttribute("data-padiem-tooltip", deps.uiT("answer-copy"));
      copyBtn.addEventListener("click", () => {
        const done = copyBtn.querySelector("span") || copyBtn;
        const prev = done.textContent;
        const flash = () => { done.textContent = "✓"; setTimeout(() => { done.textContent = prev; }, 900); };
        const plain = bubble ? bubble.textContent : text;
        /* #4488: shared clipboard path; legacy branches stay only as the
         * fallback when the shared script is unavailable. */
        const shared = window.PadiemAnswerCopy || window.SharedAnswerCopy;
        if (shared && typeof shared.copyText === "function") {
          shared.copyText(plain).then((ok) => { if (ok) flash(); });
        } else if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(plain).then(flash, () => {});
        } else {
          const ta = document.createElement("textarea");
          ta.value = plain;
          document.body.appendChild(ta);
          ta.select();
          try { document.execCommand("copy"); flash(); } catch (e) {}
          ta.remove();
        }
      });
    }
    const editBtn = fragment.querySelector(".user-action-edit");
    if (editBtn) {
      editBtn.setAttribute("data-padiem-tooltip", editBtn.getAttribute("aria-label") || "");
      editBtn.addEventListener("click", () => {
        deps.input.value = text;
        deps.input.focus();
        deps.input.dispatchEvent(new Event("input", { bubbles: true }));
      });
    }
    // One shared chip tooltip for every hint on this turn.
    window.PadiemSharedTooltip?.bind?.(fragment);
    deps.messageList.appendChild(fragment);
  }
  function renderAnswer(article, result) {
    const content = article.querySelector(".assistant-content");
    content.replaceChildren();
    deps.renderWebGroundingNotice(content, result.notice, result.metadata);
    // #5573: the live PC scope notice is its own line above the answer.
    window.PadiemChatPcScopeNotice?.render?.(content, window.PadiemChatPcScopeNotice?.value?.(result));
    const paragraph = document.createElement("p");
    paragraph.textContent = result.answer;
    content.appendChild(paragraph);
    if (Number.isInteger(result.project_files_used) && result.project_files_used > 0) {
      const used = document.createElement("small");
      used.className = "reference-note";
      used.textContent = deps.uiT("project-files-used", { count: result.project_files_used });
      content.appendChild(used);
    }
    const skillTitle = result.skill && result.skill.id !== "auto" && typeof result.skill.title === "string" ? result.skill.title : "";
    // The brand (Padiem Chat / Padiem Claw) stays in [data-assistant-product].
    // The repetitive runtime line is removed: only a truthful non-default
    // state (mock preview) or an explicit skill title is shown.
    const runtimeLabel = result.runtime === "mock" ? deps.uiT("mock-response") : "";
    const answerLabel = skillTitle ? (runtimeLabel ? `${runtimeLabel} · ${skillTitle}` : skillTitle) : runtimeLabel;
    article.querySelector("[data-runtime-label]").textContent = answerLabel;
    // A completed answer carries no runtime status: the chip is released
    // instead of staying on "answer preparing".
    window.PadiemChatLifecycle?.applyRuntimeLabel?.(article, answerLabel, "status");
    if (Array.isArray(result.memory_proposals)) {
      window.PadiemChatMemoryReview?.render?.(result.memory_proposals);
    }
    PadiemChatLifecycle.set(article, deps.MESSAGE_LIFECYCLE.COMPLETED);
  }
  function renderStreamError(article, message, retryMessages, retrySkill, retryContext, clawGeneralRequest = false, lifecycle = deps.MESSAGE_LIFECYCLE.FAILED, clawFailure = null, errorCode = "") {
    const content = article.querySelector(".assistant-content");
    const typing = content.querySelector(".typing");
    if (typing) typing.remove();
    const statusLabel = deps.failureStatusLabel(lifecycle);
    article.querySelector("[data-runtime-label]").textContent = statusLabel;
    // A failure is a real status: the chip stays visible with its own copy.
    window.PadiemChatLifecycle?.applyRuntimeLabel?.(article, statusLabel, "status");
    const box = deps.buildRetryBox(message, article, retryMessages, retrySkill, null, retryContext, clawGeneralRequest, undefined, clawFailure);
    const codeNote = clawGeneralRequest ? null : deps.failureCodeNote(errorCode, statusLabel);
    if (codeNote) box.appendChild(codeNote);
    content.appendChild(box);
    PadiemChatLifecycle.set(article, lifecycle);
    deps.revealErrorState(article);
  }
  function clearAttachment() {
    for (const item of deps.selectedAttachments) {
      if (item.previewUrl) URL.revokeObjectURL(item.previewUrl);
    }
    deps.selectedAttachments = [];
    deps.attachmentFileInput.value = "";
    deps.renderAttachmentChips();
    deps.setNote(deps.idleNote());
    deps.updateComposer();
  }
  function attachmentCountLimit() {
    const configured = Number(window.PadiemAttachmentCapabilities?.maxPerMessage);
    return Number.isSafeInteger(configured) && configured >= 1
      ? Math.min(configured, 10) : 5;
  }
  function attachmentTrayNote() {
    const valid = deps.selectedAttachments.filter((item) => !item.invalid);
    if (!valid.length) return deps.idleNote();
    // #6126: a .hwp name whose bytes are a real HWPX (ZIP) package is read as
    // HWPX, so the tray note follows the actual media type, not only the name.
    if (valid.some((item) => item.mediaType === "application/hwp+zip"
        || String(item.name || "").toLowerCase().endsWith(".hwpx"))) {
      return deps.uiT("attachment-hwpx-note");
    }
    return valid.length === 1 && valid[0].type === "image"
      ? deps.uiT("attachment-image-note")
      : deps.uiT("attachment-document-note");
  }
  function removeAttachmentItem(item) {
    if (deps.inFlight) return;
    const index = deps.selectedAttachments.indexOf(item);
    if (index < 0) return;
    if (item.previewUrl) URL.revokeObjectURL(item.previewUrl);
    deps.selectedAttachments.splice(index, 1);
    deps.renderAttachmentChips();
    deps.setNote(deps.attachmentTrayNote());
    deps.updateComposer();
  }
  function renderAttachmentChips() {
    if (!deps.attachmentChipList) return;
    deps.attachmentChipList.replaceChildren();
    if (!deps.selectedAttachments.length) {
      deps.attachmentTray.hidden = true;
      return;
    }
    // The chip row belongs to the multi-attachment tray: one entry per file,
    // removal button included. Single-attachment thumbnail code (pre-#1727)
    // is gone; per-file notes live in attachmentTrayNote().
    for (const item of deps.selectedAttachments) {
      const chip = document.createElement("li");
      chip.className = "attachment-chip" + (item.invalid ? " attachment-chip-invalid" : "");
      const icon = document.createElement("span");
      icon.className = "attachment-chip-icon";
      icon.setAttribute("aria-hidden", "true");
      icon.textContent = item.type === "image"
        ? "IMG"
        : (deps.extensionOf(item.name).replace(".", "").toUpperCase() || "DOC");
      const copy = document.createElement("div");
      copy.className = "attachment-chip-copy";
      const name = document.createElement("strong");
      name.textContent = item.name;
      const detail = document.createElement("small");
      detail.textContent = item.invalid ? (item.error || deps.uiT("file-read-failed")) : deps.formatBytes(item.byteSize);
      copy.append(name, detail);
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "attachment-remove";
      remove.textContent = "×";
      remove.setAttribute("data-locale-aria-label", "attachment-remove");
      remove.setAttribute("aria-label", deps.uiT("attachment-remove"));
      remove.disabled = deps.inFlight;
      remove.addEventListener("click", () => deps.removeAttachmentItem(item));
      chip.append(icon, copy, remove);
      deps.attachmentChipList.appendChild(chip);
    }
    deps.attachmentTray.hidden = false;
  }
  async function addAttachmentFiles(files) {
    // #261102 multi-attachment: picking or dropping several files at once
    // turns each file into an independent chip. A per-file refusal (e.g. the
    // legacy hwp guidance) shows on that chip only, and only valid chips
    // reach the send payload.
    const list = Array.from(files || []);
    if (!list.length) return;
    const limit = deps.attachmentCountLimit();
    for (const file of list) {
      const validCount = deps.selectedAttachments.filter((item) => !item.invalid).length;
      try {
        if (validCount >= limit) {
          throw new Error(deps.uiT("attachment-count-limit", { count: limit }));
        }
        let next;
        // #6126: an uploaded .hwp is judged by its own bytes, not its name.
        // The older OLE2 binary Hangul format is refused with the save-as-
        // HWPX guidance on this chip only; a mislabeled file whose bytes are
        // a real HWPX (ZIP) package keeps working as HWPX below.
        const hwpFamily = deps.extensionOf(file.name) === ".hwp"
          ? (await deps.binaryDocuments?.headerFamily?.(file)) || null
          : null;
        if (hwpFamily === "ole") throw new Error(deps.uiT("hwp-legacy-guidance"));
        const useFileLane = window.PadiemFileLane?.shouldUse(file);
        const fileLaneAvailable = useFileLane && await window.PadiemFileLane.available();
        if (useFileLane && fileLaneAvailable) {
          next = window.PadiemFileLane.pending(file);
        } else if (useFileLane && window.PadiemFileLane.isBinary(file)) {
          throw new Error(deps.uiT("file-lane-unavailable"));
        } else if (deps.ALLOWED_IMAGE_TYPES.has(file.type)) next = await deps.selectImage(file);
        else if (hwpFamily === "zip" && deps.binaryDocuments?.hwpxMedia) next = await deps.binaryDocuments.read(file, { mediaType: deps.binaryDocuments.hwpxMedia });
        else if (deps.binaryDocuments && typeof deps.binaryDocuments.canRead === "function" && deps.binaryDocuments.canRead(file)) next = await deps.binaryDocuments.read(file);
        else next = await deps.readDocumentFile(file);
        // Photos and original documents read by the browser fit only one
        // request frame, so a single attachment alone is allowed. Multiple
        // documents (tus/text) combine freely.
        const rawByteAttachment = Boolean(next.file);
        const mixedWithExisting = validCount > 0;
        if (mixedWithExisting && (rawByteAttachment
            || deps.selectedAttachments.some((item) => !item.invalid && item.file))) {
          throw new Error(deps.uiT("attachment-raw-single"));
        }
        deps.attachmentKeyCounter += 1;
        deps.selectedAttachments.push({ ...next, key: `att-${deps.attachmentKeyCounter}` });
      } catch (error) {
        deps.attachmentKeyCounter += 1;
        deps.selectedAttachments.push({
          key: `att-${deps.attachmentKeyCounter}`,
          invalid: true,
          type: "document",
          name: file && file.name ? file.name : "file",
          byteSize: file && typeof file.size === "number" ? file.size : 0,
          error: error instanceof Error ? error.message : deps.uiT("file-read-failed"),
        });
      }
    }
    deps.attachmentFileInput.value = "";
    deps.renderAttachmentChips();
    deps.setNote(deps.attachmentTrayNote());
    deps.updateComposer();
  }
  function attachmentPayload(list) {
    const items = (Array.isArray(list) ? list : list ? [list] : [])
      .filter((item) => item && !item.invalid);
    if (!items.length) return undefined;
    return items.map((item) => {
      if (item.fileId) return { type: "file", file_id: item.fileId };
      if (item.file) {
        return { type: item.type, name: item.name, media_type: item.mediaType, file: item.file };
      }
      return { type: item.type, name: item.name, media_type: item.mediaType, text: item.text };
    });
  }
  function safeLocalUiMessage(error, fallback) {
    if (error?.uiMessageSafe) return error.message;
    const localFileErrors = [deps.attachmentCopy().unsupportedFormat, deps.uiT("empty-document"),
      deps.uiT("document-read-failed"), deps.uiT("binary-document")];
    return error instanceof Error && localFileErrors.includes(error.message) ? error.message : fallback;
  }
  function resetConversationView(preserveProject = true) {
    deps.conversationEpoch += 1;
    deps.lastCompletedAnswerRequest = null;
    if (deps.activeRequestController) {
      deps.activeRequestCancelReason = "conversation_reset";
      deps.activeRequestController.abort();
      deps.activeRequestController = null;
      deps.activeRequestArticle = null;
    }
    deps.activeClawRunId = null;
    deps.inFlight = false;
    // #2505: a new conversation always starts a new one, on either screen: the
    // single shared conversation is cleared. Server-owned records are never
    // deleted here.
    deps.conversationState.setProduct?.(deps.conversationProduct);
    deps.conversationState.reset();
    if (!preserveProject) {
      deps.activeProject = null;
      deps.activeProjectFileCount = 0;
    }
    deps.clearAttachment();
    deps.messageList.replaceChildren();
    deps.messageList.hidden = true;
    delete deps.messageList.closest(".conversation")?.dataset.continuousThread;
    deps.clawArtifactShownFor = "";
    deps.conversationArtifactContext?.clear?.();
    deps.emptyState.hidden = false;
    deps.shell.dataset.state = "home";
    if (typeof document.getElementById === "function") {
      for (const id of ["clawRunHistoryDisclosure", "clawRunHistory",
                        "clawApprovedDisclosure", "clawApprovedMemory", "clawMemoryReview"]) {
        const node = document.getElementById(id);
        if (!node) continue;
        node.hidden = true;
        if (node.tagName === "DETAILS") node.open = false;
      }
    }
    window.PadiemChatMemoryReview?.sync?.();
    // One shared follow state for Chat and Claw: a new conversation starts
    // from "latest" and hides the jump control.
    window.__padiemConversationMotion?.reset?.();
    // Leaving for home drops any pending Claw execute recovery timer/state.
    deps.clearClawRecovery({ syncControls: true });
    deps.clearClawWait();
    deps.setNavActive();
    deps.input.value = "";
    deps.renderProjectState();
    deps.updateComposer();
    deps.closeSidebar();
    deps.input.focus();
  }
  function resetConversation(preserveProject = true) {
    if (deps.conversationProduct === deps.PRODUCT_CLAW && deps.shell.dataset.state === "claw") {
      deps.switchConversationProduct(deps.PRODUCT_CHAT);
      deps.shell.dataset.state = "chat";
      deps.setNavActive();
      window.PadiemChatMemoryReview?.sync?.();
      deps.closeSidebar();
      deps.input.focus();
      return;
    }
    deps.resetConversationView(preserveProject);
  }
  function approvalDecisionErrorMessage(data, response) {
    const code = data && data.error && typeof data.error.code === "string" ? data.error.code : "";
    const status = response ? response.status : 0;
    if (code === "unauthorized" || status === 401) return deps.clawT("claw-error-auth-needed");
    if (code === "approval_not_available" || status === 404) return deps.clawT("claw-approval-not-available");
    return deps.clawT("claw-approval-error");
  }
  function approvedMemoryErrorMessage(data, response) {
    const code = data && data.error && typeof data.error.code === "string" ? data.error.code : "";
    const status = response ? response.status : 0;
    if (code === "explicit_approval_required") return deps.clawT("claw-memory-error-approval");
    if (code === "invalid_proposal" || code === "invalid_payload" || code === "forbidden_owner_field") return deps.clawT("claw-memory-error-invalid");
    if (code === "unauthorized" || status === 401) return deps.clawT("claw-memory-error-auth");
    if (code === "approved_memory_unavailable" || code === "approved_memory_write_failed" || code === "approved_memory_read_failed" || status === 503) return deps.clawT("claw-memory-error-unavailable");
    if (code === "approved_memory_not_found" || status === 404) return deps.clawT("claw-memory-error-not-found");
    return deps.clawT("claw-memory-error-generic");
  }
      return {
        attachmentCopy,
        showComposerInlineHint,
        updateComposer,
        showConversation,
        addUserMessage,
        renderAnswer,
        renderStreamError,
        clearAttachment,
        attachmentCountLimit,
        attachmentTrayNote,
        removeAttachmentItem,
        renderAttachmentChips,
        addAttachmentFiles,
        attachmentPayload,
        safeLocalUiMessage,
        resetConversationView,
        resetConversation,
        approvalDecisionErrorMessage,
        approvedMemoryErrorMessage,
      };
    },
  };
})();
