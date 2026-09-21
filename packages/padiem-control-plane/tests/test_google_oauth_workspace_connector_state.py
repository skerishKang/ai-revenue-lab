from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import types

import pytest

from google_oauth_durable_store import (
    GMAIL_READONLY_SCOPE,
    GOOGLE_DRIVE_READONLY_SCOPE,
    CloudflareDurableGoogleOAuthStore,
    DurableGoogleOAuthCredential,
    GoogleOAuthWorkspaceConnectorState,
    workspace_connector_state,
)
from padiem_control_plane.contracts import ControlPlaneContractError


NOW = datetime(2026, 9, 20, 5, 0, tzinfo=timezone.utc)
SEALED_REFRESH = "sealed:v1:BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"
WORKSPACE_A = "workspace.a.reviewed"
WORKSPACE_B = "workspace.b.reviewed"


# --------------------------------------------------------------------------
# SQLite-backed Durable Object storage double
# --------------------------------------------------------------------------


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
        rows_written = cursor.rowcount if cursor.rowcount >= 0 else 0
        return _Cursor(rows=[], rows_written=rows_written)


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
    connector_id: str = "gmail",
    workspace_ref: str = WORKSPACE_A,
    issued_at: datetime = NOW,
    expires_at: datetime | None = None,
) -> DurableGoogleOAuthCredential:
    scope = GMAIL_READONLY_SCOPE if connector_id == "gmail" else GOOGLE_DRIVE_READONLY_SCOPE
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


def _read(store, *, workspace_ref: str = WORKSPACE_A, now: datetime = NOW):
    states = store.list_workspace_connector_state(workspace_ref=workspace_ref, now=now)
    return {state.connector_id: state for state in states}


# --------------------------------------------------------------------------
# 1-3. Positive workspace reads
# --------------------------------------------------------------------------


def test_workspace_a_gmail_active_binding_reads_usable() -> None:
    store, _ = _store()
    store.save_credential(_credential(binding_ref="binding.a.gmail", connector_id="gmail"))

    states = _read(store)
    assert set(states) == {"gmail", "google-drive"}
    assert states["gmail"].state == "connected"
    assert states["gmail"].usable is True
    assert states["gmail"].ambiguous is False
    assert states["google-drive"].state == "not_connected"
    assert states["google-drive"].usable is False


def test_workspace_a_google_drive_active_binding_reads_usable() -> None:
    store, _ = _store()
    store.save_credential(
        _credential(binding_ref="binding.a.drive", connector_id="google-drive")
    )

    states = _read(store)
    assert states["google-drive"].state == "connected"
    assert states["google-drive"].usable is True
    assert states["gmail"].state == "not_connected"


def test_workspace_b_cannot_observe_workspace_a_binding() -> None:
    store, _ = _store()
    store.save_credential(_credential(binding_ref="binding.a.gmail", connector_id="gmail"))

    states_a = _read(store, workspace_ref=WORKSPACE_A)
    states_b = _read(store, workspace_ref=WORKSPACE_B)

    assert states_a["gmail"].state == "connected"
    assert states_b["gmail"].state == "not_connected"
    assert states_b["google-drive"].state == "not_connected"


# --------------------------------------------------------------------------
# 4-5. Revoked / expired rows are not usable
# --------------------------------------------------------------------------


def test_revoked_binding_is_not_usable() -> None:
    store, _ = _store()
    record = _credential(binding_ref="binding.a.gmail.revoked")
    store.save_credential(record)
    store.revoke_credential(binding_ref=record.binding_ref, revoked_at=NOW + timedelta(seconds=10))

    states = _read(store, now=NOW + timedelta(seconds=20))
    assert states["gmail"].state == "not_connected"
    assert states["gmail"].usable is False


def test_expired_binding_is_not_usable() -> None:
    store, _ = _store()
    store.save_credential(
        _credential(
            binding_ref="binding.a.gmail.expired",
            expires_at=NOW + timedelta(seconds=30),
        )
    )

    assert _read(store, now=NOW + timedelta(seconds=10))["gmail"].state == "connected"
    assert _read(store, now=NOW + timedelta(seconds=31))["gmail"].state == "not_connected"


def test_missing_binding_reports_not_connected_for_both_connectors() -> None:
    store, _ = _store()
    states = _read(store)
    assert states["gmail"].state == "not_connected"
    assert states["google-drive"].state == "not_connected"


# --------------------------------------------------------------------------
# 6. Duplicate active binding => ambiguous (never latest-wins)
# --------------------------------------------------------------------------


def test_duplicate_usable_rows_for_one_workspace_connector_are_ambiguous() -> None:
    store, _ = _store()
    store.save_credential(_credential(binding_ref="binding.a.gmail.one", connector_id="gmail"))
    store.save_credential(_credential(binding_ref="binding.a.gmail.two", connector_id="gmail"))

    states = _read(store)
    assert states["gmail"].state == "ambiguous"
    assert states["gmail"].ambiguous is True
    assert states["gmail"].usable is False
    # A different connector in the same workspace is unaffected.
    assert states["google-drive"].state == "not_connected"


def test_one_usable_plus_one_revoked_row_is_not_ambiguous() -> None:
    store, _ = _store()
    store.save_credential(_credential(binding_ref="binding.a.gmail.live", connector_id="gmail"))
    dead = _credential(binding_ref="binding.a.gmail.dead", connector_id="gmail")
    store.save_credential(dead)
    store.revoke_credential(binding_ref=dead.binding_ref, revoked_at=NOW + timedelta(seconds=5))

    states = _read(store, now=NOW + timedelta(seconds=10))
    assert states["gmail"].state == "connected"
    assert states["gmail"].ambiguous is False


def test_duplicate_rows_across_workspaces_do_not_cross_contaminate() -> None:
    store, _ = _store()
    store.save_credential(_credential(binding_ref="binding.b.gmail", connector_id="gmail", workspace_ref=WORKSPACE_B))
    store.save_credential(_credential(binding_ref="binding.a.gmail.one", connector_id="gmail"))
    store.save_credential(_credential(binding_ref="binding.a.gmail.two", connector_id="gmail"))

    assert _read(store, workspace_ref=WORKSPACE_A)["gmail"].state == "ambiguous"
    assert _read(store, workspace_ref=WORKSPACE_B)["gmail"].state == "connected"


# --------------------------------------------------------------------------
# 6b. expires_present is derived from the USABLE row set only
#
# Regression for the CENTRAL source review finding on #2849: an expired or
# revoked row is not active truth, so it must never influence the flag.
# --------------------------------------------------------------------------


def test_expires_present_case_a_usable_no_expiry_row_with_inactive_expiring_row() -> None:
    """Case A: the sole usable row has no expiry; the other row is expired."""
    store, _ = _store()
    store.save_credential(_credential(binding_ref="binding.a.gmail.live", connector_id="gmail"))
    store.save_credential(
        _credential(
            binding_ref="binding.a.gmail.stale",
            connector_id="gmail",
            expires_at=NOW + timedelta(seconds=30),
        )
    )

    states = _read(store, now=NOW + timedelta(seconds=40))
    assert states["gmail"].state == "connected"
    assert states["gmail"].usable is True
    # The inactive row's expiry must NOT leak into the bounded truth.
    assert states["gmail"].expires_present is False


def test_expires_present_case_b_usable_expiring_row_with_inactive_expiring_row() -> None:
    """Case B: the sole usable row carries an expiry."""
    store, _ = _store()
    store.save_credential(
        _credential(
            binding_ref="binding.a.gmail.expiring",
            connector_id="gmail",
            expires_at=NOW + timedelta(days=30),
        )
    )
    store.save_credential(
        _credential(
            binding_ref="binding.a.gmail.stale",
            connector_id="gmail",
            expires_at=NOW + timedelta(seconds=30),
        )
    )

    states = _read(store, now=NOW + timedelta(seconds=40))
    assert states["gmail"].state == "connected"
    assert states["gmail"].expires_present is True


def test_expires_present_case_c_ambiguous_uses_usable_rows_only() -> None:
    """Case C: two usable rows, one with an expiry and one without."""
    store, _ = _store()
    store.save_credential(
        _credential(
            binding_ref="binding.a.gmail.with_expiry",
            connector_id="gmail",
            expires_at=NOW + timedelta(days=30),
        )
    )
    store.save_credential(_credential(binding_ref="binding.a.gmail.no_expiry", connector_id="gmail"))

    states = _read(store)
    assert states["gmail"].state == "ambiguous"
    assert states["gmail"].usable is False
    assert states["gmail"].ambiguous is True
    assert states["gmail"].expires_present is True


def test_expires_present_is_false_when_no_usable_row_carries_an_expiry() -> None:
    """Two usable rows, neither with an expiry => ambiguous but no expiry present."""
    store, _ = _store()
    store.save_credential(_credential(binding_ref="binding.a.gmail.one", connector_id="gmail"))
    store.save_credential(_credential(binding_ref="binding.a.gmail.two", connector_id="gmail"))

    states = _read(store)
    assert states["gmail"].state == "ambiguous"
    assert states["gmail"].expires_present is False


def test_expires_present_is_false_when_no_row_is_usable() -> None:
    """Expired and revoked rows alone must not report an expiry."""
    store, _ = _store()
    store.save_credential(
        _credential(
            binding_ref="binding.a.gmail.expired",
            connector_id="gmail",
            expires_at=NOW + timedelta(seconds=30),
        )
    )
    revoked = _credential(
        binding_ref="binding.a.gmail.revoked",
        connector_id="gmail",
        expires_at=NOW + timedelta(days=30),
    )
    store.save_credential(revoked)
    store.revoke_credential(binding_ref=revoked.binding_ref, revoked_at=NOW + timedelta(seconds=5))

    states = _read(store, now=NOW + timedelta(seconds=40))
    assert states["gmail"].state == "not_connected"
    assert states["gmail"].usable is False
    assert states["gmail"].expires_present is False


def test_expires_present_ignores_inactive_rows_for_the_other_connector_only() -> None:
    """The flag is computed per connector from that connector's usable rows."""
    store, _ = _store()
    # gmail: usable row without expiry + inactive row with expiry.
    store.save_credential(_credential(binding_ref="binding.a.gmail.live", connector_id="gmail"))
    store.save_credential(
        _credential(
            binding_ref="binding.a.gmail.stale",
            connector_id="gmail",
            expires_at=NOW + timedelta(seconds=30),
        )
    )
    # google-drive: usable row with expiry.
    store.save_credential(
        _credential(
            binding_ref="binding.a.drive.live",
            connector_id="google-drive",
            expires_at=NOW + timedelta(days=30),
        )
    )

    states = _read(store, now=NOW + timedelta(seconds=40))
    assert states["gmail"].expires_present is False
    assert states["google-drive"].expires_present is True


def test_expires_present_flag_never_leaks_the_inactive_row_timestamp() -> None:
    store, _ = _store()
    store.save_credential(_credential(binding_ref="binding.a.gmail.live", connector_id="gmail"))
    stale_expiry = NOW + timedelta(seconds=30)
    store.save_credential(
        _credential(
            binding_ref="binding.a.gmail.stale",
            connector_id="gmail",
            expires_at=stale_expiry,
        )
    )

    states = _read(store, now=NOW + timedelta(seconds=40))
    rendered = json.dumps(
        [state.to_bounded_dict() for state in states.values()],
        sort_keys=True,
    )
    assert states["gmail"].expires_present is False
    assert stale_expiry.isoformat() not in rendered
    assert "2026-09-20T05:00:30" not in rendered


# --------------------------------------------------------------------------
# 6c. connector_ids narrowing filter is bounded (no duplicate output)
# --------------------------------------------------------------------------


def test_duplicate_connector_ids_filter_is_rejected() -> None:
    store, _ = _store()
    with pytest.raises(ControlPlaneContractError) as exc:
        store.list_workspace_connector_state(
            workspace_ref=WORKSPACE_A,
            now=NOW,
            connector_ids=("gmail", "gmail"),
        )
    assert exc.value.code == "invalid_google_oauth_durable_record"


def test_duplicate_connector_filter_cannot_produce_duplicate_state_rows() -> None:
    store, _ = _store()
    store.save_credential(_credential(binding_ref="binding.a.gmail", connector_id="gmail"))

    # A duplicate filter must fail closed rather than emit the connector twice.
    with pytest.raises(ControlPlaneContractError):
        store.list_workspace_connector_state(
            workspace_ref=WORKSPACE_A,
            now=NOW,
            connector_ids=("gmail", "gmail", "google-drive"),
        )

    # The canonical path still returns each connector exactly once.
    states = store.list_workspace_connector_state(workspace_ref=WORKSPACE_A, now=NOW)
    ids = [state.connector_id for state in states]
    assert ids == sorted(set(ids))
    assert len(ids) == len(set(ids))

    narrowed = store.list_workspace_connector_state(
        workspace_ref=WORKSPACE_A,
        now=NOW,
        connector_ids=("gmail",),
    )
    assert [state.connector_id for state in narrowed] == ["gmail"]


def test_non_tuple_connector_filter_is_rejected() -> None:
    store, _ = _store()
    for bad in (["gmail"], "gmail", {"gmail"}):
        with pytest.raises(ControlPlaneContractError):
            store.list_workspace_connector_state(
                workspace_ref=WORKSPACE_A,
                now=NOW,
                connector_ids=bad,  # type: ignore[arg-type]
            )


# --------------------------------------------------------------------------
# 6d. The read SELECT stays aligned with what the docstring claims
# --------------------------------------------------------------------------


def test_read_select_reads_only_the_fields_the_docstring_declares() -> None:
    store, storage = _store()
    storage.sql.statements.clear()

    store.list_workspace_connector_state(workspace_ref=WORKSPACE_A, now=NOW)

    selects = [text for text in storage.sql.statements if text.lstrip().upper().startswith("SELECT")]
    assert len(selects) == 1
    projection = selects[0].split("FROM")[0]
    assert "connector_id" in projection
    assert "expires_at" in projection
    assert "revoked_at" in projection
    # No secret or identity field may ever join the projection.
    for forbidden in (
        "sealed_refresh_token",
        "actor_ref",
        "account_ref",
        "scopes_json",
        "issued_at",
        "binding_ref",
    ):
        assert forbidden not in projection


def test_verdict_helper_maps_usable_row_counts_exactly() -> None:
    assert workspace_connector_state(connector_id="gmail", usable_rows=0, expires_present=False).state == "not_connected"
    assert workspace_connector_state(connector_id="gmail", usable_rows=1, expires_present=False).state == "connected"
    ambiguous = workspace_connector_state(connector_id="gmail", usable_rows=2, expires_present=False)
    assert ambiguous.state == "ambiguous" and ambiguous.ambiguous is True and ambiguous.usable is False


# --------------------------------------------------------------------------
# 7. Bounded output: no identity, no scopes, no sealed material
# --------------------------------------------------------------------------


def _all_read_output(store) -> str:
    states = store.list_workspace_connector_state(workspace_ref=WORKSPACE_A, now=NOW)
    return json.dumps([state.to_bounded_dict() for state in states], sort_keys=True)


def test_projection_contains_no_binding_ref() -> None:
    store, _ = _store()
    store.save_credential(_credential(binding_ref="binding.a.gmail.secret", connector_id="gmail"))
    rendered = _all_read_output(store)
    assert "binding.a.gmail.secret" not in rendered
    assert "binding_ref" not in rendered


def test_projection_contains_no_actor_account_or_workspace_ref() -> None:
    store, _ = _store()
    store.save_credential(_credential(binding_ref="binding.a.gmail", connector_id="gmail"))
    rendered = _all_read_output(store)
    assert "actor.binding.a.gmail" not in rendered
    assert "account.binding.a.gmail" not in rendered
    assert "actor_ref" not in rendered
    assert "account_ref" not in rendered
    assert "workspace_ref" not in rendered
    assert WORKSPACE_A not in rendered


def test_projection_contains_no_scopes_and_no_sealed_credential() -> None:
    store, _ = _store()
    store.save_credential(_credential(binding_ref="binding.a.gmail", connector_id="gmail"))
    rendered = _all_read_output(store)
    assert "googleapis.com" not in rendered
    assert "scopes" not in rendered
    assert SEALED_REFRESH not in rendered
    assert "sealed" not in rendered
    assert "refresh_token" not in rendered


def test_projection_keys_are_exactly_the_reviewed_bounded_set() -> None:
    state = GoogleOAuthWorkspaceConnectorState(
        connector_id="gmail",
        state="connected",
        expires_present=False,
    )
    assert set(state.to_bounded_dict()) == {
        "connector_id",
        "state",
        "usable",
        "expires_present",
        "ambiguous",
    }


def test_expires_present_flag_reports_presence_without_leaking_the_timestamp() -> None:
    store, _ = _store()
    expiry = NOW + timedelta(days=30)
    store.save_credential(
        _credential(binding_ref="binding.a.gmail", connector_id="gmail", expires_at=expiry)
    )
    states = _read(store)
    assert states["gmail"].expires_present is True
    rendered = _all_read_output(store)
    # Presence is reported; the raw timestamp text is not.
    assert "2026-10-20" not in rendered and expiry.isoformat() not in rendered


def test_raw_credential_safe_dict_is_not_reachable_from_the_bounded_projection() -> None:
    store, _ = _store()
    store.save_credential(_credential(binding_ref="binding.a.gmail", connector_id="gmail"))
    states = store.list_workspace_connector_state(workspace_ref=WORKSPACE_A, now=NOW)
    for state in states:
        assert not hasattr(state, "binding_ref")
        assert not hasattr(state, "actor_ref")
        assert not hasattr(state, "account_ref")
        assert not hasattr(state, "workspace_ref")
        assert not hasattr(state, "scopes")
        assert not hasattr(state, "sealed_refresh_token")


# --------------------------------------------------------------------------
# 8. Store query discipline
# --------------------------------------------------------------------------


def test_every_read_statement_is_anchored_to_the_exact_workspace_ref() -> None:
    store, storage = _store()
    store.save_credential(_credential(binding_ref="binding.a.gmail", connector_id="gmail"))
    storage.sql.statements.clear()

    store.list_workspace_connector_state(workspace_ref=WORKSPACE_A, now=NOW)

    selects = [text for text in storage.sql.statements if text.lstrip().upper().startswith("SELECT")]
    assert selects, "the workspace read must issue exactly one bounded SELECT"
    for statement in selects:
        normalized = " ".join(statement.split())
        assert "FROM google_oauth_refresh_credential" in normalized
        assert "WHERE workspace_ref = ?" in normalized
        # The read must never select raw identity or sealed material.
        assert "sealed_refresh_token" not in normalized
        assert "actor_ref" not in normalized
        assert "account_ref" not in normalized
        assert "scopes_json" not in normalized


def test_unsafe_workspace_ref_is_rejected_before_any_query() -> None:
    store, storage = _store()
    storage.sql.statements.clear()
    for bad in ("", " workspace", "workspace;drop", "*", "workspace\nb"):
        with pytest.raises(ControlPlaneContractError):
            store.list_workspace_connector_state(workspace_ref=bad, now=NOW)
    assert storage.sql.statements == []


def test_unreviewed_connector_filter_is_rejected() -> None:
    store, _ = _store()
    with pytest.raises(ControlPlaneContractError):
        store.list_workspace_connector_state(
            workspace_ref=WORKSPACE_A,
            now=NOW,
            connector_ids=("gmail", "google-slides"),
        )


def test_reviewed_calendar_connector_does_not_widen_default_workspace_surface() -> None:
    """#2010 / #2830 non-widening rule.

    ``google-calendar`` is a reviewed OAuth authority (the CP access-lease
    layer accepts it), but the public/default workspace-status projection must
    stay exactly the authorized B-0 set: gmail + google-drive.
    """
    store, _ = _store()
    import google_oauth_durable_store as durable

    assert "google-calendar" in durable.OAUTH_REVIEWED_CONNECTORS
    assert "google-calendar" in durable._REVIEWED_SCOPES
    assert durable.WORKSPACE_READ_CONNECTOR_SCOPE == ("gmail", "google-drive")

    # The default projection still emits only the B-0 pair, even though the
    # reviewed OAuth authority set is wider.
    states = store.list_workspace_connector_state(workspace_ref=WORKSPACE_A, now=NOW)
    assert {state.connector_id for state in states} == {"gmail", "google-drive"}

    # The reviewed Calendar connector is explicitly filterable (it is a real
    # reviewed authority) and never duplicates a state row.
    filtered = store.list_workspace_connector_state(
        workspace_ref=WORKSPACE_A,
        now=NOW,
        connector_ids=("google-calendar",),
    )
    assert [state.connector_id for state in filtered] == ["google-calendar"]
    assert filtered[0].state == "not_connected"


def test_workspace_read_performs_no_write() -> None:
    store, storage = _store()
    store.save_credential(_credential(binding_ref="binding.a.gmail", connector_id="gmail"))
    before = storage.connection.execute(
        "SELECT count(*) FROM google_oauth_refresh_credential"
    ).fetchone()[0]
    storage.sql.statements.clear()

    store.list_workspace_connector_state(workspace_ref=WORKSPACE_A, now=NOW)

    writes = [
        text
        for text in storage.sql.statements
        if not text.lstrip().upper().startswith("SELECT")
    ]
    assert writes == []
    after = storage.connection.execute(
        "SELECT count(*) FROM google_oauth_refresh_credential"
    ).fetchone()[0]
    assert before == after == 1


def test_store_declares_workspace_read_truth_flags() -> None:
    import google_oauth_durable_store as durable

    assert durable.WORKSPACE_KEYED_CONNECTOR_READ is True
    assert durable.WORKSPACE_READ_CONNECTOR_SCOPE == ("gmail", "google-drive")
    assert durable.WORKSPACE_READ_TOKEN_UNSEAL is False
    assert durable.WORKSPACE_READ_ACCESS_LEASE_ISSUE is False
    assert durable.WORKSPACE_READ_PUBLIC_ROUTE is False
    assert durable.WORKSPACE_READ_WRITE_SCOPE is False
    assert durable.WORKSPACE_READ_DUPLICATE_ACTIVE_POLICY == "ambiguous_fail_closed"
    assert durable.WORKSPACE_READ_EXPIRES_PRESENT_SCOPE == "usable_rows_only"
    assert durable.WORKSPACE_READ_DUPLICATE_CONNECTOR_FILTER == "rejected"
    assert durable.WORKSPACE_READ_BINDING_REF_OUTPUT is False
    assert durable.WORKSPACE_READ_ACTOR_ACCOUNT_REF_OUTPUT is False
    assert durable.WORKSPACE_READ_WORKSPACE_REF_ECHO is False
    assert durable.WORKSPACE_READ_SCOPES_OUTPUT is False
    assert durable.WORKSPACE_READ_SEALED_CREDENTIAL_OUTPUT is False
    assert durable.WORKSPACE_READ_SCHEMA_UNIQUE_INDEX_ADDED is False
    # This slice must not introduce a production uniqueness migration.
    assert "UNIQUE(workspace_ref, connector_id)" not in durable._CREDENTIAL_SCHEMA
    assert "UNIQUE (workspace_ref, connector_id)" not in durable._CREDENTIAL_SCHEMA


# --------------------------------------------------------------------------
# 9-13. Private worker RPC
# --------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, body="", *, status=200, headers=None):
        self.body = body
        self.status = status
        self.headers = headers or {}


class _FakeWorkerEntrypoint:
    def __init__(self, env=None):
        self.env = env


class _FakeDurableObject:
    def __init__(self, ctx, env):
        self.ctx = ctx
        self.env = env


_workers = types.ModuleType("workers")
_workers.Response = _FakeResponse
_workers.WorkerEntrypoint = _FakeWorkerEntrypoint
_workers.DurableObject = _FakeDurableObject
sys.modules.setdefault("workers", _workers)

_WORKER_PATH = Path(__file__).parents[1] / "google_oauth_worker.py"
_SPEC = importlib.util.spec_from_file_location("padiem_google_oauth_worker_b0_test", _WORKER_PATH)
assert _SPEC is not None and _SPEC.loader is not None
worker = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = worker
_SPEC.loader.exec_module(worker)


import base64  # noqa: E402

SEAL_KEY = base64.urlsafe_b64encode(b"S" * 32).decode("ascii").rstrip("=")
TICKET_KEY = base64.urlsafe_b64encode(b"T" * 32).decode("ascii").rstrip("=")
AUTHORITY_REF = "control-plane.google-oauth.production.v1"


class _Env:
    def __init__(self, *, namespace=None) -> None:
        self.GOOGLE_OAUTH_AUTHORITY_REF = AUTHORITY_REF
        self.GOOGLE_OAUTH_SEAL_KEY = SEAL_KEY
        self.GOOGLE_OAUTH_CLIENT_ID = "client-id.apps.googleusercontent.com"
        self.GOOGLE_OAUTH_CLIENT_SECRET = "client-secret-value"
        self.GOOGLE_OAUTH_REDIRECT_URI = "https://oauth.padiem.net/v1/google/callback"
        self.GOOGLE_CONNECT_TICKET_KEY = TICKET_KEY
        self.GOOGLE_OAUTH_STATE = namespace


class _Context:
    def __init__(self, storage: _Storage) -> None:
        self.storage = storage


class _Stub:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def workspace_connector_state(self, payload):
        self.calls.append(("workspace_connector_state", payload))
        return {"ok": True, "routed": True}


class _Namespace:
    def __init__(self, stub: _Stub) -> None:
        self.stub = stub
        self.names: list[str] = []

    def idFromName(self, name: str) -> str:
        self.names.append(name)
        return f"do::{name}"

    def get(self, object_id: str):
        return self.stub


def _durable_object(storage: _Storage | None = None):
    storage = storage or _Storage()
    return storage, worker.GoogleOAuthDurableObject(_Context(storage), _Env())


def _rpc(durable_object, payload):
    return asyncio.run(durable_object.workspace_connector_state(payload))


def test_rpc_returns_bounded_connector_truth_for_workspace() -> None:
    storage, durable_object = _durable_object()
    store = CloudflareDurableGoogleOAuthStore(storage)
    store.save_credential(_credential(binding_ref="binding.a.gmail", connector_id="gmail"))

    result = _rpc(durable_object, {"workspace_ref": WORKSPACE_A})

    assert result["ok"] is True
    connectors = {item["connector_id"]: item for item in result["connectors"]}
    assert set(connectors) == {"gmail", "google-drive"}
    assert connectors["gmail"]["state"] == "connected"
    assert connectors["gmail"]["usable"] is True
    assert connectors["google-drive"]["state"] == "not_connected"


def test_rpc_response_never_contains_identity_or_sealed_material() -> None:
    storage, durable_object = _durable_object()
    store = CloudflareDurableGoogleOAuthStore(storage)
    store.save_credential(_credential(binding_ref="binding.a.gmail.leak", connector_id="gmail"))

    rendered = json.dumps(_rpc(durable_object, {"workspace_ref": WORKSPACE_A}), sort_keys=True)

    assert "binding.a.gmail.leak" not in rendered
    assert "binding_ref" not in rendered
    assert "actor_ref" not in rendered
    assert "account_ref" not in rendered
    assert "workspace_ref" not in rendered
    assert WORKSPACE_A not in rendered
    assert "googleapis.com" not in rendered
    assert SEALED_REFRESH not in rendered
    assert "refresh_token" not in rendered


def test_rpc_payload_is_closed_and_rejects_extra_keys() -> None:
    _, durable_object = _durable_object()

    denied = _rpc(
        durable_object,
        {"workspace_ref": WORKSPACE_A, "connector_id": "gmail"},
    )
    assert denied["ok"] is False
    assert denied["error"]["code"] == "invalid_google_oauth_ingress"

    assert _rpc(durable_object, {})["ok"] is False
    assert _rpc(durable_object, {"workspace": WORKSPACE_A})["ok"] is False
    assert _rpc(durable_object, "workspace.a")["ok"] is False


def test_rpc_rejects_unsafe_workspace_ref_without_disclosing_state() -> None:
    _, durable_object = _durable_object()
    denied = _rpc(durable_object, {"workspace_ref": "workspace;drop table"})
    assert denied["ok"] is False
    assert denied["error"]["code"] == "invalid_google_oauth_durable_record"


def test_status_rpc_never_unseals_or_issues_an_access_lease(monkeypatch) -> None:
    storage, durable_object = _durable_object()
    store = CloudflareDurableGoogleOAuthStore(storage)
    store.save_credential(_credential(binding_ref="binding.a.gmail", connector_id="gmail"))

    lease_calls: list[tuple[str, str]] = []
    unseal_calls: list[object] = []

    async def _forbidden_issue(self, *, binding_ref, connector_id):
        lease_calls.append((binding_ref, connector_id))
        raise AssertionError("status read must never issue an access lease")

    async def _forbidden_unseal(self, *, envelope, context):
        unseal_calls.append(envelope)
        raise AssertionError("status read must never unseal the refresh credential")

    monkeypatch.setattr(
        worker.GoogleOAuthAccessLeaseRuntime,
        "issue",
        _forbidden_issue,
    )
    monkeypatch.setattr(
        worker.GoogleOAuthWebCryptoSealer,
        "unseal_text",
        _forbidden_unseal,
    )

    result = _rpc(durable_object, {"workspace_ref": WORKSPACE_A})
    assert result["ok"] is True
    assert result["connectors"]
    assert lease_calls == []
    assert unseal_calls == []


def test_public_fetch_remains_404_on_durable_object_and_gateway() -> None:
    _, durable_object = _durable_object()
    response = asyncio.run(durable_object.fetch(object()))
    assert response.status == 404
    assert response.headers["cache-control"] == "no-store"

    stub = _Stub()
    namespace = _Namespace(stub)
    entrypoint = worker.Default(_Env(namespace=namespace))
    gateway_response = asyncio.run(entrypoint.fetch(object()))
    assert gateway_response.status == 404

    result = asyncio.run(entrypoint.workspace_connector_state({"workspace_ref": WORKSPACE_A}))
    assert result == {"ok": True, "routed": True}
    assert namespace.names == [AUTHORITY_REF]
    assert stub.calls == [("workspace_connector_state", {"workspace_ref": WORKSPACE_A})]


def test_gateway_rejects_a_caller_supplied_authority_ref() -> None:
    stub = _Stub()
    env = _Env(namespace=_Namespace(stub))
    env.GOOGLE_OAUTH_AUTHORITY_REF = "caller.supplied.authority"
    entrypoint = worker.Default(env)
    with pytest.raises(RuntimeError):
        asyncio.run(entrypoint.workspace_connector_state({"workspace_ref": WORKSPACE_A}))


def test_worker_declares_b0_read_slice_truth_flags() -> None:
    assert worker.WORKSPACE_CONNECTOR_STATE_RPC is True
    assert worker.WORKSPACE_CONNECTOR_STATE_PUBLIC_ROUTE is False
    assert worker.WORKSPACE_CONNECTOR_STATE_PAYLOAD_CLOSED is True
    assert worker.WORKSPACE_CONNECTOR_STATE_LEAKS_BINDING_REF is False
    assert worker.WORKSPACE_CONNECTOR_STATE_LEAKS_ACTOR_REF is False
    assert worker.WORKSPACE_CONNECTOR_STATE_LEAKS_ACCOUNT_REF is False
    assert worker.WORKSPACE_CONNECTOR_STATE_ECHOES_WORKSPACE_REF is False
    assert worker.WORKSPACE_CONNECTOR_STATE_LEAKS_SCOPES is False
    assert worker.WORKSPACE_CONNECTOR_STATE_LEAKS_SEALED_CREDENTIAL is False
    assert worker.WORKSPACE_CONNECTOR_STATE_UNSEALS_REFRESH_TOKEN is False
    assert worker.WORKSPACE_CONNECTOR_STATE_ISSUES_ACCESS_LEASE is False
    assert worker.WORKSPACE_CONNECTOR_STATE_WRITE_AUTHORITY is False
    assert worker.WORKSPACE_CONNECTOR_STATE_DUPLICATE_POLICY == "ambiguous_fail_closed"
    # Unchanged pre-existing invariants that this slice must not disturb.
    assert worker.PUBLIC_FETCH is False
    assert worker.PRODUCTION_ROUTE_CONFIGURED is False
    assert worker.PRODUCTION_MUTATION is False
    assert worker.ACCESS_TOKEN_RAW_RPC_RESPONSE is False


def test_b0_slice_added_no_public_route_or_authority_constant() -> None:
    source = _WORKER_PATH.read_text(encoding="utf-8")
    # No new public HTTP surface was configured for this read slice.
    assert '"/v1/connectors' not in source
    assert "workspace-status" not in source
    assert "NEW_AUTHORITY" not in source
    # The DO still exposes exactly one fetch, returning 404.
    assert source.count("async def fetch") == 2


def test_worker_config_still_declares_no_public_route() -> None:
    config_path = Path(__file__).parents[1] / ("wrang" + "ler.google-oauth.jsonc")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    assert config["workers_dev"] is False
    assert config["preview_urls"] is False
    assert "routes" not in config and "route" not in config
