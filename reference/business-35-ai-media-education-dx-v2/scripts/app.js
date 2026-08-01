/* app.js — 파디엠 AI 미디어 업무전환 v2 interactions
   deterministic · deep-linkable · keyboard · reduced-motion safe */
(function () {
  "use strict";
  var P = window.PADIEM;
  var reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function $(s, r) { return (r || document).querySelector(s); }
  function $$(s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); }

  /* ---------- deep-link + scroll highlight (active nav) ---------- */
  var sectionIds = ["hero", "thesis", "diagnostic", "case", "workflow", "offers", "deliverables", "conversion"];
  function currentSection() {
    var y = window.scrollY + 90, cur = "hero";
    sectionIds.forEach(function (id) {
      var el = document.getElementById(id);
      if (el && el.offsetTop <= y) cur = id;
    });
    return cur;
  }
  var navLinks = $$("[data-nav-link]");
  function syncNav() {
    var cur = currentSection();
    navLinks.forEach(function (a) {
      var active = a.getAttribute("href") === "#" + cur;
      a.classList.toggle("is-active", active);
      if (active) a.setAttribute("aria-current", "location");
      else a.removeAttribute("aria-current");
    });
  }
  window.addEventListener("scroll", syncNav, { passive: true });
  window.addEventListener("hashchange", syncNav);

  /* ---------- interactive diagnostic (explicit run intent) ---------- */
  var form = $("#diag-form");
  var result = $("#diag-result");
  function readDiag() {
    var v = {};
    $$("[data-diag]", form).forEach(function (s) { v[s.name] = s.value; });
    return v;
  }
  function setDiagPending() {
    result.innerHTML = "<p class='empty'>선택이 변경되었습니다. <em>진단 결과 보기</em>를 눌러 결과를 업데이트하세요. 실제 제출·저장은 하지 않습니다.</p>";
  }
  function renderDiag() {
    var r = P.diag(readDiag());
    result.innerHTML =
      "<h3>" + r.org + " · " + r.team + "</h3>" +
      "<dl>" +
      "<div><dt>핵심 병목</dt><dd>" + r.coreBottleneck + "</dd></div>" +
      "<div><dt>사람 검토 지점</dt><dd>" + r.humanReview + "</dd></div>" +
      "<div><dt>우선 적용 업무</dt><dd>" + r.priorityWork + "</dd></div>" +
      "<div><dt>예상 산출물</dt><dd>" + r.outputs.join(" · ") + "</dd></div>" +
      "</dl>" +
      "<div class='rec'><dt>추천 프로그램</dt><dd><strong>" + r.program + "</strong> — " + r.programDesc + "</dd>" +
      "<dt>전환 가설</dt><dd>" + r.estimate.before + " → " + r.estimate.after + " (" + r.estimate.reduction + ")</dd></div>" +
      "<p class='price-note'>실제 제출·저장은 하지 않습니다.</p>";
  }
  // 조건 변경 → 아직 실행되지 않은 상태(결과 업데이트 필요)
  form.addEventListener("change", setDiagPending);
  // 진단 결과 보기 → 명시적으로 계산·렌더링
  $$("[data-diag-run]").forEach(function (b) {
    b.addEventListener("click", function () {
      renderDiag();
      result.scrollIntoView({ behavior: reduced ? "auto" : "smooth", block: "nearest" });
    });
  });

  /* ---------- signature workflow motion (board-triggered, restartable replay) ---------- */
  var wfBoard = $("[data-wf-board]");
  var wfSection = $("#workflow");
  var wfRunBtn = $("[data-wf-run]");
  var wfGen = 0;
  var wfTimers = [];
  var wfPlayed = false;

  function clearWfTimers() { wfTimers.forEach(function (t) { clearTimeout(t); }); wfTimers = []; }
  function resetWf() {
    $$("[data-wf-step]", wfBoard).forEach(function (li) { li.className = ""; });
    $$("[data-wf-transform] span", wfBoard).forEach(function (sp) { sp.classList.remove("is-on"); });
    var seal = $("[data-wf-seal]", wfBoard);
    if (seal) seal.textContent = "HUMAN-APPROVED OS";
  }
  var mark = function (sel, cls) { var el = $(sel, wfBoard); if (el) el.classList.add(cls); };
  function finalWf() {
    mark('[data-wf-step="b2"]', "is-hot"); mark('[data-wf-step="b4"]', "is-hot");
    $$("[data-wf-transform] span", wfBoard).forEach(function (sp) { sp.classList.add("is-on"); });
    mark('[data-wf-step="a2"]', "is-ai"); mark('[data-wf-step="a3"]', "is-ai");
    mark('[data-wf-step="a4"]', "is-review"); mark('[data-wf-step="a5"]', "is-review");
    mark('[data-wf-step="a6"]', "is-done"); mark('[data-wf-step="a7"]', "is-done");
    var seal = $("[data-wf-seal]", wfBoard);
    if (seal) seal.textContent = "HUMAN-APPROVED AI MEDIA OPERATING SYSTEM";
  }
  // Restartable replay: 매 클릭이 이전 timer 전부 취소 + generation 증가 후 처음부터 재생
  function playWf() {
    resetWf();
    clearWfTimers();
    var gen = ++wfGen;
    if (reduced) { finalWf(); return; }
    var at = function (ms, fn) {
      wfTimers.push(setTimeout(function () { if (gen !== wfGen) return; fn(); }, ms));
    };
    at(200, function () { mark('[data-wf-step="b2"]', "is-hot"); mark('[data-wf-step="b4"]', "is-hot"); });
    at(900, function () { var sp = $$("[data-wf-transform] span", wfBoard)[0]; if (sp) sp.classList.add("is-on"); });
    at(1700, function () {
      mark('[data-wf-step="a2"]', "is-ai"); mark('[data-wf-step="a3"]', "is-ai");
      var sp = $$("[data-wf-transform] span", wfBoard)[2]; if (sp) sp.classList.add("is-on");
    });
    at(2500, function () {
      mark('[data-wf-step="a4"]', "is-review"); mark('[data-wf-step="a5"]', "is-review");
      var sp = $$("[data-wf-transform] span", wfBoard)[1]; if (sp) sp.classList.add("is-on");
    });
    at(3300, finalWf);
  }
  // replay button — restartable (lock 없음), 상태 설명 유지
  var wfStatus = $("#wf-status") || null;
  if (!wfStatus) { wfStatus = document.createElement("span"); wfStatus.id = "wf-status"; wfStatus.className = "wf-status"; wfBoard.parentNode.insertBefore(wfStatus, wfBoard); }
  wfStatus.textContent = "업무전환 준비됨 — 재생은 다시 보기 버튼으로 언제든 재시작할 수 있습니다.";
  wfRunBtn.addEventListener("click", function () {
    wfStatus.textContent = "업무전환 재생 시작…";
    playWf();
    var g = wfGen;
    setTimeout(function () { if (g === wfGen && !reduced) wfStatus.textContent = "업무전환 최종 상태 — HUMAN-APPROVED AI MEDIA OPERATING SYSTEM"; }, 3350);
  });

  // viewport trigger: [data-wf-board]가 의미 있게 보일 때 첫 1회
  function shouldTrigger(entry) {
    var ratio = entry.intersectionRatio || 0;
    if (ratio >= 0.35) return true;
    var rect = entry.boundingClientRect;
    var vh = window.innerHeight;
    var vis = entry.intersectionRect ? entry.intersectionRect.height : 0;
    if (rect.height >= vh) {
      // tall board fallback: 의미 있는 가시 픽셀 + 보드 상단 ≤ 70% + 보드 하단 ≥ 20%
      return entry.isIntersecting && vis >= 80 && rect.top <= vh * 0.7 && rect.bottom >= vh * 0.2;
    }
    return false;
  }
  function triggerOnVisible() {
    if (wfPlayed) return;
    wfPlayed = true;
    playWf();
  }
  if ("IntersectionObserver" in window) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (shouldTrigger(en) && !wfPlayed) { triggerOnVisible(); io.disconnect(); }
      });
    }, { threshold: [0, 0.1, 0.35] });
    io.observe(wfBoard);
  } else {
    // IO 미지원 fallback: 보드가 의미 있게 보이는 시점(스크롤)에 한 번
    var onScroll = function () {
      var r = wfBoard.getBoundingClientRect();
      var vh = window.innerHeight;
      if (r.top <= vh * 0.7 && r.bottom >= vh * 0.2 && !wfPlayed) { triggerOnVisible(); window.removeEventListener("scroll", onScroll); }
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
  }
  // #workflow deep link: 보드가 배치된 뒤 실행
  if (location.hash === "#workflow") setTimeout(triggerOnVisible, 0);
  window.addEventListener("hashchange", function () { if (location.hash === "#workflow") setTimeout(triggerOnVisible, 0); });
  // test hook
  window.__wfGen = function () { return wfGen; };

  /* ---------- deliverable gallery (semantic controls) ---------- */
  var delDetail = $("#del-detail");
  function renderDel(key) {
    var d = P.deliverables[key];
    delDetail.innerHTML = "<h3>" + d.title + "</h3><p>" + d.body + "</p>";
  }
  $$("[data-del]").forEach(function (card) {
    card.addEventListener("click", function () {
      $$("[data-del]").forEach(function (c) { c.classList.remove("is-open"); c.setAttribute("aria-expanded", "false"); });
      card.classList.add("is-open");
      card.setAttribute("aria-expanded", "true");
      renderDel(card.getAttribute("data-del"));
    });
    card.addEventListener("keydown", function (e) {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); card.click(); }
    });
  });

  /* ---------- conversion CTA ---------- */
  var convResult = $("#conv-result");
  var convMap = {
    consult: {
      title: "30분 진단 상담 준비",
      body: "조직 조건을 먼저 확인할 수 있도록 진단 결과를 요약해 둡니다. 실제 접수 기능은 다음 단계이며, 상담 준비 화면만 제공합니다."
    },
    scenario: {
      title: "우리 조직 적용 시나리오",
      body: "선택한 조건의 병목(핵심 병목)과 추천 프로그램(추천 프로그램)을 기준으로 적용 시나리오를 화면 안에서 요약합니다."
    },
    proposal: {
      title: "파일럿 제안 구성하기",
      body: "추천 프로그램과 예상 산출물, 전환 가설을 제안 요약으로 구성합니다. 실제 계약·전송은 하지 않습니다."
    }
  };
  $$("[data-conv]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      $$("[data-conv]").forEach(function (b) { b.classList.remove("is-active"); });
      btn.classList.add("is-active");
      var r = P.diag(readDiag());
      var m = convMap[btn.getAttribute("data-conv")];
      var body = m.body
        .replace("핵심 병목", r.coreBottleneck)
        .replace("추천 프로그램", r.program);
      convResult.innerHTML = "<h3>" + m.title + "</h3><dl>" +
        "<div><dt>조직</dt><dd>" + r.org + " · " + r.team + "</dd></div>" +
        "<div><dt>추천 프로그램</dt><dd>" + r.program + "</dd></div>" +
        "<div><dt>우선 적용 업무</dt><dd>" + r.priorityWork + "</dd></div>" +
        "</dl><p>" + body + "</p>";
      convResult.scrollIntoView({ behavior: reduced ? "auto" : "smooth", block: "nearest" });
    });
  });

  syncNav();
})();
