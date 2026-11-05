// Shared renderers for the councillor site.
// static/miraen.json is the only content source: this file fetches it once and
// renders the activity list/detail, the media grid and the news list from it.
const DATA_URL = "./static/miraen.json";

let SITE = null;
let ACTIVITIES = [];
let MEDIA = [];
let NEWS = [];

function escapeHtml(value) {
  return String(value == null ? "" : value).replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;"
  })[ch]);
}

function safeHref(value) {
  try {
    const url = new URL(String(value), window.location.href);
    return /^https?:$/.test(url.protocol) ? url.href : "";
  } catch (error) {
    return "";
  }
}

function loadSiteData() {
  return fetch(DATA_URL, { cache: "no-store" })
    .then((response) => {
      if (!response.ok) throw new Error("HTTP " + response.status);
      return response.json();
    })
    .then((data) => {
      if (!data || !data.activity || !Array.isArray(data.activity.items) ||
          !data.media || !Array.isArray(data.media.tiles)) {
        throw new Error("miraen.json shape");
      }
      SITE = data;
      ACTIVITIES = data.activity.items;
      MEDIA = data.media.tiles;
      NEWS = ACTIVITIES.filter((item) => item.featured === true);
      return data;
    })
    .catch((error) => {
      console.error("자료를 불러오지 못했습니다.", error);
      return null;
    });
}

// app.js loads before home.js, so the home renderer waits on the same promise.
window.COUNCILLOR_DATA_READY = loadSiteData();

function prefersReducedMotion() {
  try {
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  } catch (error) {
    return false;
  }
}

function scrollToElement(element, block) {
  element.scrollIntoView({ behavior: prefersReducedMotion() ? "auto" : "smooth", block: block || "start" });
}

function renderDataError() {
  const list = document.getElementById("activityList");
  if (list) {
    list.hidden = false;
    list.innerHTML = '<li class="activity-item">자료를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.</li>';
  }
  const grid = document.getElementById("mediaGrid");
  if (grid) {
    grid.innerHTML = '<p class="source-note">자료를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.</p>';
  }
  const news = document.getElementById("newsList");
  if (news) {
    news.innerHTML = '<li class="news-item">자료를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.</li>';
  }
}

function renderActivities(filter = "all", query = "") {
  const list = document.getElementById("activityList");
  if (!list) return;
  const detail = document.getElementById("activityDetail");
  if (detail) detail.hidden = true;
  list.hidden = false;
  list.innerHTML = "";
  const q = query.trim().toLowerCase();
  const filtered = ACTIVITIES.filter((a) => {
    if (filter !== "all" && a.tag !== filter) return false;
    if (q && !a.title.toLowerCase().includes(q) && !(a.body || "").toLowerCase().includes(q)) return false;
    return true;
  });
  if (filtered.length === 0) {
    const li = document.createElement("li");
    li.className = "activity-item";
    li.textContent = "검색 결과가 없습니다.";
    list.appendChild(li);
    return;
  }
  filtered.forEach((a) => {
    const li = document.createElement("li");
    li.className = "activity-item";
    li.setAttribute("tabindex", "0");
    li.setAttribute("role", "button");
    li.innerHTML =
      '<div class="item-date">' + escapeHtml(a.date) +
        '<span class="item-tag">' + escapeHtml(a.tag) + "</span></div>" +
      '<div class="item-title">' + escapeHtml(a.title) + "</div>";
    const open = () => showDetail(a);
    li.addEventListener("click", open);
    li.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); } });
    list.appendChild(li);
  });
}

function showDetail(a) {
  const list = document.getElementById("activityList");
  const detail = document.getElementById("activityDetail");
  list.hidden = true;
  detail.hidden = false;
  document.getElementById("detailTitle").textContent = a.title;
  document.getElementById("detailDate").textContent =
    a.date + " · " + a.tag + (a.source ? " · " + a.source : "");
  const body = document.getElementById("detailBody");
  body.textContent = a.body || "";
  body.hidden = !a.body;
  const link = document.getElementById("detailLink");
  const href = safeHref(a.url);
  link.href = href || "#";
  link.hidden = !href;
  scrollToElement(detail, "start");
}

function renderMedia() {
  const grid = document.getElementById("mediaGrid");
  if (!grid) return;
  grid.innerHTML = "";
  MEDIA.filter((m) => m.thumb).forEach((m) => {
    const tile = document.createElement("a");
    tile.className = "media-tile";
    tile.href = safeHref(m.url) || "#";
    tile.target = "_blank";
    tile.rel = "noopener";
    tile.setAttribute("tabindex", "0");
    const thumb = `<img class="tile-thumb" src="${escapeHtml(safeHref(m.thumb))}" alt="${escapeHtml(m.title)}" loading="lazy" onerror="this.style.display='none'" />`;
    const notes = (m.notes || []).map((n) => `<li>${escapeHtml(n)}</li>`).join("");
    tile.innerHTML = thumb +
      `<div class="tile-kind">${escapeHtml(m.kind)}</div>` +
      `<div class="tile-title">${escapeHtml(m.title)}</div>` +
      `<ul class="tile-notes">${notes}</ul>`;
    grid.appendChild(tile);
  });
}

function renderNews() {
  const list = document.getElementById("newsList");
  if (!list) return;
  list.innerHTML = "";
  NEWS.forEach((n) => {
    const li = document.createElement("li");
    li.className = "news-item";
    const href = safeHref(n.url);
    const title = href
      ? `<a href="${escapeHtml(href)}" target="_blank" rel="noopener">${escapeHtml(n.title)}</a>`
      : escapeHtml(n.title);
    li.innerHTML =
      `<div class="news-date">${escapeHtml(n.date)}${n.source ? " · " + escapeHtml(n.source) : ""}</div>` +
      `<h3 class="news-title">${title}</h3>` +
      `<p class="news-body">${escapeHtml(n.body || "")}</p>`;
    list.appendChild(li);
  });
}

// Tiles without a picture of their own move to a compact link list under the gallery
// instead of holding an empty 4:3 box.
function renderMediaMore() {
  const list = document.getElementById("mediaMore");
  if (!list) return;
  const rest = MEDIA.filter((m) => !m.thumb);
  list.innerHTML = rest.map((m) =>
    '<li><a href="' + escapeHtml(safeHref(m.url) || "#") + '" target="_blank" rel="noopener">' +
      '<span class="link-title">' + escapeHtml(m.title) + "</span>" +
      '<span class="link-kind">' + escapeHtml(m.kind) + "</span>" +
    "</a></li>"
  ).join("");
}

// The email lives once in miraen.json. The markup carries the same value for a visitor
// without JavaScript; this keeps the link in sync when the address changes.
function renderContact(data) {
  const email = data && data.contact && data.contact.email;
  if (!email) return;
  document.querySelectorAll("[data-contact-email]").forEach((link) => {
    link.href = "mailto:" + email;
    if (!link.textContent.trim()) link.textContent = email;
  });
}

function renderPolicy(data) {
  const policy = data && data.policy;
  if (!policy) return;
  const groups = [
    ["policyForums", policy.forums, "원문 보기"],
    ["policyVideos", policy.videos, "영상 보기"],
    ["policyBills", policy.bills, "의안 보기"]
  ];
  groups.forEach(([id, items, label]) => {
    const grid = document.getElementById(id);
    if (!grid) return;
    const list = Array.isArray(items) ? items : [];
    const block = grid.closest(".policy-block");
    if (list.length === 0) {
      if (block) block.hidden = true;
      return;
    }
    grid.innerHTML = list.map((item, index) => {
      const meta = [item.date, item.note].filter(Boolean).join(" · ");
      const href = safeHref(item.url);
      return '<article class="info-card">' +
        '<div class="card-num">' + String(index + 1).padStart(2, "0") + "</div>" +
        "<h3>" + escapeHtml(item.title) + "</h3>" +
        (meta ? '<p class="policy-meta">' + escapeHtml(meta) + "</p>" : "") +
        (item.summary ? "<p>" + escapeHtml(item.summary) + "</p>" : "") +
        (href ? '<a class="card-link" href="' + escapeHtml(href) + '" target="_blank" rel="noopener">' + label + "</a>" : "") +
        "</article>";
    }).join("");
  });
  const source = document.getElementById("policySource");
  if (source && policy.source) source.textContent = policy.source;
}

// about.html shows the 2025 introduction footage that used to sit in miraen.json
// without a screen. 자동 재생 없이 방문자가 시작한다.
function renderIntroVideo(data) {
  const host = document.getElementById("introVideo");
  const feature = data && data.feature;
  if (!host || !feature || !Array.isArray(feature.sources) || feature.sources.length === 0) return;
  const src = safeHref(feature.sources[0]);
  if (!src) return;
  const poster = data.hero && data.hero.poster ? safeHref(data.hero.poster) : "";
  host.innerHTML =
    '<video controls preload="metadata"' + (poster ? ' poster="' + escapeHtml(poster) + '"' : "") + ">" +
      '<source src="' + escapeHtml(src) + '" type="video/mp4" />' +
    "</video>" +
    '<p class="intro-video-title">' + escapeHtml(feature.kind || "소개 영상") + "</p>" +
    (feature.title ? '<p class="source-note">' + escapeHtml(feature.title) + " · " + escapeHtml((data.hero && data.hero.credit) || "") + "</p>" : "");
  host.hidden = false;
}

// Theme toggle — the head script applies the saved value before first paint.
function initTheme() {
  const btn = document.getElementById("themeToggle");
  if (!btn) return;
  const root = document.documentElement;
  const sync = () => {
    const isDark = root.getAttribute("data-theme") === "dark";
    btn.textContent = isDark ? "라이트" : "다크";
    btn.setAttribute("aria-pressed", String(isDark));
  };
  sync();
  btn.addEventListener("click", () => {
    const next = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
    root.setAttribute("data-theme", next);
    sync();
    try {
      localStorage.setItem("theme", next);
    } catch (error) { /* 저장소를 쓸 수 없으면 현재 화면 테마만 유지합니다. */ }
  });
}

document.addEventListener("DOMContentLoaded", () => {
  initTheme();

  window.COUNCILLOR_DATA_READY.then((data) => {
    if (!data) return;
    renderContact(data);
    renderPolicy(data);
    renderIntroVideo(data);
    renderMediaMore();
  });

  const search = document.getElementById("activitySearch");
  const filter = document.getElementById("activityFilter");
  if (search) search.addEventListener("input", () => renderActivities(filter.value, search.value));
  if (filter) filter.addEventListener("change", () => renderActivities(filter.value, search.value));

  const back = document.getElementById("activityBack");
  if (back) back.addEventListener("click", () => {
    document.getElementById("activityDetail").hidden = true;
    document.getElementById("activityList").hidden = false;
  });

  // Smooth scroll for in-page links, disabled when reduced motion is requested.
  document.querySelectorAll('a[href^="#"]').forEach((a) => {
    a.addEventListener("click", (e) => {
      const id = a.getAttribute("href").slice(1);
      const target = document.getElementById(id);
      if (target) { e.preventDefault(); scrollToElement(target); }
    });
  });

  const needsData = search || filter || document.getElementById("activityList") ||
    document.getElementById("mediaGrid") || document.getElementById("newsList");
  if (!needsData) return;
  window.COUNCILLOR_DATA_READY.then((data) => {
    if (!data) { renderDataError(); return; }
    renderActivities();
    renderMedia();
    renderNews();
  });
});
