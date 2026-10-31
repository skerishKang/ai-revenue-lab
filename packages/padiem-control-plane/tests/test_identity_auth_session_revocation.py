"""#5225: the canonical Control Plane session store is the logout revocation authority.

A PADIEM logout must end exactly one canonical auth session, so a session cookie
stored before the logout stops authenticating while another device that signed
in normally keeps its own session. The revocation is materialized through the
existing canonical ``apply_auth_session_transition`` contract, so expiry and
revocation stay monotonic and a terminal session never reactivates in place.
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
    SubjectType,
)


NOW = datetime(2026, 10, 20, 9, 0, tzinfo=timezone.utc)
LOOKUP_KEY_BYTES = b"I" * 32
LOOKUP_KEY = base64.urlsafe_b64encode(LOOKUP_KEY_BYTES).decode("ascii").rstrip("=")
PROVIDER_SUBJECT = "google-provider-subject-sensitive-5225"
ALLOWED_PRODUCTS = frozenset({"b62", "b54-padiem-claw"})


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


class TokenSource:
    def __init__(self) -> None:
        self.count = 0

    def __call__(self, bytes_count: int) -> str:
        self.count += 1
        return f"{self.count:0{bytes_count * 2}x}"[-bytes_count * 2 :]


def fixture():
    storage = FakeStorage()
    store = CloudflareCanonicalIdentityAuthorityStore(
        storage,
        lookup_key=LOOKUP_KEY_BYTES,
        allowed_product_ids=ALLOWED_PRODUCTS,
        random_hex=TokenSource(),
    )
    return store, storage


def _session(store, *, product_id="b62", user="usr_5225", provider_subject=PROVIDER_SUBJECT):
    link = store.resolve_or_create_product_link(
        product_id=product_id,
        product_user_id=user,
        auth_provider="google",
        provider_subject=provider_subject,
        now=NOW,
    )
    subject = CanonicalSubjectRef(
        subject_type=SubjectType.USER,
        subject_id=link.canonical_subject_id,
    )
    return store.establish_auth_session(
        product_id=product_id,
        subject=subject,
        authenticated_at=NOW,
        not_after=NOW + timedelta(hours=1),
        now=NOW,
    )


def test_lookup_key_still_requires_exactly_32_random_bytes():
    assert decode_identity_lookup_key(LOOKUP_KEY) == LOOKUP_KEY_BYTES
    with pytest.raises(ControlPlaneContractError):
        decode_identity_lookup_key("short")


def test_revoking_one_session_leaves_the_other_device_session_active():
    store, _storage = fixture()
    device_a = _session(store)
    device_b = _session(store)
    assert device_a.session_id != device_b.session_id

    revoked = store.revoke_auth_session(
        product_id="b62",
        session_id=device_a.session_id,
        now=NOW + timedelta(minutes=5),
    )

    assert revoked.state is AuthSessionState.REVOKED
    assert revoked.revision == device_a.revision + 1
    assert revoked.session_id == device_a.session_id
    # The other device keeps its own session: a logout never ends a session the
    # logout did not own.
    survivor = store.resolve_auth_session(session_id=device_b.session_id)
    assert survivor.state is AuthSessionState.ACTIVE
    assert survivor.is_active(now=NOW + timedelta(minutes=5))
    # The revoked session is terminal and can no longer be effective-ACTIVE.
    stored = store.resolve_auth_session(session_id=device_a.session_id)
    assert stored.state is AuthSessionState.REVOKED
    assert stored.is_active(now=NOW + timedelta(minutes=5)) is False
    assert store.resolve_current_auth_session_for_product_user(
        product_id="b62",
        product_user_id="usr_5225",
        now=NOW + timedelta(minutes=5),
    ).session_id == device_b.session_id


def test_revocation_is_idempotent_and_never_reactivates_a_terminal_session():
    store, _storage = fixture()
    session = _session(store)

    first = store.revoke_auth_session(
        product_id="b62", session_id=session.session_id, now=NOW + timedelta(minutes=1)
    )
    second = store.revoke_auth_session(
        product_id="b62", session_id=session.session_id, now=NOW + timedelta(minutes=2)
    )

    assert second.state is AuthSessionState.REVOKED
    assert second.revision == first.revision
    assert store.resolve_auth_session(session_id=session.session_id).revision == first.revision


def test_revoking_a_foreign_product_session_fails_closed():
    store, _storage = fixture()
    claw_session = _session(store, product_id="b54-padiem-claw", user="usr_claw_5225")

    with pytest.raises(ControlPlaneContractError) as exc:
        store.revoke_auth_session(
            product_id="b62",
            session_id=claw_session.session_id,
            now=NOW + timedelta(minutes=1),
        )
    assert exc.value.code == "identity_authority_product_mismatch"
    assert store.resolve_auth_session(session_id=claw_session.session_id).state is AuthSessionState.ACTIVE


def test_revoking_an_unknown_session_fails_closed():
    store, _storage = fixture()
    with pytest.raises(ControlPlaneContractError) as exc:
        store.revoke_auth_session(
            product_id="b62", session_id="sess_missing000000000000000000000000", now=NOW
        )
    assert exc.value.code == "canonical_auth_session_not_found"


def test_revocation_rejects_an_unbounded_session_identifier():
    store, _storage = fixture()
    with pytest.raises(ControlPlaneContractError) as exc:
        store.revoke_auth_session(
            product_id="b62", session_id="not a safe session id", now=NOW
        )
    assert exc.value.code == "invalid_identity_authority"


def test_revocation_rejects_a_product_outside_the_authority_allowlist():
    store, _storage = fixture()
    with pytest.raises(ControlPlaneContractError) as exc:
        store.revoke_auth_session(
            product_id="b66", session_id="sess_0123456789abcdef0123456789abcdef", now=NOW
        )
    assert exc.value.code == "identity_authority_product_mismatch"


# #5441: a replaced credential has to end every session it could still
# authenticate, on every device.


def test_revoking_all_sessions_of_one_product_user_ends_every_device_session():
    store, _storage = fixture()
    device_a = _session(store)
    device_b = _session(store)
    other_user = _session(store, user="usr_other_5441", provider_subject="other-subject-5441")

    revoked = store.revoke_all_auth_sessions_for_product_user(
        product_id="b62",
        product_user_id="usr_5225",
        now=NOW + timedelta(minutes=5),
    )

    assert {session.session_id for session in revoked} == {
        device_a.session_id,
        device_b.session_id,
    }
    for session in (device_a, device_b):
        stored = store.resolve_auth_session(session_id=session.session_id)
        assert stored.state is AuthSessionState.REVOKED
        assert stored.is_active(now=NOW + timedelta(minutes=5)) is False
    # Another account keeps its own sessions.
    survivor = store.resolve_auth_session(session_id=other_user.session_id)
    assert survivor.state is AuthSessionState.ACTIVE


def test_revoking_all_sessions_is_idempotent_and_never_reactivates_a_terminal_session():
    store, _storage = fixture()
    session = _session(store)

    first = store.revoke_all_auth_sessions_for_product_user(
        product_id="b62", product_user_id="usr_5225", now=NOW + timedelta(minutes=1)
    )
    second = store.revoke_all_auth_sessions_for_product_user(
        product_id="b62", product_user_id="usr_5225", now=NOW + timedelta(minutes=2)
    )

    assert len(first) == 1
    assert second == []
    stored = store.resolve_auth_session(session_id=session.session_id)
    assert stored.state is AuthSessionState.REVOKED
    assert stored.revision == first[0].revision


def test_revoking_all_sessions_of_an_unlinked_product_user_fails_closed():
    store, _storage = fixture()
    with pytest.raises(ControlPlaneContractError) as exc:
        store.revoke_all_auth_sessions_for_product_user(
            product_id="b62", product_user_id="usr_missing_5441", now=NOW
        )
    assert exc.value.code == "canonical_product_identity_link_not_found"


def test_revoking_all_sessions_rejects_a_product_outside_the_authority_allowlist():
    store, _storage = fixture()
    with pytest.raises(ControlPlaneContractError) as exc:
        store.revoke_all_auth_sessions_for_product_user(
            product_id="b66", product_user_id="usr_5225", now=NOW
        )
    assert exc.value.code == "identity_authority_product_mismatch"


def test_revoking_all_sessions_never_touches_another_product_session():
    store, _storage = fixture()
    _session(store)
    claw_session = _session(store, product_id="b54-padiem-claw", user="usr_claw_5441")

    store.revoke_all_auth_sessions_for_product_user(
        product_id="b62", product_user_id="usr_5225", now=NOW + timedelta(minutes=1)
    )

    survivor = store.resolve_auth_session(session_id=claw_session.session_id)
    assert survivor.state is AuthSessionState.ACTIVE

