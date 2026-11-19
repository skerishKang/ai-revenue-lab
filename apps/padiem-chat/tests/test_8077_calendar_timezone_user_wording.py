"""#8077 — 일정 입력 화면의 시간대 문구는 사용자 말로, 값 형식은 그대로."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

import locale_bundle  # noqa: E402

from app.calendar_contracts import (  # noqa: E402
    AppointmentType,
    CalendarAppointment,
)


def test_calendar_timezone_copy_uses_user_words() -> None:
    ko = locale_bundle.keys("ko")
    en = locale_bundle.keys("en")
    assert ko["calendar-appointment-timezone-label"] == "시간대 (예: Asia/Seoul)"
    assert "직접 골라 주세요" in ko["calendar-appointment-timezone-note"]
    assert "추측" in ko["calendar-appointment-timezone-note"]
    assert en["calendar-appointment-timezone-label"] == "Time zone (e.g. Asia/Seoul)"
    assert "never inferred" in en["calendar-appointment-timezone-note"]


def test_automation_timezone_copy_uses_user_words() -> None:
    ko = locale_bundle.keys("ko")
    en = locale_bundle.keys("en")
    assert ko["claw-automation-create-timezone-label"] == "시간대 (예: Asia/Seoul)"
    assert en["claw-automation-create-timezone-label"] == "Time zone (e.g. Asia/Seoul)"


def test_timezone_value_and_storage_format_stay_unchanged() -> None:
    appointment = CalendarAppointment.create(
        workspace_id="ws_8077", owner_id="owner_8077",
        appointment_type=AppointmentType.TIMED,
        title="미팅", date_val=date(2026, 12, 1),
        start_at=datetime(2026, 12, 1, 10, 0,
                          tzinfo=timezone(timedelta(hours=9))),
        tz_name="Asia/Seoul",
        now=datetime(2026, 11, 19, tzinfo=timezone.utc),
    )
    assert appointment.timezone == "Asia/Seoul"
    assert appointment.start_at is not None
    assert appointment.start_at.utcoffset() == timedelta(0)
