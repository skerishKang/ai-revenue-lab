"""#3782: Broker-internal atomic browser work material binding (issuer UNWIRED).

This test supplies *synthetic* already-admitted browser commands directly in
canonical test state. It does not manufacture a usable production P01 approval.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import timedelta

import pytest
from padiem_control_plane.contracts import ControlPlaneContractError
from padiem_control_plane.local_agent_broker import (
    BrokerCommandCapability,
    BrokerCommandState,
)
from test_local_agent_broker_browser_authenticated_take_3782 import (
    DEVICE_CREDENTIAL,
    NOW,
    _Env,
    prepared,
    take,
)
from test_local_agent_broker_browser_control_take_3782 import payload, taken_count

EVIDENCE_REF = "p01.evidence.test.3782"


def valid_scope():
    _storage, _broker, original = prepared()
    material = payload(original)
    ctx = material["context"]
    canonical = {
        "capability": "browser.control",
        "browser_session_ref": ctx["browserSessionRef"],
        "run_ref": ctx["runRef"],
        "workspace_ref": ctx["workspaceRef"],
        "owner_ref": ctx["ownerRef"],
        "device_id": ctx["deviceRef"],
        "origin_scope": ctx["originScope"],
        "allowed_action_classes": ctx["allowedActionClasses"],
        "ttl_seconds": ctx["ttlSeconds"],
        "max_actions": ctx["maxActions"],
    }
    fingerprint = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return replace(original, request_fingerprint=fingerprint)


def empty_fixture(*, capability=BrokerCommandCapability.BROWSER_CONTROL, state=BrokerCommandState.ADMITTED):
    storage, broker, original = prepared(capability=capability, state=state)
    scope = valid_scope()
    # Fixture-only canonical command state seeding, not a product admission.
    record = broker.state_port.load(authority_ref=broker.authority_ref())
    modified = replace(
        record.snapshot,
        commands=(replace(record.snapshot.commands[0], request_fingerprint=scope.request_fingerprint),),
    )
    broker.state_port.compare_and_swap(
        authority_ref=broker.authority_ref(),
        expected_version=record.version,
        snapshot=modified,
    )
    storage.sql.exec(
        "DELETE FROM local_agent_browser_control_command_take WHERE command_ref = ?",
        original.command_ref,
    )
    wire = payload(scope)
    return storage, broker, scope, wire


def register(broker, initial_scope, wire, **overrides):
    args = {
        "scope": initial_scope, "credential": DEVICE_CREDENTIAL,
        "material": wire, "p01_evidence_ref": EVIDENCE_REF,
        "p01_expires_at": NOW + timedelta(seconds=45), "now": NOW,
    }
    args.update(overrides)
    return broker._bind_browser_material_to_admitted_command(**args)


def registered_rows(storage):
    return storage.connection.execute(
        "SELECT count(*) FROM local_agent_browser_control_command_take"
    ).fetchone()[0]


def test_internal_registration_then_authenticated_take_across_restart():
    from local_agent_broker_durable_runtime import LocalAgentBrokerDurableRuntime

    storage, broker, scope, wire = empty_fixture()
    assert registered_rows(storage) == 0
    result = register(broker, scope, wire)
    assert result["stored"] is True
    assert result["expires_at"] == (NOW + timedelta(seconds=45)).isoformat().replace("+00:00", "Z")
    assert result["raw_approval_payload"] is False
    assert registered_rows(storage) == 1
    restarted = LocalAgentBrokerDurableRuntime(storage=storage, env=_Env())
    assert take(restarted, scope) == wire
    assert taken_count(storage) == 1
    with pytest.raises(ValueError, match="already taken"):
        take(broker, scope)


def test_exact_duplicate_before_or_after_take_cannot_issue_another_row():
    storage, broker, scope, wire = empty_fixture()
    register(broker, scope, wire)
    with pytest.raises(ValueError, match="already exists"):
        register(broker, scope, wire)
    assert registered_rows(storage) == 1
    take(broker, scope)
    with pytest.raises(ValueError, match="already exists"):
        register(broker, scope, wire)
    assert taken_count(storage) == 1


@pytest.mark.parametrize("mutation", [
    "changed_fingerprint", "changed_origin", "wrong_action_class",
    "widened_budget", "widened_ttl", "changed_owner", "wrong_browser",
])
def test_material_cannot_escape_canonical_session_fingerprint(mutation):
    storage, broker, scope, wire = empty_fixture()
    wire = json.loads(json.dumps(wire))
    ctx = wire["context"]
    if mutation == "changed_fingerprint":
        ctx["requestFingerprint"] = "b" * 64
    elif mutation == "changed_origin":
        ctx["originScope"] = "https://another.example"
        wire["action"]["originRef"] = "https://another.example"
    elif mutation == "wrong_action_class":
        ctx["allowedActionClasses"] = ["click", "focus"]
    elif mutation == "widened_budget":
        ctx["maxActions"] = 2
    elif mutation == "widened_ttl":
        ctx["ttlSeconds"] = 600
    elif mutation == "changed_owner":
        ctx["ownerRef"] = "owner.other"
    elif mutation == "wrong_browser":
        ctx["browserSessionRef"] = "browser.different"
        wire["action"]["browserSessionRef"] = "browser.different"
    with pytest.raises(ValueError):
        register(broker, scope, wire)
    assert registered_rows(storage) == 0


@pytest.mark.parametrize("kind", [
    "wrong_credential", "wrong_evidence", "expired_approval",
    "wrong_binding", "wrong_run", "wrong_revision",
])
def test_registration_requires_live_authenticated_admission_and_p01_copy(kind):
    storage, broker, scope, wire = empty_fixture()
    overrides = {}
    if kind == "wrong_credential":
        overrides["credential"] = b"wrong"
    elif kind == "wrong_evidence":
        overrides["p01_evidence_ref"] = "p01.other"
    elif kind == "expired_approval":
        overrides["p01_expires_at"] = NOW
    elif kind == "wrong_binding":
        overrides["scope"] = replace(scope, binding_ref="binding.wrong")
    elif kind == "wrong_run":
        overrides["scope"] = replace(scope, run_ref="run.wrong")
    else:
        overrides["scope"] = replace(scope, revision_ref="revision.wrong")
    with pytest.raises((ControlPlaneContractError, ValueError)):
        register(broker, scope, wire, **overrides)
    assert registered_rows(storage) == 0


@pytest.mark.parametrize("capability,state", [
    (BrokerCommandCapability.PROCESS_EXECUTE, BrokerCommandState.ADMITTED),
    (BrokerCommandCapability.BROWSER_CONTROL, BrokerCommandState.QUEUED),
])
def test_process_or_queued_command_cannot_register_browser_material(capability, state):
    storage, broker, scope, wire = empty_fixture(capability=capability, state=state)
    with pytest.raises(ValueError, match="live admitted command"):
        register(broker, scope, wire)
    assert registered_rows(storage) == 0


def test_rotation_revocation_purges_registered_material():
    storage, broker, scope, wire = empty_fixture()
    register(broker, scope, wire)
    assert registered_rows(storage) == 1
    result = broker.revoke_binding({
        "binding_ref": scope.binding_ref,
        "now": (NOW + timedelta(seconds=1)).isoformat(),
    })
    assert result["ok"] is True
    assert registered_rows(storage) == 0


def test_no_public_registration_rpc_or_fake_product_issuer():
    storage, broker, _scope, _wire = empty_fixture()
    assert not hasattr(broker, "register_browser_control_command")
    assert not hasattr(broker, "register_browser_control_work_ticket")
    assert not hasattr(broker, "take_browser_control_rpc")
    assert registered_rows(storage) == 0
