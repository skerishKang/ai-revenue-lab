from __future__ import annotations

import base64
import hashlib
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


def test_expected_subject_mismatch_does_not_create_subject_or_product_link():
    store, storage = fixture(allowed_product_ids=frozenset({'b62', 'lovetree'}))
    first = link(store, user='usr_existing', provider_subject='provider-A')
    before = (storage.count('canonical_identity_subject'), storage.count('canonical_product_identity_link'))
    with pytest.raises(ControlPlaneContractError) as exc:
        store.resolve_or_create_product_link(
            product_id='b62', product_user_id='usr_new', auth_provider='google',
            provider_subject='provider-B', now=NOW,
            expected_canonical_subject_id=first.canonical_subject_id,
        )
    assert exc.value.code == 'identity_rebind_forbidden'
    assert (storage.count('canonical_identity_subject'), storage.count('canonical_product_identity_link')) == before
    same = store.resolve_or_create_product_link(
        product_id='lovetree', product_user_id='usr_new', auth_provider='google',
        provider_subject='provider-A', now=NOW,
        expected_canonical_subject_id=first.canonical_subject_id,
    )
    assert same.canonical_subject_id == first.canonical_subject_id


def _link_product(store, *, product_id: str, user: str, provider_subject: str = PROVIDER_SUBJECT):
    return store.resolve_or_create_product_link(
        product_id=product_id,
        product_user_id=user,
        auth_provider="google",
        provider_subject=provider_subject,
        now=NOW,
    )


def _session(store, product_id: str, subject_id: str):
    return store.establish_auth_session(
        product_id=product_id,
        subject=CanonicalSubjectRef(SubjectType.USER, subject_id),
        authenticated_at=NOW,
        not_after=NOW + timedelta(days=2),
        now=NOW,
    )


def test_unlinking_one_product_keeps_shared_subject_and_other_sessions_active():
    store, storage = fixture(
        allowed_product_ids=frozenset({"b62", "lovetree-4-0"})
    )
    chat = _link_product(store, product_id="b62", user="usr_chat")
    tree = _link_product(store, product_id="lovetree-4-0", user="usr_tree")
    chat_session = _session(store, "b62", chat.canonical_subject_id)
    tree_session = _session(store, "lovetree-4-0", tree.canonical_subject_id)

    result = store.remove_product_link(
        product_id="b62",
        product_user_id="usr_chat",
        canonical_subject_id=chat.canonical_subject_id,
        now=NOW + timedelta(seconds=1),
    )

    assert result["removed"] is True
    assert result["remaining_links"] == 1
    assert result["common_account_deleted"] is False
    assert store.list_active_product_links_for_subject(
        canonical_subject_id=chat.canonical_subject_id
    ) == [{
        "product_id": "lovetree-4-0",
        "product_user_id": "usr_tree",
        "state": "active",
    }]
    assert store.resolve_auth_session(session_id=chat_session.session_id).state is AuthSessionState.REVOKED
    assert store.resolve_auth_session(session_id=tree_session.session_id).state is AuthSessionState.ACTIVE
    assert storage.count("canonical_identity_subject") == 1
    assert storage.count("canonical_account_deletion_audit") == 0


def test_last_unlink_revokes_every_session_and_keeps_only_hash_and_time_for_one_year():
    store, storage = fixture()
    account = link(store, user="usr_last")
    session = _session(store, "b62", account.canonical_subject_id)

    result = store.remove_product_link(
        product_id="b62",
        product_user_id="usr_last",
        canonical_subject_id=account.canonical_subject_id,
        account_deletion_operation_id="00000000-0000-4000-8000-000000000001",
        now=NOW + timedelta(seconds=1),
    )

    assert result["common_account_deleted"] is True
    assert result["remaining_links"] == 0
    assert result["revoked_sessions"] == 1
    assert store.resolve_auth_session(session_id=session.session_id).state is AuthSessionState.REVOKED
    assert storage.count("canonical_identity_subject") == 0
    assert storage.count("canonical_product_identity_link") == 0
    assert storage.count("canonical_account_deletion_audit") == 1
    columns = [row[1] for row in storage.connection.execute(
        "PRAGMA table_info(canonical_account_deletion_audit)"
    )]
    assert columns == ["user_id_hash", "deleted_at"]
    audit = storage.connection.execute(
        "SELECT user_id_hash, deleted_at FROM canonical_account_deletion_audit"
    ).fetchone()
    assert audit[0] == hashlib.sha256(account.canonical_subject_id.encode()).hexdigest()
    assert account.canonical_subject_id not in str(audit)
    assert datetime.fromisoformat(audit[1]) == NOW + timedelta(seconds=1)

    retry = store.remove_product_link(
        product_id="b62",
        product_user_id="usr_last",
        canonical_subject_id=account.canonical_subject_id,
        now=NOW + timedelta(seconds=2),
    )
    assert retry["already_deleted"] is True
    assert storage.count("canonical_account_deletion_audit") == 1

    store.prune_expired_deletion_audits(now=NOW + timedelta(days=366))
    assert storage.count("canonical_account_deletion_audit") == 0


def test_last_link_requires_auth_preparation_before_any_identity_mutation():
    store, storage = fixture()
    account = link(store, user="usr_unprepared")
    session = _session(store, "b62", account.canonical_subject_id)

    with pytest.raises(ControlPlaneContractError) as exc:
        store.remove_product_link(
            product_id="b62",
            product_user_id="usr_unprepared",
            canonical_subject_id=account.canonical_subject_id,
            now=NOW + timedelta(seconds=1),
        )

    assert exc.value.code == "account_deletion_unprepared"
    assert storage.count("canonical_identity_subject") == 1
    assert storage.count("canonical_product_identity_link") == 1
    assert storage.count("canonical_account_deletion_audit") == 0
    assert store.list_active_product_links_for_subject(
        canonical_subject_id=account.canonical_subject_id
    ) == [{
        "product_id": "b62",
        "product_user_id": "usr_unprepared",
        "state": "active",
    }]
    assert store.resolve_auth_session(session_id=session.session_id).state is AuthSessionState.ACTIVE


def test_product_link_removal_rejects_a_different_subject_without_mutation():
    store, storage = fixture(
        allowed_product_ids=frozenset({"b62", "lovetree-4-0"})
    )
    first = _link_product(store, product_id="b62", user="usr_one")
    second = _link_product(store, product_id="lovetree-4-0", user="usr_two", provider_subject="other-provider-subject")

    with pytest.raises(ControlPlaneContractError) as exc:
        store.remove_product_link(
            product_id="b62",
            product_user_id="usr_one",
            canonical_subject_id=second.canonical_subject_id,
            now=NOW + timedelta(seconds=1),
        )

    assert exc.value.code == "identity_rebind_forbidden"
    assert storage.count("canonical_identity_subject") == 2
    assert storage.count("canonical_product_identity_link") == 2
    assert store.list_active_product_links_for_subject(
        canonical_subject_id=first.canonical_subject_id
    )[0]["product_id"] == "b62"


class _RecordingSql(FakeSql):
    def __init__(self, connection: sqlite3.Connection) -> None:
        super().__init__(connection)
        self.statements: list[str] = []

    def exec(self, statement: str, *args):
        self.statements.append(statement)
        return super().exec(statement, *args)


def _store_on(storage: FakeStorage) -> CloudflareCanonicalIdentityAuthorityStore:
    return CloudflareCanonicalIdentityAuthorityStore(
        storage, lookup_key=LOOKUP_KEY_BYTES, allowed_product_ids=frozenset({"b62"})
    )


def test_current_schema_store_reads_the_version_once_and_skips_every_ddl() -> None:
    """A warm Durable Object must not repeat the create/migrate sequence."""

    storage = FakeStorage()
    _store_on(storage)
    recording = _RecordingSql(storage.connection)
    storage.sql = recording

    _store_on(storage)

    assert len(recording.statements) == 1
    assert recording.statements[0].lstrip().upper().startswith("SELECT")
    assert "schema_version" in recording.statements[0]


def test_fresh_and_older_stores_still_create_and_migrate() -> None:
    storage = FakeStorage()
    recording = _RecordingSql(storage.connection)
    storage.sql = recording

    _store_on(storage)

    ddl = [
        statement
        for statement in recording.statements
        if "CREATE TABLE" in statement or "CREATE INDEX" in statement
    ]
    assert len(ddl) >= 9
    assert any("idx_canonical_auth_session_current" in statement for statement in ddl)

    # An older recorded version keeps the unchanged create-and-migrate path.
    storage.connection.execute(
        "UPDATE identity_authority_schema SET value=? WHERE key='schema_version'", ("4",)
    )
    recording.statements.clear()

    store = _store_on(storage)

    assert any("CREATE TABLE" in statement for statement in recording.statements)
    assert any(
        "idx_canonical_auth_session_current" in statement
        for statement in recording.statements
    )
    assert store._schema_version() == 5
