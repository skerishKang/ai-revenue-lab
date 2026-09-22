/* #2834 A3 — Padiem Calendar read-only surface (Today / Upcoming).
 *
 * Read-only contract:
 * - Uses only the two existing calendar endpoints (GET today, GET upcoming).
 * - Renders every server value as plain text; no markup is ever interpreted.
 * - No writes, no client-side item synthesis, no historical run promotion.
 * - The explicit timezone comes from the browser and is sent as a required
 *   query parameter; the server timezone of an item is used for display only.
 */
(() => {
  "use strict";

  const TODAY_ROUTE = "/api/calendar/today";
  const UPCOMING_ROUTE = "/api/calendar/upcoming";
  const KNOWN_ITEM_TYPES = Object.freeze([
    "work_log",
    "appointment",
    "task",
    "alert",
    "claw_run",
    "automation_run",
  ]);
  const ITEM_TYPE_KEYS = Object.freeze({
    work_log: "calendar-item-work-log",
    appointment: "calendar-item-appointment",
    task: "calendar-item-task",
    alert: "calendar-item-alert",
    claw_run: "calendar-item-claw-run",
    automation_run: "calendar-item-automation-run",
  });
  const EMPTY_KEYS = Object.freeze({
    today: "calendar-empty-today",
    upcoming: "calendar-empty-upcoming",
  });

  // English fallback copy. Korean copy lives in locale.js; this only keeps the
  // surface readable if the locale authority is unavailable.
  const FALLBACK_COPY = Object.freeze({
    "calendar-item-work-log": "Work log",
    "calendar-item-appointment": "Appointment",
    "calendar-item-task": "Task",
    "calendar-item-alert": "Alert",
    "calendar-item-claw-run": "Claw run",
    "calendar-item-automation-run": "Automation run",
    "calendar-item-unknown": "Other",
    "calendar-item-untitled": "Untitled",
    "calendar-empty-today": "Nothing scheduled for today.",
    "calendar-empty-upcoming": "Nothing upcoming.",
    "calendar-all-day": "All day",
  });

  function text(key, variables) {
    try {
      const locale = typeof window !== "undefined" ? window.__padiemLocale : null;
      const value = locale ? locale.text(key, variables) : null;
      if (value && value !== key) return value;
    } catch (_) {}
    let value = FALLBACK_COPY[key] || key;
    if (variables && typeof variables === "object") {
      Object.keys(variables).forEach((name) => {
        value = value.split(`{${name}}`).join(String(variables[name]));
      });
    }
    return value;
  }

  function routeFor(tab) {
    return tab === "upcoming" ? UPCOMING_ROUTE : TODAY_ROUTE;
  }

  function buildQuery(timezone) {
    return `?timezone=${encodeURIComponent(String(timezone == null ? "" : timezone))}`;
  }

  function isKnownItemType(itemType) {
    return typeof itemType === "string" && KNOWN_ITEM_TYPES.includes(itemType);
  }

  function itemTypeKey(itemType) {
    return isKnownItemType(itemType) ? ITEM_TYPE_KEYS[itemType] : "calendar-item-unknown";
  }

  function browserTimezone() {
    try {
      const resolved = Intl.DateTimeFormat().resolvedOptions().timeZone;
      return typeof resolved === "string" ? resolved : "";
    } catch (_) {
      return "";
    }
  }

  function formatTimeInZone(value, timezone) {
    if (typeof value !== "string" || !value) return "";
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return "";
    try {
      return new Intl.DateTimeFormat(undefined, {
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
        timeZone: timezone,
      }).format(parsed);
    } catch (_) {
      return "";
    }
  }

  // Display uses server-provided values only: an item is shown in its own
  // server timezone. Without that timezone only the server date is shown —
  // the client never substitutes its own zone for a missing one.
  function formatWhen(item) {
    if (!item || typeof item !== "object") return "";
    const date = typeof item.date === "string" ? item.date : "";
    const timezone = typeof item.timezone === "string" ? item.timezone : "";
    if (!timezone || item.all_day === true) return date;
    const start = formatTimeInZone(item.start_at, timezone);
    const end = formatTimeInZone(item.end_at, timezone);
    if (!start) return date;
    if (end && end !== start) return `${date} ${start}–${end}`;
    return `${date} ${start}`;
  }

  const api = Object.freeze({
    TODAY_ROUTE,
    UPCOMING_ROUTE,
    KNOWN_ITEM_TYPES,
    ITEM_TYPE_KEYS,
    EMPTY_KEYS,
    routeFor,
    buildQuery,
    isKnownItemType,
    itemTypeKey,
    formatWhen,
    browserTimezone,
  });
  if (typeof window !== "undefined") window.PadiemCalendarUI = api;
  if (typeof document === "undefined") return;

  function el(tag, className, content) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (content !== undefined) node.textContent = content;
    return node;
  }

  function createModule() {
    const shell = document.querySelector(".app-shell");
    const navButton = document.getElementById("calendarNavButton");
    const view = document.getElementById("calendarView");
    const tabs = document.getElementById("calendarTabs");
    const todayTab = document.getElementById("calendarTodayTab");
    const upcomingTab = document.getElementById("calendarUpcomingTab");
    const panel = document.getElementById("calendarPanel");
    const loading = document.getElementById("calendarLoading");
    const errorBox = document.getElementById("calendarErrorBox");
    const empty = document.getElementById("calendarEmpty");
    const list = document.getElementById("calendarList");
    const refresh = document.getElementById("calendarRefresh");
    const retry = document.getElementById("calendarRetry");
    if (!shell || !navButton || !view || !list) return;

    let currentTab = "today";
    let requestToken = 0;
    let wasActive = false;
    let lastItems = null;

    function setStatus(status) {
      if (loading) loading.hidden = status !== "loading";
      if (errorBox) errorBox.hidden = status !== "error";
      if (empty) {
        empty.hidden = status !== "empty";
        if (status === "empty") empty.textContent = text(EMPTY_KEYS[currentTab]);
      }
      list.hidden = status !== "ready";
    }

    function buildRow(rawItem) {
      const item = rawItem && typeof rawItem === "object" ? rawItem : {};
      const row = el("article", "calendar-item");
      row.setAttribute("role", "listitem");
      row.dataset.itemType = isKnownItemType(item.item_type) ? item.item_type : "unknown";

      const head = el("div", "calendar-item-head");
      head.append(el("span", "calendar-item-type", text(itemTypeKey(item.item_type))));

      const titleText = typeof item.title === "string" ? item.title.trim() : "";
      row.append(head, el("h3", "calendar-item-title", titleText || text("calendar-item-untitled")));

      const when = formatWhen(item);
      if (when) row.append(el("p", "calendar-item-when", when));
      if (item.all_day === true) row.append(el("span", "calendar-item-allday", text("calendar-all-day")));

      const summaryText = typeof item.summary === "string" ? item.summary.trim() : "";
      if (summaryText) row.append(el("p", "calendar-item-summary", summaryText));
      return row;
    }

    function renderItems(items) {
      list.replaceChildren();
      items.forEach((item) => list.append(buildRow(item)));
      setStatus("ready");
    }

    function showError() {
      lastItems = null;
      list.replaceChildren();
      setStatus("error");
    }

    async function load() {
      const timezone = browserTimezone();
      requestToken += 1;
      const token = requestToken;
      if (!timezone) {
        // The endpoint requires an explicit timezone; without one we do not
        // guess and do not send a request.
        showError();
        return;
      }
      setStatus("loading");
      try {
        const response = await fetch(`${routeFor(currentTab)}${buildQuery(timezone)}`, {
          cache: "no-store",
          credentials: "same-origin",
          headers: { Accept: "application/json" },
        });
        const data = await response.json().catch(() => null);
        if (token !== requestToken) return;
        const projection = data && data.ok === true ? data.projection : null;
        const items = projection && Array.isArray(projection.items) ? projection.items : null;
        if (!response.ok || !items) {
          showError();
          return;
        }
        lastItems = items;
        if (items.length === 0) {
          list.replaceChildren();
          setStatus("empty");
          return;
        }
        renderItems(items);
      } catch (_) {
        if (token !== requestToken) return;
        showError();
      }
    }

    function selectTab(tab) {
      if (tab !== "today" && tab !== "upcoming") return;
      currentTab = tab;
      if (todayTab) todayTab.setAttribute("aria-selected", String(tab === "today"));
      if (upcomingTab) upcomingTab.setAttribute("aria-selected", String(tab === "upcoming"));
      if (panel) {
        panel.setAttribute("aria-labelledby", tab === "today" ? "calendarTodayTab" : "calendarUpcomingTab");
      }
      load();
    }

    function closeSidebar() {
      shell.classList.remove("sidebar-open");
      const menu = document.getElementById("mobileMenu");
      if (menu) menu.setAttribute("aria-expanded", "false");
      const scrim = document.getElementById("sidebarScrim");
      if (scrim) scrim.hidden = true;
    }

    function syncVisibility() {
      const active = shell.dataset.state === "calendar";
      view.hidden = !active;
      navButton.setAttribute("aria-current", active ? "page" : "false");
      if (active) {
        const chatNav = document.getElementById("newChatButton");
        if (chatNav) chatNav.setAttribute("aria-current", "false");
      }
      if (active && !wasActive) load();
      wasActive = active;
    }

    navButton.addEventListener("click", () => {
      const alreadyActive = shell.dataset.state === "calendar";
      shell.dataset.state = "calendar";
      syncVisibility();
      if (alreadyActive) load();
      closeSidebar();
    });
    if (tabs) {
      tabs.addEventListener("click", (event) => {
        const button = event.target.closest("[data-calendar-tab]");
        if (button) selectTab(button.dataset.calendarTab);
      });
    }
    if (refresh) refresh.addEventListener("click", () => load());
    if (retry) retry.addEventListener("click", () => load());
    window.addEventListener("padiem:localechange", () => {
      if (empty && !empty.hidden) empty.textContent = text(EMPTY_KEYS[currentTab]);
      if (lastItems && lastItems.length) renderItems(lastItems);
    });

    const observer = typeof MutationObserver === "function" ? new MutationObserver(syncVisibility) : null;
    if (observer) observer.observe(shell, { attributes: true, attributeFilter: ["data-state"] });
    syncVisibility();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", createModule, { once: true });
  else createModule();
})();
