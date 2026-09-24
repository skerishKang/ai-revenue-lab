from __future__ import annotations

import asyncio
import base64
import importlib.util
import sqlite3
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from identity_authority_durable import (
    CloudflareCanonicalIdentityAuthorityStore,
    _rows,
    decode_identity_lookup_key,
)
from padiem_control_plane.contracts import (
    CanonicalSubjectRef,
    ControlPlaneContractError,
    SubjectType,
)
from padiem_control_plane.tenants import (
    CanonicalTenantState,
    TenantMembershipRole,
    TenantMembershipState,
)

NOW = datetime(2026, 9, 4, 13, 0, tzinfo=timezone.utc)
LOOKUP_KEY_BYTES = b"I" * 32
LOOKUP_KEY = base64.urlsafe_b64encode(LOOKUP_KEY_BYTES).decode("ascii").rstrip("=")
PROVIDER_SUBJECT = "google-provider-subject-sensitive-123"
PRODUCT_ID = "b62"


class _FakeResponse:
    def __init__(self, body="", *, status=200, headers=None):
        self.body = body
        self.status = status
        self.headers = headers or {}


class _FakeWorkerEntrypoint:
    def __init__(self, env=None):
        self.env = env


class _FakeDurableObject:
    def __init__(self, ctx, env):
        self.ctx = ctx
        self.env = env


_workers = types.ModuleType("workers")
_workers.Response = _FakeResponse
_workers.WorkerEntrypoint = _FakeWorkerEntrypoint
_workers.DurableObject = _FakeDurableObject
sys.modules.setdefault("workers", _workers)

_worker_path = Path(__file__).parents[1] / "identity_authority_worker.py"
_worker_spec = importlib.util.spec_from_file_location(
    "padiem_identity_authority_worker_test", _worker_path
)
assert _worker_spec is not None and _worker_spec.loader is not None
_worker_mod = importlib.util.module_from_spec(_worker_spec)
sys.modules[_worker_spec.name] = _worker_mod
_worker_spec.loader.exec_module(_worker_mod)


class _FakeEnv:
    def __init__(self) -> None:
        self.CONTROL_PLANE_ALLOWED_PRODUCTS = "b62,b54-padiem-claw"
        self.CONTROL_PLANE_IDENTITY = _FakeNamespace()


class _FakeNamespace:
    def idFromName(self, name: str):
        return _FakeObjectId(name)

    def get(self, object_id):
        return _FakeStub()


class _FakeObjectId:
    def __init__(self, name: str) -> None:
        self.name = name


class _FakeStub:
    async def resolve_or_create_product_link(self, payload):
        return {"ok": True, "link": {}}

    async def establish_auth_session(self, payload):
        return {"ok": True, "session": {}}

    async def resolve_auth_session(self, payload):
        return {"ok": True, "session": {}}

    async def issue_google_connect_ticket(self, payload):
        return {"ok": True, "ticket": {}}

    async def create_tenant(self, payload):
        return {"ok": True, "tenant": {}}

    async def get_tenant(self, payload):
        return {"ok": True, "tenant": {}}

    async def assign_tenant_membership(self, payload):
        return {"ok": True, "membership": {}}

    async def revoke_tenant_membership(self, payload):
        return {"ok": True, "membership": {}}

    async def resolve_active_memberships(self, payload):
        return {"ok": True, "tenant_ids": []}

    async def resolve_active_tenant_membership(self, payload):
        return {"ok": True, "membership": {}}


class FakeCursor:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def toArray(self) -> list[dict]:
        return list(self._rows)


class FakeSql:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def exec(self, statement: str, *args):
        cursor = self._connection.execute(statement, args)
        if cursor.description is not None:
            columns = [item[0] for item in cursor.description]
            rows = [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
            return FakeCursor(rows)
        return FakeCursor([])


class FakeStorage:
    def __init__(self) -> None:
        self.connection = sqlite3.connect(":memory:", isolation_level=None)
        self.sql = FakeSql(self.connection)

    def transactionSync(self, operation):
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            result = operation()
        except Exception:
            self.connection.execute("ROLLBACK")
            raise
        self.connection.execute("COMMIT")
        return result


def _make_store() -> CloudflareCanonicalIdentityAuthorityStore:
    return CloudflareCanonicalIdentityAuthorityStore(
        FakeStorage(),
        lookup_key=decode_identity_lookup_key(LOOKUP_KEY),
        allowed_product_ids=frozenset({PRODUCT_ID}),
    )


def _create_subject(store: CloudflareCanonicalIdentityAuthorityStore) -> None:
    store._sql.exec(
        "INSERT INTO canonical_identity_subject (provider, provider_fingerprint, canonical_subject_id, created_at) VALUES (?, ?, ?, ?)",
        "google",
        PROVIDER_SUBJECT,
        "sub_test_subject_001",
        NOW.isoformat().replace("+00:00", "Z"),
    )


def _create_product_link(store: CloudflareCanonicalIdentityAuthorityStore) -> None:
    store._sql.exec(
        "INSERT INTO canonical_product_identity_link (product_id, product_user_id, canonical_subject_id, state, created_at) VALUES (?, ?, ?, ?, ?)",
        PRODUCT_ID,
        "user_001",
        "sub_test_subject_001",
        "active",
        NOW.isoformat().replace("+00:00", "Z"),
    )


def test_membership_create_and_resolve() -> None:
    store = _make_store()
    _create_subject(store)
    tenant = store.create_tenant(now=NOW)
    membership = store.assign_tenant_membership(
        tenant_id=tenant.tenant_id,
        canonical_subject_id="sub_test_subject_001",
        now=NOW,
    )
    assert membership.tenant_id == tenant.tenant_id
    assert membership.state is TenantMembershipState.ACTIVE
    tenant_ids = store._active_membership_tenant_ids("sub_test_subject_001")
    assert tenant_ids == [tenant.tenant_id]


def test_zero_single_multiple_session_tenant() -> None:
    store = _make_store()
    _create_subject(store)
    _create_product_link(store)
    session0 = store.establish_auth_session(
        product_id=PRODUCT_ID,
        subject=CanonicalSubjectRef(subject_type=SubjectType.USER, subject_id="sub_test_subject_001"),
        authenticated_at=NOW,
        not_after=NOW + timedelta(hours=1),
        now=NOW,
    )
    assert session0.tenant_id is None
    tenant = store.create_tenant(now=NOW)
    store.assign_tenant_membership(
        tenant_id=tenant.tenant_id,
        canonical_subject_id="sub_test_subject_001",
        now=NOW,
    )
    session1 = store.establish_auth_session(
        product_id=PRODUCT_ID,
        subject=CanonicalSubjectRef(subject_type=SubjectType.USER, subject_id="sub_test_subject_001"),
        authenticated_at=NOW,
        not_after=NOW + timedelta(hours=1),
        now=NOW,
    )
    assert session1.tenant_id == tenant.tenant_id
    tenant2 = store.create_tenant(now=NOW)
    store.assign_tenant_membership(
        tenant_id=tenant2.tenant_id,
        canonical_subject_id="sub_test_subject_001",
        now=NOW,
    )
    session2 = store.establish_auth_session(
        product_id=PRODUCT_ID,
        subject=CanonicalSubjectRef(subject_type=SubjectType.USER, subject_id="sub_test_subject_001"),
        authenticated_at=NOW,
        not_after=NOW + timedelta(hours=1),
        now=NOW,
    )
    assert session2.tenant_id is None


def test_inactive_membership_not_selected() -> None:
    store = _make_store()
    _create_subject(store)
    _create_product_link(store)
    tenant = store.create_tenant(now=NOW)
    store.assign_tenant_membership(
        tenant_id=tenant.tenant_id,
        canonical_subject_id="sub_test_subject_001",
        now=NOW,
    )
    store.revoke_tenant_membership(
        tenant_id=tenant.tenant_id,
        canonical_subject_id="sub_test_subject_001",
        now=NOW,
    )
    session = store.establish_auth_session(
        product_id=PRODUCT_ID,
        subject=CanonicalSubjectRef(subject_type=SubjectType.USER, subject_id="sub_test_subject_001"),
        authenticated_at=NOW,
        not_after=NOW + timedelta(hours=1),
        now=NOW,
    )
    assert session.tenant_id is None


def test_tenant_alias_subject_rejected() -> None:
    store = _make_store()
    _create_subject(store)
    with pytest.raises(ControlPlaneContractError):
        store.assign_tenant_membership(
            tenant_id="sub_test_subject_001",
            canonical_subject_id="sub_test_subject_001",
            now=NOW,
        )


def test_request_asserted_tenant_rejected() -> None:
    with pytest.raises(ControlPlaneContractError):
        _worker_mod._closed(
            {
                "product_id": PRODUCT_ID,
                "subject": {"subject_type": "user", "subject_id": "sub_test_subject_001"},
                "authenticated_at": NOW.isoformat().replace("+00:00", "Z"),
                "not_after": (NOW + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
                "tenant_id": "tenant_fake_asserted_by_caller",
            },
            _worker_mod._SESSION_KEYS,
            "auth-session RPC",
        )


def test_session_tenant_persistence_roundtrip() -> None:
    store = _make_store()
    _create_subject(store)
    _create_product_link(store)
    tenant = store.create_tenant(now=NOW)
    store.assign_tenant_membership(
        tenant_id=tenant.tenant_id,
        canonical_subject_id="sub_test_subject_001",
        now=NOW,
    )
    session = store.establish_auth_session(
        product_id=PRODUCT_ID,
        subject=CanonicalSubjectRef(subject_type=SubjectType.USER, subject_id="sub_test_subject_001"),
        authenticated_at=NOW,
        not_after=NOW + timedelta(hours=1),
        now=NOW,
    )
    resolved = store.resolve_auth_session(session_id=session.session_id)
    assert resolved.tenant_id == tenant.tenant_id


def test_legacy_session_rows_migrate_with_null_tenant() -> None:
    storage = FakeStorage()
    storage.connection.execute(
        "CREATE TABLE canonical_identity_subject ("
        "provider TEXT NOT NULL, provider_fingerprint TEXT NOT NULL, "
        "canonical_subject_id TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL, "
        "PRIMARY KEY(provider, provider_fingerprint))"
    )
    storage.connection.execute(
        "CREATE TABLE canonical_product_identity_link ("
        "product_id TEXT NOT NULL, product_user_id TEXT NOT NULL, "
        "canonical_subject_id TEXT NOT NULL, state TEXT NOT NULL, created_at TEXT NOT NULL, "
        "PRIMARY KEY(product_id, product_user_id))"
    )
    storage.connection.execute(
        "CREATE INDEX idx_canonical_product_link_subject ON canonical_product_identity_link(product_id, canonical_subject_id)"
    )
    storage.connection.execute(
        "CREATE TABLE canonical_auth_session ("
        "session_id TEXT PRIMARY KEY, product_id TEXT NOT NULL, "
        "subject_type TEXT NOT NULL, subject_id TEXT NOT NULL, "
        "issued_at TEXT NOT NULL, expires_at TEXT NOT NULL, "
        "state TEXT NOT NULL, revision INTEGER NOT NULL)"
    )
    storage.connection.execute(
        "CREATE INDEX idx_canonical_auth_session_subject ON canonical_auth_session(product_id, subject_id)"
    )
    storage.connection.execute(
        "INSERT INTO canonical_auth_session VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("legacy_session_001", PRODUCT_ID, "user", "sub_legacy", NOW.isoformat().replace("+00:00", "Z"),
         (NOW + timedelta(hours=1)).isoformat().replace("+00:00", "Z"), "active", 1),
    )
    store = CloudflareCanonicalIdentityAuthorityStore(
        storage,
        lookup_key=decode_identity_lookup_key(LOOKUP_KEY),
        allowed_product_ids=frozenset({PRODUCT_ID}),
    )
    rows = _rows(store._sql.exec("PRAGMA table_info(canonical_auth_session)"))
    column_names = {str(row["name"]) for row in rows}
    assert "tenant_id" in column_names
    resolved = store.resolve_auth_session(session_id="legacy_session_001")
    assert resolved.tenant_id is None


def test_migration_idempotent_or_restart_safe() -> None:
    store = _make_store()
    store._sql.exec(
        "INSERT INTO identity_authority_schema (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        "schema_version",
        "2",
    )
    store._apply_migrations()
    assert store._schema_version() == 3


def test_legacy_membership_schema_adds_nullable_role_without_backfill() -> None:
    storage = FakeStorage()
    initial = CloudflareCanonicalIdentityAuthorityStore(
        storage,
        lookup_key=decode_identity_lookup_key(LOOKUP_KEY),
        allowed_product_ids=frozenset({PRODUCT_ID}),
    )
    initial._sql.exec("DROP TABLE canonical_tenant_membership")
    storage.connection.execute(
        "CREATE TABLE canonical_tenant_membership ("
        "tenant_id TEXT NOT NULL, canonical_subject_id TEXT NOT NULL, "
        "state TEXT NOT NULL, created_at TEXT NOT NULL, "
        "PRIMARY KEY(tenant_id, canonical_subject_id))"
    )
    storage.connection.execute(
        "INSERT INTO canonical_tenant_membership VALUES (?, ?, ?, ?)",
        (
            "tenant_0123456789abcdef0123456789abcdef",
            "sub_legacy",
            "active",
            NOW.isoformat().replace("+00:00", "Z"),
        ),
    )
    initial._sql.exec(
        "INSERT INTO identity_authority_schema (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        "schema_version",
        "2",
    )
    migrated = CloudflareCanonicalIdentityAuthorityStore(
        storage,
        lookup_key=decode_identity_lookup_key(LOOKUP_KEY),
        allowed_product_ids=frozenset({PRODUCT_ID}),
    )
    row = _rows(
        migrated._sql.exec(
            "SELECT role FROM canonical_tenant_membership "
            "WHERE tenant_id=? AND canonical_subject_id=?",
            "tenant_0123456789abcdef0123456789abcdef",
            "sub_legacy",
        )
    )[0]
    assert row["role"] is None
    assert migrated._schema_version() == 3


def test_existing_session_contract_compatibility() -> None:
    store = _make_store()
    _create_subject(store)
    _create_product_link(store)
    session_no_tenant = store.establish_auth_session(
        product_id=PRODUCT_ID,
        subject=CanonicalSubjectRef(subject_type=SubjectType.USER, subject_id="sub_test_subject_001"),
        authenticated_at=NOW,
        not_after=NOW + timedelta(hours=1),
        now=NOW,
    )
    assert len(session_no_tenant.to_public_dict()) == 7
    tenant = store.create_tenant(now=NOW)
    store.assign_tenant_membership(
        tenant_id=tenant.tenant_id,
        canonical_subject_id="sub_test_subject_001",
        now=NOW,
    )
    session_with_tenant = store.establish_auth_session(
        product_id=PRODUCT_ID,
        subject=CanonicalSubjectRef(subject_type=SubjectType.USER, subject_id="sub_test_subject_001"),
        authenticated_at=NOW,
        not_after=NOW + timedelta(hours=1),
        now=NOW,
    )
    assert len(session_with_tenant.to_public_dict()) == 8
    assert session_with_tenant.to_public_dict()["tenant_id"] == tenant.tenant_id


def test_membership_role_schema_has_no_default() -> None:
    store = _make_store()
    rows = _rows(store._sql.exec("PRAGMA table_info(canonical_tenant_membership)"))
    role_column = next(row for row in rows if row["name"] == "role")
    assert role_column["dflt_value"] is None


def test_role_bearing_sessionless_resolver_returns_explicit_membership() -> None:
    store = _make_store()
    _create_subject(store)
    tenant = store.create_tenant(now=NOW)
    store.assign_tenant_membership(
        tenant_id=tenant.tenant_id,
        canonical_subject_id="sub_test_subject_001",
        now=NOW,
        role=TenantMembershipRole.OPERATOR,
    )
    membership = store.resolve_active_tenant_membership(
        tenant_id=tenant.tenant_id,
        canonical_subject_id="sub_test_subject_001",
        now=NOW,
    )
    assert membership.tenant_id == tenant.tenant_id
    assert membership.canonical_subject_id == "sub_test_subject_001"
    assert membership.role is TenantMembershipRole.OPERATOR


def test_legacy_roleless_membership_is_not_background_eligible() -> None:
    store = _make_store()
    _create_subject(store)
    tenant = store.create_tenant(now=NOW)
    store.assign_tenant_membership(
        tenant_id=tenant.tenant_id,
        canonical_subject_id="sub_test_subject_001",
        now=NOW,
    )
    with pytest.raises(ControlPlaneContractError) as raised:
        store.resolve_active_tenant_membership(
            tenant_id=tenant.tenant_id,
            canonical_subject_id="sub_test_subject_001",
            now=NOW,
        )
    assert raised.value.code == "canonical_tenant_membership_role_missing"


def test_sessionless_resolver_rejects_inactive_tenant() -> None:
    store = _make_store()
    _create_subject(store)
    tenant = store.create_tenant(now=NOW)
    store.assign_tenant_membership(
        tenant_id=tenant.tenant_id,
        canonical_subject_id="sub_test_subject_001",
        now=NOW,
        role=TenantMembershipRole.OWNER,
    )
    store._sql.exec(
        "UPDATE canonical_tenant SET state=? WHERE tenant_id=?",
        CanonicalTenantState.INACTIVE.value,
        tenant.tenant_id,
    )
    with pytest.raises(ControlPlaneContractError) as raised:
        store.resolve_active_tenant_membership(
            tenant_id=tenant.tenant_id,
            canonical_subject_id="sub_test_subject_001",
            now=NOW,
        )
    assert raised.value.code == "canonical_tenant_inactive"


def test_sessionless_resolver_rejects_inactive_membership() -> None:
    store = _make_store()
    _create_subject(store)
    tenant = store.create_tenant(now=NOW)
    store.assign_tenant_membership(
        tenant_id=tenant.tenant_id,
        canonical_subject_id="sub_test_subject_001",
        now=NOW,
        role=TenantMembershipRole.OWNER,
    )
    store.revoke_tenant_membership(
        tenant_id=tenant.tenant_id,
        canonical_subject_id="sub_test_subject_001",
        now=NOW,
    )
    with pytest.raises(ControlPlaneContractError) as raised:
        store.resolve_active_tenant_membership(
            tenant_id=tenant.tenant_id,
            canonical_subject_id="sub_test_subject_001",
            now=NOW,
        )
    assert raised.value.code == "canonical_tenant_membership_inactive"


def test_sessionless_resolver_rejects_missing_membership() -> None:
    store = _make_store()
    _create_subject(store)
    tenant = store.create_tenant(now=NOW)
    with pytest.raises(ControlPlaneContractError) as raised:
        store.resolve_active_tenant_membership(
            tenant_id=tenant.tenant_id,
            canonical_subject_id="sub_test_subject_001",
            now=NOW,
        )
    assert raised.value.code == "canonical_tenant_membership_not_found"


def test_sessionless_resolver_rejects_missing_canonical_subject() -> None:
    store = _make_store()
    tenant = store.create_tenant(now=NOW)
    store._sql.exec(
        "INSERT INTO canonical_tenant_membership "
        "(tenant_id, canonical_subject_id, state, created_at, role) VALUES (?, ?, ?, ?, ?)",
        tenant.tenant_id,
        "sub_missing",
        "active",
        NOW.isoformat().replace("+00:00", "Z"),
        "owner",
    )
    with pytest.raises(ControlPlaneContractError) as raised:
        store.resolve_active_tenant_membership(
            tenant_id=tenant.tenant_id,
            canonical_subject_id="sub_missing",
            now=NOW,
        )
    assert raised.value.code == "canonical_subject_not_found"


def test_sessionless_resolver_rejects_malformed_identifiers() -> None:
    store = _make_store()
    with pytest.raises(ControlPlaneContractError) as tenant_error:
        store.resolve_active_tenant_membership(
            tenant_id="tenant_bad",
            canonical_subject_id="sub_test_subject_001",
            now=NOW,
        )
    assert tenant_error.value.code == "invalid_canonical_tenant"
    with pytest.raises(ControlPlaneContractError) as subject_error:
        store.resolve_active_tenant_membership(
            tenant_id="tenant_0123456789abcdef0123456789abcdef",
            canonical_subject_id="bad subject",
            now=NOW,
        )
    assert subject_error.value.code == "invalid_identity_authority"


def test_sessionless_resolver_rejects_invalid_persisted_role() -> None:
    store = _make_store()
    _create_subject(store)
    tenant = store.create_tenant(now=NOW)
    store.assign_tenant_membership(
        tenant_id=tenant.tenant_id,
        canonical_subject_id="sub_test_subject_001",
        now=NOW,
        role=TenantMembershipRole.VIEWER,
    )
    store._sql.exec(
        "UPDATE canonical_tenant_membership SET role=? WHERE tenant_id=? AND canonical_subject_id=?",
        "administrator",
        tenant.tenant_id,
        "sub_test_subject_001",
    )
    with pytest.raises(ControlPlaneContractError) as raised:
        store.resolve_active_tenant_membership(
            tenant_id=tenant.tenant_id,
            canonical_subject_id="sub_test_subject_001",
            now=NOW,
        )
    assert raised.value.code == "canonical_tenant_membership_role_invalid"


def test_sessionless_resolver_rejects_cross_tenant_membership() -> None:
    store = _make_store()
    _create_subject(store)
    tenant = store.create_tenant(now=NOW)
    other_tenant = store.create_tenant(now=NOW)
    store.assign_tenant_membership(
        tenant_id=tenant.tenant_id,
        canonical_subject_id="sub_test_subject_001",
        now=NOW,
        role=TenantMembershipRole.OWNER,
    )
    with pytest.raises(ControlPlaneContractError) as raised:
        store.resolve_active_tenant_membership(
            tenant_id=other_tenant.tenant_id,
            canonical_subject_id="sub_test_subject_001",
            now=NOW,
        )
    assert raised.value.code == "canonical_tenant_membership_not_found"


def test_sessionless_resolver_rejects_future_membership() -> None:
    store = _make_store()
    _create_subject(store)
    tenant = store.create_tenant(now=NOW)
    store.assign_tenant_membership(
        tenant_id=tenant.tenant_id,
        canonical_subject_id="sub_test_subject_001",
        now=NOW + timedelta(minutes=5),
        role=TenantMembershipRole.OWNER,
    )
    with pytest.raises(ControlPlaneContractError) as raised:
        store.resolve_active_tenant_membership(
            tenant_id=tenant.tenant_id,
            canonical_subject_id="sub_test_subject_001",
            now=NOW,
        )
    assert raised.value.code == "canonical_tenant_membership_not_yet_active"


def test_worker_role_assignment_persists_explicit_role() -> None:
    store = _make_store()
    _create_subject(store)
    tenant = store.create_tenant(now=NOW)
    authority = object.__new__(_worker_mod.CanonicalIdentityDurableObject)
    authority._store = store
    result = asyncio.run(
        authority.assign_tenant_membership(
            {
                "tenant_id": tenant.tenant_id,
                "canonical_subject_id": "sub_test_subject_001",
                "role": "viewer",
            }
        )
    )
    assert result["ok"] is True
    assert result["membership"]["role"] == "viewer"


def test_worker_sessionless_resolver_requires_exact_fields() -> None:
    store = _make_store()
    _create_subject(store)
    tenant = store.create_tenant(now=NOW)
    store.assign_tenant_membership(
        tenant_id=tenant.tenant_id,
        canonical_subject_id="sub_test_subject_001",
        now=NOW,
        role=TenantMembershipRole.APPROVER,
    )
    authority = object.__new__(_worker_mod.CanonicalIdentityDurableObject)
    authority._store = store
    result = asyncio.run(
        authority.resolve_active_tenant_membership(
            {
                "tenant_id": tenant.tenant_id,
                "canonical_subject_id": "sub_test_subject_001",
                "now": NOW.isoformat().replace("+00:00", "Z"),
            }
        )
    )
    assert result["ok"] is True
    assert result["membership"]["role"] == "approver"
    base_payload = {
        "tenant_id": tenant.tenant_id,
        "canonical_subject_id": "sub_test_subject_001",
        "now": NOW.isoformat().replace("+00:00", "Z"),
    }
    for extra in (
        {"role": "owner"},
        {"product_user_id": "usr_not_canonical"},
        {"owner_ref": "owner:opaque"},
        {"workspace_ref": "workspace_connector"},
    ):
        rejected = asyncio.run(
            authority.resolve_active_tenant_membership(
                {**base_payload, **extra}
            )
        )
        assert rejected["ok"] is False
