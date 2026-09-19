from __future__ import annotations

from datetime import datetime, timedelta, timezone
import sqlite3

import pytest

from google_oauth_durable_store import (
    GOOGLE_DRIVE_READONLY_SCOPE,
    DurableGoogleOAuthAuthorizationState,
    DurableGoogleOAuthCredential,
)
from google_oauth_persisted_store import CloudflareDurableGoogleOAuthStore
from padiem_control_plane.contracts import ControlPlaneContractError


NOW = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)
SEALED_SESSION = "sealed:v1:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
SEALED_REFRESH = "sealed:v1:BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"


class AlwaysZeroRowsWrittenCursor:
    """A write cursor whose billing/progress counter never becomes trustworthy."""

    def __init__(self, *, rows: list[dict]) -> None:
        self._rows = rows
        self.rowsWritten = 0
        self.consumed = False

    def toArray(self) -> list[dict]:
        self.consumed = True
        return list(self._rows)


class AlwaysZeroRowsWrittenSql:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def exec(self, statement: str, *args):
        cursor = self._connection.execute(statement, args)
        rows: list[dict] = []
        if statement.lstrip().upper().startswith("SELECT"):
            columns = [item[0] for item in cursor.description or ()]
            rows = [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
        return AlwaysZeroRowsWrittenCursor(rows=rows)


class AlwaysZeroRowsWrittenStorage:
    def __init__(self) -> None:
        self.connection = sqlite3.connect(":memory:", isolation_level=None)
        self.sql = AlwaysZeroRowsWrittenSql(self.connection)

    def transactionSync(self, operation):
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            result = operation()
        except Exception:
            self.connection.execute("ROLLBACK")
            raise
        self.connection.execute("COMMIT")
        return result

    def scalar(self, statement: str, *args):
        return self.connection.execute(statement, args).fetchone()[0]


def _store() -> tuple[CloudflareDurableGoogleOAuthStore, AlwaysZeroRowsWrittenStorage]:
    storage = AlwaysZeroRowsWrittenStorage()
    return CloudflareDurableGoogleOAuthStore(storage), storage


def _state(*, state_ref: str, ticket_id: str) -> DurableGoogleOAuthAuthorizationState:
    return DurableGoogleOAuthAuthorizationState(
        state_ref=state_ref,
        ticket_id=ticket_id,
        connector_id="google-drive",
        sealed_session=SEALED_SESSION,
        created_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
    )


def _begin(
    store: CloudflareDurableGoogleOAuthStore,
    state: DurableGoogleOAuthAuthorizationState,
) -> DurableGoogleOAuthAuthorizationState:
    return store.begin_authorization(
        ticket_id=state.ticket_id,
        connector_id=state.connector_id,
        ticket_expires_at=NOW + timedelta(minutes=3),
        state=state,
        now=NOW,
    )


def _credential(*, binding_ref: str = "binding.persisted.1") -> DurableGoogleOAuthCredential:
    return DurableGoogleOAuthCredential(
        binding_ref=binding_ref,
        connector_id="google-drive",
        actor_ref="actor.persisted.1",
        account_ref="account.persisted.1",
        workspace_ref="workspace.persisted.1",
        scopes=(GOOGLE_DRIVE_READONLY_SCOPE,),
        sealed_refresh_token=SEALED_REFRESH,
        issued_at=NOW,
    )


def test_fresh_ticket_succeeds_when_every_write_cursor_reports_zero() -> None:
    store, storage = _store()
    first = _state(state_ref="state.persisted.1", ticket_id="ticket.persisted.1")

    assert _begin(store, first) == first
    assert storage.scalar("SELECT count(*) FROM google_oauth_connect_ticket_use") == 1
    assert storage.scalar("SELECT count(*) FROM google_oauth_authorization_state") == 1

    with pytest.raises(ControlPlaneContractError) as replay:
        _begin(
            store,
            _state(state_ref="state.persisted.2", ticket_id=first.ticket_id),
        )
    assert replay.value.code == "replayed_connect_ticket"
    assert storage.scalar("SELECT count(*) FROM google_oauth_connect_ticket_use") == 1
    assert storage.scalar("SELECT count(*) FROM google_oauth_authorization_state") == 1


def test_duplicate_state_rolls_back_ticket_with_zero_rows_written() -> None:
    store, storage = _store()
    _begin(store, _state(state_ref="state.shared", ticket_id="ticket.persisted.a"))

    with pytest.raises(ControlPlaneContractError) as duplicate:
        _begin(store, _state(state_ref="state.shared", ticket_id="ticket.persisted.b"))
    assert duplicate.value.code == "duplicate_google_oauth_state"

    assert storage.scalar(
        "SELECT count(*) FROM google_oauth_connect_ticket_use WHERE ticket_id = ?",
        "ticket.persisted.b",
    ) == 0

    fresh = _state(state_ref="state.fresh", ticket_id="ticket.persisted.b")
    assert _begin(store, fresh) == fresh


def test_state_and_credential_lifecycle_ignore_zero_rows_written() -> None:
    store, storage = _store()
    authorization_state = _state(
        state_ref="state.lifecycle.1",
        ticket_id="ticket.lifecycle.1",
    )
    _begin(store, authorization_state)

    consumed = store.consume_authorization_state(
        state_ref=authorization_state.state_ref,
        now=NOW + timedelta(seconds=10),
    )
    assert consumed == authorization_state
    assert storage.scalar("SELECT count(*) FROM google_oauth_authorization_state") == 0

    record = _credential()
    store.save_credential(record)
    assert store.load_active_credential(binding_ref=record.binding_ref, now=NOW) == record

    with pytest.raises(ControlPlaneContractError) as duplicate:
        store.save_credential(record)
    assert duplicate.value.code == "duplicate_google_oauth_binding"

    revoked_at = NOW + timedelta(seconds=30)
    store.revoke_credential(binding_ref=record.binding_ref, revoked_at=revoked_at)
    with pytest.raises(ControlPlaneContractError) as inactive:
        store.load_active_credential(
            binding_ref=record.binding_ref,
            now=NOW + timedelta(seconds=31),
        )
    assert inactive.value.code == "inactive_google_oauth_binding"


def test_expired_state_is_still_permanently_consumed_with_zero_rows_written() -> None:
    store, storage = _store()
    expiring = DurableGoogleOAuthAuthorizationState(
        state_ref="state.expiring.1",
        ticket_id="ticket.expiring.1",
        connector_id="google-drive",
        sealed_session=SEALED_SESSION,
        created_at=NOW,
        expires_at=NOW + timedelta(seconds=30),
    )
    _begin(store, expiring)

    with pytest.raises(ControlPlaneContractError) as expired:
        store.consume_authorization_state(
            state_ref=expiring.state_ref,
            now=NOW + timedelta(seconds=31),
        )
    assert expired.value.code == "expired_google_oauth_state"
    assert storage.scalar("SELECT count(*) FROM google_oauth_authorization_state") == 0

    with pytest.raises(ControlPlaneContractError) as replay:
        store.consume_authorization_state(
            state_ref=expiring.state_ref,
            now=NOW + timedelta(seconds=32),
        )
    assert replay.value.code == "missing_google_oauth_state"
