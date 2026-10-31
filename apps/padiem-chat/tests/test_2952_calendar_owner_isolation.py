"""#2952 load-bearing regression: two users in one workspace never share a calendar.

A workspace is the canonical Control Plane **tenant** id
(`app/claw_memory_routes.py::_resolve_memory_workspace`), and a tenant holds more
than one product user. Every native-calendar READ used to be scoped by workspace
only, so a tenant-mate could list another user's work logs and appointments, read
one by id, and private rows appeared in today/upcoming projections and in the
native-calendar chat read.

These tests pin the owner as the read scope, with both users authenticated by
real session cookies and forced into the *same* workspace, which is exactly the
condition the workspace-only scope hid.
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from datetime import date, datetime, timezone

import pytest
from starlette.testclient import TestClient

from app import native_calendar_adapter as adapter
from app import calendar_routes
from app.app_factory import create_app
from app.calendar_store import InMemoryCalendarStore
from test_b54_claw_general_p01_routing import (
    SESSION_COOKIE,
    _AuthStore,
    _make_adapter,
    _settings,
    create_session_token,
)

USER_A = "usr_" + "a" * 32
USER_B = "usr_" + "b" * 32
# One tenant shared by both users: the workspace value is identical on purpose.
SHARED_WORKSPACE = "tenant_shared_2952"
TODAY = datetime.now(timezone.utc).date().isoformat()


class _HistoryStore(_AuthStore):
    async def append_exchange(self, user_id, conversation_id, user_text, answer, product_scope=None):
        return "conv-2952"


@contextmanager
def client_for(user_id: str):
    """A signed-in browser for exactly one product user."""
    app = create_app(
        settings=_settings(),
        history_store=_HistoryStore(),
        calendar_store=InMemoryCalendarStore(),
        claw_p01_adapter=_make_adapter(),
    )
    app.state.usage_gate_enforced = False
    client = TestClient(app, base_url="https://chat.example.test")
    client.cookies.set(
        SESSION_COOKIE,
        create_session_token(_settings(), user_id),
        domain="chat.example.test",
        path="/",
    )
    with client:
        yield client


@pytest.fixture(autouse=True)
def _shared_tenant(monkeypatch):
    """Both identities resolve to the same tenant id, as a real tenant would."""

    async def workspace(_request, uid):
        return SHARED_WORKSPACE

    monkeypatch.setattr(calendar_routes, "_resolve_memory_workspace", workspace)
    monkeypatch.setattr(adapter, "_resolve_memory_workspace", workspace)


def _create_work_log(client: TestClient, title: str) -> dict:
    response = client.post(
        "/api/calendar/work-logs",
        json={"date": TODAY, "title": title, "content": "내용"},
    )
    assert response.status_code == 201, response.text
    log = response.json()["work_log"]
    # The public projection carries the canonical item id, not the raw row id.
    log["log_id"] = log["calendar_item_id"].removeprefix("item_log_")
    return log


def _create_appointment(client: TestClient, title: str) -> dict:
    response = client.post(
        "/api/calendar/appointments",
        json={"appointment_type": "date_only", "title": title, "date": TODAY},
    )
    assert response.status_code == 201, response.text
    apt = response.json()["appointment"]
    apt["appointment_id"] = apt["calendar_item_id"].removeprefix("item_apt_")
    return apt


def _two_users():
    """One app, two signed-in users, each with its own cookie jar."""

    app = create_app(
        settings=_settings(),
        history_store=_HistoryStore(),
        calendar_store=InMemoryCalendarStore(),
        claw_p01_adapter=_make_adapter(),
    )
    app.state.usage_gate_enforced = False

    def client(user_id: str) -> TestClient:
        c = TestClient(app, base_url="https://chat.example.test")
        c.cookies.set(
            SESSION_COOKIE,
            create_session_token(_settings(), user_id),
            domain="chat.example.test",
            path="/",
        )
        return c

    return app, client(USER_A), client(USER_B)


def test_the_store_itself_never_returns_a_tenant_mates_rows() -> None:
    """데이터 경계 증거: 같은 workspace 라도 owner 가 다르면 아무것도 나오지 않는다."""
    store = InMemoryCalendarStore()

    async def scenario() -> None:
        from app.calendar_contracts import CalendarAppointment, CalendarWorkLog

        await store.add_work_log(
            CalendarWorkLog.create(
                workspace_id=SHARED_WORKSPACE,
                owner_id=USER_B,
                date_val=TODAY,
                title="B의 비공개 업무 기록",
            )
        )
        await store.add_appointment(
            CalendarAppointment.create(
                workspace_id=SHARED_WORKSPACE,
                owner_id=USER_B,
                appointment_type="date_only",
                title="B의 비공개 일정",
                date_val=TODAY,
            )
        )

        assert await store.list_work_logs(SHARED_WORKSPACE, owner_id=USER_A) == ()
        assert await store.list_appointments(SHARED_WORKSPACE, owner_id=USER_A) == ()
        assert await store.get_work_log(
            SHARED_WORKSPACE, "log_unknown", owner_id=USER_A
        ) is None
        # The owner still reads their own rows.
        assert len(await store.list_work_logs(SHARED_WORKSPACE, owner_id=USER_B)) == 1
        assert len(await store.list_appointments(SHARED_WORKSPACE, owner_id=USER_B)) == 1

    asyncio.run(scenario())


def test_user_b_lists_only_their_own_calendar() -> None:
    app, a, b = _two_users()
    with a, b:
        _create_work_log(b, "B의 업무 기록")
        b_apt = _create_appointment(b, "B의 일정")
        _create_work_log(a, "A의 업무 기록")
        _create_appointment(a, "A의 일정")

        a_logs = a.get("/api/calendar/work-logs").json()["items"]
        a_apts = a.get("/api/calendar/appointments").json()["items"]
        b_logs = b.get("/api/calendar/work-logs").json()["items"]

    assert [item["title"] for item in a_logs] == ["A의 업무 기록"]
    assert [item["title"] for item in a_apts] == ["A의 일정"]
    assert [item["title"] for item in b_logs] == ["B의 업무 기록"]
    assert all(item["calendar_item_id"] != b_apt["calendar_item_id"] for item in a_apts)


def test_user_b_cannot_read_user_as_item_detail() -> None:
    app, a, b = _two_users()
    with a, b:
        a_log = _create_work_log(a, "A의 상세 기록")
        a_apt = _create_appointment(a, "A의 상세 일정")

        log_detail = b.get(
            f"/api/calendar/items/{a_log['calendar_item_id']}",
            params={"timezone": "UTC"},
        )
        apt_detail = b.get(
            f"/api/calendar/items/{a_apt['calendar_item_id']}",
            params={"timezone": "UTC"},
        )
        own_log_detail = a.get(
            f"/api/calendar/items/{a_log['calendar_item_id']}",
            params={"timezone": "UTC"},
        )

    assert log_detail.status_code == 404, log_detail.text
    assert apt_detail.status_code == 404, apt_detail.text
    assert own_log_detail.status_code == 200, own_log_detail.text


def test_user_b_cannot_write_or_delete_user_as_records() -> None:
    app, a, b = _two_users()
    with a, b:
        a_log = _create_work_log(a, "A의 수정 대상 기록")
        a_apt = _create_appointment(a, "A의 수정 대상 일정")

        log_put = b.put(
            f"/api/calendar/work-logs/{a_log['log_id']}",
            json={"title": "B가 바꾼 제목"},
        )
        apt_put = b.put(
            f"/api/calendar/appointments/{a_apt['appointment_id']}",
            json={"title": "B가 바꾼 일정"},
        )
        log_delete = b.delete(f"/api/calendar/work-logs/{a_log['log_id']}")
        apt_delete = b.delete(f"/api/calendar/appointments/{a_apt['appointment_id']}")
        assert a_log["calendar_item_id"].startswith("item_log_")

        a_logs = a.get("/api/calendar/work-logs").json()["items"]
        a_apts = a.get("/api/calendar/appointments").json()["items"]

    assert log_put.status_code == 404, log_put.text
    assert apt_put.status_code == 404, apt_put.text
    assert log_delete.status_code == 404, log_delete.text
    assert apt_delete.status_code == 404, apt_delete.text
    assert [item["title"] for item in a_logs] == ["A의 수정 대상 기록"]
    assert [item["title"] for item in a_apts] == ["A의 수정 대상 일정"]


def test_projections_and_chat_read_hide_the_tenant_mates_calendar() -> None:
    app, a, b = _two_users()
    with a, b:
        _create_appointment(b, "B의 이번 주 일정")
        _create_work_log(b, "B의 오늘 업무 기록")

        today = a.get("/api/calendar/today", params={"timezone": "UTC"})
        upcoming = a.get("/api/calendar/upcoming", params={"timezone": "UTC"})
        chat_read = a.post(
            "/api/chat",
            json={"messages": [{"role": "user", "content": "이번 주 일정 보여줘"}], "timezone": "UTC"},
        )

    assert today.status_code == 200, today.text
    assert upcoming.status_code == 200, upcoming.text
    assert "B의" not in today.text
    assert "B의" not in upcoming.text
    assert chat_read.status_code == 200, chat_read.text
    assert "B의" not in chat_read.text


def test_projection_without_a_verified_owner_projects_no_native_rows() -> None:
    """owner 가 없으면 fail closed: workspace 만으로는 아무 행도 보여주지 않는다."""
    from app.calendar_contracts import CalendarWorkLog
    from app.calendar_projection import build_range_projection

    store = InMemoryCalendarStore()

    async def scenario() -> None:
        await store.add_work_log(
            CalendarWorkLog.create(
                workspace_id=SHARED_WORKSPACE,
                owner_id=USER_A,
                date_val=TODAY,
                title="A의 기록",
            )
        )
        result = await build_range_projection(
            workspace_id=SHARED_WORKSPACE,
            start_date=date.fromisoformat(TODAY),
            end_date=date.fromisoformat(TODAY),
            tz_name="UTC",
            calendar_store=store,
            user_id=None,
        )
        assert result["items"] == []

    asyncio.run(scenario())
