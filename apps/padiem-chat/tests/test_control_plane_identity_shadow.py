from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from padiem_control_plane import (
    AuthSessionSnapshot,
    AuthSessionState,
    CanonicalSubjectRef,
    ProductIdentityLink,
    SubjectType,
)

from app.control_plane_identity import BridgedIdentitySession, IdentityBridgeError
from app.control_plane_identity_shadow import (
    D1IdentityShadowStore,
    IdentityShadowRecord,
    RefreshingCanonicalSubjectResolver,
)

NOW = datetime(2026, 9, 3, 0, 40, tzinfo=timezone.utc)
PRODUCT_USER = "usr_0123456789abcdef0123456789abcdef"
SUBJECT = "subject:padiem:user:123"
SESSION = "authsession:b62:123"


def canonical_session(*, state=AuthSessionState.ACTIVE, revision=1, subject=SUBJECT):
    return AuthSessionSnapshot(
        session_id=SESSION,
        product_id="b62",
        subject=CanonicalSubjectRef(subject_type=SubjectType.USER, subject_id=subject),
        issued_at=NOW,
        expires_at=NOW + timedelta(hours=2),
        state=state,
        revision=revision,
    )


def bridged() -> BridgedIdentitySession:
    session = canonical_session()
    return BridgedIdentitySession(
        product_user_id=PRODUCT_USER,
        identity_link=ProductIdentityLink(
            product_id="b62",
            product_user_id=PRODUCT_USER,
            canonical_subject_id=SUBJECT,
        ),
        auth_session=session,
    )


class MemoryShadowStore:
    def __init__(self, record=None):
        self.record = record

    async def save_projection(self, value):
        session = value.auth_session
        self.record = IdentityShadowRecord(
            product_user_id=value.product_user_id,
            canonical_subject_id=value.canonical_subject.subject_id,
            auth_session_id=session.session_id,
            session_revision=session.revision,
            session_state=session.state.value,
            session_expires_at=session.expires_at,
            observed_at=NOW,
        )

    async def load_projection(self, product_user_id):
        if self.record is not None and self.record.product_user_id == product_user_id:
            return self.record
        return None


class Authority:
    def __init__(self, session=None):
        self.session = session or canonical_session()
        self.calls = []

    def resolve_auth_session(self, *, session_id):
        self.calls.append(session_id)
        return self.session


async def test_shadow_pointer_is_refreshed_from_current_authority_before_use() -> None:
    store = MemoryShadowStore()
    await store.save_projection(bridged())
    authority = Authority(canonical_session(revision=2))
    resolver = RefreshingCanonicalSubjectResolver(authority=authority, store=store)

    subject_id = await resolver.resolve_subject_id(
        product_user_id=PRODUCT_USER,
        now=NOW + timedelta(minutes=5),
    )

    assert subject_id == SUBJECT
    assert authority.calls == [SESSION]


async def test_shadow_alone_is_never_canonical_authority() -> None:
    store = MemoryShadowStore()
    await store.save_projection(bridged())
    authority = Authority()
    def unavailable(*, session_id):
        raise RuntimeError("control plane unavailable")
    authority.resolve_auth_session = unavailable
    resolver = RefreshingCanonicalSubjectResolver(authority=authority, store=store)

    with pytest.raises(IdentityBridgeError) as raised:
        await resolver.resolve_subject_id(product_user_id=PRODUCT_USER, now=NOW)
    assert raised.value.status_code == 503
    assert raised.value.code == "control_plane_session_unavailable"


async def test_missing_shadow_link_fails_closed_without_authority_call() -> None:
    authority = Authority()
    resolver = RefreshingCanonicalSubjectResolver(
        authority=authority,
        store=MemoryShadowStore(),
    )
    with pytest.raises(IdentityBridgeError) as raised:
        await resolver.resolve_subject_id(product_user_id=PRODUCT_USER, now=NOW)
    assert raised.value.code == "control_plane_identity_not_linked"
    assert authority.calls == []


@pytest.mark.parametrize("state", [AuthSessionState.REVOKED, AuthSessionState.EXPIRED])
async def test_current_revoked_or_expired_session_fails_closed(state) -> None:
    store = MemoryShadowStore()
    await store.save_projection(bridged())
    authority = Authority(canonical_session(state=state, revision=2))
    resolver = RefreshingCanonicalSubjectResolver(authority=authority, store=store)

    with pytest.raises(IdentityBridgeError) as raised:
        await resolver.resolve_subject_id(product_user_id=PRODUCT_USER, now=NOW + timedelta(minutes=1))
    assert raised.value.status_code == 401
    assert raised.value.code == "control_plane_session_inactive"


async def test_subject_mismatch_between_shadow_and_current_authority_fails() -> None:
    store = MemoryShadowStore()
    await store.save_projection(bridged())
    authority = Authority(canonical_session(revision=2, subject="subject:padiem:user:other"))
    resolver = RefreshingCanonicalSubjectResolver(authority=authority, store=store)

    with pytest.raises(IdentityBridgeError) as raised:
        await resolver.resolve_subject_id(product_user_id=PRODUCT_USER, now=NOW)
    assert raised.value.status_code == 403
    assert raised.value.code == "control_plane_session_mismatch"


async def test_authority_revision_cannot_move_backwards_from_shadow() -> None:
    store = MemoryShadowStore(
        IdentityShadowRecord(
            product_user_id=PRODUCT_USER,
            canonical_subject_id=SUBJECT,
            auth_session_id=SESSION,
            session_revision=3,
            session_state="active",
            session_expires_at=NOW + timedelta(hours=1),
            observed_at=NOW,
        )
    )
    authority = Authority(canonical_session(revision=2))
    resolver = RefreshingCanonicalSubjectResolver(authority=authority, store=store)
    with pytest.raises(IdentityBridgeError) as raised:
        await resolver.resolve_subject_id(product_user_id=PRODUCT_USER, now=NOW)
    assert raised.value.code == "control_plane_session_mismatch"


class FakeStatement:
    def __init__(self, db, sql):
        self.db = db
        self.sql = " ".join(sql.split())
        self.values = ()

    def bind(self, *values):
        self.values = values
        return self

    async def run(self):
        if self.sql.startswith("INSERT INTO control_plane_identity_shadow"):
            (
                product_user_id,
                subject_id,
                session_id,
                revision,
                state,
                expires_at,
                observed_at,
            ) = self.values
            self.db.rows[product_user_id] = {
                "product_user_id": product_user_id,
                "canonical_subject_id": subject_id,
                "auth_session_id": session_id,
                "session_revision": revision,
                "session_state": state,
                "session_expires_at": expires_at,
                "observed_at": observed_at,
            }
            return {"success": True}
        raise AssertionError(self.sql)

    async def first(self):
        if self.sql.startswith("SELECT product_user_id"):
            return self.db.rows.get(self.values[0])
        raise AssertionError(self.sql)


class FakeD1:
    def __init__(self):
        self.rows = {}

    def prepare(self, sql):
        return FakeStatement(self, sql)


async def test_d1_shadow_store_persists_only_bounded_projection() -> None:
    db = FakeD1()
    store = D1IdentityShadowStore(db)
    value = bridged()

    await store.save_projection(value)
    loaded = await store.load_projection(PRODUCT_USER)

    assert loaded is not None
    assert loaded.product_user_id == PRODUCT_USER
    assert loaded.canonical_subject_id == SUBJECT
    assert loaded.auth_session_id == SESSION
    assert loaded.session_revision == 1
    assert loaded.session_state == "active"
    persisted = db.rows[PRODUCT_USER]
    assert "provider_subject" not in persisted
    assert "access_token" not in persisted
    assert "email" not in persisted
    assert "plan" not in persisted
    assert "entitlement" not in persisted
