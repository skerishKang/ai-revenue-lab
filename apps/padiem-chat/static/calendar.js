/* #2834 A4/A5 — Padiem Calendar surface (Today / Upcoming + native record/appointment create).
 *
 * Contract:
 * - Read path uses only the two existing calendar endpoints (GET today, GET upcoming).
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

  // Wall-clock date+time in an EXPLICIT zone -> offset-bearing ISO-8601. Returns
  // "" for an unknown zone or a malformed value, so a naive datetime can never be
  // produced and the caller fails closed instead of guessing.
  function zonedLocalToIso(date, time, timezone) {
    if (typeof date !== "string" || !DATE_ONLY_PATTERN.test(date)) return "";
    if (typeof time !== "string" || !TIME_OF_DAY_PATTERN.test(time)) return "";
    const dateParts = date.split("-").map(Number);
    const timeParts = time.split(":").map(Number);
    const utcGuess = Date.UTC(dateParts[0], dateParts[1] - 1, dateParts[2], timeParts[0], timeParts[1], 0);
    if (Number.isNaN(utcGuess)) return "";
    let offset = zoneOffsetMinutes(timezone, utcGuess);
    if (offset === null) return "";
    // Second pass resolves zones whose offset differs at the guessed instant
    // (DST boundaries). The zone itself is still the explicit one supplied.
    const refined = zoneOffsetMinutes(timezone, utcGuess - offset * 60000);
    if (refined !== null) offset = refined;
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

  // Same bounded UI states as the work-record path: a 201 without a usable
  // appointment object is a failure, never a saved appointment.
  function interpretAppointmentResponse(status, payload) {
    if (status === 201) {
      const saved = payload && typeof payload === "object" && payload.ok === true
        ? payload.appointment
        : null;
      if (saved && typeof saved === "object") return { status: "created", item: saved };
      return { status: "unavailable", item: null };
    }
    if (status === 401) return { status: "unauthorized", item: null };
    if (status === 400) return { status: "invalid", item: null };
    return { status: "unavailable", item: null };
  }

  const api = Object.freeze({
    TODAY_ROUTE,
    UPCOMING_ROUTE,
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
    isKnownItemType,
    itemTypeKey,
    sourceTypeText,
    formatWhen,
    browserTimezone,
    localDateInZone,
    buildWorkLogRequest,
    interpretWorkLogResponse,
    zoneOffsetMinutes,
    formatUtcOffset,
    zonedLocalToIso,
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
    const upcomingTab = document.getElementById("calendarUpcomingTab");
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
    let requestToken = 0;
    let wasActive = false;
    let lastItems = null;
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
        ensureRecordDate();
        ensureAppointmentDate();
        applyAppointmentType();
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
