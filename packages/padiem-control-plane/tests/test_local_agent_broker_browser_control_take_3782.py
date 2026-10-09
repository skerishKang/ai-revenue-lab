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


@pytest.mark.parametrize("operation", ["rotate", "revoke"])
def test_broker_credential_rotation_and_revoke_atomically_purge_control_material(operation):
    import base64

    from local_agent_broker_durable_runtime import LocalAgentBrokerDurableRuntime

    class Env:
        LOCAL_AGENT_BROKER_AUTHORITY_REF = "broker.3782.lifecycle"
        LOCAL_AGENT_BROKER_PEPPER = "broker-browser-control-3782-pepper"

    storage, ledger, scope = fixture()
    runtime = LocalAgentBrokerDurableRuntime(storage=storage, env=Env())
    encoded = base64.b64encode(b"browser-control-test-credential").decode("ascii")
    registered = runtime.register_binding({
        "binding_ref": scope.binding_ref,
        "device_id": scope.device_ref,
        "account_ref": "account.3782.1",
        "workspace_ref": scope.workspace_ref,
        "credential_b64": encoded,
        "now": (NOW - timedelta(seconds=10)).isoformat(),
    })
    assert registered["ok"] is True
    assert storage.connection.execute(
        "SELECT COUNT(*) FROM local_agent_browser_control_command_take"
    ).fetchone()[0] == 1
    if operation == "rotate":
        result = runtime.rotate_credential({
            "binding_ref": scope.binding_ref,
            "expected_generation": 1,
            "new_credential_b64": base64.b64encode(b"new-test-credential-3782").decode("ascii"),
            "now": NOW.isoformat(),
        })
    else:
        result = runtime.revoke_binding({
            "binding_ref": scope.binding_ref,
            "now": NOW.isoformat(),
        })
    assert result["ok"] is True
    assert storage.connection.execute(
        "SELECT COUNT(*) FROM local_agent_browser_control_command_take"
    ).fetchone()[0] == 0
    with pytest.raises(ValueError, match="unavailable"):
        ledger.take(scope, now=NOW)


def test_rejected_rotation_does_not_delete_approved_material():
    import base64

    from local_agent_broker_durable_runtime import LocalAgentBrokerDurableRuntime

    class Env:
        LOCAL_AGENT_BROKER_AUTHORITY_REF = "broker.3782.failed-rotation"
        LOCAL_AGENT_BROKER_PEPPER = "broker-browser-control-failed-rotation"

    storage, ledger, scope = fixture()
    runtime = LocalAgentBrokerDurableRuntime(storage=storage, env=Env())
    result = runtime.register_binding({
        "binding_ref": scope.binding_ref,
        "device_id": scope.device_ref,
        "account_ref": "account.3782.1",
        "workspace_ref": scope.workspace_ref,
        "credential_b64": base64.b64encode(b"browser-control-failed-credential").decode("ascii"),
        "now": (NOW - timedelta(seconds=10)).isoformat(),
    })
    assert result["ok"] is True
    bad = runtime.rotate_credential({
        "binding_ref": scope.binding_ref,
        "expected_generation": 9,
        "new_credential_b64": base64.b64encode(b"new-credential-3782").decode("ascii"),
        "now": NOW.isoformat(),
    })
    assert bad["ok"] is False
    assert storage.connection.execute(
        "SELECT COUNT(*) FROM local_agent_browser_control_command_take"
    ).fetchone()[0] == 1
    # The ledger still enforces one-shot before any product execution.
    assert ledger.take(scope, now=NOW) == payload(scope)


@pytest.mark.parametrize("verb", ["scroll", "focus", "click", "type", "select"])
def test_exact_bounded_browser_action_variants_can_be_taken_once(verb):
    item = payload()
    item["context"]["allowedActionClasses"] = [verb]
    action = {
        "action": verb, "browserSessionRef": "browser.3782.1",
        "originRef": "https://example.com",
    }
    if verb == "scroll":
        action.update(dx=-10_000, dy=10_000)
    else:
        action["elementRef"] = "el-0001"
    if verb == "type":
        action["text"] = "안녕하세요"
    if verb == "select":
        action["optionIndex"] = 1023
    item["action"] = action
    storage, ledger, scope = fixture(action=item)
    assert ledger.take(scope, now=NOW) == item
    assert taken_count(storage) == 1


@pytest.mark.parametrize(("part", "name", "invalid"), [
    ("action", "dx", 10),
    ("action", "elementRef", "el-12345"),
    ("action", "elementRef", "el-ffff"),
    ("action", "extra", "javascript_evaluate"),
    ("context", "originScope", "https://example.com/path"),
    ("context", "originScope", "https://example.com@other.example"),
    ("context", "ttlSeconds", True),
    ("context", "ttlSeconds", 901),
    ("context", "maxActions", 101),
    ("context", "maxActions", 0),
    ("context", "allowedActionClasses", ["click", "click"]),
    ("context", "allowedActionClasses", ["click", "submit"]),
    ("context", "browserSessionRef", "invalid session"),
    ("root", "hostLeaseRef", ""),
    ("root", "hostLeaseRef", "bad ref with spaces"),
])
def test_malformed_action_or_broadened_context_does_not_burn_slot(part, name, invalid):
    item = payload()
    target = item if part == "root" else item[part]
    target[name] = invalid
    storage, ledger, scope = fixture(action=item)
    with pytest.raises(ValueError):
        ledger.take(scope, now=NOW)
    assert taken_count(storage) == 0


@pytest.mark.parametrize(("verb", "changes"), [
    ("type", {"text": ""}),
    ("type", {"text": "x" * 257}),
    ("type", {"text": "press\nenter"}),
    ("select", {"optionIndex": True}),
    ("select", {"optionIndex": -1}),
    ("select", {"optionIndex": 1024}),
    ("scroll", {"dx": True}),
    ("scroll", {"dy": 10_001}),
])
def test_action_parameter_bounds_refuse_before_atomic_take(verb, changes):
    item = payload()
    item["context"]["allowedActionClasses"] = [verb]
    action = {
        "action": verb, "browserSessionRef": "browser.3782.1",
        "originRef": "https://example.com",
    }
    if verb == "type":
        action.update(elementRef="el-0001", text="safe")
    elif verb == "select":
        action.update(elementRef="el-0001", optionIndex=0)
    else:
        action.update(dx=0, dy=0)
    action.update(changes)
    item["action"] = action
    storage, ledger, scope = fixture(action=item)
    with pytest.raises(ValueError):
        ledger.take(scope, now=NOW)
    assert taken_count(storage) == 0

def test_one_shot_type_scrubs_sensitive_text_in_same_cas_and_keeps_tombstone():
    """An approved browser.type action must not retain the input text after take."""
    secret = "private-form-input-3782-should-not-stay-at-rest"
    action = payload()
    action["context"]["allowedActionClasses"] = ["type"]
    action["action"] = {
        "action": "type",
        "browserSessionRef": action["context"]["browserSessionRef"],
        "originRef": action["context"]["originScope"],
        "elementRef": "el-0001",
        "text": secret,
    }
    storage, ledger, scope = fixture(action=action)
    before = storage.connection.execute(
        "SELECT material_text,taken_at FROM local_agent_browser_control_command_take "
        "WHERE command_ref=?", (scope.command_ref,),
    ).fetchone()
    assert secret in before[0] and before[1] is None
    assert ledger.take(scope, now=NOW) == action
    after = storage.connection.execute(
        "SELECT material_text,taken_at FROM local_agent_browser_control_command_take "
        "WHERE command_ref=?", (scope.command_ref,),
    ).fetchone()
    assert after[0] == '{"consumed":true}'
    assert secret not in after[0] and after[1] is not None
    assert taken_count(storage) == 1
    restarted = CloudflareDurableObjectBrowserControlTakeStore(storage)
    with pytest.raises(ValueError, match="already taken"):
        restarted.take(scope, now=NOW + timedelta(seconds=1))
    assert storage.connection.execute(
        "SELECT material_text FROM local_agent_browser_control_command_take"
    ).fetchone()[0] == '{"consumed":true}'


def test_rejected_take_never_scrubs_untaken_command_or_changes_one_shot_state():
    secret = "private-input-denied-3782"
    action = payload()
    action["context"]["allowedActionClasses"] = ["type"]
    action["action"] = {
        "action": "type",
        "browserSessionRef": action["context"]["browserSessionRef"],
        "originRef": action["context"]["originScope"],
        "elementRef": "el-0001",
        "text": secret,
    }
    storage, ledger, scope = fixture(action=action)
    with pytest.raises(ValueError):
        ledger.take(replace(scope, admission_ref="forged.admission"), now=NOW)
    before = storage.connection.execute(
        "SELECT material_text,taken_at FROM local_agent_browser_control_command_take"
    ).fetchone()
    assert secret in before[0] and before[1] is None
    assert ledger.take(scope, now=NOW) == action
    assert secret not in storage.connection.execute(
        "SELECT material_text FROM local_agent_browser_control_command_take"
    ).fetchone()[0]


def test_terminal_purge_removes_browser_take_tombstone_only_for_exact_command():
    storage, ledger, scope = fixture()
    assert ledger.take(scope, now=NOW) == payload(scope)
    assert ledger.purge_command(scope.command_ref) == 1
    assert ledger.purge_command(scope.command_ref) == 0
    assert taken_count(storage) == 0
    for invalid in ("", "../traversal", "x" * 257):
        with pytest.raises(ValueError):
            ledger.purge_command(invalid)
    restarted = CloudflareDurableObjectBrowserControlTakeStore(storage)
    with pytest.raises(ValueError, match="unavailable"):
        restarted.take(scope, now=NOW + timedelta(seconds=1))
