"""#3782: hermetic SQLite CAS for canonical browser-control one-shot command take."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
from local_agent_broker_browser_control_take import (
    BROKER_BROWSER_CONTROL_TAKE_SOURCE_WIRED,
    BROWSER_CONTROL_APPROVAL_ISSUER_WIRED,
    BrowserControlCommandTakeCorrelation,
    CloudflareDurableObjectBrowserControlTakeStore,
)

NOW = datetime(2026, 10, 8, 10, 0, tzinfo=timezone.utc)
FP = "a" * 64


class _Cursor:
    def __init__(self, cursor):
        self._rows = (
            [dict(zip([d[0] for d in cursor.description], r, strict=True))
             for r in cursor.fetchall()]
            if cursor.description else []
        )
        self.rowsWritten = max(cursor.rowcount, 0)

    def toArray(self):
        return self._rows


class _Sql:
    def __init__(self, connection):
        self.connection = connection

    def exec(self, query, *bindings):
        return _Cursor(self.connection.execute(query, bindings))


class _Storage:
    def __init__(self):
        self.connection = sqlite3.connect(":memory:", isolation_level=None)
        self.sql = _Sql(self.connection)

    def transactionSync(self, operation):
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            outcome = operation()
            self.connection.execute("COMMIT")
            return outcome
        except Exception:
            self.connection.execute("ROLLBACK")
            raise


def correlation():
    return BrowserControlCommandTakeCorrelation(
        command_ref="command.3782.1", session_ref="session.3782.1",
        binding_ref="binding.3782.1", request_id="request.3782.1",
        run_ref="run.3782.1", workspace_ref="workspace.3782.1",
        owner_ref="owner.3782.1", device_ref="device.3782.1",
        request_fingerprint=FP, admission_ref="admission.3782.1",
        revision_ref="revision.3782.1",
    )


def payload(scope=None):
    scope = scope or correlation()
    return {
        "commandRef": scope.command_ref,
        "hostLeaseRef": "hostlease.3782.1",
        "capability": "browser.control",
        "context": {
            "requestFingerprint": scope.request_fingerprint,
            "browserSessionRef": "browser.3782.1",
            "deviceRef": scope.device_ref, "runRef": scope.run_ref,
            "workspaceRef": scope.workspace_ref, "ownerRef": scope.owner_ref,
            "originScope": "https://example.com",
            "allowedActionClasses": ["click"],
            "ttlSeconds": 60, "maxActions": 1,
        },
        "action": {
            "action": "click", "elementRef": "el-0001",
            "browserSessionRef": "browser.3782.1",
            "originRef": "https://example.com",
        },
    }


def fixture(*, action=None, expires_at=None):
    storage = _Storage()
    ledger = CloudflareDurableObjectBrowserControlTakeStore(storage)
    scope = correlation()
    # This *test fixture* seeds canonical pre-approved broker data directly.
    # There is NO product-side registration path in this module.
    wire = action if action is not None else payload(scope)
    wire_text = json.dumps(wire, sort_keys=True, separators=(",", ":"))
    expiry = expires_at or NOW + timedelta(minutes=3)
    storage.sql.exec(
        "INSERT INTO local_agent_browser_control_command_take "
        "(command_ref,session_ref,binding_ref,request_id,run_ref,workspace_ref,"
        "owner_ref,device_ref,request_fingerprint,admission_ref,revision_ref,"
        "expires_at,material_text,taken_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,NULL)",
        scope.command_ref, scope.session_ref, scope.binding_ref, scope.request_id,
        scope.run_ref, scope.workspace_ref, scope.owner_ref, scope.device_ref,
        scope.request_fingerprint, scope.admission_ref, scope.revision_ref,
        expiry.isoformat().replace("+00:00", "Z"), wire_text,
    )
    return storage, ledger, scope


def taken_count(storage):
    return storage.connection.execute(
        "SELECT count(*) FROM local_agent_browser_control_command_take WHERE taken_at IS NOT NULL"
    ).fetchone()[0]


def test_once_only_and_restart_replay_are_durable():
    storage, ledger, scope = fixture()
    original = ledger.take(scope, now=NOW)
    assert original == payload(scope)
    assert taken_count(storage) == 1
    restarted = CloudflareDurableObjectBrowserControlTakeStore(storage)
    with pytest.raises(ValueError, match="already taken"):
        restarted.take(scope, now=NOW + timedelta(seconds=1))
    assert taken_count(storage) == 1


@pytest.mark.parametrize("key", [
    "session_ref", "binding_ref", "request_id", "run_ref",
    "workspace_ref", "owner_ref", "device_ref",
    "request_fingerprint", "admission_ref", "revision_ref", "command_ref",
])
def test_wrong_scope_never_consumes_then_canonical_succeeds(key):
    storage, ledger, scope = fixture()
    other = "b" * 64 if key == "request_fingerprint" else f"other.{key}"
    with pytest.raises(ValueError):
        ledger.take(replace(scope, **{key: other}), now=NOW)
    assert taken_count(storage) == 0
    assert ledger.take(scope, now=NOW) == payload(scope)
    assert taken_count(storage) == 1


@pytest.mark.parametrize("change", [
    {"capability": "browser.open"},
    {"commandRef": "command.other"},
    {"extraGrant": "approved"},
])
def test_invalid_material_denies_without_taking(change):
    action = payload()
    action.update(change)
    storage, ledger, scope = fixture(action=action)
    with pytest.raises(ValueError):
        ledger.take(scope, now=NOW)
    assert taken_count(storage) == 0


@pytest.mark.parametrize("change", [
    {"requestFingerprint": "b" * 64},
    {"workspaceRef": "workspace.other"},
    {"ownerRef": "owner.other"},
    {"deviceRef": "device.other"},
    {"runRef": "run.other"},
    {"originScope": "https://other.example"},
])
def test_scope_drift_in_stored_material_refuses(change):
    action = payload()
    action["context"].update(change)
    storage, ledger, scope = fixture(action=action)
    # Origin drift is a Desktop responsibility, but a different origin MUST
    # never be coupled to an action still targeting the original origin.
    with pytest.raises(ValueError):
        ledger.take(scope, now=NOW)
    assert taken_count(storage) == 0


def test_browser_open_reused_evidence_cannot_be_treated_as_control():
    action = payload()
    action["action"]["action"] = "submit"
    storage, ledger, scope = fixture(action=action)
    with pytest.raises(ValueError):
        ledger.take(scope, now=NOW)
    assert taken_count(storage) == 0


def test_expiry_and_utc_clock_are_closed():
    storage, ledger, scope = fixture(expires_at=NOW)
    with pytest.raises(ValueError, match="expired"):
        ledger.take(scope, now=NOW)
    assert taken_count(storage) == 0
    with pytest.raises(ValueError):
        ledger.take(scope, now=NOW.replace(tzinfo=None))


def test_unknown_or_deleted_command_fails_without_output():
    storage, ledger, scope = fixture()
    storage.sql.exec("DELETE FROM local_agent_browser_control_command_take")
    with pytest.raises(ValueError, match="unavailable"):
        ledger.take(scope, now=NOW)


def test_no_producer_no_public_rpc_no_local_approval_authority():
    storage, ledger, _ = fixture()
    assert not BROWSER_CONTROL_APPROVAL_ISSUER_WIRED
    assert not BROKER_BROWSER_CONTROL_TAKE_SOURCE_WIRED
    assert not hasattr(ledger, "register_approved")
    assert not hasattr(ledger, "mint_approval")
    assert not hasattr(ledger, "issue_browser_control_command")
    assert taken_count(storage) == 0

def test_same_canonical_broker_durable_runtime_owns_ledger_without_an_exposed_gateway():
    from local_agent_broker_durable_runtime import LocalAgentBrokerDurableRuntime

    class Env:
        LOCAL_AGENT_BROKER_AUTHORITY_REF = "broker.3782.ledger"
        LOCAL_AGENT_BROKER_PEPPER = "ledger-test-pepper-0123456789"

    storage = _Storage()
    runtime = LocalAgentBrokerDurableRuntime(storage=storage, env=Env())
    assert isinstance(runtime.browser_control_take_store, CloudflareDurableObjectBrowserControlTakeStore)
    assert runtime.browser_control_take_store._storage is storage
    assert not hasattr(runtime, "register_browser_control_command")
    assert not hasattr(runtime, "take_approved_browser_control_command")
    assert not hasattr(runtime, "issue_p01_browser_control_approval")
    assert runtime.browser_control_take_store.take is not None
    with pytest.raises(ValueError, match="unavailable"):
        runtime.browser_control_take_store.take(correlation(), now=NOW)


def test_datetime_expiry_with_offset_is_still_consumable_before_expiry():
    storage, ledger, scope = fixture()
    # A prior canonical server may persist the same UTC moment with an offset.
    # Compare parsed datetimes, then CAS the exact persisted expiry bytes.
    storage.sql.exec(
        "UPDATE local_agent_browser_control_command_take SET expires_at = ?",
        "2026-10-08T19:03:00+09:00",
    )
    assert ledger.take(scope, now=NOW) == payload(scope)
    assert taken_count(storage) == 1
