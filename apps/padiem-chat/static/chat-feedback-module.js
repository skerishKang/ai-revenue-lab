(() => {
  "use strict";
  const API = "/api/chat/feedback", ADMIN = "/api/admin/feedback";
  const STATUSES = ["new", "reviewing", "fixed", "deferred"];
  const ID = /^fb_[a-f0-9]{32}$/;
  const scriptUrl = document.currentScript?.src || "";
  const state = { owner: "", epoch: 0, admin: false, view: "compose", own: [], inbox: [],
    ownCursor: null, adminCursor: null, unread: 0, bodyLimit: 4000, dailyLimit: 10,
    busy: false, ownLoading: false, adminLoading: false, ownError: "", adminError: "", message: "", receipt: "" };
  const requests = new Set();
  let nodes, returnFocus;
  const copy = (key, values) => window.__padiemLocale?.text("feedback-" + key, values) || "feedback-" + key;
  const owner = () => {
    const auth = window.PadiemAuthSession?.get?.();
    return auth?.authenticated === true && typeof auth.ownerKey === "string" ? auth.ownerKey : "";
  };
  const current = (epoch) => epoch === state.epoch && state.owner && owner() === state.owner;
  const element = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };
  function button(label, handler) {
    const node = element("button", "feedback-button", copy(label));
    node.type = "button";
    node.addEventListener("click", handler);
    return node;
  }
  function clearDraft() { nodes.body.value = ""; nodes.consent.checked = false; }
  function close() {
    if (nodes.dialog.open && typeof nodes.dialog.close === "function") nodes.dialog.close();
    else { nodes.dialog.removeAttribute("open"); closed(); }
  }
  function closed() {
    clearDraft();
    nodes.entry.setAttribute("aria-expanded", "false");
    if (returnFocus?.isConnected !== false) returnFocus?.focus?.();
  }
  function reset() {
    state.epoch += 1;
    for (const controller of requests) controller.abort();
    requests.clear();
    Object.assign(state, { admin: false, own: [], inbox: [], ownCursor: null, adminCursor: null,
      unread: 0, busy: false, ownLoading: false, adminLoading: false, ownError: "", adminError: "", message: "", receipt: "", view: "compose" });
    clearDraft();
    close();
    paint();
  }
  async function request(path, method = "GET", payload) {
    if (!state.owner || owner() !== state.owner) return null;
    const epoch = state.epoch, controller = new AbortController();
    requests.add(controller);
    const init = { method, credentials: "same-origin", cache: "no-store", signal: controller.signal,
      headers: { Accept: "application/json" } };
    if (payload !== undefined) { init.headers["Content-Type"] = "application/json"; init.body = JSON.stringify(payload); }
    try {
      const pending = window.fetch(path, init);
      delete init.body;
      if (payload && typeof payload.body === "string") payload.body = "";
      const response = await pending;
      const data = await response.json().catch(() => null);
      if (!current(epoch)) return null;
      if (response.status === 401) { state.owner = ""; reset(); state.message = "login"; paint(); return null; }
      return { status: response.status, data };
    } catch (_) {
      return current(epoch) ? { status: 0, data: null } : null;
    } finally { delete init.body; requests.delete(controller); }
  }
  function failure(reply) {
    const code = reply?.data?.error?.code;
    if (reply?.status === 429 && code === "feedback_daily_limit") return "daily-limit";
    if (reply?.status === 413 && code === "feedback_too_large") return "too-long";
    if (reply?.status === 400 && code === "feedback_invalid_request") return "invalid";
    return "failed";
  }
  function entry(value) {
    if (!value || !ID.test(value.id) || typeof value.body !== "string" || !STATUSES.includes(value.status)) return null;
    return { id: value.id, body: value.body, status: value.status, created_at: value.created_at,
      updated_at: value.updated_at, screen: value.screen, sender_label: value.sender_label,
      fixed_version: Number.isInteger(value.fixed_version) ? value.fixed_version : 0,
      unread_fixed: value.unread_fixed === true };
  }
  const date = (value) => {
    const parsed = new Date(value);
    return Number.isFinite(parsed.getTime()) ? parsed.toLocaleString(document.documentElement.lang === "en" ? "en" : "ko") : "";
  };
  function screenInfo() {
    const allowed = new Set(["/", "/chat", "/claw", "/settings", "/admin", "/index.html", "/claw.html", "/settings.html", "/admin.html"]);
    const url = new URL(window.location.href);
    const path = allowed.has(url.pathname) ? url.pathname : "/";
    let version = "unknown";
    try { const value = new URL(scriptUrl, url.origin).searchParams.get("v"); if (/^[A-Za-z0-9._-]{1,80}$/.test(value || "")) version = value; } catch (_) {}
    return { url: url.origin + path, width: Math.round(window.innerWidth), height: Math.round(window.innerHeight), app_version: version };
  }
  function paintRow(item, admin) {
    const row = element("li", "feedback-item");
    const heading = element("div", "feedback-item-heading");
    heading.append(element("code", "", item.id), element("span", "feedback-status", copy("status-" + item.status)));
    row.append(heading, element("p", "feedback-date", date(item.created_at)));
    if (admin && typeof item.sender_label === "string") row.append(element("p", "feedback-sender", copy("sender", { account: item.sender_label })));
    row.append(element("p", "feedback-body", item.body));
    if (admin && item.screen && typeof item.screen === "object") {
      const detail = element("details", "feedback-screen");
      detail.append(element("summary", "", copy("screen-info")));
      for (const [label, value] of [["url", item.screen.url], ["size", `${item.screen.width} × ${item.screen.height}`], ["version", item.screen.app_version]]) {
        if (typeof value === "string") detail.append(element("p", "", copy(label) + ": " + value));
      }
      row.append(detail);
    }
    if (admin) {
      const label = element("label", "feedback-status-editor", copy("change-status"));
      const select = element("select", "feedback-select");
      for (const status of STATUSES) { const option = element("option", "", copy("status-" + status)); option.value = status; select.append(option); }
      select.value = item.status;
      label.append(select);
      const save = button("save", () => void changeStatus(item.id, select.value));
      select.disabled = save.disabled = state.busy || state.adminLoading;
      row.append(label, save);
    } else if (item.unread_fixed) {
      const read = button("acknowledge", () => void acknowledge(item));
      read.disabled = state.busy || state.ownLoading;
      row.append(read);
    }
    return row;
  }
  function paint() {
    if (!nodes) return;
    const signedIn = Boolean(state.owner);
    nodes.login.hidden = signedIn;
    nodes.submit.disabled = !signedIn || state.busy || state.ownLoading;
    nodes.body.disabled = nodes.consent.disabled = !signedIn || state.busy;
    nodes.adminTab.hidden = !state.admin;
    nodes.count.textContent = copy("count", { count: Array.from(nodes.body.value).length, limit: state.bodyLimit });
    nodes.limit.textContent = copy("limit", { count: state.dailyLimit });
    nodes.status.textContent = state.receipt ? copy("received", { id: state.receipt }) : state.message ? copy(state.message, { limit: state.bodyLimit }) : "";
    nodes.notice.hidden = !signedIn || state.unread < 1;
    nodes.noticeText.textContent = copy("fixed-notice");
    for (const view of ["compose", "own", "admin"]) {
      nodes[view + "Panel"].hidden = state.view !== view;
      nodes[view + "Tab"].setAttribute("aria-pressed", String(state.view === view));
    }
    for (const [list, rows, loading, error] of [[nodes.ownList, state.own, state.ownLoading, state.ownError], [nodes.adminList, state.inbox, state.adminLoading, state.adminError]]) {
      list.replaceChildren(...rows.map((item) => paintRow(item, list === nodes.adminList)));
      if (!rows.length) list.append(element("li", "feedback-empty", copy(loading ? "loading" : error || (signedIn ? "empty" : "login"))));
      list.setAttribute("aria-busy", String(loading));
    }
    nodes.ownMore.hidden = !state.ownCursor;
    nodes.adminMore.hidden = !state.adminCursor;
    nodes.ownMore.disabled = nodes.ownRefresh.disabled = state.ownLoading || !signedIn;
    nodes.adminMore.disabled = nodes.adminRefresh.disabled = nodes.filter.disabled = state.adminLoading || !state.admin;
  }
  async function load(admin = false, more = false) {
    if (!state.owner || state.busy || (admin && !state.admin)) return;
    const loading = admin ? "adminLoading" : "ownLoading", cursorKey = admin ? "adminCursor" : "ownCursor";
    if (state[loading]) return;
    state[loading] = true; state[admin ? "adminError" : "ownError"] = ""; state.message = ""; state.receipt = ""; paint();
    const params = new URLSearchParams();
    if (admin) params.set("status", nodes.filter.value);
    if (more && state[cursorKey]) params.set("cursor", state[cursorKey]);
    const query = params.toString();
    const reply = await request((admin ? ADMIN : API) + (query ? "?" + query : ""));
    if (!reply) return;
    state[loading] = false;
    if (reply.status === 200 && reply.data?.ok === true && Array.isArray(reply.data.feedback)) {
      const key = admin ? "inbox" : "own", rows = reply.data.feedback.map(entry).filter(Boolean);
      state[key] = more ? Array.from(new Map([...state[key], ...rows].map((item) => [item.id, item])).values()) : rows;
      state[cursorKey] = ID.test(reply.data.next_cursor) ? reply.data.next_cursor : null;
      if (!admin) {
        state.unread = Number.isInteger(reply.data.unread_fixed_count) ? Math.max(0, reply.data.unread_fixed_count) : 0;
        for (const [key, value] of [["bodyLimit", reply.data.limits?.body_chars], ["dailyLimit", reply.data.limits?.daily_submissions]]) {
          if (Number.isInteger(value) && value > 0) state[key] = value;
        }
      }
    } else {
      state.message = failure(reply);
      state[admin ? "adminError" : "ownError"] = state.message;
      if (admin && reply.status === 403) { state.admin = false; state.inbox = []; state.adminCursor = null; state.view = "own"; }
    }
    paint();
  }
  async function submit(event) {
    event.preventDefault();
    if (!state.owner || state.busy || state.ownLoading) return;
    state.receipt = "";
    if (!nodes.body.value.trim()) { state.message = "required"; paint(); return; }
    if (Array.from(nodes.body.value).length > state.bodyLimit) { state.message = "too-long"; paint(); return; }
    const payload = { body: nodes.body.value };
    if (nodes.consent.checked) payload.screen = screenInfo();
    state.busy = true; state.message = "sending"; paint();
    const reply = await request(API, "POST", payload);
    if (!reply) return;
    state.busy = false;
    const item = entry(reply.data?.feedback);
    if (reply.status === 201 && reply.data?.ok === true && item) {
      clearDraft(); state.own.unshift(item); state.receipt = item.id; state.message = "";
    } else state.message = failure(reply);
    paint();
  }
  async function changeStatus(id, status) {
    if (state.busy || state.adminLoading || !state.admin || !ID.test(id) || !STATUSES.includes(status)) return;
    state.busy = true; state.receipt = ""; paint();
    const reply = await request(ADMIN + "/" + id, "PATCH", { status });
    if (!reply) return;
    state.busy = false;
    const item = entry(reply.data?.feedback);
    if (reply.status === 200 && reply.data?.ok === true && item) {
      state.inbox = state.inbox.map((old) => old.id === item.id ? item : old).filter((row) => nodes.filter.value === "all" || row.status === nodes.filter.value);
      state.message = "saved";
    } else {
      state.message = failure(reply);
      if (reply.status === 403) { state.admin = false; state.inbox = []; state.adminCursor = null; state.view = "own"; }
    }
    paint();
  }
  async function acknowledge(item) {
    if (state.busy || state.ownLoading) return;
    state.busy = true; state.message = ""; state.receipt = ""; paint();
    const reply = await request(API + "/" + item.id + "/read", "POST", { fixed_version: item.fixed_version });
    if (!reply) return;
    state.busy = false;
    const next = entry(reply.data?.feedback);
    if (reply.status === 200 && reply.data?.ok === true && next) {
      state.own = state.own.map((old) => old.id === next.id ? next : old);
      if (!next.unread_fixed) state.unread = Math.max(0, state.unread - 1);
    } else state.message = failure(reply);
    paint();
  }
  function show(view = "compose") {
    sync();
    state.view = view === "admin" && !state.admin ? "own" : view;
    if (!nodes.dialog.open) {
      returnFocus = document.activeElement;
      if (typeof nodes.dialog.showModal === "function") nodes.dialog.showModal(); else nodes.dialog.setAttribute("open", "");
    }
    nodes.entry.setAttribute("aria-expanded", "true");
    paint();
    if (view === "own") void load();
    if (view === "admin" && state.admin) void load(true);
    (state.view === "compose" && state.owner ? nodes.body : nodes[state.view + "Tab"]).focus();
  }
  async function checkAdmin() {
    const reply = await request("/api/admin/session");
    if (!reply) return;
    state.admin = reply.status === 200 && reply.data?.authenticated === true && reply.data.capabilities?.chat_admin === true;
    paint();
  }
  function sync() {
    const next = owner();
    if (next === state.owner) return;
    state.owner = next; reset();
    if (next) { void load(); void checkAdmin(); }
  }
  function init() {
    const ids = { entry: "feedbackButton", dialog: "feedbackDialog", body: "feedbackBody", consent: "feedbackConsent", form: "feedbackForm",
      submit: "feedbackSubmit", status: "feedbackStatus", count: "feedbackCount", limit: "feedbackLimit", login: "feedbackLogin",
      composeTab: "feedbackComposeTab", ownTab: "feedbackOwnTab", adminTab: "feedbackAdminTab",
      composePanel: "feedbackComposePanel", ownPanel: "feedbackOwnPanel", adminPanel: "feedbackAdminPanel",
      ownList: "feedbackOwnList", adminList: "feedbackAdminList", ownMore: "feedbackOwnMore", adminMore: "feedbackAdminMore",
      ownRefresh: "feedbackOwnRefresh", adminRefresh: "feedbackAdminRefresh", filter: "feedbackFilter", notice: "feedbackNotice", noticeText: "feedbackNoticeText" };
    nodes = Object.fromEntries(Object.entries(ids).map(([key, id]) => [key, document.getElementById(id)]));
    if (Object.values(nodes).some((node) => !node)) return;
    nodes.entry.addEventListener("click", () => show());
    nodes.form.addEventListener("submit", submit);
    nodes.body.addEventListener("input", () => { nodes.count.textContent = copy("count", { count: Array.from(nodes.body.value).length, limit: state.bodyLimit }); });
    nodes.dialog.addEventListener("close", closed);
    document.getElementById("feedbackClose").addEventListener("click", close);
    nodes.login.addEventListener("click", () => { close(); document.getElementById("loginButton")?.click(); });
    document.getElementById("feedbackNoticeOpen").addEventListener("click", () => show("own"));
    for (const view of ["compose", "own", "admin"]) nodes[view + "Tab"].addEventListener("click", () => show(view));
    nodes.ownRefresh.addEventListener("click", () => void load());
    nodes.adminRefresh.addEventListener("click", () => void load(true));
    nodes.ownMore.addEventListener("click", () => void load(false, true));
    nodes.adminMore.addEventListener("click", () => void load(true, true));
    nodes.filter.addEventListener("change", () => void load(true));
    window.addEventListener("padiem:auth-state", sync);
    window.addEventListener("padiem:localechange", paint);
    window.addEventListener("pagehide", () => { state.owner = ""; reset(); });
    window.addEventListener("pageshow", sync);
    paint(); sync();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init, { once: true }); else init();
})();
