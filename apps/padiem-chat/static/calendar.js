/* #2834 A4/A5/A6 — Padiem Calendar surface (Today / Day / Week / Month / Upcoming).
 *
 * Contract:
 * - Read path uses only the existing calendar endpoints (GET today, GET upcoming,
 *   GET items, and GET item detail for Day/Week/Month and bounded detail).
 * - Exactly two write paths exist, both pre-registered native authorities:
 *   POST /api/calendar/work-logs (A4) and POST /api/calendar/appointments (A5).
 *   No other endpoint is ever written, and no other write verb is ever used.
 * - A timed appointment always carries an explicit IANA time zone plus an
 *   offset-bearing ISO-8601 start; no browser/server time zone is ever inferred,
 *   and a naive datetime is never produced.
 * - The client never sends owner/workspace fields; the server derives scope from
 *   the authenticated session (a caller-supplied scope is rejected server-side).
 * - The client validates only what it must to avoid an obviously invalid request.
 *   The server remains the validation authority, so a 400 is still surfaced.
 * - Renders every server value as plain text; no markup is ever interpreted.
 * - No client-side item synthesis, no historical run promotion.
 * - The explicit timezone comes from the browser and is sent as a required
 *   query parameter; the server timezone of an item is used for display only.
 */
(() => {
  "use strict";

  const TODAY_ROUTE = "/api/calendar/today";
  const UPCOMING_ROUTE = "/api/calendar/upcoming";
  const ITEMS_ROUTE = "/api/calendar/items";
  const ITEM_DETAIL_ROUTE = "/api/calendar/items";
  const CALENDAR_ITEM_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$/;
  const DETAIL_LINK_KINDS = Object.freeze(["claw_session", "task", "artifact", "run"]);
  const DETAIL_LINK_TARGET_PATTERNS = Object.freeze({
    claw_session: /^chat_[0-9a-f]{32}$/,
    task: /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/,
    artifact: /^doc_[A-Za-z0-9]{32}$/,
    run: /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/,
  });
  const DETAIL_LINK_KEYS = Object.freeze({
    claw_session: "calendar-detail-link-session",
    task: "calendar-detail-link-task",
    artifact: "calendar-detail-link-artifact",
    run: "calendar-detail-link-run",
  });
  const RANGE_TABS = Object.freeze(["day", "week", "month"]);
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
    day: "calendar-empty-day",
    week: "calendar-empty-week",
    month: "calendar-empty-month",
    upcoming: "calendar-empty-upcoming",
  });
  // The single existing native work-log authority. No second write endpoint and
  // no client-side scope (owner/workspace) is ever constructed here.
  const WORK_LOG_ROUTE = "/api/calendar/work-logs";
  const RECORD_STATUS_KEYS = Object.freeze({
    created: "calendar-record-created",
    invalid: "calendar-record-invalid",
    unauthorized: "calendar-record-unauthorized",
    unavailable: "calendar-record-unavailable",
  });
  const RECORD_STATUS_VALUES = Object.freeze([
    "created",
    "invalid",
    "unauthorized",
    "unavailable",
  ]);
  // Server date grammar (calendar_contracts.parse_date): YYYY-MM-DD only.
  const DATE_ONLY_PATTERN = /^\d{4}-\d{2}-\d{2}$/;
  const TIME_OF_DAY_PATTERN = /^([01]\d|2[0-3]):([0-5]\d)$/;
  // The single existing native appointment authority (#2834 A5).
  const APPOINTMENT_ROUTE = "/api/calendar/appointments";
  const APPOINTMENT_TYPES = Object.freeze(["date_only", "all_day", "timed"]);
  // Contract bound (calendar_contracts.MAX_REMINDER_MINUTES).
  const MAX_REMINDER_MINUTES = 40320;
  const APPOINTMENT_STATUS_KEYS = Object.freeze({
    created: "calendar-appointment-created",
    invalid: "calendar-appointment-invalid",
    unauthorized: "calendar-appointment-unauthorized",
    unavailable: "calendar-appointment-unavailable",
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
    "calendar-empty-day": "Nothing scheduled for this day.",
    "calendar-empty-week": "Nothing scheduled for this week.",
    "calendar-empty-month": "Nothing scheduled for this month.",
    "calendar-empty-upcoming": "Nothing upcoming.",
    "calendar-all-day": "All day",
    "calendar-record-created": "Work record saved.",
    "calendar-record-invalid": "Check the date and title.",
    "calendar-record-unauthorized": "Please sign in and try again.",
    "calendar-record-unavailable": "Could not save the work record. Please try again shortly.",
    "calendar-appointment-created": "Appointment saved.",
    "calendar-appointment-invalid": "Check the appointment details.",
    "calendar-appointment-unauthorized": "Please sign in and try again.",
    "calendar-appointment-unavailable": "Could not save the appointment. Please try again shortly.",
    "calendar-detail-open": "Details",
    "calendar-detail-close": "Close detail",
    "calendar-detail-loading": "Loading details…",
    "calendar-detail-error": "Could not load details.",
    "calendar-detail-retry": "Try again",
    "calendar-detail-source": "Source",
    "calendar-detail-created": "Created",
    "calendar-detail-updated": "Updated",
    "calendar-detail-summary": "Details",
    "calendar-item-date": "When",
    "calendar-detail-links": "Related items",
    "calendar-detail-link-session": "Open Claw session",
    "calendar-detail-link-task": "Open task",
    "calendar-detail-link-artifact": "Download document",
    "calendar-detail-link-run": "Open Claw run",
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

  function isRangeTab(tab) {
    return RANGE_TABS.includes(tab);
  }

  function parseCalendarDate(value) {
    if (typeof value !== "string" || !DATE_ONLY_PATTERN.test(value)) return null;
    const parts = value.split("-").map(Number);
    const parsed = new Date(Date.UTC(parts[0], parts[1] - 1, parts[2]));
    if (Number.isNaN(parsed.getTime())) return null;
    if (
      parsed.getUTCFullYear() !== parts[0] ||
      parsed.getUTCMonth() !== parts[1] - 1 ||
      parsed.getUTCDate() !== parts[2]
    ) return null;
    return parsed;
  }

  function formatCalendarDate(value) {
    return `${value.getUTCFullYear()}-${String(value.getUTCMonth() + 1).padStart(2, "0")}-${String(value.getUTCDate()).padStart(2, "0")}`;
  }

  function shiftCalendarDate(value, days) {
    const parsed = parseCalendarDate(value);
    if (!parsed || !Number.isInteger(days)) return "";
    parsed.setUTCDate(parsed.getUTCDate() + days);
    return formatCalendarDate(parsed);
  }

  function shiftCalendarMonth(value, months) {
    const parsed = parseCalendarDate(value);
    if (!parsed || !Number.isInteger(months)) return "";
    const day = parsed.getUTCDate();
    const target = new Date(Date.UTC(parsed.getUTCFullYear(), parsed.getUTCMonth() + months, 1));
    const lastDay = new Date(Date.UTC(target.getUTCFullYear(), target.getUTCMonth() + 1, 0)).getUTCDate();
    target.setUTCDate(Math.min(day, lastDay));
    return formatCalendarDate(target);
  }

  function rangeForView(view, anchorDate) {
    const anchor = parseCalendarDate(anchorDate);
    if (!anchor || !isRangeTab(view)) return null;
    if (view === "day") return { start_date: anchorDate, end_date: anchorDate };
    if (view === "week") {
      const mondayOffset = (anchor.getUTCDay() + 6) % 7;
      const start = shiftCalendarDate(anchorDate, -mondayOffset);
      return { start_date: start, end_date: shiftCalendarDate(start, 6) };
    }
    const start = `${anchor.getUTCFullYear()}-${String(anchor.getUTCMonth() + 1).padStart(2, "0")}-01`;
    const end = new Date(Date.UTC(anchor.getUTCFullYear(), anchor.getUTCMonth() + 1, 0));
    return { start_date: start, end_date: formatCalendarDate(end) };
  }

  function buildItemsQuery(startDate, endDate, timezone) {
    return `?timezone=${encodeURIComponent(String(timezone == null ? "" : timezone))}&start_date=${encodeURIComponent(String(startDate == null ? "" : startDate))}&end_date=${encodeURIComponent(String(endDate == null ? "" : endDate))}`;
  }

  function shiftRangeAnchor(view, anchorDate, direction) {
    if (!Number.isInteger(direction) || !isRangeTab(view)) return "";
    if (view === "month") return shiftCalendarMonth(anchorDate, direction);
    return shiftCalendarDate(anchorDate, view === "week" ? direction * 7 : direction);
  }

  function isKnownItemType(itemType) {
    return typeof itemType === "string" && KNOWN_ITEM_TYPES.includes(itemType);
  }

  function itemTypeKey(itemType) {
    return isKnownItemType(itemType) ? ITEM_TYPE_KEYS[itemType] : "calendar-item-unknown";
  }

  function isRenderableItem(item) {
    return !!item && typeof item === "object" && !Array.isArray(item)
      && isKnownItemType(item.item_type)
      && typeof item.title === "string" && !!item.title.trim()
      && typeof item.date === "string" && !!parseCalendarDate(item.date);
  }

  function isCalendarItemId(value) {
    return typeof value === "string" && CALENDAR_ITEM_ID_PATTERN.test(value);
  }

  function isRenderableLinkBack(link) {
    if (!link || typeof link !== "object" || Array.isArray(link)) return false;
    if (!DETAIL_LINK_KINDS.includes(link.kind)) return false;
    if (typeof link.target_id !== "string") return false;
    return DETAIL_LINK_TARGET_PATTERNS[link.kind].test(link.target_id);
  }

  function isRenderableDetail(payload, expectedItemId) {
    if (!payload || payload.ok !== true || !payload.detail || typeof payload.detail !== "object") return false;
    const detail = payload.detail;
    const item = detail.item;
    if (!isRenderableItem(item) || item.calendar_item_id !== expectedItemId) return false;
    if (item.title.length > 200) return false;
    if (item.summary != null && (typeof item.summary !== "string" || item.summary.length > 4000)) return false;
    if (!Array.isArray(detail.link_backs) || detail.link_backs.length > 4) return false;
    const identities = new Set();
    for (const link of detail.link_backs) {
      if (!isRenderableLinkBack(link)) return false;
      const identity = `${link.kind}:${link.target_id}`;
      if (identities.has(identity)) return false;
      identities.add(identity);
    }
    return true;
  }

  function buildItemDetailRoute(itemId, timezone) {
    if (!isCalendarItemId(itemId) || typeof timezone !== "string" || !timezone) return "";
    return `${ITEM_DETAIL_ROUTE}/${encodeURIComponent(itemId)}${buildQuery(timezone)}`;
  }

  function dispatchCalendarLink(link) {
    if (!isRenderableLinkBack(link) || typeof window === "undefined" || typeof window.CustomEvent !== "function") return false;
    window.dispatchEvent(new window.CustomEvent("padiem:calendar-open-link", {
      detail: { kind: link.kind, targetId: link.target_id },
    }));
    return true;
  }

  // Public bounded field only: the server source_type is shown as plain text.
  // The internal reference field is never read or rendered.
  function sourceTypeText(item) {
    if (!item || typeof item !== "object") return "";
    return typeof item.source_type === "string" ? item.source_type.trim() : "";
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

  // The user's calendar date for an EXPLICIT timezone. formatToParts is used
  // instead of a locale-dependent string format, and a missing/invalid zone
  // yields "" so the caller fails closed rather than guessing a date.
  function localDateInZone(timezone, reference) {
    if (typeof timezone !== "string" || !timezone) return "";
    const at = reference instanceof Date ? reference : new Date();
    if (Number.isNaN(at.getTime())) return "";
    try {
      const parts = new Intl.DateTimeFormat("en-US", {
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        timeZone: timezone,
      }).formatToParts(at);
      const values = {};
      parts.forEach((part) => { values[part.type] = part.value; });
      if (!values.year || !values.month || !values.day) return "";
      return `${values.year}-${values.month}-${values.day}`;
    } catch (_) {
      return "";
    }
  }

  // Bounded work-log payload: exactly the three reviewed server fields. An empty
  // optional note is omitted rather than sent blank, and no owner/workspace/
  // tenant key can ever be produced by this builder.
  function buildWorkLogRequest(input) {
    const raw = input && typeof input === "object" ? input : {};
    const date = typeof raw.date === "string" ? raw.date.trim() : "";
    const title = typeof raw.title === "string" ? raw.title.trim() : "";
    const content = typeof raw.content === "string" ? raw.content.trim() : "";
    if (!DATE_ONLY_PATTERN.test(date)) return { ok: false, reason: "invalid_date" };
    if (!title) return { ok: false, reason: "title_required" };
    const payload = { date: date, title: title };
    if (content) payload.content = content;
    return { ok: true, payload: payload };
  }

  // Maps the existing endpoint's real status codes onto the four bounded UI
  // states. A 201 without a usable work_log is still treated as a failure, so a
  // malformed success response can never be reported as saved.
  function interpretWorkLogResponse(status, payload) {
    if (status === 201) {
      const saved = payload && typeof payload === "object" && payload.ok === true
        ? payload.work_log
        : null;
      if (saved && typeof saved === "object") return { status: "created", item: saved };
      return { status: "unavailable", item: null };
    }
    if (status === 401) return { status: "unauthorized", item: null };
    if (status === 400) return { status: "invalid", item: null };
    return { status: "unavailable", item: null };
  }

  // Minutes east of UTC for a zone at one instant, or null when the zone cannot
  // be resolved. Explicit accessor only: nothing is inferred from the host.
  function zoneOffsetMinutes(timezone, utcMillis) {
    if (typeof timezone !== "string" || !timezone) return null;
    try {
      const parts = new Intl.DateTimeFormat("en-US", {
        timeZone: timezone,
        hour12: false,
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      }).formatToParts(new Date(utcMillis));
      const values = {};
      parts.forEach((part) => { values[part.type] = part.value; });
      if (!values.year || !values.month || !values.day) return null;
      const asUtc = Date.UTC(
        Number(values.year),
        Number(values.month) - 1,
        Number(values.day),
        Number(values.hour) % 24,
        Number(values.minute),
        Number(values.second)
      );
      if (Number.isNaN(asUtc)) return null;
      return Math.round((asUtc - utcMillis) / 60000);
    } catch (_) {
      return null;
    }
  }

  function formatUtcOffset(minutes) {
    const sign = minutes < 0 ? "-" : "+";
    const total = Math.abs(minutes);
    const hours = String(Math.floor(total / 60)).padStart(2, "0");
    const mins = String(total % 60).padStart(2, "0");
    return `${sign}${hours}:${mins}`;
  }

  // The wall clock ("YYYY-MM-DD HH:MM") that one instant reads as in an explicit
  // zone, or null when the zone cannot be resolved. Used to verify that a
  // converted instant really is the clock time the user typed.
  function zoneWallClock(timezone, utcMillis) {
    if (typeof timezone !== "string" || !timezone) return null;
    try {
      const parts = new Intl.DateTimeFormat("en-US", {
        timeZone: timezone,
        hour12: false,
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      }).formatToParts(new Date(utcMillis));
      const values = {};
      parts.forEach((part) => { values[part.type] = part.value; });
      if (!values.year || !values.month || !values.day) return null;
      const hour = Number(values.hour) % 24;
      if (Number.isNaN(hour)) return null;
      return `${values.year}-${values.month}-${values.day} ${String(hour).padStart(2, "0")}:${values.minute}`;
    } catch (_) {
      return null;
    }
  }

  // Wall-clock date+time in an EXPLICIT zone -> offset-bearing ISO-8601. Returns
  // "" for an unknown zone, a malformed value, or a wall clock that the zone
  // SKIPS (the DST spring-forward gap), so a naive datetime can never be produced
  // and the caller fails closed rather than sending some other instant.
  //
  // Because the result is only accepted when it round-trips, the instant that is
  // sent always reads back as exactly the clock time the user typed in that zone.
  // A fall-back wall clock that exists twice resolves deterministically to the
  // EARLIER instant (the pre-transition offset side); both candidates read back as
  // the same wall clock, so the entered time is never silently drifted.
  function zonedLocalToIso(date, time, timezone) {
    if (typeof date !== "string" || !DATE_ONLY_PATTERN.test(date)) return "";
    if (typeof time !== "string" || !TIME_OF_DAY_PATTERN.test(time)) return "";
    const dateParts = date.split("-").map(Number);
    const timeParts = time.split(":").map(Number);
    const utcGuess = Date.UTC(dateParts[0], dateParts[1] - 1, dateParts[2], timeParts[0], timeParts[1], 0);
    if (Number.isNaN(utcGuess)) return "";
    const guessOffset = zoneOffsetMinutes(timezone, utcGuess);
    if (guessOffset === null) return "";
    // Sample the offsets in effect around the instant the naive guess points at,
    // so both sides of a nearby transition are considered.
    const base = utcGuess - guessOffset * 60000;
    const offsets = [];
    [-7200000, 0, 7200000].forEach((shift) => {
      const candidateOffset = zoneOffsetMinutes(timezone, base + shift);
      if (candidateOffset !== null && offsets.indexOf(candidateOffset) < 0) {
        offsets.push(candidateOffset);
      }
    });
    const wanted = `${date} ${time}`;
    const candidates = [];
    offsets.forEach((candidateOffset) => {
      const instant = utcGuess - candidateOffset * 60000;
      if (zoneWallClock(timezone, instant) === wanted) candidates.push(instant);
    });
    // No candidate round-trips: the zone skips this wall clock entirely.
    if (candidates.length === 0) return "";
    const instant = Math.min.apply(null, candidates);
    const offset = zoneOffsetMinutes(timezone, instant);
    if (offset === null) return "";
    return `${date}T${time}:00${formatUtcOffset(offset)}`;
  }

  // Bounded appointment payload. date_only/all_day carry only the date and never a
  // synthetic time; timed carries the explicit zone plus an offset-bearing start
  // and optional end, and no date (the server derives it in that zone, so a
  // date_mismatch is impossible). No scope key can be produced here.
  function buildAppointmentRequest(input) {
    const raw = input && typeof input === "object" ? input : {};
    const type = typeof raw.appointment_type === "string" ? raw.appointment_type.trim() : "";
    const title = typeof raw.title === "string" ? raw.title.trim() : "";
    const description = typeof raw.description === "string" ? raw.description.trim() : "";
    if (!APPOINTMENT_TYPES.includes(type)) return { ok: false, reason: "invalid_type" };
    if (!title) return { ok: false, reason: "title_required" };

    const payload = { appointment_type: type, title: title };
    if (description) payload.description = description;

    if (type === "timed") {
      const timezone = typeof raw.timezone === "string" ? raw.timezone.trim() : "";
      if (!timezone) return { ok: false, reason: "timezone_required" };
      const startAt = zonedLocalToIso(raw.date, raw.start_time, timezone);
      if (!startAt) return { ok: false, reason: "invalid_start" };
      payload.timezone = timezone;
      payload.start_at = startAt;
      if (typeof raw.end_time === "string" && raw.end_time.trim()) {
        const endAt = zonedLocalToIso(raw.date, raw.end_time, timezone);
        if (!endAt) return { ok: false, reason: "invalid_end" };
        payload.end_at = endAt;
      }
    } else {
      const date = typeof raw.date === "string" ? raw.date.trim() : "";
      if (!DATE_ONLY_PATTERN.test(date)) return { ok: false, reason: "invalid_date" };
      payload.date = date;
    }

    const reminder = raw.reminder_minutes;
    if (reminder !== undefined && reminder !== null && reminder !== "") {
      const parsed = Number(reminder);
      if (!Number.isInteger(parsed) || parsed < 0 || parsed > MAX_REMINDER_MINUTES) {
        return { ok: false, reason: "invalid_reminder" };
      }
      payload.reminder_minutes = parsed;
    }
    return { ok: true, payload: payload };
  }

  // "Usable" means the canonical projection's own stable fields are all present:
  // the bounded identity, the appointment item type, a real title and a server
  // date. A 201 that does not carry them (including an empty object) is a
  // failure, never a saved appointment.
  function isUsableProjectedAppointment(value) {
    if (!value || typeof value !== "object" || Array.isArray(value)) return false;
    if (typeof value.calendar_item_id !== "string" || !value.calendar_item_id.trim()) return false;
    if (value.item_type !== "appointment") return false;
    if (typeof value.title !== "string" || !value.title.trim()) return false;
    return typeof value.date === "string" && DATE_ONLY_PATTERN.test(value.date);
  }

  // Same bounded UI states as the work-record path: a 201 without a usable
  // appointment projection is a failure, never a saved appointment.
  function interpretAppointmentResponse(status, payload) {
    if (status === 201) {
      const saved = payload && typeof payload === "object" && payload.ok === true
        ? payload.appointment
        : null;
      if (isUsableProjectedAppointment(saved)) return { status: "created", item: saved };
      return { status: "unavailable", item: null };
    }
    if (status === 401) return { status: "unauthorized", item: null };
    if (status === 400) return { status: "invalid", item: null };
    return { status: "unavailable", item: null };
  }

  const api = Object.freeze({
    TODAY_ROUTE,
    UPCOMING_ROUTE,
    ITEMS_ROUTE,
    ITEM_DETAIL_ROUTE,
    DETAIL_LINK_KINDS,
    DETAIL_LINK_KEYS,
    RANGE_TABS,
    WORK_LOG_ROUTE,
    APPOINTMENT_ROUTE,
    APPOINTMENT_TYPES,
    APPOINTMENT_STATUS_KEYS,
    KNOWN_ITEM_TYPES,
    ITEM_TYPE_KEYS,
    EMPTY_KEYS,
    RECORD_STATUS_KEYS,
    RECORD_STATUS_VALUES,
    routeFor,
    buildQuery,
    isRangeTab,
    rangeForView,
    buildItemsQuery,
    shiftRangeAnchor,
    isKnownItemType,
    itemTypeKey,
    isRenderableItem,
    isCalendarItemId,
    isRenderableLinkBack,
    isRenderableDetail,
    buildItemDetailRoute,
    dispatchCalendarLink,
    sourceTypeText,
    formatWhen,
    browserTimezone,
    localDateInZone,
    buildWorkLogRequest,
    interpretWorkLogResponse,
    zoneOffsetMinutes,
    zoneWallClock,
    formatUtcOffset,
    zonedLocalToIso,
    isUsableProjectedAppointment,
    buildAppointmentRequest,
    interpretAppointmentResponse,
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
    const dayTab = document.getElementById("calendarDayTab");
    const weekTab = document.getElementById("calendarWeekTab");
    const monthTab = document.getElementById("calendarMonthTab");
    const upcomingTab = document.getElementById("calendarUpcomingTab");
    const rangeNavigation = document.getElementById("calendarRangeNavigation");
    const rangeLabel = document.getElementById("calendarRangeLabel");
    const previousRange = document.getElementById("calendarPreviousRange");
    const nextRange = document.getElementById("calendarNextRange");
    const rangeToday = document.getElementById("calendarRangeToday");
    const panel = document.getElementById("calendarPanel");
    const loading = document.getElementById("calendarLoading");
    const errorBox = document.getElementById("calendarErrorBox");
    const empty = document.getElementById("calendarEmpty");
    const list = document.getElementById("calendarList");
    const refresh = document.getElementById("calendarRefresh");
    const retry = document.getElementById("calendarRetry");
    const recordForm = document.getElementById("calendarRecordForm");
    const recordDate = document.getElementById("calendarRecordDate");
    const recordTitle = document.getElementById("calendarRecordTitle");
    const recordContent = document.getElementById("calendarRecordContent");
    const recordSubmit = document.getElementById("calendarRecordSubmit");
    const recordStatus = document.getElementById("calendarRecordStatus");
    const appointmentForm = document.getElementById("calendarAppointmentForm");
    const appointmentType = document.getElementById("calendarAppointmentType");
    const appointmentTitle = document.getElementById("calendarAppointmentTitle");
    const appointmentDate = document.getElementById("calendarAppointmentDate");
    const appointmentTimezone = document.getElementById("calendarAppointmentTimeZone");
    const appointmentStart = document.getElementById("calendarAppointmentStart");
    const appointmentEnd = document.getElementById("calendarAppointmentEnd");
    const appointmentReminder = document.getElementById("calendarAppointmentReminder");
    const appointmentDescription = document.getElementById("calendarAppointmentDescription");
    const appointmentSubmit = document.getElementById("calendarAppointmentSubmit");
    const appointmentStatus = document.getElementById("calendarAppointmentStatus");
    const appointmentTimezoneField = document.getElementById("calendarAppointmentTimeZoneField");
    const appointmentStartField = document.getElementById("calendarAppointmentStartField");
    const appointmentEndField = document.getElementById("calendarAppointmentEndField");
    if (!shell || !navButton || !view || !list) return;

    let currentTab = "today";
    let rangeAnchorDate = "";
    let requestToken = 0;
    let wasActive = false;
    let lastItems = null;
    let detailSequence = 0;
    let detailRequestToken = 0;
    let activeDetailButton = null;
    let activeDetailPanel = null;
    let lastRecordStatus = null;
    let lastAppointmentStatus = null;

    function setStatus(status) {
      if (loading) loading.hidden = status !== "loading";
      if (errorBox) errorBox.hidden = status !== "error";
      if (empty) {
        empty.hidden = status !== "empty";
        if (status === "empty") empty.textContent = text(EMPTY_KEYS[currentTab]);
      }
      list.hidden = status !== "ready";
    }

    function setDetailToggle(button, open) {
      if (!button) return;
      button.textContent = text(open ? "calendar-detail-close" : "calendar-detail-open");
      button.setAttribute("aria-expanded", String(open));
    }

    function closeDetail(button, panel) {
      if (panel) {
        panel.hidden = true;
        panel.replaceChildren();
        panel.setAttribute("aria-busy", "false");
      }
      setDetailToggle(button, false);
      if (activeDetailButton === button) activeDetailButton = null;
      if (activeDetailPanel === panel) activeDetailPanel = null;
    }

    function detailMessage(panel, key) {
      panel.replaceChildren();
      panel.append(el("p", "calendar-detail-message", text(key)));
    }

    function appendDetailMeta(target, label, value) {
      if (!value) return;
      target.append(el("dt", "calendar-detail-label", label), el("dd", "calendar-detail-value", value));
    }

    function renderDetailError(item, button, panel) {
      panel.setAttribute("aria-busy", "false");
      detailMessage(panel, "calendar-detail-error");
      const retry = el("button", "calendar-detail-retry", text("calendar-detail-retry"));
      retry.type = "button";
      retry.addEventListener("click", () => loadItemDetail(item, button, panel, true));
      panel.append(retry);
    }

    function renderDetail(payload, panel) {
      const detail = payload.detail;
      const item = detail.item;
      panel.replaceChildren();
      panel.setAttribute("aria-busy", "false");
      panel.append(el("h4", "calendar-detail-heading", item.title.trim()));
      const meta = el("dl", "calendar-detail-meta");
      appendDetailMeta(meta, text("calendar-detail-source"), sourceTypeText(item));
      appendDetailMeta(meta, text("calendar-all-day"), item.all_day === true ? text("calendar-all-day") : "");
      const when = formatWhen(item);
      appendDetailMeta(meta, text("calendar-item-date"), when);
      appendDetailMeta(meta, text("calendar-detail-created"), item.created_at);
      appendDetailMeta(meta, text("calendar-detail-updated"), item.updated_at);
      panel.append(meta);
      if (typeof item.summary === "string" && item.summary.trim()) {
        panel.append(el("p", "calendar-detail-summary", item.summary.trim()));
      }
      if (detail.link_backs.length === 0) return;
      const links = el("div", "calendar-detail-links");
      links.setAttribute("role", "group");
      links.setAttribute("aria-label", text("calendar-detail-links"));
      detail.link_backs.forEach((link) => {
        const button = el("button", "calendar-detail-link", text(DETAIL_LINK_KEYS[link.kind]));
        button.type = "button";
        button.dataset.calendarLinkKind = link.kind;
        button.dataset.calendarLinkTarget = link.target_id;
        button.addEventListener("click", () => dispatchCalendarLink(link));
        links.append(button);
      });
      panel.append(links);
    }

    async function loadItemDetail(item, button, panel, retrying) {
      const itemId = item && typeof item === "object" ? item.calendar_item_id : "";
      if (!isCalendarItemId(itemId) || !button || !panel) return;
      if (!retrying && button.getAttribute("aria-expanded") === "true") {
        closeDetail(button, panel);
        return;
      }
      const timezone = browserTimezone();
      if (activeDetailButton && activeDetailButton !== button) {
        activeDetailButton.disabled = false;
        setDetailToggle(activeDetailButton, false);
      }
      if (activeDetailPanel && activeDetailPanel !== panel) {
        activeDetailPanel.hidden = true;
        activeDetailPanel.replaceChildren();
      }
      const token = ++detailRequestToken;
      activeDetailButton = button;
      activeDetailPanel = panel;
      button.disabled = true;
      panel.hidden = false;
      panel.setAttribute("aria-busy", "true");
      setDetailToggle(button, true);
      detailMessage(panel, "calendar-detail-loading");
      const route = buildItemDetailRoute(itemId, timezone);
      if (!route) {
        button.disabled = false;
        if (activeDetailButton === button) activeDetailButton = null;
        if (activeDetailPanel === panel) activeDetailPanel = null;
        renderDetailError(item, button, panel);
        return;
      }
      try {
        const response = await fetch(route, {
          cache: "no-store",
          credentials: "same-origin",
          headers: { Accept: "application/json" },
        });
        const data = await response.json().catch(() => null);
        if (token !== detailRequestToken) return;
        if (!response.ok || !isRenderableDetail(data, itemId)) {
          renderDetailError(item, button, panel);
          return;
        }
        renderDetail(data, panel);
      } catch (_) {
        if (token !== detailRequestToken) return;
        renderDetailError(item, button, panel);
      } finally {
        if (token === detailRequestToken) {
          button.disabled = false;
          if (activeDetailButton === button) activeDetailButton = null;
          if (activeDetailPanel === panel) activeDetailPanel = null;
        }
      }
    }

    function buildRow(rawItem) {
      const item = rawItem && typeof rawItem === "object" ? rawItem : {};
      const row = el("article", "calendar-item");
      row.setAttribute("role", "listitem");
      row.dataset.itemType = isKnownItemType(item.item_type) ? item.item_type : "unknown";

      const head = el("div", "calendar-item-head");
      head.append(el("span", "calendar-item-type", text(itemTypeKey(item.item_type))));
      const sourceText = sourceTypeText(item);
      if (sourceText) head.append(el("span", "calendar-item-source", sourceText));

      const titleText = typeof item.title === "string" ? item.title.trim() : "";
      row.append(head, el("h3", "calendar-item-title", titleText || text("calendar-item-untitled")));

      const when = formatWhen(item);
      if (when) row.append(el("p", "calendar-item-when", when));
      if (item.all_day === true) row.append(el("span", "calendar-item-allday", text("calendar-all-day")));

      const summaryText = typeof item.summary === "string" ? item.summary.trim() : "";
      if (summaryText) row.append(el("p", "calendar-item-summary", summaryText));

      const itemId = item.calendar_item_id;
      if (isCalendarItemId(itemId)) {
        const actions = el("div", "calendar-item-actions");
        const detailButton = el("button", "calendar-detail-button", text("calendar-detail-open"));
        detailButton.type = "button";
        detailButton.setAttribute("aria-expanded", "false");
        detailButton.setAttribute("aria-controls", `calendarDetail${detailSequence + 1}`);
        const detailPanel = el("section", "calendar-item-detail");
        detailPanel.id = `calendarDetail${++detailSequence}`;
        detailPanel.hidden = true;
        detailPanel.setAttribute("aria-live", "polite");
        detailPanel.setAttribute("aria-busy", "false");
        detailButton.addEventListener("click", () => loadItemDetail(item, detailButton, detailPanel));
        actions.append(detailButton);
        row.append(actions, detailPanel);
      }
      return row;
    }

    function renderItems(items) {
      detailRequestToken += 1;
      if (activeDetailButton) activeDetailButton.disabled = false;
      activeDetailButton = null;
      activeDetailPanel = null;
      list.replaceChildren();
      const boundedItems = items.filter(isRenderableItem);
      if (boundedItems.length === 0) {
        setStatus("empty");
        return;
      }
      if (currentTab !== "month") {
        boundedItems.forEach((item) => list.append(buildRow(item)));
        setStatus("ready");
        return;
      }

      const groups = new Map();
      boundedItems.forEach((item) => {
        const itemDate = item.date;
        if (!groups.has(itemDate)) groups.set(itemDate, []);
        groups.get(itemDate).push(item);
      });
      groups.forEach((groupItems, date) => {
        const group = el("section", "calendar-date-group");
        group.setAttribute("role", "group");
        group.append(el("h3", "calendar-date-group-title", date));
        groupItems.forEach((item) => group.append(buildRow(item)));
        list.append(group);
      });
      setStatus("ready");
    }

    function updateRangeNavigation(timezone) {
      const active = isRangeTab(currentTab);
      if (rangeNavigation) rangeNavigation.hidden = !active;
      if (!active) return;
      const range = rangeForView(currentTab, rangeAnchorDate);
      if (rangeLabel) {
        rangeLabel.textContent = range
          ? range.start_date === range.end_date
            ? range.start_date
            : `${range.start_date} - ${range.end_date}`
          : "";
      }
      if (rangeToday) rangeToday.disabled = !localDateInZone(timezone);
    }

    function showError() {
      lastItems = null;
      list.replaceChildren();
      setStatus("error");
      detailRequestToken += 1;
    }

    function showRecordStatus(kind) {
      lastRecordStatus = kind;
      if (!recordStatus) return;
      const key = RECORD_STATUS_KEYS[kind];
      if (!key) {
        recordStatus.hidden = true;
        recordStatus.textContent = "";
        delete recordStatus.dataset.recordStatus;
        return;
      }
      recordStatus.textContent = text(key);
      recordStatus.dataset.recordStatus = kind;
      recordStatus.hidden = false;
    }

    function setRecordBusy(busy) {
      const isBusy = busy === true;
      if (recordSubmit) recordSubmit.disabled = isBusy;
      if (recordForm) recordForm.setAttribute("aria-busy", isBusy ? "true" : "false");
    }

    // The default date is computed from the browser's own timezone with an
    // explicit accessor; an unresolved zone leaves the field empty so the user
    // chooses the date instead of the client guessing one.
    function ensureRecordDate() {
      if (!recordDate || recordDate.value) return;
      const today = localDateInZone(browserTimezone());
      if (today) recordDate.value = today;
    }

    async function submitRecord(event) {
      if (event && typeof event.preventDefault === "function") event.preventDefault();
      if (!recordForm || !recordDate || !recordTitle) return;
      showRecordStatus(null);
      const built = buildWorkLogRequest({
        date: recordDate.value,
        title: recordTitle.value,
        content: recordContent ? recordContent.value : "",
      });
      if (built.ok !== true) {
        showRecordStatus("invalid");
        return;
      }
      if (!browserTimezone()) {
        showRecordStatus("unavailable");
        return;
      }
      setRecordBusy(true);
      try {
        const response = await fetch(WORK_LOG_ROUTE, {
          method: "POST",
          cache: "no-store",
          credentials: "same-origin",
          headers: { Accept: "application/json", "Content-Type": "application/json" },
          body: JSON.stringify(built.payload),
        });
        const data = await response.json().catch(() => null);
        const outcome = interpretWorkLogResponse(response.status, data);
        showRecordStatus(outcome.status);
        if (outcome.status === "created") {
          recordTitle.value = "";
          if (recordContent) recordContent.value = "";
          if (recordDate) recordDate.value = localDateInZone(browserTimezone());
          ensureRecordDate();
          await load();
        }
      } catch (_) {
        showRecordStatus("unavailable");
      } finally {
        setRecordBusy(false);
      }
    }

    function showAppointmentStatus(kind) {
      lastAppointmentStatus = kind;
      if (!appointmentStatus) return;
      const key = APPOINTMENT_STATUS_KEYS[kind];
      if (!key) {
        appointmentStatus.hidden = true;
        appointmentStatus.textContent = "";
        delete appointmentStatus.dataset.appointmentStatus;
        return;
      }
      appointmentStatus.textContent = text(key);
      appointmentStatus.dataset.appointmentStatus = kind;
      appointmentStatus.hidden = false;
    }

    function setAppointmentBusy(busy) {
      const isBusy = busy === true;
      if (appointmentSubmit) appointmentSubmit.disabled = isBusy;
      if (appointmentForm) appointmentForm.setAttribute("aria-busy", isBusy ? "true" : "false");
    }

    // Only the timed type carries a time zone / start / end. The other two send a
    // date alone, so those inputs are hidden; the zone field is pre-filled with
    // the browser zone as an explicit, editable default and is never inferred at
    // submit time.
    function applyAppointmentType() {
      const timed = !!appointmentType && appointmentType.value === "timed";
      [appointmentTimezoneField, appointmentStartField, appointmentEndField].forEach((field) => {
        if (field) field.hidden = !timed;
      });
      if (appointmentTimezone && !appointmentTimezone.value) {
        appointmentTimezone.value = browserTimezone();
      }
    }

    // Same rule as the work-record form: an unresolved browser zone leaves the
    // field empty so the user chooses the date rather than the client guessing.
    function ensureAppointmentDate() {
      if (!appointmentDate || appointmentDate.value) return;
      const today = localDateInZone(browserTimezone());
      if (today) appointmentDate.value = today;
    }

    async function submitAppointment(event) {
      if (event && typeof event.preventDefault === "function") event.preventDefault();
      if (!appointmentForm || !appointmentType || !appointmentTitle) return;
      showAppointmentStatus(null);
      const built = buildAppointmentRequest({
        appointment_type: appointmentType.value,
        title: appointmentTitle.value,
        date: appointmentDate ? appointmentDate.value : "",
        timezone: appointmentTimezone ? appointmentTimezone.value : "",
        start_time: appointmentStart ? appointmentStart.value : "",
        end_time: appointmentEnd ? appointmentEnd.value : "",
        reminder_minutes: appointmentReminder ? appointmentReminder.value : "",
        description: appointmentDescription ? appointmentDescription.value : "",
      });
      if (built.ok !== true) {
        showAppointmentStatus("invalid");
        return;
      }
      setAppointmentBusy(true);
      try {
        const response = await fetch(APPOINTMENT_ROUTE, {
          method: "POST",
          cache: "no-store",
          credentials: "same-origin",
          headers: { Accept: "application/json", "Content-Type": "application/json" },
          body: JSON.stringify(built.payload),
        });
        const data = await response.json().catch(() => null);
        const outcome = interpretAppointmentResponse(response.status, data);
        showAppointmentStatus(outcome.status);
        if (outcome.status === "created") {
          appointmentTitle.value = "";
          if (appointmentDescription) appointmentDescription.value = "";
          if (appointmentStart) appointmentStart.value = "";
          if (appointmentEnd) appointmentEnd.value = "";
          if (appointmentDate) appointmentDate.value = localDateInZone(browserTimezone());
          ensureAppointmentDate();
          applyAppointmentType();
          await load();
        }
      } catch (_) {
        showAppointmentStatus("unavailable");
      } finally {
        setAppointmentBusy(false);
      }
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
      if (isRangeTab(currentTab)) {
        const range = rangeForView(currentTab, rangeAnchorDate);
        if (!range) {
          showError();
          return;
        }
        updateRangeNavigation(timezone);
        setStatus("loading");
        try {
          const response = await fetch(`${ITEMS_ROUTE}${buildItemsQuery(range.start_date, range.end_date, timezone)}`, {
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
      if (tab !== "today" && tab !== "upcoming" && !isRangeTab(tab)) return;
      currentTab = tab;
      if (todayTab) todayTab.setAttribute("aria-selected", String(tab === "today"));
      if (dayTab) dayTab.setAttribute("aria-selected", String(tab === "day"));
      if (weekTab) weekTab.setAttribute("aria-selected", String(tab === "week"));
      if (monthTab) monthTab.setAttribute("aria-selected", String(tab === "month"));
      if (upcomingTab) upcomingTab.setAttribute("aria-selected", String(tab === "upcoming"));
      if (panel) {
        const labels = {
          today: "calendarTodayTab",
          day: "calendarDayTab",
          week: "calendarWeekTab",
          month: "calendarMonthTab",
          upcoming: "calendarUpcomingTab",
        };
        panel.setAttribute("aria-labelledby", labels[tab]);
      }
      updateRangeNavigation(browserTimezone());
      load();
    }

    function resetRangeToToday() {
      const today = localDateInZone(browserTimezone());
      if (!today) return;
      rangeAnchorDate = today;
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
        ensureRecordDate();
        ensureAppointmentDate();
        applyAppointmentType();
        if (!rangeAnchorDate) rangeAnchorDate = localDateInZone(browserTimezone());
        updateRangeNavigation(browserTimezone());
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
    if (previousRange) previousRange.addEventListener("click", () => {
      rangeAnchorDate = shiftRangeAnchor(currentTab, rangeAnchorDate, -1);
      load();
    });
    if (nextRange) nextRange.addEventListener("click", () => {
      rangeAnchorDate = shiftRangeAnchor(currentTab, rangeAnchorDate, 1);
      load();
    });
    if (rangeToday) rangeToday.addEventListener("click", resetRangeToToday);
    if (refresh) refresh.addEventListener("click", () => load());
    if (retry) retry.addEventListener("click", () => load());
    if (recordForm) recordForm.addEventListener("submit", submitRecord);
    if (appointmentType) appointmentType.addEventListener("change", applyAppointmentType);
    if (appointmentForm) appointmentForm.addEventListener("submit", submitAppointment);
    window.addEventListener("padiem:localechange", () => {
      if (empty && !empty.hidden) empty.textContent = text(EMPTY_KEYS[currentTab]);
      if (lastItems && lastItems.length) renderItems(lastItems);
      if (lastRecordStatus) showRecordStatus(lastRecordStatus);
      if (lastAppointmentStatus) showAppointmentStatus(lastAppointmentStatus);
    });

    const observer = typeof MutationObserver === "function" ? new MutationObserver(syncVisibility) : null;
    if (observer) observer.observe(shell, { attributes: true, attributeFilter: ["data-state"] });
    syncVisibility();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", createModule, { once: true });
  else createModule();
})();
