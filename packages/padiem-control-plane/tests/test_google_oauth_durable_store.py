from __future__ import annotations

from datetime import datetime, timedelta, timezone
import sqlite3

import pytest

from google_oauth_durable_store import (
    GMAIL_READONLY_SCOPE,
    GOOGLE_DRIVE_READONLY_SCOPE,
    CloudflareDurableGoogleOAuthStore,
    DurableGoogleOAuthAuthorizationState,
    DurableGoogleOAuthCredential,
)
from padiem_control_plane.contracts import ControlPlaneContractError


NOW = datetime(2026, 9, 4, 10, 30, tzinfo=timezone.utc)
SEALED_SESSION = "sealed:v1:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
SEALED_REFRESH = "sealed:v1:BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"


class FakeCursor:
    def __init__(self, *, rows: list[dict], rows_written: int) -> None:
        self._rows = rows
        self.rowsWritten = rows_written

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
            return FakeCursor(rows=rows, rows_written=0)
        rows_written = cursor.rowcount if cursor.rowcount >= 0 else 0
        return FakeCursor(rows=[], rows_written=rows_written)


class FakeDurableStorage:
    """SQLite-backed transactionSync test double with real rollback semantics."""

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

    def scalar(self, statement: str, *args):
        return self.connection.execute(statement, args).fetchone()[0]


def store() -> tuple[CloudflareDurableGoogleOAuthStore, FakeDurableStorage]:
    storage = FakeDurableStorage()
    return CloudflareDurableGoogleOAuthStore(storage), storage


def state(
    *,
    state_ref: str = "state_1",
    ticket_id: str = "ticket_1",
    connector_id: str = "gmail",
    created_at: datetime = NOW,
    expires_at: datetime | None = None,
    sealed_session: str = SEALED_SESSION,
) -> DurableGoogleOAuthAuthorizationState:
    return DurableGoogleOAuthAuthorizationState(
        state_ref=state_ref,
        ticket_id=ticket_id,
        connector_id=connector_id,
        sealed_session=sealed_session,
        created_at=created_at,
        expires_at=expires_at or created_at + timedelta(minutes=5),
    )


def credential(
    *,
    binding_ref: str = "binding_1",
    connector_id: str = "gmail",
    scopes: tuple[str, ...] = (GMAIL_READONLY_SCOPE,),
    sealed_refresh_token: str = SEALED_REFRESH,
    issued_at: datetime = NOW,
) -> DurableGoogleOAuthCredential:
    return DurableGoogleOAuthCredential(
        binding_ref=binding_ref,
        connector_id=connector_id,
        actor_ref="actor_1",
        account_ref="account_1",
        workspace_ref="workspace_1",
        scopes=scopes,
        sealed_refresh_token=sealed_refresh_token,
        issued_at=issued_at,
    )


def begin(
    oauth_store: CloudflareDurableGoogleOAuthStore,
    authorization_state: DurableGoogleOAuthAuthorizationState,
    *,
    now: datetime = NOW,
) -> DurableGoogleOAuthAuthorizationState:
    return oauth_store.begin_authorization(
        ticket_id=authorization_state.ticket_id,
        connector_id=authorization_state.connector_id,
        ticket_expires_at=now + timedelta(minutes=3),
        state=authorization_state,
        now=now,
    )


def test_begin_authorization_consumes_ticket_once_and_persists_only_state_envelope():
    oauth_store, storage = store()
    authorization_state = state()

    assert begin(oauth_store, authorization_state) == authorization_state
    assert storage.scalar("SELECT count(*) FROM google_oauth_connect_ticket_use") == 1
    assert storage.scalar("SELECT count(*) FROM google_oauth_authorization_state") == 1
    stored = storage.connection.execute(
        "SELECT sealed_session FROM google_oauth_authorization_state WHERE state_ref = ?",
        (authorization_state.state_ref,),
    ).fetchone()[0]
    assert stored == SEALED_SESSION
    assert "pkce" not in stored.lower()

    with pytest.raises(ControlPlaneContractError) as exc:
        begin(
            oauth_store,
            state(state_ref="state_2", ticket_id=authorization_state.ticket_id),
        )
    assert exc.value.code == "replayed_connect_ticket"
    assert storage.scalar("SELECT count(*) FROM google_oauth_authorization_state") == 1


def test_duplicate_state_rolls_back_ticket_consumption_when_begin_did_not_succeed():
    oauth_store, storage = store()
    begin(oauth_store, state(state_ref="shared_state", ticket_id="ticket_a"))

    with pytest.raises(ControlPlaneContractError) as exc:
        begin(oauth_store, state(state_ref="shared_state", ticket_id="ticket_b"))
    assert exc.value.code == "duplicate_google_oauth_state"

    # ticket_b was in the same failed transaction, so it must remain usable.
    begin(oauth_store, state(state_ref="fresh_state", ticket_id="ticket_b"))
    assert storage.scalar("SELECT count(*) FROM google_oauth_connect_ticket_use") == 2


def test_authorization_state_is_single_use():
    oauth_store, storage = store()
    authorization_state = state()
    begin(oauth_store, authorization_state)

    consumed = oauth_store.consume_authorization_state(state_ref="state_1", now=NOW + timedelta(seconds=10))
    assert consumed.state_ref == "state_1"
    assert storage.scalar("SELECT count(*) FROM google_oauth_authorization_state") == 0

    with pytest.raises(ControlPlaneContractError) as exc:
        oauth_store.consume_authorization_state(state_ref="state_1", now=NOW + timedelta(seconds=11))
    assert exc.value.code == "missing_google_oauth_state"


def test_expired_authorization_state_is_consumed_permanently_not_rolled_back():
    oauth_store, storage = store()
    authorization_state = state(expires_at=NOW + timedelta(seconds=30))
    begin(oauth_store, authorization_state)

    with pytest.raises(ControlPlaneContractError) as exc:
        oauth_store.consume_authorization_state(
            state_ref="state_1",
            now=NOW + timedelta(seconds=31),
        )
    assert exc.value.code == "expired_google_oauth_state"
    assert storage.scalar("SELECT count(*) FROM google_oauth_authorization_state") == 0

    # Regression: raising expiry inside transactionSync would roll DELETE back.
    with pytest.raises(ControlPlaneContractError) as replay_exc:
        oauth_store.consume_authorization_state(
            state_ref="state_1",
            now=NOW + timedelta(seconds=32),
        )
    assert replay_exc.value.code == "missing_google_oauth_state"


def test_plaintext_or_unversioned_sensitive_values_are_rejected_before_persistence():
    oauth_store, storage = store()

    with pytest.raises(ControlPlaneContractError):
        state(sealed_session="plain-pkce-verifier")
    with pytest.raises(ControlPlaneContractError):
        credential(sealed_refresh_token="plain-refresh-token")

    assert storage.scalar("SELECT count(*) FROM google_oauth_authorization_state") == 0
    assert storage.scalar("SELECT count(*) FROM google_oauth_refresh_credential") == 0
    assert oauth_store.safe_dict()["sealed_envelope_required"] is True
    assert oauth_store.safe_dict()["cryptography_implemented_here"] is False
    assert oauth_store.safe_dict()["webcrypto_sealer_required"] is True


def test_only_reviewed_gmail_and_drive_readonly_scopes_can_be_persisted():
    oauth_store, _ = store()

    gmail = credential()
    oauth_store.save_credential(gmail)
    assert oauth_store.load_active_credential(binding_ref="binding_1", now=NOW) == gmail

    drive = credential(
        binding_ref="binding_2",
        connector_id="google-drive",
        scopes=(GOOGLE_DRIVE_READONLY_SCOPE,),
        sealed_refresh_token="sealed:v1:CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC",
    )
    oauth_store.save_credential(drive)
    assert oauth_store.load_active_credential(binding_ref="binding_2", now=NOW) == drive

    with pytest.raises(ControlPlaneContractError) as exc:
        credential(
            binding_ref="binding_write",
            connector_id="google-drive",
            scopes=("https://www.googleapis.com/auth/drive",),
        )
    assert exc.value.code == "unreviewed_google_oauth_scope"


def test_credential_revocation_is_durable_and_predate_attempt_rolls_back():
    oauth_store, _ = store()
    oauth_store.save_credential(credential())
    oauth_store.revoke_credential(binding_ref="binding_1", revoked_at=NOW + timedelta(seconds=5))

    with pytest.raises(ControlPlaneContractError) as exc:
        oauth_store.load_active_credential(binding_ref="binding_1", now=NOW + timedelta(seconds=6))
    assert exc.value.code == "inactive_google_oauth_binding"

    second = credential(binding_ref="binding_2", issued_at=NOW + timedelta(minutes=1))
    oauth_store.save_credential(second)
    with pytest.raises(ControlPlaneContractError) as invalid:
        oauth_store.revoke_credential(binding_ref="binding_2", revoked_at=NOW)
    assert invalid.value.code == "invalid_google_oauth_durable_record"
    assert oauth_store.load_active_credential(
        binding_ref="binding_2",
        now=NOW + timedelta(minutes=2),
    ) == second


def test_connect_ticket_and_authorization_time_bounds_fail_closed():
    oauth_store, storage = store()
    authorization_state = state()

    with pytest.raises(ControlPlaneContractError) as expired:
        oauth_store.begin_authorization(
            ticket_id="ticket_expired",
            connector_id="gmail",
            ticket_expires_at=NOW,
            state=state(ticket_id="ticket_expired"),
            now=NOW,
        )
    assert expired.value.code == "expired_connect_ticket"

    with pytest.raises(ControlPlaneContractError) as unbounded:
        oauth_store.begin_authorization(
            ticket_id="ticket_long",
            connector_id="gmail",
            ticket_expires_at=NOW + timedelta(minutes=10),
            state=state(ticket_id="ticket_long"),
            now=NOW,
        )
    assert unbounded.value.code == "invalid_connect_ticket"
    assert storage.scalar("SELECT count(*) FROM google_oauth_connect_ticket_use") == 0


def test_public_projections_never_expose_sealed_payloads_or_raw_credentials():
    authorization_public = state().safe_dict()
    credential_public = credential().safe_dict()

    assert SEALED_SESSION not in str(authorization_public)
    assert SEALED_REFRESH not in str(credential_public)
    assert authorization_public["raw_pkce_verifier"] is False
    assert authorization_public["raw_connect_ticket"] is False
    assert credential_public["raw_refresh_token"] is False
    assert credential_public["raw_access_token"] is False
    assert credential_public["raw_client_secret"] is False
