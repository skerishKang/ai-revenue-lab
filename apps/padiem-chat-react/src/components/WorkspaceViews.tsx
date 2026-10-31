import { useCallback, useEffect, useState } from "react";
import {
  createAutomationRule,
  createCalendarWorkLog,
  createMeeting,
  deleteAutomationRule,
  fetchAutomationRules,
  fetchCalendarItems,
  fetchLibraryFiles,
  fetchMeeting,
  fetchMeetings,
  type AutomationRule,
  type CalendarItem,
  type CalendarTab,
  type LibraryFile,
  type MeetingSummary,
} from "../api/workspaceApi";
import { useLocale } from "../i18n/LocaleProvider";

/**
 * #5298 — the workspace views.
 *
 * The library, the automation, the calendar and the meeting notes all exist in
 * the product. The clone renders the same surfaces with the same ids and
 * classes, so the approved styling applies unchanged, and it reads the
 * product's own routes.
 */

type ViewState = "idle" | "loading" | "ready" | "error" | "empty";

/* ---------------------------------------------------------------- library */

export function LibraryView() {
  const { t } = useLocale();
  const [files, setFiles] = useState<LibraryFile[]>([]);
  const [state, setState] = useState<ViewState>("loading");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetchLibraryFiles(null, controller.signal)
      .then((page) => {
        setFiles(page.files);
        setState(page.files.length ? "ready" : "empty");
      })
      .catch((failure: unknown) => {
        if (failure instanceof Error && failure.name === "AbortError") return;
        setError(failure instanceof Error ? failure.message : t("library-error"));
        setState("error");
      });
    return () => controller.abort();
  }, [t]);

  return (
    <section className="library-view" id="libraryView" aria-labelledby="libraryTitle">
      <header className="library-header">
        <p className="standalone-view-kicker">Padiem Library</p>
        <h2 className="standalone-view-title" id="libraryTitle">
          {t("library-title") || "라이브러리"}
        </h2>
      </header>
      <div className="library-panel" id="libraryFilesPanel" role="tabpanel" tabIndex={-1}>
        <div className="library-list" id="libraryFileList" role="list">
          {state === "loading" ? (
            <p className="library-empty" id="libraryLoading">
              {t("library-loading") || "라이브러리를 불러오는 중…"}
            </p>
          ) : null}
          {state === "error" ? (
            <p className="library-error" id="libraryError" role="alert">
              {error}
            </p>
          ) : null}
          {state === "empty" ? (
            <p className="library-empty" id="libraryEmpty">
              {t("library-empty") || "저장된 자료가 없습니다."}
            </p>
          ) : null}
          {files.map((file) => (
            <article className="library-item" key={file.id} data-file-id={file.id}>
              <strong>{file.name}</strong>
              <small>{file.media_type ?? file.project_id}</small>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------- automation */

export function AutomationView() {
  const { t } = useLocale();
  const [rules, setRules] = useState<AutomationRule[]>([]);
  const [state, setState] = useState<ViewState>("loading");
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [expression, setExpression] = useState("");
  const [timezone, setTimezone] = useState("");
  const [status, setStatus] = useState<string | null>(null);

  const reload = useCallback(() => {
    setState("loading");
    fetchAutomationRules()
      .then((result) => {
        setRules(result.rules);
        setState(result.rules.length ? "ready" : "empty");
      })
      .catch((failure: unknown) => {
        setError(failure instanceof Error ? failure.message : t("claw-automation-error"));
        setState("error");
      });
  }, [t]);

  useEffect(reload, [reload]);

  const create = async (event: React.FormEvent) => {
    event.preventDefault();
    setStatus(null);
    try {
      await createAutomationRule({
        name: name.trim(),
        schedule_kind: "daypart",
        schedule_expression: expression.trim(),
        schedule_timezone: timezone.trim(),
      });
      setName("");
      setExpression("");
      reload();
    } catch (failure) {
      setStatus(failure instanceof Error ? failure.message : t("claw-automation-error"));
    }
  };

  const remove = async (rule: AutomationRule) => {
    setStatus(null);
    try {
      await deleteAutomationRule(rule.rule_id);
      reload();
    } catch (failure) {
      setStatus(failure instanceof Error ? failure.message : t("claw-automation-error"));
    }
  };

  return (
    <section
      className="standalone-view automation-view"
      id="automationView"
      aria-labelledby="automationViewTitle"
    >
      <header className="standalone-view-header">
        <p className="standalone-view-kicker">Padiem Automation</p>
        <h2 className="standalone-view-title" id="automationViewTitle">
          {t("automation-view-title") || "자동화"}
        </h2>
      </header>
      <div className="claw-inbox-status" id="clawAutomationStatus" aria-live="polite" aria-atomic="true">
        {state === "loading" ? (
          <p id="clawAutomationLoading">{t("claw-automation-loading") || "자동화 규칙을 불러오는 중…"}</p>
        ) : null}
        {state === "error" ? (
          <p id="clawAutomationError" role="alert">
            {error}
          </p>
        ) : null}
        {state === "empty" ? (
          <p className="claw-inbox-empty" id="clawAutomationEmpty">
            {t("claw-automation-empty") || "등록된 자동화 규칙이 없습니다."}
          </p>
        ) : null}
      </div>
      <ul className="claw-inbox-list" id="clawAutomationList" role="list">
        {rules.map((rule) => (
          <li key={rule.rule_id} className="claw-inbox-item" data-rule-id={rule.rule_id}>
            <strong>{rule.name}</strong>
            <small>
              {rule.schedule_expression} ({rule.schedule_timezone}) ·{" "}
              {rule.enabled ? t("automation-rule-on") || "켜짐" : t("automation-rule-off") || "꺼짐"}
            </small>
            <button
              type="button"
              className="claw-inbox-retry"
              onClick={() => void remove(rule)}
            >
              {t("delete") || "삭제"}
            </button>
          </li>
        ))}
      </ul>
      <form className="calendar-record-form" id="clawAutomationCreateForm" onSubmit={create}>
        <label className="calendar-record-field" htmlFor="clawAutomationCreateName">
          {t("claw-automation-create-summary") || "+ 자동화 만들기"}
          <input
            id="clawAutomationCreateName"
            name="name"
            type="text"
            maxLength={120}
            required
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
        </label>
        <label className="calendar-record-field" htmlFor="clawAutomationCreateExpression">
          {t("automation-rule-setting") || "실행 조건"}
          <input
            id="clawAutomationCreateExpression"
            name="schedule_expression"
            type="text"
            maxLength={120}
            required
            value={expression}
            onChange={(event) => setExpression(event.target.value)}
          />
        </label>
        <label className="calendar-record-field" htmlFor="clawAutomationCreateTimezone">
          {t("calendar-record-timezone-label") || "시간대"}
          <input
            id="clawAutomationCreateTimezone"
            name="schedule_timezone"
            type="text"
            maxLength={64}
            required
            value={timezone}
            onChange={(event) => setTimezone(event.target.value)}
          />
        </label>
        <button className="calendar-record-submit" id="clawAutomationCreateSubmit" type="submit">
          {t("claw-automation-create-submit") || "자동화 만들기"}
        </button>
        <p className="calendar-record-status" id="clawAutomationCreateStatus" role="status" aria-live="polite" hidden>
          {status}
        </p>
      </form>
    </section>
  );
}

/* --------------------------------------------------------------- calendar */

const CALENDAR_TABS: { tab: CalendarTab; id: string; labelKey: string; label: string }[] = [
  { tab: "today", id: "calendarTodayTab", labelKey: "calendar-today", label: "오늘" },
  { tab: "day", id: "calendarDayTab", labelKey: "calendar-day", label: "일" },
  { tab: "week", id: "calendarWeekTab", labelKey: "calendar-week", label: "주" },
  { tab: "month", id: "calendarMonthTab", labelKey: "calendar-month", label: "월" },
  { tab: "upcoming", id: "calendarUpcomingTab", labelKey: "calendar-upcoming", label: "예정" },
];

export function CalendarView() {
  const { t } = useLocale();
  const [tab, setTab] = useState<CalendarTab>("today");
  const [items, setItems] = useState<CalendarItem[]>([]);
  const [state, setState] = useState<ViewState>("loading");
  const [error, setError] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [date, setDate] = useState("");
  const [content, setContent] = useState("");
  const [status, setStatus] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setState("loading");
    fetchCalendarItems(tab, {}, controller.signal)
      .then((result) => {
        setItems(result);
        setState(result.length ? "ready" : "empty");
      })
      .catch((failure: unknown) => {
        if (failure instanceof Error && failure.name === "AbortError") return;
        setError(failure instanceof Error ? failure.message : t("calendar-error"));
        setState("error");
      });
    return () => controller.abort();
  }, [tab, t]);

  const save = async (event: React.FormEvent) => {
    event.preventDefault();
    setStatus(null);
    try {
      await createCalendarWorkLog({
        date: date.trim(),
        title: title.trim(),
        ...(content.trim() ? { content: content.trim() } : {}),
      });
      setTitle("");
      setContent("");
      setTab("today");
    } catch (failure) {
      setStatus(failure instanceof Error ? failure.message : t("calendar-record-unavailable"));
    }
  };

  return (
    <section className="calendar-view" id="calendarView" aria-labelledby="calendarViewTitle">
      <header className="calendar-view-header">
        <p className="standalone-view-kicker">Padiem Calendar</p>
        <h2 className="standalone-view-title" id="calendarViewTitle">
          {t("calendar-title") || "캘린더"}
        </h2>
      </header>
      <div className="calendar-tabs" id="calendarTabs" role="tablist" aria-label={t("calendar-tabs-aria") || "캘린더 보기 선택"}>
        {CALENDAR_TABS.map((entry) => (
          <button
            key={entry.tab}
            type="button"
            className="calendar-tab"
            id={entry.id}
            role="tab"
            data-calendar-tab={entry.tab}
            aria-selected={tab === entry.tab ? "true" : "false"}
            aria-controls="calendarPanel"
            onClick={() => setTab(entry.tab)}
          >
            {t(entry.labelKey) || entry.label}
          </button>
        ))}
      </div>
      <div className="calendar-panel" id="calendarPanel" role="tabpanel" tabIndex={-1}>
        {state === "loading" ? (
          <p className="calendar-loading" id="calendarLoading">
            {t("calendar-loading") || "불러오는 중…"}
          </p>
        ) : null}
        {state === "error" ? (
          <p className="calendar-error" id="calendarError" role="alert">
            {error}
          </p>
        ) : null}
        {state === "empty" ? (
          <p className="calendar-empty" id="calendarEmpty">
            {t("calendar-empty-today") || "오늘 예정된 일정이 없습니다."}
          </p>
        ) : null}
        <ul className="calendar-items" id="calendarItemList">
          {items.map((item) => (
            <li key={item.calendar_item_id ?? item.id ?? item.title} className="calendar-item">
              <strong>{item.title}</strong>
              <small>
                {item.date}
                {item.start_at ? ` ${item.start_at.slice(11, 16)}` : ""}
              </small>
            </li>
          ))}
        </ul>
      </div>
      <form className="calendar-record-form" id="calendarRecordForm" onSubmit={save}>
        <h3 className="calendar-record-summary">
          {t("calendar-record-summary") || "작업 기록 추가"}
        </h3>
        <label className="calendar-record-field" htmlFor="calendarRecordTitle">
          {t("calendar-record-title-label") || "제목"}
          <input
            id="calendarRecordTitle"
            name="title"
            type="text"
            maxLength={200}
            required
            value={title}
            onChange={(event) => setTitle(event.target.value)}
          />
        </label>
        <label className="calendar-record-field" htmlFor="calendarRecordDate">
          {t("calendar-record-date") || "날짜"}
          <input
            id="calendarRecordDate"
            name="date"
            type="date"
            required
            value={date}
            onChange={(event) => setDate(event.target.value)}
          />
        </label>
        <label className="calendar-record-field" htmlFor="calendarRecordContent">
          {t("calendar-record-content-label") || "메모 (선택)"}
          <textarea
            id="calendarRecordContent"
            name="content"
            rows={3}
            maxLength={2000}
            value={content}
            onChange={(event) => setContent(event.target.value)}
          />
        </label>
        <button className="calendar-record-submit" id="calendarRecordSubmit" type="submit">
          {t("calendar-record-submit") || "기록 저장"}
        </button>
        <p className="calendar-record-status" id="calendarRecordStatus" role="status" aria-live="polite" hidden>
          {status}
        </p>
      </form>
    </section>
  );
}

/* --------------------------------------------------------------- meetings */

export function MeetingView() {
  const { t } = useLocale();
  const [meetings, setMeetings] = useState<MeetingSummary[]>([]);
  const [state, setState] = useState<ViewState>("loading");
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<MeetingSummary | null>(null);
  const [title, setTitle] = useState("");
  const [status, setStatus] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetchMeetings(controller.signal)
      .then((result) => {
        setMeetings(result);
        setState(result.length ? "ready" : "empty");
      })
      .catch((failure: unknown) => {
        if (failure instanceof Error && failure.name === "AbortError") return;
        setError(failure instanceof Error ? failure.message : t("meeting-error"));
        setState("error");
      });
    return () => controller.abort();
  }, [t]);

  const open = async (meeting: MeetingSummary) => {
    setStatus(null);
    try {
      const detail = await fetchMeeting(meeting);
      setSelected(detail.meeting);
    } catch (failure) {
      setStatus(failure instanceof Error ? failure.message : t("meeting-error"));
    }
  };

  const create = async (event: React.FormEvent) => {
    event.preventDefault();
    setStatus(null);
    try {
      await createMeeting({ title: title.trim() });
      setTitle("");
      setMeetings(await fetchMeetings());
    } catch (failure) {
      setStatus(failure instanceof Error ? failure.message : t("meeting-error"));
    }
  };

  return (
    <section
      id="meetingView"
      className="standalone-view meeting-view"
      aria-labelledby="meetingTitle"
    >
      <header className="standalone-view-header meeting-header">
        <div>
          <p className="standalone-view-kicker">Padiem Meeting</p>
          <h2 className="standalone-view-title" id="meetingTitle">
            {t("meeting-title") || "회의록"}
          </h2>
        </div>
      </header>
      <p className="meeting-help">
        {t("meeting-help") ||
          "녹음·실시간 받아쓰기는 별도 기능입니다. 시작을 누르면 마이크 사용 권한을 요청합니다."}
      </p>
      <div className="claw-inbox-status" id="meetingStatus" aria-live="polite" aria-atomic="true">
        {state === "loading" ? <p id="meetingLoading">{t("calendar-loading") || "불러오는 중…"}</p> : null}
        {state === "error" ? (
          <p id="meetingError" role="alert">
            {error}
          </p>
        ) : null}
        {state === "empty" ? (
          <p className="claw-inbox-empty" id="meetingEmpty">
            {t("meeting-records-empty") || "저장된 회의록이 없습니다."}
          </p>
        ) : null}
      </div>
      <ul className="meeting-records" id="meetingRecordsList">
        {meetings.map((meeting) => (
          <li key={meeting.meeting_ref ?? meeting.id ?? meeting.title} className="meeting-record">
            <button type="button" onClick={() => void open(meeting)}>
              {meeting.title}
            </button>
            {meeting.created_at ? <small>{meeting.created_at}</small> : null}
          </li>
        ))}
      </ul>
      {selected ? (
        <section className="meeting-detail" id="meetingDetail" aria-live="polite">
          <h3>{selected.title}</h3>
        </section>
      ) : null}
      <form className="calendar-record-form" id="meetingCreateForm" onSubmit={create}>
        <label className="calendar-record-field" htmlFor="meetingCreateTitle">
          {t("meeting-title") || "회의록"}
          <input
            id="meetingCreateTitle"
            name="title"
            type="text"
            maxLength={200}
            required
            value={title}
            onChange={(event) => setTitle(event.target.value)}
          />
        </label>
        <button className="calendar-record-submit" id="meetingCreateSubmit" type="submit">
          {t("save") || "저장"}
        </button>
        <p className="calendar-record-status" id="meetingCreateStatus" role="status" aria-live="polite" hidden>
          {status}
        </p>
      </form>
    </section>
  );
}
