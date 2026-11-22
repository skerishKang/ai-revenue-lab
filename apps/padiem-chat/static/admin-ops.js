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
  // #7690 후속: 받은함은 Chat 의견과 사이트 의견을 함께 본다. 사이트 이름은
  // 발신 쪽 칸에 쓰고, 식별자(계정 원문)는 화면에 넣지 않는다.
  const SITE_ENDPOINT = "/api/admin/site-feedback";
  const SITE_LABELS = Object.freeze({
    lovetree: "러브트리", "miraen-home": "임미란 홈페이지",
  });
  const SOURCES = Object.freeze([
    ["all", "전체"], ["chat", "Chat"],
    ["lovetree", "러브트리"], ["miraen-home", "임미란 홈페이지"],
  ]);
  const INBOX_HASH = "#ops-inbox";
  const MEMBERS_HASH = "#ops-members";
  const JOURNAL_HASH = "#ops-journal";
  const SCORES_HASH = "#ops-scores";
  const NEWS_HASH = "#ops-news";
  const state = {
    filter: "all", source: "all", cursors: { chat: null, site: null },
    inboxItems: [], busy: false,
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

  const TABS = Object.freeze([
    ["inbox", "opsTabInbox", "opsInboxPane"],
    ["members", "opsTabMembers", "opsMembersPane"],
    ["journal", "opsTabJournal", "opsJournalPane"],
    ["scores", "opsTabScores", "opsScoresPane"],
    ["news", "opsTabNews", "opsNewsPane"],
  ]);

  function selectTab(name) {
    for (const [key, tabId, paneId] of TABS) {
      const on = key === name;
      const tab = $(tabId);
      const pane = $(paneId);
      if (!tab || !pane) continue;
      tab.classList.toggle("selected", on);
      tab.setAttribute("aria-selected", on ? "true" : "false");
      pane.hidden = !on;
    }
    /* #8035 ③: 점수·일지 탭은 자기 모듈이 배선·읽기를 맡는다(#7216). */
    if ((name === "scores" || name === "journal") && window.PadiemOpsScores) {
      window.PadiemOpsScores.activate();
    }
    if (name === "news" && window.PadiemOpsNews) {
      window.PadiemOpsNews.activate();
    }
  }

  function applyHash() {
    const known = [INBOX_HASH, MEMBERS_HASH, JOURNAL_HASH, SCORES_HASH, NEWS_HASH];
    if (known.includes(location.hash)) {
      const panel = $("opsCenterPanel");
      if (panel && !$("adminContent").hidden) {
        panel.scrollIntoView({ block: "start" });
      }
    }
    if (location.hash === MEMBERS_HASH) {
      void loadMembers(true);
    } else if (location.hash === JOURNAL_HASH) {
      selectTab("journal");
    } else if (location.hash === SCORES_HASH) {
      selectTab("scores");
    } else if (location.hash === NEWS_HASH) {
      selectTab("news");
    }
  }

  /* ---- inbox (reuses the feedback window's server functions) ----------- */

  function senderName(item) {
    if (item.is_ai_tester && item.sender_display) return item.sender_display;
    return item.sender_email || item.sender_user_id || item.sender_label || "";
  }

  function isSiteItem(item) {
    return !!(item && typeof item.site === "string" && item.site);
  }

  function siteName(site) {
    return SITE_LABELS[site] || site;
  }

  function statusSelect(item, onChange) {
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
    select.addEventListener("change", () => { void onChange(item.id, select); });
    return select;
  }

  function paintSiteRow(item) {
    const li = node("li", null, "ops-row");
    li.dataset.feedbackId = item.id;
    li.dataset.status = item.status;

    const head = node("div", null, "ops-row-head");
    head.append(node("span", fmtDate(item.created_at), "ops-row-date"));
    head.append(node("span", "사이트 · " + siteName(item.site), "ops-chip"));
    head.append(statusSelect(item, changeSiteStatus));
    li.append(head);

    li.append(node("p", item.body, "ops-row-body"));
    const bits = [];
    if (item.external_feedback_id != null) bits.push("외부 의견 번호: " + item.external_feedback_id);
    if (item.external_status) bits.push("외부 상태: " + item.external_status);
    bits.push(item.external_is_ai_customer ? "AI 고객" : "사람 고객");
    if (item.external_title) bits.push("제목: " + item.external_title);
    if (item.external_category) bits.push("분류: " + item.external_category);
    li.append(node("p", bits.join(" · "), "ops-row-news"));
    if (item.external_append) {
      li.append(node("p", "덧붙임: " + item.external_append, "ops-row-body"));
    }
    if (item.ops_memo) {
      li.append(node("p", "운영 메모: " + item.ops_memo, "ops-reply"));
    }
    // #7690 역방향: 러브트리로 들어온 의견은 답글·상태를 고객에게 돌려보낸다
    // (운영 메모는 고객에게 안 보인다). 그 밖의 사이트 의견은 메모만 가능하다.
    if (item.external_feedback_id != null) {
      li.append(...outboxRows(item));
    } else {
      li.append(node("p", "운영 메모만 가능합니다. 고객에게 답글을 보낼 수 없습니다.", "ops-row-news"));
    }

    const form = document.createElement("div");
    form.className = "ops-reply-form";
    const input = document.createElement("textarea");
    input.className = "ops-reply-input";
    input.rows = 2;
    input.value = item.ops_memo || "";
    input.placeholder = "운영 메모(고객에게 보이지 않습니다)";
    input.setAttribute("aria-label", "운영 메모 입력");
    const save = node("button", "메모 저장", "ops-reply-send");
    save.type = "button";
    save.addEventListener("click", () => { void saveSiteMemo(item.id, input, li); });
    form.append(input, save);
    li.append(form);
    if (item.external_feedback_id != null) {
      li.append(replyForm(item));
    }
    return li;
  }

  // ── #7690 역방향: 러브트리로 간 답글·상태 줄 ──────────────────────────────
  const OUTBOX_STATE_LABELS = Object.freeze({
    sent: "러브트리로 보냄", pending: "보내기 대기 중", waiting: "보낼 주소·비밀이 없어 줄에 대기 중",
    failed: "보내기 실패", exhausted: "보내기 실패",
  });

  function notifyState(entry) {
    if (entry.kind === "status") {
      return "상태 알림: " + (entry.status || "") + " — " +
        (OUTBOX_STATE_LABELS[entry.state] || entry.state);
    }
    return "답글: " + fmtDate(entry.reply_created_at) + " — " +
      (OUTBOX_STATE_LABELS[entry.state] || entry.state);
  }

  function resendButton(item, entry) {
    const again = node("button", "다시 보내기", "ops-reply-send");
    again.type = "button";
    again.dataset.eventKey = entry.event_key;
    again.addEventListener("click", () => { void resendOutbox(item, entry.event_key, again); });
    return again;
  }

  function outboxRows(item) {
    const rows = [];
    const replies = (item.outbox || []).filter((entry) => entry.kind === "reply");
    const status = (item.outbox || []).filter((entry) => entry.kind === "status")[0];
    for (const entry of replies) {
      rows.push(node("p", "고객 답글: " + entry.reply_body, "ops-reply"));
      rows.push(node("p", notifyState(entry), "ops-row-news"));
      if (entry.state === "failed" || entry.state === "exhausted") {
        rows.push(resendButton(item, entry));
      }
    }
    if (status) {
      rows.push(node("p", notifyState(status), "ops-row-news"));
      if (status.state === "failed" || status.state === "exhausted") {
        rows.push(resendButton(item, status));
      }
    }
    return rows;
  }

  function replyForm(item) {
    const wrap = node("div", null, "ops-reply-form");
    wrap.append(node("p",
      "운영 메모와 다릅니다. 아래 답글은 고객에게 보입니다.", "ops-row-news"));
    const input = document.createElement("textarea");
    input.className = "ops-reply-input";
    input.rows = 2;
    input.maxLength = 2000;
    input.placeholder = "고객에게 보일 답글(2000자까지)";
    input.setAttribute("aria-label", "고객에게 보일 답글 입력");
    const send = node("button", "답글 보내기", "ops-reply-send");
    send.type = "button";
    send.addEventListener("click", () => { void sendSiteReply(item.id, input); });
    wrap.append(input, send);
    return wrap;
  }

  async function sendSiteReply(id, input) {
    const text = input.value;
    const send = input.parentElement ? input.parentElement.querySelector(".ops-reply-send") : null;
    if (send) send.disabled = true;
    try {
      const { status: code, body } = await call(
        SITE_ENDPOINT + "/" + encodeURIComponent(id) + "/reply", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ body: text }),
        });
      if (code === 201 && body?.ok === true) {
        setStatus("opsStatus", "");
        void loadInbox(true);
      } else {
        setStatus("opsStatus", "답글을 보내지 못했습니다(" +
          (body?.error?.code || code) + ").");
        if (send) send.disabled = false;
      }
    } catch (_) {
      setStatus("opsStatus", "답글을 보내는 중 연결이 끊겼습니다.");
      if (send) send.disabled = false;
    }
  }

  async function resendOutbox(item, eventKey, button) {
    button.disabled = true;
    try {
      const { status: code, body } = await call(
        SITE_ENDPOINT + "/" + encodeURIComponent(item.id) + "/resend", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ eventKey }),
        });
      if (code === 200 && body?.ok === true) {
        void loadInbox(true);
      } else {
        setStatus("opsStatus", "다시 보내지 못했습니다(" +
          (body?.error?.code || code) + ").");
        button.disabled = false;
      }
    } catch (_) {
      setStatus("opsStatus", "다시 보내는 중 연결이 끊겼습니다.");
      button.disabled = false;
    }
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
    li.append(node("p", "의견 번호: " + item.id, "ops-row-news"));
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

  function paintAny(item) {
    return isSiteItem(item) ? paintSiteRow(item) : paintRow(item);
  }

  function replaceRow(item) {
    const fresh = paintAny(item);
    const old = document.querySelector(
      `#opsInboxList .ops-row[data-feedback-id="${CSS.escape(item.id)}"]`);
    if (old) old.replaceWith(fresh);
    const index = state.inboxItems.findIndex((entry) => entry.id === item.id);
    if (index >= 0) state.inboxItems[index] = item;
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

  async function changeSiteStatus(id, select) {
    const status = select.value;
    select.disabled = true;
    try {
      const { status: code, body } = await call(
        SITE_ENDPOINT + "/" + encodeURIComponent(id), {
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

  async function saveSiteMemo(id, input, li) {
    const save = li.querySelector(".ops-reply-send");
    save.disabled = true;
    try {
      const { status: code, body } = await call(
        SITE_ENDPOINT + "/" + encodeURIComponent(id), {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ops_memo: input.value }),
        });
      if (code === 200 && body?.ok === true && body.feedback) {
        replaceRow(body.feedback);
        setStatus("opsStatus", "");
      } else {
        setStatus("opsStatus", "운영 메모를 저장하지 못했습니다(" +
          (body?.error?.code || code) + ").");
        save.disabled = false;
      }
    } catch (_) {
      setStatus("opsStatus", "운영 메모를 저장하는 중 연결이 끊겼습니다.");
      save.disabled = false;
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

  function inboxSources() {
    if (state.source === "chat") return ["chat"];
    if (state.source === "all") return ["chat", "site"];
    return ["site"];
  }

  function paintInboxList() {
    const list = $("opsInboxList");
    list.replaceChildren();
    for (const item of state.inboxItems) list.append(paintAny(item));
  }

  async function loadInbox(reset) {
    if (state.busy) return;
    state.busy = true;
    setStatus("opsStatus", "불러오는 중…");
    try {
      const kinds = inboxSources();
      const results = [];
      for (const kind of kinds) {
        const params = new URLSearchParams({ status: state.filter });
        if (kind === "site" && state.source !== "all") params.set("site", state.source);
        if (!reset && state.cursors[kind]) params.set("cursor", state.cursors[kind]);
        const url = (kind === "site" ? SITE_ENDPOINT : "/api/admin/feedback")
          + "?" + params.toString();
        const fetched = await call(url);
        results.push({ kind, ...fetched });
      }
      const failed = results.find((entry) => entry.status !== 200 || entry.body?.ok !== true);
      const list = $("opsInboxList");
      if (failed) {
        // Fail closed: the guard codes pass through, no data is rendered.
        list.replaceChildren();
        state.inboxItems = [];
        state.cursors = { chat: null, site: null };
        $("opsMore").hidden = true;
        setStatus("opsStatus", "받은함을 열 수 없습니다(" +
          (failed.body?.error?.code || failed.status) + ").");
        return;
      }
      if (reset) state.inboxItems = [];
      for (const entry of results) {
        for (const item of entry.body.feedback || []) {
          if (!state.inboxItems.some((old) => old.id === item.id)) {
            state.inboxItems.push(item);
          }
        }
        state.cursors[entry.kind] = entry.body.next_cursor || null;
        if (entry.kind === "site" && Array.isArray(entry.body.sites)) {
          syncSourceFilters(entry.body.sites);
        }
      }
      state.inboxItems.sort((a, b) =>
        String(b.created_at || "").localeCompare(String(a.created_at || ""))
        || String(b.id || "").localeCompare(String(a.id || "")));
      paintInboxList();
      $("opsMore").hidden = !state.cursors.chat && !state.cursors.site;
      setStatus("opsStatus", "");
    } catch (_) {
      setStatus("opsStatus", "받은함을 불러오는 중 연결이 끊겼습니다.");
    } finally {
      state.busy = false;
    }
  }

  function syncSourceFilters(sites) {
    const host = $("opsSourceFilters");
    if (!host) return;
    for (const site of sites) {
      if (host.querySelector(`[data-source="${CSS.escape(site)}"]`)) continue;
      const button = sourceButton(site, siteName(site));
      button.dataset.source = site;
      host.append(button);
    }
  }

  function sourceButton(value, label) {
    const button = node("button", label, "ops-filter" +
      (value === state.source ? " selected" : ""));
    button.type = "button";
    button.dataset.source = value;
    button.setAttribute("aria-pressed", value === state.source ? "true" : "false");
    button.addEventListener("click", () => {
      if (state.source === value) return;
      state.source = value;
      state.cursors = { chat: null, site: null };
      const host = $("opsSourceFilters");
      for (const other of host.querySelectorAll(".ops-filter")) {
        const on = other.dataset.source === value;
        other.classList.toggle("selected", on);
        other.setAttribute("aria-pressed", on ? "true" : "false");
      }
      void loadInbox(true);
    });
    return button;
  }

  function resetInboxCursors() {
    state.cursors = { chat: null, site: null };
  }

  function wireInbox() {
    const filters = $("opsFilters");
    filters.replaceChildren();
    const sources = $("opsSourceFilters");
    if (sources) {
      sources.replaceChildren();
      for (const [value, label] of SOURCES) sources.append(sourceButton(value, label));
    }
    for (const [value, label] of FILTERS) {
      const button = node("button", label, "ops-filter" +
        (value === state.filter ? " selected" : ""));
      button.type = "button";
      button.dataset.filter = value;
      button.setAttribute("aria-pressed", value === state.filter ? "true" : "false");
      button.addEventListener("click", () => {
        if (state.filter === value) return;
        state.filter = value;
        resetInboxCursors();
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
      resetInboxCursors();
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
    round_score_view: "회차 점수 열람", round_score_create: "회차 점수 입력",
    round_score_update: "회차 점수 수정", round_score_hide: "회차 점수 숨김",
    ops_alert_view: "알림 상태 열람", ops_alert_dispatch: "알림 다시 보내기",
    news_view: "새 소식 열람", news_create: "새 소식 작성", news_update: "새 소식 수정",
  });

  function auditRow(row) {
    const tr = document.createElement("tr");
    tr.append(
      node("td", fmtDate(row.created_at), "ops-audit-cell"),
      node("td", row.actor_label || "확인 불가", "ops-audit-cell"),
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

  /* ---- PC release observations (#8192) ---------------------------------- */
  function renderPcRollout(plan) {
    const panel = $("opsPcRollout");
    if (!panel) return;
    panel.hidden = !plan;
    if (!plan) return;
    const labels = { internal: "내부 PC", percentage: "일부 배포", all: "전체", paused: "멈춤", remaining: "나머지 PC" };
    $("opsPcRolloutSummary").textContent = "안정 " + plan.stable.version + " · 대상 " + plan.target.version +
      " · " + labels[plan.stage] + (plan.stage === "percentage" ? " " + plan.percent + "%" : "") +
      (plan.initialized ? "" : " · 기준 버전 미등록");
    const input = $("opsPcRolloutPercent");
    input.value = plan.percent;
    input.disabled = false;
    const buttons = { initialize: $("opsPcRolloutInitialize"), percentage: $("opsPcRolloutSave"),
      next: $("opsPcRolloutNext"), pause: $("opsPcRolloutPause") };
    for (const [action, button] of Object.entries(buttons)) {
      button.hidden = action === "initialize" ? plan.initialized : !plan.initialized;
      button.disabled = (action === "next" && plan.stage === "all") ||
        (action === "pause" && plan.stage === "paused");
      button.onclick = async () => {
        if ($("adminContent").hidden || !input.reportValidity()) return;
        for (const control of Object.values(buttons)) control.disabled = true;
        input.disabled = true;
        setStatus("opsPcRolloutStatus", "");
        try {
          const result = await call("/api/admin/ops-pc-versions/rollout", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ action, percent: Number(input.value), revision: plan.revision,
              target_sha256: plan.target.sha256 }),
          });
          if (result.status !== 200 || result.body?.ok !== true) {
            setStatus("opsPcRolloutStatus", "배포 설정을 저장하지 못했습니다. 다시 확인하세요.");
          }
        } catch (_) {
          setStatus("opsPcRolloutStatus", "배포 설정 연결에 실패했습니다.");
        } finally {
          await loadPcVersions();
        }
      };
    }
    const body = $("opsPcRolloutBody");
    body.replaceChildren();
    for (const name of ["internal", "percentage", "remaining"]) {
      const group = plan.groups[name];
      const row = node("tr");
      for (const value of [labels[name], group.total, group.updated, group.failed, group.rollback]) {
        row.append(node("td", value));
      }
      body.append(row);
    }
  }

  const refreshLabels = {refresh: "갱신 대상", updated: "갱신 완료", skipped: "건너뜀",
    reinstall_required: "재설치 필요", install: "신규 설치 대상", failed: "실패", queued: "응답 대기 중"};
  const refreshReasons = {system_denied: "SYSTEM 권한 없음", status_missing: "상태 파일 없음",
    release_unknown: "설치 기록 없음",
    observation_stale: "상태 정보 오래됨", status_unknown: "상태 확인 불가",
    digest_unverified: "해시 확인 불가", already_current: "최신 상태", source_changed: "새 소스 확인",
    registered: "등록 완료", awaiting_receipt: "응답 대기", dispatch_failed: "명령 실패",
    registration_failed: "등록 실패", updater_running: "실행 중", dispatch_unconfirmed: "명령 확인 불가",
    dispatch_refused: "명령 거부", receipt_unverified: "응답 검증 실패",
    watcher_missing: "감시기 없음", watcher_unregistered: "감시기 등록 실패",
    watcher_python_missing: "감시기 미등록(Python 없음)"};
  function registrationLabel(row) {
    if (row?.reason === "system_denied") {
      return "자동 갱신 제외 · " + refreshReasons.system_denied;
    }
    const label = row && refreshLabels[row.action];
    return label ? label + " · " + (refreshReasons[row.reason] || "원인 확인 불가") : "미확인";
  }
  const REFRESH_ERRORS = {
    canonical_session_required: "관리자 세션을 확인할 수 없습니다. 다시 로그인하세요.",
    connector_enrollment_csrf_denied: "보안 토큰이 만료되었습니다. 페이지를 다시 여세요.",
    enrollment_server_dependency_unavailable: "서버 준비가 끝나지 않았습니다. 잠시 뒤 다시 시도하세요.",
    canonical_session_inactive: "관리자 세션이 만료되었습니다.",
    refresh_unavailable: "갱신 상태를 불러올 수 없습니다.",
    invalid_refresh: "요청 형식이 올바르지 않습니다.",
    release_changed: "배포 버전이 바뀌었습니다. 화면을 다시 여세요.",
    administrator_required: "관리자 권한이 필요합니다.",
  };
  let previewSha = null;
  let rolloutInitialized = null;
  function refreshError(result) {
    const error = result.body && result.body.error;
    const code = error && typeof error === "object" ? error.code : error;
    return REFRESH_ERRORS[code] || code || "HTTP " + result.status;
  }
  async function refreshUpdaters(dryRun) {
    if ($("adminContent").hidden || (!dryRun && !previewSha)) return;
    const preview = $("opsPcRefreshPreview"), apply = $("opsPcRefreshApply");
    preview.disabled = apply.disabled = true;
    try {
      const result = await call("/api/admin/ops-pc-versions/refresh-updaters", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify(dryRun ? {dry_run: true} : {dry_run: false, source_sha256: previewSha}),
      });
      previewSha = null;
      if (result.status !== 200 || result.body?.ok !== true || !Array.isArray(result.body.devices)) {
        const base = rolloutInitialized === false
          ? " 기준 버전이 없어 미리 보기가 제한됐습니다. 기준 버전을 먼저 등록하세요."
          : "";
        setStatus("opsPcRefreshStatus", "갱신 작업을 완료하지 못했습니다: " + refreshError(result).replace(/\.+$/, "") + "." + base);
        return;
      }
      const rows = result.body.devices;
      if (dryRun && rows.some(row => row.action === "refresh")) previewSha = result.body.source_sha256;
      const summary = Object.entries(refreshLabels).map(([key, value]) =>
        value + " " + rows.filter(row => row.action === key).length + "대").join(" · ");
      const base = dryRun && rolloutInitialized === false
        ? " 기준 버전이 없습니다. 기준 버전을 먼저 등록하세요 — 등록하면 현재 안정 버전이 기준선으로 저장되고 배포 단계가 전체로 열립니다."
        : "";
      setStatus("opsPcRefreshStatus", (dryRun ? "미리 보기: " : "실행 결과: ") + summary + "." + base);
      await loadPcVersions();
    } catch (_) {
      previewSha = null;
      setStatus("opsPcRefreshStatus", "갱신 작업을 완료하지 못했습니다 (연결 실패).");
    } finally {
      preview.disabled = false;
      apply.disabled = !previewSha;
    }
  }

  async function loadPcVersions() {
    const body = $("opsPcVersionsBody");
    if (!body || $("adminContent").hidden) return;
    const reload = $("opsPcVersionsReload");
    reload.disabled = true;
    try {
      const result = await call("/api/admin/ops-pc-versions");
      body.replaceChildren();
      renderPcRollout(null);
      if (result.status !== 200 || !Array.isArray(result.body?.devices)) {
        setStatus("opsPcVersionsStatus", "PC 버전 정보를 불러오지 못했습니다.");
        return;
      }
      renderPcRollout(result.body.rollout);
      rolloutInitialized = result.body.rollout ? result.body.rollout.initialized : null;
      for (const item of result.body.devices) {
        const row = node("tr");
        const missing = item.received_at ? "정보 없음" : "보고 없음";
        const version = item.helper_version
          ? item.helper_version + (item.helper_build ? " (" + item.helper_build + ")" : "")
          : item.helper_build || missing;
        const updateLabels = {current: "최신", pending: "확인 중", success: "업데이트 완료",
          hash_mismatch: "해시 불일치", signature_mismatch: "서명 불일치",
          download_failed: "내려받기 실패", manifest_rejected: "버전 정보 거부", deferred: "대기", rollback: "롤백",
          available: "새 버전 있음", registration_failed: "자동 업데이트 등록 실패"};
        const reportedVersion = updateLabels[item.update_result]
          ? version + " · " + updateLabels[item.update_result] +
            (item.update_registration_error ? " (" + item.update_registration_error + ")" : "") : version;
        const deviceLabel = item.display_name || (item.device_id ? "…" + item.device_id.slice(-6) : "정보 없음");
        for (const value of [deviceLabel, reportedVersion, item.mesh_agent_version || missing,
          (item.received_at || item.last_healthy_at) ? fmtDate(item.received_at || item.last_healthy_at) : missing, registrationLabel(item.updater_registration)]) {
          row.append(node("td", value));
        }
        body.append(row);
      }
      setStatus("opsPcVersionsStatus", result.body.devices.length ? "" : "연결된 PC가 없습니다.");
    } catch (_) {
      body.replaceChildren();
      setStatus("opsPcVersionsStatus", "PC 버전 정보를 불러오지 못했습니다.");
    } finally {
      reload.disabled = false;
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
    for (const [key, tabId, , hash] of [
      ["journal", "opsTabJournal", "", JOURNAL_HASH],
      ["scores", "opsTabScores", "", SCORES_HASH],
      ["news", "opsTabNews", "", NEWS_HASH],
    ]) {
      const tab = $(tabId);
      if (!tab) continue;
      tab.addEventListener("click", () => {
        selectTab(key);
        if (location.hash !== hash) location.hash = hash;
        $("opsCenterPanel").scrollIntoView({ block: "start" });
      });
    }
    $("opsPcRefreshPreview")?.addEventListener("click", () => { void refreshUpdaters(true); });
    $("opsPcRefreshApply")?.addEventListener("click", () => { void refreshUpdaters(false); });
    const pcReload = $("opsPcVersionsReload");
    if (pcReload) {
      pcReload.addEventListener("click", () => { void loadPcVersions(); });
      void loadPcVersions();
    }
    void loadAudit();
    /* #8105: 알림 상태판은 자기 모듈이 배선·읽기를 맡는다(#7216). */
    if (window.PadiemOpsAlerts) window.PadiemOpsAlerts.activate();
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
