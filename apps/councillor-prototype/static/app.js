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

function bodyParagraphs(value) {
  return String(value || "").split(/\n{2,}/).map((part) => part.trim()).filter(Boolean);
}

function mediaSourceLabel(item) {
  const explicit = String(item.source_label || "").trim();
  if (explicit) return explicit;
  const raw = String(item.url || "");
  return item.kind === "포토" && raw.includes("PID=014") && !raw.includes("bbsSn=")
    ? "의회 사진자료실 보기"
    : "원문 보기";
}

function mediaSourceNotice(item) {
  const raw = String(item.url || "");
  return item.kind === "포토" && raw.includes("council.gwangju.go.kr/9imr/")
    ? String(SITE?.media?.photoSourceNotice || "")
    : "";
}

function thumbSrcSet(value) {
  const raw = String(value || "").split("?")[0];
  const name = raw.split("/").pop().replace(/\.[^.]+$/, "");
  if (!name) return "";
  return "./static/images/thumbs/" + name + "-320.webp 320w, ./static/images/thumbs/" + name + "-640.webp 640w";
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

// One script owns data loading and every page hook, including the home media column.
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
    if (list.querySelector(".activity-item[id]")) {
      showActivityStatus("자료를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.");
    } else {
      list.innerHTML = '<li class="activity-item">자료를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.</li>';
    }
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

function activityIdFor(a) {
  if (a && a.id) return a.id;
  const index = ACTIVITIES.indexOf(a);
  return "a-" + (a && a.date ? a.date : "unknown") + "-" + String(index + 1).padStart(2, "0");
}

function activityById(id) {
  return ACTIVITIES.find((a) => activityIdFor(a) === id) || null;
}

function currentActivityHash() {
  const raw = (window.location.hash || "").replace(/^#/, "");
  // A hand-typed or truncated link (for example "#%E0") must not stop the page.
  try { return decodeURIComponent(raw); } catch (_) { return raw; }
}

function clearActivityHash() {
  if (!window.location.hash) return;
  try {
    window.history.replaceState({ view: "list" }, "", window.location.pathname + window.location.search);
  } catch (error) { /* 주소창만 정리합니다. */ }
}

function showActivityStatus(message) {
  const el = document.getElementById("activityStatus");
  if (!el) return;
  el.textContent = message || "";
  el.hidden = !message;
}

function showActivityList(status) {
  const list = document.getElementById("activityList");
  const detail = document.getElementById("activityDetail");
  if (!list || !detail) return;
  detail.hidden = true;
  list.hidden = false;
  showActivityStatus(status || "");
  const visible = Array.from(list.querySelectorAll(".activity-item[id]"))
    .filter((row) => row.id !== "activityEmpty" && !row.hidden).length;
  renderCombinedPolicy(document.getElementById("activitySearch")?.value || "", visible);
}

function initActivityList(list) {
  if (list.dataset.activityReady === "true") return;
  // prerender.py owns the row markup; here we only make the existing rows usable.
  list.querySelectorAll(".activity-item[id]").forEach((li) => {
    const a = activityById(li.id);
    if (!a) return;
    li.setAttribute("tabindex", "0");
    li.setAttribute("role", "button");
    const open = () => showDetail(a);
    li.addEventListener("click", open);
    li.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); }
    });
  });
  list.dataset.activityReady = "true";
}

// #8723: the home search forwards scope=all; only non-empty result groups
// should be visible there, with one shared empty line when both are empty.
function combinedSearchActive() {
  return new URLSearchParams(location.search).get("scope") === "all";
}

function renderActivities(filter = "all", query = "") {
  const list = document.getElementById("activityList");
  if (!list || !SITE) return;
  initActivityList(list);
  const detail = document.getElementById("activityDetail");
  if (detail) detail.hidden = true;
  list.hidden = false;
  const q = query.trim().toLowerCase();
  let count = 0;
  ACTIVITIES.forEach((a) => {
    const row = document.getElementById(activityIdFor(a));
    const matches = (filter === "all" || a.tag === filter) &&
      (!q || a.title.toLowerCase().includes(q) || (a.body || "").toLowerCase().includes(q));
    row.hidden = !matches;
    if (matches) count++;
  });
  let empty = document.getElementById("activityEmpty");
  if (!count && !empty) {
    empty = document.createElement("li");
    empty.id = "activityEmpty";
    empty.className = "activity-item";
    empty.textContent = "검색 결과가 없습니다.";
    list.appendChild(empty);
  }
  // In the combined search the policy renderer owns the one empty line.
  if (empty) empty.hidden = count !== 0 || combinedSearchActive();
  showActivityStatus("");
  renderCombinedPolicy(query, count);
}

function showDetail(a, options) {
  const push = !options || options.push !== false;
  const list = document.getElementById("activityList");
  const detail = document.getElementById("activityDetail");
  if (!list || !detail) return;
  list.hidden = true;
  detail.hidden = false;
  showActivityStatus("");
  document.getElementById("detailTitle").textContent = a.title;
  document.getElementById("detailDate").textContent =
    a.date + " · " + a.tag + (a.source ? " · " + a.source : "");
  const body = document.getElementById("detailBody");
  const paragraphs = bodyParagraphs(a.body);
  body.replaceChildren(...paragraphs.map((text) => {
    const paragraph = document.createElement("p");
    paragraph.textContent = text;
    return paragraph;
  }));
  body.hidden = paragraphs.length === 0;
  const glossary = document.getElementById("detailTerms");
  if (glossary) {
    const text = a.title + " " + (a.body || "");
    const terms = SITE?.activity?.glossary?.terms || {};
    glossary.innerHTML = Object.entries(terms).filter(([term]) => text.includes(term))
      .map(([term, meaning]) => '<p><b>' + escapeHtml(term) + '</b> — ' + escapeHtml(meaning) + '</p>').join("");
    glossary.hidden = !glossary.innerHTML;
  }
  const policyResults = document.getElementById("combinedPolicy");
  if (policyResults) policyResults.hidden = true;
  const link = document.getElementById("detailLink");
  const rawHref = String(a.url || "");
  const href = /^(https?:\/\/|\.\/)/.test(rawHref) ? safeHref(rawHref) : "";
  link.href = href || "#";
  link.hidden = !href;
  const id = activityIdFor(a);
  if (push && id) {
    try {
      window.history.pushState({ view: "detail", id: id }, "", "#" + id);
    } catch (error) { /* 주소 갱신을 못 해도 상세는 엽니다. */ }
  }
  scrollToElement(detail, "start");
  const title = document.getElementById("detailTitle");
  if (title) {
    try { title.focus({ preventScroll: true }); } catch (error) { title.focus(); }
  }
}

function syncActivityFromLocation(initial) {
  if (!document.getElementById("activityList") || !document.getElementById("activityDetail")) return;
  const id = currentActivityHash();
  if (!id) { showActivityList(""); return; }
  const a = activityById(id);
  if (!a) {
    showActivityList("찾는 활동이 없습니다.");
    return;
  }
  if (initial) {
    try {
      window.history.replaceState({ view: "list" }, "", window.location.pathname + window.location.search);
      window.history.pushState({ view: "detail", id: id }, "", "#" + id);
    } catch (error) { /* 주소 갱신을 못 해도 상세는 엽니다. */ }
  }
  showDetail(a, { push: false });
  if (initial) {
    // A prerendered fragment is also a native browser navigation target.
    // Restore heading focus after that initial navigation has settled, without
    // overriding any focus the visitor has already moved to another control.
    const restoreFocus = () => requestAnimationFrame(() => requestAnimationFrame(() => {
      const detail = document.getElementById("activityDetail");
      const title = document.getElementById("detailTitle");
      if (currentActivityHash() !== id || detail.hidden) return;
      if (document.activeElement === document.body ||
          document.activeElement === document.documentElement ||
          document.activeElement === document.getElementById(id)) {
        title.focus({ preventScroll: true });
      }
    }));
    if (document.readyState === "complete") restoreFocus();
    else window.addEventListener("load", restoreFocus, { once: true });
  }
}

function enhanceMediaCards(root = document) {
  root.querySelectorAll("[data-media-thumb]").forEach((card) => {
    card.removeAttribute("target");
    card.removeAttribute("href");
    card.setAttribute("role", "button");
    card.setAttribute("tabindex", "0");
    card.setAttribute("aria-haspopup", "dialog");
    card.setAttribute("aria-label", card.dataset.mediaTitle + " 크게 보기");
  });
  markExternalLinks();
}

function renderMedia() {
  const grid = document.getElementById("mediaGrid");
  if (grid) enhanceMediaCards(grid);
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

// The old council's bill system has no per-assembly list page, so the policy page
// groups the representative bills itself: 9th assembly first, newest first inside each.
function renderBills(policy) {
  const grid = document.getElementById("policyBills");
  if (!grid) return;
  const block = grid.closest(".policy-block");
  const items = Array.isArray(policy.bills) ? policy.bills : [];
  if (items.length === 0) {
    if (block) block.hidden = true;
    return;
  }
  if (block) block.hidden = false;
  // The bill groups and rows are prerendered; only the search is wired here.
  const search = document.getElementById("billSearch");
  if (!search) return;
  const status = document.getElementById("billSearchStatus");
  const applyFilter = () => {
    const q = search.value.trim().toLowerCase();
    let totalVisible = 0;
    const summaries = [];
    grid.querySelectorAll(".bill-group").forEach((group) => {
      const total = Number(group.dataset.total) || 0;
      const assembly = group.dataset.assembly;
      let visible = 0;
      group.querySelectorAll(".bill-row").forEach((row) => {
        const match = !q || row.textContent.toLowerCase().includes(q);
        row.hidden = !match;
        if (match) visible += 1;
      });
      totalVisible += visible;
      const count = group.querySelector(".bill-count");
      if (count) {
        count.textContent = !q ? total + "건" : visible > 0
          ? visible + "건 / 전체 " + total + "건"
          : "검색 결과 없음";
      }
      group.hidden = false;
      group.classList.toggle("is-empty", Boolean(q) && visible === 0);
      if (q && visible > 0 && group.tagName === "DETAILS") group.open = true;
      summaries.push("제" + assembly + "대 " + (q && visible === 0
        ? "검색 결과 없음 / 전체 " + total + "건"
        : visible + "건 / 전체 " + total + "건"));
    });
    if (status) {
      status.textContent = q
        ? totalVisible > 0
          ? "검색 결과 총 " + totalVisible + "건 / 전체 " + items.length + "건. " + summaries.join(", ")
          : "검색 결과가 없습니다. 전체 " + items.length + "건."
        : "전체 " + items.length + "건";
    }
  };
  search.oninput = applyFilter;
  applyFilter();
  const query = initialQueryParameter();
  if (query) { search.value = query; applyFilter(); }
}

function renderPolicy(data) {
  const policy = data && data.policy;
  if (!policy) return;
  // Policy cards and bill groups are prerendered; only their search is wired here.
  [["policyForums", policy.forums], ["policyVideos", policy.videos], ["policyBills", policy.bills]]
    .forEach(([id, items]) => {
      const grid = document.getElementById(id);
      const block = grid && grid.closest(".policy-block");
      if (block) block.hidden = !Array.isArray(items) || items.length === 0;
    });
  renderBills(policy);
  const source = document.getElementById("policySource");
  if (source && policy.source) source.textContent = policy.source;
  markExternalLinks();
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
let lightboxItems = [];
let lightboxIndex = 0;
let lightboxTrigger = null;

function renderLightbox() {
  const item = lightboxItems[lightboxIndex];
  if (!item) return;
  const img = document.getElementById("lightboxImg");
  const title = document.getElementById("lightboxTitle");
  const link = document.getElementById("lightboxLink");
  const source = document.getElementById("lightboxSource");
  if (img) { img.src = safeHref(item.thumb) || ""; img.alt = item.title || ""; }
  if (title) title.textContent = item.title || "";
  if (link) {
    const href = item.url ? safeHref(item.url) : "";
    const label = mediaSourceLabel(item);
    link.href = href || "#";
    link.hidden = !href;
    link.textContent = label + " ↗";
    link.setAttribute("aria-label", label + " (새 탭)");
    link.dataset.extMarked = "1";
  }
  if (source) {
    source.textContent = mediaSourceNotice(item);
    source.hidden = !source.textContent;
  }
}

function openLightbox(index, trigger) {
  const dialog = document.getElementById("mediaLightbox");
  if (!dialog) return;
  lightboxItems = Array.from(document.querySelectorAll("[data-media-thumb]"), (card) => ({
    thumb: card.dataset.mediaThumb, title: card.dataset.mediaTitle, url: card.dataset.mediaUrl,
    kind: card.dataset.mediaKind || ""
  }));
  lightboxIndex = Math.max(0, Math.min(lightboxItems.length - 1, Number(index) || 0));
  lightboxTrigger = trigger || null;
  renderLightbox();
  if (typeof dialog.showModal === "function") dialog.showModal();
  else dialog.setAttribute("open", "");
  document.body.classList.add("lightbox-open");
  document.getElementById("lightboxClose")?.focus();
}

function closeLightbox() {
  const dialog = document.getElementById("mediaLightbox");
  if (!dialog) return;
  if (typeof dialog.close === "function") dialog.close();
  else dialog.removeAttribute("open");
  document.body.classList.remove("lightbox-open");
  if (lightboxTrigger && typeof lightboxTrigger.focus === "function") lightboxTrigger.focus();
}

function stepLightbox(delta) {
  if (!lightboxItems.length) return;
  lightboxIndex = (lightboxIndex + delta + lightboxItems.length) % lightboxItems.length;
  renderLightbox();
}

function initLightbox() {
  const dialog = document.getElementById("mediaLightbox");
  if (!dialog) return;
  enhanceMediaCards();
  const activate = (event) => {
    const card = event.target.closest("[data-media-thumb]");
    if (!card) return;
    event.preventDefault();
    openLightbox(Array.from(document.querySelectorAll("[data-media-thumb]")).indexOf(card), card);
  };
  document.addEventListener("click", activate);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      if (event.target.closest("[data-media-thumb]")) activate(event);
    }
  });
  document.getElementById("lightboxClose")?.addEventListener("click", closeLightbox);
  document.getElementById("lightboxPrev")?.addEventListener("click", () => stepLightbox(-1));
  document.getElementById("lightboxNext")?.addEventListener("click", () => stepLightbox(1));
  dialog.addEventListener("click", (event) => { if (event.target === dialog) closeLightbox(); });
  dialog.addEventListener("keydown", (event) => {
    if (event.key === "ArrowLeft") { event.preventDefault(); stepLightbox(-1); }
    if (event.key === "ArrowRight") { event.preventDefault(); stepLightbox(1); }
  });
  dialog.addEventListener("close", () => {
    document.body.classList.remove("lightbox-open");
    if (lightboxTrigger && typeof lightboxTrigger.focus === "function") lightboxTrigger.focus();
  });
}

function markExternalLinks() {
  document.querySelectorAll('a[target="_blank"]').forEach((a) => {
    if (a.dataset.extMarked === "1" || a.hasAttribute("data-media-thumb")) return;
    if (a.closest(".bill-row")) return;
    a.dataset.extMarked = "1";
    const text = (a.textContent || "").trim();
    if (!text.includes("↗")) {
      const mark = document.createElement("span");
      mark.className = "ext-mark";
      mark.setAttribute("aria-hidden", "true");
      mark.textContent = "↗";
      a.append(mark);
    }
    const label = a.getAttribute("aria-label") || text;
    if (!label.includes("(새 탭)")) a.setAttribute("aria-label", label + " (새 탭)");
  });
}

function initTheme() {
  const btn = document.getElementById("themeToggle");
  if (!btn) return;
  const root = document.documentElement;
  const sync = () => {
    const isDark = root.getAttribute("data-theme") === "dark";
    btn.textContent = isDark ? "밝게 보기" : "어둡게 보기";
    btn.setAttribute("aria-label", isDark ? "밝은 화면으로 보기" : "어두운 화면으로 보기");
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

// The home search box arrives as ?q=... on the search screens; each page feeds
// the value into its own existing search control (no second engine).
function renderCombinedPolicy(query, activityCount = 0) {
  const section = document.getElementById("combinedPolicy");
  if (!section || !SITE || !combinedSearchActive()) return;
  const heading = document.getElementById("combinedActivityHeading");
  const q = query.trim().toLowerCase();
  const records = ["forums", "videos", "bills"].flatMap((key) => SITE.policy[key] || []);
  const matches = records.filter((item) => !q || [item.title, item.summary, item.note, item.number, item.date, item.result]
    .some((value) => String(value || "").toLowerCase().includes(q)));
  const list = document.getElementById("combinedPolicyList");
  list.innerHTML = matches.map((item) => {
    const raw = String(item.url || "");
    const url = /^(https?:\/\/|\.\/)/.test(raw) ? safeHref(raw) : "";
    const title = escapeHtml(item.title);
    return '<li class="combined-policy-row">' + (url ? '<a href="' + escapeHtml(url) +
      '" target="_blank" rel="noopener">' + title + '</a>' : '<span>' + title + '</span>') + '</li>';
  }).join("");
  section.hidden = matches.length === 0;
  if (heading) heading.hidden = activityCount === 0;
  const empty = document.getElementById("activityEmpty");
  if (empty) empty.hidden = !(activityCount === 0 && matches.length === 0);
  markExternalLinks();
}

function initialQueryParameter() {
  try {
    const value = new URLSearchParams(window.location.search || "").get("q");
    return (value || "").trim();
  } catch (_) { return ""; }
}

document.addEventListener("DOMContentLoaded", () => {
  initTheme();
  markExternalLinks();
  initLightbox();
  const homeMedia = document.getElementById("homeMedia");
  if (homeMedia) enhanceMediaCards(homeMedia);

  window.COUNCILLOR_DATA_READY.then((data) => {
    if (!data) return;
    renderContact(data);
    renderPolicy(data);
    renderIntroVideo(data);
  });

  const search = document.getElementById("activitySearch");
  const filter = document.getElementById("activityFilter");
  const renderFromControls = () => {
    clearActivityHash();
    renderActivities(filter.value, search.value);
  };
  if (search) search.addEventListener("input", renderFromControls);
  if (filter) filter.addEventListener("change", renderFromControls);

  const back = document.getElementById("activityBack");
  const closeActivity = () => {
    if (window.history.state?.view === "detail" && window.history.length > 1) {
      window.history.back();
    } else {
      clearActivityHash();
      showActivityList("");
    }
  };
  if (back) {
    back.addEventListener("click", closeActivity);
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !document.getElementById("activityDetail").hidden) {
        event.preventDefault();
        closeActivity();
      }
    });
  }

  window.addEventListener("popstate", () => syncActivityFromLocation(false));
  window.addEventListener("hashchange", () => syncActivityFromLocation(false));

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
    // #7550 동훈 3회차: the home search box forwards ?q here; the existing
    // search input and renderer run it, so the list opens already searched.
    const query = initialQueryParameter();
    if (query && search) search.value = query;
    renderActivities(filter ? filter.value : "all", search ? search.value : query);
    renderMedia();
    syncActivityFromLocation(true);
  });
});
