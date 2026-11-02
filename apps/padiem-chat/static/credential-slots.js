/* Read-only B14 credential-slot board. No key value is ever rendered,
   requested or stored by this page: it displays only what the owner API
   returns, and the API itself emits metadata only. */
(() => {
  "use strict";

  const API = "/api/admin/credential-slots";
  const $ = (id) => document.getElementById(id);

  const STATE_LABELS = {
    configured: ["설정됨", "good"],
    empty: ["값 없음", "idle"],
    placeholder: ["예시값 거부", "warn"],
    unresolved: ["확인 불가", "bad"],
    rejected_mode: ["권한 거부", "bad"],
  };
  const MODIFIED_SOURCES = {
    secret_file: "시크릿 파일",
    env_file: "환경 파일",
    none: "",
  };
  const LEDGER_LABELS = {
    bound: "호출 이력 연결됨",
    not_configured: "호출 이력 미연결",
    unavailable: "호출 이력 읽기 실패",
  };

  function node(tag, text, className) {
    const el = document.createElement(tag);
    if (text !== undefined && text !== null) el.textContent = String(text);
    if (className) el.className = className;
    return el;
  }

  function notice(message) {
    const box = $("accessNotice");
    box.hidden = !message;
    box.textContent = message || "";
  }

  function stamp(value) {
    if (typeof value !== "string" || !value) return "—";
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return "—";
    const pad = (n) => String(n).padStart(2, "0");
    return parsed.getFullYear() + "-" + pad(parsed.getMonth() + 1) + "-" + pad(parsed.getDate()) +
      " " + pad(parsed.getHours()) + ":" + pad(parsed.getMinutes());
  }

  function stateCell(row) {
    const [label, tone] = STATE_LABELS[row.state] || ["알 수 없음", "idle"];
    const cell = node("span", label, "state " + tone);
    cell.title = row.state_detail || row.state;
    return cell;
  }

  function providersCell(ids) {
    if (!Array.isArray(ids) || !ids.length) return node("span", "—", "dim");
    const wrap = node("div", null, "provider-list");
    for (const id of ids) wrap.append(node("span", id, "provider-tag"));
    return wrap;
  }

  function errorsCell(row, ledgerState) {
    if (ledgerState === "not_configured") return node("span", "미연결", "dim");
    if (ledgerState === "unavailable") return node("span", "읽기 실패", "dim");
    const items = row.recent_error_codes;
    if (!Array.isArray(items) || !items.length) return node("span", "—", "dim");
    const wrap = node("div", null, "error-list");
    for (const item of items) {
      const line = node("div");
      line.append(node("span", item.code, "error-code"));
      line.append(node("span", " ×" + item.count, "error-count"));
      wrap.append(line);
    }
    return wrap;
  }

  function cell(content) {
    const td = node("td");
    td.append(content);
    return td;
  }

  function resetBody(message) {
    const tr = node("tr");
    const td = node("td", message, "placeholder");
    td.colSpan = 8;
    tr.append(td);
    $("slotBody").replaceChildren(tr);
  }

  function render(payload) {
    const slots = payload.slots;
    const ledger = payload.ledger;
    const configured = slots.filter((row) => row.configured === true).length;
    $("slotCount").textContent = String(slots.length);
    $("modeBadge").textContent = "읽기 전용";
    $("ledgerStatus").textContent = LEDGER_LABELS[ledger.state] || ledger.state;

    const summary = $("slotSummary");
    summary.replaceChildren();
    const good = node("span", null, "slot-chip is-good");
    good.append(node("span", "설정됨"));
    good.append(node("strong", configured));
    const missing = node("span", null, "slot-chip" + (configured === slots.length ? "" : " is-warn"));
    missing.append(node("span", "미설정"));
    missing.append(node("strong", slots.length - configured));
    const windowChip = node("span", null, "slot-chip");
    windowChip.append(node("span", "오류 집계"));
    windowChip.append(node("strong", ledger.error_window_hours + "시간"));
    summary.append(good, missing, windowChip);

    const body = $("slotBody");
    body.replaceChildren();
    for (const row of slots) {
      const tr = node("tr");
      const name = node("td");
      const strong = node("strong", row.slot, "slot-name");
      strong.append(node("small", "슬롯 " + row.slot_number));
      name.append(strong);
      tr.append(name);
      tr.append(cell(providersCell(row.provider_ids)));
      tr.append(cell(stateCell(row)));
      tr.append(node("td", row.length === null ? "—" : row.length, row.length === null ? "dim" : "tail"));
      tr.append(node("td", row.last4 ? "••••" + row.last4 : "—", row.last4 ? "tail" : "dim"));
      const modified = node("td", null, "mtime");
      if (row.file_modified_at) {
        modified.append(node("div", stamp(row.file_modified_at)));
        modified.append(node("small", MODIFIED_SOURCES[row.file_modified_source] || "", "dim"));
      } else {
        modified.append(node("span", "—", "dim"));
      }
      tr.append(modified);
      tr.append(node("td", stamp(row.last_success_at), row.last_success_at ? "mtime" : "dim"));
      tr.append(cell(errorsCell(row, ledger.state)));
      body.append(tr);
    }

    const notes = [];
    if (payload.registry === "unavailable") notes.push("공급사 레지스트리를 읽지 못해 공급사 열이 비어 있습니다.");
    if (ledger.state === "not_configured") notes.push("호출 이력 저장소가 이 배포에 연결되지 않았습니다.");
    if (ledger.state === "unavailable") notes.push("호출 이력을 읽지 못했습니다. 오류를 0으로 표시하지 않습니다.");
    notice(notes.join(" "));
  }

  async function load() {
    $("refreshBtn").disabled = true;
    $("modeBadge").textContent = "불러오는 중";
    $("ledgerStatus").textContent = "확인 중";
    resetBody("슬롯 상태를 확인하고 있습니다.");
    notice("");
    try {
      const response = await fetch(API, {
        credentials: "same-origin", cache: "no-store",
        headers: {"Accept": "application/json"},
      });
      let data = null;
      try { data = await response.json(); } catch { data = null; }
      if (!response.ok || data?.ok !== true) {
        const code = typeof data?.error?.code === "string" ? data.error.code : "http_" + response.status;
        throw new Error(code);
      }
      if (!Array.isArray(data.slots) || !data.ledger || typeof data.ledger !== "object") {
        throw new Error("credential_slots_invalid_response");
      }
      render(data);
    } catch (err) {
      $("modeBadge").textContent = "확인 불가";
      $("ledgerStatus").textContent = "확인 불가";
      $("slotSummary").replaceChildren();
      resetBody("슬롯 상태를 표시할 수 없습니다.");
      const code = String(err.message || "unknown");
      notice(messageFor(code));
    } finally {
      $("refreshBtn").disabled = false;
    }
  }

  function messageFor(code) {
    if (code === "authentication_required") {
      return "로그인이 필요합니다. 총관리자 계정으로 다시 로그인해 주세요.";
    }
    if (code === "global_model_admin_forbidden") {
      return "대표(owner) 계정만 볼 수 있는 화면입니다.";
    }
    if (code === "central_admin_not_configured" || code === "central_admin_authority_unavailable") {
      return "관리자 권한 확인이 구성되지 않았습니다. (code: " + code + ")";
    }
    if (code === "credential_slots_unavailable") {
      return "B14 연결이 구성되지 않았습니다.";
    }
    if (code === "b14_slot_status_proof_unconfigured") {
      return "서버 간 증명 비밀값이 구성되지 않아 B14 조회를 거부했습니다.";
    }
    if (code === "b14_slot_status_unreachable" || code === "b14_slot_status_refused") {
      return "B14에 연결하지 못했거나 조회가 거부되었습니다. (code: " + code + ")";
    }
    return "슬롯 상태를 가져오지 못했습니다. (code: " + code + ")";
  }

  $("refreshBtn").addEventListener("click", load);
  load();
})();
