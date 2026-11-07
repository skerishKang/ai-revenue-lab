"""#2952 follow-up sweep: a read is scoped by its owner, not by the tenant.

`app/claw_memory_routes.py::_resolve_memory_workspace` resolves the canonical
Control Plane **tenant** id, so one workspace holds several product users.

These tests use the real D1 SQL (sqlite), real signed-in session cookies and two
users forced into the *same* tenant — the exact condition a tenant-only scope
hides.

2026-11-07: the Claw task/alert inbox half of this sweep was removed with the
inbox itself (대표 결정 2026-11-07, 작업함 제거). The document/artifact
owner-scope half stays.
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
from app import claw_routes
from app.app_factory import create_app
from app.auth import SESSION_COOKIE, create_session_token
from app.auth_routes import current_user_id
from app.history import D1HistoryStore
from app.workspace_storage import (
    DOCX_MEDIA_TYPE,
    D1ClawDocumentMetadataStore,
    WorkspaceDocumentStore,
)

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


class _NoCalendarStore:
    """The calendar rows are #6120's scope; the document half needs no store."""

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
            D1ClawDocumentMetadataStore(
                _db(
                    "008_claw_document_metadata.sql",
                    "080_claw_document_metadata_user_id.sql",
                )
            ),
            bucket,
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
            tenant_id=SHARED_TENANT, user_id=USER_A,
            filename="a-report.docx", body=b"A-PRIVATE-BYTES",
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
            tenant_id=SHARED_TENANT, user_id=USER_A,
            filename="orphan.docx", body=b"ORPHAN-BYTES",
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
    conn_pair = _db(
        "008_claw_document_metadata.sql", "080_claw_document_metadata_user_id.sql",
    )
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


# --- #6323: the generated-document row carries its owner ---------------------

def _owner_documents() -> tuple[WorkspaceDocumentStore, _D1]:
    db = _db(
        "008_claw_document_metadata.sql", "080_claw_document_metadata_user_id.sql",
    )
    return WorkspaceDocumentStore(D1ClawDocumentMetadataStore(db), _Bucket()), db


def test_a_generated_document_reads_only_for_the_user_who_minted_it() -> None:
    store, _ = _owner_documents()
    saved = asyncio.run(store.put_generated_docx(
        tenant_id=SHARED_TENANT, user_id=USER_A, filename="a.docx", body=b"A-BYTES",
    ))

    own = asyncio.run(store.get_for_tenant(
        tenant_id=SHARED_TENANT, document_id=saved.document_id, user_id=USER_A,
    ))
    mate = asyncio.run(store.get_for_tenant(
        tenant_id=SHARED_TENANT, document_id=saved.document_id, user_id=USER_B,
    ))

    assert own is not None and own[1] == b"A-BYTES"
    assert mate is None


def test_a_row_with_no_owner_is_refused_for_everyone() -> None:
    """A pre-080 row keeps user_id NULL, and an unproven owner is not an owner."""
    store, db = _owner_documents()
    doc_id = "doc_" + "c" * 32
    db.conn.execute(
        "INSERT INTO claw_document_metadata "
        "(document_id, tenant_id, object_key, filename, media_type, byte_length, created_at, expires_at, deleted_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)",
        (
            doc_id, SHARED_TENANT,
            f"workspaces/{SHARED_TENANT}/claw/documents/{doc_id}/orphan.docx",
            "orphan.docx", DOCX_MEDIA_TYPE, 10,
            BASE.isoformat(), (BASE + timedelta(days=30)).isoformat(),
        ),
    )

    for user in (USER_A, USER_B):
        assert asyncio.run(store.get_for_tenant(
            tenant_id=SHARED_TENANT, document_id=doc_id, user_id=user,
        )) is None


def test_a_generated_document_cannot_be_stored_without_an_owner() -> None:
    store, _ = _owner_documents()
    with pytest.raises(ValueError):
        asyncio.run(store.put_generated_docx(
            tenant_id=SHARED_TENANT, user_id="", filename="a.docx", body=b"A-BYTES",
        ))


_REAL_OWNER = claw_routes._resolve_canonical_owner
_REAL_OWNER_PREVIEW = claw_artifact_preview_routes._resolve_canonical_owner
