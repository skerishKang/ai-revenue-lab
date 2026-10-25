(() => {
  "use strict";

  // #5034 LOCAL4 — the common notification inbox for Chat and Claw.
  //
  // Reuse boundary: this module owns presentation only. It reads the existing
  // Claw task/alert store through GET /api/claw/inbox/{alerts,tasks} and
  // updates it through PATCH /api/claw/inbox/{alerts,tasks}/{id}. It adds no
  // endpoint, no second inbox, no second notification authority and no
  // polling loop; the server derives the signed-in owner and the canonical
  // workspace from the session, so a scope cannot be widened from here.
  //
  // Read semantics: an alert whose status is "active" is unread and "dismissed"
  // is read — the existing two-state alert contract, reversible both ways. A
  // task keeps its own open/done/cancelled work status; this inbox never turns
  // a task into "done" to hide a notification, because the task status is a
  // work truth the inbox does not own.
  //
  // Result navigation never guesses. A ref that resolves to a verified
  // conversation id opens that conversation through the existing read-only
  // conversation opener; anything else falls back to the existing Claw inbox
  // focused on the exact item. When neither resolves, nothing is opened.

  const ALERTS_PATH = "/api/claw/inbox/alerts";
  const TASKS_PATH = "/api/claw/inbox/tasks";
  const LIMIT = 20;
  const ALERT_ACTIVE = "active";
  const ALERT_DISMISSED = "dismissed";
  const TASK_OPEN = "open";
  const CONVERSATION_REF = /^chat_[a-f0-9]{32}$/;
  const RUN_REF = /^sched_run_[a-f0-9]{64}$/;
  const MAX_BADGE = 99;
  const AUTH_EVENTS = ["padiem:auth-state", "padiem:auth-changed", "padiem:account-changed"];

  const state = {
    authenticated: false,
    open: false,
    inflight: false,
    statusInflight: false,
    alerts: { phase: "idle", items: [] },
    tasks: { phase: "idle", items: [] },
  };

  let refs = null;

  function text(key, variables) {
    const value = window.__padiemLocale?.text?.(key, variables);
    if (typeof value !== "string" || !value || value === key) return "";
    return value;
  }

  function isAuthenticated() {
    const loginButton = document.getElementById("loginButton");
    return Boolean(loginButton) && !loginButton.hidden;
  }

  function alertIsUnread(item) {
    return Boolean(item)
      && typeof item.alert_id === "string"
      && typeof item.title === "string"
      && item.status === ALERT_ACTIVE;
  }

  function unreadAlertCount() {
    if (!state.authenticated) return 0;
    return state.alerts.items.filter(alertIsUnread).length;
  }

  function severityLabel(value) {
    if (value === "critical") return text("notification-inbox-severity-critical");
    if (value === "warn") return text("notification-inbox-severity-warn");
    if (value === "info") return text("notification-inbox-severity-info");
    return "";
  }

  function statusLabel(key) {
    const value = text(key);
    return value ? value : "";
  }

  function formatStamp(value) {
    if (typeof value !== "string" || !value) return "";
    const parsed = Date.parse(value);
    if (Number.isNaN(parsed)) return "";
    const locale = window.__padiemLocale?.getCurrent?.() || "ko";
    try {
      return new Intl.DateTimeFormat(locale === "en" ? "en" : "ko", {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      }).format(new Date(parsed));
    } catch (_) {
      return "";
    }
  }

  function createPanel(bell) {
    const scrim = document.createElement("div");
    scrim.className = "notification-inbox-scrim";
    scrim.hidden = true;

    const panel = document.createElement("aside");
    panel.className = "notification-inbox";
    panel.id = "notificationInbox";
    panel.setAttribute("role", "dialog");
    panel.setAttribute("aria-modal", "true");
    panel.setAttribute("aria-labelledby", "notificationInboxTitle");
    panel.setAttribute("tabindex", "-1");
    panel.hidden = true;

    const header = document.createElement("header");
    header.className = "notification-inbox-header";

    const title = document.createElement("h3");
    title.id = "notificationInboxTitle";
    title.className = "notification-inbox-title";

    const headerActions = document.createElement("div");
    headerActions.className = "notification-inbox-header-actions";

    const retry = document.createElement("button");
    retry.type = "button";
    retry.className = "notification-inbox-action";
    retry.hidden = true;

    const close = document.createElement("button");
    close.type = "button";
    close.className = "notification-inbox-action";

    headerActions.append(retry, close);
    header.append(title, headerActions);

    const help = document.createElement("p");
    help.className = "notification-inbox-help";

    function createSection(listId, statusId) {
      const section = document.createElement("section");
      section.className = "notification-inbox-section";

      const heading = document.createElement("h4");
      heading.className = "notification-inbox-section-title";

      const status = document.createElement("p");
      status.className = "notification-inbox-status";
      status.id = statusId;
      status.setAttribute("aria-live", "polite");
      status.setAttribute("aria-atomic", "true");

      const list = document.createElement("div");
      list.className = "notification-inbox-list";
      list.id = listId;
      list.setAttribute("role", "list");

      section.append(heading, status, list);
      return { section, heading, status, list };
    }

    const alertsSection = createSection("notificationInboxAlertsList", "notificationInboxAlertsStatus");
    const tasksSection = createSection("notificationInboxTasksList", "notificationInboxTasksStatus");

    panel.append(header, help, alertsSection.section, tasksSection.section);
    scrim.append(panel);
    document.body.append(scrim);

    return {
      bell,
      badge: document.getElementById("notificationInboxBadge"),
      scrim,
      panel,
      title,
      retry,
      close,
      help,
      alerts: alertsSection,
      tasks: tasksSection,
    };
  }

  function render() {
    if (!refs) return;
    const signedIn = state.authenticated;
    refs.bell.hidden = !signedIn;
    refs.bell.setAttribute("aria-expanded", state.open ? "true" : "false");

    const count = unreadAlertCount();
    if (!refs.badge) return;
    refs.badge.hidden = count === 0;
    refs.badge.textContent = count === 0 ? "" : (count > MAX_BADGE ? `${MAX_BADGE}+` : String(count));
    refs.bell.setAttribute("data-count", String(count));
    refs.bell.setAttribute("aria-label", count ? text("notification-inbox-bell-unread", { count: String(count) }) : text("notification-inbox-bell"));

    const titleText = text("notification-inbox-title");
    if (titleText) refs.title.textContent = titleText;
    const closeText = text("notification-inbox-close");
    if (closeText) refs.close.textContent = closeText;
    const retryText = text("retry");
    if (retryText) refs.retry.textContent = retryText;
    const helpText = text("claw-inbox-help");
    if (helpText) refs.help.textContent = helpText;

    renderSection(refs.alerts, "alerts", "notification-inbox-alerts-section", "claw-inbox-empty-alerts", createAlertItem);
    renderSection(refs.tasks, "tasks", "notification-inbox-tasks-section", "notification-inbox-tasks-empty", createTaskItem);

    refs.retry.hidden = state.alerts.phase !== "error" && state.tasks.phase !== "error";
  }

  function renderSection(sectionRefs, name, headingKey, emptyKey, itemFactory) {
    const section = state[name];
    if (section.phase === "idle") {
      sectionRefs.status.textContent = "";
      sectionRefs.list.replaceChildren();
    } else if (section.phase === "loading") {
      sectionRefs.status.textContent = text("claw-inbox-loading");
      sectionRefs.list.replaceChildren();
    } else if (section.phase === "error") {
      sectionRefs.status.textContent = text("claw-inbox-error");
      sectionRefs.list.replaceChildren();
    } else if (section.items.length === 0) {
      sectionRefs.status.textContent = text(emptyKey);
      sectionRefs.list.replaceChildren();
    } else {
      sectionRefs.status.textContent = "";
      sectionRefs.list.replaceChildren(...section.items.map((item) => itemFactory(item)));
    }
    const heading = text(headingKey);
    if (heading) sectionRefs.heading.textContent = heading;
  }

  function createItemShell(kind, id, status) {
    const card = document.createElement("article");
    card.className = "notification-inbox-item";
    card.setAttribute("role", "listitem");
    card.setAttribute("tabindex", "0");
    card.dataset.kind = kind;
    card.dataset.itemId = id;
    if (typeof status === "string" && status) card.dataset.status = status;
    return card;
  }

  function createItemCopy(titleText, metaText) {
    const copy = document.createElement("div");
    copy.className = "notification-inbox-item-copy";

    const title = document.createElement("strong");
    title.className = "notification-inbox-item-title";
    title.textContent = typeof titleText === "string" ? titleText : "";

    const meta = document.createElement("span");
    meta.className = "notification-inbox-item-meta";
    meta.textContent = metaText;
    if (!metaText) meta.hidden = true;

    copy.append(title, meta);
    return copy;
  }

  function createActionButton(actionKey, labelKey, handler) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "notification-inbox-item-action";
    button.setAttribute("data-action", actionKey);
    button.textContent = text(labelKey);
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      handler();
    });
    return button;
  }

  function bindItem(card, item) {
    card.addEventListener("click", () => openResult(card.dataset.kind, item));
    card.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      if (event.target !== card) return;
      event.preventDefault();
      openResult(card.dataset.kind, item);
    });
  }

  function createAlertItem(item) {
    const id = item.alert_id;
    const card = createItemShell("alerts", id, item.status);
    const unread = alertIsUnread(item);

    const metaParts = [];
    const severity = severityLabel(item.severity);
    if (severity) metaParts.push(severity);
    const stamp = formatStamp(item.created_at);
    if (stamp) metaParts.push(stamp);
    if (unread) metaParts.push(text("notification-inbox-unread"));
    card.append(createItemCopy(item.title, metaParts.join(" · ")));

    const actions = document.createElement("div");
    actions.className = "notification-inbox-item-actions";
    actions.append(
      createActionButton("open", "notification-inbox-open", () => openResult("alerts", item)),
      createActionButton(
        unread ? "read" : "restore",
        unread ? "notification-inbox-read" : "notification-inbox-restore",
        () => void setAlertStatus(item, unread ? ALERT_DISMISSED : ALERT_ACTIVE),
      ),
    );
    card.append(actions);
    bindItem(card, item);
    return card;
  }

  function createTaskItem(item) {
    const id = item.task_id;
    const card = createItemShell("tasks", id, item.status);

    const metaParts = [];
    const stamp = formatStamp(item.created_at);
    if (stamp) metaParts.push(stamp);
    if (item.status === TASK_OPEN) metaParts.push(text("notification-inbox-task-open"));
    else if (item.status === "done") metaParts.push(text("notification-inbox-task-done"));
    else if (item.status === "cancelled") metaParts.push(text("notification-inbox-task-cancelled"));
    card.append(createItemCopy(item.title, metaParts.join(" · ")));

    const actions = document.createElement("div");
    actions.className = "notification-inbox-item-actions";
    actions.append(createActionButton("open", "notification-inbox-open", () => openResult("tasks", item)));
    card.append(actions);
    bindItem(card, item);
    return card;
  }

  async function loadList(name) {
    const path = name === "alerts" ? ALERTS_PATH : TASKS_PATH;
    try {
      const response = await fetch(`${path}?limit=${LIMIT}`, {
        headers: { Accept: "application/json" },
        cache: "no-store",
      });
      const data = await response.json().catch(() => null);
      if (!response.ok || !data || data.ok !== true || !Array.isArray(data.items)) {
        throw new Error("inbox unavailable");
      }
      state[name].items = data.items.filter((item) => item && typeof item === "object");
      state[name].phase = "ready";
    } catch (_) {
      state[name].phase = "error";
    }
  }

  function refresh({ force = false } = {}) {
    if (!state.authenticated) return Promise.resolve();
    if (state.inflight && !force) return Promise.resolve();
    state.inflight = true;
    if (force || state.alerts.phase === "idle") state.alerts.phase = "loading";
    if (force || state.tasks.phase === "idle") state.tasks.phase = "loading";
    render();
    return Promise.allSettled([loadList("alerts"), loadList("tasks")]).then(() => {
      state.inflight = false;
      render();
    });
  }

  async function setAlertStatus(item, status) {
    if (!item || typeof item.alert_id !== "string" || state.statusInflight) return;
    state.statusInflight = true;
    try {
      const response = await fetch(`${ALERTS_PATH}/${encodeURIComponent(item.alert_id)}`, {
        method: "PATCH",
        headers: { Accept: "application/json", "Content-Type": "application/json" },
        body: JSON.stringify({ status }),
        cache: "no-store",
      });
      const data = await response.json().catch(() => null);
      if (!response.ok || !data || data.ok !== true) throw new Error("inbox status update failed");
      await refresh({ force: true });
    } catch (_) {
      state.alerts.phase = "error";
      render();
    } finally {
      state.statusInflight = false;
    }
  }

  function firstConversationRef(item) {
    const candidates = [];
    if (Array.isArray(item.linked_refs)) candidates.push(...item.linked_refs);
    if (typeof item.linked_ref === "string") candidates.push(item.linked_ref);
    if (typeof item.source_id === "string") candidates.push(item.source_id);
    return candidates.find((ref) => typeof ref === "string" && CONVERSATION_REF.test(ref)) || "";
  }

  // #5034: an automation alert names the run that produced it. The reference is
  // the server-derived occurrence id, never a browser value, and it is accepted
  // only in that exact grammar. Navigation reuses the existing calendar link-back
  // event, so no second run-opening authority is introduced.
  function firstRunRef(item) {
    const candidates = [];
    if (Array.isArray(item.linked_refs)) candidates.push(...item.linked_refs);
    if (typeof item.source_id === "string") candidates.push(item.source_id);
    return candidates.find((ref) => typeof ref === "string" && RUN_REF.test(ref)) || "";
  }

  function openRunRef(runId) {
    try {
      window.dispatchEvent(new CustomEvent("padiem:calendar-open-link", {
        detail: { kind: "run", targetId: runId },
      }));
      return true;
    } catch (_) {
      return false;
    }
  }

  function openResult(kind, item) {
    if (!item) return;
    const id = kind === "alerts" ? item.alert_id : item.task_id;
    if (typeof id !== "string" || !id) return;

    const conversationRef = firstConversationRef(item);
    if (conversationRef && typeof window.PadiemChatConversationOpener?.open === "function") {
      let opened = false;
      try {
        opened = window.PadiemChatConversationOpener.open(conversationRef) === true;
      } catch (_) {
        opened = false;
      }
      if (opened) {
        closePanel();
        return;
      }
    }

    const runRef = firstRunRef(item);
    if (runRef && openRunRef(runRef)) {
      closePanel();
      return;
    }

    if (typeof window.PadiemInboxOpener?.open === "function") {
      let opened = false;
      try {
        opened = window.PadiemInboxOpener.open(kind, id) === true;
      } catch (_) {
        opened = false;
      }
      if (opened) closePanel();
    }
  }

  function openPanel() {
    if (!state.authenticated || state.open) return;
    state.open = true;
    refs.panel.hidden = false;
    refs.scrim.hidden = false;
    render();
    const firstItem = refs.alerts.list.querySelector(".notification-inbox-item") || refs.panel;
    firstItem.focus?.();
    void refresh({ force: true });
  }

  function closePanel() {
    if (!state.open) return;
    state.open = false;
    refs.panel.hidden = true;
    refs.scrim.hidden = true;
    render();
    refs.bell.focus?.();
  }

  function togglePanel() {
    if (state.open) {
      closePanel();
    } else {
      openPanel();
    }
  }

  function syncAuth(event) {
    const detail = event && event.detail;
    const next = typeof (detail && detail.authenticated) === "boolean"
      ? detail.authenticated
      : isAuthenticated();
    if (next === state.authenticated) return;
    state.authenticated = next;
    if (!next) {
      state.alerts.phase = "idle";
      state.alerts.items = [];
      state.tasks.phase = "idle";
      state.tasks.items = [];
      if (state.open) {
        state.open = false;
        refs.panel.hidden = true;
        refs.scrim.hidden = true;
      }
      render();
      return;
    }
    render();
    void refresh();
  }

  function init() {
    const bell = document.getElementById("notificationsBellButton");
    if (!bell || !document.body) return;
    refs = createPanel(bell);

    refs.bell.addEventListener("click", togglePanel);
    refs.close.addEventListener("click", closePanel);
    refs.retry.addEventListener("click", () => void refresh({ force: true }));
    refs.scrim.addEventListener("click", (event) => {
      if (event.target === refs.scrim) closePanel();
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && state.open) closePanel();
    });
    for (const eventName of AUTH_EVENTS) window.addEventListener(eventName, syncAuth);
    window.addEventListener("padiem:localechange", () => render());

    state.authenticated = isAuthenticated();
    render();
    if (state.authenticated) void refresh();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init, { once: true });
  } else {
    init();
  }
})();
