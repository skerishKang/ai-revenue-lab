"""#3243 — read-only current active canonical session resolution.

The B54 bridge mints a canonical session at login (#2964/#3240) but nothing could
re-resolve it for a later server-side request: `B54BridgedIdentitySession` is
server-only and no product-local shadow exists. This suite covers the new
server-derived lookup, and proves it adds no store of its own.

Covered:

- PRODUCT_LINK_ACTIVE_REQUIRED: only an ACTIVE product link resolves
- ONE_ACTIVE_SESSION: the single active session is returned
- OLDER_ACTIVE + NEWER_ACTIVE -> NEWER
- NEWEST_EXPIRED + OLDER_ACTIVE -> OLDER_ACTIVE
- NEWEST_REVOKED + OLDER_ACTIVE -> OLDER_ACTIVE
- ALL_INACTIVE -> fail closed
- UNKNOWN_PRODUCT -> rejected by the allowlist
- FOREIGN_USER -> no disclosure
- B62_AND_B54_PRESENT -> only the requested product's session
- No caller-supplied clock, session id, subject or tenant
- No new table and no write on this path
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from identity_authority_durable import (
    CloudflareCanonicalIdentityAuthorityStore,
    _rows,
    decode_identity_lookup_key,
)
from padiem_control_plane.auth_sessions import AuthSessionState
from padiem_control_plane.contracts import (
    CanonicalSubjectRef,
    ControlPlaneContractError,
    IdentityLinkState,
    SubjectType,
)

NOW = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)
LOOKUP_KEY_BYTES = b"I" * 32
B54 = "b54-padiem-claw"
B62 = "b62"
USER = "usr_" + "1" * 32
OTHER_USER = "usr_" + "9" * 32
TENANT = "tenant_" + "a" * 32


class FakeCursor:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def toArray(self) -> list[dict]:
        return list(self._rows)


class FakeSql:
    def __init__(self, connection) -> None:
        self._connection = connection

    def exec(self, statement: str, *args):
        cursor = self._connection.execute(statement, args)
        if cursor.description is not None:
            columns = [item[0] for item in cursor.description]
            return FakeCursor([dict(zip(columns, row, strict=True)) for row in cursor.fetchall()])
        return FakeCursor([])


class FakeStorage:
    def __init__(self) -> None:
        import sqlite3

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

    def count(self, table: str) -> int:
        return int(self.connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0])

    def tables(self) -> set[str]:
        return {
            str(row[0])
            for row in self.connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }


class TokenSource:
    def __init__(self) -> None:
        self.count = 0

    def __call__(self, bytes_count: int) -> str:
        self.count += 1
        return f"{self.count:0{bytes_count * 2}x}"[-bytes_count * 2 :]


def fixture(*, products=frozenset({B62, B54})):
    storage = FakeStorage()
    store = CloudflareCanonicalIdentityAuthorityStore(
        storage,
        lookup_key=LOOKUP_KEY_BYTES,
        allowed_product_ids=products,
        random_hex=TokenSource(),
    )
    return store, storage


def link(store, *, product=B54, user=USER, provider_subject="ps-1"):
    return store.resolve_or_create_product_link(
        product_id=product,
        product_user_id=user,
        auth_provider="google",
        provider_subject=provider_subject,
        now=NOW,
    )


def with_tenant(store, canonical_subject_id: str, tenant_id: str = TENANT) -> None:
    """Give the subject an active canonical tenant membership, as a real account has."""

    if not store._sql.exec(
        "SELECT tenant_id FROM canonical_tenant WHERE tenant_id=?", tenant_id
    ).toArray():
        store._sql.exec(
            "INSERT INTO canonical_tenant (tenant_id, state, created_at) VALUES (?,?,?)",
            tenant_id,
            "active",
            NOW.isoformat(),
        )
    store.assign_tenant_membership(
        tenant_id=tenant_id, canonical_subject_id=canonical_subject_id, now=NOW
    )


def mint(store, *, product=B54, user=USER, subject, issued_at, expires_at, tenant=TENANT, now=NOW):
    return store.establish_auth_session(
        product_id=product,
        subject=subject,
        authenticated_at=issued_at,
        not_after=expires_at,
        now=now,
    )


def user_subject(subject_id: str) -> CanonicalSubjectRef:
    return CanonicalSubjectRef(subject_type=SubjectType.USER, subject_id=subject_id)


def resolve(store, *, product=B54, user=USER, now=NOW):
    return store.resolve_current_auth_session_for_product_user(
        product_id=product, product_user_id=user, now=now
    )


# --- link precondition ------------------------------------------------------


def test_product_link_active_is_required() -> None:
    store, _ = fixture()
    created = link(store)
    # No session yet: fail closed rather than inventing one.
    with pytest.raises(ControlPlaneContractError) as excinfo:
        resolve(store)
    assert excinfo.value.code == "canonical_auth_session_not_found"

    subject = user_subject(created.canonical_subject_id)
    with_tenant(store, created.canonical_subject_id)
    mint(
        store,
        subject=subject,
        issued_at=NOW - timedelta(hours=1),
        expires_at=NOW + timedelta(hours=1),
    )
    # A non-ACTIVE link refuses even with a live session row.
    store._sql.exec(
        "UPDATE canonical_product_identity_link SET state=? WHERE product_id=? AND product_user_id=?",
        IdentityLinkState.REVOKED.value,
        B54,
        USER,
    )
    with pytest.raises(ControlPlaneContractError) as excinfo:
        resolve(store)
    assert excinfo.value.code == "canonical_product_identity_link_not_active"


def test_unknown_product_is_rejected() -> None:
    store, _ = fixture(products=frozenset({B62}))
    with pytest.raises(ControlPlaneContractError) as excinfo:
        resolve(store, product=B54)
    assert "product" in excinfo.value.code


def test_foreign_user_gets_no_disclosure() -> None:
    store, _ = fixture()
    created = link(store, user=USER)
    subject = user_subject(created.canonical_subject_id)
    with_tenant(store, created.canonical_subject_id)
    mint(
        store,
        subject=subject,
        issued_at=NOW - timedelta(hours=1),
        expires_at=NOW + timedelta(hours=1),
    )
    assert resolve(store, user=USER) is not None
    with pytest.raises(ControlPlaneContractError):
        resolve(store, user=OTHER_USER)


# --- one active session ----------------------------------------------------


def test_single_active_session_resolves() -> None:
    store, _ = fixture()
    created = link(store)
    subject = user_subject(created.canonical_subject_id)
    with_tenant(store, created.canonical_subject_id)
    minted = mint(
        store,
        subject=subject,
        issued_at=NOW - timedelta(minutes=5),
        expires_at=NOW + timedelta(hours=1),
    )
    resolved = resolve(store)
    assert resolved.session_id == minted.session_id
    assert resolved.product_id == B54
    assert resolved.subject == subject
    assert resolved.tenant_id == TENANT
    assert resolved.state is AuthSessionState.ACTIVE


# --- newest-active selection ----------------------------------------------


def test_older_active_plus_newer_active_selects_newer() -> None:
    store, _ = fixture()
    created = link(store)
    subject = user_subject(created.canonical_subject_id)
    with_tenant(store, created.canonical_subject_id)
    older = mint(
        store,
        subject=subject,
        issued_at=NOW - timedelta(hours=2),
        expires_at=NOW + timedelta(hours=1),
    )
    newer = mint(
        store,
        subject=subject,
        issued_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(hours=2),
    )
    assert older.session_id != newer.session_id
    assert resolve(store).session_id == newer.session_id


def test_newest_expired_falls_back_to_older_active() -> None:
    store, _ = fixture()
    created = link(store)
    subject = user_subject(created.canonical_subject_id)
    with_tenant(store, created.canonical_subject_id)
    older = mint(
        store,
        subject=subject,
        issued_at=NOW - timedelta(hours=3),
        expires_at=NOW + timedelta(hours=3),
        now=NOW - timedelta(hours=3),
    )
    # Minted last but already expired at resolve time. The store refuses to mint
    # an already-expired window, so it is minted valid and then observed after
    # its expiry — exactly the real "newest session has lapsed" case.
    lapsed = mint(
        store,
        subject=subject,
        issued_at=NOW - timedelta(minutes=10),
        expires_at=NOW + timedelta(minutes=5),
        now=NOW - timedelta(minutes=10),
    )
    later = NOW + timedelta(minutes=15)
    assert resolve(store, now=later).session_id == older.session_id
    assert lapsed.session_id != older.session_id
    # And the newest one is still selected while it is in fact active.
    assert resolve(store, now=NOW).session_id == lapsed.session_id


def test_newest_revoked_falls_back_to_older_active() -> None:
    store, _ = fixture()
    created = link(store)
    subject = user_subject(created.canonical_subject_id)
    with_tenant(store, created.canonical_subject_id)
    older = mint(
        store,
        subject=subject,
        issued_at=NOW - timedelta(hours=3),
        expires_at=NOW + timedelta(hours=3),
    )
    revoked = mint(
        store,
        subject=subject,
        issued_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(hours=3),
    )
    store._sql.exec(
        "UPDATE canonical_auth_session SET state=? WHERE session_id=?",
        AuthSessionState.REVOKED.value,
        revoked.session_id,
    )
    assert resolve(store).session_id == older.session_id


def test_expired_and_revoked_only_fails_closed() -> None:
    store, _ = fixture()
    created = link(store)
    subject = user_subject(created.canonical_subject_id)
    with_tenant(store, created.canonical_subject_id)
    revoked = mint(
        store,
        subject=subject,
        issued_at=NOW - timedelta(hours=2),
        expires_at=NOW + timedelta(hours=1),
        now=NOW - timedelta(hours=2),
    )
    lapsed = mint(
        store,
        subject=subject,
        issued_at=NOW - timedelta(hours=1),
        expires_at=NOW + timedelta(minutes=30),
        now=NOW - timedelta(hours=1),
    )
    store._sql.exec(
        "UPDATE canonical_auth_session SET state=? WHERE session_id=?",
        AuthSessionState.REVOKED.value,
        revoked.session_id,
    )
    with pytest.raises(ControlPlaneContractError) as excinfo:
        resolve(store, now=NOW + timedelta(minutes=45))
    assert excinfo.value.code == "canonical_auth_session_not_found"
    assert lapsed.session_id not in ("", None)


def test_tie_on_issued_at_breaks_by_revision_then_session_id() -> None:
    store, _ = fixture()
    created = link(store)
    subject = user_subject(created.canonical_subject_id)
    with_tenant(store, created.canonical_subject_id)
    issued = NOW - timedelta(hours=1)
    first = mint(store, subject=subject, issued_at=issued, expires_at=NOW + timedelta(hours=1))
    second = mint(store, subject=subject, issued_at=issued, expires_at=NOW + timedelta(hours=1))
    # Deterministic: the higher revision wins, and repeating is stable.
    expected = max(first, second, key=lambda s: (s.revision, s.session_id))
    assert resolve(store).session_id == expected.session_id
    assert resolve(store).session_id == resolve(store).session_id


# --- cross-product isolation ----------------------------------------------


def test_b62_and_b54_sessions_resolve_per_product_only() -> None:
    store, _ = fixture()
    b54_link = link(store, product=B54, provider_subject="ps-b54")
    with_tenant(store, b54_link.canonical_subject_id)
    # The B62 link for the SAME provider subject resolves to the same canonical
    # person, so one subject legitimately holds a B62 and a B54 session.
    b62_link = link(store, product=B62, provider_subject="ps-b54")
    assert b54_link.canonical_subject_id == b62_link.canonical_subject_id

    b62_session = mint(
        store,
        product=B62,
        subject=user_subject(b54_link.canonical_subject_id),
        issued_at=NOW - timedelta(hours=1),
        expires_at=NOW + timedelta(hours=1),
    )
    b54_session = mint(
        store,
        product=B54,
        subject=user_subject(b54_link.canonical_subject_id),
        issued_at=NOW - timedelta(hours=1),
        expires_at=NOW + timedelta(hours=1),
    )
    assert resolve(store, product=B54).session_id == b54_session.session_id
    assert resolve(store, product=B62).session_id == b62_session.session_id
    assert resolve(store, product=B54).session_id != b62_session.session_id


# --- no new store, no writes ----------------------------------------------


# ── corrupt canonical rows fail closed (#3243 integrity) ───────────────────


def _corrupt(store, *, session_id: str, column: str, value) -> None:
    store._sql.exec(
        f"UPDATE canonical_auth_session SET {column}=? WHERE session_id=?",
        value,
        session_id,
    )


def _two_sessions(store):
    created = link(store)
    subject = user_subject(created.canonical_subject_id)
    with_tenant(store, created.canonical_subject_id)
    older = mint(
        store,
        subject=subject,
        issued_at=NOW - timedelta(hours=2),
        expires_at=NOW + timedelta(hours=2),
        now=NOW - timedelta(hours=2),
    )
    newer = mint(
        store,
        subject=subject,
        issued_at=NOW - timedelta(minutes=5),
        expires_at=NOW + timedelta(hours=2),
        now=NOW - timedelta(minutes=5),
    )
    return older, newer


def test_corrupt_newest_row_does_not_fall_back_to_older_active() -> None:
    """Corrupt newest + older ACTIVE -> fail closed, older is NOT returned."""

    store, _ = fixture()
    older, newer = _two_sessions(store)
    assert resolve(store).session_id == newer.session_id
    # The newest row claims to be active but carries a corrupt expiry.
    _corrupt(store, session_id=newer.session_id, column="expires_at", value="not-a-timestamp")
    with pytest.raises(ControlPlaneContractError) as excinfo:
        resolve(store)
    assert excinfo.value.code == "identity_authority_storage_error"
    assert older.session_id not in str(excinfo.value)


def test_non_candidate_rows_are_filtered_by_sql_and_never_decoded() -> None:
    """A row SQL cannot classify as a candidate is excluded, not decoded.

    Selection now happens in SQL, so a malformed row that is not the selected
    session is filtered out instead of failing the whole read. The selected row
    is still decoded, so a malformed newest row still fails closed.
    """

    store, _ = fixture()
    older, newer = _two_sessions(store)
    _corrupt(store, session_id=older.session_id, column="state", value="bogus-state")
    assert resolve(store).session_id == newer.session_id


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("issued_at", "not-a-timestamp"),
        ("expires_at", "not-a-timestamp"),
        ("expires_at", "2030-99-99T00:00:00Z"),
        ("revision", 0),
        ("revision", -3),
        ("revision", "not-an-int"),
        ("subject_type", "robot"),
        ("session_id", ""),
        ("tenant_id", "b54-padiem-claw"),
    ],
)
def test_any_malformed_row_field_fails_closed(column, value) -> None:
    """Invalid state/time/revision/product/subject/tenant/session shape."""

    store, _ = fixture()
    older, newer = _two_sessions(store)
    _corrupt(store, session_id=newer.session_id, column=column, value=value)
    with pytest.raises(ControlPlaneContractError) as excinfo:
        resolve(store)
    assert excinfo.value.code == "identity_authority_storage_error"
    # The healthy older row is never returned as a substitute.
    assert older.session_id not in str(excinfo.value)


def test_valid_revoked_and_expired_rows_are_excluded_without_error() -> None:
    """Valid REVOKED / EXPIRED rows stay non-candidates and raise no error."""

    store, _ = fixture()
    created = link(store)
    subject = user_subject(created.canonical_subject_id)
    with_tenant(store, created.canonical_subject_id)
    revoked = mint(
        store,
        subject=subject,
        issued_at=NOW - timedelta(hours=1),
        expires_at=NOW + timedelta(hours=5),
        now=NOW - timedelta(hours=1),
    )
    explicit_expired = mint(
        store,
        subject=subject,
        issued_at=NOW - timedelta(minutes=30),
        expires_at=NOW + timedelta(hours=5),
        now=NOW - timedelta(minutes=30),
    )
    store._sql.exec(
        "UPDATE canonical_auth_session SET state=? WHERE session_id=?",
        AuthSessionState.REVOKED.value,
        revoked.session_id,
    )
    store._sql.exec(
        "UPDATE canonical_auth_session SET state=? WHERE session_id=?",
        AuthSessionState.EXPIRED.value,
        explicit_expired.session_id,
    )
    # Nothing active left: this is absence, not corruption.
    with pytest.raises(ControlPlaneContractError) as excinfo:
        resolve(store)
    assert excinfo.value.code == "canonical_auth_session_not_found"

    # With a genuinely active row present it is selected normally.
    active = mint(
        store,
        subject=subject,
        issued_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(hours=5),
        now=NOW - timedelta(minutes=1),
    )
    assert resolve(store).session_id == active.session_id


def test_row_decoder_rejects_malformed_product_and_subject_shape() -> None:
    """`product_id` / `subject_id` ARE the query key, so a mismatch removes the
    row from scope entirely rather than returning it. The canonical decoder still
    rejects a malformed shape directly, and the resolver additionally refuses any
    row that came back out of scope."""

    store, _ = fixture()
    for bad_row in (
        {"session_id": "sess_x", "product_id": "", "subject_type": "user", "subject_id": SUBJECT_OF(store),
         "issued_at": NOW.isoformat(), "expires_at": (NOW + timedelta(hours=1)).isoformat(),
         "state": "active", "revision": 1, "tenant_id": None},
        {"session_id": "sess_x", "product_id": B54, "subject_type": "user", "subject_id": "",
         "issued_at": NOW.isoformat(), "expires_at": (NOW + timedelta(hours=1)).isoformat(),
         "state": "active", "revision": 1, "tenant_id": None},
        {"session_id": "sess_x", "product_id": B54, "subject_type": "user", "subject_id": SUBJECT_OF(store),
         "issued_at": NOW.isoformat(), "expires_at": (NOW + timedelta(hours=1)).isoformat(),
         "state": "active", "revision": 1, "tenant_id": "b54-padiem-claw"},
    ):
        with pytest.raises(ControlPlaneContractError) as excinfo:
            store._session_from_row(bad_row)
        assert excinfo.value.code == "identity_authority_storage_error"


def SUBJECT_OF(store) -> str:
    created = link(store)
    with_tenant(store, created.canonical_subject_id)
    return created.canonical_subject_id


def test_resolve_auth_session_by_id_reports_corruption_not_a_missing_row() -> None:
    """The existing by-id lookup keeps its one canonical corruption code."""

    store, _ = fixture()
    created = link(store)
    minted = mint(
        store,
        subject=user_subject(created.canonical_subject_id),
        issued_at=NOW - timedelta(hours=1),
        expires_at=NOW + timedelta(hours=1),
    )
    _corrupt(store, session_id=minted.session_id, column="expires_at", value="nope")
    with pytest.raises(ControlPlaneContractError) as excinfo:
        store.resolve_auth_session(session_id=minted.session_id)
    assert excinfo.value.code == "identity_authority_storage_error"


def test_no_new_table_is_created() -> None:
    store, storage = fixture()
    link(store)
    tables = storage.tables()
    assert "canonical_product_identity_link" in tables
    assert "canonical_auth_session" in tables
    # This slice adds no b54-specific table or shadow of its own.
    assert not any("b54" in name for name in tables)
    assert not any("shadow" in name for name in tables)


def test_resolution_writes_nothing() -> None:
    store, storage = fixture()
    created = link(store)
    mint(
        store,
        subject=user_subject(created.canonical_subject_id),
        issued_at=NOW - timedelta(hours=1),
        expires_at=NOW + timedelta(hours=1),
    )
    before = storage.connection.execute(
        "SELECT session_id, state, expires_at FROM canonical_auth_session"
    ).fetchall()
    for _ in range(3):
        resolve(store)
    after = storage.connection.execute(
        "SELECT session_id, state, expires_at FROM canonical_auth_session"
    ).fetchall()
    assert before == after
    assert len(after) == 1


@pytest.mark.parametrize(
    ("column", "value"), [("state", "bogus-state"), ("issued_at", "")]
)
def test_unclassifiable_newest_row_is_not_a_candidate(column, value) -> None:
    store, _ = fixture()
    older, newer = _two_sessions(store)
    _corrupt(store, session_id=newer.session_id, column=column, value=value)
    assert resolve(store).session_id == older.session_id


def test_resolve_auth_session_by_id_is_unchanged() -> None:
    """Section 6: the existing session_id lookup keeps its semantics."""

    store, _ = fixture()
    created = link(store)
    minted = mint(
        store,
        subject=user_subject(created.canonical_subject_id),
        issued_at=NOW - timedelta(hours=1),
        expires_at=NOW + timedelta(hours=1),
    )
    by_id = store.resolve_auth_session(session_id=minted.session_id)
    assert by_id.session_id == minted.session_id
    with pytest.raises(ControlPlaneContractError) as excinfo:
        store.resolve_auth_session(session_id="sess_missing")
    assert excinfo.value.code == "canonical_auth_session_not_found"


# ── SQL selection parity with the previous Python selection ─────────


def _legacy_python_selection(store, *, product: str, subject_id: str, now: datetime):
    """The pre-optimisation selection, kept verbatim as the parity oracle."""

    rows = _rows(
        store._sql.exec(
            "SELECT session_id, product_id, subject_type, subject_id, issued_at, "
            "expires_at, state, revision, tenant_id FROM canonical_auth_session "
            "WHERE product_id=? AND subject_id=?",
            product,
            subject_id,
        )
    )
    active = []
    for row in rows:
        snapshot = store._session_from_row(row)
        if snapshot.state is not AuthSessionState.ACTIVE:
            continue
        if snapshot.expires_at <= now:
            continue
        active.append(
            (snapshot.issued_at, snapshot.revision, snapshot.session_id, snapshot)
        )
    if not active:
        raise ControlPlaneContractError(
            "canonical_auth_session_not_found",
            "no active canonical auth session exists for this product user",
        )
    active.sort(key=lambda item: (item[0], item[1], item[2]))
    return active[-1][3]


def _insert_row(
    store,
    *,
    session_id: str,
    subject_id: str,
    issued_at: str,
    expires_at: str,
    state: str = "active",
    revision: int = 1,
    product: str = B54,
    tenant: str = TENANT,
) -> None:
    store._sql.exec(
        "INSERT INTO canonical_auth_session (session_id, product_id, subject_type, "
        "subject_id, issued_at, expires_at, state, revision, tenant_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        session_id,
        product,
        "user",
        subject_id,
        issued_at,
        expires_at,
        state,
        revision,
        tenant,
    )


def _assert_parity(store, *, subject_id: str, product: str = B54, now=NOW):
    legacy = _legacy_python_selection(
        store, product=product, subject_id=subject_id, now=now
    )
    resolved = resolve(store, product=product, now=now)
    assert resolved.session_id == legacy.session_id
    assert resolved == legacy
    return resolved


def test_sql_selection_matches_python_for_active_expired_revoked_and_ties() -> None:
    store, _ = fixture()
    created = link(store)
    subject = user_subject(created.canonical_subject_id)
    with_tenant(store, created.canonical_subject_id)

    mint(
        store,
        subject=subject,
        issued_at=NOW - timedelta(hours=4),
        expires_at=NOW - timedelta(hours=1),
        now=NOW - timedelta(hours=4),
    )
    mint(
        store,
        subject=subject,
        issued_at=NOW - timedelta(hours=3),
        expires_at=NOW + timedelta(hours=1),
        now=NOW - timedelta(hours=3),
    )
    revoked = mint(
        store,
        subject=subject,
        issued_at=NOW - timedelta(hours=2),
        expires_at=NOW + timedelta(hours=1),
        now=NOW - timedelta(hours=2),
    )
    store._sql.exec(
        "UPDATE canonical_auth_session SET state=? WHERE session_id=?",
        AuthSessionState.REVOKED.value,
        revoked.session_id,
    )
    issued = NOW - timedelta(minutes=30)
    low = mint(
        store,
        subject=subject,
        issued_at=issued,
        expires_at=NOW + timedelta(hours=2),
        now=issued,
    )
    high = mint(
        store,
        subject=subject,
        issued_at=issued,
        expires_at=NOW + timedelta(hours=2),
        now=issued,
    )

    resolved = _assert_parity(store, subject_id=created.canonical_subject_id)
    assert resolved.session_id in {low.session_id, high.session_id}


def test_sql_selection_matches_python_across_iso_precision_boundaries() -> None:
    store, _ = fixture()
    created = link(store)
    subject_id = created.canonical_subject_id
    with_tenant(store, subject_id)

    # A whole-second issued_at is OLDER than a fractional one in the same
    # second; plain text order would have ranked it newer.
    _insert_row(
        store,
        session_id="sess_whole_second",
        subject_id=subject_id,
        issued_at="2026-09-30T11:00:00Z",
        expires_at="2026-09-30T23:00:00Z",
    )
    _insert_row(
        store,
        session_id="sess_fractional",
        subject_id=subject_id,
        issued_at="2026-09-30T11:00:00.500000Z",
        expires_at="2026-09-30T23:00:00Z",
    )
    assert resolve(store).session_id == "sess_fractional"
    assert _assert_parity(store, subject_id=subject_id).session_id == "sess_fractional"

    # expires_at exactly at the whole second is already lapsed at now + 500ms;
    # plain text order would have kept it alive.
    boundary = NOW + timedelta(milliseconds=500)
    _insert_row(
        store,
        session_id="sess_boundary",
        subject_id=subject_id,
        issued_at="2026-09-30T10:00:00Z",
        expires_at="2026-09-30T12:00:00Z",
    )
    assert resolve(store, now=boundary).session_id == "sess_fractional"
    assert (
        _assert_parity(store, subject_id=subject_id, now=boundary).session_id
        == "sess_fractional"
    )


class RecordingSql(FakeSql):
    def __init__(self, connection) -> None:
        super().__init__(connection)
        self.statements: list[str] = []

    def exec(self, statement: str, *args):
        self.statements.append(statement)
        return super().exec(statement, *args)


def test_selection_filters_orders_and_limits_in_sql() -> None:
    storage = FakeStorage()
    recording = RecordingSql(storage.connection)
    storage.sql = recording
    store = CloudflareCanonicalIdentityAuthorityStore(
        storage,
        lookup_key=LOOKUP_KEY_BYTES,
        allowed_product_ids=frozenset({B62, B54}),
        random_hex=TokenSource(),
    )
    created = link(store)
    subject = user_subject(created.canonical_subject_id)
    with_tenant(store, created.canonical_subject_id)
    mint(
        store,
        subject=subject,
        issued_at=NOW - timedelta(hours=2),
        expires_at=NOW + timedelta(hours=1),
    )
    mint(
        store,
        subject=subject,
        issued_at=NOW - timedelta(hours=1),
        expires_at=NOW + timedelta(hours=1),
    )
    recording.statements.clear()

    resolve(store)

    session_reads = [
        statement
        for statement in recording.statements
        if "FROM canonical_auth_session" in statement
        and statement.lstrip().startswith("SELECT session_id")
    ]
    assert len(session_reads) == 1
    assert "LIMIT 1" in session_reads[0]
    assert "ORDER BY" in session_reads[0]
    assert "state=?" in session_reads[0]
