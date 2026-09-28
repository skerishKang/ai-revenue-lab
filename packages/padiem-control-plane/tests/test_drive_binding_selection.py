"""Control Plane workspace-scoped Drive binding selection tests (#3193).

Network-free. Proves exact workspace+connector selection, usable-only selection,
ambiguity fail-closed, and that the callsite never accepts a caller workspace.
"""

from __future__ import annotations

import inspect
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from drive_binding_selection import TrustedDriveBindingSelectionCallsite
from google_oauth_durable_store import (
    GOOGLE_CALENDAR_READONLY_SCOPE,
    GOOGLE_DRIVE_READONLY_SCOPE,
    CloudflareDurableGoogleOAuthStore,
    DurableGoogleOAuthCredential,
    GoogleOAuthBindingSelection,
    GoogleOAuthBindingSelectionStatus,
)
from identity_connector_ticket import CanonicalConnectorContext
from padiem_control_plane.auth_sessions import AuthSessionSnapshot, AuthSessionState
from padiem_control_plane.contracts import (
    CanonicalSubjectRef,
    ControlPlaneContractError,
    SubjectType,
)

NOW = datetime(2026, 9, 28, 5, 0, tzinfo=timezone.utc)
SEALED_REFRESH = "sealed:v1:BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"
WORKSPACE_A = "workspace.a.reviewed"
WORKSPACE_B = "workspace.b.reviewed"
BINDING_A = "binding.a.drive"
BINDING_B = "binding.b.drive"


class _Cursor:
    def __init__(self, *, rows: list[dict], rows_written: int) -> None:
        self._rows = rows
        self.rowsWritten = rows_written

    def toArray(self) -> list[dict]:
        return list(self._rows)


class _Sql:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection
        self.statements: list[str] = []

    def exec(self, statement: str, *args):
        self.statements.append(statement)
        cursor = self._connection.execute(statement, args)
        if statement.lstrip().upper().startswith("SELECT"):
            columns = [item[0] for item in cursor.description or ()]
            rows = [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
            return _Cursor(rows=rows, rows_written=0)
        return _Cursor(rows=[], rows_written=cursor.rowcount if cursor.rowcount >= 0 else 0)


class _Storage:
    def __init__(self) -> None:
        self.connection = sqlite3.connect(":memory:", isolation_level=None)
        self.sql = _Sql(self.connection)

    def transactionSync(self, operation):
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            result = operation()
        except Exception:
            self.connection.execute("ROLLBACK")
            raise
        self.connection.execute("COMMIT")
        return result


def _store() -> tuple[CloudflareDurableGoogleOAuthStore, _Storage]:
    storage = _Storage()
    return CloudflareDurableGoogleOAuthStore(storage), storage


def _credential(
    *,
    binding_ref: str,
    connector_id: str = "google-drive",
    workspace_ref: str = WORKSPACE_A,
    issued_at: datetime = NOW - timedelta(hours=1),
    expires_at: datetime | None = None,
) -> DurableGoogleOAuthCredential:
    scope = GOOGLE_DRIVE_READONLY_SCOPE
    if connector_id == "google-calendar":
        scope = GOOGLE_CALENDAR_READONLY_SCOPE
    return DurableGoogleOAuthCredential(
        binding_ref=binding_ref,
        connector_id=connector_id,
        actor_ref=f"actor.{binding_ref}",
        account_ref=f"account.{binding_ref}",
        workspace_ref=workspace_ref,
        scopes=(scope,),
        sealed_refresh_token=SEALED_REFRESH,
        issued_at=issued_at,
        expires_at=expires_at,
    )


def session() -> AuthSessionSnapshot:
    return AuthSessionSnapshot(
        session_id="auth-session-1",
        product_id="b62",
        subject=CanonicalSubjectRef(SubjectType.USER, "user-1"),
        issued_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(hours=1),
        state=AuthSessionState.ACTIVE,
        revision=1,
    )


def context(workspace_ref: str = WORKSPACE_A) -> CanonicalConnectorContext:
    return CanonicalConnectorContext(
        product_id="b62",
        subject_id="user-1",
        actor_ref="actor-1",
        account_ref="account-1",
        workspace_ref=workspace_ref,
        created_at=NOW - timedelta(minutes=1),
    )


class FakeContextStore:
    def __init__(self, result) -> None:
        self.result = result
        self.calls = 0

    def resolve_existing(self, *, auth_session, now):
        self.calls += 1
        return self.result

    def resolve_or_create(self, **kwargs):
        raise AssertionError("drive selection must never create connector context")


# --- 1. exact workspace selection -----------------------------------------


def test_workspace_a_selects_its_own_drive_binding() -> None:
    store, _ = _store()
    store.save_credential(_credential(binding_ref=BINDING_A, workspace_ref=WORKSPACE_A))
    selection = store.select_active_drive_binding(workspace_ref=WORKSPACE_A, now=NOW)
    assert selection.resolved is True
    assert selection.connector_id == "google-drive"
    assert selection.workspace_ref == WORKSPACE_A
    assert selection.binding_ref == BINDING_A
    assert selection.account_ref is None
    assert set(selection.to_private_dict()) == {
        "status",
        "connector_id",
        "workspace_ref",
        "binding_ref",
        "actor_ref",
    }


def test_two_workspaces_select_their_own_binding() -> None:
    store, _ = _store()
    store.save_credential(_credential(binding_ref=BINDING_A, workspace_ref=WORKSPACE_A))
    store.save_credential(_credential(binding_ref=BINDING_B, workspace_ref=WORKSPACE_B))
    assert store.select_active_drive_binding(workspace_ref=WORKSPACE_A, now=NOW).binding_ref == BINDING_A
    assert store.select_active_drive_binding(workspace_ref=WORKSPACE_B, now=NOW).binding_ref == BINDING_B


def test_workspace_b_cannot_receive_workspace_a_binding() -> None:
    store, _ = _store()
    store.save_credential(_credential(binding_ref=BINDING_A, workspace_ref=WORKSPACE_A))
    selection = store.select_active_drive_binding(workspace_ref=WORKSPACE_B, now=NOW)
    assert selection.status is GoogleOAuthBindingSelectionStatus.NOT_CONNECTED
    assert selection.binding_ref is None
    assert selection.actor_ref is None


def test_no_drive_binding_is_not_connected() -> None:
    store, _ = _store()
    selection = store.select_active_drive_binding(workspace_ref=WORKSPACE_A, now=NOW)
    assert selection.status is GoogleOAuthBindingSelectionStatus.NOT_CONNECTED
    assert set(selection.to_private_dict()) == {"status", "connector_id", "workspace_ref"}


# --- 2. usable-only + ambiguity -------------------------------------------


def test_ambiguous_drive_bindings_fail_closed() -> None:
    store, _ = _store()
    store.save_credential(_credential(binding_ref=BINDING_A, workspace_ref=WORKSPACE_A))
    store.save_credential(_credential(binding_ref="binding.a.drive.2", workspace_ref=WORKSPACE_A))
    with pytest.raises(ControlPlaneContractError) as excinfo:
        store.select_active_drive_binding(workspace_ref=WORKSPACE_A, now=NOW)
    assert "ambiguous_google_oauth_binding" in str(getattr(excinfo.value, "code", "")) or "ambiguous" in str(
        excinfo.value
    )


def test_revoked_binding_is_not_selected() -> None:
    store, _ = _store()
    store.save_credential(_credential(binding_ref=BINDING_A, workspace_ref=WORKSPACE_A))
    store.revoke_credential(binding_ref=BINDING_A, revoked_at=NOW)
    selection = store.select_active_drive_binding(workspace_ref=WORKSPACE_A, now=NOW)
    assert selection.status is GoogleOAuthBindingSelectionStatus.NOT_CONNECTED


def test_expired_binding_is_not_selected() -> None:
    store, _ = _store()
    store.save_credential(
        _credential(binding_ref=BINDING_A, workspace_ref=WORKSPACE_A, expires_at=NOW - timedelta(minutes=1))
    )
    selection = store.select_active_drive_binding(workspace_ref=WORKSPACE_A, now=NOW)
    assert selection.status is GoogleOAuthBindingSelectionStatus.NOT_CONNECTED


def test_wrong_drive_scope_is_denied() -> None:
    store, storage = _store()
    store.save_credential(_credential(binding_ref=BINDING_A, workspace_ref=WORKSPACE_A))
    storage.connection.execute(
        "UPDATE google_oauth_refresh_credential SET scopes_json = ? WHERE binding_ref = ?",
        ('["https://www.googleapis.com/auth/drive"]', BINDING_A),
    )
    with pytest.raises(ControlPlaneContractError):
        store.select_active_drive_binding(workspace_ref=WORKSPACE_A, now=NOW)


def test_malformed_scope_row_is_denied() -> None:
    store, storage = _store()
    store.save_credential(_credential(binding_ref=BINDING_A, workspace_ref=WORKSPACE_A))
    storage.connection.execute(
        "UPDATE google_oauth_refresh_credential SET scopes_json = ? WHERE binding_ref = ?",
        ("not-json", BINDING_A),
    )
    with pytest.raises(ControlPlaneContractError):
        store.select_active_drive_binding(workspace_ref=WORKSPACE_A, now=NOW)


def test_wrong_connector_row_is_never_selected() -> None:
    store, _ = _store()
    # a calendar credential in the same workspace must not satisfy a Drive read
    store.save_credential(_credential(binding_ref="binding.a.cal", connector_id="google-calendar"))
    selection = store.select_active_drive_binding(workspace_ref=WORKSPACE_A, now=NOW)
    assert selection.status is GoogleOAuthBindingSelectionStatus.NOT_CONNECTED


# --- 3. callsite: no caller workspace authority ---------------------------


def test_callsite_uses_canonical_context_workspace_only() -> None:
    store, _ = _store()
    store.save_credential(_credential(binding_ref=BINDING_A, workspace_ref=WORKSPACE_A))
    context_store = FakeContextStore(context())
    callsite = TrustedDriveBindingSelectionCallsite(context_store=context_store, oauth_store=store)
    selection = callsite.select_for_auth_session(auth_session=session(), now=NOW)
    assert selection.binding_ref == BINDING_A
    assert context_store.calls == 1


def test_callsite_signature_has_no_caller_workspace() -> None:
    params = set(inspect.signature(TrustedDriveBindingSelectionCallsite.select_for_auth_session).parameters)
    assert "workspace_ref" not in params
    assert "workspace" not in params


def test_callsite_missing_workspace_fails_closed() -> None:
    store, _ = _store()
    callsite = TrustedDriveBindingSelectionCallsite(context_store=FakeContextStore(None), oauth_store=store)
    with pytest.raises(ControlPlaneContractError):
        callsite.select_for_auth_session(auth_session=session(), now=NOW)


def test_selector_and_callsite_are_private_only() -> None:
    from google_oauth_durable_store import CloudflareDurableGoogleOAuthStore as Store

    assert not hasattr(Store, "fetch_public")
    safe = TrustedDriveBindingSelectionCallsite.__new__(TrustedDriveBindingSelectionCallsite).safe_dict()
    assert safe["public_route"] is False
    assert safe["caller_workspace_authority"] is False
    assert safe["creates_connector_context"] is False
    assert safe["raw_refresh_token_output"] is False
    assert safe["access_token_output"] is False
