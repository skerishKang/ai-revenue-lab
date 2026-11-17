(() => {
  "use strict";
  // #7718 3단계 — 운영센터 '사용 일지' 탭. 실제 데이터는 인자로만 받고,
  // 기본 렌더는 빈 상태다. 서버 호출·운영 계정·실제 DB·시험 데이터를 쓰지 않는다.
  const copy = (key, fallback) => window.__padiemLocale?.text("usage-" + key) || fallback;
  const EMPTY = "사용 기록이 아직 없습니다. AI 명예회원이 첫 질문을 보내면 여기에 표시됩니다.";

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function paintMetrics(host, metrics) {
    if (!Array.isArray(metrics) || !metrics.length) {
      host.replaceChildren(element("div", "usage-metric", "—"));
      return;
    }
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

  function render(rows = [], metrics = []) {
    const panel = document.getElementById("feedbackUsagePanel");
    if (!panel) return;
    const metricHost = panel.querySelector(".usage-metrics");
    const list = panel.querySelector(".usage-list");
    const empty = panel.querySelector(".usage-empty");
    if (!metricHost || !list || !empty) return;
    paintMetrics(metricHost, metrics);
    empty.textContent = copy("empty", EMPTY);
    const safeRows = Array.isArray(rows) ? rows : [];
    list.replaceChildren(...safeRows.map(paintRow));
    empty.hidden = safeRows.length > 0;
    list.hidden = !empty.hidden;
  }

  window.PadiemUsageLog = { render };
  const tab = document.getElementById("feedbackUsageTab");
  if (tab) tab.addEventListener("click", () => render());
})();
