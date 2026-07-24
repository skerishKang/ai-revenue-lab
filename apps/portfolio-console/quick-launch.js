window.ARL_QUICK_LAUNCH = [
  { label: "Portfolio Console", url: "https://ai-revenue-portfolio-console.pages.dev", state: "verified" },
  { label: "LoveBud", url: "https://lovebud.pages.dev/", state: "verified" },
  { label: "Personal Edition", url: "https://feat-personal-edition-final.ai-revenue-personal-edition.pages.dev", state: "verified" },
  { label: "Living Travel", url: "https://ops-living-travel-external-s.ai-revenue-living-travel.pages.dev", state: "verified" },
  { label: "Living Fiction", url: null, state: "planned" },
  { label: "Living Learning", url: "https://ai-revenue-living-learning.pages.dev/", state: "verified" },
  { label: "Personal Video Archive", url: "https://feat-personal-video-archive.ai-revenue-personal-video-archive.pages.dev", state: "verified" },
  { label: "LoveTree 3.0", url: null, state: "planned" },
  { label: "Korean AI Platform", url: null, state: "planned" },
  { label: "AI Finder / 광주 북구청", url: null, state: "planned" },
  { label: "Love Matchmaking", url: null, state: "planned" },
  { label: "광주 남구청 AI Finder", url: null, state: "planned" },
  { label: "광주 서구청 AI Finder", url: null, state: "planned" }
];

(() => {
  "use strict";

  function renderQuickLaunch() {
    const items = window.ARL_QUICK_LAUNCH;
    if (!Array.isArray(items)) return;

    const container = document.getElementById("quick-launch-list");
    if (!container) return;

    container.innerHTML = items.map((item) => {
      const active = item.state === "verified" && item.url;
      const hrefAttr = active ? ` href="${item.url}"` : "";
      const extras = active
        ? ' target="_blank" rel="noopener noreferrer"'
        : ' aria-disabled="true" tabindex="-1"';
      const cls = active ? "ql-item ql-active" : "ql-item ql-planned";
      return `<a class="${cls}"${hrefAttr}${extras}>${item.label}</a>`;
    }).join("");
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", renderQuickLaunch);
  } else {
    renderQuickLaunch();
  }
})();
