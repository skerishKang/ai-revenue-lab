/*  app.js  —  guided tutorial controller (방림명지로드힐 운영 데모)
 *
 *  Renders the 7 chapters and 7 scenarios for the 방림명지로드힐 real-complex
 *  demo. 데모용 예시 값은 데모 예시로 표시합니다. Status vocabulary uses only
 *  non-judgemental phrases: 확인 필요 / 자료 부족 / 절차 보완 필요 / 공개 보류 /
 *  전문 검토 필요 / 기록 유지.
 */

(function () {
  "use strict";

  var data = window.ARL_TUTORIAL;

  var STATUS_CLASS = {
    "확인 필요": "st-confirm",
    "자료 부족": "st-missing",
    "절차 보완 필요": "st-review",
    "공개 보류": "st-hold",
    "전문 검토 필요": "st-review",
    "기록 유지": "st-keep",
    "정상 회의": "st-normal"
  };

  var currentChapter = data.chapters[0].id;
  var currentScenario = "normal";

  var tabsEl = document.getElementById("chapter-tabs");
  var scenarioEl = document.getElementById("scenario");
  var chapterTitle = document.getElementById("chapter-title");
  var chapterFolio = document.getElementById("chapter-folio");
  var bodyEl = document.getElementById("chapter-body");
  var statusEl = document.getElementById("scenario-status");

  function escapeHtml(v) {
    return String(v == null ? "" : v)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function statusChip(text) {
    var cls = STATUS_CLASS[text] || "st-keep";
    return '<span class="status ' + cls + '">' + escapeHtml(text) + "</span>";
  }

  function renderTabs() {
    var html = "";
    data.chapters.forEach(function (c) {
      var selected = c.id === currentChapter ? "true" : "false";
      html += '<button type="button" role="tab" aria-selected="' + selected + '" data-chapter="' + c.id + '">' +
        "<i>" + c.no + "</i>" + escapeHtml(c.title) + "</button>";
    });
    tabsEl.innerHTML = html;
  }

  function renderScenarioSelect() {
    var html = "";
    data.scenarios.forEach(function (s) {
      var selected = s.id === currentScenario ? " selected" : "";
      html += '<option value="' + s.id + '"' + selected + ">" + escapeHtml(s.title) + "</option>";
    });
    scenarioEl.innerHTML = html;
  }

  function renderChapter() {
    var chapter = null;
    data.chapters.forEach(function (c) { if (c.id === currentChapter) chapter = c; });
    if (!chapter) return;
    chapterTitle.textContent = chapter.no + ". " + chapter.title;
    chapterFolio.textContent = "챕터 " + chapter.no + " / 7 · 방림명지로드힐 운영 데모";
    var steps = chapter.steps.map(function (s, i) {
      return '<div class="step-card"><span class="no">STEP ' + (i + 1) + "</span>" +
        "<h3>" + escapeHtml(s.title) + "</h3><p>" + escapeHtml(s.text) + "</p></div>";
    }).join("");
    var scenario = null;
    data.scenarios.forEach(function (s) { if (s.id === currentScenario) scenario = s; });
    bodyEl.innerHTML =
      '<div class="ledger-strip">' +
      data.scenarios.map(function (s) {
        return "<span>" + escapeHtml(s.title) + "</span>";
      }).join("") +
      "</div>" +
      '<div class="steps">' + steps + "</div>" +
      '<div class="guide-note"><h4>가이드 노트 <span class="demo-tag">데모 예시</span></h4><p>' + escapeHtml(chapter.guide) + "</p></div>" +
      (scenario
        ? '<div class="scenario-card"><h4>시나리오 · ' + escapeHtml(scenario.title) + "</h4>" +
          "<p>" + escapeHtml(scenario.text) + "</p>" +
          (scenario.demo ? '<span class="demo-tag">데모 예시</span> ' : "") +
          statusChip(scenario.status) + "</div>"
        : "");
    statusEl.hidden = !scenario;
    if (scenario) {
      statusEl.textContent = scenario.status;
      statusEl.className = "status " + (STATUS_CLASS[scenario.status] || "st-keep");
    }
  }

  function render() {
    renderTabs();
    renderScenarioSelect();
    renderChapter();
  }

  tabsEl.addEventListener("click", function (ev) {
    var btn = ev.target.closest("button[data-chapter]");
    if (!btn) return;
    currentChapter = btn.dataset.chapter;
    render();
  });

  scenarioEl.addEventListener("change", function () {
    currentScenario = scenarioEl.value;
    render();
  });

  render();
})();
