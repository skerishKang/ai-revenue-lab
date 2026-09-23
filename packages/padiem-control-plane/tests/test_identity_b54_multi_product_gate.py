"""Multi-product gate tests for #2964 — bounded B54 canonical auth-session authority.

Minimum proof requirements from the work contract:
  R01  b62 기존 session 정상
  R02  b54-padiem-claw canonical session 정상
  R03  arbitrary third product 거부
  R04  B54 tenant server-derived
  R05  browser subject/tenant/product authority=0  (structural — no browser path exists)
  R06  B54 session → B54 app만 허용
  R07  B62 session → B54 app 거부  (Engine firewall: product_id != app_id)
  R08  B54 session → B62 app 거부  (Engine firewall: product_id != app_id)
  R09  SECOND_IDENTITY_AUTHORITY=0
  R10  SECOND_SESSION_STORE=0
  R11  b62 기존 behavior unchanged — product_id=b62 store 단독도 정상
  R12  store init rejects empty frozenset
  R13  store init rejects non-frozenset
  R14  B54 safe_dict reflects allowed_product_ids list
  R15  B54 link is idempotent (same subject resolves same canonical)
  R16  B54 session product_id == "b54-padiem-claw" (no drift)
  R17  B54 session state=ACTIVE immediately after establishment
  R18  B54 session resolves via resolve_auth_session
  R19  B62 session cannot be established under B54 subject in multi-product store
  R20  B54 session cannot be established under B62 subject in multi-product store
  R21  Missing session fails closed without synthetic fallback
  R22  b54_identity_bridge module constants are correct
"""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import sqlite3

import pytest

from identity_authority_durable import (
    CloudflareCanonicalIdentityAuthorityStore,
    decode_identity_lookup_key,
)
from padiem_control_plane.auth_sessions import AuthSessionState
from padiem_control_plane.contracts import (
    CanonicalSubjectRef,
    ControlPlaneContractError,
    IdentityLinkState,
    SubjectType,
)

NOW = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)
LOOKUP_KEY_BYTES = b"K" * 32
LOOKUP_KEY = base64.urlsafe_b64encode(LOOKUP_KEY_BYTES).decode("ascii").rstrip("=")

B62_PRODUCT = "b62"
B54_PRODUCT = "b54-padiem-claw"
THIRD_PRODUCT = "b99"

MULTI_PRODUCT_SET = frozenset({B62_PRODUCT, B54_PRODUCT})


# ---------------------------------------------------------------------------
# Shared infrastructure (copy of FakeStorage from test_identity_authority_durable)
# ---------------------------------------------------------------------------


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


def _make_store(*, product_ids: frozenset[str]) -> CloudflareCanonicalIdentityAuthorityStore:
    return CloudflareCanonicalIdentityAuthorityStore(
        FakeStorage(),
        lookup_key=LOOKUP_KEY_BYTES,
        allowed_product_ids=product_ids,
        random_hex=_TokenSource(),
    )


def _link(store, *, product_id: str, user_id: str, provider: str, subject: str):
    return store.resolve_or_create_product_link(
        product_id=product_id,
        product_user_id=user_id,
        auth_provider=provider,
        provider_subject=subject,
        now=NOW,
    )


def _session(store, *, product_id: str, canonical_subject_id: str):
    subject = CanonicalSubjectRef(SubjectType.USER, canonical_subject_id)
    return store.establish_auth_session(
        product_id=product_id,
        subject=subject,
        authenticated_at=NOW - timedelta(minutes=1),
        not_after=NOW + timedelta(hours=1),
        now=NOW,
    ), subject


# ---------------------------------------------------------------------------
# R01: B62 existing session works normally (unchanged behavior)
# ---------------------------------------------------------------------------


def test_r01_b62_session_normal_in_multi_product_store():
    """R01: b62 기존 session 정상."""
    store = _make_store(product_ids=MULTI_PRODUCT_SET)
    link = _link(store, product_id=B62_PRODUCT, user_id="usr_b62", provider="google", subject="google-sub-b62")
    assert link.product_id == B62_PRODUCT
    assert link.state is IdentityLinkState.ACTIVE
    session, subject = _session(store, product_id=B62_PRODUCT, canonical_subject_id=link.canonical_subject_id)
    assert session.product_id == B62_PRODUCT
    assert session.subject == subject
    assert session.state is AuthSessionState.ACTIVE


# ---------------------------------------------------------------------------
# R02: B54 canonical session works correctly
# ---------------------------------------------------------------------------


def test_r02_b54_canonical_session_normal():
    """R02: b54-padiem-claw canonical session 정상."""
    store = _make_store(product_ids=MULTI_PRODUCT_SET)
    link = _link(store, product_id=B54_PRODUCT, user_id="usr_b54", provider="password", subject="b54-owner-pw-sub")
    assert link.product_id == B54_PRODUCT
    assert link.state is IdentityLinkState.ACTIVE
    session, subject = _session(store, product_id=B54_PRODUCT, canonical_subject_id=link.canonical_subject_id)
    assert session.product_id == B54_PRODUCT
    assert session.subject == subject
    assert session.state is AuthSessionState.ACTIVE
    assert session.is_active(now=NOW)


# ---------------------------------------------------------------------------
# R03: Arbitrary third product is rejected
# ---------------------------------------------------------------------------


def test_r03_arbitrary_third_product_rejected():
    """R03: arbitrary third product 거부."""
    store = _make_store(product_ids=MULTI_PRODUCT_SET)
    with pytest.raises(ControlPlaneContractError) as exc:
        _link(store, product_id=THIRD_PRODUCT, user_id="usr_1", provider="google", subject="some-sub")
    assert exc.value.code == "identity_authority_product_mismatch"


# ---------------------------------------------------------------------------
# R04: B54 tenant is server-derived (authority controls tenant creation)
# ---------------------------------------------------------------------------


def test_r04_b54_tenant_server_derived():
    """R04: B54 tenant server-derived — create_tenant + assign_tenant_membership go through authority."""
    store = _make_store(product_ids=MULTI_PRODUCT_SET)
    link = _link(store, product_id=B54_PRODUCT, user_id="usr_b54", provider="password", subject="b54-tenant-sub")
    # create_tenant and assign_tenant_membership are product-neutral operations
    tenant = store.create_tenant(now=NOW)
    tenant_id = tenant.tenant_id
    assert isinstance(tenant_id, str) and tenant_id
    store.assign_tenant_membership(tenant_id=tenant_id, canonical_subject_id=link.canonical_subject_id, now=NOW)
    memberships = store._active_membership_tenant_ids(link.canonical_subject_id)
    assert isinstance(memberships, list)
    assert tenant_id in memberships


# ---------------------------------------------------------------------------
# R06: B54 session → B54 app only (product_id equality preserved in session)
# ---------------------------------------------------------------------------


def test_r06_b54_session_product_id_is_b54_only():
    """R06: B54 session product_id == 'b54-padiem-claw' — not b62, not anything else."""
    store = _make_store(product_ids=MULTI_PRODUCT_SET)
    link = _link(store, product_id=B54_PRODUCT, user_id="usr_b54", provider="password", subject="b54-r06-sub")
    session, _ = _session(store, product_id=B54_PRODUCT, canonical_subject_id=link.canonical_subject_id)
    assert session.product_id == B54_PRODUCT
    assert session.product_id != B62_PRODUCT


# ---------------------------------------------------------------------------
# R09/R10: Single canonical identity authority / single session store
# (structural test: only one store class exists; both products use it)
# ---------------------------------------------------------------------------


def test_r09_r10_single_identity_authority_single_session_store():
    """R09/R10: SECOND_IDENTITY_AUTHORITY=0 / SECOND_SESSION_STORE=0.

    Both B62 and B54 sessions are stored in the same CloudflareCanonicalIdentityAuthorityStore
    instance. No second identity authority class or second session store is created.
    """
    store = _make_store(product_ids=MULTI_PRODUCT_SET)
    assert isinstance(store, CloudflareCanonicalIdentityAuthorityStore)
    # Both products use the same instance:
    link_b62 = _link(store, product_id=B62_PRODUCT, user_id="usr_b62", provider="google", subject="google-r09")
    link_b54 = _link(store, product_id=B54_PRODUCT, user_id="usr_b54", provider="password", subject="pw-r09")
    sess_b62, _ = _session(store, product_id=B62_PRODUCT, canonical_subject_id=link_b62.canonical_subject_id)
    sess_b54, _ = _session(store, product_id=B54_PRODUCT, canonical_subject_id=link_b54.canonical_subject_id)
    # Both resolve from the same store
    assert store.resolve_auth_session(session_id=sess_b62.session_id).product_id == B62_PRODUCT
    assert store.resolve_auth_session(session_id=sess_b54.session_id).product_id == B54_PRODUCT


# ---------------------------------------------------------------------------
# R11: B62-only store still works (backward compat)
# ---------------------------------------------------------------------------


def test_r11_b62_only_store_still_works():
    """R11: b62 기존 behavior unchanged — product_id=b62 store 단독도 정상."""
    store = _make_store(product_ids=frozenset({B62_PRODUCT}))
    link = _link(store, product_id=B62_PRODUCT, user_id="usr_b62", provider="google", subject="google-r11")
    session, subject = _session(store, product_id=B62_PRODUCT, canonical_subject_id=link.canonical_subject_id)
    assert session.product_id == B62_PRODUCT
    assert session.state is AuthSessionState.ACTIVE


# ---------------------------------------------------------------------------
# R12/R13: Store init rejects invalid allowlist
# ---------------------------------------------------------------------------


def test_r12_store_init_rejects_empty_frozenset():
    """R12: store init rejects empty frozenset."""
    with pytest.raises(ValueError):
        CloudflareCanonicalIdentityAuthorityStore(
            FakeStorage(),
            lookup_key=LOOKUP_KEY_BYTES,
            allowed_product_ids=frozenset(),
        )


def test_r13_store_init_rejects_non_frozenset():
    """R13: store init rejects non-frozenset (list, set, str)."""
    for bad in (["b62"], {"b62"}, "b62", None):
        with pytest.raises((ValueError, TypeError, AttributeError)):
            CloudflareCanonicalIdentityAuthorityStore(
                FakeStorage(),
                lookup_key=LOOKUP_KEY_BYTES,
                allowed_product_ids=bad,  # type: ignore[arg-type]
            )


# ---------------------------------------------------------------------------
# R14: safe_dict reflects allowed_product_ids list
# ---------------------------------------------------------------------------


def test_r14_safe_dict_reflects_allowed_product_ids():
    """R14: B54 safe_dict reflects allowed_product_ids list."""
    store = _make_store(product_ids=MULTI_PRODUCT_SET)
    d = store.safe_dict()
    assert "allowed_product_ids" in d
    assert "allowed_product_id" not in d  # old key must be gone
    ids = d["allowed_product_ids"]
    assert isinstance(ids, list)
    assert sorted(ids) == ids  # deterministically sorted
    assert B62_PRODUCT in ids
    assert B54_PRODUCT in ids
    assert THIRD_PRODUCT not in ids


# ---------------------------------------------------------------------------
# R15: B54 link is idempotent
# ---------------------------------------------------------------------------


def test_r15_b54_link_is_idempotent():
    """R15: B54 link is idempotent — same provider subject resolves same canonical."""
    store = _make_store(product_ids=MULTI_PRODUCT_SET)
    first = _link(store, product_id=B54_PRODUCT, user_id="usr_b54", provider="password", subject="b54-idem-sub")
    second = _link(store, product_id=B54_PRODUCT, user_id="usr_b54", provider="password", subject="b54-idem-sub")
    assert first.canonical_subject_id == second.canonical_subject_id


# ---------------------------------------------------------------------------
# R16/R17/R18: B54 session product_id correctness, active state, resolvable
# ---------------------------------------------------------------------------


def test_r16_r17_r18_b54_session_product_state_resolvable():
    """R16: product_id drift absent; R17: state=ACTIVE; R18: resolve succeeds."""
    store = _make_store(product_ids=MULTI_PRODUCT_SET)
    link = _link(store, product_id=B54_PRODUCT, user_id="usr_b54", provider="password", subject="b54-r16-sub")
    session, subject = _session(store, product_id=B54_PRODUCT, canonical_subject_id=link.canonical_subject_id)
    assert session.product_id == B54_PRODUCT          # R16
    assert session.state is AuthSessionState.ACTIVE   # R17
    resolved = store.resolve_auth_session(session_id=session.session_id)
    assert resolved == session                         # R18


# ---------------------------------------------------------------------------
# R19: B62 session cannot be established under B54 subject
# ---------------------------------------------------------------------------


def test_r19_b62_session_rejected_for_b54_subject():
    """R19: B62 session → B54 app 거부 (store level: product_id mismatch)."""
    store = _make_store(product_ids=MULTI_PRODUCT_SET)
    b54_link = _link(store, product_id=B54_PRODUCT, user_id="usr_b54", provider="password", subject="b54-r19-sub")
    b54_subject = CanonicalSubjectRef(SubjectType.USER, b54_link.canonical_subject_id)
    with pytest.raises(ControlPlaneContractError) as exc:
        store.establish_auth_session(
            product_id=B62_PRODUCT,
            subject=b54_subject,
            authenticated_at=NOW - timedelta(minutes=1),
            not_after=NOW + timedelta(hours=1),
            now=NOW,
        )
    # B62 is in the allowlist (product check passes) but the B54 subject has
    # no B62 product link → link_missing (fail-closed, cross-product leakage impossible).
    assert exc.value.code in {"identity_authority_product_mismatch", "identity_authority_link_missing"}


# ---------------------------------------------------------------------------
# R20: B54 session cannot be established under B62 subject
# ---------------------------------------------------------------------------


def test_r20_b54_session_rejected_for_b62_subject():
    """R20: B54 session → B62 app 거부 (store level: product_id mismatch)."""
    store = _make_store(product_ids=MULTI_PRODUCT_SET)
    b62_link = _link(store, product_id=B62_PRODUCT, user_id="usr_b62", provider="google", subject="google-r20-sub")
    b62_subject = CanonicalSubjectRef(SubjectType.USER, b62_link.canonical_subject_id)
    with pytest.raises(ControlPlaneContractError) as exc:
        store.establish_auth_session(
            product_id=B54_PRODUCT,
            subject=b62_subject,
            authenticated_at=NOW - timedelta(minutes=1),
            not_after=NOW + timedelta(hours=1),
            now=NOW,
        )
    # B54 is in the allowlist (product check passes) but the B62 subject has
    # no B54 product link → link_missing (fail-closed, cross-product leakage impossible).
    assert exc.value.code in {"identity_authority_product_mismatch", "identity_authority_link_missing"}


# ---------------------------------------------------------------------------
# R21: Missing session fails closed
# ---------------------------------------------------------------------------


def test_r21_missing_session_fails_closed():
    """R21: Missing session fails closed without synthetic fallback."""
    store = _make_store(product_ids=MULTI_PRODUCT_SET)
    with pytest.raises(ControlPlaneContractError) as exc:
        store.resolve_auth_session(session_id="sess_nonexistent")
    assert exc.value.code == "canonical_auth_session_not_found"


# ---------------------------------------------------------------------------
# R22: b54_identity_bridge module constants
# ---------------------------------------------------------------------------


def test_r22_b54_identity_bridge_constants():
    """R22: b54_identity_bridge module constants are correct."""
    from padiem_control_plane.b54_identity_bridge import B54_PRODUCT_ID
    assert B54_PRODUCT_ID == "b54-padiem-claw"
    # Must not equal B62 product
    assert B54_PRODUCT_ID != "b62"
