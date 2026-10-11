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


NOW = datetime(2026, 9, 4, 13, 0, tzinfo=timezone.utc)
LOOKUP_KEY_BYTES = b"I" * 32
LOOKUP_KEY = base64.urlsafe_b64encode(LOOKUP_KEY_BYTES).decode("ascii").rstrip("=")
PROVIDER_SUBJECT = "google-provider-subject-sensitive-123"


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

    def all_text(self) -> str:
        chunks: list[str] = []
        for table in (
            "canonical_identity_subject",
            "canonical_product_identity_link",
            "canonical_auth_session",
        ):
            for row in self.connection.execute(f"SELECT * FROM {table}").fetchall():
                chunks.extend("" if value is None else str(value) for value in row)
        return "\n".join(chunks)

    def count(self, table: str) -> int:
        return int(self.connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0])


class TokenSource:
    def __init__(self) -> None:
        self.count = 0

    def __call__(self, bytes_count: int) -> str:
        self.count += 1
        return f"{self.count:0{bytes_count * 2}x}"[-bytes_count * 2 :]


def fixture(*, allowed_product_ids: frozenset[str] = frozenset({"b62"})):
    storage = FakeStorage()
    store = CloudflareCanonicalIdentityAuthorityStore(
        storage,
        lookup_key=LOOKUP_KEY_BYTES,
        allowed_product_ids=allowed_product_ids,
        random_hex=TokenSource(),
    )
    return store, storage


def link(store, *, user="usr_1", provider_subject=PROVIDER_SUBJECT):
    return store.resolve_or_create_product_link(
        product_id="b62",
        product_user_id=user,
        auth_provider="google",
        provider_subject=provider_subject,
        now=NOW,
    )


def test_lookup_key_requires_exact_32_random_bytes():
    assert decode_identity_lookup_key(LOOKUP_KEY) == LOOKUP_KEY_BYTES
    with pytest.raises(ControlPlaneContractError) as exc:
        decode_identity_lookup_key("short")
    assert exc.value.code == "invalid_identity_authority_secret"


def test_provider_subject_is_hmac_fingerprinted_and_never_persisted_raw():
    store, storage = fixture()
    result = link(store)

    assert result.product_id == "b62"
    assert result.product_user_id == "usr_1"
    assert result.state is IdentityLinkState.ACTIVE
    assert result.canonical_subject_id.startswith("sub_")
    persisted = storage.all_text()
    assert PROVIDER_SUBJECT not in persisted
    assert "google" in persisted
    assert len(persisted) > 0
    assert store.safe_dict()["provider_subject_persisted"] is False
    assert store.safe_dict()["provider_subject_hmac_fingerprint_only"] is True


def test_same_provider_identity_resolves_same_canonical_subject_without_duplicate_subject_row():
    store, storage = fixture()
    first = link(store, user="usr_1")
    second = link(store, user="usr_2")

    assert first.canonical_subject_id == second.canonical_subject_id
    assert storage.count("canonical_identity_subject") == 1
    assert storage.count("canonical_product_identity_link") == 2


def test_product_user_rebind_to_different_provider_subject_is_forbidden_and_rolled_back():
    store, storage = fixture()
    original = link(store, user="usr_1", provider_subject="provider-A")

    with pytest.raises(ControlPlaneContractError) as exc:
        link(store, user="usr_1", provider_subject="provider-B")
    assert exc.value.code == "identity_rebind_forbidden"
    assert storage.count("canonical_identity_subject") == 1
    assert storage.count("canonical_product_identity_link") == 1

    current = storage.connection.execute(
        "SELECT canonical_subject_id FROM canonical_product_identity_link WHERE product_id='b62' AND product_user_id='usr_1'"
    ).fetchone()[0]
    assert current == original.canonical_subject_id


def test_password_provider_is_reviewed_and_hmac_fingerprinted() -> None:
    store, storage = fixture()
    result = store.resolve_or_create_product_link(
        product_id="b62",
        product_user_id="usr_password_1",
        auth_provider="password",
        provider_subject="owner.test",
        now=NOW,
    )

    assert result.product_id == "b62"
    assert result.product_user_id == "usr_password_1"
    assert result.state is IdentityLinkState.ACTIVE
    persisted = storage.all_text()
    assert "owner.test" not in persisted
    assert "password" in persisted


def test_unreviewed_product_and_provider_fail_closed_before_authority_mutation():
    store, storage = fixture()
    with pytest.raises(ControlPlaneContractError) as product_exc:
        store.resolve_or_create_product_link(
            product_id="b99",
            product_user_id="usr_1",
            auth_provider="google",
            provider_subject=PROVIDER_SUBJECT,
            now=NOW,
        )
    assert product_exc.value.code == "identity_authority_product_mismatch"

    with pytest.raises(ControlPlaneContractError) as provider_exc:
        store.resolve_or_create_product_link(
            product_id="b62",
            product_user_id="usr_1",
            auth_provider="github",
            provider_subject=PROVIDER_SUBJECT,
            now=NOW,
        )
    assert provider_exc.value.code == "unsupported_identity_provider"
    assert storage.count("canonical_identity_subject") == 0


def test_b54_product_link_and_session_succeed_in_multi_product_store():
    """B54 is now an allowed product; its link and session must succeed."""
    store, storage = fixture(allowed_product_ids=frozenset({"b62", "b54-padiem-claw"}))
    result = store.resolve_or_create_product_link(
        product_id="b54-padiem-claw",
        product_user_id="usr_b54_1",
        auth_provider="password",
        provider_subject="b54-owner-subject",
        now=NOW,
    )
    assert result.product_id == "b54-padiem-claw"
    assert result.product_user_id == "usr_b54_1"
    assert result.state is IdentityLinkState.ACTIVE

    subject = CanonicalSubjectRef(SubjectType.USER, result.canonical_subject_id)
    session = store.establish_auth_session(
        product_id="b54-padiem-claw",
        subject=subject,
        authenticated_at=NOW - timedelta(minutes=1),
        not_after=NOW + timedelta(hours=1),
        now=NOW,
    )
    assert session.product_id == "b54-padiem-claw"
    assert session.subject == subject
    assert session.state is AuthSessionState.ACTIVE

    resolved = store.resolve_auth_session(session_id=session.session_id)
    assert resolved == session


def test_third_product_still_rejected_in_multi_product_store():
    """b99 must be rejected even when two products are allowed."""
    store, _ = fixture(allowed_product_ids=frozenset({"b62", "b54-padiem-claw"}))
    with pytest.raises(ControlPlaneContractError) as exc:
        store.resolve_or_create_product_link(
            product_id="b99",
            product_user_id="usr_1",
            auth_provider="google",
            provider_subject=PROVIDER_SUBJECT,
            now=NOW,
        )
    assert exc.value.code == "identity_authority_product_mismatch"


def test_safe_dict_reflects_allowed_product_ids_as_sorted_list():
    store, _ = fixture(allowed_product_ids=frozenset({"b62", "b54-padiem-claw"}))
    d = store.safe_dict()
    assert "allowed_product_ids" in d
    assert isinstance(d["allowed_product_ids"], list)
    assert sorted(d["allowed_product_ids"]) == d["allowed_product_ids"]
    assert "b62" in d["allowed_product_ids"]
    assert "b54-padiem-claw" in d["allowed_product_ids"]


def test_b54_session_cannot_be_established_when_store_is_b62_only():
    """A b62-only store must reject b54 session establishment."""
    store, _ = fixture(allowed_product_ids=frozenset({"b62"}))
    result = store.resolve_or_create_product_link(
        product_id="b62",
        product_user_id="usr_1",
        auth_provider="google",
        provider_subject=PROVIDER_SUBJECT,
        now=NOW,
    )
    subject = CanonicalSubjectRef(SubjectType.USER, result.canonical_subject_id)
    with pytest.raises(ControlPlaneContractError) as exc:
        store.establish_auth_session(
            product_id="b54-padiem-claw",
            subject=subject,
            authenticated_at=NOW - timedelta(minutes=1),
            not_after=NOW + timedelta(hours=1),
            now=NOW,
        )
    assert exc.value.code == "identity_authority_product_mismatch"


def test_b62_and_b54_sessions_are_isolated_in_multi_product_store():
    """B62 link/session and B54 link/session must be independent; cross-product session
    establishment for a subject linked under the other product is rejected."""
    store, _ = fixture(allowed_product_ids=frozenset({"b62", "b54-padiem-claw"}))

    # Create a B62 link and session.
    b62_link = store.resolve_or_create_product_link(
        product_id="b62",
        product_user_id="usr_b62",
        auth_provider="google",
        provider_subject=PROVIDER_SUBJECT,
        now=NOW,
    )
    b62_subject = CanonicalSubjectRef(SubjectType.USER, b62_link.canonical_subject_id)
    b62_session = store.establish_auth_session(
        product_id="b62",
        subject=b62_subject,
        authenticated_at=NOW - timedelta(minutes=1),
        not_after=NOW + timedelta(hours=1),
        now=NOW,
    )
    assert b62_session.product_id == "b62"

    # Create a B54 link and session for a different user.
    b54_link = store.resolve_or_create_product_link(
        product_id="b54-padiem-claw",
        product_user_id="usr_b54",
        auth_provider="password",
        provider_subject="b54-pw-subject",
        now=NOW,
    )
    b54_subject = CanonicalSubjectRef(SubjectType.USER, b54_link.canonical_subject_id)
    b54_session = store.establish_auth_session(
        product_id="b54-padiem-claw",
        subject=b54_subject,
        authenticated_at=NOW - timedelta(minutes=1),
        not_after=NOW + timedelta(hours=1),
        now=NOW,
    )
    assert b54_session.product_id == "b54-padiem-claw"

    # Both sessions resolve independently; they have different session IDs.
    assert b62_session.session_id != b54_session.session_id
    assert store.resolve_auth_session(session_id=b62_session.session_id).product_id == "b62"
    assert store.resolve_auth_session(session_id=b54_session.session_id).product_id == "b54-padiem-claw"

    # Attempting to establish a B62 session for the B54-linked subject is rejected.
    # B62 is in the allowlist (product check passes) but the B54 subject has no B62
    # product link → identity_authority_link_missing (fail-closed, no cross-product leakage).
    with pytest.raises(ControlPlaneContractError) as exc:
        store.establish_auth_session(
            product_id="b62",
            subject=b54_subject,
            authenticated_at=NOW - timedelta(minutes=1),
            not_after=NOW + timedelta(hours=1),
            now=NOW,
        )
    assert exc.value.code in {"identity_authority_product_mismatch", "identity_authority_link_missing"}


def test_linked_canonical_subject_can_establish_and_resolve_bounded_active_session():
    store, storage = fixture()
    identity = link(store)
    subject = CanonicalSubjectRef(SubjectType.USER, identity.canonical_subject_id)
    authenticated_at = NOW - timedelta(minutes=1)
    not_after = NOW + timedelta(hours=1)

    session = store.establish_auth_session(
        product_id="b62",
        subject=subject,
        authenticated_at=authenticated_at,
        not_after=not_after,
        now=NOW,
    )
    assert session.session_id.startswith("sess_")
    assert session.product_id == "b62"
    assert session.subject == subject
    assert session.issued_at == NOW
    assert session.expires_at == not_after
    assert session.state is AuthSessionState.ACTIVE
    assert storage.count("canonical_auth_session") == 1

    resolved = store.resolve_auth_session(session_id=session.session_id)
    assert resolved == session
    assert resolved.is_active(now=NOW)


def test_session_requires_active_link_and_unexpired_product_auth_evidence():
    store, storage = fixture()
    unknown = CanonicalSubjectRef(SubjectType.USER, "sub_unknown")
    with pytest.raises(ControlPlaneContractError) as missing:
        store.establish_auth_session(
            product_id="b62",
            subject=unknown,
            authenticated_at=NOW - timedelta(minutes=1),
            not_after=NOW + timedelta(hours=1),
            now=NOW,
        )
    assert missing.value.code == "identity_authority_link_missing"

    identity = link(store)
    subject = CanonicalSubjectRef(SubjectType.USER, identity.canonical_subject_id)
    with pytest.raises(ControlPlaneContractError) as expired:
        store.establish_auth_session(
            product_id="b62",
            subject=subject,
            authenticated_at=NOW - timedelta(hours=2),
            not_after=NOW,
            now=NOW,
        )
    assert expired.value.code == "identity_authority_session_expired"
    assert storage.count("canonical_auth_session") == 0


def test_missing_session_fails_closed_without_synthetic_fallback():
    store, _ = fixture()
    with pytest.raises(ControlPlaneContractError) as exc:
        store.resolve_auth_session(session_id="sess_missing")
    assert exc.value.code == "canonical_auth_session_not_found"
