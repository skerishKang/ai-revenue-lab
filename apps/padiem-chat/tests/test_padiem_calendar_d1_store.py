"""#2834 Phase B-2: Durable D1 persistence tests for Native Padiem Calendar.

Validates:
- Real SQLite execution of migration 013_padiem_calendar.sql.
- D1CalendarStore implementation conforming to CalendarStore protocol.
- Strict workspace isolation: cross-workspace access returns None / empty list.
- Parameter boundaries, date filtering, and deterministic ordering.
- Timed events with explicit timezones, all-day events, and date-only events.
- Work-log non-promotion to long-term memory.
- Error handling and fail-closed semantics on database failures.
- App factory wiring: D1CalendarStore derived from d1_binding.
- End-to-end HTTP routes with D1CalendarStore.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import sqlite3
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.testclient import TestClient

from app.app_factory import create_app
from app.auth import SESSION_COOKIE, create_session_token
from app.calendar_contracts import (
    AppointmentType,
    CalendarAppointment,
    CalendarContractError,
    CalendarWorkLog,
    MAX_CALENDAR_LIST_LIMIT,
)
from app.calendar_store import (
    CalendarStore,
    D1CalendarStore,
    D1_CALENDAR_STORE_READY,
    DOMAIN_CONTRACT_READY,
    DURABLE_STORE_READY,
    InMemoryCalendarStore,
    STORE_PROTOCOL_READY,
)
from app.config import Settings
from app.control_plane_identity import PADIEM_CHAT_PRODUCT_ID
from app.control_plane_identity_shadow import IdentityShadowRecord
from app.workspace_storage import WorkspaceStorageError
from padiem_control_plane import (
    AuthSessionSnapshot,
    AuthSessionState,
    CanonicalSubjectRef,
    SubjectType,
)

MIGRATION_PATH = (
    Path(__file__).resolve().parents[1] / "migrations" / "013_padiem_calendar.sql"
)
COOKIE_SECRET = "test-session-secret-calendar-d1-32-chars-ok"


class SqliteD1Binding:
    """In-memory SQLite adapter conforming to Cloudflare D1 interface."""

    def __init__(self, conn: sqlite3.Connection | None = None) -> None:
        self.conn = conn or sqlite3.connect(
            ":memory:", check_same_thread=False, isolation_level=None
        )
        self.conn.row_factory = sqlite3.Row

    def prepare(self, sql: str) -> SqliteD1Statement:
        return SqliteD1Statement(self.conn, sql)


class SqliteD1Statement:
    def __init__(
        self,
        conn: sqlite3.Connection,
        sql: str,
        params: tuple[Any, ...] = (),
    ) -> None:
        self.conn = conn
        self.sql = sql
        self.params = params

    def bind(self, *values: Any) -> SqliteD1Statement:
        return SqliteD1Statement(self.conn, self.sql, values)

    async def run(self) -> dict[str, Any]:
        cursor = self.conn.cursor()
        cursor.execute(self.sql, self.params)
        return {"success": True}

    async def first(self) -> dict[str, Any] | None:
        cursor = self.conn.cursor()
        cursor.execute(self.sql, self.params)
        row = cursor.fetchone()
        return dict(row) if row is not None else None

    async def all(self) -> list[dict[str, Any]]:
        cursor = self.conn.cursor()
        cursor.execute(self.sql, self.params)
        rows = cursor.fetchall()
        return [dict(r) for r in rows]


@pytest.fixture
def d1_db() -> SqliteD1Binding:
    binding = SqliteD1Binding()
    sql_script = MIGRATION_PATH.read_text(encoding="utf-8")
    binding.conn.executescript(sql_script)
    return binding


@pytest.fixture
def d1_store(d1_db: SqliteD1Binding) -> D1CalendarStore:
    return D1CalendarStore(d1_db)


# ==============================================================================
# 1. Readiness flags & Protocol compliance
# ==============================================================================

def test_phase_b2_constants() -> None:
    assert DOMAIN_CONTRACT_READY is True
    assert STORE_PROTOCOL_READY is True
    assert DURABLE_STORE_READY is True
    assert D1_CALENDAR_STORE_READY is True


def test_d1_store_requires_db_binding() -> None:
    with pytest.raises(ValueError, match="D1 binding .* is required"):
        D1CalendarStore(None)


def test_d1_store_conforms_to_calendar_store_protocol(d1_store: D1CalendarStore) -> None:
    assert isinstance(d1_store, CalendarStore)


# ==============================================================================
# 2. Native Work-Log CRUD & Workspace Isolation
# ==============================================================================

@pytest.mark.asyncio
async def test_d1_work_log_crud_and_isolation(d1_store: D1CalendarStore) -> None:
    now = datetime(2026, 9, 20, 10, 0, 0, tzinfo=timezone.utc)
    log_a = CalendarWorkLog.create(
        workspace_id="ws_alpha",
        owner_id="usr_alice",
        date_val="2026-09-20",
        title="A사와 견적 협의",
        content="단가 10% 할인 합의",
        now=now,
    )

    # 1. Add log to workspace alpha
    saved = await d1_store.add_work_log(log_a)
    assert saved.log_id == log_a.log_id
    assert saved.title == "A사와 견적 협의"

    # 2. Get log from workspace alpha
    fetched = await d1_store.get_work_log("ws_alpha", log_a.log_id)
    assert fetched is not None
    assert fetched.log_id == log_a.log_id
    assert fetched.workspace_id == "ws_alpha"
    assert fetched.owner_id == "usr_alice"
    assert fetched.date == date(2026, 9, 20)
    assert fetched.title == "A사와 견적 협의"
    assert fetched.content == "단가 10% 할인 합의"
    assert fetched.created_at == now
    assert fetched.updated_at == now

    # 3. Non-disclosing lookup: foreign workspace returns None
    foreign_lookup = await d1_store.get_work_log("ws_beta", log_a.log_id)
    assert foreign_lookup is None, "Foreign workspace was able to read alpha's work-log!"

    # 4. Missing lookup returns None
    missing_lookup = await d1_store.get_work_log("ws_alpha", "log_nonexistent")
    assert missing_lookup is None

    # 5. List work logs scoped to workspace alpha
    logs_alpha = await d1_store.list_work_logs("ws_alpha")
    assert len(logs_alpha) == 1
    assert logs_alpha[0].log_id == log_a.log_id

    # 6. List work logs for workspace beta returns 0 items
    logs_beta = await d1_store.list_work_logs("ws_beta")
    assert len(logs_beta) == 0


@pytest.mark.asyncio
async def test_d1_work_log_date_filtering_and_ordering(d1_store: D1CalendarStore) -> None:
    ws = "ws_test"
    t1 = datetime(2026, 9, 20, 8, 0, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 9, 20, 12, 0, 0, tzinfo=timezone.utc)
    t3 = datetime(2026, 9, 21, 9, 0, 0, tzinfo=timezone.utc)
    t4 = datetime(2026, 9, 22, 10, 0, 0, tzinfo=timezone.utc)

    log_1 = CalendarWorkLog.create(
        workspace_id=ws, owner_id="usr_1", date_val="2026-09-20", title="Log Early", now=t1
    )
    log_2 = CalendarWorkLog.create(
        workspace_id=ws, owner_id="usr_1", date_val="2026-09-20", title="Log Later", now=t2
    )
    log_3 = CalendarWorkLog.create(
        workspace_id=ws, owner_id="usr_1", date_val="2026-09-21", title="Log Tomorrow", now=t3
    )
    log_4 = CalendarWorkLog.create(
        workspace_id=ws, owner_id="usr_1", date_val="2026-09-22", title="Log Day After", now=t4
    )

    for l in (log_4, log_2, log_1, log_3):  # Insert out of order
        await d1_store.add_work_log(l)

    # All items ordered deterministically by date ASC, created_at ASC
    all_logs = await d1_store.list_work_logs(ws)
    assert [l.title for l in all_logs] == ["Log Early", "Log Later", "Log Tomorrow", "Log Day After"]

    # Filter start_date only
    from_21 = await d1_store.list_work_logs(ws, start_date=date(2026, 9, 21))
    assert [l.title for l in from_21] == ["Log Tomorrow", "Log Day After"]

    # Filter end_date only
    up_to_20 = await d1_store.list_work_logs(ws, end_date=date(2026, 9, 20))
    assert [l.title for l in up_to_20] == ["Log Early", "Log Later"]

    # Range filter
    range_21 = await d1_store.list_work_logs(
        ws, start_date=date(2026, 9, 21), end_date=date(2026, 9, 21)
    )
    assert [l.title for l in range_21] == ["Log Tomorrow"]

    # Limit check
    limited = await d1_store.list_work_logs(ws, limit=2)
    assert len(limited) == 2
    assert [l.title for l in limited] == ["Log Early", "Log Later"]


# ==============================================================================
# 3. Native Appointment CRUD & Types & Isolation
# ==============================================================================

@pytest.mark.asyncio
async def test_d1_appointment_crud_all_types(d1_store: D1CalendarStore) -> None:
    ws = "ws_apts"
    owner = "usr_bob"

    # 1. Date-only appointment
    apt_date = CalendarAppointment.create(
        workspace_id=ws,
        owner_id=owner,
        appointment_type=AppointmentType.DATE_ONLY,
        title="세금계산서 발행 마감",
        date_val="2026-09-30",
        description="회계팀 전달",
    )
    await d1_store.add_appointment(apt_date)

    # 2. All-day appointment
    apt_allday = CalendarAppointment.create(
        workspace_id=ws,
        owner_id=owner,
        appointment_type=AppointmentType.ALL_DAY,
        title="전사 정기 점검",
        date_val="2026-10-01",
    )
    await d1_store.add_appointment(apt_allday)

    # 3. Timed appointment
    apt_timed = CalendarAppointment.create(
        workspace_id=ws,
        owner_id=owner,
        appointment_type=AppointmentType.TIMED,
        title="주주총회 사전 리허설",
        start_at="2026-09-25T14:00:00+09:00",
        end_at="2026-09-25T16:00:00+09:00",
        tz_name="Asia/Seoul",
        reminder_minutes=60,
    )
    await d1_store.add_appointment(apt_timed)

    # Read back and verify each
    f_date = await d1_store.get_appointment(ws, apt_date.appointment_id)
    assert f_date is not None
    assert f_date.appointment_type == AppointmentType.DATE_ONLY
    assert f_date.date == date(2026, 9, 30)
    assert f_date.start_at is None
    assert f_date.end_at is None
    assert f_date.timezone is None
    assert f_date.description == "회계팀 전달"

    f_all = await d1_store.get_appointment(ws, apt_allday.appointment_id)
    assert f_all is not None
    assert f_all.appointment_type == AppointmentType.ALL_DAY
    assert f_all.date == date(2026, 10, 1)

    f_timed = await d1_store.get_appointment(ws, apt_timed.appointment_id)
    assert f_timed is not None
    assert f_timed.appointment_type == AppointmentType.TIMED
    assert f_timed.timezone == "Asia/Seoul"
    assert f_timed.reminder_minutes == 60
    assert f_timed.start_at == datetime(2026, 9, 25, 5, 0, 0, tzinfo=timezone.utc)
    assert f_timed.end_at == datetime(2026, 9, 25, 7, 0, 0, tzinfo=timezone.utc)

    # Isolation check
    assert await d1_store.get_appointment("ws_foreign", apt_timed.appointment_id) is None
    foreign_list = await d1_store.list_appointments("ws_foreign")
    assert len(foreign_list) == 0


@pytest.mark.asyncio
async def test_d1_appointment_ordering_parity_with_in_memory(d1_store: D1CalendarStore) -> None:
    ws = "ws_order_test"
    mem_store = InMemoryCalendarStore()

    apts = [
        CalendarAppointment.create(
            workspace_id=ws,
            owner_id="u1",
            appointment_type=AppointmentType.DATE_ONLY,
            title="A_DateOnly",
            date_val="2026-09-22",
        ),
        CalendarAppointment.create(
            workspace_id=ws,
            owner_id="u1",
            appointment_type=AppointmentType.TIMED,
            title="B_TimedMorning",
            start_at="2026-09-22T09:00:00+09:00",
            tz_name="Asia/Seoul",
        ),
        CalendarAppointment.create(
            workspace_id=ws,
            owner_id="u1",
            appointment_type=AppointmentType.TIMED,
            title="C_TimedAfternoon",
            start_at="2026-09-22T15:00:00+09:00",
            tz_name="Asia/Seoul",
        ),
        CalendarAppointment.create(
            workspace_id=ws,
            owner_id="u1",
            appointment_type=AppointmentType.ALL_DAY,
            title="D_AllDay",
            date_val="2026-09-21",
        ),
    ]

    for apt in apts:
        await d1_store.add_appointment(apt)
        await mem_store.add_appointment(apt)

    d1_items = await d1_store.list_appointments(ws)
    mem_items = await mem_store.list_appointments(ws)

    # Verify exact ordering parity between in-memory reference and D1
    assert [a.appointment_id for a in d1_items] == [a.appointment_id for a in mem_items]
    assert [a.title for a in d1_items] == [
        "D_AllDay",         # 2026-09-21
        "A_DateOnly",       # 2026-09-22, start_at="" (sorts before timestamps)
        "B_TimedMorning",   # 2026-09-22 09:00 KST
        "C_TimedAfternoon", # 2026-09-22 15:00 KST
    ]


# ==============================================================================
# 4. Fail-Closed Error Handling & Boundary Defense
# ==============================================================================

@pytest.mark.asyncio
async def test_d1_store_unsafe_identifiers_rejected(d1_store: D1CalendarStore) -> None:
    with pytest.raises(CalendarContractError) as exc:
        await d1_store.get_work_log("ws; DROP TABLE padiem_calendar_work_log;", "log_123")
    assert exc.value.code == "invalid_identifier"

    with pytest.raises(CalendarContractError) as exc:
        await d1_store.get_appointment("ws_1", "apt-invalid id with spaces")
    assert exc.value.code == "invalid_identifier"


@pytest.mark.asyncio
async def test_d1_store_fails_closed_on_broken_database(d1_db: SqliteD1Binding) -> None:
    store = D1CalendarStore(d1_db)
    # Intentionally corrupt connection by closing it
    d1_db.conn.close()

    now = datetime(2026, 9, 20, 10, 0, 0, tzinfo=timezone.utc)
    log = CalendarWorkLog.create(
        workspace_id="ws_broken",
        owner_id="u1",
        date_val="2026-09-20",
        title="Broken DB Test",
        now=now,
    )

    with pytest.raises(WorkspaceStorageError, match="D1 write failed"):
        await store.add_work_log(log)

    with pytest.raises(WorkspaceStorageError, match="D1 read failed"):
        await store.get_work_log("ws_broken", log.log_id)

    with pytest.raises(WorkspaceStorageError, match="D1 read failed"):
        await store.list_work_logs("ws_broken")


# ==============================================================================
# 5. App Factory Wiring: D1 Binding Auto-Derivation
# ==============================================================================

def test_app_factory_wires_d1_calendar_store_when_d1_binding_present(d1_db: SqliteD1Binding) -> None:
    settings = Settings.from_values(
        runtime_mode="mock",
        live_enabled="false",
        auth_mode="off",
        session_secret=COOKIE_SECRET,
    )
    # When d1_binding is provided and calendar_store is omitted:
    app = create_app(settings=settings, d1_binding=d1_db)
    assert isinstance(app.state.calendar_store, D1CalendarStore)
    assert app.state.calendar_store.db is d1_db


def test_app_factory_falls_back_to_in_memory_when_d1_binding_absent() -> None:
    settings = Settings.from_values(
        runtime_mode="mock",
        live_enabled="false",
        auth_mode="off",
        session_secret=COOKIE_SECRET,
    )
    # When d1_binding is None and calendar_store is omitted:
    app = create_app(settings=settings, d1_binding=None)
    assert isinstance(app.state.calendar_store, InMemoryCalendarStore)


def test_app_factory_explicit_calendar_store_wins(d1_db: SqliteD1Binding) -> None:
    custom_store = InMemoryCalendarStore()
    settings = Settings.from_values(
        runtime_mode="mock",
        live_enabled="false",
        auth_mode="off",
        session_secret=COOKIE_SECRET,
    )
    # When custom store is explicitly passed, it overrides D1 derivation:
    app = create_app(settings=settings, d1_binding=d1_db, calendar_store=custom_store)
    assert app.state.calendar_store is custom_store


# ==============================================================================
# 6. End-to-End HTTP Route Integration with D1 Persistence
# ==============================================================================

def _build_d1_http_client(d1_db: SqliteD1Binding, user_id: str, tenant_id: str) -> TestClient:
    settings = Settings.from_values(
        runtime_mode="mock",
        live_enabled="false",
        auth_mode="google",
        google_client_id="test.apps.googleusercontent.com",
        google_client_secret="test-google-secret",
        session_secret=COOKIE_SECRET,
        public_base_url="https://chat.example.test",
    )
    now = datetime.now(timezone.utc)
    shadow = MagicMock()
    shadow.load_projection = AsyncMock(
        return_value=IdentityShadowRecord(
            product_user_id=user_id,
            canonical_subject_id=f"sub_{user_id}",
            auth_session_id=f"sess_{user_id}",
            session_revision=1,
            session_state="active",
            session_expires_at=now + timedelta(hours=1),
            observed_at=now,
        )
    )
    authority = MagicMock()
    authority.resolve_auth_session = AsyncMock(
        return_value=AuthSessionSnapshot(
            session_id=f"sess_{user_id}",
            product_id=PADIEM_CHAT_PRODUCT_ID,
            subject=CanonicalSubjectRef(SubjectType.USER, f"sub_{user_id}"),
            issued_at=now - timedelta(hours=1),
            expires_at=now + timedelta(hours=1),
            state=AuthSessionState.ACTIVE,
            revision=1,
            tenant_id=tenant_id,
        )
    )
    app = create_app(settings=settings, d1_binding=d1_db, history_store=MagicMock())
    app.state.identity_shadow_store = shadow
    app.state.control_plane_identity_authority = authority

    client = TestClient(app, base_url="https://chat.example.test")
    client.cookies.set(
        SESSION_COOKIE,
        create_session_token(app.state.settings, user_id),
        domain="chat.example.test",
        path="/",
    )
    return client


def test_e2e_http_calendar_d1_persistence_and_isolation(d1_db: SqliteD1Binding) -> None:
    user_1 = "usr_alice_1111111111111111111111"
    user_2 = "usr_bob_222222222222222222222222"
    tenant_1 = "tenant_alpha"
    tenant_2 = "tenant_beta"

    client1 = _build_d1_http_client(d1_db, user_1, tenant_1)
    client2 = _build_d1_http_client(d1_db, user_2, tenant_2)

    # 1. User 1 in Tenant 1 creates work-log and appointment
    r_wl = client1.post(
        "/api/calendar/work-logs",
        json={
            "date": "2026-09-20",
            "title": "Alpha Supplier Review",
            "content": "Selected Supplier A based on unit pricing.",
        },
    )
    assert r_wl.status_code == 201
    wl_id = r_wl.json()["work_log"]["calendar_item_id"].replace("item_log_", "")

    r_apt = client1.post(
        "/api/calendar/appointments",
        json={
            "appointment_type": "timed",
            "title": "Alpha Contract Signing",
            "start_at": "2026-09-22T14:00:00+09:00",
            "end_at": "2026-09-22T15:00:00+09:00",
            "timezone": "Asia/Seoul",
        },
    )
    assert r_apt.status_code == 201

    # 2. User 1 lists and queries today/range projections from Tenant 1
    r_list = client1.get("/api/calendar/work-logs")
    assert r_list.status_code == 200
    assert len(r_list.json()["items"]) == 1
    assert r_list.json()["items"][0]["title"] == "Alpha Supplier Review"

    r_range = client1.get(
        "/api/calendar/items?start_date=2026-09-20&end_date=2026-09-23&timezone=Asia/Seoul"
    )
    assert r_range.status_code == 200
    p_items = r_range.json()["projection"]["items"]
    titles = [it["title"] for it in p_items]
    assert "Alpha Supplier Review" in titles
    assert "Alpha Contract Signing" in titles

    # 3. User 2 in Tenant 2 queries calendar: MUST SEE ZERO ITEMS (Tenant Isolation)
    r_t2_wl = client2.get("/api/calendar/work-logs")
    assert r_t2_wl.status_code == 200
    assert len(r_t2_wl.json()["items"]) == 0

    r_t2_range = client2.get(
        "/api/calendar/items?start_date=2026-09-20&end_date=2026-09-23&timezone=Asia/Seoul"
    )
    assert r_t2_range.status_code == 200
    assert len(r_t2_range.json()["projection"]["items"]) == 0

    # 4. Direct database row inspection verifies real D1 table rows
    cursor = d1_db.conn.cursor()
    cursor.execute("SELECT id, workspace_id, title FROM padiem_calendar_work_log")
    rows = cursor.fetchall()
    assert len(rows) == 1
    assert rows[0]["id"] == wl_id
    assert rows[0]["workspace_id"] == tenant_1
    assert rows[0]["title"] == "Alpha Supplier Review"
