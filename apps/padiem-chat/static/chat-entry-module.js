// #7809 T2: saved conversation, submit, and regenerate entry decisions.
(() => {
  "use strict";
  window.PadiemChatEntryModule = {
    create(deps) {
  async function openSavedConversation(id) {
    if (!deps.authState.authenticated || deps.inFlight) return;
    const epoch = deps.authViewEpoch;
    try {
      const response = await fetch(`/api/conversations/${encodeURIComponent(id)}`, { headers: { "Accept": "application/json" }, cache: "no-store" });
      const data = await response.json().catch(() => null);
      if (!response.ok || !data || !data.conversation || !Array.isArray(data.conversation.messages)) throw new Error(deps.uiT("conversation-load-failed"));
      const savedProjectId = typeof data.conversation.project_id === "string" ? data.conversation.project_id : null;
      const restoredProject = savedProjectId ? await deps.ensureProject(savedProjectId) : null;
      if (savedProjectId && !restoredProject) throw new Error(deps.uiT("conversation-project-load-failed"));
      // Paint the list early, but preserve the existing canonical Claw lane
      // classification when the user opens a row before its labels arrive.
      const labels = deps.clawConversationLabelsRead;
      if (labels && labels.epoch === epoch) await labels.promise;
      if (epoch !== deps.authViewEpoch || !deps.authState.authenticated) return false;
      deps.clearAttachment();
      // #2505: the saved thread is the ONE conversation, so it is loaded into
      // the shared store. A thread that has Claw turns still opens on the Claw
      // screen (its last lane), and the other screen shows the same record.
      const isVerifiedClawThread = deps.clawConversationIds.has(data.conversation.id);
      const targetProduct = isVerifiedClawThread ? deps.PRODUCT_CLAW : deps.PRODUCT_CHAT;
      deps.messageList.replaceChildren();
      deps.messageList.hidden = true;
      deps.conversationState.resetProduct?.(targetProduct);
      deps.conversationState.setProduct?.(targetProduct);
      deps.conversationProduct = targetProduct;
      deps.conversationState.setConversationId(data.conversation.id, targetProduct);
      deps.activeProject = restoredProject;
      deps.activeProjectFileCount = 0;
      deps.renderProjectState();
      if (deps.activeProject) deps.refreshActiveProjectFileCount();
      if (isVerifiedClawThread) deps.openClawWorkspace();
      deps.showConversation({ preserveClaw: isVerifiedClawThread, restoreSaved: true });
      deps.syncApprovedMemoryVisibility();
      deps.syncClawRunHistoryVisibility();
      deps.conversationArtifactContext?.show?.(data.conversation.id);
      if (isVerifiedClawThread) deps.clawArtifactShownFor = data.conversation.id;
      data.conversation.messages.forEach((item) => {
        if (!item || typeof item.content !== "string") return;
        if (item.role === "user") deps.addUserMessage(item.content, null, { restored: true });
        if (item.role === "assistant") deps.renderStoredAssistant(item.content, item);
        if (item.role === "user" || item.role === "assistant") deps.conversationState.appendMessage({ role: item.role, content: item.content }, targetProduct);
      });
      // #5895: keep showing a PC turn that is still running on the server, and
      // restore the thread once its stored answer lands.
      void deps.resumeUnfinishedPcRun(data.conversation.id);
      // A restored conversation opens on its newest turn with follow resumed,
      // on the same shared Chat/Claw control.
      window.__padiemConversationMotion?.resume?.();
      deps.closeSidebar();
      deps.input.focus();
      return true;
    } catch (error) {
      deps.setNote(error instanceof Error ? error.message : deps.uiT("conversation-load-failed"), "error");
      return false;
    }
  }
  function clawGeneralRequestActive() {
    return deps.shell.dataset.state === "claw" && !(deps.clawManualForm && !deps.clawManualForm.hidden);
  }
  function storedRegenerateRequest(article) {
    const stored = deps.lastCompletedAnswerRequest;
    if (!stored || stored.article !== article) return null;
    if (!article || !article.isConnected) return null;
    if (!window.PadiemChatLifecycle || !window.PadiemChatLifecycle.isCompleted(article)) return null;
    if (deps.inFlight) return null;
    const list = document.getElementById("messageList");
    const items = list ? list.querySelectorAll(".assistant-message") : [];
    if (!items.length || items[items.length - 1] !== article) return null;
    return stored;
  }
  async function submitPrompt(text, selectedSkill) {
    const prompt = text.trim();
    if (!prompt || deps.inFlight) return;
    if (!deps.requireSessionForModelUse()) return;
    // #3539: snapshot the canonical lane before changing presentation;
    // #3931: keep a general Claw request in the same Claw conversation.
    // Neither UI state nor the selected model ID may authorize fallback.
    const clawGeneralRequest = clawGeneralRequestActive();
    // Chat/Claw separation: the lane decides the product. The conversation id, the turn
    // store and the skill all come from that product's own slot, so a Claw
    // request never carries the Chat conversation id and a Chat request never
    // carries the Claw one. This is an immutable submit-time snapshot.
    const product = clawGeneralRequest ? deps.PRODUCT_CLAW : deps.PRODUCT_CHAT;
    deps.conversationState.setProduct?.(product);
    if (selectedSkill) deps.conversationState.setSkill(selectedSkill);
    const attachmentSnapshot = deps.selectedAttachments;
    const contextSnapshot = { product, conversationId: deps.conversationState.getConversationId(product), project: deps.activeProject };
    // PADIEM Custom is text-only on both Chat and Claw. Refuse attachments
    // here, with the typed prompt preserved.
    const customSelected = Boolean(window.PadiemCustomSelection?.get?.());
    if (customSelected && attachmentSnapshot.length) {
      deps.setNote(deps.uiT("custom-text-only"), "error");
      return;
    }
    // #6828: grade-only Claw execution. The grade travels as `tier` and the
    // server resolves the grade route; no per-request model id is ever sent.
    contextSnapshot.selectedModelId = "";
    deps.showConversation({ preserveClaw: clawGeneralRequest });
    deps.addUserMessage(prompt, attachmentSnapshot);
    deps.input.value = "";
    // #5561: the composer is empty again, so the primary action slot returns
    // to the voice waveform.
    deps.updateComposer();
    const outbound = deps.conversationState.outboundWithUser(prompt);
    const success = await deps.requestAnswer(outbound, deps.conversationState.getSkill(), attachmentSnapshot, contextSnapshot, clawGeneralRequest);
    if (success && deps.selectedAttachments === attachmentSnapshot) deps.clearAttachment();
  }
      return { openSavedConversation, clawGeneralRequestActive, storedRegenerateRequest, submitPrompt };
    },
  };
})();
