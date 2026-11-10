// #7216 R5 step 3 - recent conversations menu (moved out of the app.js closure).
// No behavior, copy, DOM id or event name change. Shared state and DOM refs are
// read/written only through the deps getters/setters. app.js keeps the same-named
// one-line forwarders.
(() => {
  "use strict";
  window.PadiemChatHistoryModule = {
    create(deps) {
  function renderTyping(article) {
    const content = article.querySelector(".assistant-content");
    content.replaceChildren();
    // #5559: the waiting state is the status card, so the answer body keeps
    // only the marker the sources and export flows read. It no longer draws a
    // second set of waiting dots, and it no longer repeats the status for a
    // screen reader.
    const typing = document.createElement("span");
    typing.className = "typing";
    typing.setAttribute("aria-hidden", "true");
    content.appendChild(typing);
  }
  function clearHistoryUI() {
    deps.clawConversationIds.clear();
    deps.clawConversationLabelsRead = null;
    deps.historyList.replaceChildren();
    deps.historySection.hidden = true;
    deps.historyEmpty.hidden = true;
    clearHistoryActionStatus();
  }
  // #6119: the recent list is loading, never blank. The sidebar shows gray
  // rows until the answer lands, and a read that produced no answer asks one
  // more time — a failure is drawn as one honest retry row, never as an
  // empty list.
  function renderHistorySkeleton() {
    clearHistoryActionStatus();
    deps.historySection.hidden = false;
    deps.historyEmpty.hidden = true;
    deps.historyList.replaceChildren();
    for (let index = 0; index < 4; index += 1) {
      const row = document.createElement("div");
      row.className = "history-row history-skeleton";
      row.setAttribute("aria-hidden", "true");
      deps.historyList.appendChild(row);
    }
  }
  function renderHistoryLoadFailed() {
    deps.historySection.hidden = false;
    deps.historyEmpty.hidden = true;
    deps.historyList.replaceChildren();
    const row = document.createElement("div");
    row.className = "history-row history-load-failed";
    const text = document.createElement("span");
    text.className = "history-load-failed-text";
    text.textContent = deps.uiT("history-load-failed");
    const retry = document.createElement("button");
    retry.type = "button";
    retry.className = "history-retry";
    retry.textContent = deps.uiT("history-retry");
    retry.addEventListener("click", () => {
      void loadRecentConversations();
    });
    row.append(text, retry);
    deps.historyList.appendChild(row);
  }
  async function fetchRecentConversations() {
    const response = await fetch("/api/conversations", { headers: { "Accept": "application/json" }, cache: "no-store" });
    const data = await response.json().catch(() => null);
    if (!response.ok || !data || !Array.isArray(data.conversations)) throw new Error("history unavailable");
    return data;
  }
  async function loadRecentConversations() {
    if (!deps.authState.authenticated || !deps.authState.history_ready) {
      clearHistoryUI();
      return;
    }
    const epoch = deps.authViewEpoch;
    const sequence = ++deps.historyReadSequence;
    deps.clawConversationLabelsRead = null;
    const current = () => epoch === deps.authViewEpoch && sequence === deps.historyReadSequence && deps.authState.authenticated;
    renderHistorySkeleton();
    let data = null;
    for (let attempt = 0; attempt < 2; attempt += 1) {
      try {
        data = await fetchRecentConversations();
        if (!current()) return;
        break;
      } catch (_) {
        if (!current()) return;
        if (attempt === 1) data = null;
      }
    }
    if (!data) {
      renderHistoryLoadFailed();
      return;
    }
    try {
      // Labels are presentation only; run history is owner-filtered by the server.
      // Never infer a Claw execution authority from a title or browser storage.
      const historyButtons = new Map();
      const enrichClawLabels = async () => {
        const verifiedClawIds = new Set();
        try {
          const threadRunHistoryLimit = 30;
          const { response: runsResponse, data: runsData } = await deps.readClawRuns(threadRunHistoryLimit, epoch);
          if (!current()) return;
          if (runsResponse.ok && runsData?.ok === true && Array.isArray(runsData.runs)) {
            runsData.runs.forEach((run) => {
              if (run?.channel === "web"
                  && (run?.action === "general" || String(run?.title || "").startsWith("Claw:"))
                  && run?.status === "completed"
                  && /^chat_[a-f0-9]{32}$/.test(run?.session?.conversation_id || "")) {
                verifiedClawIds.add(run.session.conversation_id);
              }
            });
          }
        } catch (_) { /* No Claw authority can be inferred from a failed read. */ }
        if (!current()) return;
        deps.clawConversationIds.clear();
        verifiedClawIds.forEach((id) => deps.clawConversationIds.add(id));
        historyButtons.forEach(({ button, title }, id) => {
          button.textContent = deps.clawConversationIds.has(id) ? `Claw · ${title}` : title;
        });
      };
      clearHistoryActionStatus();
      deps.clawConversationIds.clear();
      deps.historyList.replaceChildren();
      deps.historySection.hidden = false;
      deps.historyEmpty.hidden = data.conversations.length !== 0;
      let pinnedGroupDrawn = false;
      data.conversations.forEach((conversation) => {
        if (!conversation || typeof conversation.id !== "string" || typeof conversation.title !== "string") return;
        const pinned = conversation.pinned === true;
        // #7175: one explicit group, then the pinned rows in server order.
        if (pinned && !pinnedGroupDrawn) {
          pinnedGroupDrawn = true;
          const groupLabel = document.createElement("p");
          groupLabel.className = "history-group-label";
          groupLabel.textContent = deps.uiT("conversation-pinned-group");
          deps.historyList.appendChild(groupLabel);
        }
        const row = document.createElement("div");
        row.className = pinned ? "history-row history-row-pinned" : "history-row";
        row.dataset.conversationId = conversation.id;
        const button = document.createElement("button");
        button.type = "button";
        button.className = "recent-item history-item";
        button.textContent = deps.clawConversationIds.has(conversation.id)
          ? `Claw · ${conversation.title}` : conversation.title;
        historyButtons.set(conversation.id, { button, title: conversation.title });
        button.addEventListener("click", () => deps.openSavedConversation(conversation.id));
        const actions = document.createElement("details");
        actions.className = "history-actions";
        const more = document.createElement("summary");
        more.className = "history-more";
        const moreLabel = deps.uiT("manage") + ": " + conversation.title;
        more.setAttribute("aria-label", moreLabel);
        window.PadiemSharedTooltip?.label?.(more, moreLabel);
        more.append(deps.sidebarActionIcon("more"));
        const menu = document.createElement("div");
        menu.className = "history-actions-menu";
        // #7175: rename in place. The row is rebuilt from the server answer
        // after a save, so every label (title, tooltips, menu) moves together.
        const rename = document.createElement("button");
        rename.type = "button";
        rename.className = "history-menu-action history-menu-rename";
        rename.append(deps.sidebarActionIcon("rename"), document.createTextNode(deps.uiT("conversation-rename")));
        const renameLabel = deps.uiT("conversation-rename-aria", { title: conversation.title });
        rename.setAttribute("aria-label", renameLabel);
        window.PadiemSharedTooltip?.label?.(rename, renameLabel);
        rename.addEventListener("click", () => {
          actions.open = false;
          beginConversationRename(row, button, conversation);
        });
        const pin = document.createElement("button");
        pin.type = "button";
        pin.className = "history-menu-action history-menu-pin";
        pin.append(
          deps.sidebarActionIcon(pinned ? "unpin" : "pin"),
          document.createTextNode(deps.uiT(pinned ? "conversation-unpin" : "conversation-pin")),
        );
        const pinLabel = deps.uiT(pinned ? "conversation-unpin-aria" : "conversation-pin-aria", { title: conversation.title });
        pin.setAttribute("aria-label", pinLabel);
        window.PadiemSharedTooltip?.label?.(pin, pinLabel);
        pin.addEventListener("click", async () => {
          actions.open = false;
          pin.disabled = true;
          try {
            await patchConversation(conversation.id, { pinned: !pinned });
            clearHistoryActionStatus();
            await loadRecentConversations();
            focusHistoryConversation(conversation.id);
          } catch (error) {
            pin.disabled = false;
            showHistoryActionStatus(error instanceof Error && error.message ? error.message : deps.uiT("conversation-update-failed"));
            more.focus();
          }
        });
        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "history-delete history-menu-delete";
        remove.append(deps.sidebarActionIcon("trash"), document.createTextNode(deps.uiT("delete")));
        remove.setAttribute("aria-label", deps.uiT("conversation-delete-aria", { title: conversation.title }));
        window.PadiemSharedTooltip?.label?.(remove, deps.uiT("conversation-delete-aria", { title: conversation.title }));
        remove.addEventListener("click", async () => {
          await deleteConversation(conversation.id, conversation.title);
          // Dialog close must return focus to a visible action, not an item
          // concealed inside a closed native details panel.
          if (actions.isConnected) {
            actions.open = false;
            more.focus();
          }
        });
        actions.addEventListener("toggle", () => {
          if (!actions.open) return;
          deps.historyList.querySelectorAll(".history-actions[open]").forEach((other) => {
            if (other !== actions) other.open = false;
          });
        });
        menu.append(rename, pin, remove);
        actions.append(more, menu);
        row.append(button, actions);
        deps.historyList.appendChild(row);
      });
      // Optional thread labels never hold the conversation list behind an
      // independent identity/Engine read. The list is already usable here.
      if (data.conversations.length) {
        deps.clawConversationLabelsRead = { epoch, promise: enrichClawLabels() };
      }
    } catch (_) {
      // #6119: a read that landed but could not render is still a failure —
      // the retry row says so instead of painting an empty list.
      renderHistoryLoadFailed();
    }
  }
  function clearHistoryActionStatus() {
    if (!deps.historyActionStatus) return;
    deps.historyActionStatus.hidden = true;
    deps.historyActionStatus.textContent = "";
  }
  function showHistoryActionStatus(message) {
    if (!deps.historyActionStatus || !message) return;
    deps.historyActionStatus.textContent = message;
    deps.historyActionStatus.hidden = false;
  }
  async function patchConversation(id, body) {
    const response = await fetch(`/api/conversations/${encodeURIComponent(id)}`, {
      method: "PATCH",
      headers: { "Accept": "application/json", "Content-Type": "application/json" },
      cache: "no-store",
      body: JSON.stringify(body),
    });
    const data = await response.json().catch(() => null);
    if (!response.ok || !data || data.updated !== true || !data.conversation
        || data.conversation.id !== id) {
      const message = data && data.error && typeof data.error.message === "string"
        ? data.error.message
        : deps.uiT("conversation-update-failed");
      throw new Error(message);
    }
    return data.conversation;
  }
  function focusHistoryConversation(id) {
    const row = Array.from(deps.historyList.querySelectorAll(".history-row"))
      .find((candidate) => candidate.dataset.conversationId === id);
    const target = row ? (row.querySelector(".history-more") || row.querySelector(".history-item")) : null;
    if (target && typeof target.focus === "function") target.focus({ preventScroll: true });
  }
  function beginConversationRename(row, button, conversation) {
    if (!deps.authState.authenticated || deps.inFlight) return;
    if (row.querySelector(".history-rename-input")) return;
    const input = document.createElement("input");
    input.type = "text";
    input.className = "history-rename-input";
    input.maxLength = deps.HISTORY_TITLE_MAX_CHARS;
    input.value = conversation.title;
    input.setAttribute("aria-label", deps.uiT("conversation-rename-aria", { title: conversation.title }));
    input.setAttribute("enterkeyhint", "done");
    let saving = false;
    let closed = false;
    const restore = () => {
      if (!input.isConnected) return;
      input.replaceWith(button);
      button.focus();
    };
    const cancel = () => {
      if (saving || closed) return;
      closed = true;
      clearHistoryActionStatus();
      restore();
    };
    const save = async () => {
      if (saving || closed) return;
      const title = input.value.trim().replace(/\s+/g, " ");
      if (!title) {
        input.setAttribute("aria-invalid", "true");
        showHistoryActionStatus(deps.uiT("conversation-title-required"));
        input.focus();
        return;
      }
      saving = true;
      input.removeAttribute("aria-invalid");
      input.disabled = true;
      try {
        const updated = await patchConversation(conversation.id, { title });
        conversation.title = updated.title;
        button.textContent = deps.clawConversationIds.has(conversation.id)
          ? `Claw · ${updated.title}` : updated.title;
        clearHistoryActionStatus();
        if (input.isConnected) input.replaceWith(button);
        await loadRecentConversations();
        focusHistoryConversation(conversation.id);
      } catch (error) {
        saving = false;
        input.disabled = false;
        input.setAttribute("aria-invalid", "true");
        showHistoryActionStatus(
          error instanceof Error && error.message ? error.message : deps.uiT("conversation-update-failed"),
        );
        input.focus();
      }
    };
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        event.stopPropagation();
        void save();
      } else if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        cancel();
      }
    });
    input.addEventListener("blur", () => {
      if (!saving) cancel();
    });
    row.replaceChild(input, button);
    input.focus();
    input.select();
  }
  async function deleteConversation(id, title) {
    if (!deps.authState.authenticated || deps.inFlight) return;
    const confirmed = await window.PadiemConfirmDialog.confirm({
      title: deps.uiT("conversation-delete-title"),
      message: deps.uiT("conversation-delete-message", { title }),
      cancelLabel: deps.uiT("cancel"),
      confirmLabel: deps.uiT("delete"),
    });
    if (!confirmed) return;
    try {
      const response = await fetch(`/api/conversations/${encodeURIComponent(id)}`, {
        method: "DELETE",
        headers: { "Accept": "application/json" },
        cache: "no-store",
      });
      const data = await response.json().catch(() => null);
      if (!response.ok || !data || data.deleted !== true || data.conversation_id !== id) {
        const message = data && data.error && typeof data.error.message === "string"
          ? data.error.message
          : deps.uiT("conversation-delete-failed");
        throw new Error(message);
      }
      const deletedActiveConversation = deps.conversationState.getConversationId() === id;
      if (deletedActiveConversation) deps.resetConversationView(true);
      await loadRecentConversations();
      if (deletedActiveConversation) {
        deps.input.focus();
      } else {
        deps.setNote(deps.idleNote());
      }
    } catch (error) {
      deps.setNote(error instanceof Error ? error.message : deps.uiT("conversation-delete-failed"), "error");
    }
  }
  function clearClawRunHistoryPdfPreviews() {
    for (const controller of deps.clawRunHistoryPdfControllers) controller.destroy();
    deps.clawRunHistoryPdfControllers.clear();
  }
  function setClawRunHistoryStatus(message, code = "") {
    if (!deps.clawRunHistoryError) return;
    if (!message) {
      deps.clawRunHistoryError.hidden = true;
      deps.clawRunHistoryError.textContent = "";
      deps.clawRunHistoryError.removeAttribute("data-state");
      return;
    }
    deps.clawRunHistoryError.hidden = false;
    deps.clawRunHistoryError.textContent = message;
    const reference = deps.failureCodeNote(code, "");
    if (reference) deps.clawRunHistoryError.appendChild(reference);
    deps.clawRunHistoryError.dataset.state = "error";
  }
  function clawRunHistoryErrorMessage(data, response) {
    const code = data && data.error && typeof data.error.code === "string" ? data.error.code : "";
    const status = response ? response.status : 0;
    if (code === "unauthorized" || status === 401) return deps.clawT("claw-error-auth-needed");
    return deps.clawT("claw-runs-error");
  }
  // Unguarded fetch: callers hold the single-flight flag while awaiting this.
  async function fetchClawRunHistory(options) {
    if (!deps.clawRunHistory) return;
    const focusRunId = deps.pendingClawRunFocusId;
    deps.pendingClawRunFocusId = "";
    const visibilityEpoch = deps.clawRunHistoryVisibilityEpoch;
    setClawRunHistoryStatus("");
    if (deps.clawRunHistoryLoading) deps.clawRunHistoryLoading.hidden = false;
    if (deps.clawRunHistoryList) deps.clawRunHistoryList.hidden = true;
    if (deps.clawRunHistoryEmpty) deps.clawRunHistoryEmpty.hidden = true;
    if (deps.clawRunHistoryExpand) deps.clawRunHistoryExpand.hidden = true;
    // On refresh, retire the old cards before dropping their DOM and PDF Blob.
    clearClawRunHistoryPdfPreviews();
    if (deps.clawRunHistoryList) deps.clawRunHistoryList.replaceChildren();
    try {
      const { response, data } = await deps.readClawRuns(deps.clawRunHistoryLimit, deps.authViewEpoch, options);
      // A response begun before logout/workspace departure is not a license
      // to paint old owner file cards into a newer authenticated session.
      if (visibilityEpoch !== deps.clawRunHistoryVisibilityEpoch ||
          deps.authState.authenticated !== true || deps.clawRunHistory.hidden) return;
      if (!response.ok || !data || data.ok !== true || !Array.isArray(data.runs)) {
        throw deps.mappedUiError(clawRunHistoryErrorMessage(data, response), data);
      }
      if (deps.clawRunHistoryLoading) deps.clawRunHistoryLoading.hidden = true;
      const includeGeneral = typeof window !== "undefined"
        && window.__padiemClawRunHistoryIncludeGeneral === true;
      const visibleRuns = data.runs.filter((run) => {
        if (!run || typeof run.run_id !== "string") return false;
        if (includeGeneral || (focusRunId && run.run_id === focusRunId)) return true;
        return !(run.action === "general" && !run.artifact && (run.status === "completed" || !run.status));
      });
      if (visibleRuns.length === 0) {
        // Empty history must not leave an empty list container visible.
        if (deps.clawRunHistoryEmpty) deps.clawRunHistoryEmpty.hidden = false;
        return;
      }
      if (deps.clawRunHistoryList) deps.clawRunHistoryList.hidden = false;
      // Equal to the requested limit suggests (but does not prove) older runs.
      // Never invent a count or claim further runs exist until the next GET.
      if (deps.clawRunHistoryExpand) deps.clawRunHistoryExpand.hidden =
        deps.clawRunHistoryLimit !== 10 || data.runs.length < 10;
      visibleRuns.forEach((run) => {
        deps.clawRunHistoryList?.appendChild(deps.renderClawRunCard(run));
      });
      if (focusRunId && deps.clawRunHistoryList) {
        const target = Array.from(deps.clawRunHistoryList.children).find((card) => card.dataset && card.dataset.runId === focusRunId);
        if (target) {
          // #4488 Phase A: open the disclosure before focusing a specific run.
          if (deps.clawRunHistoryDisclosure) deps.clawRunHistoryDisclosure.open = true;
          target.setAttribute("tabindex", "-1");
          target.focus?.();
          target.scrollIntoView?.();
        }
      }
    } catch (error) {
      if (visibilityEpoch !== deps.clawRunHistoryVisibilityEpoch ||
          deps.authState.authenticated !== true || deps.clawRunHistory.hidden) return;
      if (deps.clawRunHistoryLoading) deps.clawRunHistoryLoading.hidden = true;
      if (deps.clawRunHistoryExpand) deps.clawRunHistoryExpand.hidden = true;
      setClawRunHistoryStatus(deps.safeLocalUiMessage(error, deps.clawT("claw-runs-error")), error?.code);
    }
  }
  async function loadClawRunHistory(options) {
    if (deps.clawRunHistoryInFlight) return;
    deps.clawRunHistoryInFlight = true;
    try {
      await fetchClawRunHistory(options);
    } finally {
      deps.clawRunHistoryInFlight = false;
    }
  }
  function syncClawRunHistoryVisibility() {
    if (!deps.clawRunHistory) return;
    // Owner-authenticated surface only.
    const wasVisible = deps.clawRunHistory.hidden === false;
    const show = deps.authState.authenticated === true
      && (deps.shell.dataset.state === "claw" || deps.shell.dataset.state === "chat");
    deps.clawRunHistory.hidden = !show;
    if (deps.clawRunHistoryDisclosure) deps.clawRunHistoryDisclosure.hidden = !show;
    if (show) {
      // Coming back to the workspace is a request for the current list; the
      // first reveal may share the read the sidebar already started.
      const returning = deps.clawRunHistoryLeftSurface;
      deps.clawRunHistoryLeftSurface = false;
      loadClawRunHistory(returning ? { force: true } : undefined);
    }
    else {
      if (wasVisible) deps.clawRunHistoryLeftSurface = true;
      deps.clawRunHistoryVisibilityEpoch += 1;
      deps.clawRunHistoryLimit = 10;
      if (typeof window !== "undefined") window.__padiemClawRunHistoryIncludeGeneral = false;
      if (deps.clawRunHistoryExpand) deps.clawRunHistoryExpand.hidden = true;
      clearClawRunHistoryPdfPreviews();
    }
  }
      return {
        renderTyping,
        clearHistoryUI,
        renderHistorySkeleton,
        renderHistoryLoadFailed,
        fetchRecentConversations,
        loadRecentConversations,
        clearHistoryActionStatus,
        showHistoryActionStatus,
        patchConversation,
        focusHistoryConversation,
        beginConversationRename,
        deleteConversation,
        clearClawRunHistoryPdfPreviews,
        setClawRunHistoryStatus,
        clawRunHistoryErrorMessage,
        fetchClawRunHistory,
        loadClawRunHistory,
        syncClawRunHistoryVisibility,
      };
    },
  };
})();
