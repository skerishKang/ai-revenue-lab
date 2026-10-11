from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from google_oauth_durable_store import (
    CALENDAR_BINDING_SELECTION_PRIVATE_ONLY,
    CALENDAR_BINDING_SELECTION_PUBLIC_ROUTE,
    GMAIL_READONLY_SCOPE,
    GOOGLE_CALENDAR_READONLY_SCOPE,
    GOOGLE_DRIVE_READONLY_SCOPE,
    PUBLIC_WORKSPACE_STATUS_IDENTITY_WIDENING,
    WORKSPACE_READ_CONNECTOR_SCOPE,
    CloudflareDurableGoogleOAuthStore,
    DurableGoogleOAuthAuthorizationState,
    DurableGoogleOAuthCredential,
    GoogleOAuthBindingSelectionStatus,
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
    expires_at: datetime | None = None,
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
        expires_at=expires_at,
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


def test_calendar_binding_selection_zero_usable_rows_is_not_connected():
    oauth_store, _ = store()

    selection = oauth_store.select_active_calendar_binding(
        workspace_ref="workspace_1",
        now=NOW,
    )

    assert selection.status is GoogleOAuthBindingSelectionStatus.NOT_CONNECTED
    assert selection.resolved is False
    assert selection.to_private_dict() == {
        "status": "not_connected",
        "connector_id": "google-calendar",
        "workspace_ref": "workspace_1",
    }
    assert selection.to_bounded_dict()["identity_projection"] is False


def test_calendar_binding_selection_one_usable_row_resolves_exact_private_identity():
    oauth_store, _ = store()
    oauth_store.save_credential(
        credential(
            binding_ref="calendar-binding-1",
            connector_id="google-calendar",
            scopes=(GOOGLE_CALENDAR_READONLY_SCOPE,),
        )
    )

    selection = oauth_store.select_active_calendar_binding(
        workspace_ref="workspace_1",
        now=NOW,
    )

    assert selection.status is GoogleOAuthBindingSelectionStatus.RESOLVED
    assert selection.resolved is True
    assert selection.binding_ref == "calendar-binding-1"
    assert selection.actor_ref == "actor_1"
    assert selection.account_ref == "account_1"
    assert selection.connector_id == "google-calendar"
    assert selection.workspace_ref == "workspace_1"
    assert selection.to_bounded_dict()["sealed_refresh_token"] is False
    assert selection.to_bounded_dict()["access_token"] is False
    assert selection.to_bounded_dict()["provider_payload"] is False


def test_calendar_binding_selection_two_usable_rows_is_ambiguous_fail_closed():
    oauth_store, _ = store()
    oauth_store.save_credential(
        credential(
            binding_ref="calendar-binding-1",
            connector_id="google-calendar",
            scopes=(GOOGLE_CALENDAR_READONLY_SCOPE,),
        )
    )
    oauth_store.save_credential(
        credential(
            binding_ref="calendar-binding-2",
            connector_id="google-calendar",
            scopes=(GOOGLE_CALENDAR_READONLY_SCOPE,),
        )
    )

    with pytest.raises(ControlPlaneContractError) as caught:
        oauth_store.select_active_calendar_binding(
            workspace_ref="workspace_1",
            now=NOW,
        )

    assert caught.value.code == "ambiguous_google_oauth_binding"


def test_calendar_binding_selection_ignores_revoked_and_expired_rows():
    oauth_store, _ = store()
    revoked = credential(
        binding_ref="calendar-revoked",
        connector_id="google-calendar",
        scopes=(GOOGLE_CALENDAR_READONLY_SCOPE,),
    )
    expired = credential(
        binding_ref="calendar-expired",
        connector_id="google-calendar",
        scopes=(GOOGLE_CALENDAR_READONLY_SCOPE,),
        expires_at=NOW + timedelta(seconds=10),
    )
    oauth_store.save_credential(revoked)
    oauth_store.save_credential(expired)
    oauth_store.revoke_credential(
        binding_ref=revoked.binding_ref,
        revoked_at=NOW + timedelta(seconds=1),
    )

    selection = oauth_store.select_active_calendar_binding(
        workspace_ref="workspace_1",
        now=NOW + timedelta(seconds=20),
    )

    assert selection.status is GoogleOAuthBindingSelectionStatus.NOT_CONNECTED


def test_calendar_binding_selection_is_workspace_scoped():
    oauth_store, _ = store()
    oauth_store.save_credential(
        credential(
            binding_ref="calendar-workspace-1",
            connector_id="google-calendar",
            scopes=(GOOGLE_CALENDAR_READONLY_SCOPE,),
        )
    )

    selection = oauth_store.select_active_calendar_binding(
        workspace_ref="workspace_other",
        now=NOW,
    )

    assert selection.status is GoogleOAuthBindingSelectionStatus.NOT_CONNECTED
    assert selection.binding_ref is None
    assert selection.actor_ref is None


@pytest.mark.parametrize("connector_id", ["gmail", "google-drive"])
def test_calendar_binding_selection_ignores_other_connectors(connector_id):
    oauth_store, _ = store()
    oauth_store.save_credential(
        credential(
            binding_ref=f"other-{connector_id}",
            connector_id=connector_id,
            scopes=(
                GMAIL_READONLY_SCOPE
                if connector_id == "gmail"
                else GOOGLE_DRIVE_READONLY_SCOPE,
            ),
        )
    )

    selection = oauth_store.select_active_calendar_binding(
        workspace_ref="workspace_1",
        now=NOW,
    )

    assert selection.status is GoogleOAuthBindingSelectionStatus.NOT_CONNECTED


def test_calendar_binding_selection_rejects_wrong_scope_without_exposing_payload():
    oauth_store, storage = store()
    storage.connection.execute(
        "INSERT INTO google_oauth_refresh_credential "
        "(binding_ref, connector_id, actor_ref, account_ref, workspace_ref, scopes_json, "
        "sealed_refresh_token, issued_at, expires_at, revoked_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "calendar-wrong-scope",
            "google-calendar",
            "actor_1",
            "account_1",
            "workspace_1",
            json.dumps(["https://www.googleapis.com/auth/calendar"]),
            SEALED_REFRESH,
            NOW.isoformat(),
            None,
            None,
        ),
    )

    with pytest.raises(ControlPlaneContractError) as caught:
        oauth_store.select_active_calendar_binding(
            workspace_ref="workspace_1",
            now=NOW,
        )

    assert caught.value.code == "google_oauth_scope_mismatch"
    assert "sealed_refresh_token" not in caught.value.safe_message


def test_calendar_binding_selection_keeps_public_workspace_status_identity_free():
    oauth_store, _ = store()
    oauth_store.save_credential(
        credential(
            binding_ref="calendar-public-check",
            connector_id="google-calendar",
            scopes=(GOOGLE_CALENDAR_READONLY_SCOPE,),
        )
    )

    selection = oauth_store.select_active_calendar_binding(
        workspace_ref="workspace_1",
        now=NOW,
    )
    states = oauth_store.list_workspace_connector_state(
        workspace_ref="workspace_1",
        now=NOW,
    )

    assert {state.connector_id for state in states} == set(WORKSPACE_READ_CONNECTOR_SCOPE)
    assert "google-calendar" not in {state.connector_id for state in states}
    assert "binding_ref" not in selection.to_bounded_dict()
    assert "actor_ref" not in selection.to_bounded_dict()
    assert "workspace_ref" not in selection.to_bounded_dict()
    assert CALENDAR_BINDING_SELECTION_PRIVATE_ONLY is True
    assert CALENDAR_BINDING_SELECTION_PUBLIC_ROUTE is False
    assert PUBLIC_WORKSPACE_STATUS_IDENTITY_WIDENING is False


def test_calendar_binding_selector_has_no_second_store_or_credential_authority():
    oauth_store, _ = store()
    safe = oauth_store.safe_dict()

    assert safe["cloudflare_durable_object"] is True
    assert safe["sqlite_storage"] is True
    assert safe["raw_refresh_token_persisted"] is False
    assert safe["raw_pkce_verifier_persisted"] is False
    assert safe["production_deployment"] is False
    assert safe["production_ready"] is False
