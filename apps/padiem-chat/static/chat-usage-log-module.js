(() => {
  "use strict";
  // #7718 3단계 — 운영센터 '사용 일지' 탭. 실제 기록이 아직 없어 시험용
  // 가짜 데이터로 화면을 잠그고, 데이터가 없으면 빈 상태 문구를 보여 준다.
  // 관리자만 여는 탭이며 서버 호출·운영 계정·실제 DB를 쓰지 않는다.
  const copy = (key, fallback) => window.__padiemLocale?.text("usage-" + key) || fallback;
  const EMPTY = "사용 기록이 아직 없습니다. AI 명예회원이 첫 질문을 보내면 여기에 표시됩니다.";
  const FIXTURE = {
    metrics: [
      { key: "active", label: "활동 명예회원", value: 3 },
      { key: "left", label: "떠난 명예회원", value: 1 },
      { key: "new", label: "새 의견", value: 7 },
      { key: "resolved", label: "고침", value: 5 },
      { key: "return", label: "평균 다시 올 점수", value: "3.4" },
    ],
    rows: [
      { persona: "AI 정호", grade: "Plus", entries: [
        { round: 1, at: "2026.11.10", summary: "견적서 초안", score: 2 },
        { round: 2, at: "2026.11.12", summary: "회의정리", score: 3 },
        { round: 3, at: "2026.11.15", summary: "축사 다듬기", score: 4 },
      ] },
      { persona: "AI 민지", grade: "Free", entries: [
        { round: 1, at: "2026.11.11", summary: "PDF→Markdown", score: 3 },
        { round: 2, at: "2026.11.14", summary: "새 소식 확인", score: 4 },
      ] },
      { persona: "AI 수현", grade: "Pro", entries: [
        { round: 1, at: "2026.11.09", summary: "SNS 홍보", score: 4 },
        { round: 2, at: "2026.11.13", summary: "견적서 초안", score: 3 },
      ] },
    ],
  };

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function paintMetrics(host, metrics) {
    host.replaceChildren(...metrics.map((metric) => {
      const cell = element("div", "usage-metric");
      cell.append(element("span", "usage-metric-value", String(metric.value)),
                  element("span", "usage-metric-label", copy(metric.key, metric.label)));
      return cell;
    }));
  }

  function paintRow(persona) {
    const card = element("li", "usage-persona");
    const head = element("div", "usage-persona-head");
    head.append(element("strong", "usage-persona-name", persona.persona),
                element("span", "usage-persona-grade", persona.grade));
    card.append(head);
    const list = element("ol", "usage-rounds");
    let previous = null;
    for (const entry of persona.entries) {
      const row = element("li", "usage-round");
      const trend = previous === null ? "" : entry.score > previous ? " ↑" : entry.score < previous ? " ↓" : " →";
      row.append(element("span", "usage-round-no", String(entry.round).padStart(2, "0")),
                 element("span", "usage-round-at", entry.at),
                 element("span", "usage-round-summary", entry.summary),
                 element("span", "usage-round-score", "예쁜가 " + entry.score + trend));
      previous = entry.score;
      list.append(row);
    }
    card.append(list);
    return card;
  }

  function render(rows = FIXTURE.rows, metrics = FIXTURE.metrics) {
    const panel = document.getElementById("feedbackUsagePanel");
    if (!panel) return;
    const metricHost = panel.querySelector(".usage-metrics");
    const list = panel.querySelector(".usage-list");
    const empty = panel.querySelector(".usage-empty");
    if (!metricHost || !list || !empty) return;
    paintMetrics(metricHost, metrics || []);
    empty.textContent = copy("empty", EMPTY);
    list.replaceChildren(...(rows || []).map(paintRow));
    empty.hidden = Boolean(rows && rows.length);
    list.hidden = !empty.hidden;
  }

  window.PadiemUsageLog = { render, FIXTURE, EMPTY };
  const tab = document.getElementById("feedbackUsageTab");
  if (tab) tab.addEventListener("click", () => render());
})();
