/* app.js — 파디엠 AI 미디어 업무전환 v2 interactions
   deterministic · deep-linkable · keyboard · reduced-motion safe */
(function () {
  "use strict";
  var P = window.PADIEM;
  var reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function $(s, r) { return (r || document).querySelector(s); }
  function $$(s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); }

  /* ---------- deep-link + scroll highlight ---------- */
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
      a.classList.toggle("is-active", a.getAttribute("href") === "#" + cur);
    });
  }
  window.addEventListener("scroll", syncNav, { passive: true });
  window.addEventListener("hashchange", syncNav);

  /* ---------- interactive diagnostic ---------- */
  var form = $("#diag-form");
  var result = $("#diag-result");
  function readDiag() {
    var v = {};
    $$("[data-diag]", form).forEach(function (s) { v[s.name] = s.value; });
    return v;
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
      "<p class='price-note'>가격 가설 · 시장 검증 전 · 실제 제출·저장 없음</p>";
  }
  form.addEventListener("change", renderDiag);
  $$("[data-diag-run]").forEach(function (b) {
    b.addEventListener("click", function () {
      renderDiag();
      result.scrollIntoView({ behavior: reduced ? "auto" : "smooth", block: "nearest" });
    });
  });

  /* ---------- signature workflow motion ---------- */
  var wfBoard = $("[data-wf-board]");
  var wfRun = $("[data-wf-run]");
  var wfTimer = null;
  function resetWf() {
    $$("[data-wf-step]", wfBoard).forEach(function (li) {
      li.className = "";
    });
    var seal = $("[data-wf-seal]", wfBoard);
    if (seal) seal.textContent = "HUMAN-APPROVED OS";
  }
  function runWf() {
    resetWf();
    if (wfTimer) clearTimeout(wfTimer);
    var timeline = [];
    var at = function (ms, fn) { timeline.push({ ms: ms, fn: fn }); };
    var mark = function (sel, cls) { var el = $(sel, wfBoard); if (el) el.classList.add(cls); };
    // BEFORE: show bottleneck
    at(200, function () { mark('[data-wf-step="b2"]', "is-hot"); mark('[data-wf-step="b4"]', "is-hot"); });
    at(700, function () { $$("[data-wf-transform] span", wfBoard).forEach(function (s) { s.style.opacity = 1; }); });
    // AFTER: AI-assisted steps, then human review gates, then done + seal
    at(1300, function () { mark('[data-wf-step="a2"]', "is-ai"); mark('[data-wf-step="a3"]', "is-ai"); });
    at(1900, function () { mark('[data-wf-step="a4"]', "is-review"); mark('[data-wf-step="a5"]', "is-review"); });
    at(2500, function () { mark('[data-wf-step="a6"]', "is-done"); mark('[data-wf-step="a7"]', "is-done"); });
    at(3100, function () {
      $$('[data-wf-step="a1"], [data-wf-step="a2"], [data-wf-step="a3"], [data-wf-step="a4"], [data-wf-step="a5"], [data-wf-step="a6"], [data-wf-step="a7"]', wfBoard).forEach(function (li) { li.classList.add("is-done"); });
      var seal = $("[data-wf-seal]", wfBoard);
      if (seal) seal.textContent = "HUMAN-APPROVED AI MEDIA OPERATING SYSTEM";
    });
    if (reduced) {
      // reduced motion: jump straight to the final state (same information)
      timeline.forEach(function (t) { t.fn(); });
    } else {
      timeline.forEach(function (t) { wfTimer = setTimeout(t.fn, t.ms); });
    }
  }
  wfRun.addEventListener("click", runWf);
  // run once on load (and on reduced motion, jump straight to final)
  runWf();

  /* ---------- deliverable gallery ---------- */
  var delDetail = $("#del-detail");
  function renderDel(key) {
    var d = P.deliverables[key];
    delDetail.innerHTML = "<h3>" + d.title + "</h3><p>" + d.body + "</p>";
  }
  $$("[data-del]").forEach(function (card) {
    card.addEventListener("click", function () {
      $$("[data-del]").forEach(function (c) { c.classList.remove("is-open"); });
      card.classList.add("is-open");
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
