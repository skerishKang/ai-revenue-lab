from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3

import pytest

from identity_connector_ticket import (
    CONNECT_TICKET_TTL_SECONDS,
    CanonicalConnectorContextStore,
    GoogleConnectTicketIssuer,
    decode_connect_ticket_key,
)
from padiem_control_plane.auth_sessions import AuthSessionSnapshot, AuthSessionState
from padiem_control_plane.connector_connect_ticket import (
    GMAIL_READONLY_SCOPE,
    GOOGLE_DRIVE_READONLY_SCOPE,
    ConnectorConnectTicketAuthority,
)
from padiem_control_plane.contracts import (
    CanonicalSubjectRef,
    ControlPlaneContractError,
    SubjectType,
)


NOW = datetime(2026, 9, 4, 13, 30, tzinfo=timezone.utc)
KEY_BYTES = b"T" * 32
KEY_TEXT = base64.urlsafe_b64encode(KEY_BYTES).decode("ascii").rstrip("=")


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
        if statement.lstrip().upper().startswith("SELECT"):
            columns = [item[0] for item in cursor.description or ()]
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

    def rows(self) -> list[tuple]:
        return self.connection.execute(
            "SELECT product_id, subject_id, actor_ref, account_ref, workspace_ref, created_at "
            "FROM canonical_connector_context ORDER BY subject_id"
        ).fetchall()


class TokenSource:
    def __init__(self) -> None:
        self.count = 0

    def __call__(self, bytes_count: int) -> str:
        self.count += 1
        return f"{self.count:0{bytes_count * 2}x}"[-bytes_count * 2 :]


def session(subject_id: str = "sub_1", **overrides) -> AuthSessionSnapshot:
    values = dict(
        session_id="sess_1",
        product_id="b62",
        subject=CanonicalSubjectRef(SubjectType.USER, subject_id),
        issued_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(hours=1),
        state=AuthSessionState.ACTIVE,
        revision=1,
    )
    values.update(overrides)
    return AuthSessionSnapshot(**values)


def fixture():
    storage = FakeStorage()
    source = TokenSource()
    context_store = CanonicalConnectorContextStore(storage, random_hex=source)
    issuer = GoogleConnectTicketIssuer(
        context_store=context_store,
        signing_key=KEY_BYTES,
        clock=lambda: NOW,
        random_hex=source,
    )
    return storage, context_store, issuer


def test_connect_ticket_key_requires_exact_256_bit_base64url_secret():
    assert decode_connect_ticket_key(KEY_TEXT) == KEY_BYTES
    with pytest.raises(ControlPlaneContractError) as exc:
        decode_connect_ticket_key("short")
    assert exc.value.code == "invalid_connect_ticket_authority"


def test_context_is_server_owned_stable_and_distinct_per_canonical_subject():
    storage, context_store, _ = fixture()
    first = context_store.resolve_or_create(auth_session=session("sub_1"), now=NOW)
    repeated = context_store.resolve_or_create(auth_session=session("sub_1"), now=NOW + timedelta(seconds=1))
    second = context_store.resolve_or_create(
        auth_session=session("sub_2", session_id="sess_2"),
        now=NOW,
    )

    assert repeated == first
    assert first.actor_ref.startswith("actor_")
    assert first.account_ref.startswith("account_")
    assert first.workspace_ref.startswith("workspace_")
    assert first.actor_ref != second.actor_ref
    assert first.account_ref != second.account_ref
    assert first.workspace_ref != second.workspace_ref
    assert len(storage.rows()) == 2
    assert first.safe_dict()["server_owned"] is True
    assert first.safe_dict()["client_asserted"] is False
    assert context_store.safe_dict()["client_supplied_actor_account_workspace"] is False


def test_context_rejects_revoked_expired_foreign_and_non_user_sessions():
    _, context_store, _ = fixture()

    with pytest.raises(ControlPlaneContractError) as revoked:
        context_store.resolve_or_create(
            auth_session=session(state=AuthSessionState.REVOKED),
            now=NOW,
        )
    assert revoked.value.code == "inactive_auth_session"

    with pytest.raises(ControlPlaneContractError) as expired:
        context_store.resolve_or_create(
            auth_session=session(expires_at=NOW),
            now=NOW,
        )
    assert expired.value.code == "inactive_auth_session"

    with pytest.raises(ControlPlaneContractError) as foreign:
        context_store.resolve_or_create(
            auth_session=session(product_id="b54"),
            now=NOW,
        )
    assert foreign.value.code == "connector_context_session_mismatch"

    with pytest.raises(ControlPlaneContractError) as anonymous:
        context_store.resolve_or_create(
            auth_session=session(subject=CanonicalSubjectRef(SubjectType.ANONYMOUS, "anon_1")),
            now=NOW,
        )
    assert anonymous.value.code == "connector_context_session_mismatch"


def test_gmail_ticket_binds_authoritative_server_context_and_exact_readonly_scope():
    _, context_store, issuer = fixture()
    auth = session()
    receipt = issuer.issue(auth_session=auth, connector_id="gmail")
    context = context_store.resolve_or_create(auth_session=auth, now=NOW)

    claims = ConnectorConnectTicketAuthority(signing_key=KEY_BYTES).verify(
        token=receipt.connect_ticket,
        now=NOW + timedelta(seconds=1),
        expected_connector_id="gmail",
        auth_session=auth,
    )

    assert claims.session_id == auth.session_id
    assert claims.product_id == "b62"
    assert claims.subject_id == auth.subject.subject_id
    assert claims.actor_ref == context.actor_ref
    assert claims.account_ref == context.account_ref
    assert claims.workspace_ref == context.workspace_ref
    assert claims.scopes == (GMAIL_READONLY_SCOPE,)
    assert claims.expires_at == NOW + timedelta(seconds=CONNECT_TICKET_TTL_SECONDS)
    assert receipt.expires_at == claims.expires_at
    assert KEY_TEXT not in receipt.connect_ticket
    assert receipt.connect_ticket not in repr(receipt)
    assert receipt.safe_dict()["raw_connect_ticket"] is False
    assert receipt.safe_dict()["raw_signing_key"] is False


def test_drive_ticket_is_readonly_and_unreviewed_connector_fails_closed_without_context_row():
    storage, _, issuer = fixture()
    auth = session()
    receipt = issuer.issue(auth_session=auth, connector_id="google-drive")
    claims = ConnectorConnectTicketAuthority(signing_key=KEY_BYTES).verify(
        token=receipt.connect_ticket,
        now=NOW,
        expected_connector_id="google-drive",
        auth_session=auth,
    )
    assert claims.scopes == (GOOGLE_DRIVE_READONLY_SCOPE,)
    assert len(storage.rows()) == 1

    other_storage, _, other_issuer = fixture()
    with pytest.raises(ControlPlaneContractError) as exc:
        other_issuer.issue(auth_session=auth, connector_id="calendar")
    assert exc.value.code == "unreviewed_connect_scope"
    assert other_storage.rows() == []


def test_revoked_session_cannot_mint_ticket_or_create_connector_context():
    storage, _, issuer = fixture()
    with pytest.raises(ControlPlaneContractError) as exc:
        issuer.issue(
            auth_session=session(state=AuthSessionState.REVOKED),
            connector_id="gmail",
        )
    assert exc.value.code == "inactive_auth_session"
    assert storage.rows() == []


def test_private_worker_rpc_accepts_no_client_actor_account_or_workspace_fields():
    source = Path("identity_authority_worker.py").read_text(encoding="utf-8")
    assert '_CONNECT_KEYS = frozenset({"session_id", "connector_id"})' in source
    assert 'wire = _closed(payload, _CONNECT_KEYS, "Google connect-ticket RPC")' in source
    assert 'actor_ref=wire[' not in source
    assert 'account_ref=wire[' not in source
    assert 'workspace_ref=wire[' not in source
    assert "CLIENT_ACTOR_ACCOUNT_WORKSPACE_AUTHORITY = False" in source
    assert "RAW_CONNECT_TICKET_PUBLIC = False" in source
