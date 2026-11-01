// Home-page renderers for #5972.
// The shared renderers live in app.js; this file fills the blocks on index.html
// from the same static/miraen.json data that app.js loads, so no content is
// copied into JavaScript.
(function () {
  "use strict";

  // Line icons drawn inline. The reference marks each strip item, activity card and
  // statistic with its own glyph rather than an ordinal number, and the two webfonts
  // carry no icon set, so the paths live here instead of an icon dependency.
  const PATHS = {
    record: '<rect x="3.2" y="2.6" width="13.6" height="14.8" rx="2.2"/><path d="M6.6 7.2h6.8M6.6 10.4h6.8M6.6 13.6h4.2"/>',
    person: '<circle cx="10" cy="6.6" r="3.2"/><path d="M4 17c0-3.3 2.7-5.3 6-5.3s6 2 6 5.3"/>',
    people: '<circle cx="7.4" cy="6.9" r="2.6"/><circle cx="13.3" cy="8.1" r="2.1"/><path d="M2.9 16.4c0-2.7 2-4.3 4.5-4.3s4.5 1.6 4.5 4.3"/><path d="M12.1 12.5c2.4-.5 5 .6 5 3.9"/>',
    document: '<path d="M5 2.6h6.2l3.8 3.8v11H5z"/><path d="M11.2 2.6v3.8h3.8"/><path d="M7.6 11h4.8M7.6 14h4.8"/>',
    building: '<path d="M2.8 8.6L10 3.4l7.2 5.2"/><path d="M5.2 9.4v6.4M9 9.4v6.4M11 9.4v6.4M14.8 9.4v6.4"/><path d="M2.6 17.4h14.8"/>',
    flag: '<path d="M5.6 17.2V3.4"/><path d="M5.6 4.3c3-1.5 6 1.5 9 .3v6.4c-3 1.2-6-1.8-9-.3z"/>',
    photo: '<rect x="2.8" y="4.2" width="14.4" height="11.6" rx="2.1"/><circle cx="7.4" cy="8.5" r="1.5"/><path d="M4.6 14.4l4.1-3.7 3 2.7 2.2-1.9 3.3 3"/>',
    news: '<path d="M4 4.2h9.6v12H5.6A1.6 1.6 0 014 14.6z"/><path d="M13.6 7.2h2.8v7.6a1.4 1.4 0 01-1.4 1.4h-1.4"/><path d="M6.5 7.2h4.8M6.5 10h4.8"/>',
    source: '<path d="M8.6 11.4a3 3 0 004.2 0l2.6-2.6a3 3 0 00-4.2-4.2L10 5.8"/><path d="M11.4 8.6a3 3 0 00-4.2 0L4.6 11.2a3 3 0 004.2 4.2l1.2-1.2"/>'
  };

  function icon(name) {
    return (
      '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" ' +
      'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
      (PATHS[name] || PATHS.record) +
      "</svg>"
    );
  }

  function esc(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, (ch) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;"
    })[ch]);
  }

  function href(value) {
    try {
      const url = new URL(String(value), window.location.href);
      return /^https?:$/.test(url.protocol) ? url.href : "";
    } catch (error) {
      return "";
    }
  }

  // Meeting kind -> icon. A record of a 회의 reads as a minute/record, a 본회의 as the
  // assembly itself, a 기념식 as a flag; anything else falls back to the record glyph.
  const TAG_ICON = { 회의: "record", 위원회: "people", 본회의: "building", 기념식: "flag", 토론회: "people", "5분발언": "record" };

  const LINKS = [
    { icon: "\u25C6", label: "정책자료", href: "./policy.html" },
    { icon: "\u25C6", label: "의원 소개", href: "./about.html" },
    { icon: "\u25C6", label: "의정활동", href: "./activity.html" },
    { icon: "\u25C6", label: "미디어", href: "./media.html" },
    { icon: "\u2197", label: "의회 공식 페이지", href: "https://council.jeonnam-gwangju.go.kr/jngjassem/contents/lawmakerList", external: true },
    { icon: "\u2197", label: "중앙선거관리위원회", href: "http://data.nec.go.kr/resource/Cnddt_100157517520260603", external: true }
  ];

  // Three verified records plus a fourth slot that states the record count.
  // The reference mockup shows four cards; we do not invent a fourth activity.
  function renderKeyActivities(activities) {
    const grid = document.getElementById("keyActivities");
    if (!grid) return;
    grid.innerHTML = "";
    activities.slice(0, 3).forEach((a) => {
      const card = document.createElement("a");
      card.className = "key-activity-card";
      card.href = "./activity.html";
      card.innerHTML =
        (a.thumb
          ? '<div class="ka-media">' +
              '<img class="ka-thumb" src="' + esc(href(a.thumb)) + '" alt="" loading="lazy" ' +
                'onerror="this.style.visibility=\'hidden\'" />' +
              '<span class="ka-badge" aria-hidden="true">' + icon(TAG_ICON[a.tag] || "record") + "</span>" +
            "</div>"
          : "") +
        '<div class="ka-body">' +
          '<span class="ka-date">' + esc(a.date) + " · " + esc(a.tag) + "</span>" +
          '<p class="ka-title">' + esc(a.title) + "</p>" +
          '<p class="ka-desc">' + esc(a.body || "") + "</p>" +
        "</div>";
      grid.appendChild(card);
    });

    const summary = document.createElement("a");
    summary.className = "key-activity-card is-summary";
    summary.href = "./activity.html";
    summary.innerHTML =
      '<div class="ka-body">' +
        '<span class="ka-date">전체 기록</span>' +
        '<span class="ka-count">' + activities.length + "건</span>" +
        '<p class="ka-desc">의회 공개 자료로 확인한 의정활동 기록입니다.</p>' +
        '<span class="ka-foot">전체 목록 보기 →</span>' +
      "</div>";
    grid.appendChild(summary);
  }

  // Counts of material held on this page — not achievement or performance data.
  function renderStats(activities, mediaTiles, newsItems) {
    const list = document.getElementById("statList");
    if (!list) return;
    const items = [
      ["record", "의정활동 기록", activities.length + "건"],
      ["photo", "사진·영상 자료", mediaTiles.length + "건"],
      ["news", "의정소식", newsItems.length + "건"],
      ["source", "자료 출처", "3곳"]
    ];
    list.innerHTML = items.map((it) =>
      '<li class="stat-item">' +
        '<span class="stat-icon" aria-hidden="true">' + icon(it[0]) + "</span>" +
        "<span>" +
          '<span class="stat-value">' + it[2] + "</span>" +
          '<span class="stat-label">' + it[1] + "</span>" +
        "</span>" +
      "</li>"
    ).join("");
  }

  function renderNewsColumn(newsItems) {
    const list = document.getElementById("homeNews");
    if (!list) return;
    const items = newsItems.slice(0, 3);
    if (items.length === 0) {
      list.innerHTML =
        '<li><p class="col-item-meta">확인된 의정소식이 아직 없습니다. ' +
        "새 소식은 의회 공식 페이지와 같은 기준으로 확인한 뒤 올립니다.</p></li>";
      return;
    }
    list.innerHTML = items.map((n) => {
      const url = href(n.url);
      const title = url
        ? '<a href="' + esc(url) + '" target="_blank" rel="noopener">' + esc(n.title) + "</a>"
        : esc(n.title);
      return "<li>" +
        '<p class="col-item-meta">' + esc(n.date) + (n.source ? " · " + esc(n.source) : "") + "</p>" +
        '<p class="col-item-title">' + title + "</p>" +
        '<p class="col-item-meta">' + esc(n.body || "") + "</p>" +
      "</li>";
    }).join("");
  }

  function renderMediaColumn(mediaTiles) {
    const list = document.getElementById("homeMedia");
    if (!list) return;
    // Only tiles that own an image: the video links have no thumbnail of their own.
    const picks = mediaTiles.filter((m) => m.thumb).slice(1, 4);
    list.innerHTML = picks.map((m) =>
      "<li>" +
        '<a class="col-item" href="' + esc(href(m.url) || "#") + '" target="_blank" rel="noopener">' +
          '<img class="col-thumb" src="' + esc(href(m.thumb)) + '" alt="" loading="lazy" ' +
            'onerror="this.style.visibility=\'hidden\'" />' +
          "<div>" +
            '<p class="col-item-title">' + esc(m.title) + "</p>" +
            '<p class="col-item-meta">' + esc(m.kind) + "</p>" +
          "</div>" +
        "</a>" +
      "</li>"
    ).join("");
  }

  function renderLinkColumn() {
    const grid = document.getElementById("homeLinks");
    if (!grid) return;
    grid.innerHTML = LINKS.map((l) =>
      '<a class="col-tile" href="' + l.href + '"' +
        (l.external ? ' target="_blank" rel="noopener"' : "") + ">" +
        '<span class="col-tile-icon" aria-hidden="true">' + l.icon + "</span>" +
        '<span class="col-tile-label">' + l.label + "</span>" +
      "</a>"
    ).join("");
  }

  function renderHomeDataError() {
    const grid = document.getElementById("keyActivities");
    if (grid) grid.innerHTML = '<p class="source-note">자료를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.</p>';
    const news = document.getElementById("homeNews");
    if (news) news.innerHTML = '<li><p class="col-item-meta">자료를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.</p></li>';
    const media = document.getElementById("homeMedia");
    if (media) media.innerHTML = '<li><p class="col-item-meta">자료를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.</p></li>';
  }

  document.addEventListener("DOMContentLoaded", function () {
    renderLinkColumn();
    const ready = window.COUNCILLOR_DATA_READY;
    if (!ready) { renderHomeDataError(); return; }
    ready.then(function (data) {
      if (!data) { renderHomeDataError(); return; }
      const activities = data.activity.items;
      const mediaTiles = data.media.tiles;
      const NEWS = activities.filter((item) => item.featured === true);
      renderKeyActivities(activities);
      renderStats(activities, mediaTiles, NEWS);
      renderNewsColumn(NEWS);
      renderMediaColumn(mediaTiles);
    });
  });
})();
