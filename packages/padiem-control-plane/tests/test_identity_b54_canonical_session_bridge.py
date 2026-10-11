"""B54 canonical session bridge driven by the real canonical authority store (#2964).

Every value asserted here is minted or resolved by
``CloudflareCanonicalIdentityAuthorityStore`` — the same store the deployed
Control Plane identity Worker wraps — so the tenant, subject, and session ids in
these proofs are server-derived content, not fixtures written by this test.

Proves:
  B54_REAL_SERVER_PRODUCER_PRESENT   an importable canonical bridge over the real store
  B54_SESSION_PRODUCT_ID             b54-padiem-claw, and nothing else
  B54_SESSION_TENANT_PRESENT         every returned session carries a tenant
  B54_TENANT_SERVER_DERIVED          tenant equals the store-resolved membership tenant
  DEFAULT_TENANT=NO / BROWSER_WORKSPACE_AS_TENANT=NO   no caller tenant input exists
  TENANT_EQUALS_PRODUCT=NO / TENANT_EQUALS_SUBJECT=NO
  >1 membership                      fail closed, and no session is minted
  SECOND_IDENTITY_AUTHORITY=0 / SECOND_SESSION_STORE=0
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import inspect
import sqlite3

import pytest

import identity_authority_durable as durable_module
from identity_authority_durable import CloudflareCanonicalIdentityAuthorityStore
from padiem_control_plane.auth_sessions import AuthSessionState
from padiem_control_plane.b54_identity_bridge import (
    B54IdentityBridgeError,
    TrustedB54ServerAuthEvidence,
    bridge_trusted_b54_server_auth,
)

NOW = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)
LOOKUP_KEY_BYTES = b"K" * 32
B54_PRODUCT = "b54-padiem-claw"
B62_PRODUCT = "b62"
PRODUCT_SET = frozenset({B62_PRODUCT, B54_PRODUCT})


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


class _TokenSource:
    def __init__(self) -> None:
        self.count = 0

    def __call__(self, bytes_count: int) -> str:
        self.count += 1
        return f"{self.count:0{bytes_count * 2}x}"[-bytes_count * 2 :]


class CanonicalStoreAuthority:
    """Mirror of the private Service Binding RPC: every call delegates to the store.

    Nothing here mints or remembers identity, tenant, or session state — the
    Control Plane store is the only authority, which is what makes this a faithful
    stand-in for the deployed adapter rather than a second stack.
    """

    def __init__(self, store: CloudflareCanonicalIdentityAuthorityStore) -> None:
        self._store = store

    def resolve_or_create_product_link(
        self, *, product_id, product_user_id, auth_provider, provider_subject
    ):
        return self._store.resolve_or_create_product_link(
            product_id=product_id,
            product_user_id=product_user_id,
            auth_provider=auth_provider,
            provider_subject=provider_subject,
            now=NOW,
        )

    def establish_auth_session(self, *, product_id, subject, authenticated_at, not_after):
        return self._store.establish_auth_session(
            product_id=product_id,
            subject=subject,
            authenticated_at=authenticated_at,
            not_after=not_after,
            now=NOW,
        )

    def resolve_auth_session(self, *, session_id: str):
        return self._store.resolve_auth_session(session_id=session_id)

    def create_tenant(self) -> str:
        return self._store.create_tenant(now=NOW).tenant_id

    def assign_tenant_membership(self, *, tenant_id: str, canonical_subject_id: str) -> None:
        self._store.assign_tenant_membership(
            tenant_id=tenant_id, canonical_subject_id=canonical_subject_id, now=NOW
        )

    def resolve_active_memberships(self, *, canonical_subject_id: str):
        return tuple(self._store._active_membership_tenant_ids(canonical_subject_id))


def _fixture():
    storage = FakeStorage()
    store = CloudflareCanonicalIdentityAuthorityStore(
        storage,
        lookup_key=LOOKUP_KEY_BYTES,
        allowed_product_ids=PRODUCT_SET,
        random_hex=_TokenSource(),
    )
    return storage, store, CanonicalStoreAuthority(store)


def _evidence(user_id: str) -> TrustedB54ServerAuthEvidence:
    return TrustedB54ServerAuthEvidence(
        product_user_id=user_id,
        provider="password",
        provider_subject="claw-" + user_id,
        authenticated_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(hours=1),
    )


def _bridge(authority, user_id: str):
    return asyncio.run(bridge_trusted_b54_server_auth(authority, _evidence(user_id), now=NOW))


def _session_count(storage: FakeStorage) -> int:
    return int(
        storage.connection.execute("SELECT COUNT(*) FROM canonical_auth_session").fetchone()[0]
    )


def _enroll(authority, store, *, product_id: str, user_id: str, memberships: int):
    link = authority.resolve_or_create_product_link(
        product_id=product_id,
        product_user_id=user_id,
        auth_provider="password",
        provider_subject="claw-" + user_id,
    )
    tenants = []
    for _ in range(memberships):
        tenant = store.create_tenant(now=NOW)
        store.assign_tenant_membership(
            tenant_id=tenant.tenant_id, canonical_subject_id=link.canonical_subject_id, now=NOW
        )
        tenants.append(tenant.tenant_id)
    return link, tenants


# ---------------------------------------------------------------------------
# The chain is a producer, and no caller can opt out of tenancy
# ---------------------------------------------------------------------------


def test_bridge_takes_no_caller_tenant_product_subject_or_session_input():
    """``ensure_personal_tenant`` was the opt-out that let a tenant-less session pass.

    Its absence from the signature is part of the proof, alongside the absence of
    any tenant, product, subject, session, or workspace parameter.
    """
    parameters = inspect.signature(bridge_trusted_b54_server_auth).parameters
    assert set(parameters) == {"authority", "evidence", "now"}
    assert "ensure_personal_tenant" not in parameters


def test_evidence_carries_only_server_authentication_fields():
    assert set(TrustedB54ServerAuthEvidence.__dataclass_fields__) == {
        "product_user_id",
        "provider",
        "provider_subject",
        "authenticated_at",
        "expires_at",
    }


def test_bridge_is_importable_from_the_installed_control_plane_package():
    """Production-callable means reachable from the installed package, not a path hack."""
    import padiem_control_plane.b54_identity_bridge as bridge

    assert bridge.B54_PRODUCT_ID == B54_PRODUCT
    assert callable(bridge.bridge_trusted_b54_server_auth)


# ---------------------------------------------------------------------------
# Exactly one active membership: use it
# ---------------------------------------------------------------------------


def test_single_membership_tenant_is_carried_by_the_session():
    _storage, store, authority = _fixture()
    link, tenants = _enroll(
        authority, store, product_id=B54_PRODUCT, user_id="usr_2964single", memberships=1
    )

    bridged = _bridge(authority, "usr_2964single")

    assert bridged.auth_session.product_id == B54_PRODUCT
    assert bridged.auth_session.tenant_id == tenants[0]
    assert bridged.auth_session.subject.subject_id == link.canonical_subject_id
    assert bridged.auth_session.state is AuthSessionState.ACTIVE


# ---------------------------------------------------------------------------
# Zero membership: the canonical personal-tenant policy creates and assigns
# ---------------------------------------------------------------------------


def test_zero_membership_provisions_through_the_canonical_authority():
    storage, store, authority = _fixture()

    bridged = _bridge(authority, "usr_2964fresh")

    tenant_id = bridged.auth_session.tenant_id
    assert isinstance(tenant_id, str) and tenant_id
    # Canonical store truth, not a value this bridge invented locally.
    assert store.get_tenant(tenant_id=tenant_id).tenant_id == tenant_id
    subject_id = bridged.auth_session.subject.subject_id
    assert store._active_membership_tenant_ids(subject_id) == [tenant_id]
    assert (
        storage.connection.execute(
            "SELECT COUNT(*) FROM canonical_auth_session WHERE tenant_id=?", (tenant_id,)
        ).fetchone()[0]
        == 1
    )


def test_repeated_bridge_calls_reuse_the_existing_canonical_tenant():
    _storage, _store, authority = _fixture()

    first = _bridge(authority, "usr_2964stable")
    second = _bridge(authority, "usr_2964stable")

    assert first.auth_session.tenant_id == second.auth_session.tenant_id
    assert first.identity_link.canonical_subject_id == second.identity_link.canonical_subject_id


def test_authority_without_personal_tenant_capability_refuses_instead_of_minting_one():
    """A canonical authority without personal-tenant provisioning is a policy refusal."""

    class ReadOnlyAuthority:
        def __init__(self, inner: CanonicalStoreAuthority) -> None:
            self._inner = inner

        def resolve_or_create_product_link(self, **kwargs):
            return self._inner.resolve_or_create_product_link(**kwargs)

        def establish_auth_session(self, **kwargs):
            return self._inner.establish_auth_session(**kwargs)

        def resolve_active_memberships(self, *, canonical_subject_id: str):
            return self._inner.resolve_active_memberships(
                canonical_subject_id=canonical_subject_id
            )

    storage, _store, authority = _fixture()
    before = _session_count(storage)

    with pytest.raises(B54IdentityBridgeError) as exc:
        _bridge(ReadOnlyAuthority(authority), "usr_2964readonly")

    assert exc.value.code == "b54_control_plane_personal_tenant_not_permitted"
    assert exc.value.status_code == 503
    assert _session_count(storage) == before


# ---------------------------------------------------------------------------
# More than one membership: fail closed, and mint nothing
# ---------------------------------------------------------------------------


def test_ambiguous_membership_fails_closed_without_minting_a_session():
    storage, store, authority = _fixture()
    _enroll(authority, store, product_id=B54_PRODUCT, user_id="usr_2964multi", memberships=2)
    before = _session_count(storage)

    with pytest.raises(B54IdentityBridgeError) as exc:
        _bridge(authority, "usr_2964multi")

    assert exc.value.code == "b54_control_plane_tenant_ambiguous"
    assert exc.value.status_code == 403
    assert _session_count(storage) == before


def test_membership_projection_that_is_not_a_tuple_fails_closed():
    class BrokenProjection(CanonicalStoreAuthority):
        def resolve_active_memberships(self, *, canonical_subject_id: str):
            return ["tenant_not_a_tuple"]

    storage, store, authority = _fixture()
    before = _session_count(storage)
    broken = BrokenProjection(store)

    with pytest.raises(B54IdentityBridgeError) as exc:
        _bridge(broken, "usr_2964projection")

    assert exc.value.code == "b54_control_plane_tenant_invalid"
    assert _session_count(storage) == before


# ---------------------------------------------------------------------------
# A session that drops the resolved tenant is rejected, never returned
# ---------------------------------------------------------------------------


def test_session_without_the_resolved_tenant_is_rejected():
    """The store yields tenant_id=None for an unenrolled subject.

    That is exactly what the Engine fails closed on, so the bridge rejects it
    instead of handing a tenant-less session downstream.
    """

    class TenantDroppingAuthority(CanonicalStoreAuthority):
        def resolve_active_memberships(self, *, canonical_subject_id: str):
            return ()

        def create_tenant(self) -> str:
            return "tenant_never_enrolled"

        def assign_tenant_membership(self, *, tenant_id: str, canonical_subject_id: str) -> None:
            return None

    _storage, store, authority = _fixture()

    with pytest.raises(B54IdentityBridgeError) as exc:
        _bridge(TenantDroppingAuthority(store), "usr_2964dropped")

    assert exc.value.code == "b54_control_plane_session_tenant_mismatch"
    assert exc.value.status_code == 403


# ---------------------------------------------------------------------------
# Tenant distinctness, product scope, and single-store read-back
# ---------------------------------------------------------------------------


def test_tenant_is_never_the_product_the_subject_the_user_or_a_default():
    _storage, _store, authority = _fixture()

    session = _bridge(authority, "usr_2964distinct").auth_session

    assert session.tenant_id
    assert session.tenant_id != B54_PRODUCT
    assert session.tenant_id != session.subject.subject_id
    assert session.tenant_id != "usr_2964distinct"
    assert session.tenant_id != "default"


def test_bridge_can_only_mint_the_b54_product_scope():
    """Even an authority that rewrites product_id cannot yield a usable B62 session."""

    class B62ReturningAuthority(CanonicalStoreAuthority):
        def establish_auth_session(self, *, subject, authenticated_at, not_after, **_ignored):
            return self._store.establish_auth_session(
                product_id=B62_PRODUCT,
                subject=subject,
                authenticated_at=authenticated_at,
                not_after=not_after,
                now=NOW,
            )

    _storage, store, authority = _fixture()
    # The same canonical subject is enrolled under B62 as well, so a B62-scoped
    # session really can be minted for it and the mismatch must be caught by the
    # bridge rather than by a missing-link side effect.
    _enroll(authority, store, product_id=B62_PRODUCT, user_id="usr_2964crossprod", memberships=0)

    with pytest.raises(B54IdentityBridgeError) as exc:
        _bridge(B62ReturningAuthority(store), "usr_2964crossprod")

    assert exc.value.code == "b54_control_plane_session_mismatch"


def test_produced_session_resolves_from_the_same_single_store():
    """SECOND_SESSION_STORE=0: the returned id reads back from the one canonical store."""
    _storage, store, authority = _fixture()

    bridged = _bridge(authority, "usr_2964readback")

    resolved = store.resolve_auth_session(session_id=bridged.auth_session.session_id)
    assert resolved == bridged.auth_session
    assert resolved.product_id == B54_PRODUCT
    assert resolved.tenant_id == bridged.auth_session.tenant_id


def test_produced_session_wire_is_the_engine_tenant_aware_closed_shape():
    """The canonical projection is the eight-key shape the Engine accepts."""
    _storage, _store, authority = _fixture()

    payload = _bridge(authority, "usr_2964wire").auth_session.to_public_dict()

    assert set(payload) == {
        "session_id",
        "product_id",
        "subject",
        "issued_at",
        "expires_at",
        "state",
        "revision",
        "tenant_id",
    }
    assert payload["product_id"] == B54_PRODUCT
    assert set(payload["subject"]) == {"subject_type", "subject_id"}
    assert payload["subject"]["subject_type"] == "user"


def test_only_one_canonical_identity_authority_type_is_in_play():
    """SECOND_IDENTITY_AUTHORITY=0: the bridge consumes the reviewed store, not a rival."""
    assert (
        CloudflareCanonicalIdentityAuthorityStore
        is durable_module.CloudflareCanonicalIdentityAuthorityStore
    )
    stores = [
        name
        for name in dir(durable_module)
        if name.endswith("Store") and getattr(durable_module, name, None) is not None
    ]
    assert stores == ["CloudflareCanonicalIdentityAuthorityStore"]
