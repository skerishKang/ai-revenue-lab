/* #8035 ① 운영센터 — the /admin tab frame and the inbox tab. The inbox
   reuses the feedback window's own server functions (/api/admin/feedback*),
   so the screen and the ops tools share one path; nothing here reads SQL or
   duplicates a guard. This module fetches ONLY while the administrator gate
   has opened #adminContent — guests and normal members get zero /api/* calls
   from it, exactly like the page's own gate flow. */
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  /* #8035: the ops panel follows the operator's theme preference passed as
     ?theme= — the URL parameter only. The dashboard palette itself stays
     pinned (#4428 html:root), so no dashboard value shifts and the glass
     sheet is not pulled in; the panel carries its own scoped theme tokens. */
  const THEMES = ["light", "dark", "cinematic", "padiem-home", "padiem-glass"];
  const asked = new URLSearchParams(location.search).get("theme");
  if (THEMES.includes(asked)) {
    document.documentElement.setAttribute("data-theme", asked);
  }
  const STATUS_LABELS = Object.freeze({
    new: "새", reviewing: "고치는 중", fixed: "고침", deferred: "나중에",
  });
  const FILTERS = Object.freeze([
    ["all", "전체"], ["new", "새"], ["reviewing", "고치는 중"],
    ["fixed", "고침"], ["deferred", "나중에"],
  ]);
  const INBOX_HASH = "#ops-inbox";
  const state = { filter: "all", cursor: null, busy: false, wired: false };

  function node(tag, value, className) {
    const el = document.createElement(tag);
    if (value !== undefined && value !== null) el.textContent = String(value);
    if (className) el.className = className;
    return el;
  }

  function setStatus(message) {
    const el = $("opsStatus");
    if (!el) return;
    el.hidden = !message;
    el.textContent = message || "";
  }

  function fmtDate(iso) {
    if (typeof iso !== "string" || iso.length < 10) return "";
    const [d, t] = iso.split("T");
    const parts = d.split("-");
    return `${Number(parts[0])}. ${Number(parts[1])}. ${Number(parts[2])}.` +
      (t ? ` ${t.slice(0, 5)}` : "");
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

  function paintRow(item) {
    const li = node("li", null, "ops-row");
    li.dataset.feedbackId = item.id;
    li.dataset.status = item.status;

    const head = node("div", null, "ops-row-head");
    const meta = node("span", fmtDate(item.created_at), "ops-row-date");
    head.append(meta);
    if (item.is_ai_tester) {
      head.append(node("span", "AI 테스터", "ops-chip ops-chip-ai"));
    }
    const sender = node("span", item.sender_display || item.sender_label || "",
      "ops-row-sender");
    if (item.is_ai_tester && item.sender_intro) {
      const intro = item.sender_intro;
      const bits = [intro.age_band, intro.job, intro.device]
        .filter((v) => typeof v === "string" && v.trim()).join(" · ");
      sender.title = bits;
    }
    head.append(sender);
    const select = document.createElement("select");
    select.className = "ops-status-select";
    select.setAttribute("aria-label", "상태 바꾸기");
    for (const [value, label] of Object.entries(STATUS_LABELS)) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = label;
      if (value === item.status) option.selected = true;
      select.append(option);
    }
    select.addEventListener("change", () => { void changeStatus(item.id, select); });
    head.append(select);
    li.append(head);

    li.append(node("p", item.body, "ops-row-body"));
    if (item.news) {
      li.append(node("p",
        `연결된 새 소식 #${item.news.number}: ${item.news.title}`,
        "ops-row-news"));
    }
    for (const reply of item.replies || []) {
      li.append(node("p",
        (reply.side === "ops" ? "운영 답변: " : "본인 말: ") +
        reply.body + "  (" + fmtDate(reply.created_at) + ")",
        reply.side === "ops" ? "ops-reply ops-reply-ops" : "ops-reply"));
    }

    const form = document.createElement("div");
    form.className = "ops-reply-form";
    const input = document.createElement("textarea");
    input.className = "ops-reply-input";
    input.rows = 2;
    input.placeholder = "답글 달기(고객에게 보입니다)";
    input.setAttribute("aria-label", "답글 입력");
    const send = node("button", "답글 달기", "ops-reply-send");
    send.type = "button";
    send.addEventListener("click", () => { void sendReply(item.id, input, li); });
    const tester = node("button",
      item.is_ai_tester ? "AI 테스터 표시 해제" : "AI 테스터 표시",
      "ops-ai-toggle");
    tester.type = "button";
    tester.addEventListener("click", () => {
      void toggleAiTester(item.id, !item.is_ai_tester, li);
    });
    form.append(input, send, tester);
    li.append(form);
    return li;
  }

  function replaceRow(item) {
    const fresh = paintRow(item);
    const old = document.querySelector(
      `#opsInboxList .ops-row[data-feedback-id="${CSS.escape(item.id)}"]`);
    if (old) old.replaceWith(fresh);
  }

  async function changeStatus(id, select) {
    const status = select.value;
    select.disabled = true;
    try {
      const { status: code, body } = await call(
        "/api/admin/feedback/" + encodeURIComponent(id), {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ status }),
        });
      if (code === 200 && body?.ok === true && body.feedback) {
        replaceRow(body.feedback);
        setStatus("");
      } else {
        setStatus("상태를 바꾸지 못했습니다(" +
          (body?.error?.code || code) + ").");
        select.value = select.dataset.previous || status;
      }
    } catch (_) {
      setStatus("상태를 바꾸는 중 연결이 끊겼습니다.");
    } finally {
      const fresh = document.querySelector(
        `#opsInboxList .ops-row[data-feedback-id="${CSS.escape(id)}"] select`);
      if (fresh) {
        fresh.dataset.previous = fresh.value;
        fresh.disabled = false;
      }
    }
  }

  async function sendReply(id, input, li) {
    const text = input.value;
    const send = li.querySelector(".ops-reply-send");
    send.disabled = true;
    try {
      const { status: code, body } = await call(
        "/api/admin/feedback/" + encodeURIComponent(id) + "/replies", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ body: text }),
        });
      if (code === 201 && body?.ok === true && body.feedback) {
        replaceRow(body.feedback);
        setStatus("");
      } else {
        setStatus("답글을 보내지 못했습니다(" +
          (body?.error?.code || code) + ").");
        send.disabled = false;
      }
    } catch (_) {
      setStatus("답글을 보내는 중 연결이 끊겼습니다.");
      send.disabled = false;
    }
  }

  async function toggleAiTester(id, enabled, li) {
    const button = li.querySelector(".ops-ai-toggle");
    button.disabled = true;
    try {
      const { status: code, body } = await call(
        "/api/admin/feedback/" + encodeURIComponent(id) + "/ai-tester", {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ai_tester: enabled }),
        });
      if (code === 200 && body?.ok === true && body.feedback) {
        replaceRow(body.feedback);
        setStatus("");
      } else {
        setStatus("AI 테스터 표시를 바꾸지 못했습니다(" +
          (body?.error?.code || code) + ").");
        button.disabled = false;
      }
    } catch (_) {
      setStatus("AI 테스터 표시를 바꾸는 중 연결이 끊겼습니다.");
      button.disabled = false;
    }
  }

  async function loadInbox(reset) {
    if (state.busy) return;
    state.busy = true;
    setStatus("불러오는 중…");
    try {
      const params = new URLSearchParams({ status: state.filter });
      if (!reset && state.cursor) params.set("cursor", state.cursor);
      const { status: code, body } = await call(
        "/api/admin/feedback?" + params.toString());
      const list = $("opsInboxList");
      if (code !== 200 || body?.ok !== true) {
        // Fail closed: the guard codes pass through, no data is rendered.
        list.replaceChildren();
        $("opsMore").hidden = true;
        setStatus("받은함을 열 수 없습니다(" +
          (body?.error?.code || code) + ").");
        return;
      }
      if (reset) list.replaceChildren();
      for (const item of body.feedback || []) list.append(paintRow(item));
      state.cursor = body.next_cursor || null;
      $("opsMore").hidden = !state.cursor;
      setStatus("");
    } catch (_) {
      setStatus("받은함을 불러오는 중 연결이 끊겼습니다.");
    } finally {
      state.busy = false;
    }
  }

  function wire() {
    const filters = $("opsFilters");
    filters.replaceChildren();
    for (const [value, label] of FILTERS) {
      const button = node("button", label, "ops-filter" +
        (value === state.filter ? " selected" : ""));
      button.type = "button";
      button.dataset.filter = value;
      button.setAttribute("aria-pressed", value === state.filter ? "true" : "false");
      button.addEventListener("click", () => {
        if (state.filter === value) return;
        state.filter = value;
        state.cursor = null;
        for (const other of filters.querySelectorAll(".ops-filter")) {
          const on = other.dataset.filter === value;
          other.classList.toggle("selected", on);
          other.setAttribute("aria-pressed", on ? "true" : "false");
        }
        void loadInbox(true);
      });
      filters.append(button);
    }
    $("opsReload").addEventListener("click", () => {
      state.cursor = null;
      void loadInbox(true);
    });
    $("opsMore").addEventListener("click", () => { void loadInbox(false); });
    $("opsTabInbox").addEventListener("click", () => {
      // #564 lesson: the address must carry the view so browser back works.
      if (location.hash !== INBOX_HASH) location.hash = INBOX_HASH;
      $("opsCenterPanel").scrollIntoView({ block: "start" });
    });
    void loadInbox(true);
  }

  function applyHash() {
    if (location.hash === INBOX_HASH) {
      const panel = $("opsCenterPanel");
      if (panel && !$("adminContent").hidden) {
        panel.scrollIntoView({ block: "start" });
      }
    }
  }

  const content = $("adminContent");
  const observer = new MutationObserver(() => {
    if (content.hidden) return;
    if (!state.wired) {
      state.wired = true;
      wire();
    }
    applyHash();
  });
  observer.observe(content, { attributes: true, attributeFilter: ["hidden"] });
  if (!content.hidden) {
    state.wired = true;
    wire();
  }
  window.addEventListener("hashchange", applyHash);
})();
