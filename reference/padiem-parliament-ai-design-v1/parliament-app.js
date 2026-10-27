/*
 * PADIEM Parliament AI — 프로토타입 동작 (#5967 1차)
 *
 * 네트워크 0: fetch·XHR·WebSocket을 한 번도 호출하지 않습니다. 운영 제품(축사·SNS·
 * 회의록·활동집)의 인증/AI 생성/저장 원점은 이 파일 바깥에 그대로 있고, 연결 여부는
 * 시안을 승인한 뒤의 별도 작업입니다. 여기서는 화면 전환·테마 축·편집 경험만 동작합니다.
 */
(function () {
  "use strict";

  const COUNTRIES = ["kr", "us", "fr", "uk"];
  const STYLES = ["classic", "modern", "dark", "light", "minimal"];
  const THEME_KEY = "padiem-parliament-theme";

  const WORKS = {
    speech: {
      label: "축사·인사말",
      fields: [
        { name: "event", kind: "text", text: "행사명", hint: "제78주년 광복절 기념식" },
        { name: "date", kind: "date", text: "일자" },
        { name: "place", kind: "text", text: "장소", hint: "강서문화회관" },
        { name: "audience", kind: "text", text: "청중", hint: "주민 200명" },
        { name: "author", kind: "text", text: "발언자", hint: "김의원" },
        { name: "message", kind: "textarea", text: "전할 메시지", hint: "함께 성장하는 지역사회" },
        { name: "length", kind: "select", text: "길이", options: [["short", "짧게"], ["medium", "중간"], ["long", "길게"]], value: "medium" },
        { name: "tone", kind: "select", text: "말투", options: [["formal", "공식"], ["warm", "따뜻한"], ["concise", "간결"]], value: "formal" }
      ],
      skeleton: (v) => [
        (v.event || "행사명") + "에서 뵙게 되어 기쁩니다.",
        "",
        "오늘 " + (v.place || "장소") + "을 찾아주신 " + (v.audience || "여러분") + "께 깊이 감사드립니다.",
        (v.message || "전할 메시지") + " — 그 한 가지 말씀을 중심으로 짧은 여정과 앞날을 함께 나누고자 합니다.",
        "",
        "— " + (v.author || "발언자")
      ].join("\n")
    },
    sns: {
      label: "SNS 홍보",
      fields: [
        { name: "event", kind: "text", text: "행사명", hint: "주민 정원 사업 설명회" },
        { name: "whenwhere", kind: "text", text: "일시·장소", hint: "10월 30일 오후 2시, 구청 소회의실" },
        { name: "content", kind: "textarea", text: "핵심 내용", hint: "정원 사업 신청 방법과 지원 금액 안내" },
        { name: "audience", kind: "text", text: "대상 독자", hint: "구내 상인" },
        { name: "platform", kind: "select", text: "플랫폼", options: [["blog", "블로그"], ["facebook", "페이스북"], ["instagram", "인스타그램"]], value: "blog" }
      ],
      skeleton: (v) => [
        "[" + (v.platform || "블로그") + "] " + (v.event || "행사명"),
        "",
        "일시·장소: " + (v.whenwhere || "일시·장소"),
        (v.content || "핵심 내용"),
        "",
        (v.audience || "대상 독자") + "께 전할 한 문단 + 해시태그 영역"
      ].join("\n")
    },
    meeting: {
      label: "회의정리·활동집",
      fields: [
        { name: "title", kind: "text", text: "제목", hint: "10월 주민 민원 회의" },
        { name: "when", kind: "text", text: "일시", hint: "2026-10-24 10:00" },
        { name: "attendees", kind: "text", text: "참석자", hint: "비서실장, 지역 담당" },
        { name: "content", kind: "textarea", text: "논의 내용", hint: "항구 도로 보수 일정과 버스 노선 조정" }
      ],
      skeleton: (v) => [
        "회의록 — " + (v.title || "제목"),
        "일시: " + (v.when || "일시") + " / 참석: " + (v.attendees || "참석자"),
        "",
        "1. 논의: " + (v.content || "논의 내용"),
        "2. 결정: (채워 넣으세요)",
        "3. 후속: (담당 / 기한)"
      ].join("\n")
    }
  };

  const home = document.getElementById("paHome");
  const editor = document.getElementById("paEditor");
  const metaFields = document.getElementById("paMetaFields");
  const kicker = document.getElementById("paEditorTitle");
  const documentBox = document.getElementById("paDocument");
  const status = document.getElementById("paStatus");
  const scene = document.querySelector(".pa-scene");
  const countrySelect = document.getElementById("paCountry");
  const styleSelect = document.getElementById("paStyle");
  const root = document.documentElement;

  const state = { work: null };

  function store() {
    try { return window.localStorage || null; } catch (_) { return null; }
  }

  function prefersReduced() {
    try { return Boolean(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches); } catch (_) { return false; }
  }

  function applyTheme(country, style) {
    const safeCountry = COUNTRIES.indexOf(country) >= 0 ? country : "kr";
    const safeStyle = STYLES.indexOf(style) >= 0 ? style : "dark";
    root.dataset.country = safeCountry;
    root.dataset.style = safeStyle;
    countrySelect.value = safeCountry;
    styleSelect.value = safeStyle;
    try {
      const kept = store();
      if (kept) kept.setItem(THEME_KEY, JSON.stringify({ country: safeCountry, style: safeStyle }));
    } catch (_) {}
  }

  function readTheme() {
    try {
      const raw = store() && store().getItem(THEME_KEY);
      if (!raw) return {};
      const value = JSON.parse(raw);
      return value && typeof value === "object" ? value : {};
    } catch (_) { return {}; }
  }

  function buildField(spec, index) {
    const label = document.createElement("label");
    const caption = document.createElement("span");
    caption.textContent = spec.text;
    label.appendChild(caption);

    let field;
    if (spec.kind === "select") {
      field = document.createElement("select");
      spec.options.forEach(([value, shown]) => {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = shown;
        if (value === spec.value) option.selected = true;
        field.appendChild(option);
      });
    } else {
      field = document.createElement(spec.kind === "textarea" ? "textarea" : "input");
      if (spec.kind === "date") field.type = "date";
      else if (spec.kind === "text") field.type = "text";
      if (spec.kind === "textarea") field.rows = 3;
      if (spec.hint) field.placeholder = spec.hint;
    }
    field.name = spec.name;
    field.id = "paField-" + state.work + "-" + spec.name;
    if (index === 0) field.dataset.firstField = "1";
    label.setAttribute("for", field.id);
    label.appendChild(field);
    return label;
  }

  function buildMeta(work) {
    metaFields.replaceChildren();
    WORKS[work].fields.forEach((spec, index) => metaFields.appendChild(buildField(spec, index)));
  }

  function metaValues() {
    const values = {};
    WORKS[state.work].fields.forEach((spec) => {
      const field = metaFields.querySelector('[name="' + spec.name + '"]');
      values[spec.name] = field ? String(field.value || "").trim() : "";
    });
    return values;
  }

  function announce(message) {
    status.textContent = message;
  }

  function countText() {
    return documentBox.value.replace(/\s+/g, "").length + "자";
  }

  function markCard(work) {
    document.querySelectorAll(".pa-work-select").forEach((button) => {
      button.setAttribute("aria-expanded", button.dataset.work === work ? "true" : "false");
    });
  }

  function openWork(work, moveFocus) {
    if (!WORKS[work]) return null;
    state.work = work;
    home.hidden = true;
    editor.hidden = false;
    kicker.textContent = WORKS[work].label;
    buildMeta(work);
    markCard(work);
    try { window.history.replaceState(null, "", "#/" + work); } catch (_) {}
    announce("프로토타입 화면입니다. 생성·저장 API는 호출되지 않습니다.");
    if (moveFocus !== false) {
      const first = metaFields.querySelector("[data-first-field]");
      if (first && typeof first.focus === "function") first.focus();
    }
    return work;
  }

  function goHome() {
    state.work = null;
    editor.hidden = true;
    home.hidden = false;
    markCard(null);
    try { window.history.replaceState(null, "", window.location.pathname + window.location.search); } catch (_) {}
    const cta = document.getElementById("paHomeCta");
    if (cta && typeof cta.focus === "function") cta.focus();
  }

  function workFromUrl() {
    const value = (window.location.hash || "").replace(/^#\/?/, "");
    return WORKS[value] ? value : null;
  }

  document.querySelectorAll(".pa-work-select").forEach((button) => {
    button.addEventListener("click", () => {
      if (state.work === button.dataset.work) goHome();
      else openWork(button.dataset.work);
    });
  });

  document.getElementById("paHomeCta").addEventListener("click", () => {
    const works = document.querySelector(".pa-works");
    if (works && typeof works.scrollIntoView === "function") {
      works.scrollIntoView({ behavior: prefersReduced() ? "auto" : "smooth", block: "start" });
    }
    const first = document.querySelector(".pa-work-select");
    if (first && typeof first.focus === "function") first.focus();
  });

  document.getElementById("paBack").addEventListener("click", goHome);

  document.getElementById("paDraft").addEventListener("click", () => {
    if (!state.work) return;
    documentBox.value = WORKS[state.work].skeleton(metaValues());
    announce("입력값으로 뼈대만 채웠습니다 — 운영 생성(POST /api/chat)은 이 화면에서 호출되지 않습니다. " + countText());
    documentBox.focus();
  });

  documentBox.addEventListener("input", () => announce(countText()));

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !editor.hidden) goHome();
  });

  [countrySelect, styleSelect].forEach((select) => {
    select.addEventListener("change", () => applyTheme(countrySelect.value, styleSelect.value));
  });

  // 히어로 시차: 한 속성(transform)만, rAF로 묶고 감소 동작에서는 완전히 끄는다.
  let queued = false;
  function paintParallax() {
    queued = false;
    if (!scene || prefersReduced()) { return; }
    const offset = Math.min(window.scrollY || 0, 640) * 0.18;
    scene.style.transform = "translate3d(0," + offset.toFixed(1) + "px,0)";
  }
  window.addEventListener("scroll", () => {
    if (!queued) { queued = true; window.requestAnimationFrame(paintParallax); }
  }, { passive: true });

  const saved = readTheme();
  applyTheme(saved.country, saved.style);

  const wanted = workFromUrl();
  if (wanted) openWork(wanted, false);

  window.PadiemParliamentProto = {
    state: () => ({ work: state.work, country: root.dataset.country, style: root.dataset.style }),
    open: (work) => openWork(work),
    home: goHome,
    theme: () => ({ countries: COUNTRIES.slice(), styles: STYLES.slice() })
  };
})();
