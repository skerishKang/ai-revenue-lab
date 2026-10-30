"""#2952 follow-up sweep: an inbox read is scoped by its owner, not by the tenant.

`app/claw_memory_routes.py::_resolve_memory_workspace` resolves the canonical
Control Plane **tenant** id, so one workspace holds several product users. The
durable Claw task/alert store read rows by `workspace_id` alone and applied the
member predicate in the caller, after a bounded `LIMIT` scan. Two things followed
from that: the store could not refuse a tenant-wide read, and one member's volume
pushed another member's own rows out of their inbox and calendar.

These tests use the real D1 SQL (sqlite), real signed-in session cookies and two
users forced into the *same* tenant — the exact condition the tenant-only scope
hid.
"""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from app import claw_inbox_routes
from app.app_factory import create_app
from app.auth import SESSION_COOKIE, create_session_token
from app.calendar_projection import build_range_projection
from app.claw_task_alert_store import D1ClawTaskAlertStore

from kagent.claw_memory import ClawFollowupTask, ClawTaskStatus

from test_b54_claw_general_p01_routing import _make_adapter, _settings

USER_A = "usr_" + "a" * 32
USER_B = "usr_" + "b" * 32
SHARED_TENANT = "tenant_shared_2952_sweep"
MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"
BASE = datetime(2026, 10, 1, tzinfo=timezone.utc)


class _D1:
    """Runs the store's own SQL against sqlite, D1-shaped call surface."""

    class _Statement:
        def __init__(self, conn, query):
            self.conn, self.query, self.args = conn, query, ()

        def bind(self, *values):
            self.args = values
            return self

        async def run(self):
            cur = self.conn.execute(self.query, self.args)
            return {"success": True, "meta": {"changes": cur.rowcount}}

        async def first(self):
            row = self.conn.execute(self.query, self.args).fetchone()
            return dict(row) if row else None

        async def all(self):
            return [dict(r) for r in self.conn.execute(self.query, self.args).fetchall()]

    def __init__(self, conn):
        self.conn = conn

    def prepare(self, query):
        return _D1._Statement(self.conn, query)


def _store() -> D1ClawTaskAlertStore:
    conn = sqlite3.connect(":memory:", isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript((MIGRATIONS / "010_claw_task_alert.sql").read_text(encoding="utf-8"))
    return D1ClawTaskAlertStore(_D1(conn))


def _task(
    task_id: str, member_id: str, created: datetime, *, due: date | None = None
) -> ClawFollowupTask:
    return ClawFollowupTask(
        task_id=task_id,
        workspace_id=SHARED_TENANT,
        member_id=member_id,
        title=f"후속 작업 {task_id}",
        status=ClawTaskStatus.OPEN,
        created_at=created,
        due_date=due,
    )


def _two_users(store: D1ClawTaskAlertStore):
    """One app, two signed-in users, each with its own cookie jar."""
    settings = _settings()
    app = create_app(
        settings=settings,
        history_store=MagicHistory(),
        calendar_store=None,
        claw_p01_adapter=_make_adapter(),
        claw_task_alert_store=store,
    )
    app.state.usage_gate_enforced = False

    def client(user_id: str) -> TestClient:
        c = TestClient(app, base_url="https://chat.example.test")
        c.cookies.set(
            SESSION_COOKIE,
            create_session_token(settings, user_id),
            domain="chat.example.test",
            path="/",
        )
        return c

    return app, client(USER_A), client(USER_B)


class MagicHistory:
    async def append_exchange(self, user_id, conversation_id, user_text, answer, product_scope=None):
        return "conv-2952-sweep"


@pytest.fixture(autouse=True)
def _shared_tenant(monkeypatch):
    """Both identities resolve to the same tenant id, as a real tenant would."""

    async def workspace(_request, uid):
        return SHARED_TENANT

    monkeypatch.setattr(claw_inbox_routes, "_resolve_memory_workspace", workspace)


def test_the_store_itself_never_returns_a_tenant_mates_tasks() -> None:
    """데이터 경계 증거: 같은 workspace 라도 member_id 가 다르면 아무것도 나오지 않는다."""
    store = _store()

    async def scenario() -> None:
        await store.add_task(_task("task-b", USER_B, BASE))

        assert await store.list_tasks(SHARED_TENANT, member_id=USER_A) == ()
        mine = await store.list_tasks(SHARED_TENANT, member_id=USER_B)
        assert [t.task_id for t in mine] == ["task-b"]
        # A read with no owner argument cannot be expressed at all.
        with pytest.raises(TypeError):
            store.list_tasks(SHARED_TENANT)  # type: ignore[call-arg]
        with pytest.raises(TypeError):
            store.list_alerts(SHARED_TENANT)  # type: ignore[call-arg]

    asyncio.run(scenario())


def test_a_tenant_mate_volume_cannot_hide_my_own_rows() -> None:
    """절단 결함 증거: LIMIT 이 소유자 필터보다 먼저 걸리면 내 항목이 사라진다."""
    store = _store()

    async def seed() -> None:
        await store.add_task(_task("mine", USER_B, BASE))
        for index in range(260):
            await store.add_task(
                _task(f"a-{index:03d}", USER_A, BASE + timedelta(minutes=index + 1))
            )

    asyncio.run(seed())

    app, a, b = _two_users(store)
    with a, b:
        mine = b.get("/api/claw/inbox/tasks", params={"limit": 50})
        theirs = a.get("/api/claw/inbox/tasks", params={"limit": 50})

    assert mine.status_code == 200, mine.text
    items = mine.json()["items"]
    assert [item["task_id"] for item in items] == ["mine"], items
    assert all(item["member_id"] == USER_B for item in items)
    assert theirs.status_code == 200, theirs.text
    assert all(item["member_id"] == USER_A for item in theirs.json()["items"])


def test_user_b_cannot_read_or_patch_user_as_task() -> None:
    store = _store()
    asyncio.run(store.add_task(_task("task-a", USER_A, BASE)))

    app, a, b = _two_users(store)
    with a, b:
        empty_for_b = b.get("/api/claw/inbox/tasks", params={"limit": 50})
        patch = b.patch("/api/claw/inbox/tasks/task-a", json={"status": "done"})
        own_read = a.get("/api/claw/inbox/tasks", params={"limit": 50})

    assert empty_for_b.status_code == 200, empty_for_b.text
    assert empty_for_b.json()["items"] == []
    assert patch.status_code == 404, patch.text
    assert [item["task_id"] for item in own_read.json()["items"]] == ["task-a"]


def test_projection_never_carries_a_tenant_mates_task() -> None:
    """캘린더 투영도 같은 규칙: 검증된 소유자 외에는 테넌트 행이 들어가지 않는다."""
    store = _store()

    async def seed() -> None:
        await store.add_task(_task("task-a", USER_A, BASE, due=BASE.date()))
        await store.add_task(_task("task-b", USER_B, BASE, due=BASE.date()))

    async def project(member: str) -> dict:
        return await build_range_projection(
            SHARED_TENANT,
            BASE.date(),
            BASE.date() + timedelta(days=1),
            "UTC",
            calendar_store=_NoCalendarStore(),
            task_alert_store=store,
            user_id=member,
        )

    asyncio.run(seed())
    as_a = asyncio.run(project(USER_A))
    as_b = asyncio.run(project(USER_B))
    no_owner = asyncio.run(
        build_range_projection(
            SHARED_TENANT,
            BASE.date(),
            BASE.date() + timedelta(days=1),
            "UTC",
            calendar_store=_NoCalendarStore(),
            task_alert_store=store,
            user_id=None,
        )
    )

    def titles(projection: dict) -> list[str]:
        return [item["title"] for item in projection["items"]]

    assert any("task-a" in t for t in titles(as_a)), titles(as_a)
    assert not any("task-a" in t for t in titles(as_b)), titles(as_b)
    assert any("task-b" in t for t in titles(as_b)), titles(as_b)
    assert not any("task-" in t for t in titles(no_owner)), titles(no_owner)


class _NoCalendarStore:
    """The calendar rows are #6120's scope; this sweep only proves the task lane."""

    async def list_work_logs(self, workspace_id, **kwargs):
        return ()

    async def list_appointments(self, workspace_id, **kwargs):
        return ()

    async def get_work_log(self, workspace_id, log_id, **kwargs):
        return None

    async def get_appointment(self, workspace_id, appointment_id, **kwargs):
        return None
