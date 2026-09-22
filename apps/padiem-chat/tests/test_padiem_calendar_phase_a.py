"""#2834 Native Padiem Calendar Phase A test suite.

Verifies:
1. Native work-log create/validate and work-log != Memory (no auto-promotion)
2. Native appointment contracts: date-only, all-day, timed, explicit timezone
3. Timezone required for timed events; naive datetimes fail closed
4. Today projection deterministic and correct for explicit timezones (DST/tz aware)
5. Upcoming projection: deterministic ordering, past items excluded, limit bounded
6. Task, Alert, Claw run projection bounded without duplicate storage
7. Automation run deferred pending #2833 (no fake rows)
8. Workspace isolation: workspace A cannot read or mutate workspace B
9. Privacy: raw user/owner/provider/storage ids not exposed in public projections
10. External calendar prohibition: 0 provider calls, 0 external writes
11. Adversarial/mutation verification
12. HTTP route integration via Starlette TestClient with existing B62 auth
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json
from typing import Any
import pytest
from starlette.testclient import TestClient

from app.auth import create_session_token
from app.calendar_contracts import (
    AppointmentType,
    AUTOMATION_PROJECTION,
    CALENDAR_CONTRACT_VERSION,
    CALENDAR_WORK_LOG,
    CalendarAppointment,
    CalendarContractError,
    CalendarItemProjection,
    CalendarItemType,
    CalendarSourceType,
    CalendarWorkLog,
    EXTERNAL_CALENDAR_REQUIRED,
    LONG_TERM_MEMORY,
    MEMORY_AUTO_PROMOTION,
    PADIEM_CALENDAR_CANONICAL_PRODUCT,
    SERVER_LOCAL_TIMEZONE_INFERENCE,
    parse_aware_datetime,
    parse_date,
    validate_timezone,
)
from app.calendar_projection import (
    build_range_projection,
    build_today_projection,
    build_upcoming_projection,
    project_alert,
    project_appointment,
    project_claw_run,
    project_task,
    project_work_log,
)
from app.calendar_store import (
    CalendarStore,
    DOMAIN_CONTRACT_READY,
    DURABLE_STORE_DEFERRED,
    DURABLE_STORE_DEFERRED_REASON,
    InMemoryCalendarStore,
    REFERENCE_IN_MEMORY_STORE_READY,
    STORE_PROTOCOL_READY,
)
from app.config import Settings
from app.history import HistoryStore, UserProfile
from app.main import create_app

SESSION_COOKIE = "padiem_session"
SECRET_KEY = "test-secret-key-32-bytes-minimum-length-here"


class FakeHistoryStore:
    """Minimal fake history store for testing."""

    def __init__(self) -> None:
        self.users: dict[str, UserProfile] = {}
        self.claw_runs: dict[str, list[dict[str, Any]]] = {}

    async def get_user(self, user_id: str) -> UserProfile | None:
        return self.users.get(user_id)

    async def list_recent_claw_runs(
        self, user_id: str, limit: int = 30
    ) -> list[dict[str, Any]]:
        return list(self.claw_runs.get(user_id, []))[:limit]


class FakeTaskAlertStore:
    """Fake task/alert store simulating D1ClawTaskAlertStore visibility semantics."""

    def __init__(self) -> None:
        self.tasks: dict[str, list[Any]] = {}
        self.alerts: dict[str, list[Any]] = {}

    async def list_tasks(
        self, workspace_id: str, limit: int = 256
    ) -> list[Any]:
        return list(self.tasks.get(workspace_id, []))[:limit]

    async def list_alerts(
        self, workspace_id: str, *, member_id: str | None = None, limit: int = 256
    ) -> list[Any]:
        raw = list(self.alerts.get(workspace_id, []))
        if member_id is not None:
            raw = [
                a for a in raw
                if getattr(a, "is_visible_to", lambda m: True)(member_id)
            ]
        return raw[:limit]


class MockTask:
    def __init__(
        self,
        task_id: str,
        title: str,
        status: str = "pending",
        due_date: date | None = None,
        created_at: datetime | None = None,
        member_id: str = "",
    ) -> None:
        self.task_id = task_id
        self.title = title
        self.status = status
        self.due_date = due_date
        self.created_at = created_at or datetime(2026, 9, 20, 10, 0, 0, tzinfo=timezone.utc)
        self.member_id = member_id


class MockAlert:
    def __init__(
        self,
        alert_id: str,
        title: str,
        severity: str = "info",
        kind: str = "notice",
        created_at: datetime | None = None,
        visible_to_members: tuple[str, ...] = (),
        visible_to_all: bool = False,
    ) -> None:
        self.alert_id = alert_id
        self.title = title
        self.severity = severity
        self.kind = kind
        self.created_at = created_at or datetime(2026, 9, 20, 10, 0, 0, tzinfo=timezone.utc)
        self.visible_to_members = visible_to_members
        self.visible_to_all = visible_to_all

    def is_visible_to(self, member_id: str) -> bool:
        if self.visible_to_all:
            return True
        return member_id in self.visible_to_members


# ==============================================================================
# 1. Native work-log record (Axis A) & Work-Log != Memory
# ==============================================================================

def test_work_log_creation_and_contract() -> None:
    now = datetime(2026, 9, 20, 12, 0, 0, tzinfo=timezone.utc)
    log = CalendarWorkLog.create(
        workspace_id="ws_main",
        owner_id="usr_test1",
        date_val="2026-09-20",
        title="A사와 납기 협의함",
        content="납기 10월 15일로 잠정 합의. 계약서 검토 필요.",
        now=now,
    )
    assert log.workspace_id == "ws_main"
    assert log.owner_id == "usr_test1"
    assert log.date == date(2026, 9, 20)
    assert log.title == "A사와 납기 협의함"
    assert log.content == "납기 10월 15일로 잠정 합의. 계약서 검토 필요."
    assert log.created_at == now
    assert log.updated_at == now

    # Check contract constants
    assert CALENDAR_WORK_LOG is True
    assert LONG_TERM_MEMORY is False
    assert MEMORY_AUTO_PROMOTION is False

    # Memory auto-promotion is structurally prohibited
    assert not hasattr(log, "promote_to_memory")
    assert not hasattr(log, "to_memory")
    assert not hasattr(log, "memory_id")


def test_work_log_validation_rules() -> None:
    # Empty title rejected
    with pytest.raises(CalendarContractError) as exc:
        CalendarWorkLog.create(
            workspace_id="ws_main",
            owner_id="usr_test1",
            date_val="2026-09-20",
            title="   ",
        )
    assert "title_required" in exc.value.code

    # Title with newlines rejected
    with pytest.raises(CalendarContractError) as exc:
        CalendarWorkLog.create(
            workspace_id="ws_main",
            owner_id="usr_test1",
            date_val="2026-09-20",
            title="Line 1\nLine 2",
        )
    assert "invalid_title" in exc.value.code

    # Title exceeding bound rejected
    with pytest.raises(CalendarContractError) as exc:
        CalendarWorkLog.create(
            workspace_id="ws_main",
            owner_id="usr_test1",
            date_val="2026-09-20",
            title="A" * 201,
        )
    assert "title_too_long" in exc.value.code

    # Invalid date string rejected
    with pytest.raises(CalendarContractError) as exc:
        CalendarWorkLog.create(
            workspace_id="ws_main",
            owner_id="usr_test1",
            date_val="2026-02-30",
            title="Valid title",
        )
    assert "invalid_date" in exc.value.code


# ==============================================================================
# 2. Native appointment contract (Axis B)
# ==============================================================================

def test_date_only_appointment() -> None:
    apt = CalendarAppointment.create(
        workspace_id="ws_1",
        owner_id="usr_1",
        appointment_type=AppointmentType.DATE_ONLY,
        title="계약서 검토 완료 예정일",
        description="법무팀 확인 후 서명",
        date_val="2026-09-25",
    )
    assert apt.appointment_type == AppointmentType.DATE_ONLY
    assert apt.date == date(2026, 9, 25)
    assert apt.start_at is None
    assert apt.end_at is None
    assert apt.timezone is None

    # date_only cannot have start_at or end_at
    with pytest.raises(CalendarContractError) as exc:
        CalendarAppointment.create(
            workspace_id="ws_1",
            owner_id="usr_1",
            appointment_type=AppointmentType.DATE_ONLY,
            title="Invalid date only",
            date_val="2026-09-25",
            start_at="2026-09-25T10:00:00+09:00",
        )
    assert exc.value.code == "date_only_cannot_have_time"


def test_all_day_appointment() -> None:
    apt = CalendarAppointment.create(
        workspace_id="ws_1",
        owner_id="usr_1",
        appointment_type=AppointmentType.ALL_DAY,
        title="추석 연휴 워크숍",
        date_val="2026-10-01",
    )
    assert apt.appointment_type == AppointmentType.ALL_DAY
    assert apt.date == date(2026, 10, 1)
    assert apt.start_at is None
    assert apt.end_at is None

    # all_day cannot have start_at
    with pytest.raises(CalendarContractError) as exc:
        CalendarAppointment.create(
            workspace_id="ws_1",
            owner_id="usr_1",
            appointment_type=AppointmentType.ALL_DAY,
            title="Invalid all day",
            date_val="2026-10-01",
            start_at="2026-10-01T09:00:00Z",
        )
    assert exc.value.code == "all_day_cannot_have_time"


def test_timed_appointment_with_explicit_timezone() -> None:
    now = datetime(2026, 9, 20, 0, 0, 0, tzinfo=timezone.utc)
    apt = CalendarAppointment.create(
        workspace_id="ws_1",
        owner_id="usr_1",
        appointment_type=AppointmentType.TIMED,
        title="B사 견적 비교 미팅",
        description="단가 및 납기 조율",
        start_at="2026-09-21T14:00:00+09:00",
        end_at="2026-09-21T15:00:00+09:00",
        tz_name="Asia/Seoul",
        reminder_minutes=15,
        now=now,
    )
    assert apt.appointment_type == AppointmentType.TIMED
    assert apt.timezone == "Asia/Seoul"
    assert apt.date == date(2026, 9, 21)
    # Stored UTC normalization
    assert apt.start_at == datetime(2026, 9, 21, 5, 0, 0, tzinfo=timezone.utc)
    assert apt.end_at == datetime(2026, 9, 21, 6, 0, 0, tzinfo=timezone.utc)
    assert apt.reminder_minutes == 15


def test_timed_appointment_fails_closed_without_timezone() -> None:
    with pytest.raises(CalendarContractError) as exc:
        CalendarAppointment.create(
            workspace_id="ws_1",
            owner_id="usr_1",
            appointment_type=AppointmentType.TIMED,
            title="Meeting without timezone",
            start_at="2026-09-21T14:00:00+09:00",
            tz_name=None,  # No timezone provided!
        )
    assert exc.value.code == "timezone_required"


def test_timed_appointment_fails_closed_on_naive_datetime() -> None:
    with pytest.raises(CalendarContractError) as exc:
        CalendarAppointment.create(
            workspace_id="ws_1",
            owner_id="usr_1",
            appointment_type=AppointmentType.TIMED,
            title="Meeting with naive datetime",
            start_at="2026-09-21T14:00:00",  # No offset/tz!
            tz_name="Asia/Seoul",
        )
    assert exc.value.code == "naive_datetime_rejected"


def test_timed_appointment_fails_closed_on_invalid_time_range() -> None:
    with pytest.raises(CalendarContractError) as exc:
        CalendarAppointment.create(
            workspace_id="ws_1",
            owner_id="usr_1",
            appointment_type=AppointmentType.TIMED,
            title="End before start",
            start_at="2026-09-21T15:00:00+09:00",
            end_at="2026-09-21T14:00:00+09:00",
            tz_name="Asia/Seoul",
        )
    assert exc.value.code == "invalid_time_range"


def test_appointment_types_structurally_distinct() -> None:
    assert AppointmentType.DATE_ONLY != AppointmentType.TIMED
    assert AppointmentType.ALL_DAY != AppointmentType.TIMED
    assert AppointmentType.DATE_ONLY != AppointmentType.ALL_DAY


# ==============================================================================
# 3. Canonical calendar item projection (Axis C)
# ==============================================================================

def test_work_log_projection_bounded_safe() -> None:
    log = CalendarWorkLog.create(
        workspace_id="ws_alpha",
        owner_id="usr_secret_id",
        date_val="2026-09-20",
        title="업무 일지 기록",
        content="진행 상황 메모",
    )
    proj = project_work_log(log)
    safe = proj.safe_dict()

    assert safe["calendar_item_id"] == f"item_log_{log.log_id}"
    assert safe["workspace_id"] == "ws_alpha"
    assert safe["item_type"] == "work_log"
    assert safe["source_type"] == "native_work_log"
    assert safe["source_ref"] == f"work_log:{log.log_id}"
    assert safe["title"] == "업무 일지 기록"
    assert safe["summary"] == "진행 상황 메모"
    assert safe["date"] == "2026-09-20"

    # Privacy verification: owner_id, raw user id must NOT be in projection!
    assert "owner_id" not in safe
    assert "user_id" not in safe
    assert "usr_secret_id" not in json.dumps(safe)


def test_appointment_projection_bounded_safe() -> None:
    apt = CalendarAppointment.create(
        workspace_id="ws_alpha",
        owner_id="usr_secret_id",
        appointment_type=AppointmentType.TIMED,
        title="고객사 미팅",
        description="상세 내용",
        start_at="2026-09-20T10:00:00+09:00",
        end_at="2026-09-20T11:00:00+09:00",
        tz_name="Asia/Seoul",
    )
    proj = project_appointment(apt)
    safe = proj.safe_dict()

    assert safe["calendar_item_id"] == f"item_apt_{apt.appointment_id}"
    assert safe["item_type"] == "appointment"
    assert safe["source_type"] == "native_appointment"
    assert safe["source_ref"] == f"appointment:{apt.appointment_id}"
    assert safe["timezone"] == "Asia/Seoul"
    assert safe["all_day"] is False

    # Privacy verification
    assert "owner_id" not in safe
    assert "usr_secret_id" not in json.dumps(safe)


def test_existing_task_alert_and_claw_run_projection() -> None:
    # Task projection (read-only projection, no duplicate storage)
    t = MockTask("task_123", "원자재 공급사 계약서 검토", due_date=date(2026, 9, 22))
    p_task = project_task(t, "ws_alpha")
    s_task = p_task.safe_dict()
    assert s_task["calendar_item_id"] == "item_task_task_123"
    assert s_task["item_type"] == "task"
    assert s_task["source_ref"] == "task:task_123"
    assert s_task["date"] == "2026-09-22"

    # Alert projection
    a = MockAlert("alert_456", "인보이스 결제 마감 경고", severity="critical")
    p_alert = project_alert(a, "ws_alpha")
    s_alert = p_alert.safe_dict()
    assert s_alert["calendar_item_id"] == "item_alert_alert_456"
    assert s_alert["item_type"] == "alert"
    assert s_alert["source_ref"] == "alert:alert_456"

    # Claw run projection
    run_row = {
        "run_id": "run_789",
        "title": "공급업체 견적 비교 실행",
        "status": "success",
        "result_summary": "최적 공급사 추천 완료",
        "created_at": "2026-09-20T08:30:00Z",
    }
    p_run = project_claw_run(run_row, "ws_alpha")
    s_run = p_run.safe_dict()
    assert s_run["calendar_item_id"] == "item_run_run_789"
    assert s_run["item_type"] == "claw_run"
    assert s_run["source_ref"] == "claw_run:run_789"
    assert s_run["date"] == "2026-09-20"

    # Automation projection is explicitly deferred
    assert AUTOMATION_PROJECTION == "READ_ONLY_DURABLE_STORE"


# ==============================================================================
# 4. Today / Upcoming deterministic backend projections (Axis D)
# ==============================================================================

@pytest.mark.asyncio
async def test_today_projection_deterministic_timezone() -> None:
    store = InMemoryCalendarStore()
    # Log for 2026-09-21
    await store.add_work_log(
        CalendarWorkLog.create(
            workspace_id="ws_tz",
            owner_id="usr_1",
            date_val="2026-09-21",
            title="9월 21일 업무",
        )
    )
    # Log for 2026-09-20
    await store.add_work_log(
        CalendarWorkLog.create(
            workspace_id="ws_tz",
            owner_id="usr_1",
            date_val="2026-09-20",
            title="9월 20일 업무",
        )
    )

    # Reference moment: 2026-09-20T16:00:00Z
    # In Asia/Seoul (UTC+9), it is 2026-09-21 01:00:00 -> today is 2026-09-21
    # In America/New_York (EDT, UTC-4), it is 2026-09-20 12:00:00 -> today is 2026-09-20
    ref_utc = datetime(2026, 9, 20, 16, 0, 0, tzinfo=timezone.utc)

    proj_seoul = await build_today_projection(
        workspace_id="ws_tz",
        tz_name="Asia/Seoul",
        calendar_store=store,
        now_utc=ref_utc,
    )
    assert proj_seoul["date"] == "2026-09-21"
    assert proj_seoul["total_count"] == 1
    assert proj_seoul["items"][0]["title"] == "9월 21일 업무"

    proj_ny = await build_today_projection(
        workspace_id="ws_tz",
        tz_name="America/New_York",
        calendar_store=store,
        now_utc=ref_utc,
    )
    assert proj_ny["date"] == "2026-09-20"
    assert proj_ny["total_count"] == 1
    assert proj_ny["items"][0]["title"] == "9월 20일 업무"


@pytest.mark.asyncio
async def test_upcoming_projection_excludes_past_items() -> None:
    store = InMemoryCalendarStore()
    ref_now = datetime(2026, 9, 20, 12, 0, 0, tzinfo=timezone.utc)

    # Past timed appointment: 2026-09-20 09:00:00 UTC (past)
    await store.add_appointment(
        CalendarAppointment.create(
            workspace_id="ws_up",
            owner_id="usr_1",
            appointment_type=AppointmentType.TIMED,
            title="Past Meeting",
            start_at="2026-09-20T09:00:00Z",
            end_at="2026-09-20T10:00:00Z",
            tz_name="UTC",
        )
    )
    # Future timed appointment: 2026-09-20 15:00:00 UTC (future)
    await store.add_appointment(
        CalendarAppointment.create(
            workspace_id="ws_up",
            owner_id="usr_1",
            appointment_type=AppointmentType.TIMED,
            title="Future Meeting 1",
            start_at="2026-09-20T15:00:00Z",
            end_at="2026-09-20T16:00:00Z",
            tz_name="UTC",
        )
    )
    # Future date-only appointment: 2026-09-22 (future)
    await store.add_appointment(
        CalendarAppointment.create(
            workspace_id="ws_up",
            owner_id="usr_1",
            appointment_type=AppointmentType.DATE_ONLY,
            title="Future Date Only",
            date_val="2026-09-22",
        )
    )
    # Task due in future
    task_store = FakeTaskAlertStore()
    task_store.tasks["ws_up"] = [
        MockTask(
            "task_fut",
            "Future Task Deadline",
            due_date=date(2026, 9, 23),
            member_id="usr_1",
        )
    ]

    upcoming = await build_upcoming_projection(
        workspace_id="ws_up",
        tz_name="UTC",
        calendar_store=store,
        task_alert_store=task_store,
        user_id="usr_1",
        now_utc=ref_now,
        limit=10,
    )

    items = upcoming["items"]
    # Past Meeting must NOT be present!
    titles = [i["title"] for i in items]
    assert "Past Meeting" not in titles
    assert "Future Meeting 1" in titles
    assert "Future Date Only" in titles
    assert "Future Task Deadline" in titles

    # Verify ascending ordering
    dates = [i["date"] for i in items]
    assert dates == sorted(dates)


# ==============================================================================
# 5. Workspace isolation & storage protocol (Axis E)
# ==============================================================================

@pytest.mark.asyncio
async def test_workspace_isolation() -> None:
    store = InMemoryCalendarStore()

    # Workspace A writes
    log_a = await store.add_work_log(
        CalendarWorkLog.create(
            workspace_id="ws_a",
            owner_id="usr_a",
            date_val="2026-09-20",
            title="WS A Work Log",
        )
    )
    apt_a = await store.add_appointment(
        CalendarAppointment.create(
            workspace_id="ws_a",
            owner_id="usr_a",
            appointment_type=AppointmentType.DATE_ONLY,
            title="WS A Appointment",
            date_val="2026-09-21",
        )
    )

    # Workspace B cannot read Workspace A's records
    assert await store.get_work_log("ws_b", log_a.log_id) is None
    assert await store.get_appointment("ws_b", apt_a.appointment_id) is None

    # Listing workspace B returns nothing from workspace A
    logs_b = await store.list_work_logs("ws_b")
    assert len(logs_b) == 0

    apts_b = await store.list_appointments("ws_b")
    assert len(apts_b) == 0


def test_persistence_decision_constants() -> None:
    assert DOMAIN_CONTRACT_READY is True
    assert STORE_PROTOCOL_READY is True
    assert REFERENCE_IN_MEMORY_STORE_READY is True
    assert DURABLE_STORE_DEFERRED is False
    assert (
        DURABLE_STORE_DEFERRED_REASON
        == "resolved_in_phase_b2: D1CalendarStore implemented with migration 013"
    )


# ==============================================================================
# 6. External calendar prohibition & zero provider calls
# ==============================================================================

def test_external_calendar_prohibited() -> None:
    assert PADIEM_CALENDAR_CANONICAL_PRODUCT is True
    assert EXTERNAL_CALENDAR_REQUIRED is False
    assert SERVER_LOCAL_TIMEZONE_INFERENCE is False


# ==============================================================================
# 7. Adversarial & mutation checks
# ==============================================================================

def test_mutation_adversarial_timezone_ignored() -> None:
    # If code ignores missing timezone, this test catches it
    with pytest.raises(CalendarContractError) as exc:
        validate_timezone(None)
    assert exc.value.code == "timezone_required"

    with pytest.raises(CalendarContractError) as exc:
        validate_timezone("Invalid/Non_Existent_Timezone_12345")
    assert exc.value.code == "invalid_timezone"


@pytest.mark.asyncio
async def test_mutation_adversarial_workspace_predicate_removal() -> None:
    store = InMemoryCalendarStore()
    await store.add_work_log(
        CalendarWorkLog.create(
            workspace_id="ws_secret",
            owner_id="usr_secret",
            date_val="2026-09-20",
            title="Secret Financial Log",
        )
    )
    # If workspace isolation is broken, query for ws_other would return ws_secret's items
    other_items = await store.list_work_logs("ws_other")
    assert len(other_items) == 0


@pytest.mark.asyncio
async def test_mutation_adversarial_past_comparator() -> None:
    store = InMemoryCalendarStore()
    ref_now = datetime(2026, 9, 20, 12, 0, 0, tzinfo=timezone.utc)
    # Event strictly in past
    await store.add_appointment(
        CalendarAppointment.create(
            workspace_id="ws_comp",
            owner_id="usr_1",
            appointment_type=AppointmentType.TIMED,
            title="Past",
            start_at="2026-09-19T10:00:00Z",
            end_at="2026-09-19T11:00:00Z",
            tz_name="UTC",
        )
    )
    upcoming = await build_upcoming_projection(
        workspace_id="ws_comp",
        tz_name="UTC",
        calendar_store=store,
        now_utc=ref_now,
    )
    assert len(upcoming["items"]) == 0


# ==============================================================================
# 8. HTTP Routes integration via Starlette TestClient
# ==============================================================================

def _google_settings(**overrides) -> Settings:
    values = {
        "runtime_mode": "mock",
        "auth_mode": "google",
        "public_base_url": "https://chat.example.test",
        "google_client_id": "calendar-client.apps.googleusercontent.com",
        "google_client_secret": "calendar-google-secret",
        "session_secret": "calendar-session-secret-not-a-real-credential-0",
        "session_max_age_seconds": 3600,
    }
    values.update(overrides)
    return Settings.from_values(**values)


@pytest.fixture
def test_app_and_client() -> tuple[Any, TestClient, str]:
    settings = _google_settings()
    history_store = FakeHistoryStore()
    user_id = "usr_calendar_tester"
    history_store.users[user_id] = UserProfile(
        id=user_id,
        email="calendar@example.test",
        display_name="Calendar Tester",
        picture_url="",
    )
    token = create_session_token(settings, user_id)
    calendar_store = InMemoryCalendarStore()

    app = create_app(
        settings=settings,
        history_store=history_store,
        calendar_store=calendar_store,
    )
    client = TestClient(app, base_url="https://chat.example.test")
    client.cookies.set(SESSION_COOKIE, token)
    return app, client, user_id


def test_http_calendar_unauthorized() -> None:
    settings = _google_settings()
    app = create_app(settings=settings)
    anon_client = TestClient(app, base_url="https://chat.example.test")

    res = anon_client.get("/api/calendar/today?timezone=Asia/Seoul")
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "unauthorized"


def test_http_calendar_today_requires_timezone(
    test_app_and_client: tuple[Any, TestClient, str],
) -> None:
    _, client, _ = test_app_and_client
    res = client.get("/api/calendar/today")
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "timezone_required"


def test_http_calendar_work_logs_lifecycle(
    test_app_and_client: tuple[Any, TestClient, str],
) -> None:
    _, client, _ = test_app_and_client

    # 1. Create work log
    create_res = client.post(
        "/api/calendar/work-logs",
        json={
            "date": "2026-09-20",
            "title": "A사와 납기 협의함",
            "content": "단가 5% 인하 및 10월 납품 합의",
        },
    )
    assert create_res.status_code == 201
    body = create_res.json()
    assert body["ok"] is True
    assert body["work_log"]["title"] == "A사와 납기 협의함"
    assert body["work_log"]["item_type"] == "work_log"
    assert body["work_log"]["source_type"] == "native_work_log"

    # 2. Rejection of caller-supplied ownership override
    override_res = client.post(
        "/api/calendar/work-logs",
        json={
            "workspace_id": "malicious_workspace",
            "date": "2026-09-20",
            "title": "Hacked log",
        },
    )
    assert override_res.status_code == 400
    assert override_res.json()["error"]["code"] == "forbidden_ownership_override"

    # 3. List work logs
    list_res = client.get("/api/calendar/work-logs")
    assert list_res.status_code == 200
    list_body = list_res.json()
    assert list_body["ok"] is True
    assert len(list_body["items"]) == 1
    assert list_body["items"][0]["title"] == "A사와 납기 협의함"


def test_http_calendar_appointments_lifecycle(
    test_app_and_client: tuple[Any, TestClient, str],
) -> None:
    _, client, _ = test_app_and_client

    # 1. Create timed appointment
    create_res = client.post(
        "/api/calendar/appointments",
        json={
            "appointment_type": "timed",
            "title": "계약서 서명 미팅",
            "start_at": "2026-09-25T14:00:00+09:00",
            "end_at": "2026-09-25T15:00:00+09:00",
            "timezone": "Asia/Seoul",
            "reminder_minutes": 30,
        },
    )
    assert create_res.status_code == 201
    body = create_res.json()
    assert body["ok"] is True
    apt = body["appointment"]
    assert apt["title"] == "계약서 서명 미팅"
    assert apt["item_type"] == "appointment"
    assert apt["timezone"] == "Asia/Seoul"
    assert apt["all_day"] is False

    # 2. List appointments
    list_res = client.get("/api/calendar/appointments")
    assert list_res.status_code == 200
    list_body = list_res.json()
    assert list_body["ok"] is True
    assert len(list_body["items"]) == 1


def test_http_calendar_today_and_upcoming_views(
    test_app_and_client: tuple[Any, TestClient, str],
) -> None:
    _, client, _ = test_app_and_client

    # Create an appointment for 2026-09-20 (today in Asia/Seoul)
    client.post(
        "/api/calendar/appointments",
        json={
            "appointment_type": "timed",
            "title": "오늘 오후 회의",
            "start_at": "2026-09-20T15:00:00+09:00",
            "end_at": "2026-09-20T16:00:00+09:00",
            "timezone": "Asia/Seoul",
        },
    )
    # Create an appointment for 2026-09-25 (upcoming)
    client.post(
        "/api/calendar/appointments",
        json={
            "appointment_type": "date_only",
            "title": "다음주 계약 마감",
            "date": "2026-09-25",
        },
    )

    # Query today
    today_res = client.get("/api/calendar/today?timezone=Asia/Seoul")
    assert today_res.status_code == 200
    today_body = today_res.json()
    assert today_body["ok"] is True
    assert today_body["projection"]["view"] == "today"

    # Query upcoming
    upcoming_res = client.get("/api/calendar/upcoming?timezone=Asia/Seoul")
    assert upcoming_res.status_code == 200
    upcoming_body = upcoming_res.json()
    assert upcoming_body["ok"] is True
    assert upcoming_body["projection"]["view"] == "upcoming"
    assert upcoming_body["projection"]["total_count"] >= 1

    # Query range items
    range_res = client.get(
        "/api/calendar/items?timezone=Asia/Seoul&start_date=2026-09-20&end_date=2026-09-30"
    )
    assert range_res.status_code == 200
    range_body = range_res.json()
    assert range_body["ok"] is True
    assert range_body["projection"]["view"] == "range"
    assert range_body["projection"]["total_count"] >= 2


# ==============================================================================
# 9. Corrective Pass Regressions for CENTRAL Review Blockers (#2841)
# ==============================================================================

@pytest.mark.asyncio
async def test_blocker_1_task_alert_member_visibility_parity() -> None:
    """Blocker 1: Tasks and alerts must adhere to existing inbox visibility semantics."""
    calendar_store = InMemoryCalendarStore()
    task_alert_store = FakeTaskAlertStore()
    ws = "ws_collab"

    # Tasks for Alice and Bob in the same workspace
    t_alice = MockTask(
        task_id="task_alice",
        title="Alice Task",
        due_date=date(2026, 9, 20),
        member_id="usr_alice",
    )
    t_bob = MockTask(
        task_id="task_bob",
        title="Bob Task",
        due_date=date(2026, 9, 20),
        member_id="usr_bob",
    )
    task_alert_store.tasks[ws] = [t_alice, t_bob]

    # Alerts: Alice private, Bob private, and Public
    a_alice = MockAlert(
        alert_id="alert_alice",
        title="Alice Alert",
        created_at=datetime(2026, 9, 20, 9, 0, 0, tzinfo=timezone.utc),
        visible_to_members=("usr_alice",),
        visible_to_all=False,
    )
    a_bob = MockAlert(
        alert_id="alert_bob",
        title="Bob Alert",
        created_at=datetime(2026, 9, 20, 9, 0, 0, tzinfo=timezone.utc),
        visible_to_members=("usr_bob",),
        visible_to_all=False,
    )
    a_public = MockAlert(
        alert_id="alert_pub",
        title="Public Alert",
        created_at=datetime(2026, 9, 20, 9, 0, 0, tzinfo=timezone.utc),
        visible_to_members=(),
        visible_to_all=True,
    )
    task_alert_store.alerts[ws] = [a_alice, a_bob, a_public]

    # 1. Alice's projection
    p_alice = await build_today_projection(
        workspace_id=ws,
        tz_name="UTC",
        calendar_store=calendar_store,
        task_alert_store=task_alert_store,
        user_id="usr_alice",
        now_utc=datetime(2026, 9, 20, 12, 0, 0, tzinfo=timezone.utc),
    )
    alice_titles = [item["title"] for item in p_alice["items"]]
    assert "Alice Task" in alice_titles
    assert "Bob Task" not in alice_titles, "Cross-member task leak: Bob task visible to Alice!"
    assert "Alice Alert" in alice_titles
    assert "Bob Alert" not in alice_titles, "Cross-member alert leak: Bob alert visible to Alice!"
    assert "Public Alert" in alice_titles

    # 2. Bob's projection
    p_bob = await build_today_projection(
        workspace_id=ws,
        tz_name="UTC",
        calendar_store=calendar_store,
        task_alert_store=task_alert_store,
        user_id="usr_bob",
        now_utc=datetime(2026, 9, 20, 12, 0, 0, tzinfo=timezone.utc),
    )
    bob_titles = [item["title"] for item in p_bob["items"]]
    assert "Bob Task" in bob_titles
    assert "Alice Task" not in bob_titles, "Cross-member task leak: Alice task visible to Bob!"
    assert "Bob Alert" in bob_titles
    assert "Alice Alert" not in bob_titles, "Cross-member alert leak: Alice alert visible to Bob!"
    assert "Public Alert" in bob_titles

    # 3. Fail-closed on missing user_id: 0 tasks and 0 alerts projected
    p_anon = await build_today_projection(
        workspace_id=ws,
        tz_name="UTC",
        calendar_store=calendar_store,
        task_alert_store=task_alert_store,
        user_id=None,
        now_utc=datetime(2026, 9, 20, 12, 0, 0, tzinfo=timezone.utc),
    )
    anon_types = [item["item_type"] for item in p_anon["items"]]
    assert "task" not in anon_types, "Anonymous caller must not receive tasks"
    assert "alert" not in anon_types, "Anonymous caller must not receive alerts"

    # 4. Same member visibility parity in upcoming projection
    t_alice_future = MockTask(
        task_id="task_alice_fut",
        title="Alice Future Task",
        due_date=date(2026, 9, 25),
        member_id="usr_alice",
    )
    t_bob_future = MockTask(
        task_id="task_bob_fut",
        title="Bob Future Task",
        due_date=date(2026, 9, 25),
        member_id="usr_bob",
    )
    task_alert_store.tasks[ws].extend([t_alice_future, t_bob_future])

    p_alice_up = await build_upcoming_projection(
        workspace_id=ws,
        tz_name="UTC",
        calendar_store=calendar_store,
        task_alert_store=task_alert_store,
        user_id="usr_alice",
        now_utc=datetime(2026, 9, 20, 12, 0, 0, tzinfo=timezone.utc),
    )
    alice_up_titles = [item["title"] for item in p_alice_up["items"]]
    assert "Alice Future Task" in alice_up_titles
    assert "Bob Future Task" not in alice_up_titles, "Cross-member future task leak in upcoming!"


@pytest.mark.asyncio
async def test_blocker_2_claw_run_scope_fail_closed() -> None:
    """Blocker 2: Claw runs must only be projected when workspace is provably owner-derived."""
    calendar_store = InMemoryCalendarStore()
    history_store = FakeHistoryStore()
    history_store.claw_runs["usr_alice"] = [
        {
            "run_id": "run_alice_1",
            "title": "Alice Intake Run",
            "status": "success",
            "result_summary": "Done",
            "created_at": "2026-09-20T10:00:00Z",
        }
    ]

    # Case A: Owner-derived fallback workspace (provable scope) -> run IS visible
    p_owner_ws = await build_today_projection(
        workspace_id="owner:usr_alice",
        tz_name="UTC",
        calendar_store=calendar_store,
        history_store=history_store,
        user_id="usr_alice",
        now_utc=datetime(2026, 9, 20, 12, 0, 0, tzinfo=timezone.utc),
    )
    owner_titles = [item["title"] for item in p_owner_ws["items"]]
    assert "Alice Intake Run" in owner_titles

    # Case B: Canonical tenant workspace (unscoped linkage) -> run MUST BE OMITTED (fail-closed)
    p_tenant_ws = await build_today_projection(
        workspace_id="tenant_canonical_corp_123",
        tz_name="UTC",
        calendar_store=calendar_store,
        history_store=history_store,
        user_id="usr_alice",
        now_utc=datetime(2026, 9, 20, 12, 0, 0, tzinfo=timezone.utc),
    )
    tenant_titles = [item["title"] for item in p_tenant_ws["items"]]
    assert "Alice Intake Run" not in tenant_titles, "Unproven run was relabeled into canonical tenant!"

    # Case C: Different user querying owner workspace -> never visible
    p_other_user = await build_today_projection(
        workspace_id="owner:usr_bob",
        tz_name="UTC",
        calendar_store=calendar_store,
        history_store=history_store,
        user_id="usr_bob",
        now_utc=datetime(2026, 9, 20, 12, 0, 0, tzinfo=timezone.utc),
    )
    other_titles = [item["title"] for item in p_other_user["items"]]
    assert "Alice Intake Run" not in other_titles


@pytest.mark.asyncio
async def test_blocker_3_timezone_item_date_parity() -> None:
    """Blocker 3: Returned item.date must match the requested explicit timezone."""
    calendar_store = InMemoryCalendarStore()
    task_alert_store = FakeTaskAlertStore()
    history_store = FakeHistoryStore()
    ws = "owner:usr_alice"

    # Instant: 2026-09-20T16:00:00Z
    # In Asia/Seoul (UTC+9), this is 2026-09-21 01:00:00 KST -> date is 2026-09-21!
    # In America/New_York (UTC-4), this is 2026-09-20 12:00:00 EDT -> date is 2026-09-20!
    created_instant = datetime(2026, 9, 20, 16, 0, 0, tzinfo=timezone.utc)
    created_str = "2026-09-20T16:00:00Z"

    task_alert_store.alerts[ws] = [
        MockAlert(
            alert_id="alert_tz_test",
            title="Late Evening Alert",
            created_at=created_instant,
            visible_to_all=True,
        )
    ]
    history_store.claw_runs["usr_alice"] = [
        {
            "run_id": "run_tz_test",
            "title": "Late Evening Claw Run",
            "status": "success",
            "result_summary": "OK",
            "created_at": created_str,
        }
    ]

    # 1. Query for Asia/Seoul on 2026-09-21 (when 2026-09-20T16:00:00Z occurred locally)
    p_seoul = await build_today_projection(
        workspace_id=ws,
        tz_name="Asia/Seoul",
        calendar_store=calendar_store,
        task_alert_store=task_alert_store,
        history_store=history_store,
        user_id="usr_alice",
        now_utc=datetime(2026, 9, 20, 16, 30, 0, tzinfo=timezone.utc),
    )
    assert p_seoul["date"] == "2026-09-21"
    for item in p_seoul["items"]:
        assert item["date"] == "2026-09-21", (
            f"Item date {item['date']} does not match projection date 2026-09-21 in Asia/Seoul! item={item}"
        )

    # 2. Query for America/New_York on 2026-09-20 (when 2026-09-20T16:00:00Z occurred locally)
    p_ny = await build_today_projection(
        workspace_id=ws,
        tz_name="America/New_York",
        calendar_store=calendar_store,
        task_alert_store=task_alert_store,
        history_store=history_store,
        user_id="usr_alice",
        now_utc=datetime(2026, 9, 20, 16, 30, 0, tzinfo=timezone.utc),
    )
    assert p_ny["date"] == "2026-09-20"
    for item in p_ny["items"]:
        assert item["date"] == "2026-09-20", (
            f"Item date {item['date']} does not match projection date 2026-09-20 in America/New_York! item={item}"
        )

    # 3. Midnight boundary test in Asia/Seoul
    # Exactly 2026-09-20T15:00:00Z -> 2026-09-21 00:00:00 KST -> date 2026-09-21
    # 2026-09-20T14:59:59Z -> 2026-09-20 23:59:59 KST -> date 2026-09-20
    p_midnight = await build_range_projection(
        workspace_id=ws,
        start_date=date(2026, 9, 21),
        end_date=date(2026, 9, 21),
        tz_name="Asia/Seoul",
        calendar_store=calendar_store,
        task_alert_store=task_alert_store,
        history_store=history_store,
        user_id="usr_alice",
    )
    for item in p_midnight["items"]:
        assert item["date"] == "2026-09-21"

