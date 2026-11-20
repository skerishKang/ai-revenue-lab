/* #8105 — 운영센터 알림 상태판. 새 기능은 자기 모듈에 둔다(#7216).
   관리자 게이트(#adminContent)가 열린 뒤에만 /api/admin/ops-alerts 를 부른다
   — 게스트·일반 회원에게는 호출이 0건이다. 값은 textContent로만 넣는다. */
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const CHANNEL_LABELS = Object.freeze({
    telegram: "텔레그램", discord: "디스코드", email: "이메일",
  });
  const state = { wired: false, loaded: false, busy: false };

  function node(tag, value, className) {
    const el = document.createElement(tag);
    if (value !== undefined && value !== null) el.textContent = String(value);
    if (className) el.className = className;
    return el;
  }

  function setStatus(message) {
    const el = $("opsAlertStatus");
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

  function paint(body) {
    const configured = body.configured || [];
    const config = $("opsAlertConfig");
    const names = configured.map((key) => CHANNEL_LABELS[key] || key);
    config.replaceChildren(
      node("span", names.length
        ? "알림 설정됨: " + names.join("·")
        : "알림 설정 안 됨 — 채널 값이 없어 대기함에 쌓아만 둡니다."),
      node("span", "  대기 " + (body.pending ?? 0) + "건", "ops-alert-pending")
    );
    const tbody = $("opsAlertBody");
    tbody.replaceChildren();
    for (const row of body.channels || []) {
      const tr = document.createElement("tr");
      tr.append(
        node("td", CHANNEL_LABELS[row.channel] || row.channel, "ops-alert-channel"),
        node("td", row.last_success || "-", "ops-audit-cell"),
        node("td", row.last_failure || "-", "ops-audit-cell"),
        node("td", row.attempts ?? 0, "ops-audit-cell")
      );
      tbody.append(tr);
    }
    $("opsAlertDispatch").disabled = !names.length;
  }

  async function load() {
    setStatus("");
    try {
      const { status: code, body } = await call("/api/admin/ops-alerts");
      if (code !== 200 || body?.ok !== true) {
        $("opsAlertBody").replaceChildren();
        setStatus("알림 상태를 불러오지 못했습니다(" +
          (body?.error?.code || code) + ").");
        return;
      }
      paint(body);
      state.loaded = true;
    } catch (_) {
      setStatus("알림 상태를 불러오는 중 연결이 끊겼습니다.");
    }
  }

  async function dispatch() {
    if (state.busy) return;
    state.busy = true;
    setStatus("");
    try {
      const { status: code, body } = await call(
        "/api/admin/ops-alerts/dispatch", { method: "POST" });
      if (code !== 200 || body?.ok !== true) {
        setStatus("다시 보내지 못했습니다(" + (body?.error?.code || code) + ").");
        return;
      }
      const result = body.result || {};
      setStatus("다시 보내기: 성공 " + (result.sent ?? 0) +
        "건, 실패 " + (result.failed ?? 0) + "건.");
      await load();
    } catch (_) {
      setStatus("다시 보내는 중 연결이 끊겼습니다.");
    } finally {
      state.busy = false;
    }
  }

  function wire() {
    $("opsAlertReload").addEventListener("click", () => { void load(); });
    $("opsAlertDispatch").addEventListener("click", () => { void dispatch(); });
  }

  window.PadiemOpsAlerts = Object.freeze({
    activate() {
      if (!state.wired) {
        state.wired = true;
        wire();
      }
      if (!state.loaded) void load();
    },
    reload() { return load(); },
  });
})();