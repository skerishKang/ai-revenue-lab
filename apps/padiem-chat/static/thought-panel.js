(() => {
  "use strict";

  const thoughtByArticle = new WeakMap();

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
      const paragraph = document.createElement("p");
      details.append(label, paragraph);
      body.insertBefore(details, content);
    } else {
      const label = details.querySelector("summary");
      if (label) label.textContent = activeLabel;
    }
    return details;
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

    const details = panelFor(article, options.activeLabel || "");
    const paragraph = details && details.querySelector("p");
    if (paragraph) {
      const sanitize = typeof options.sanitize === "function"
        ? options.sanitize : (value) => value;
      paragraph.textContent = sanitize(state.text);
    }
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

  window.PadiemChatThoughtPanel = Object.freeze({ handleFrame, settle });
})();
