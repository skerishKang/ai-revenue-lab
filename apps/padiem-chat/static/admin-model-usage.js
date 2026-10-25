/* #5318 owner model usage console.
 *
 * Reads only the console's own endpoints, which in turn read the B14 call
 * ledger. The gate and every number come from the server: this file never
 * computes a usage figure from a browser-side guess, and a value the ledger
 * reports as absent stays labelled instead of being printed as a zero.
 */
(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const SESSION_PATH = "/api/admin/session";
  const CALLS_PATH = "/api/admin/model-usage/calls";
  const AGGREGATE_PATH = "/api/admin/model-usage/aggregate";
  const ABSENT = "—";
  const MISSING_USAGE = "미보고";
  const UNKNOWN_COST = "확인 불가";
  const TIER_UNDECLARED = "등급 미수집";
  // The same pair the B14 gateway itself classifies as a timeout
  // (app/pilot/gateway.py), so the label follows the record instead of a guess.
  const TIMEOUT_CODES = Object.freeze(["upstream_timeout", "gateway_timeout"]);
  const TIERS = Object.freeze(["FREE", "PLUS", "PRO", "MAX"]);
  const PRODUCTS = Object.freeze([
    ["chat", "Chat"], ["claw", "Claw"], ["b66", "B66"],
    ["engine", "Engine"], ["api", "API"], ["unknown", "미선언"],
  ]);
  const OUTCOMES = Object.freeze([["success", "성공"], ["error", "실패"], ["aborted", "중단"]]);
  const LIMITS = Object.freeze([25, 50, 100, 200]);
  const GROUP_TABS = Object.freeze([
    ["selected_model_id", "모델"],
    ["selected_provider", "공급사"],
    ["membership_tier", "등급"],
    ["product", "제품"],
    ["outcome", "결과"],
    ["error_code", "실패 사유"],
    ["cost_basis", "비용 근거"],
    ["token_source", "토큰 출처"],
  ]);

  const state = { limit: 50, offset: 0, groupBy: "selected_model_id", total: 0 };

  function node(tag, value, className) {
    const el = document.createElement(tag);
    if (value !== undefined && value !== null) el.textContent = String(value);
    if (className) el.className = className;
    return el;
  }

  function option(value, label) {
    const el = document.createElement("option");
    el.value = value;
    el.textContent = label;
    return el;
  }

  function fill(select, entries, includeAll) {
    if (includeAll) select.appendChild(option("", entries === OUTCOMES ? "결과 전체" : "전체"));
    for (const [value, label] of entries) select.appendChild(option(value, label));
  }

  function numberOr(value, label) {
    if (value === null || value === undefined) return label || ABSENT;
    const parsed = Number(value);
    if (!Number.isFinite(parsed)) return label || ABSENT;
    return parsed.toLocaleString("ko-KR", { maximumFractionDigits: 4 });
  }

  function text(row, key) {
    const value = row ? row[key] : null;
    return value === null || value === undefined || value === "" ? ABSENT : String(value);
  }

  async function getJSON(path) {
    const response = await fetch(path, { credentials: "same-origin", headers: { Accept: "application/json" } });
    let payload = null;
    try {
      payload = await response.json();
    } catch (error) {
      payload = null;
    }
    return { status: response.status, payload };
  }

  function params(overrides) {
    const query = new URLSearchParams();
    const put = (key, value) => {
      const trimmed = typeof value === "string" ? value.trim() : value;
      if (trimmed !== "" && trimmed !== null && trimmed !== undefined) query.set(key, String(trimmed));
    };
    put("since", filtersSince());
    put("until", filtersUntil());
    put("selected_model_id", $("modelInput").value);
    put("selected_provider", $("providerInput").value);
    put("membership_tier", $("tierSelect").value);
    put("product", $("productSelect").value);
    put("outcome", $("outcomeSelect").value);
    for (const [key, value] of Object.entries(overrides || {})) put(key, value);
    return query;
  }

  // A date is sent as a full UTC instant: the ledger compares ISO-8601 text.
  function filtersSince() {
    const value = $("sinceInput").value;
    return value ? value + "T00:00:00Z" : "";
  }

  function filtersUntil() {
    const value = $("untilInput").value;
    return value ? value + "T23:59:59Z" : "";
  }

  function setStatus(id, value) {
    const el = $(id);
    if (el) el.textContent = value;
  }

  function notice(message) {
    const box = $("accessNotice");
    box.hidden = !message;
    box.textContent = message || "";
  }

  function storageNote(storageState) {
    if (storageState === "not_configured") {
      return "이 배포에는 호출 이력 저장소가 연결되지 않았습니다. 0건이 아니라 미연결 상태입니다.";
    }
    if (storageState && storageState !== "bound") return "저장 상태: " + storageState;
    return "";
  }

  // Each aggregate row is one bucket of one dimension, so every total below is
  // summed inside a single grouping. Adding a second grouping's rows in would
  // count the same call twice, and reading a field the query never selected
  // would print an absent value as zero.
  function cards(outcomeRows, timeoutRows, costRows) {
    const wrap = $("summaryCards");
    wrap.replaceChildren();
    const rows = outcomeRows;
    const total = rows.reduce((sum, row) => sum + Number(row.calls || 0), 0);
    const succeeded = rows.reduce((sum, row) => sum + Number(row.succeeded || 0), 0);
    const failed = rows.reduce((sum, row) => sum + Number(row.failed || 0), 0);
    const tokens = rows.reduce((sum, row) => sum + Number(row.total_tokens || 0), 0);
    const withTokens = rows.reduce((sum, row) => sum + Number(row.calls_with_tokens || 0), 0);
    const withoutTokens = rows.reduce((sum, row) => sum + Number(row.calls_without_tokens || 0), 0);
    const usd = rows.reduce((sum, row) => sum + Number(row.estimated_usd || 0), 0);
    const krw = rows.reduce((sum, row) => sum + Number(row.estimated_krw || 0), 0);
    const costUnknown = costRows.reduce(
      (sum, row) => sum + (row.dimension === "unknown" ? Number(row.calls || 0) : 0), 0);
    const definitions = [
      ["총 호출", numberOr(total), "논리 요청 기준 — 폴백 3회도 1회"],
      ["성공", numberOr(succeeded), ""],
      ["실패", numberOr(failed), ""],
      ["타임아웃", numberOr(timeoutCount(timeoutRows)), TIMEOUT_CODES.join(" · ")],
      ["폴백 발생", numberOr(fallbackCount(rows)), ""],
      ["토큰 합계", numberOr(tokens), withTokens + "회 측정 · " + withoutTokens + "회 미보고"],
      ["추정 비용", usd || krw ? "$" + usd.toFixed(4) + " / ₩" + krw.toFixed(0) : ABSENT,
        costUnknown ? costUnknown + "회는 가격 미설정(확인 불가)" : "카탈로그 가격 스냅샷"],
    ];
    for (const [title, value, note] of definitions) {
      const card = node("div", null, "usage-card");
      card.appendChild(node("span", title, "usage-card-title"));
      card.appendChild(node("strong", value, "usage-card-value"));
      if (note) card.appendChild(node("span", note, "usage-card-note"));
      wrap.appendChild(card);
    }
    $("summaryNote").textContent =
      "미보고 토큰과 가격 미설정 항목은 0으로 합산하지 않습니다. "
      + withoutTokens + "회는 공급자가 사용량을 보고하지 않았고, "
      + costUnknown + "회는 가격 스냅샷이 없습니다.";
  }

  function timeoutCount(errorRows) {
    return errorRows.reduce(
      (sum, row) => sum + (TIMEOUT_CODES.includes(row.dimension) ? Number(row.calls || 0) : 0), 0);
  }

  function fallbackCount(rows) {
    return rows.reduce((sum, row) => sum + Number(row.fallbacks || 0), 0);
  }

  function renderGroup(rows, dimensionLabel) {
    const body = $("groupByBody");
    body.replaceChildren();
    $("dimensionHead").textContent = dimensionLabel;
    for (const row of rows) {
      const tr = document.createElement("tr");
      const parts = [
        row.dimension === null || row.dimension === "" ? ABSENT : String(row.dimension),
        numberOr(row.calls), numberOr(row.succeeded), numberOr(row.failed),
        numberOr(row.fallbacks),
        row.calls_with_tokens ? numberOr(row.total_tokens) : MISSING_USAGE,
        row.cost_basis === "unknown" || (row.estimated_usd === null && row.estimated_krw === null)
          ? UNKNOWN_COST
          : "$" + Number(row.estimated_usd || 0).toFixed(4) + " / ₩" + Number(row.estimated_krw || 0).toFixed(0),
      ];
      for (const value of parts) tr.appendChild(node("td", value));
      body.appendChild(tr);
    }
    if (!rows.length) body.appendChild(rowMessage(7, "집계될 행이 없습니다."));
  }

  function rowMessage(span, message) {
    const tr = document.createElement("tr");
    const td = node("td", message, "usage-empty");
    td.colSpan = span;
    tr.appendChild(td);
    return tr;
  }

  function renderTrend(rows) {
    const body = $("trendBody");
    body.replaceChildren();
    for (const row of rows) {
      const tr = document.createElement("tr");
      const parts = [
        row.dimension ? String(row.dimension) : "날짜 미상",
        numberOr(row.calls), numberOr(row.succeeded), numberOr(row.failed),
        row.calls_with_tokens ? numberOr(row.total_tokens) : MISSING_USAGE,
        row.cost_basis === "unknown" || (row.estimated_usd === null && row.estimated_krw === null)
          ? UNKNOWN_COST
          : "$" + Number(row.estimated_usd || 0).toFixed(4),
      ];
      for (const value of parts) tr.appendChild(node("td", value));
      body.appendChild(tr);
    }
    if (!rows.length) body.appendChild(rowMessage(5, "이 기간에 기록된 호출이 없습니다."));
  }

  function renderCalls(rows) {
    const body = $("callsBody");
    body.replaceChildren();
    for (const row of rows) {
      const tr = document.createElement("tr");
      const cost = row.cost_state === "catalog_estimate"
        ? "$" + Number(row.estimated_usd || 0).toFixed(4) + " / ₩" + Number(row.estimated_krw || 0).toFixed(0)
        : row.cost_state === "known_free" ? "무료(확인됨)" : UNKNOWN_COST;
      const usage = row.usage_state === "measured"
        ? numberOr(row.total_tokens)
        : MISSING_USAGE;
      const parts = [
        text(row, "started_at"),
        text(row, "product") + (row.identity_source === "caller_declared" ? " (호출자 선언)" : ""),
        text(row, "requested_model_id"),
        text(row, "actual_response_model") === ABSENT ? text(row, "selected_model_id") : text(row, "actual_response_model"),
        outcomeLabel(row),
        usage,
        cost,
        row.latency_source === "measured" ? numberOr(row.elapsed_ms) + " ms" : ABSENT,
      ];
      for (const value of parts) tr.appendChild(node("td", value));
      const action = document.createElement("td");
      const button = node("button", "상세", "btn");
      button.type = "button";
      button.addEventListener("click", () => openDetail(String(row.log_id || "")));
      action.appendChild(button);
      tr.appendChild(action);
      body.appendChild(tr);
    }
    if (!rows.length) body.appendChild(rowMessage(9, "이 조건에서 기록된 호출이 없습니다."));
  }

  function outcomeLabel(row) {
    const outcome = { success: "성공", error: "실패", aborted: "중단" }[row.outcome] || text(row, "outcome");
    if (row.outcome === "success") return outcome;
    const reason = row.error_code ? " · " + row.error_code : "";
    const fallback = Number(row.fallback_depth || 0) > 0 ? " · 폴백 " + row.fallback_depth : "";
    return outcome + reason + fallback;
  }

  async function openDetail(logId) {
    if (!logId) return;
    setStatus("detailStatus", "호출 중");
    $("detailPanel").replaceChildren(node("p", "불러오는 중…", "caption-note"));
    const { status, payload } = await getJSON("/api/admin/model-usage/calls/" + encodeURIComponent(logId));
    if (!payload || payload.ok !== true) {
      setStatus("detailStatus", "실패");
      $("detailPanel").replaceChildren(
        node("p", "상세를 읽을 수 없습니다 (HTTP " + status + " · "
          + ((payload && payload.error && payload.error.code) || "알 수 없음") + ")", "caption-note"));
      return;
    }
    setStatus("detailStatus", payload.call.log_id);
    $("detailPanel").replaceChildren(...detailNodes(payload.call));
  }

  function detailNodes(call) {
    const out = [];
    const head = node("div", null, "usage-detail-grid");
    for (const [label, value] of [
      ["요청 ID", text(call, "request_id")],
      ["최종 모델", text(call, "actual_response_model") === ABSENT ? text(call, "selected_model_id") : text(call, "actual_response_model")],
      ["공급사", text(call, "selected_provider")],
      ["프로토콜", text(call, "protocol")],
      ["경로 모드", text(call, "route_mode")],
      ["스트리밍", call.streaming ? "예" : "아니오"],
      ["최종 결과", outcomeLabel(call)],
      ["종료 사유", text(call, "finish_reason")],
      ["TTFT", call.ttft_ms === null || call.ttft_ms === undefined ? ABSENT : numberOr(call.ttft_ms) + " ms"],
      ["토큰", call.usage_state === "measured"
        ? "입력 " + numberOr(call.prompt_tokens) + " · 출력 " + numberOr(call.completion_tokens)
          + " ·추론 " + numberOr(call.reasoning_tokens) + " · 합계 " + numberOr(call.total_tokens)
        : MISSING_USAGE],
      ["비용", call.cost_state === "catalog_estimate"
        ? "$" + Number(call.estimated_usd || 0).toFixed(6) + " / ₩" + Number(call.estimated_krw || 0).toFixed(0) + " (추정)"
        : call.cost_state === "known_free" ? "무료(확인됨)" : UNKNOWN_COST],
      ["등급", call.membership_tier_declared ? text(call, "membership_tier") : TIER_UNDECLARED],
      ["정체성 출처", call.identity_source === "caller_declared" ? "호출자 선언"
        : call.identity_source === "b14_observed" ? "B14 관측" : "확인 불가"],
    ]) {
      const cell = node("div", null, "usage-detail-cell");
      cell.appendChild(node("span", label, "usage-detail-label"));
      cell.appendChild(node("strong", value, "usage-detail-value"));
      head.appendChild(cell);
    }
    out.push(head);
    out.push(node("h3", "물리적 시도 " + ((call.attempts || []).length) + "건", "usage-detail-heading"));
    const table = node("table", null, "usage-table");
    const caption = node("caption", "이 호출에서 실제로 시도된 각 후보", "visually-hidden");
    const thead = document.createElement("thead");
    const headRow = document.createElement("tr");
    for (const label of ["#", "공급사", "모델", "결과", "오류 코드", "토큰", "추정 비용", "지연"]) {
      headRow.appendChild(node("th", label));
    }
    thead.appendChild(headRow);
    const tbody = document.createElement("tbody");
    for (const attempt of call.attempts || []) {
      const tr = document.createElement("tr");
      for (const value of [
        numberOr(attempt.attempt_index),
        text(attempt, "provider"),
        text(attempt, "actual_response_model") === ABSENT ? text(attempt, "model_id") : text(attempt, "actual_response_model"),
        attempt.dispatched ? (attempt.outcome === "aborted" ? "중단" : attempt.outcome === "success" ? "성공" : "실패") : "미전송(스킵)",
        text(attempt, "error_code"),
        attempt.usage_state === "measured" ? numberOr(attempt.total_tokens) : MISSING_USAGE,
        attempt.cost_state === "catalog_estimate" ? "$" + Number(attempt.estimated_usd || 0).toFixed(6)
          : attempt.cost_state === "known_free" ? "무료" : UNKNOWN_COST,
        attempt.latency_source === "measured" ? numberOr(attempt.elapsed_ms) + " ms" : ABSENT,
      ]) tr.appendChild(node("td", value));
      tbody.appendChild(tr);
    }
    if (!(call.attempts || []).length) tbody.appendChild(rowMessage(8, "시도 기록이 없습니다."));
    table.append(caption, thead, tbody);
    out.push(table);
    out.push(node("p", "실패한 시도는 성공 기록에 덮어써지지 않습니다. 미전송(스킵)은 공급자에 발송되지 않은 후보이므로 지연·토큰·비용이 없습니다.",
      "caption-note"));
    return out;
  }

  async function loadGroup() {
    setStatus("groupByStatus", "호출 중");
    const { status, payload } = await getJSON(AGGREGATE_PATH + "?" + params({ group_by: state.groupBy }).toString());
    if (!payload || payload.ok !== true) {
      setStatus("groupByStatus", "읽을 수 없음");
      $("groupByBody").replaceChildren(rowMessage(7, "집계를 읽을 수 없습니다 (HTTP " + status + ")."));
      return;
    }
    const label = (GROUP_TABS.find(([key]) => key === state.groupBy) || ["", "구분"])[1];
    renderGroup(payload.rows || [], label);
    setStatus("groupByStatus", (payload.rows || []).length + "개 구분"
      + (payload.storage_state === "not_configured" ? " · 저장소 미연결" : ""));
  }

  async function loadTrend() {
    setStatus("trendStatus", "호출 중");
    const { status, payload } = await getJSON(AGGREGATE_PATH + "?" + params({ group_by: "day" }).toString());
    if (!payload || payload.ok !== true) {
      setStatus("trendStatus", "읽을 수 없음");
      $("trendBody").replaceChildren(rowMessage(5, "추세를 읽을 수 없습니다 (HTTP " + status + ")."));
      return;
    }
    renderTrend(payload.rows || []);
    setStatus("trendStatus", (payload.rows || []).length + "개 날짜");
  }

  async function loadSummary() {
    // One request per dimension, all with the same filters: the ledger exposes
    // one grouping per call, and a total is only ever summed within its own.
    const [outcome, errors, costs, page] = await Promise.all([
      getJSON(AGGREGATE_PATH + "?" + params({ group_by: "outcome" }).toString()),
      getJSON(AGGREGATE_PATH + "?" + params({ group_by: "error_code" }).toString()),
      getJSON(AGGREGATE_PATH + "?" + params({ group_by: "cost_basis" }).toString()),
      getJSON(CALLS_PATH + "?" + params({ limit: 1 }).toString()),
    ]);
    if (!outcome.payload || outcome.payload.ok !== true) {
      $("summaryCards").replaceChildren(node("p", "합계를 읽을 수 없습니다.", "caption-note"));
      setStatus("storageStatus", "합계 조회 실패");
      return;
    }
    cards(
      outcome.payload.rows || [],
      (errors.payload && errors.payload.rows) || [],
      (costs.payload && costs.payload.rows) || [],
    );
    $("summaryScope").textContent = (filtersSince() || filtersUntil())
      ? "선택한 기간" : "기록 전체 기간";
    $("evidenceNote").textContent = (page.payload && page.payload.evidence_note) || "";
    setStatus("storageStatus",
      storageNote(outcome.payload.storage_state || "") || "저장소 연결됨");
  }

  async function loadCalls() {
    setStatus("pageStatus", "호출 중");
    const { status, payload } = await getJSON(CALLS_PATH + "?" + params({
      limit: state.limit, offset: state.offset,
    }).toString());
    if (!payload || payload.ok !== true) {
      setStatus("pageStatus", "읽을 수 없음");
      $("callsBody").replaceChildren(rowMessage(9, "이력을 읽을 수 없습니다 (HTTP " + status + ")."));
      return;
    }
    state.total = Number(payload.total || 0);
    renderCalls(payload.calls || []);
    const note = storageNote(payload.storage_state);
    if (note) notice(note);
    $("pageStatus").textContent = (payload.calls || []).length + "건 표시 / 총 " + numberOr(payload.total) + "건";
    $("pageCaption").textContent = "페이지 시작 " + state.offset + " · 크기 " + state.limit;
    $("prevButton").disabled = state.offset <= 0;
    $("nextButton").disabled = state.offset + state.limit >= state.total;
  }

  async function loadAll() {
    state.offset = 0;
    await Promise.all([loadSummary(), loadTrend(), loadGroup(), loadCalls()]);
  }

  function renderTabs() {
    const wrap = $("groupByTabs");
    wrap.replaceChildren();
    for (const [key, label] of GROUP_TABS) {
      const tab = node("button", label, "btn usage-tab" + (key === state.groupBy ? " active" : ""));
      tab.type = "button";
      tab.addEventListener("click", () => {
        state.groupBy = key;
        renderTabs();
        void loadGroup();
      });
      wrap.appendChild(tab);
    }
  }

  function bindControls() {
    fill($("tierSelect"), TIERS.map((tier) => [tier, tier]), true);
    fill($("productSelect"), PRODUCTS, true);
    fill($("outcomeSelect"), OUTCOMES, true);
    for (const limit of LIMITS) $("limitSelect").appendChild(option(String(limit), limit + "건"));
    $("limitSelect").value = String(state.limit);
    $("applyButton").addEventListener("click", () => {
      state.limit = Number($("limitSelect").value);
      void loadAll();
    });
    $("prevButton").addEventListener("click", () => {
      state.offset = Math.max(0, state.offset - state.limit);
      void loadCalls();
    });
    $("nextButton").addEventListener("click", () => {
      state.offset += state.limit;
      void loadCalls();
    });
    renderTabs();
  }

  async function boot() {
    const { status, payload } = await getJSON(SESSION_PATH);
    const caps = payload && payload.capabilities;
    if (!payload || payload.authenticated !== true || !caps || caps.central_model_admin !== true) {
      $("gatePanel").hidden = false;
      setStatus("roleBadge", status === 401 ? "미인증" : "권한 없음");
      setStatus("storageStatus", "권한 확인 실패");
      return;
    }
    $("roleBadge").textContent = payload.role === "SUPER_ADMIN" ? "총괄 관리자" : "관리자";
    $("roleCaption").textContent = "실행 이력 조회";
    $("usageContent").hidden = false;
    bindControls();
    await loadAll();
  }

  document.addEventListener("DOMContentLoaded", () => { void boot(); });
})();
