"""Network-free tests for durable explicitly user-approved Claw memory (#2331)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.testclient import TestClient

from app.app_factory import create_app
from app.approved_memory import (
    MAX_APPROVED_MEMORIES,
    ApprovedMemoryError,
    D1ApprovedMemoryStore,
    canonicalize_proposal,
)
from app.auth import SESSION_COOKIE, create_session_token
from app.config import Settings
from app.control_plane_identity import PADIEM_CHAT_PRODUCT_ID
from app.control_plane_identity_shadow import IdentityShadowRecord
from padiem_control_plane import (
    AuthSessionSnapshot,
    AuthSessionState,
    CanonicalSubjectRef,
    SubjectType,
)

APPROVE_PATH = "/api/claw/memory/approve"
REJECT_PATH = "/api/claw/memory/reject"
LIST_PATH = "/api/claw/memory"

SIGNED_IN_USER_ID = "usr_" + "7" * 32
OTHER_USER_ID = "usr_" + "f" * 32


def _google_settings(**overrides) -> Settings:
    values = {
        "runtime_mode": "mock",
        "auth_mode": "google",
        "public_base_url": "https://chat.example.test",
        "google_client_id": "claw-memory-client.apps.googleusercontent.com",
        "google_client_secret": "claw-memory-google-secret",
        "session_secret": "claw-memory-session-secret-not-a-real-cred-00",
        "session_max_age_seconds": 3600,
    }
    values.update(overrides)
    return Settings.from_values(**values)


def _make_identity_shadow_store(**overrides) -> MagicMock:
    store = MagicMock()
    now = datetime.now(timezone.utc)
    values = {
        "product_user_id": SIGNED_IN_USER_ID,
        "canonical_subject_id": "subject_test",
        "auth_session_id": "session_test123",
        "session_revision": 1,
        "session_state": "active",
        "session_expires_at": now + timedelta(hours=1),
        "observed_at": now,
    }
    values.update(overrides)
    record = IdentityShadowRecord(**values)
    store.load_projection = AsyncMock(return_value=record)
    return store


def _make_auth_session_snapshot(**overrides) -> AuthSessionSnapshot:
    now = datetime.now(timezone.utc)
    values = {
        "session_id": "session_test123",
        "product_id": PADIEM_CHAT_PRODUCT_ID,
        "subject": CanonicalSubjectRef(SubjectType.USER, "subject_test"),
        "issued_at": now - timedelta(hours=1),
        "expires_at": now + timedelta(hours=1),
        "state": AuthSessionState.ACTIVE,
        "revision": 1,
        "tenant_id": "tenant_test",
    }
    values.update(overrides)
    return AuthSessionSnapshot(**values)


def _make_authority(snapshot=None) -> MagicMock:
    authority = MagicMock()
    authority.resolve_auth_session = AsyncMock(
        return_value=snapshot if snapshot is not None else _make_auth_session_snapshot()
    )
    return authority


class _InMemoryApprovedStore:
    """Route-level fake: owner/workspace-scoped, hard-bounded, no real D1."""

    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}
        self.approve_calls = 0

    async def approve_memory(self, *, user_id, workspace_id, proposal) -> dict:
        from datetime import datetime as _dt, timezone as _tz

        self.approve_calls += 1
        now = _dt.now(_tz.utc).isoformat()
        memory_id = "mem_" + f"{len(self.rows):032x}"[-32:].replace(" ", "0")
        # Ensure unique hex suffix even for many rows.
        memory_id = "mem_" + ("%032x" % (len(self.rows) + 1))
        row = {
            "memory_id": memory_id,
            "workspace_id": workspace_id,
            "memory_type": proposal.memory_type,
            "name": proposal.name,
            "note": proposal.note,
            "source_channel": proposal.source_channel,
            "status": "approved",
            "created_at": now,
            "updated_at": now,
            "_user_id": user_id,
            "_workspace_id": workspace_id,
        }
        self.rows[memory_id] = row
        return {k: v for k, v in row.items() if not k.startswith("_")}

    async def list_approved_memories(self, *, user_id, workspace_id, limit=MAX_APPROVED_MEMORIES):
        bounded = max(1, min(int(limit), MAX_APPROVED_MEMORIES))
        matched = [
            {k: v for k, v in row.items() if not k.startswith("_")}
            for row in self.rows.values()
            if row["_user_id"] == user_id and row["_workspace_id"] == workspace_id
        ]
        return matched[:bounded]

    async def get_approved_memory(self, *, user_id, workspace_id, memory_id):
        row = self.rows.get(memory_id)
        if row is None or row["_user_id"] != user_id or row["_workspace_id"] != workspace_id:
            return None
        return {k: v for k, v in row.items() if not k.startswith("_")}


def _memory_client(store, *, user_id: str = SIGNED_IN_USER_ID) -> TestClient:
    settings = _google_settings()
    app = create_app(settings=settings, history_store=MagicMock(), approved_memory_store=store)
    app.state.identity_shadow_store = _make_identity_shadow_store(product_user_id=user_id)
    app.state.control_plane_identity_authority = _make_authority()
    client = TestClient(app, base_url="https://chat.example.test")
    client.cookies.set(
        SESSION_COOKIE,
        create_session_token(settings, user_id),
        domain="chat.example.test",
        path="/",
    )
    return client


def _anonymous_client(store) -> TestClient:
    settings = _google_settings()
    app = create_app(settings=settings, history_store=MagicMock(), approved_memory_store=store)
    app.state.identity_shadow_store = _make_identity_shadow_store()
    app.state.control_plane_identity_authority = _make_authority()
    return TestClient(app, base_url="https://chat.example.test")


_VALID_PROPOSAL = {"type": "customer_contact_candidate", "name": "A업체", "note": "채널 kakao 잠재 고객", "source_channel": "kakao"}


def test_routes_are_registered() -> None:
    app = create_app(Settings.from_values(runtime_mode="mock", live_enabled="false", auth_mode="off"))
    paths = {getattr(route, "path", None) for route in app.routes}
    assert "/api/claw/memory/approve" in paths
    assert "/api/claw/memory/reject" in paths
    assert "/api/claw/memory" in paths
    assert "/api/claw/memory/{memory_id}" in paths


def test_explicit_approval_persists_and_lists_for_same_owner() -> None:
    store = _InMemoryApprovedStore()
    client = _memory_client(store)
    resp = client.post(APPROVE_PATH, json={"proposal": dict(_VALID_PROPOSAL), "approved": True})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["memory"]["name"] == "A업체"
    assert body["memory"]["status"] == "approved"
    assert body["memory"]["memory_id"].startswith("mem_")

    listed = client.get(LIST_PATH)
    assert listed.status_code == 200
    memories = listed.json()["memories"]
    assert len(memories) == 1
    assert memories[0]["memory_id"] == body["memory"]["memory_id"]

    detail = client.get(f"/api/claw/memory/{body['memory']['memory_id']}")
    assert detail.status_code == 200
    assert detail.json()["memory"]["name"] == "A업체"


def test_same_proposal_without_explicit_approval_creates_no_row() -> None:
    store = _InMemoryApprovedStore()
    client = _memory_client(store)
    # Missing approval flag.
    resp = client.post(APPROVE_PATH, json={"proposal": dict(_VALID_PROPOSAL)})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "explicit_approval_required"
    # Explicit False is also rejected.
    resp2 = client.post(APPROVE_PATH, json={"proposal": dict(_VALID_PROPOSAL), "approved": False})
    assert resp2.status_code == 400
    assert store.approve_calls == 0
    assert client.get(LIST_PATH).json()["memories"] == []


def test_preview_does_not_create_approved_memory_row() -> None:
    store = _InMemoryApprovedStore()
    client = _memory_client(store)
    preview = client.post(
        "/api/claw/manual-intake/preview",
        json={"content": "견적 요청 테스트.", "channel": "kakao", "action": "quote", "sender_hint": "A업체"},
    )
    assert preview.status_code == 200
    assert store.approve_calls == 0
    assert client.get(LIST_PATH).json()["memories"] == []


def test_rejection_creates_no_durable_row() -> None:
    store = _InMemoryApprovedStore()
    client = _memory_client(store)
    resp = client.post(REJECT_PATH, json={"proposal": dict(_VALID_PROPOSAL)})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "persisted": False}
    assert store.approve_calls == 0
    assert client.get(LIST_PATH).json()["memories"] == []


def test_anonymous_cannot_approve_list_or_read() -> None:
    store = _InMemoryApprovedStore()
    client = _anonymous_client(store)
    assert client.post(APPROVE_PATH, json={"proposal": dict(_VALID_PROPOSAL), "approved": True}).status_code == 401
    assert client.post(REJECT_PATH, json={"proposal": dict(_VALID_PROPOSAL)}).status_code == 401
    assert client.get(LIST_PATH).status_code == 401
    assert client.get("/api/claw/memory/mem_" + "0" * 32).status_code == 401
    assert store.approve_calls == 0


def test_owner_isolation_and_nondisclosing_detail() -> None:
    store = _InMemoryApprovedStore()
    owner_a = _memory_client(store, user_id=SIGNED_IN_USER_ID)
    owner_b = _memory_client(store, user_id=OTHER_USER_ID)
    created = owner_a.post(APPROVE_PATH, json={"proposal": dict(_VALID_PROPOSAL), "approved": True}).json()["memory"]
    memory_id = created["memory_id"]

    # Owner B lists nothing and cannot observe owner A memory.
    assert owner_b.get(LIST_PATH).json()["memories"] == []
    foreign = owner_b.get(f"/api/claw/memory/{memory_id}")
    missing = owner_b.get("/api/claw/memory/mem_" + "1" * 32)
    assert foreign.status_code == 404
    assert missing.status_code == 404
    assert foreign.json() == missing.json()
    assert foreign.json() == {"ok": False, "error": {"code": "approved_memory_not_found", "message": "메모리를 찾을 수 없습니다."}}
    assert OTHER_USER_ID not in owner_a.get(LIST_PATH).text
    assert SIGNED_IN_USER_ID not in owner_b.get(LIST_PATH).text


def test_hard_list_bound() -> None:
    store = _InMemoryApprovedStore()
    client = _memory_client(store)
    for i in range(5):
        proposal = {"type": "organization_candidate", "name": f"업체{i}", "source_channel": "email"}
        assert client.post(APPROVE_PATH, json={"proposal": proposal, "approved": True}).status_code == 200
    resp = client.get(f"{LIST_PATH}?limit=9999")
    assert resp.status_code == 200
    assert len(resp.json()["memories"]) <= MAX_APPROVED_MEMORIES
    assert client.get(f"{LIST_PATH}?limit=abc").status_code == 400
    assert client.get(f"{LIST_PATH}?limit=0").status_code == 400


def test_malformed_and_oversized_proposal_fails_closed() -> None:
    store = _InMemoryApprovedStore()
    client = _memory_client(store)
    assert client.post(APPROVE_PATH, json={"proposal": {"type": "bad type!", "name": "A"}, "approved": True}).status_code == 400
    assert client.post(APPROVE_PATH, json={"proposal": {"type": "t", "name": "   "}, "approved": True}).status_code == 400
    assert client.post(APPROVE_PATH, json={"proposal": {"type": "t", "name": "A" * 500}, "approved": True}).status_code == 400
    assert client.post(APPROVE_PATH, json={"proposal": {"type": "t", "name": "A", "note": "n" * 5000}, "approved": True}).status_code == 400
    assert client.post(APPROVE_PATH, json={"proposal": {"type": "t", "name": "A", "source_channel": "evil"}, "approved": True}).status_code == 400
    assert client.post(APPROVE_PATH, json={"proposal": "not-a-dict", "approved": True}).status_code == 400
    assert store.approve_calls == 0


def test_caller_supplied_owner_fields_forbidden() -> None:
    store = _InMemoryApprovedStore()
    client = _memory_client(store)
    smuggled = dict(_VALID_PROPOSAL, user_id=OTHER_USER_ID)
    assert client.post(APPROVE_PATH, json={"proposal": smuggled, "approved": True}).status_code == 400
    assert client.post(APPROVE_PATH, json={"proposal": dict(_VALID_PROPOSAL), "approved": True, "user_id": OTHER_USER_ID}).status_code == 400
    assert client.post(APPROVE_PATH, json={"proposal": dict(_VALID_PROPOSAL), "approved": True, "tenant_id": "tenant_evil"}).status_code == 400
    assert store.approve_calls == 0


def test_storage_failure_fails_closed_without_claiming_persistence() -> None:
    class _FailingStore(_InMemoryApprovedStore):
        async def approve_memory(self, **kwargs):
            raise RuntimeError("d1 write down")

        async def list_approved_memories(self, **kwargs):
            raise RuntimeError("d1 read down")

    client = _memory_client(_FailingStore())
    resp = client.post(APPROVE_PATH, json={"proposal": dict(_VALID_PROPOSAL), "approved": True})
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "approved_memory_write_failed"
    assert "memory_id" not in resp.text
    assert client.get(LIST_PATH).status_code == 503


def test_missing_store_fails_closed() -> None:
    settings = _google_settings()
    app = create_app(settings=settings, history_store=MagicMock(), approved_memory_store=None)
    # Explicitly unbind: no D1-derived store in this unit composition.
    app.state.approved_memory_store = None
    app.state.identity_shadow_store = _make_identity_shadow_store()
    app.state.control_plane_identity_authority = _make_authority()
    client = TestClient(app, base_url="https://chat.example.test")
    client.cookies.set(SESSION_COOKIE, create_session_token(settings, SIGNED_IN_USER_ID), domain="chat.example.test", path="/")
    assert client.post(APPROVE_PATH, json={"proposal": dict(_VALID_PROPOSAL), "approved": True}).status_code == 503
    assert client.get(LIST_PATH).status_code == 503


def test_no_sensitive_material_in_projection() -> None:
    store = _InMemoryApprovedStore()
    client = _memory_client(store)
    hostile = dict(
        _VALID_PROPOSAL,
        raw_content="Pasted secret raw text",
        prompt="prompt bytes",
        reasoning="hidden reasoning",
        secret="provider-secret-value",
        session_cookie="session-cookie-value",
        oauth_token="oauth-token-value",
        object_key="workspaces/tenant/object",
        artifact_bytes="bytes",
    )
    resp = client.post(APPROVE_PATH, json={"proposal": hostile, "approved": True})
    assert resp.status_code == 200
    text = resp.text + client.get(LIST_PATH).text
    for marker in ("Pasted secret raw text", "hidden reasoning", "provider-secret-value", "session-cookie-value", "oauth-token-value", "workspaces/tenant"):
        assert marker not in text
    memory = resp.json()["memory"]
    assert set(memory) == {"memory_id", "workspace_id", "memory_type", "name", "note", "source_channel", "status", "created_at", "updated_at"}


def test_model_output_alone_cannot_self_approve() -> None:
    # No signed-in session: even a well-formed approved payload is rejected.
    store = _InMemoryApprovedStore()
    client = _anonymous_client(store)
    resp = client.post(APPROVE_PATH, json={"proposal": dict(_VALID_PROPOSAL), "approved": True})
    assert resp.status_code == 401
    assert store.approve_calls == 0


def test_invalid_memory_id_and_unavailable_store_shapes() -> None:
    store = _InMemoryApprovedStore()
    client = _memory_client(store)
    assert client.get("/api/claw/memory/not-a-memory-id").status_code == 400


def test_anonymous_phase_a_reply_and_summary_unchanged() -> None:
    settings = Settings.from_values(runtime_mode="mock", live_enabled="false", auth_mode="off")
    app = create_app(settings=settings)
    client = TestClient(app)
    for action in ("reply", "summary"):
        resp = client.post(
            "/api/claw/manual-intake/preview",
            json={"content": "Phase A 내용.", "channel": "sms", "action": action},
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True


# ── Direct D1 store tests (prepared binds only, no DDL at runtime) ───────────


class _MemoryStatement:
    def __init__(self, db, sql):
        self.db = db
        self.sql = sql
        self.values: tuple = ()

    def bind(self, *values):
        self.values = values
        return self

    async def first(self):
        if self.sql.startswith("SELECT id, workspace_id, memory_type"):
            memory_id, user_id, workspace_id = self.values
            for row in self.db.rows:
                if row["id"] == memory_id and row["user_id"] == user_id and row["workspace_id"] == workspace_id:
                    return {k: v for k, v in row.items() if k != "user_id"}
            return None
        return None

    async def run(self):
        self.db.bound.append((self.sql, self.values))
        if self.sql.startswith("INSERT INTO claw_approved_memory"):
            cols = ("id", "user_id", "workspace_id", "memory_type", "name", "note", "source_channel", "status", "created_at", "updated_at")
            # status is a literal in SQL text; values exclude it.
            (memory_id, user_id, workspace_id, memory_type, name, note, source_channel, created_at, updated_at) = self.values
            self.db.rows.append({
                "id": memory_id, "user_id": user_id, "workspace_id": workspace_id,
                "memory_type": memory_type, "name": name, "note": note,
                "source_channel": source_channel, "status": "approved",
                "created_at": created_at, "updated_at": updated_at,
            })
            return {"results": []}
        if self.sql.startswith("SELECT id, workspace_id, memory_type"):
            user_id, workspace_id, limit = self.values
            rows = [r for r in self.db.rows if r["user_id"] == user_id and r["workspace_id"] == workspace_id]
            rows.sort(key=lambda r: r["created_at"], reverse=True)
            return {"results": [{k: v for k, v in r.items() if k != "user_id"} for r in rows[:limit]]}
        return {"results": []}


class _MemoryD1:
    def __init__(self):
        self.rows: list[dict] = []
        self.bound: list[tuple] = []
        self.prepared: list[str] = []

    def prepare(self, sql):
        self.prepared.append(sql)
        return _MemoryStatement(self, sql)


@pytest.mark.asyncio
async def test_d1_approve_lists_owner_workspace_scoped_and_bounded() -> None:
    store = D1ApprovedMemoryStore(_MemoryD1())
    proposal = canonicalize_proposal(dict(_VALID_PROPOSAL))
    created = await store.approve_memory(user_id="usr_owner", workspace_id="ws_1", proposal=proposal)
    assert created["memory_id"].startswith("mem_")
    assert created["workspace_id"] == "ws_1"
    other = canonicalize_proposal({"type": "organization_candidate", "name": "B", "source_channel": "email"})
    await store.approve_memory(user_id="usr_other", workspace_id="ws_1", proposal=other)
    await store.approve_memory(user_id="usr_owner", workspace_id="ws_2", proposal=other)
    own = await store.list_approved_memories(user_id="usr_owner", workspace_id="ws_1", limit=999)
    assert len(own) == 1
    assert len(await store.list_approved_memories(user_id="usr_owner", workspace_id="ws_1", limit=999)) <= MAX_APPROVED_MEMORIES
    assert all("user_id" not in row for row in own)
    assert all("usr_owner" not in sql and "ws_1" not in sql for sql in store.db.prepared)


@pytest.mark.asyncio
async def test_d1_detail_is_nondisclosing_for_foreign_record() -> None:
    store = D1ApprovedMemoryStore(_MemoryD1())
    created = await store.approve_memory(
        user_id="usr_owner", workspace_id="ws_1", proposal=canonicalize_proposal(dict(_VALID_PROPOSAL))
    )
    assert await store.get_approved_memory(user_id="usr_owner", workspace_id="ws_1", memory_id=created["memory_id"]) is not None
    assert await store.get_approved_memory(user_id="usr_other", workspace_id="ws_1", memory_id=created["memory_id"]) is None
    assert await store.get_approved_memory(user_id="usr_owner", workspace_id="ws_2", memory_id=created["memory_id"]) is None


def test_migration_011_is_additive_and_public_safe() -> None:
    migration = (Path(__file__).resolve().parents[1] / "migrations" / "011_claw_approved_memory.sql").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS claw_approved_memory" in migration
    assert "user_id TEXT NOT NULL" in migration
    assert "workspace_id TEXT NOT NULL" in migration
    for forbidden in ("raw_content", "prompt", "secret", "token", "cookie", "object_key"):
        assert forbidden not in migration.lower()


def test_no_runtime_ddl_or_retrieval_machinery_in_new_modules() -> None:
    for filename in ("approved_memory.py", "claw_memory_routes.py"):
        source = (Path(__file__).resolve().parents[1] / "app" / filename).read_text(encoding="utf-8")
        assert "CREATE TABLE" not in source
        for forbidden in ("embedding", "vector_db", "rag_", "cosine", "top_k", "top-k"):
            assert forbidden not in source.lower()
    migration_names = sorted(p.name for p in (Path(__file__).resolve().parents[1] / "migrations").glob("*.sql"))
    assert "011_claw_approved_memory.sql" in migration_names
    # 010_claw_task_alert.sql is a separately reserved migration (#2328) and is
    # intentionally not asserted absent here; #2331 owns only migration 011.
