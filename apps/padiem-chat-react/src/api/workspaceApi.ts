/**
 * #5298 — the workspace clients.
 *
 * The library, the automation rules, the calendar and the meeting notes all
 * exist in the product already. The clone reuses their routes, their payloads
 * and their responses; it never invents a second contract.
 */

export interface ApiError {
  code?: string;
  message?: string;
}

async function readError(response: Response, fallback: string): Promise<Error> {
  const data = (await response.json().catch(() => null)) as { error?: ApiError } | null;
  const message =
    data && data.error && typeof data.error.message === "string" ? data.error.message : fallback;
  const error = new Error(message) as Error & { code?: string };
  if (data && data.error && typeof data.error.code === "string") error.code = data.error.code;
  return error;
}

async function readJson<T>(response: Response, fallback: string): Promise<T> {
  if (!response.ok) throw await readError(response, fallback);
  return (await response.json()) as T;
}

/* ---------------------------------------------------------------- library */

export interface LibraryFile {
  id: string;
  name: string;
  project_id: string;
  media_type?: string;
  size_bytes?: number;
  created_at?: string;
}

export interface LibraryPage {
  files: LibraryFile[];
  hasMore: boolean;
  nextCursor: string | null;
}

export async function fetchLibraryFiles(
  cursor: string | null = null,
  signal?: AbortSignal,
): Promise<LibraryPage> {
  const query = new URLSearchParams({ limit: "50" });
  if (cursor) query.set("cursor", cursor);
  const response = await fetch(`/api/project-files?${query.toString()}`, {
    headers: { Accept: "application/json" },
    cache: "no-store",
    signal,
  });
  const data = await readJson<{
    files?: LibraryFile[];
    has_more?: boolean;
    next_cursor?: string | null;
  }>(response, "라이브러리를 불러오지 못했습니다.");
  const files = (data.files ?? []).filter(
    (file) => file && typeof file.id === "string" && typeof file.name === "string",
  );
  return {
    files,
    hasMore: data.has_more === true,
    nextCursor: typeof data.next_cursor === "string" ? data.next_cursor : null,
  };
}

/* ------------------------------------------------------------- automation */

export interface AutomationRule {
  rule_id: string;
  name: string;
  schedule_kind?: string;
  schedule_expression?: string;
  schedule_timezone?: string;
  enabled?: boolean;
  task?: string;
}

export interface AutomationRuleInput {
  name: string;
  task?: string;
  schedule_kind: string;
  schedule_expression: string;
  schedule_timezone: string;
}

export async function fetchAutomationRules(signal?: AbortSignal): Promise<{
  rules: AutomationRule[];
  truncated: boolean;
}> {
  const response = await fetch("/api/claw/automation/rules", {
    headers: { Accept: "application/json" },
    cache: "no-store",
    signal,
  });
  const data = await readJson<{ ok?: boolean; rules?: AutomationRule[]; truncated?: boolean }>(
    response,
    "자동화 규칙을 불러오지 못했습니다.",
  );
  const rules = (data.rules ?? []).filter(
    (rule) => rule && typeof rule.rule_id === "string" && typeof rule.name === "string",
  );
  return { rules, truncated: data.truncated === true };
}

export async function createAutomationRule(
  input: AutomationRuleInput,
): Promise<AutomationRule> {
  const response = await fetch("/api/claw/automation/rules", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(input),
  });
  const data = await readJson<{ rule?: AutomationRule }>(
    response,
    "자동화 규칙을 만들지 못했습니다.",
  );
  if (!data.rule) throw new Error("자동화 규칙을 만들지 못했습니다.");
  return data.rule;
}

export async function updateAutomationRule(
  ruleId: string,
  input: Partial<AutomationRuleInput> & { enabled?: boolean },
): Promise<AutomationRule> {
  const response = await fetch(
    `/api/claw/automation/rules/${encodeURIComponent(ruleId)}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(input),
    },
  );
  const data = await readJson<{ rule?: AutomationRule }>(
    response,
    "자동화 규칙을 수정하지 못했습니다.",
  );
  if (!data.rule) throw new Error("자동화 규칙을 수정하지 못했습니다.");
  return data.rule;
}

export async function deleteAutomationRule(ruleId: string): Promise<void> {
  const response = await fetch(
    `/api/claw/automation/rules/${encodeURIComponent(ruleId)}`,
    { method: "DELETE", headers: { Accept: "application/json" } },
  );
  await readJson<unknown>(response, "자동화 규칙을 삭제하지 못했습니다.");
}

/* --------------------------------------------------------------- calendar */

export type CalendarTab = "today" | "upcoming" | "day" | "week" | "month";

export interface CalendarItem {
  calendar_item_id?: string;
  id?: string;
  title: string;
  date: string;
  start_at?: string | null;
  end_at?: string | null;
  timezone?: string;
  all_day?: boolean;
  kind?: string;
  type?: string;
  description?: string;
}

export interface WorkLogInput {
  date: string;
  title: string;
  content?: string;
}

export interface AppointmentInput {
  title: string;
  date: string;
  timezone: string;
  start_at?: string;
  end_at?: string;
  description?: string;
  reminder_minutes?: number;
}

const CALENDAR_TAB_ROUTES: Record<string, string> = {
  today: "/api/calendar/today",
  upcoming: "/api/calendar/upcoming",
  day: "/api/calendar/items",
  week: "/api/calendar/items",
  month: "/api/calendar/items",
};

export async function fetchCalendarItems(
  tab: CalendarTab,
  range: { startDate?: string; endDate?: string } = {},
  signal?: AbortSignal,
): Promise<CalendarItem[]> {
  const route = CALENDAR_TAB_ROUTES[tab] ?? "/api/calendar/today";
  const query = new URLSearchParams();
  if (range.startDate) query.set("start_date", range.startDate);
  if (range.endDate) query.set("end_date", range.endDate);
  const search = query.toString();
  const response = await fetch(search ? `${route}?${search}` : route, {
    headers: { Accept: "application/json" },
    cache: "no-store",
    signal,
  });
  const data = await readJson<{ items?: CalendarItem[] }>(
    response,
    "캘린더를 불러오지 못했습니다.",
  );
  return (data.items ?? []).filter(
    (item) => item && typeof item.title === "string" && typeof item.date === "string",
  );
}

export async function createCalendarWorkLog(input: WorkLogInput): Promise<void> {
  const response = await fetch("/api/calendar/work-logs", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(input),
  });
  await readJson<unknown>(response, "작업 기록을 저장하지 못했습니다.");
}

export async function deleteCalendarWorkLog(logId: string): Promise<void> {
  const response = await fetch(`/api/calendar/work-logs/${encodeURIComponent(logId)}`, {
    method: "DELETE",
    headers: { Accept: "application/json" },
  });
  await readJson<unknown>(response, "작업 기록을 삭제하지 못했습니다.");
}

export async function createCalendarAppointment(input: AppointmentInput): Promise<void> {
  const response = await fetch("/api/calendar/appointments", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(input),
  });
  await readJson<unknown>(response, "일정을 저장하지 못했습니다.");
}

export async function deleteCalendarAppointment(appointmentId: string): Promise<void> {
  const response = await fetch(
    `/api/calendar/appointments/${encodeURIComponent(appointmentId)}`,
    { method: "DELETE", headers: { Accept: "application/json" } },
  );
  await readJson<unknown>(response, "일정을 삭제하지 못했습니다.");
}

/* --------------------------------------------------------------- meetings */

export interface MeetingSummary {
  meeting_ref?: string;
  id?: string;
  title: string;
  mode?: string;
  created_at?: string;
  status?: string;
}

export interface MeetingDetail {
  meeting: MeetingSummary;
  artifacts: { artifact_id?: string; name?: string; [key: string]: unknown }[];
  actions: { action_ref?: string; kind?: string; [key: string]: unknown }[];
}

function meetingRef(meeting: MeetingSummary): string {
  const ref = meeting.meeting_ref ?? meeting.id;
  if (typeof ref !== "string" || !ref) {
    throw new Error("회의록을 불러오지 못했습니다.");
  }
  return ref;
}

export async function fetchMeetings(signal?: AbortSignal): Promise<MeetingSummary[]> {
  const response = await fetch("/api/claw/meetings", {
    headers: { Accept: "application/json" },
    cache: "no-store",
    signal,
  });
  const data = await readJson<{ meetings?: MeetingSummary[] }>(
    response,
    "회의록을 불러오지 못했습니다.",
  );
  return (data.meetings ?? []).filter(
    (meeting) => meeting && typeof meeting.title === "string",
  );
}

export async function fetchMeeting(
  meeting: MeetingSummary,
  signal?: AbortSignal,
): Promise<MeetingDetail> {
  const ref = meetingRef(meeting);
  const response = await fetch(`/api/claw/meetings/${encodeURIComponent(ref)}`, {
    headers: { Accept: "application/json" },
    cache: "no-store",
    signal,
  });
  const data = await readJson<Partial<MeetingDetail>>(
    response,
    "회의록을 불러오지 못했습니다.",
  );
  return {
    meeting: data.meeting ?? meeting,
    artifacts: Array.isArray(data.artifacts) ? data.artifacts : [],
    actions: Array.isArray(data.actions) ? data.actions : [],
  };
}

export async function createMeeting(input: {
  title: string;
  mode?: string;
}): Promise<MeetingSummary> {
  const response = await fetch("/api/claw/meetings", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ title: input.title, mode: input.mode ?? "note" }),
  });
  const data = await readJson<{ meeting?: MeetingSummary }>(
    response,
    "회의록을 만들지 못했습니다.",
  );
  if (!data.meeting) throw new Error("회의록을 만들지 못했습니다.");
  return data.meeting;
}
