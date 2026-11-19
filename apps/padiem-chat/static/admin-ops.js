/* #8035 운영센터 — the /admin tab frame, the inbox tab, the members tab and
   the small audit table. The inbox reuses the feedback window's own server
   functions (/api/admin/feedback*) and the members tab reuses the members
   endpoints (/api/admin/members*), so the screen and the operations tools
   share one path; nothing here reads SQL or duplicates a guard. This module
   fetches ONLY while the administrator gate has opened #adminContent —
   guests and normal members get zero /api/* calls from it, exactly like the
   page's own gate flow. The dashboard palette stays pinned (#4428): the
   panel follows the operator's ?theme= choice through its own scoped
   tokens, and the theme parameter is read here, not by theme-init. */
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
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
  const MEMBERS_HASH = "#ops-members";
  const state = {
    filter: "all", cursor: null, busy: false,
    membersQuery: "", membersCursor: null, membersBusy: false,
    memberDetailId: "", auditLoaded: false,
  };

  function node(tag, value, className) {
    const el = document.createElement(tag);
    if (value !== undefined && value !== null) el.textContent = String(value);
    if (className) el.className = className;
    return el;
  }

  function setStatus(id, message) {
    const el = $(id);
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

  /* ---- tabs ------------------------------------------------------------ */

  function selectTab(name) {
    const inbox = name === "inbox";
    $("opsTabInbox").classList.toggle("selected", inbox);
    $("opsTabInbox").setAttribute("aria-selected", inbox ? "true" : "false");
    $("opsInboxPane").hidden = !inbox;
    $("opsTabMembers").classList.toggle("selected", !inbox);
    $("opsTabMembers").setAttribute("aria-selected", !inbox ? "true" : "false");
    $("opsMembersPane").hidden = inbox;
  }

  function applyHash() {
    if (location.hash === INBOX_HASH || location.hash === MEMBERS_HASH) {
      const panel = $("opsCenterPanel");
      if (panel && !$("adminContent").hidden) {
        panel.scrollIntoView({ block: "start" });
      }
    }
    if (location.hash === MEMBERS_HASH) {
      void loadMembers(true);
    }
  }

  /* ---- inbox (reuses the feedback window's server functions) ----------- */

  function senderName(item) {
    if (item.is_ai_tester && item.sender_display) return item.sender_display;
    return item.sender_email || item.sender_user_id || item.sender_label || "";
  }

  function paintRow(item) {
    const li = node("li", null, "ops-row");
    li.dataset.feedbackId = item.id;
    li.dataset.status = item.status;

    const head = node("div", null, "ops-row-head");
    head.append(node("span", fmtDate(item.created_at), "ops-row-date"));
    if (item.is_ai_tester) {
      head.append(node("span", "AI 테스터", "ops-chip ops-chip-ai"));
    }
    const sender = node("button", senderName(item), "ops-row-sender ops-link");
    sender.type = "button";
    sender.title = "회원 상세 열기";
    sender.addEventListener("click", () => { void openMemberDetail(item.sender_user_id); });
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
    select.dataset.previous = item.status;
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
        setStatus("opsStatus", "");
      } else {
        setStatus("opsStatus", "상태를 바꾸지 못했습니다(" +
          (body?.error?.code || code) + ").");
        select.value = select.dataset.previous || status;
      }
    } catch (_) {
      setStatus("opsStatus", "상태를 바꾸는 중 연결이 끊겼습니다.");
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
        setStatus("opsStatus", "");
      } else {
        setStatus("opsStatus", "답글을 보내지 못했습니다(" +
          (body?.error?.code || code) + ").");
        send.disabled = false;
      }
    } catch (_) {
      setStatus("opsStatus", "답글을 보내는 중 연결이 끊겼습니다.");
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
        setStatus("opsStatus", "");
      } else {
        setStatus("opsStatus", "AI 테스터 표시를 바꾸지 못했습니다(" +
          (body?.error?.code || code) + ").");
        button.disabled = false;
      }
    } catch (_) {
      setStatus("opsStatus", "AI 테스터 표시를 바꾸는 중 연결이 끊겼습니다.");
      button.disabled = false;
    }
  }

  async function loadInbox(reset) {
    if (state.busy) return;
    state.busy = true;
    setStatus("opsStatus", "불러오는 중…");
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
        setStatus("opsStatus", "받은함을 열 수 없습니다(" +
          (body?.error?.code || code) + ").");
        return;
      }
      if (reset) list.replaceChildren();
      for (const item of body.feedback || []) list.append(paintRow(item));
      state.cursor = body.next_cursor || null;
      $("opsMore").hidden = !state.cursor;
      setStatus("opsStatus", "");
    } catch (_) {
      setStatus("opsStatus", "받은함을 불러오는 중 연결이 끊겼습니다.");
    } finally {
      state.busy = false;
    }
  }

  function wireInbox() {
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
    void loadInbox(true);
  }

  /* ---- members tab ------------------------------------------------------ */

  function memberRow(member) {
    const li = node("li", null, "ops-row ops-member-row");
    const button = node("button", null, "ops-member-open");
    button.type = "button";
    button.append(
      node("span", member.email || member.id, "ops-member-email"),
      node("span", member.display_name || "이름 없음", "ops-member-name"),
      node("span", "가입 " + fmtDate(member.created_at), "ops-member-meta"),
      node("span", "활동 " + fmtDate(member.last_activity), "ops-member-meta"),
      node("span", member.tier, "ops-member-tier"),
      node("span", member.ai_tester ? "AI 테스터" : "일반", "ops-chip" +
        (member.ai_tester ? " ops-chip-ai" : "")),
      node("span", "의견 " + member.feedback_count, "ops-member-meta")
    );
    button.addEventListener("click", () => {
      void openMemberDetail(member.id);
    });
    li.append(button);
    return li;
  }

  async function loadMembers(reset) {
    if (state.membersBusy) return;
    state.membersBusy = true;
    setStatus("opsMembersStatus", "불러오는 중…");
    try {
      const params = new URLSearchParams();
      if (state.membersQuery) params.set("query", state.membersQuery);
      if (!reset && state.membersCursor) params.set("cursor", state.membersCursor);
      const { status: code, body } = await call("/api/admin/members?" + params.toString());
      const list = $("opsMembersList");
      if (code !== 200 || body?.ok !== true) {
        list.replaceChildren();
        $("opsMembersMore").hidden = true;
        setStatus("opsMembersStatus", "회원 목록을 열 수 없습니다(" +
          (body?.error?.code || code) + ").");
        return;
      }
      if (reset) list.replaceChildren();
      for (const member of body.members || []) list.append(memberRow(member));
      state.membersCursor = body.next_cursor || null;
      $("opsMembersMore").hidden = !state.membersCursor;
      if (!(body.members || []).length) {
        list.append(node("li", "해당 회원이 없습니다.", "ops-row"));
      }
      setStatus("opsMembersStatus", "");
    } catch (_) {
      setStatus("opsMembersStatus", "회원 목록을 불러오는 중 연결이 끊겼습니다.");
    } finally {
      state.membersBusy = false;
    }
  }

  function paintMemberDetail(member) {
    const box = $("opsMemberDetail");
    box.replaceChildren();
    const card = node("div", null, "ops-row ops-member-detail");
    const head = node("div", null, "ops-row-head");
    const back = node("button", "← 목록", "ops-link ops-back");
    back.type = "button";
    back.addEventListener("click", () => {
      $("opsMemberDetail").hidden = true;
      $("opsMembersList").hidden = false;
      if (location.hash !== MEMBERS_HASH) location.hash = MEMBERS_HASH;
    });
    head.append(back, node("span", member.display_name || "이름 없음",
      "ops-row-sender"), node("span", member.email || "", "ops-row-date"));
    card.append(head);
    card.append(node("p",
      `가입 ${fmtDate(member.created_at)} · 마지막 활동 ${fmtDate(member.last_activity)}` +
      ` · 등급 ${member.tier}` +
      (member.ai_tester ? " · AI 테스터" : ""),
      "ops-member-detail-meta"));
    const counts = node("p", null, "ops-member-detail-meta");
    counts.append(node("strong", `의견 ${member.feedback_count}`, "ops-count"),
      node("strong", `대화 ${member.conversation_count}`, "ops-count"),
      node("strong", `PC 연결 ${member.pc_link_count}`, "ops-count"));
    card.append(counts);
    const listTitle = node("p", "이 회원의 의견", "ops-member-detail-label");
    card.append(listTitle);
    if (!(member.feedback || []).length) {
      card.append(node("p", "남긴 의견이 없습니다.", "ops-row-news"));
    }
    for (const item of member.feedback || []) {
      card.append(node("p",
        fmtDate(item.created_at) + " · " + (STATUS_LABELS[item.status] || item.status) +
        " · " + (item.body || "").slice(0, 80),
        "ops-reply"));
    }
    box.append(card);
    box.hidden = false;
    $("opsMembersList").hidden = true;
  }

  async function openMemberDetail(user_id) {
    if (!user_id) return;
    setStatus("opsMembersStatus", "회원 상세를 불러오는 중…");
    try {
      const { status: code, body } = await call(
        "/api/admin/members/" + encodeURIComponent(user_id));
      if (code === 200 && body?.ok === true && body.member) {
        setStatus("opsMembersStatus", "");
        paintMemberDetail(body.member);
      } else {
        setStatus("opsMembersStatus", "회원 상세를 열 수 없습니다(" +
          (body?.error?.code || code) + ").");
      }
    } catch (_) {
      setStatus("opsMembersStatus", "회원 상세를 불러오는 중 연결이 끊겼습니다.");
    }
  }

  function wireMembers() {
    const search = $("opsMemberSearch");
    search.addEventListener("keydown", (event) => {
      if (event.key !== "Enter") return;
      state.membersQuery = search.value.trim();
      state.membersCursor = null;
      void loadMembers(true);
    });
    $("opsMembersReload").addEventListener("click", () => {
      state.membersQuery = search.value.trim();
      state.membersCursor = null;
      void loadMembers(true);
    });
    $("opsMembersMore").addEventListener("click", () => { void loadMembers(false); });
    void loadMembers(true);
  }

  /* ---- the small audit table -------------------------------------------- */

  const ACTION_LABELS = Object.freeze({
    feedback_status: "의견 상태 변경", feedback_reply: "의견 답글",
    feedback_ai_tester: "AI 테스터 표시 변경", member_detail_view: "회원 상세 열람",
  });

  function auditRow(row) {
    const tr = document.createElement("tr");
    tr.append(
      node("td", fmtDate(row.created_at), "ops-audit-cell"),
      node("td", row.actor_user_id, "ops-audit-cell"),
      node("td", ACTION_LABELS[row.action] || row.action, "ops-audit-cell"),
      node("td", row.target_type === "member"
        ? (row.target_id.slice(0, 10) + "…")
        : row.target_id, "ops-audit-cell")
    );
    return tr;
  }

  async function loadAudit() {
    setStatus("opsAuditStatus", "");
    try {
      const { status: code, body } = await call("/api/admin/ops-audit");
      const tbody = $("opsAuditBody");
      if (code !== 200 || body?.ok !== true) {
        tbody.replaceChildren();
        setStatus("opsAuditStatus", "감사 기록을 열 수 없습니다(" +
          (body?.error?.code || code) + ").");
        return;
      }
      tbody.replaceChildren();
      for (const row of body.audit || []) tbody.append(auditRow(row));
      if (!(body.audit || []).length) {
        const tr = document.createElement("tr");
        const td = node("td", "아직 기록이 없습니다.", "ops-audit-cell");
        td.colSpan = 4;
        tr.append(td);
        tbody.append(tr);
      }
    } catch (_) {
      setStatus("opsAuditStatus", "감사 기록을 불러오는 중 연결이 끊겼습니다.");
    }
  }

  /* ---- gate wiring ------------------------------------------------------- */

  function wire() {
    wireInbox();
    wireMembers();
    $("opsTabInbox").addEventListener("click", () => {
      selectTab("inbox");
      if (location.hash !== INBOX_HASH) location.hash = INBOX_HASH;
      $("opsCenterPanel").scrollIntoView({ block: "start" });
    });
    $("opsTabMembers").addEventListener("click", () => {
      selectTab("members");
      if (location.hash !== MEMBERS_HASH) location.hash = MEMBERS_HASH;
      $("opsCenterPanel").scrollIntoView({ block: "start" });
    });
    $("opsAuditReload").addEventListener("click", () => { void loadAudit(); });
    void loadAudit();
  }

  const content = $("adminContent");
  const observer = new MutationObserver(() => {
    if (content.hidden) return;
    if (!state.wired) {
      state.wired = true;
      wire();
      selectTab("inbox");
    }
    applyHash();
  });
  observer.observe(content, { attributes: true, attributeFilter: ["hidden"] });
  if (!content.hidden) {
    state.wired = true;
    wire();
    selectTab("inbox");
  }
  window.addEventListener("hashchange", applyHash);
})();
