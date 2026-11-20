/* #8035 ③ (#7718 흡수) — 운영센터 '점수 입력'·'사용 일지' 탭.
   새 기능은 자기 모듈에 둔다(#7216). 이 모듈은 관리자 게이트(#adminContent)가
   열린 뒤에만 /api/admin/round-scores 를 부른다 — 게스트·일반 회원에게는
   호출이 0건이다. 값은 textContent로만 넣고, 점수 흐름은 표로 먼저 보여 준다.
   화면과 운영 도구는 같은 서버 함수를 쓴다(#8035 원칙). */
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const SOURCES = Object.freeze([["ai", "AI 고객"], ["human", "실제 고객"]]);
  const SOURCE_LABELS = Object.freeze({ ai: "AI 고객", human: "실제 고객" });
  const state = { loaded: false, busy: false, editing: "" };

  function node(tag, value, className) {
    const el = document.createElement(tag);
    if (value !== undefined && value !== null) el.textContent = String(value);
    if (className) el.className = className;
    return el;
  }

  function setStatus(id, message) {
    const el = $(id);
    if (!el) return;
    el.textContent = message || "";
    el.hidden = !message;
  }

  async function call(url, options) {
    const response = await fetch(url, {
      credentials: "same-origin", cache: "no-store",
      headers: { Accept: "application/json", ...(options?.headers || {}) },
      ...options,
    });
    const body = await response.json().catch(() => null);
    return { status: response.status, body };
  }

  function send(url, method, payload) {
    return call(url, {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  }

  /* ---- 표: 회차 점수 ---------------------------------------------------- */

  function trendText(entries) {
    /* 점수 흐름은 날짜 오름차순 숫자와 화살표로만(단순하게). */
    const parts = [];
    let previous = null;
    for (const entry of entries) {
      if (previous !== null) {
        parts.push(entry.score > previous ? "↑" : entry.score < previous ? "↓" : "→");
      }
      parts.push(String(entry.score));
      previous = entry.score;
    }
    return parts.join(" ");
  }

  function scoreRow(row) {
    const li = node("li", null, "ops-row ops-score-row");
    li.dataset.scoreId = row.id;
    const head = node("div", null, "ops-score-head");
    head.append(
      node("span", row.persona_name, "ops-score-name"),
      node("span", row.round_no + "회차", "ops-score-round"),
      node("span", row.round_on, "ops-score-day"),
      node("span", SOURCE_LABELS[row.source] || row.source, "ops-score-source")
    );
    li.append(head);
    const scores = node("div", null, "ops-score-values");
    scores.append(
      node("span", "다시 올 " + row.return_score, "ops-score-value"),
      node("span", "예쁜가 " + row.pretty_score, "ops-score-value")
    );
    li.append(scores);
    if (row.memo) li.append(node("p", row.memo, "ops-score-memo"));
    const bar = node("div", null, "ops-score-bar");
    const edit = node("button", "고치기", "ops-reload");
    edit.type = "button";
    edit.addEventListener("click", () => startEdit(row));
    const hide = node("button", "지우기", "ops-reload");
    hide.type = "button";
    hide.addEventListener("click", () => { void hideScore(row.id); });
    bar.append(edit, hide);
    li.append(bar);
    return li;
  }

  function journalRows(journal) {
    const tbody = $("opsJournalBody");
    tbody.replaceChildren();
    const people = journal?.personas || [];
    for (const person of people) {
      const tr = document.createElement("tr");
      tr.append(
        node("td", person.persona, "ops-audit-cell"),
        node("td", SOURCE_LABELS[person.source] || person.source, "ops-audit-cell"),
        node("td", person.rounds, "ops-audit-cell"),
        node("td", person.latest_score ?? "-", "ops-audit-cell"),
        node("td", trendText(person.entries || []), "ops-audit-cell ops-score-trend"),
        node("td", person.latest_on || "-", "ops-audit-cell")
      );
      tbody.append(tr);
    }
    if (!people.length) {
      const tr = document.createElement("tr");
      const td = node("td", "아직 입력한 회차 점수가 없습니다.", "ops-audit-cell");
      td.colSpan = 6;
      tr.append(td);
      tbody.append(tr);
    }
  }

  function journalMetrics(journal) {
    const box = $("opsJournalMetrics");
    box.replaceChildren();
    const pairs = [
      ["회차 수", journal?.rounds ?? 0],
      ["평균 다시 올 점수", journal?.return_avg ?? "-"],
      ["평균 예쁜가", journal?.pretty_avg ?? "-"],
    ];
    for (const [label, value] of pairs) {
      const item = node("div", null, "ops-metric");
      item.append(node("span", label, "ops-metric-label"),
                  node("strong", value, "ops-metric-value"));
      box.append(item);
    }
  }

  /* ---- 입력·수정 -------------------------------------------------------- */

  function formValue(id) {
    const el = $(id);
    return el ? el.value : "";
  }

  function readForm() {
    return {
      persona_name: formValue("opsScoreName").trim(),
      round_no: Number(formValue("opsScoreRound")),
      round_on: formValue("opsScoreDay"),
      source: formValue("opsScoreSource"),
      return_score: Number(formValue("opsScoreReturn")),
      pretty_score: Number(formValue("opsScorePretty")),
      memo: formValue("opsScoreMemo"),
    };
  }

  function fillForm(row) {
    $("opsScoreName").value = row ? row.persona_name : "";
    $("opsScoreRound").value = row ? String(row.round_no) : "1";
    $("opsScoreDay").value = row ? row.round_on : new Date().toISOString().slice(0, 10);
    $("opsScoreSource").value = row ? row.source : "ai";
    $("opsScoreReturn").value = row ? String(row.return_score) : "3";
    $("opsScorePretty").value = row ? String(row.pretty_score) : "3";
    $("opsScoreMemo").value = row ? row.memo : "";
  }

  function startEdit(row) {
    state.editing = row.id;
    fillForm(row);
    $("opsScoreSubmit").textContent = "고친 내용 저장";
    $("opsScoreCancel").hidden = false;
    setStatus("opsScoreStatus", row.persona_name + " " + row.round_no + "회차를 고치는 중입니다.");
  }

  function resetForm() {
    state.editing = "";
    fillForm(null);
    $("opsScoreSubmit").textContent = "점수 저장";
    $("opsScoreCancel").hidden = true;
  }

  async function submitForm() {
    if (state.busy) return;
    state.busy = true;
    setStatus("opsScoreStatus", "");
    const payload = readForm();
    try {
      const editing = state.editing;
      const { status: code, body } = editing
        ? await send("/api/admin/round-scores/" + editing, "PATCH", payload)
        : await send("/api/admin/round-scores", "POST", payload);
      if (code !== 200 || body?.ok !== true) {
        setStatus("opsScoreStatus", "저장하지 못했습니다(" +
          (body?.error?.code || code) + ").");
        return;
      }
      resetForm();
      setStatus("opsScoreStatus", editing ? "고쳤습니다." : "저장했습니다.");
      await load();
    } catch (_) {
      setStatus("opsScoreStatus", "저장하는 중 연결이 끊겼습니다.");
    } finally {
      state.busy = false;
    }
  }

  async function hideScore(scoreId) {
    if (state.busy) return;
    state.busy = true;
    try {
      const { status: code, body } = await call(
        "/api/admin/round-scores/" + scoreId, { method: "DELETE" });
      if (code !== 200 || body?.ok !== true) {
        setStatus("opsScoreStatus", "지우지 못했습니다(" +
          (body?.error?.code || code) + ").");
        return;
      }
      if (state.editing === scoreId) resetForm();
      setStatus("opsScoreStatus", "숨겼습니다. 감사 기록에 남습니다.");
      await load();
    } catch (_) {
      setStatus("opsScoreStatus", "지우는 중 연결이 끊겼습니다.");
    } finally {
      state.busy = false;
    }
  }

  /* ---- 읽기 ------------------------------------------------------------- */

  async function load() {
    setStatus("opsScoresStatus", "");
    const days = Number(formValue("opsJournalDays")) || 30;
    try {
      const { status: code, body } = await call(
        "/api/admin/round-scores?days=" + days);
      const list = $("opsScoresList");
      if (code !== 200 || body?.ok !== true) {
        list.replaceChildren();
        journalRows(null);
        journalMetrics(null);
        setStatus("opsScoresStatus", "점수를 불러오지 못했습니다(" +
          (body?.error?.code || code) + ").");
        return;
      }
      list.replaceChildren();
      for (const row of body.scores || []) list.append(scoreRow(row));
      if (!(body.scores || []).length) {
        list.append(node("li", "아직 입력한 회차 점수가 없습니다.", "ops-score-empty"));
      }
      journalRows(body.journal);
      journalMetrics(body.journal);
      state.loaded = true;
    } catch (_) {
      setStatus("opsScoresStatus", "점수를 불러오는 중 연결이 끊겼습니다.");
    }
  }

  function wireSources() {
    const select = $("opsScoreSource");
    select.replaceChildren();
    for (const [value, label] of SOURCES) {
      const option = node("option", label);
      option.value = value;
      select.append(option);
    }
  }

  function wire() {
    wireSources();
    resetForm();
    $("opsScoreSubmit").addEventListener("click", () => { void submitForm(); });
    $("opsScoreCancel").addEventListener("click", () => {
      resetForm();
      setStatus("opsScoreStatus", "");
    });
    $("opsScoresReload").addEventListener("click", () => { void load(); });
    $("opsJournalReload").addEventListener("click", () => { void load(); });
    $("opsJournalDays").addEventListener("change", () => { void load(); });
  }

  /* 관리자 게이트가 열린 뒤에만 배선·읽기한다(게스트 호출 0건). */
  const api = Object.freeze({
    activate() {
      if (!state.wired) {
        state.wired = true;
        wire();
      }
      if (!state.loaded) void load();
    },
    reload() { return load(); },
  });
  window.PadiemOpsScores = api;
})();