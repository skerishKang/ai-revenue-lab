// Prototype app.js — councillor homepage redesign
const ACTIVITIES = [
  { date: "2026-07-01", tag: "의회", title: "전남광주통합특별시의회 제1대 개원 · 보건복지위원회·예산결산특별위원회 위원", url: "https://council.jeonnam-gwangju.go.kr/jngjassem/contents/lawmakerList", body: "전남광주통합특별시의회 제1대 개원. 보건복지위원회와 예산결산특별위원회 위원으로 활동." },
  { date: "2026-06-25", tag: "기념식", title: "6·25전쟁 제76주년 기념식 행사", url: "https://council.gwangju.go.kr/9imr/index.do?PID=014", body: "6·25전쟁 제76주년 기념식 참석." },
  { date: "2026-06-22", tag: "본회의", title: "제344회 임시회 제3차 본회의", url: "https://council.gwangju.go.kr/9imr/index.do?PID=014", body: "제344회 임시회 제3차 본회의 참석." },
  { date: "2026-06-15", tag: "위원회", title: "제1차 산업건설위원회", url: "https://council.gwangju.go.kr/9imr/index.do?PID=014", body: "제1차 산업건설위원회 참석." },
  { date: "2026-06-03", tag: "당선", title: "제9회 전국동시지방선거 남구 제1선거구 당선", url: "http://data.nec.go.kr/resource/Cnddt_100157517520260603", body: "중앙선거관리위원회 후보자 공개 자료에 당선인으로 기록되어 있습니다." }
];

const MEDIA = [
  { kind: "포토", title: "의정활동 사진 자료실", url: "https://council.gwangju.go.kr/9imr/index.do?PID=014", notes: ["제8·9대 광주광역시의회 의정활동 사진", "새 의회 기록은 의회 의원 소개 페이지에서 확인됩니다"] },
  { kind: "영상", title: "의정활동영상 · 영상인사말", url: "https://council.gwangju.go.kr/9imr/index.do?PID=017", notes: ["본회의 발언·현장 기록 영상", "첫 화면과 소개 영상과 같은 출처의 공식 기록"] },
  { kind: "포토", title: "의정스케치", url: "https://council.gwangju.go.kr/9imr/index.do?PID=010", notes: ["의정활동 스케치 사진"] },
  { kind: "영상", title: "영상인사말", url: "https://council.gwangju.go.kr/9imr/index.do?PID=029", notes: ["영상 인사말"] },
  { kind: "본회의", title: "제316회 교육행정질문", url: "https://www.youtube.com/watch?v=8vdllvPwRAY", notes: ["유튜브"] },
  { kind: "본회의", title: "제325회 제1차 정례회 시정질문", url: "https://www.youtube.com/watch?v=8QYTXpxW6pA", notes: ["유튜브"] },
  { kind: "5분발언", title: "제327회 교육행정 5분자유발언", url: "https://www.youtube.com/watch?v=rc87So2Dgcs", notes: ["유튜브"] },
  { kind: "채널", title: "광주광역시의회 유튜브", url: "https://www.youtube.com/channel/UCvQfeQB_3OQwgclBaqamidw", notes: ["공식 채널"] },
  { kind: "의회", title: "전남광주통합특별시의회 의원 소개", url: "https://council.jeonnam-gwangju.go.kr/jngjassem/contents/lawmakerList", notes: ["공식 페이지"] }
];

const NEWS = [
  { date: "2026-10-25", title: "의정소식 안내", body: "이 페이지에는 의원실에서 확인한 공식 소식만 올립니다. 새 소식은 의회 공식 페이지와 같은 기준으로 정리되어 표시됩니다." },
  { date: "2026-10-25", title: "자료 기준", body: "표시한 직위·상임위원회·학력·당선 기록은 전남광주통합특별시의회 의원 소개와 중앙선거관리위원회 공개 자료에 맞췄습니다." }
];

function renderActivities(filter = "all", query = "") {
  const list = document.getElementById("activityList");
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
  filtered.forEach((a, idx) => {
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
  document.getElementById("detailBody").textContent = a.body || "";
  const link = document.getElementById("detailLink");
  link.href = a.url;
  detail.scrollIntoView({ behavior: "smooth", block: "start" });
}

function renderMedia() {
  const grid = document.getElementById("mediaGrid");
  if (!grid) return;
  grid.innerHTML = "";
  MEDIA.forEach(m => {
    const tile = document.createElement("div");
    tile.className = "media-tile";
    tile.setAttribute("tabindex", "0");
    tile.setAttribute("role", "link");
    tile.innerHTML = `<div class="tile-kind">${m.kind}</div><div class="tile-title">${m.title}</div><ul class="tile-notes">${(m.notes||[]).map(n=>`<li>${n}</li>`).join("")}</ul>`;
    const open = () => window.open(m.url, "_blank", "noopener");
    tile.addEventListener("click", open);
    tile.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); } });
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

// Theme toggle
function initTheme() {
  const btn = document.getElementById("themeToggle");
  if (!btn) return;
  const saved = localStorage.getItem("theme");
  if (saved) document.documentElement.setAttribute("data-theme", saved);
  btn.textContent = document.documentElement.getAttribute("data-theme") === "light" ? "다크" : "라이트";
  btn.addEventListener("click", () => {
    const cur = document.documentElement.getAttribute("data-theme");
    const next = cur === "light" ? "dark" : "light";
    document.documentElement.setAttribute("data-theme", next);
    localStorage.setItem("theme", next);
    btn.textContent = next === "light" ? "다크" : "라이트";
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

  // Smooth scroll for nav
  document.querySelectorAll('a[href^="#"]').forEach(a => {
    a.addEventListener("click", (e) => {
      const id = a.getAttribute("href").slice(1);
      const target = document.getElementById(id);
      if (target) { e.preventDefault(); target.scrollIntoView({ behavior: "smooth" }); }
    });
  });
});
