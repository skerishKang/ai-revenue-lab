(() => {
  "use strict";

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
      if (typeof item.retrieved_at === "string" && item.retrieved_at.trim()) {
        const retrieved = document.createElement("small");
        retrieved.className = "answer-source-retrieved-at";
        retrieved.textContent = item.retrieved_at.trim();
        copy.append(retrieved);
      }
      anchor.append(number, copy);
      row.appendChild(anchor);
      list.appendChild(row);
    });

    section.append(heading, list);
    content.appendChild(section);
  }

  // The server-selected search path sends evidence with the completed answer.
  // This module only renders that validated evidence; it never changes requests.
  window.PadiemSearchSources = Object.freeze({ render: renderSources });
})();
