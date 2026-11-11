(() => {
  "use strict";

  const thoughtByArticle = new WeakMap();
  // #7459: a thought transcript can name the internal tool that produced it
  // (`claw.pc.query_drives`). That identifier is implementation detail, never
  // copy: the reader sees a neutral phrase instead.
  const INTERNAL_TOOL_IDENTIFIER = /\b(?:claw|padiem|mcp|tool)(?:\.[A-Za-z0-9_-]+)+\b/gi;
  // #7469 follow-up: padiem.net, chat.padiem.net and URLs/email addresses that
  // contain them are product addresses, not tool identifiers. Mask those spans
  // first so only tool-call names (claw.pc_shell, padiem.drive.read) are hidden.
  const PUBLIC_ADDRESS = /(?:[a-z][a-z0-9+.-]*:\/\/|www\.)[^\s<>"'`]+|[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}|\b(?:[a-z0-9-]+\.)+(?:com|net|org|io|co|kr|ai|app|dev|cloud|site|info|biz|me|tv|us|uk|jp)\b(?:\/[^\s<>"'`]*)?/gi;
  const INTERNAL_TOOL_HIDDEN_KEY = "internal-tool-hidden";
  const INTERNAL_TOOL_HIDDEN_FALLBACK = "[internal tool hidden]";
  const WORK_STATUS_SELECTOR = ".capability-kit";

  function internalToolHiddenCopy() {
    try {
      const copy = window.__padiemLocale?.text?.(INTERNAL_TOOL_HIDDEN_KEY);
      if (typeof copy === "string" && copy) return copy;
    } catch (_) {
      // Fall through to the neutral default below.
    }
    return INTERNAL_TOOL_HIDDEN_FALLBACK;
  }

  function hideToolIdentifiers(segment, copy) {
    return segment.replace(INTERNAL_TOOL_IDENTIFIER, () => copy);
  }

  function scrubInternalToolNames(value) {
    const text = String(value ?? "");
    const copy = internalToolHiddenCopy();
    let scrubbed = "";
    let cursor = 0;
    for (const match of text.matchAll(PUBLIC_ADDRESS)) {
      scrubbed += hideToolIdentifiers(text.slice(cursor, match.index), copy);
      scrubbed += match[0];
      cursor = match.index + match[0].length;
    }
    return scrubbed + hideToolIdentifiers(text.slice(cursor), copy);
  }

  function paintText(container, text) {
    if (!container) return;
    const api = window.PadiemRichResponse;
    if (api && typeof api.render === "function") {
      try {
        if (api.render(container, text) !== false) return;
      } catch (_) {
        // Fall through to the plain-text copy below.
      }
    }
    container.textContent = text;
  }

  // The order is a product contract: work status (AI 작업 상태) first, then the
  // thought transcript, then the answer. A panel created before the status
  // card must not jump above it.
  function placePanel(body, content, details) {
    const status = body.querySelector(WORK_STATUS_SELECTOR);
    if (!status || status.parentElement !== body) {
      body.insertBefore(details, content);
      return;
    }
    const next = status.nextSibling;
    if (next) body.insertBefore(details, next);
    else body.append(details);
  }

  function textContainer(details) {
    let container = details.querySelector(".orchestration-thought-body")
      || details.querySelector("p");
    if (!container) {
      container = document.createElement("div");
      container.className = "orchestration-thought-body";
      details.append(container);
    }
    return container;
  }

  function panelFor(article, activeLabel) {
    const body = article?.querySelector(".assistant-body");
    const content = article?.querySelector(".assistant-content");
    if (!body || !content) return null;

    let details = body.querySelector(".orchestration-thought-summary");
    if (!details) {
      details = document.createElement("details");
      details.className = "orchestration-thought-summary";
      const label = document.createElement("summary");
      label.textContent = activeLabel;
      const paragraph = document.createElement("div");
      paragraph.className = "orchestration-thought-body";
      details.append(label, paragraph);
      placePanel(body, content, details);
    } else {
      const label = details.querySelector("summary");
      if (label && activeLabel) label.textContent = activeLabel;
    }
    return details;
  }

  function renderSummary(article, text, options = {}) {
    if (!article || typeof text !== "string" || !text) return false;
    const details = panelFor(article, options.label || "");
    if (!details) return false;
    paintText(textContainer(details), scrubInternalToolNames(text));
    return true;
  }

  function handleFrame(article, frame, options = {}) {
    if (!frame || frame.event !== "thought") return false;
    let payload;
    try {
      payload = JSON.parse(frame.data);
    } catch (_) {
      return true;
    }
    const delta = payload && payload.text;
    if (typeof delta !== "string" || !delta) return true;

    const state = thoughtByArticle.get(article) || { text: "" };
    state.text += delta;
    thoughtByArticle.set(article, state);

    const sanitize = typeof options.sanitize === "function"
      ? options.sanitize : (value) => value;
    renderSummary(article, sanitize(state.text), { label: options.activeLabel });
    return true;
  }

  // Called after the work status card is (re)inserted so the contract order
  // holds no matter which surface rendered first.
  function reorder(article) {
    const body = article?.querySelector(".assistant-body");
    const content = article?.querySelector(".assistant-content");
    const details = article?.querySelector(".orchestration-thought-summary");
    if (!body || !content || !details) return false;
    const status = body.querySelector(WORK_STATUS_SELECTOR);
    if (!status || status.parentElement !== body) return false;
    body.insertBefore(details, content);
    return true;
  }

  function settle(article, doneLabel) {
    if (!article || !thoughtByArticle.has(article)) return false;
    const details = article.querySelector(".orchestration-thought-summary");
    if (!details) return false;
    const label = details.querySelector("summary");
    if (label) label.textContent = doneLabel;
    details.open = false;
    return true;
  }

  window.PadiemChatThoughtPanel = Object.freeze({
    handleFrame,
    renderSummary,
    reorder,
    settle,
  });
})();
