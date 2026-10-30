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
from types import SimpleNamespace
from starlette.testclient import TestClient

from app import claw_artifact_preview_routes
from app import claw_inbox_routes
from app import claw_routes
from app.app_factory import create_app
from app.auth import SESSION_COOKIE, create_session_token
from app.auth_routes import current_user_id
from app.calendar_projection import build_range_projection
from app.claw_task_alert_store import D1ClawTaskAlertStore
from app.history import D1HistoryStore
from app.workspace_storage import D1ClawDocumentMetadataStore, WorkspaceDocumentStore

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


def _db(*migrations: str) -> _D1:
    conn = sqlite3.connect(":memory:", isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    for name in migrations:
        conn.executescript((MIGRATIONS / name).read_text(encoding="utf-8"))
    return _D1(conn)


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


class _Bucket:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def put(self, key, body, **kwargs) -> None:
        self.objects[key] = bytes(body)

    async def get(self, key):
        body = self.objects.get(key)
        return None if body is None else SimpleNamespace(body=body)

    async def delete(self, key) -> None:
        self.objects.pop(key, None)


def _history() -> D1HistoryStore:
    return D1HistoryStore(
        _db(
            "001_auth_history.sql",
            "009_claw_run_history.sql",
            "014_claw_run_history_conversation.sql",
            "015_claw_run_history_workspace.sql",
        )
    )


def _documents() -> tuple[WorkspaceDocumentStore, _Bucket]:
    bucket = _Bucket()
    return (
        WorkspaceDocumentStore(
            D1ClawDocumentMetadataStore(_db("008_claw_document_metadata.sql")), bucket
        ),
        bucket,
    )


def _artifact_users(history, documents):
    """Two signed-in users in one tenant, real history and document stores."""
    settings = _settings()
    app = create_app(
        settings=settings,
        history_store=history,
        calendar_store=None,
        claw_p01_adapter=_make_adapter(),
    )
    app.state.usage_gate_enforced = False
    app.state.workspace_document_store = documents

    async def owner(request):
        # The tenant half is the mocked canonical authority; the user id still
        # comes from the real session cookie the client carries.
        return current_user_id(request), SHARED_TENANT

    claw_routes._resolve_canonical_owner = owner
    claw_artifact_preview_routes._resolve_canonical_owner = owner

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


def test_a_tenant_mate_cannot_open_another_users_document_bytes() -> None:
    """#2952 실측 결함: 테넌트 일치만으로 남의 문서 바이트가 열리던 경로."""
    history = _history()
    store, _bucket = _documents()
    meta = asyncio.run(
        store.put_generated_docx(
            tenant_id=SHARED_TENANT, filename="a-report.docx", body=b"A-PRIVATE-BYTES"
        )
    )
    asyncio.run(
        history.record_claw_run(
            USER_A,
            "run-artifact-1",
            "chat",
            "summary",
            "A의 실행",
            "done",
            artifact_document_id=meta.document_id,
            artifact_filename=meta.filename,
            artifact_media_type=meta.media_type,
        )
    )

    app, a, b = _artifact_users(history, store)
    try:
        with a, b:
            own = a.get(f"/api/claw/manual-intake/artifact/{meta.document_id}")
            mate = b.get(f"/api/claw/manual-intake/artifact/{meta.document_id}")
            mate_preview = b.get(
                f"/api/claw/manual-intake/artifact/{meta.document_id}/preview"
            )
            own_preview = a.get(
                f"/api/claw/manual-intake/artifact/{meta.document_id}/preview"
            )
    finally:
        claw_routes._resolve_canonical_owner = _REAL_OWNER
        claw_artifact_preview_routes._resolve_canonical_owner = _REAL_OWNER_PREVIEW

    assert own.status_code == 200, own.text
    assert own.content == b"A-PRIVATE-BYTES"
    assert mate.status_code == 404, mate.text
    assert mate.content != b"A-PRIVATE-BYTES"
    assert mate_preview.status_code == 404, mate_preview.text
    assert own_preview.status_code in (200, 415) or own_preview.content == b"A-PRIVATE-BYTES"


def test_a_document_with_no_minting_run_is_readable_by_no_one() -> None:
    """소유 권위가 없는 문서(비교 레인이 남긴 옛 행 포함)은 누구에게도 열리지 않는다."""
    history = _history()
    store, _bucket = _documents()
    meta = asyncio.run(
        store.put_generated_docx(
            tenant_id=SHARED_TENANT, filename="orphan.docx", body=b"ORPHAN-BYTES"
        )
    )

    app, a, b = _artifact_users(history, store)
    try:
        with a, b:
            first = a.get(f"/api/claw/manual-intake/artifact/{meta.document_id}")
            second = b.get(f"/api/claw/manual-intake/artifact/{meta.document_id}")
    finally:
        claw_routes._resolve_canonical_owner = _REAL_OWNER
        claw_artifact_preview_routes._resolve_canonical_owner = _REAL_OWNER_PREVIEW

    assert first.status_code == 404, first.text
    assert second.status_code == 404, second.text


def test_comparison_writes_no_document_row_at_all() -> None:
    """② 고정: 견적 비교는 아티팩트 저장소에 행을 남기지 않는다."""
    conn_pair = _db("008_claw_document_metadata.sql")
    store = WorkspaceDocumentStore(D1ClawDocumentMetadataStore(conn_pair), _Bucket())
    history = _history()
    app, a, _b = _artifact_users(history, store)

    from test_claw_quote_compare_http import (
        COMPARE_ROUTE,
        SUPPLIER_A,
        SUPPLIER_B,
        _payload,
    )

    try:
        with a:
            resp = a.post(
                COMPARE_ROUTE,
                json=_payload(SUPPLIER_A, SUPPLIER_B, artifact="docx"),
            )
            assert resp.status_code == 200, resp.text
            assert resp.headers["content-type"].startswith(
                "application/vnd.openxmlformats-officedocument"
            )
            rows = conn_pair.conn.execute(
                "SELECT COUNT(*) FROM claw_document_metadata"
            ).fetchone()[0]
    finally:
        claw_routes._resolve_canonical_owner = _REAL_OWNER
        claw_artifact_preview_routes._resolve_canonical_owner = _REAL_OWNER_PREVIEW

    assert rows == 0


_REAL_OWNER = claw_routes._resolve_canonical_owner
_REAL_OWNER_PREVIEW = claw_artifact_preview_routes._resolve_canonical_owner
