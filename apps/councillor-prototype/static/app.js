// Prototype app.js — councillor homepage redesign
// Content mirrors static/miraen.json; tests/test_mobile_navigation_contract.py
// fails if the two drift.
const ACTIVITIES = [
  { date: "2026-07-01", tag: "의회", title: "전남광주통합특별시의회 제1대 개원 · 보건복지위원회·예산결산특별위원회 위원", url: "https://council.jeonnam-gwangju.go.kr/jngjassem/contents/lawmakerList" },
  { date: "2026-06-25", tag: "기념식", title: "6·25전쟁 제76주년 기념식 행사", url: "https://council.gwangju.go.kr/9imr/index.do?PID=014" },
  { date: "2026-06-22", tag: "본회의", title: "제344회 임시회 제3차 본회의", url: "https://council.gwangju.go.kr/9imr/index.do?PID=014" },
  { date: "2026-06-15", tag: "위원회", title: "제1차 산업건설위원회", url: "https://council.gwangju.go.kr/9imr/index.do?PID=014" },
  { date: "2026-06-03", tag: "당선", title: "제9회 전국동시지방선거 남구 제1선거구 당선", url: "http://data.nec.go.kr/resource/Cnddt_100157517520260603", body: "중앙선거관리위원회 후보자 공개 자료에 당선인으로 기록되어 있습니다." }
];

// Only entries with their own image carry a thumb. Video, YouTube, channel and
// council links used to repeat one hero poster on six tiles; they now render as
// labelled tiles instead of pretending the poster belongs to each item.
const MEDIA = [
  { kind: "프로필", title: "임미란 의원 공식 프로필 사진", url: "https://council.gwangju.go.kr/9imr/index.do?PID=003", thumb: "./static/images/profile-portrait.webp", notes: ["광주광역시의회 공식 페이지 제공", "출처: council.gwangju.go.kr"] },
  { kind: "포토", title: "제1차 산업건설위원회", url: "https://council.gwangju.go.kr/9imr/index.do?PID=014", thumb: "./static/images/media-01.jpg", notes: ["의회 공개 사진자료실", "2026-06-15"] },
  { kind: "포토", title: "제46주년 5·18민주화운동 기념 민주평화대행진", url: "https://council.gwangju.go.kr/9imr/index.do?PID=014", thumb: "./static/images/media-02.jpg", notes: ["의회 공개 사진자료실", "2026-05-17"] },
  { kind: "포토", title: "제344회 임시회 제3차 본회의", url: "https://council.gwangju.go.kr/9imr/index.do?PID=014", thumb: "./static/images/media-03.jpg", notes: ["의회 공개 사진자료실", "2026-06-22"] },
  { kind: "포토", title: "6·25전쟁 제76주년 기념식", url: "https://council.gwangju.go.kr/9imr/index.do?PID=014", thumb: "./static/images/media-04.jpg", notes: ["의회 공개 사진자료실", "2026-06-25"] },
  { kind: "포토", title: "제344회 임시회 제1차 본회의(개회)", url: "https://council.gwangju.go.kr/9imr/index.do?PID=014", thumb: "./static/images/media-05.jpg", notes: ["의회 공개 사진자료실", "2026-06-15"] },
  { kind: "포토", title: "제71회 현충일 추념식", url: "https://council.gwangju.go.kr/9imr/index.do?PID=014", thumb: "./static/images/media-06.jpg", notes: ["의회 공개 사진자료실", "2026-06-06"] },
  { kind: "포토", title: "제1차 산업건설위원회 (2)", url: "https://council.gwangju.go.kr/9imr/index.do?PID=014", thumb: "./static/images/media-07.jpg", notes: ["의회 공개 사진자료실", "2026-06-15"] },
  { kind: "포토", title: "제46주년 5·18민주화운동 전야제", url: "https://council.gwangju.go.kr/9imr/index.do?PID=014", thumb: "./static/images/media-08.jpg", notes: ["의회 공개 사진자료실", "2026-05-17"] },
  { kind: "포토", title: "의정스케치", url: "https://council.gwangju.go.kr/9imr/index.do?PID=010", notes: ["의회 공개 사진자료실"] },
  { kind: "영상", title: "의정활동영상 · 영상인사말", url: "https://council.gwangju.go.kr/9imr/index.do?PID=017", notes: ["본회의 발언·현장 기록 영상", "의회가 공개한 공식 기록"] },
  { kind: "영상", title: "영상인사말", url: "https://council.gwangju.go.kr/9imr/index.do?PID=029", notes: ["영상 인사말"] },
  { kind: "본회의", title: "제316회 교육행정질문", url: "https://www.youtube.com/watch?v=8vdllvPwRAY", notes: ["유튜브"] },
  { kind: "본회의", title: "제325회 제1차 정례회 시정질문", url: "https://www.youtube.com/watch?v=8QYTXpxW6pA", notes: ["유튜브"] },
  { kind: "5분발언", title: "제327회 교육행정 5분자유발언", url: "https://www.youtube.com/watch?v=rc87So2Dgcs", notes: ["유튜브"] },
  { kind: "채널", title: "광주광역시의회 유튜브", url: "https://www.youtube.com/channel/UCvQfeQB_3OQwgclBaqamidw", notes: ["공식 채널"] },
  { kind: "의회", title: "전남광주통합특별시의회 의원 소개", url: "https://council.jeonnam-gwangju.go.kr/jngjassem/contents/lawmakerList", notes: ["공식 페이지"] }
];

// 안내문은 소식이 아니므로 소식 목록과 개수에서 제외합니다.
const NEWS = [];

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

function renderActivities(filter = "all", query = "") {
  const list = document.getElementById("activityList");
  if (!list) return;
  const detail = document.getElementById("activityDetail");
  if (detail) detail.hidden = true;
  list.hidden = false;
  list.innerHTML = "";
  const q = query.trim().toLowerCase();
  const filtered = ACTIVITIES.filter(a => {
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
    li.innerHTML = `<div class="item-date">${a.date}<span class="item-tag">${a.tag}</span></div><div class="item-title">${a.title}</div>`;
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
  document.getElementById("detailDate").textContent = a.date + " · " + a.tag;
  const body = document.getElementById("detailBody");
  body.textContent = a.body || "";
  body.hidden = !a.body;
  const link = document.getElementById("detailLink");
  link.href = a.url;
  scrollToElement(detail, "start");
}

function renderMedia() {
  const grid = document.getElementById("mediaGrid");
  if (!grid) return;
  grid.innerHTML = "";
  MEDIA.forEach(m => {
    const tile = document.createElement("a");
    tile.className = "media-tile";
    tile.href = m.url;
    tile.target = "_blank";
    tile.rel = "noopener";
    tile.setAttribute("tabindex", "0");
    const thumb = m.thumb
      ? `<img class="tile-thumb" src="${m.thumb}" alt="${m.title}" loading="lazy" onerror="this.style.display='none'" />`
      : `<span class="tile-thumb tile-thumb-empty" aria-hidden="true">${m.kind}</span>`;
    tile.innerHTML = thumb + `<div class="tile-kind">${m.kind}</div><div class="tile-title">${m.title}</div><ul class="tile-notes">${(m.notes || []).map(n => `<li>${n}</li>`).join("")}</ul>`;
    grid.appendChild(tile);
  });
}

function renderNews() {
  const list = document.getElementById("newsList");
  if (!list) return;
  list.innerHTML = "";
  NEWS.forEach(n => {
    const li = document.createElement("li");
    li.className = "news-item";
    li.innerHTML = `<div class="news-date">${n.date}</div><h3 class="news-title">${n.title}</h3><p class="news-body">${n.body}</p>`;
    list.appendChild(li);
  });
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
  renderActivities();
  renderMedia();
  renderNews();
  initTheme();

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
  document.querySelectorAll('a[href^="#"]').forEach(a => {
    a.addEventListener("click", (e) => {
      const id = a.getAttribute("href").slice(1);
      const target = document.getElementById(id);
      if (target) { e.preventDefault(); scrollToElement(target); }
    });
  });
});
