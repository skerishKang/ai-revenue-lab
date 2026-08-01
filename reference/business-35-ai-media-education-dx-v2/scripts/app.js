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

  /* ---------- signature workflow motion (viewport-triggered, timer-safe) ---------- */
  var wfBoard = $("[data-wf-board]");
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
    // 다섯 정보를 최종 상태로 한 번에 표시 (reduced-motion fallback)
    mark('[data-wf-step="b2"]', "is-hot"); mark('[data-wf-step="b4"]', "is-hot");
    $$("[data-wf-transform] span", wfBoard).forEach(function (sp) { sp.classList.add("is-on"); });
    mark('[data-wf-step="a2"]', "is-ai"); mark('[data-wf-step="a3"]', "is-ai");
    mark('[data-wf-step="a4"]', "is-review"); mark('[data-wf-step="a5"]', "is-review");
    mark('[data-wf-step="a6"]', "is-done"); mark('[data-wf-step="a7"]', "is-done");
    var seal = $("[data-wf-seal]", wfBoard);
    if (seal) seal.textContent = "HUMAN-APPROVED AI MEDIA OPERATING SYSTEM";
  }
  function playWf() {
    resetWf();
    clearWfTimers();
    var gen = ++wfGen;
    if (reduced) { finalWf(); return; }
    var at = function (ms, fn) {
      wfTimers.push(setTimeout(function () { if (gen !== wfGen) return; fn(); }, ms));
    };
    // 1. 병목 표시
    at(200, function () { mark('[data-wf-step="b2"]', "is-hot"); mark('[data-wf-step="b4"]', "is-hot"); });
    // 2. 교육 개입
    at(900, function () { var sp = $$("[data-wf-transform] span", wfBoard)[0]; if (sp) sp.classList.add("is-on"); });
    // 3. AI-assisted 단계 연결
    at(1700, function () {
      mark('[data-wf-step="a2"]', "is-ai"); mark('[data-wf-step="a3"]', "is-ai");
      var sp = $$("[data-wf-transform] span", wfBoard)[2]; if (sp) sp.classList.add("is-on");
    });
    // 4. 사람 검토 gate
    at(2500, function () {
      mark('[data-wf-step="a4"]', "is-review"); mark('[data-wf-step="a5"]', "is-review");
      var sp = $$("[data-wf-transform] span", wfBoard)[1]; if (sp) sp.classList.add("is-on");
    });
    // 5. 승인된 운영 체계
    at(3300, finalWf);
  }

  // Replay button: deterministic replay anytime (버튼은 재생 중 잠시 disabled + 상태 설명)
  var replayLabel = "변환 다시 보기";
  wfRunBtn.addEventListener("click", function () {
    wfRunBtn.disabled = true;
    wfRunBtn.setAttribute("aria-describedby", "wf-status");
    var status = $("#wf-status") || document.createElement("span");
    if (!status.id) { status.id = "wf-status"; status.className = "wf-status"; wfBoard.parentNode.insertBefore(status, wfBoard); }
    status.textContent = "업무전환 재생 중…";
    playWf();
    var g = wfGen;
    var enable = function () { if (g === wfGen) { wfRunBtn.disabled = false; if (status) status.textContent = "업무전환 최종 상태"; } };
    setTimeout(enable, reduced ? 50 : 3400);
  });

  // viewport trigger: workflow가 35% 이상 진입 시 첫 방문 한 번 자동 실행
  var wfSection = $("#workflow");
  function triggerOnVisible() {
    if (wfPlayed) return;
    wfPlayed = true;
    playWf();
  }
  if ("IntersectionObserver" in window && !reduced) {
    // threshold 0.35 진입 기준 + 섹션이 뷰포트보다 클 경우(모바일/태블릿) 첫 가시 진입 시 트리거
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        var ratio = en.intersectionRatio || 0;
        var tall = en.boundingClientRect.height >= window.innerHeight;
        if (en.isIntersecting && (ratio >= 0.35 || tall) && !wfPlayed) { triggerOnVisible(); io.disconnect(); }
      });
    }, { threshold: [0, 0.1, 0.35] });
    io.observe(wfSection);
  } else if (reduced) {
    triggerOnVisible(); // reduced motion: 즉시 최종 정보
  } else {
    // IO 미지원 fallback: 섹션이 보이는 시점에 안전하게 최종 정보
    var onScroll = function () {
      var r = wfSection.getBoundingClientRect();
      if (r.top < window.innerHeight * 0.65 && !wfPlayed) { triggerOnVisible(); window.removeEventListener("scroll", onScroll); }
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
  }
  // #workflow deep link 진입 → 표시 직후 실행
  if (location.hash === "#workflow") triggerOnVisible();
  window.addEventListener("hashchange", function () { if (location.hash === "#workflow") triggerOnVisible(); });

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
