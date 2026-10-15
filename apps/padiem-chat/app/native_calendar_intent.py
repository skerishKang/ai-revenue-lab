from __future__ import annotations

import re
from datetime import date, timedelta, timezone, datetime
from typing import Any

from .calendar_contracts import validate_timezone

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None

READ_WORDS = ("일정", "스케줄", "약속", "회의")
CREATE_WORDS = ("등록", "추가", "잡아", "잡아줘", "생성", " inequality")

def _today_tz(tz_name: str) -> date:
    return datetime.now(ZoneInfo(tz_name)).date() if ZoneInfo else date.today()

def _parse_date(text: str, tz_name: str) -> tuple[date | None, str]:
    text_low = text.lower()
    today = _today_tz(tz_name)
    if "오늘" in text or "today" in text_low:
        return today, text
    if "내일" in text or "tomorrow" in text_low:
        return today + timedelta(days=1), text
    if "모레" in text:
        return today + timedelta(days=2), text
    if "이번 주" in text or "this week" in text_low:
        monday = today - timedelta(days=today.weekday())
        return monday, text
    if "다음 주" in text or "next week" in text_low:
        monday = today - timedelta(days=today.weekday()) + timedelta(days=7)
        return monday, text
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3))), text
        except ValueError:
            pass
    m = re.search(r"(\d{1,2})월\s*(\d{1,2})일", text)
    if m:
        try:
            # Safe on current year only after confirmation is absent; therefore
            # return None instead of inventing a year for ambiguous month/day.
            return None, text
        except ValueError:
            pass
    weekdays = {"월": 0, "화": 1, "수": 2, "목": 3, "금": 4, "토": 5, "일": 6}
    for word, idx in weekdays.items():
        if word + "요일" in text or re.search(r"\b" + word + r"\b", text):
            base = today - timedelta(days=today.weekday())
            return base + timedelta(days=idx), text
    return None, text

def _time_bounds(text: str) -> tuple[str | None, str | None]:
    hour = None
    minute = "00"
    m = re.search(r"(\d{1,2}):(\d{2})", text)
    if m:
        hour, minute = m.group(1), m.group(2)
    else:
        m = re.search(r"(\d{1,2})\s*시", text)
        if m:
            hour = m.group(1)
    if hour is None:
        return None, None
    hour_int = int(hour)
    if "오후" in text and hour_int < 12:
        hour_int += 12
    if "오전" in text:
        hour_int = hour_int % 12
    iso_time = f"{hour_int:02d}:{minute}:00"
    return iso_time, None

def parse_native_calendar_intent(text: str, *, timezone_name: str | None = None) -> dict:
    answer = {"version": "native-calendar-tool.v1", "op": "none", "args": {}}
    text = text.strip()
    if not any(w in text for w in READ_WORDS + CREATE_WORDS):
        return answer
    is_create = any(w in text for w in ("등록", "추가", "잡아", "생성", "schedule", "book"))
    if timezone_name is None:
        # Explicit timezone only; no server-local inference.
        return {"version": "native-calendar-tool.v1", "op": "clarify",
                "args": {}, "question": "시간대(예: Asia/Seoul)를 먼저 알려주세요."}

    try:
        validate_timezone(timezone_name)
    except Exception:
        return {"version": "native-calendar-tool.v1", "op": "clarify",
                "args": {}, "question": "유효한 IANA 시간대를 알려주세요."}

    today = _today_tz(timezone_name)
    if "이벤트" in text and "이번 주" in text:
        pass

    if is_create:
        parsed_date, _ = _parse_date(text, timezone_name)
        start_time, _ = _time_bounds(text)
        if parsed_date is None:
            return {"version": "native-calendar-tool.v1", "op": "clarify",
                    "args": {}, "question": "일정 날짜를 더 구체적으로 알려주세요."}
        if start_time is None:
            return {"version": "native-calendar-tool.v1", "op": "clarify",
                    "args": {}, "question": "시작 시간을 알려주세요."}
        # title: strip scheduling and date phrases crudely
        title = text
        for phrase in ("일정 등록해줘.", "일정 등록해줘", "등록해줘.", "등록해줘", "추가해줘", "잡아줘", "다음 주 월요일", "다음 주", "이번 주", "내일", "모레", "오늘"):
            title = title.replace(phrase, "")
        title = re.sub(r"\d{1,2}시(?:\s*\d{1,2}분)?", "", title)
        title = re.sub(r"오전|오후", "", title)
        title = re.sub(r"\s+", " ", title).strip(" .")
        if not title:
            return {"version": "native-calendar-tool.v1", "op": "clarify",
                    "args": {}, "question": "일정 제목을 알려주세요."}
        start_iso = f"{parsed_date.isoformat()}T{start_time}+{'+' + '09:00' if False else ''}"
        # preserve supplied timezone offset via zoneinfo identifier in context? adapter needs aware datetime.
        # provide at local no offset concrete using UTC offsets impossible without zone; store offset unknown. Use offset now.
        return {
            "version": "native-calendar-tool.v1",
            "op": "create_appointment",
            "args": {
                "appointment_type": "timed",
                "title": title,
                "date": parsed_date.isoformat(),
                "timezone": timezone_name,
                "start_at": _local_iso(parsed_date, start_time, timezone_name),
            },
        }
    else:
        if "이번 주" in text or "this week" in text.lower():
            start = today - timedelta(days=today.weekday())
            end = start + timedelta(days=6)
        elif "다음 주" in text or "next week" in text.lower():
            start = today - timedelta(days=today.weekday()) + timedelta(days=7)
            end = start + timedelta(days=6)
        else:
            parsed_date, _ = _parse_date(text, timezone_name)
            if parsed_date is None:
                return {"version": "native-calendar-tool.v1", "op": "clarify",
                        "args": {}, "question": "조회할 일정 범위(예: 오늘/이번 주/다음 주)를 알려주세요."}
            start = parsed_date
            end = parsed_date
        return {
            "version": "native-calendar-tool.v1",
            "op": "read",
            "args": {
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "timezone": timezone_name,
            },
        }


def _local_iso(d: date, time_str: str, tz_name: str) -> str:
    try:
        from zoneinfo import ZoneInfo
        dt = datetime.combine(d, datetime.strptime(time_str, "%H:%M:%S").time(), tzinfo=ZoneInfo(tz_name))
        return dt.isoformat()
    except Exception:
        return f"{d.isoformat()}T{time_str}"


def latest_user_text(messages):
    for item in reversed(messages or []):
        if item.get("role") == "user" and isinstance(item.get("content"), str):
            return item["content"].strip()
    return ""


async def try_native_calendar_chat(request, store, uid, messages, timezone_name=None, turn_key=None):
    """Best-effort native Calendar execution for a clearly local calendar request."""
    text = latest_user_text(messages)
    plan = parse_native_calendar_intent(text, timezone_name=timezone_name)
    if plan.get("op") == "none":
        return None
    if plan.get("op") == "clarify":
        return {"answer": plan.get("question", ""), "answer_status": "needs_clarification", "tool": "native_calendar"}

    from .native_calendar_adapter import execute_native_calendar_plan
    import hashlib
    if turn_key is None:
        turn_seed = "|".join(str(v) for v in (uid, text))
        turn_key = "chat-" + hashlib.sha256(turn_seed.encode("utf-8")).hexdigest()[:16]
    result = await execute_native_calendar_plan(request, store, uid, plan, turn_key=turn_key)
    if result.get("operation") == "read":
        items = result.get("items", [])
        if not items:
            answer = f"해당 기간에 저장된 네이티브 일정이 없습니다 ({result['timezone']})."
        else:
            lines = [f"- {item.get('title')} ({item.get('date')} {item.get('start_at') or ''})".strip() for item in items]
            answer = "네이티브 일정 " + str(len(items)) + "건입니다:\n" + "\n".join(lines)
    elif result.get("operation") == "create_appointment":
        apt = result.get("appointment", {})
        answer = "네이티브 일정이 등록되었습니다: " + str(apt.get("title")) + " (" + str(apt.get("date")) + ")"
    else:
        answer = str(result)
    return {"answer": answer, "answer_status": "answered_with_native_calendar", "native_calendar": result}
