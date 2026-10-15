(() => {
  "use strict";
  const API = "/api/padiem/b66/admin";
  const el = (id) => document.getElementById(id);
  const access = el("access");
  const content = el("candidateContent");
  const rows = el("candidateRows");
  const statusLine = el("candidateStatus");
  const detail = el("candidateDetail");
  const filter = el("candidateStatusFilter");

  async function req(path) {
    const r = await fetch(API + path, {
      credentials: "same-origin",
      cache: "no-store",
      headers: { Accept: "application/json" }
    });
    const payload = await r.json().catch(() => ({}));
    if (!r.ok || payload.ok !== true) {
      throw new Error(payload?.error?.code || "request_failed");
    }
    return payload;
  }

  function safeText(value) {
    return String(value == null ? "" : value);
  }

  function addTerm(container, term, value) {
    const dt = document.createElement("dt");
    dt.textContent = term;
    const dd = document.createElement("dd");
    dd.textContent = safeText(value);
    container.append(dt, dd);
    return dd;
  }

  function renderDetail(candidate) {
    detail.replaceChildren();
    const card = document.createElement("section");
    card.className = "panel";
    const heading = document.createElement("h2");
    heading.textContent = "선택한 승인 요청";
    card.append(heading);
    const dl = document.createElement("dl");
    addTerm(dl, "승인 요청 ID", candidate.candidate_id);
    addTerm(dl, "서버 사용자 ID", candidate.user_id);
    addTerm(dl, "견적서 이름", candidate.skill_name);
    addTerm(dl, "상태", candidate.status);
    addTerm(dl, "제출 시각", candidate.created_at);
    addTerm(dl, "수정 시각", candidate.updated_at);
    addTerm(dl, "결정 시각", candidate.decided_at);
    card.append(dl);
    const note = document.createElement("p");
    note.textContent = "승인/거부 실행 버튼은 신뢰 서버 grant 가 검증될 때까지 표시하지 않습니다.";
    card.append(note);
    detail.append(card);
  }

  async function loadList() {
    const value = filter.value || "pending";
    const currentLimit = 20;
    statusLine.textContent = "승인 요청 목록을 불러오는 중입니다.";
    rows.replaceChildren();
    try {
      const data = await req("/saved-skill-candidates?status=" + encodeURIComponent(value) + "&limit=" + currentLimit);
      const candidates = Array.isArray(data.candidates) ? data.candidates : [];
      for (const item of candidates) {
        const tr = document.createElement("tr");
        tr.append(detailCellSafe(item, "candidate_id"));
        tr.append(detailCellSafe(item, "user_id"));
        tr.append(detailCellSafe(item, "skill_name"));
        tr.append(detailCellSafe(item, "status"));
        tr.append(detailCellSafe(item, "created_at"));
        tr.append(detailCellSafe(item, "updated_at"));
        tr.append(detailCellSafe(item, "decided_at"));
        const action = document.createElement("td");
        const button = document.createElement("button");
        button.type = "button";
        button.className = "secondary";
        button.textContent = "상세";
        button.addEventListener("click", async () => {
          button.disabled = true;
          statusLine.textContent = "상세를 불러오는 중입니다.";
          try {
            const result = await req("/saved-skill-candidates/" + encodeURIComponent(item.candidate_id));
            renderDetail(result.candidate || {});
            statusLine.textContent = "선택한 승인 요청 " + safeText(item.candidate_id) + " 상세를 표시합니다.";
          } catch (error) {
            statusLine.textContent = "상세 조회 실패: " + safeText(error.message);
          } finally {
            button.disabled = false;
          }
        });
        action.append(button);
        tr.append(action);
        rows.append(tr);
      }
      if (!candidates.length) {
        const empty = document.createElement("tr");
        const cell = document.createElement("td");
        cell.colSpan = 8;
        cell.textContent = "해당 상태의 승인 요청이 없습니다.";
        empty.append(cell);
        rows.append(empty);
      }
      statusLine.textContent = "승인 요청 " + candidates.length + "건 표시 중입니다.";
    } catch (error) {
      statusLine.textContent = "조회 실패: " + safeText(error.message);
      const empty = document.createElement("tr");
      const cell = document.createElement("td");
      cell.colSpan = 8;
      cell.textContent = "승인 요청을 확인할 수 없습니다.";
      empty.append(cell);
      rows.append(empty);
    }
  }

  function detailCellSafe(item, field) {
    const td = document.createElement("td");
    if (field === "candidate_id") td.className = "note";
    td.textContent = safeText(item[field]);
    td.style.overflowWrap = "anywhere";
    return td;
  }

  async function initialize() {
    try {
      const response = await req("/me");
      if (response.admin !== true) throw new Error("admin_forbidden");
      access.hidden = true;
      content.hidden = false;
      await loadList();
    } catch (error) {
      access.textContent = error.message === "admin_forbidden" ? "관리자 권한이 없습니다." : "관리자 계정으로 로그인해 주세요.";
      content.hidden = true;
    }
  }

  filter.addEventListener("change", loadList);
  el("candidateReload").addEventListener("click", loadList);
  initialize();
})();
