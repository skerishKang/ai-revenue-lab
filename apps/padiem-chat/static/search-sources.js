(() => {
  "use strict";

  const messageList = document.getElementById("messageList");
  const input = document.getElementById("messageInput");
  const runtimeNote = document.getElementById("runtimeNote");
  const attachmentThumb = document.getElementById("attachmentThumb");
  const toolButtons = Array.from(document.querySelectorAll(".composer-tools .tool-button"));
  const webSearchButton = toolButtons.find((button) => button.textContent.includes("웹 검색"));
  const starters = Array.from(document.querySelectorAll(".starter"));
  const webSearchStarter = starters.find((button) => button.textContent.includes("웹에서 찾아줘"));

  if (!messageList || !input || !webSearchButton || !webSearchStarter) return;

  const nativeFetch = window.fetch.bind(window);
  const starterStatus = webSearchStarter.querySelector("small");
  let webReady = false;
  let searchActive = false;
  let searchInFlight = false;
  let retrySearchPending = false;
  let retryOverride = false;

  webSearchButton.id = webSearchButton.id || "webSearchButton";
  webSearchStarter.id = webSearchStarter.id || "webSearchStarterButton";
  webSearchButton.setAttribute("aria-pressed", "false");
  webSearchStarter.setAttribute("aria-pressed", "false");

  function setNote(text, state = "normal") {
    if (!runtimeNote) return;
    runtimeNote.textContent = text;
    runtimeNote.dataset.state = state;
  }

  function imageSelected() {
    return Boolean(attachmentThumb && !attachmentThumb.hidden && attachmentThumb.getAttribute("src"));
  }

  function syncControls() {
    const unavailable = !webReady || searchInFlight;
    webSearchButton.disabled = unavailable;
    webSearchButton.setAttribute("aria-disabled", unavailable ? "true" : "false");
    webSearchStarter.disabled = unavailable;
    webSearchStarter.setAttribute("aria-disabled", unavailable ? "true" : "false");
    webSearchButton.setAttribute("aria-pressed", searchActive ? "true" : "false");
    webSearchStarter.setAttribute("aria-pressed", searchActive ? "true" : "false");
    webSearchButton.classList.toggle("is-active", searchActive);
    webSearchStarter.classList.toggle("is-active", searchActive);

    if (webReady) {
      webSearchButton.title = searchActive
        ? "웹 검색 사용 중 · 누르면 해제합니다"
        : "다음 질문을 웹에서 찾아 출처와 함께 답합니다";
      if (starterStatus) {
        starterStatus.textContent = searchActive ? "다음 질문에서 사용" : "최신 정보 · 출처와 함께";
      }
    } else {
      webSearchButton.title = "웹 검색은 현재 사용할 수 없습니다";
      if (starterStatus) starterStatus.textContent = "웹 검색 · 준비 중";
    }
  }

  function setSearchActive(next, announce = true) {
    if (!webReady || searchInFlight) return false;
    if (next && imageSelected()) {
      searchActive = false;
      syncControls();
      if (announce) setNote("사진 첨부와 웹 검색은 한 질문에서 함께 사용할 수 없습니다.", "error");
      return false;
    }
    searchActive = Boolean(next);
    syncControls();
    if (announce) {
      setNote(
        searchActive
          ? "다음 질문은 웹에서 찾아 출처와 함께 답합니다."
          : "웹 검색을 사용하지 않습니다."
      );
    }
    return true;
  }

  function chatRequest(inputValue) {
    if (typeof inputValue === "string") return inputValue === "/api/chat" || inputValue.endsWith("/api/chat");
    if (inputValue instanceof Request) {
      try {
        return new URL(inputValue.url, window.location.href).pathname === "/api/chat";
      } catch (_) {
        return false;
      }
    }
    if (inputValue instanceof URL) return inputValue.pathname === "/api/chat";
    return false;
  }

  function addSearchTool(init) {
    if (!init || typeof init.body !== "string") return null;
    let payload;
    try {
      payload = JSON.parse(init.body);
    } catch (_) {
      return null;
    }
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) return null;
    if (payload.tool !== undefined || payload.tool_input !== undefined) return null;
    payload.tool = "web_search";
    return { ...init, body: JSON.stringify(payload) };
  }

  function currentAssistantArticle() {
    const articles = messageList.querySelectorAll(".assistant-message");
    return articles.length ? articles[articles.length - 1] : null;
  }

  function publicSourceUrl(value) {
    if (typeof value !== "string" || !value.trim()) return null;
    try {
      const url = new URL(value);
      if (url.protocol !== "http:" && url.protocol !== "https:") return null;
      return url;
    } catch (_) {
      return null;
    }
  }

  function renderSources(article, evidence) {
    if (!(article instanceof Element) || !article.isConnected || !Array.isArray(evidence)) return;
    const content = article.querySelector(".assistant-content");
    if (!content || content.querySelector(".error-box")) return;

    const existing = content.querySelector(".answer-sources");
    if (existing) existing.remove();

    const safeItems = evidence
      .slice(0, 5)
      .map((item, index) => ({ item, index, url: publicSourceUrl(item && item.url) }))
      .filter((entry) => entry.item && entry.url);
    if (!safeItems.length) return;

    const section = document.createElement("section");
    section.className = "answer-sources";
    section.setAttribute("aria-label", "답변 출처");

    const heading = document.createElement("h3");
    heading.className = "answer-sources-title";
    heading.textContent = "출처";

    const list = document.createElement("ol");
    list.className = "answer-sources-list";

    safeItems.forEach(({ item, index, url }) => {
      const row = document.createElement("li");
      row.className = "answer-source-item";

      const anchor = document.createElement("a");
      anchor.className = "answer-source-link";
      anchor.href = url.href;
      anchor.target = "_blank";
      anchor.rel = "noopener noreferrer";

      const number = document.createElement("span");
      number.className = "answer-source-number";
      number.textContent = `[${index + 1}]`;

      const copy = document.createElement("span");
      copy.className = "answer-source-copy";

      const title = document.createElement("strong");
      title.textContent = typeof item.title === "string" && item.title.trim() ? item.title.trim() : url.hostname;

      const host = document.createElement("small");
      host.textContent = url.hostname;

      copy.append(title, host);
      anchor.append(number, copy);
      row.appendChild(anchor);
      list.appendChild(row);
    });

    section.append(heading, list);
    content.appendChild(section);
  }

  function scheduleSources(article, evidence, attempt = 0) {
    window.setTimeout(() => {
      if (!(article instanceof Element) || !article.isConnected) return;
      const content = article.querySelector(".assistant-content");
      if (!content) return;
      if (content.querySelector(".typing") && attempt < 20) {
        scheduleSources(article, evidence, attempt + 1);
        return;
      }
      renderSources(article, evidence);
    }, attempt === 0 ? 0 : 25);
  }

  window.fetch = async (inputValue, init) => {
    const isChat = chatRequest(inputValue);
    const wantsSearch = isChat && searchActive;
    let searchRequest = false;
    let nextInit = init;
    let article = null;

    if (wantsSearch) {
      const blockedByImage = imageSelected() && !retryOverride;
      if (blockedByImage) {
        searchActive = false;
        retryOverride = false;
        syncControls();
        setNote("사진 첨부와 웹 검색은 한 질문에서 함께 사용할 수 없습니다.", "error");
      } else {
        const augmented = addSearchTool(init);
        if (augmented) {
          searchRequest = true;
          nextInit = augmented;
          article = currentAssistantArticle();
          searchActive = false;
          searchInFlight = true;
          retryOverride = false;
          syncControls();
        }
      }
    }

    try {
      const response = await nativeFetch(inputValue, nextInit);
      if (searchRequest) {
        if (!response.ok) {
          retrySearchPending = true;
        } else {
          retrySearchPending = false;
          response.clone().json().then((data) => {
            if (
              data
              && data.answer_status === "answered_with_evidence"
              && data.tool
              && data.tool.id === "web_search"
              && Array.isArray(data.evidence)
            ) {
              scheduleSources(article, data.evidence);
            }
          }).catch(() => {});
        }
      }
      return response;
    } catch (error) {
      if (searchRequest) retrySearchPending = true;
      throw error;
    } finally {
      if (searchRequest) {
        searchInFlight = false;
        syncControls();
      }
    }
  };

  webSearchButton.addEventListener("click", () => setSearchActive(!searchActive));
  webSearchStarter.addEventListener("click", () => {
    if (setSearchActive(true)) input.focus();
  });

  messageList.addEventListener("click", (event) => {
    const target = event.target instanceof Element ? event.target.closest(".retry-button") : null;
    if (!target || !retrySearchPending || !webReady) return;
    searchActive = true;
    retryOverride = true;
    retrySearchPending = false;
    syncControls();
  }, true);

  if (attachmentThumb) {
    const attachmentObserver = new MutationObserver(() => {
      if (imageSelected() && searchActive && !retryOverride) {
        searchActive = false;
        syncControls();
        setNote("사진을 선택해 웹 검색이 해제되었습니다. 사진과 웹 검색은 한 질문에서 함께 사용할 수 없습니다.", "error");
      }
    });
    attachmentObserver.observe(attachmentThumb, { attributes: true, attributeFilter: ["hidden", "src"] });
  }

  async function loadCapability() {
    try {
      const response = await nativeFetch("/health", { headers: { "Accept": "application/json" }, cache: "no-store" });
      const data = await response.json().catch(() => null);
      webReady = Boolean(response.ok && data && data.web_tools_ready === true);
    } catch (_) {
      webReady = false;
    }
    if (!webReady) searchActive = false;
    syncControls();
  }

  syncControls();
  loadCapability();
})();
