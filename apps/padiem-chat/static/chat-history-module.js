// #7216 R5 step 3 / #7812 R5 B3 - recent conversations menu (moved out of the app.js closure).
// B3 moved the Claw run-history panel functions (clearClawRunHistoryPdfPreviews, ...)
// to chat-run-history-module.js and the document click/keydown menu listeners into wire().
// No behavior, copy, DOM id or event name change. Shared state and DOM refs are
// read/written only through the deps getters/setters. app.js keeps the same-named
// one-line forwarders.
(() => {
  "use strict";
  window.PadiemChatHistoryModule = {
    create(deps) {
      // #7812 R5 B3: the sidebar's own read generation and title cap live here;
      // they are used only by this module, so create() owns them without reading
      // deps (rule (a)).
      let historyReadSequence = 0;
      const HISTORY_TITLE_MAX_CHARS = 80;

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
    const sequence = ++historyReadSequence;
    deps.clawConversationLabelsRead = null;
    const current = () => epoch === deps.authViewEpoch && sequence === historyReadSequence && deps.authState.authenticated;
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
      // #7365: the tool lanes label connector-originated PC command rows with
      // a fixed server-side literal (the tool-request title). This constant is
      // a data matcher against that label — it is never rendered on screen —
      // so it mirrors the exact bytes with unicode escapes instead of adding
      // hardcoded display copy to the shipped sources.
      const TOOL_REQUEST_PREFIX = "\uc678\ubd80 AI \ub3c4\uad6c \uc694\uccad:";
      const toolRequestRows = [];
      let normalConversationCount = 0;
      deps.historyEmpty.hidden = data.conversations.length !== 0;
      let pinnedGroupDrawn = false;
      data.conversations.forEach((conversation) => {
        if (!conversation || typeof conversation.id !== "string" || typeof conversation.title !== "string") return;
        const isToolRequest = conversation.title.startsWith(TOOL_REQUEST_PREFIX);
        if (!isToolRequest) normalConversationCount += 1;
        const pinned = conversation.pinned === true;
        // #7175: one explicit group, then the pinned rows in server order.
        if (pinned && !pinnedGroupDrawn && !isToolRequest) {
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
          // #8013: pick the vertical direction from the room the list really
          // has, so the plate stays inside the list instead of clipping at its
          // top edge. Only a plate whose sheet opted in (--menu-direction:
          // room-based — the Glass frame sheet) gets the inline top/bottom;
          // every other theme keeps the shared below-the-row placement.
          if (getComputedStyle(menu).getPropertyValue("--menu-direction")
              !== "room-based") return;
          let clip = actions.parentElement;
          while (clip && clip !== document.body) {
            const flow = getComputedStyle(clip).overflowY;
            if (flow === "auto" || flow === "scroll") break;
            clip = clip.parentElement;
          }
          if (!clip || clip === document.body) return;
          const clipRect = clip.getBoundingClientRect();
          const rowRect = actions.getBoundingClientRect();
          const roomAbove = rowRect.top - clipRect.top;
          const roomBelow = clipRect.bottom - rowRect.bottom;
          // Open toward the roomier side. A plate opening upward covers only
          // its own row and the rows before it (it outranks their glass
          // stacking contexts), while a plate reaching downward is painted
          // over by the row after it — so a row with room below keeps the
          // shared downward placement and a row at the list's end flips up.
          if (roomAbove >= roomBelow) {
            menu.style.top = "auto";
            menu.style.bottom = "2px";
          } else {
            menu.style.removeProperty("top");
            menu.style.removeProperty("bottom");
          }
          actions.dataset.menuPlaced = "1";
        });
        menu.append(rename, pin, remove);
        actions.append(more, menu);
        row.append(button, actions);
        // #7365: a connector-originated PC command record lists inside the
        // collapsed tool-request group, not the person's conversation list.
        if (isToolRequest) {
          toolRequestRows.push(row);
          return;
        }
        deps.historyList.appendChild(row);
      });
      if (toolRequestRows.length) {
        const toolGroup = document.createElement("details");
        toolGroup.className = "history-tool-requests";
        const summary = document.createElement("summary");
        summary.className = "history-group-label history-tool-requests-summary";
        summary.textContent = deps.uiT("history-tool-request-group");
        summary.setAttribute("aria-label",
          `${deps.uiT("history-tool-request-group")} (${toolRequestRows.length})`);
        toolGroup.append(summary, ...toolRequestRows);
        deps.historyList.appendChild(toolGroup);
      }
      deps.historyEmpty.hidden = normalConversationCount !== 0;
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
    input.maxLength = HISTORY_TITLE_MAX_CHARS;
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
      // #7812 R5 B3 (rule (b), R-11): document click/keydown for the recent
      // menu register from app.js at the original listener block, so their order
      // among the other document listeners is unchanged.
      function wireMenuListeners() {
        document.addEventListener("click", (event) => {
          if (event.target instanceof Element && event.target.closest(".history-actions")) return;
          deps.historyList.querySelectorAll(".history-actions[open]").forEach((node) => { node.open = false; });
        });
        document.addEventListener("keydown", (event) => {
          if (event.key !== "Escape") return;
          const expanded = deps.historyList.querySelector(".history-actions[open]");
          if (!expanded) return;
          expanded.open = false;
          expanded.querySelector("summary")?.focus();
          event.stopPropagation();
        });
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
        wireMenuListeners,
      };
    },
  };
})();
