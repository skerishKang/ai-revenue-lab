(() => {
  "use strict";
  // #4469: Claw answer sources display adapter. The backend SSE done frame only
  // carries provenance that already passed the server-side https/title/date
  // verification in claw_general_routes._project_search_sources; this renderer
  // performs a second bounded browser-side check purely for display safety.
  // It renders nothing on absence and never claims a search happened.
  function safeUrl(value) {
    if (typeof value !== "string" || !value.trim()) return null;
    try {
      const url = new URL(value);
      return url.protocol === "https:" ? url : null;
    } catch (_) {
      return null;
    }
  }

  // #7784 (same rule as search-sources.js): when the answer cites sources
  // ([1], [2], ...), only those appear; the list order is the citation order,
  // so the position is the citation number. No citation, or no readable
  // answer text, keeps the old show-all behavior.
  function answerTextForSources(content) {
    const template = content.querySelector("template.rich-response-source");
    const templateText = template && template.content
      && typeof template.content.textContent === "string"
      ? template.content.textContent : "";
    if (templateText) return templateText;
    const rich = content.querySelector(".rich-response");
    if (rich && typeof rich.textContent === "string" && rich.textContent.trim()) {
      return rich.textContent;
    }
    const paragraphs = Array.from(content.querySelectorAll("p"))
      .filter((node) => node.textContent && node.textContent.trim())
      .map((node) => node.textContent);
    if (!paragraphs.length) return null;
    return paragraphs.join("\n");
  }

  function citedSourceNumbers(answerText) {
    const cited = new Set();
    const pattern = /\[(\d{1,2})\]/g;
    let match;
    while ((match = pattern.exec(answerText)) !== null) {
      const number = Number(match[1]);
      if (Number.isInteger(number) && number >= 1) cited.add(number);
    }
    return cited;
  }

  function localeLabel(key, fallback) {
    try {
      if (typeof window !== "object" || typeof window.PadiemLocaleText !== "function") return fallback;
      const text = window.PadiemLocaleText(key, document.documentElement.lang);
      return typeof text === "string" && text.trim() ? text : fallback;
    } catch (_) {
      return fallback;
    }
  }

  function formatRetrievedAt(value) {
    const parsed = new Date(value);
    if (!(parsed instanceof Date) || Number.isNaN(parsed.getTime())) return value;
    const lang = document.documentElement.lang || "ko";
    if (lang.toLowerCase().startsWith("ko")) return `${parsed.getMonth() + 1}월 ${parsed.getDate()}일`;
    try {
      return new Intl.DateTimeFormat(lang, { month: "short", day: "numeric" }).format(parsed);
    } catch (_) {
      return `${parsed.getMonth() + 1}/${parsed.getDate()}`;
    }
  }

  function renderClawAnswerSources(article, rawSources) {
    if (!(article instanceof Element) || !Array.isArray(rawSources) || !rawSources.length) return;
    const content = article.querySelector(".assistant-content");
    if (!content || content.querySelector(".error-box")) return;
    const existing = content.querySelector(".answer-sources");
    if (existing) existing.remove();

    const seen = new Set();
    const items = [];
    const sliced = rawSources.slice(0, 5);
    for (let position = 0; position < sliced.length; position += 1) {
      const entry = sliced[position];
      if (!entry || typeof entry !== "object") return; // malformed frame data renders nothing
      const url = safeUrl(entry.url);
      if (!url) return;
      if (typeof entry.title !== "string" || typeof entry.retrieved_at !== "string") return;
      const key = url.href;
      if (seen.has(key)) continue;
      seen.add(key);
      items.push({ position, url, title: entry.title, retrievedAt: entry.retrieved_at });
    }
    const answerText = answerTextForSources(content);
    const cited = answerText === null ? null : citedSourceNumbers(answerText);
    const visibleItems = (cited && cited.size)
      ? items.filter((item) => cited.has(item.position + 1))
      : items;
    if (!visibleItems.length) return;

    const section = document.createElement("section");
    section.className = "answer-sources";
    section.setAttribute("aria-label", localeLabel("sources-aria", "답변 출처"));

    const heading = document.createElement("h3");
    heading.className = "answer-sources-title";
    heading.textContent = localeLabel("sources", "출처");

    const list = document.createElement("ol");
    list.className = "answer-sources-list";

    for (const item of visibleItems) {
      const row = document.createElement("li");
      row.className = "answer-source-item";

      const anchor = document.createElement("a");
      anchor.className = "answer-source-link";
      anchor.href = item.url.href;
      anchor.target = "_blank";
      anchor.rel = "noopener noreferrer";

      const copy = document.createElement("span");
      copy.className = "answer-source-copy";

      const title = document.createElement("strong");
      title.textContent = item.title.trim() ? item.title.trim() : item.url.hostname;

      const meta = document.createElement("small");
      meta.textContent = item.url.hostname + " · " + formatRetrievedAt(item.retrievedAt);

      copy.append(title, meta);
      anchor.appendChild(copy);
      row.appendChild(anchor);
      list.appendChild(row);
    }

    section.append(heading, list);
    content.appendChild(section);
  }

  window.PadiemClawAnswerSources = { render: renderClawAnswerSources };
})();
