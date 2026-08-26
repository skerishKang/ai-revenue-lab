(() => {
  "use strict";

  const messageList = document.getElementById("messageList");
  const input = document.getElementById("messageInput");
  const runtimeNote = document.getElementById("runtimeNote");
  const attachmentThumb = document.getElementById("attachmentThumb");
  const deepResearchButton = document.getElementById("deepResearchButton");
  const toolButtons = Array.from(document.querySelectorAll(".composer-tools .tool-button"));
  const webSearchButton = toolButtons.find((button) => button.textContent.includes("웹 검색"));
  const starters = Array.from(document.querySelectorAll(".starter"));
  const webSearchStarter = starters.find((button) => button.textContent.includes("웹에서 찾아줘"));

  if (!messageList || !input || !webSearchButton || !webSearchStarter || !deepResearchButton) return;

  const nativeFetch = window.fetch.bind(window);
  const starterStatus = webSearchStarter.querySelector("small");
  let webReady = false;
  let researchReady = false;
  let activeTool = null;
  let toolInFlight = null;
  let retryTool = null;
  let retryOverride = false;

  webSearchButton.id = webSearchButton.id || "webSearchButton";
  webSearchStarter.id = webSearchStarter.id || "webSearchStarterButton";
  webSearchButton.setAttribute("aria-pressed", "false");
  webSearchStarter.setAttribute("aria-pressed", "false");
  deepResearchButton.setAttribute("aria-pressed", "false");

  function setNote(text, state = "normal") {
    if (!runtimeNote) return;
    runtimeNote.textContent = text;
    runtimeNote.dataset.state = state;
  }

  function imageSelected() {
    return Boolean(attachmentThumb && !attachmentThumb.hidden && attachmentThumb.getAttribute("src"));
  }

  function readyFor(toolId) {
    if (toolId === "web_search") return webReady;
    if (toolId === "deep_research") return researchReady;
    return false;
  }

  function syncControls() {
    const busy = toolInFlight !== null;
    const webUnavailable = !webReady || busy;
    const researchUnavailable = !researchReady || busy;

    webSearchButton.disabled = webUnavailable;
    webSearchButton.setAttribute("aria-disabled", webUnavailable ? "true" : "false");
    webSearchStarter.disabled = webUnavailable;
    webSearchStarter.setAttribute("aria-disabled", webUnavailable ? "true" : "false");
    deepResearchButton.disabled = researchUnavailable;
    deepResearchButton.setAttribute("aria-disabled", researchUnavailable ? "true" : "false");

    const webActive = activeTool === "web_search";
    const researchActive = activeTool === "deep_research";
    webSearchButton.setAttribute("aria-pressed", webActive ? "true" : "false");
    webSearchStarter.setAttribute("aria-pressed", webActive ? "true" : "false");
    deepResearchButton.setAttribute("aria-pressed", researchActive ? "true" : "false");
    webSearchButton.classList.toggle("is-active", webActive);
    webSearchStarter.classList.toggle("is-active", webActive);
    deepResearchButton.classList.toggle("is-active", researchActive);

    if (webReady) {
      webSearchButton.title = webActive
        ? "웹 검색 사용 중 · 누르면 해제합니다"
        : "다음 질문을 웹에서 찾아 출처와 함께 답합니다";
      if (starterStatus) starterStatus.textContent = webActive ? "다음 질문에서 사용" : "최신 정보 · 출처와 함께";
    } else {
      webSearchButton.title = "웹 검색은 현재 사용할 수 없습니다";
      if (starterStatus) starterStatus.textContent = "웹 검색 · 준비 중";
    }

    deepResearchButton.title = researchReady
      ? (researchActive ? "심층 리서치 사용 중 · 누르면 해제합니다" : "여러 검색과 출처를 비교해 다음 질문에 답합니다")
      : "심층 리서치는 현재 사용할 수 없습니다";
  }

  function setActiveTool(toolId, next = true, announce = true) {
    if (!readyFor(toolId) || toolInFlight !== null) return false;
    if (next && imageSelected()) {
      activeTool = null;
      syncControls();
      if (announce) setNote("사진 첨부와 웹 검색·심층 리서치는 한 질문에서 함께 사용할 수 없습니다.", "error");
      return false;
    }
    activeTool = next ? toolId : null;
    syncControls();
    if (announce) {
      if (activeTool === "web_search") setNote("다음 질문은 웹에서 찾아 출처와 함께 답합니다.");
      else if (activeTool === "deep_research") setNote("다음 질문은 여러 웹 자료를 비교해 심층 리서치합니다.");
      else setNote("웹 도구를 사용하지 않습니다.");
    }
    return true;
  }

  function chatPath(inputValue) {
    if (typeof inputValue === "string") {
      try {
        return new URL(inputValue, window.location.href).pathname;
      } catch (_) {
        return null;
      }
    }
    if (inputValue instanceof Request) {
      try {
        return new URL(inputValue.url, window.location.href).pathname;
      } catch (_) {
        return null;
      }
    }
    if (inputValue instanceof URL) return inputValue.pathname;
    return null;
  }

  function chatRequest(inputValue) {
    const path = chatPath(inputValue);
    return path === "/api/chat" || path === "/api/chat/stream";
  }

  function streamingChatRequest(inputValue) {
    return chatPath(inputValue) === "/api/chat/stream";
  }

  function addTool(init, toolId) {
    if (!init || typeof init.body !== "string") return null;
    let payload;
    try {
      payload = JSON.parse(init.body);
    } catch (_) {
      return null;
    }
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) return null;
    if (payload.tool !== undefined || payload.tool_input !== undefined) return null;
    payload.tool = toolId;
    return { ...init, body: JSON.stringify(payload) };
  }

  function currentAssistantArticle() {
    const articles = messageList.querySelectorAll(".assistant-message");
    return articles.length ? articles[articles.length - 1] : null;
  }

  function setStreamState(article, state) {
    if (!(article instanceof Element) || !article.isConnected) return;
    article.dataset.streamState = state;
  }

  function streamEventName(frame) {
    const normalized = frame.replace(/\r\n/g, "\n");
    for (const line of normalized.split("\n")) {
      if (!line.startsWith("event:")) continue;
      return line.slice("event:".length).trim();
    }
    return null;
  }

  function instrumentStreamingResponse(response, article) {
    const contentType = (response.headers.get("content-type") || "").toLowerCase();
    if (!response.ok || !contentType.includes("text/event-stream") || !response.body || typeof ReadableStream !== "function") {
      return response;
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";
    let terminal = false;
    setStreamState(article, "active");

    function inspect(chunkText, final = false) {
      buffer += chunkText;
      buffer = buffer.replace(/\r\n/g, "\n");
      let boundary = buffer.indexOf("\n\n");
      while (boundary >= 0) {
        const frame = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const eventName = streamEventName(frame);
        if (eventName === "done") {
          terminal = true;
          setStreamState(article, "done");
        } else if (eventName === "error") {
          terminal = true;
          setStreamState(article, "error");
        }
        boundary = buffer.indexOf("\n\n");
      }
      if (final && !terminal) setStreamState(article, "error");
    }

    const monitoredBody = new ReadableStream({
      async pull(controller) {
        try {
          const item = await reader.read();
          if (item.done) {
            inspect(decoder.decode(), true);
            controller.close();
            reader.releaseLock();
            return;
          }
          inspect(decoder.decode(item.value, { stream: true }));
          controller.enqueue(item.value);
        } catch (error) {
          if (!terminal) setStreamState(article, "error");
          controller.error(error);
          try { reader.releaseLock(); } catch (_) { /* no-op */ }
        }
      },
      async cancel(reason) {
        if (!terminal) setStreamState(article, "error");
        try {
          await reader.cancel(reason);
        } finally {
          try { reader.releaseLock(); } catch (_) { /* no-op */ }
        }
      },
    });

    return new Response(monitoredBody, {
      status: response.status,
      statusText: response.statusText,
      headers: response.headers,
    });
  }

  function toolCompletedAsStream(data, article) {
    if (!data || typeof data.answer !== "string" || !data.answer) return null;
    const done = { done: true };
    if (typeof data.conversation_id === "string") done.conversation_id = data.conversation_id;
    if (typeof data.project_id === "string") done.project_id = data.project_id;
    if (data.project && typeof data.project === "object") done.project = data.project;
    if (Number.isInteger(data.project_files_used)) done.project_files_used = data.project_files_used;

    const body = [
      `event: delta\ndata: ${JSON.stringify({ delta: data.answer })}\n\n`,
      `event: done\ndata: ${JSON.stringify(done)}\n\n`,
    ].join("");
    const response = new Response(body, {
      status: 200,
      headers: {
        "Content-Type": "text/event-stream; charset=utf-8",
        "Cache-Control": "no-cache, no-store",
      },
    });
    return instrumentStreamingResponse(response, article);
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

  function renderResearchSummary(content, research) {
    if (!research || typeof research !== "object") return;
    const searches = Number.isInteger(research.searches_completed) ? research.searches_completed : 0;
    const sources = Number.isInteger(research.source_count) ? research.source_count : 0;
    const summary = document.createElement("p");
    summary.className = "research-summary";
    summary.textContent = `심층 리서치 · 검색 ${searches}회 · 출처 ${sources}개${research.status === "partial" ? " · 일부 자료는 가져오지 못했습니다" : ""}`;
    content.appendChild(summary);
  }

  function renderSources(article, evidence, research = null) {
    if (!(article instanceof Element) || !article.isConnected || !Array.isArray(evidence)) return;
    const content = article.querySelector(".assistant-content");
    if (!content || content.querySelector(".error-box")) return;

    const existingSources = content.querySelector(".answer-sources");
    if (existingSources) existingSources.remove();
    const existingSummary = content.querySelector(".research-summary");
    if (existingSummary) existingSummary.remove();

    if (research) renderResearchSummary(content, research);

    const safeItems = evidence
      .slice(0, 10)
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

  function scheduleSources(article, evidence, research = null, attempt = 0) {
    window.setTimeout(() => {
      if (!(article instanceof Element) || !article.isConnected) return;
      const content = article.querySelector(".assistant-content");
      if (!content) return;
      if ((content.querySelector(".typing") || article.dataset.streamState === "active") && attempt < 40) {
        scheduleSources(article, evidence, research, attempt + 1);
        return;
      }
      renderSources(article, evidence, research);
    }, attempt === 0 ? 0 : 25);
  }

  function inspectToolResult(article, data) {
    const groundedSearch = data
      && data.answer_status === "answered_with_evidence"
      && data.tool
      && data.tool.id === "web_search"
      && Array.isArray(data.evidence);
    const deepResearch = data
      && data.answer_status === "deep_research_answered"
      && data.tool
      && data.tool.id === "deep_research"
      && Array.isArray(data.evidence);
    if (groundedSearch) scheduleSources(article, data.evidence);
    if (deepResearch) scheduleSources(article, data.evidence, data.research || null);
  }

  window.fetch = async (inputValue, init) => {
    const isChat = chatRequest(inputValue);
    const isStreamingChat = streamingChatRequest(inputValue);
    const requestedTool = isChat ? activeTool : null;
    let toolRequest = null;
    let nextInit = init;
    let article = isStreamingChat ? currentAssistantArticle() : null;
    let requestTarget = inputValue;

    if (requestedTool) {
      const blockedByImage = imageSelected() && !retryOverride;
      if (blockedByImage) {
        activeTool = null;
        retryOverride = false;
        syncControls();
        setNote("사진 첨부와 웹 검색·심층 리서치는 한 질문에서 함께 사용할 수 없습니다.", "error");
      } else {
        const augmented = addTool(init, requestedTool);
        if (augmented) {
          toolRequest = requestedTool;
          nextInit = augmented;
          article = currentAssistantArticle();
          activeTool = null;
          toolInFlight = requestedTool;
          retryOverride = false;
          if (isStreamingChat) requestTarget = "/api/chat";
          syncControls();
        }
      }
    }

    try {
      const response = await nativeFetch(requestTarget, nextInit);
      if (toolRequest) {
        if (!response.ok) {
          retryTool = toolRequest;
          return response;
        }

        retryTool = null;
        if (isStreamingChat) {
          const data = await response.json().catch(() => null);
          if (!data || typeof data.answer !== "string") {
            return new Response(JSON.stringify(data || { error: { code: "invalid_tool_response", message: "도구 응답을 확인할 수 없습니다." } }), {
              status: 502,
              headers: { "Content-Type": "application/json" },
            });
          }
          inspectToolResult(article, data);
          const synthetic = toolCompletedAsStream(data, article);
          if (synthetic) return synthetic;
          return new Response(JSON.stringify({ error: { code: "invalid_tool_response", message: "도구 응답을 확인할 수 없습니다." } }), {
            status: 502,
            headers: { "Content-Type": "application/json" },
          });
        }

        response.clone().json().then((data) => inspectToolResult(article, data)).catch(() => {});
        return response;
      }

      if (isStreamingChat) return instrumentStreamingResponse(response, article);
      return response;
    } catch (error) {
      if (toolRequest) retryTool = toolRequest;
      throw error;
    } finally {
      if (toolRequest) {
        toolInFlight = null;
        syncControls();
      }
    }
  };

  webSearchButton.addEventListener("click", () => setActiveTool("web_search", activeTool !== "web_search"));
  webSearchStarter.addEventListener("click", () => {
    if (setActiveTool("web_search", true)) input.focus();
  });
  deepResearchButton.addEventListener("click", () => {
    if (setActiveTool("deep_research", activeTool !== "deep_research")) input.focus();
  });

  messageList.addEventListener("click", (event) => {
    const target = event.target instanceof Element ? event.target.closest(".retry-button") : null;
    if (!target || !retryTool || !readyFor(retryTool)) return;
    activeTool = retryTool;
    retryOverride = true;
    retryTool = null;
    syncControls();
  }, true);

  if (attachmentThumb) {
    const attachmentObserver = new MutationObserver(() => {
      if (imageSelected() && activeTool && !retryOverride) {
        activeTool = null;
        syncControls();
        setNote("사진을 선택해 웹 도구가 해제되었습니다. 사진과 웹 검색·심층 리서치는 한 질문에서 함께 사용할 수 없습니다.", "error");
      }
    });
    attachmentObserver.observe(attachmentThumb, { attributes: true, attributeFilter: ["hidden", "src"] });
  }

  async function loadCapability() {
    try {
      const response = await nativeFetch("/health", { headers: { "Accept": "application/json" }, cache: "no-store" });
      const data = await response.json().catch(() => null);
      webReady = Boolean(response.ok && data && data.web_tools_ready === true);
      researchReady = Boolean(response.ok && data && data.deep_research_ready === true);
    } catch (_) {
      webReady = false;
      researchReady = false;
    }
    if (activeTool && !readyFor(activeTool)) activeTool = null;
    syncControls();
  }

  syncControls();
  loadCapability();
})();
