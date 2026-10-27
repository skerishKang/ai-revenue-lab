// Home-page renderers for #5972.
// app.js keeps the shared features (theme toggle, activity list/detail, media
// grid, news list). This file only fills the blocks that exist on index.html and
// reads the same verified arrays, so no inner page is affected by it.
(function () {
  "use strict";

  // Same three verified thumbnails app.js uses for the activity cards.
  const THUMBS = [
    "https://council.gwangju.go.kr/attach/270/98cd8f6145e5c736ed4354910280438at.jpg",
    "https://council.gwangju.go.kr/attach/270/6ff19762dcce4baefb738da6599dab22t.jpg",
    "https://council.gwangju.go.kr/attach/270/065fd00c569698e4fdaeeff940d56064t.jpg"
  ];

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
  function renderKeyActivities() {
    const grid = document.getElementById("keyActivities");
    if (!grid) return;
    grid.innerHTML = "";
    ACTIVITIES.slice(0, 3).forEach((a, i) => {
      const card = document.createElement("a");
      card.className = "key-activity-card";
      card.href = "./activity.html";
      card.innerHTML =
        '<div class="ka-media">' +
          '<img class="ka-thumb" src="' + THUMBS[i] + '" alt="" loading="lazy" ' +
            'onerror="this.style.visibility=\'hidden\'" />' +
          '<span class="ka-badge" aria-hidden="true">' + (i + 1) + "</span>" +
        "</div>" +
        '<div class="ka-body">' +
          '<span class="ka-date">' + a.date + " · " + a.tag + "</span>" +
          '<p class="ka-title">' + a.title + "</p>" +
          '<p class="ka-desc">' + (a.body || "") + "</p>" +
        "</div>";
      grid.appendChild(card);
    });

    const summary = document.createElement("a");
    summary.className = "key-activity-card is-summary";
    summary.href = "./activity.html";
    summary.innerHTML =
      '<div class="ka-body">' +
        '<span class="ka-date">전체 기록</span>' +
        '<span class="ka-count">' + ACTIVITIES.length + "건</span>" +
        '<p class="ka-desc">의회 공개 자료로 확인한 의정활동 기록입니다.</p>' +
        '<span class="ka-foot">전체 목록 보기 →</span>' +
      "</div>";
    grid.appendChild(summary);
  }

  // Counts of material held on this page — not achievement or performance data.
  function renderStats() {
    const list = document.getElementById("statList");
    if (!list) return;
    const items = [
      ["의정활동 기록", ACTIVITIES.length + "건"],
      ["사진·영상 자료", MEDIA.length + "건"],
      ["의정소식", NEWS.length + "건"],
      ["자료 출처", "3곳"]
    ];
    list.innerHTML = items.map((it, i) =>
      '<li class="stat-item">' +
        '<span class="stat-icon" aria-hidden="true">' + (i + 1) + "</span>" +
        "<span>" +
          '<span class="stat-value">' + it[1] + "</span>" +
          '<span class="stat-label">' + it[0] + "</span>" +
        "</span>" +
      "</li>"
    ).join("");
  }

  function renderNewsColumn() {
    const list = document.getElementById("homeNews");
    if (!list) return;
    const items = NEWS.slice(0, 3);
    if (items.length === 0) {
      list.innerHTML =
        '<li><p class="col-item-meta">확인된 의정소식이 아직 없습니다. ' +
        "새 소식은 의회 공식 페이지와 같은 기준으로 확인한 뒤 올립니다.</p></li>";
      return;
    }
    list.innerHTML = items.map(n =>
      "<li>" +
        '<p class="col-item-meta">' + n.date + "</p>" +
        '<p class="col-item-title">' + n.title + "</p>" +
        '<p class="col-item-meta">' + n.body + "</p>" +
      "</li>"
    ).join("");
  }

  function renderMediaColumn() {
    const list = document.getElementById("homeMedia");
    if (!list) return;
    const video = MEDIA.filter(m => m.kind === "영상")[0];
    const picks = [MEDIA[1], MEDIA[2], video].filter(Boolean);
    list.innerHTML = picks.map(m =>
      "<li>" +
        '<a class="col-item" href="' + m.url + '" target="_blank" rel="noopener">' +
          '<img class="col-thumb" src="' + m.thumb + '" alt="" loading="lazy" ' +
            'onerror="this.style.visibility=\'hidden\'" />' +
          "<div>" +
            '<p class="col-item-title">' + m.title + "</p>" +
            '<p class="col-item-meta">' + m.kind + "</p>" +
          "</div>" +
        "</a>" +
      "</li>"
    ).join("");
  }

  function renderLinkColumn() {
    const grid = document.getElementById("homeLinks");
    if (!grid) return;
    grid.innerHTML = LINKS.map(l =>
      '<a class="col-tile" href="' + l.href + '"' +
        (l.external ? ' target="_blank" rel="noopener"' : "") + ">" +
        '<span class="col-tile-icon" aria-hidden="true">' + l.icon + "</span>" +
        '<span class="col-tile-label">' + l.label + "</span>" +
      "</a>"
    ).join("");
  }

  document.addEventListener("DOMContentLoaded", function () {
    // app.js defines the data arrays; without them there is nothing to render.
    if (typeof ACTIVITIES === "undefined" || typeof MEDIA === "undefined" || typeof NEWS === "undefined") return;
    renderKeyActivities();
    renderStats();
    renderNewsColumn();
    renderMediaColumn();
    renderLinkColumn();
  });
})();
