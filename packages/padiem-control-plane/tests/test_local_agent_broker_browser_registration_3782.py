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
from local_agent_broker_browser_p01_source import (
    AuthenticatedBrowserControlP01Approval,
    browser_control_tool_invocation_digest,
)
from local_agent_broker_durable_runtime import LocalAgentBrokerDurableRuntime
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


class _VerifiedFixtureP01Source:
    """Test-only synthetic source. Never instantiate from a product transport."""

    def __init__(self, scope, wire):
        self.calls = 0
        self.grant = AuthenticatedBrowserControlP01Approval(
            command_ref=scope.command_ref, binding_ref=scope.binding_ref,
            request_id=scope.request_id, run_ref=scope.run_ref,
            request_fingerprint=scope.request_fingerprint,
            admission_ref=scope.admission_ref, revision_ref=scope.revision_ref,
            evidence_ref=EVIDENCE_REF, pause_ref="pause.fixture.3782",
            decision_ref="decision.fixture.3782", approval_tool_id="browser.control",
            approval_invocation_sha256=browser_control_tool_invocation_digest(wire),
            approval_scope=("browser.control",), decision_outcome="approved",
            local_permission_result="require_p01_approval",
            decided_at=NOW - timedelta(seconds=10),
            expires_at=NOW + timedelta(seconds=45),
        )

    def resolve_approved_command(self, *, scope, now):
        self.calls += 1
        return self.grant



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
    broker = LocalAgentBrokerDurableRuntime(
        storage=storage, env=_Env(),
        p01_approval_source=_VerifiedFixtureP01Source(scope, wire),
    )
    return storage, broker, scope, wire


def register(broker, initial_scope, wire, **overrides):
    args = {
        "scope": initial_scope, "credential": DEVICE_CREDENTIAL,
        "material": wire, "now": NOW,
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
    restarted = LocalAgentBrokerDurableRuntime(
        storage=storage, env=_Env(), p01_approval_source=broker._p01_approval_source
    )
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
        source = broker._p01_approval_source
        source.grant = replace(source.grant, evidence_ref="p01.other")
    elif kind == "expired_approval":
        source = broker._p01_approval_source
        source.grant = replace(source.grant, expires_at=NOW)
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


def test_unwired_product_broker_does_not_accept_any_approval_strings():
    """The actual Worker constructs without a resolver; never default-approve."""
    storage, _fixture_broker, scope, wire = empty_fixture()
    product_broker = LocalAgentBrokerDurableRuntime(storage=storage, env=_Env())
    assert product_broker._p01_approval_source is None
    with pytest.raises(ValueError, match="P01 source not wired"):
        register(product_broker, scope, wire)
    assert registered_rows(storage) == 0


@pytest.mark.parametrize("invalid", [
    "wrong_tool", "denied", "wrong_pause_scope", "wrong_digest",
    "wrong_p01_command", "wrong_p01_run", "wrong_p01_binding",
    "wrong_admission", "wrong_revision", "denied_local_policy",
    "invalid_local_policy", "future_decision", "expired",
    "wrong_evidence", "missing_pause", "missing_decision",
])
def test_injected_p01_source_cannot_widen_authority_or_claim_other_scope(invalid):
    storage, broker, scope, wire = empty_fixture()
    source = broker._p01_approval_source
    grant = source.grant
    drift = {
        "wrong_tool": {"approval_tool_id": "process.execute"},
        "denied": {"decision_outcome": "denied"},
        "wrong_pause_scope": {"approval_scope": ("process.execute",)},
        "wrong_digest": {"approval_invocation_sha256": "0" * 64},
        "wrong_p01_command": {"command_ref": "command.other"},
        "wrong_p01_run": {"run_ref": "run.other"},
        "wrong_p01_binding": {"binding_ref": "binding.other"},
        "wrong_admission": {"admission_ref": "admission.other"},
        "wrong_revision": {"revision_ref": "revision.other"},
        "denied_local_policy": {"local_permission_result": "denied"},
        "invalid_local_policy": {"local_permission_result": "owner_override"},
        "future_decision": {"decided_at": NOW + timedelta(seconds=1)},
        "expired": {"expires_at": NOW},
        "wrong_evidence": {"evidence_ref": "evidence.other"},
        "missing_pause": {"pause_ref": ""},
        "missing_decision": {"decision_ref": ""},
    }
    source.grant = replace(grant, **drift[invalid])
    with pytest.raises(ValueError):
        register(broker, scope, wire)
    assert source.calls == 1
    assert registered_rows(storage) == 0
    assert taken_count(storage) == 0


def test_invalid_material_is_rejected_before_trusted_p01_source_is_queried():
    storage, broker, scope, wire = empty_fixture()
    wire["action"]["action"] = "navigate"  # not lease-eligible
    with pytest.raises(ValueError):
        register(broker, scope, wire)
    assert broker._p01_approval_source.calls == 0
    assert registered_rows(storage) == 0


def test_wrong_device_credential_is_rejected_before_p01_source_is_queried():
    storage, broker, scope, wire = empty_fixture()
    with pytest.raises(ControlPlaneContractError):
        register(broker, scope, wire, credential=b"bogus-credential")
    assert broker._p01_approval_source.calls == 0
    assert registered_rows(storage) == 0


def test_untrusted_mapping_cannot_substitute_for_source_resolved_grant():
    storage, broker, scope, wire = empty_fixture()
    source = broker._p01_approval_source
    source.grant = dict(source.grant.__dict__) if hasattr(source.grant, "__dict__") else {
        "decision_outcome": "approved", "approval_tool_id": "browser.control",
    }
    with pytest.raises(ValueError, match="no verified approval"):
        register(broker, scope, wire)
    assert registered_rows(storage) == 0


def test_injected_approval_source_requires_closed_resolver_method():
    storage, _broker, _scope, _wire = empty_fixture()
    with pytest.raises(ValueError, match="canonical first-party"):
        LocalAgentBrokerDurableRuntime(
            storage=storage, env=_Env(),
            p01_approval_source={"outcome": "approved"},
        )


def test_core_p01_tool_digest_matches_broker_canonical_projection():
    """Uses actual Core/KAgent libraries on Windows; skipped when unavailable in
    standalone Control Plane CI, which must remain independently installable.
    """
    from importlib.util import find_spec

    if find_spec("padiem_ai_core") is None or find_spec("kagent") is None:
        pytest.skip("optional cross-package parity requires KAgent and Core")
    from kagent.browser_control_lease_authority import BrowserControlLeaseRequest

    _storage, _broker, scope, wire = empty_fixture()
    ctx = wire["context"]
    req = BrowserControlLeaseRequest(
        browser_session_ref=ctx["browserSessionRef"],
        run_ref=ctx["runRef"],
        workspace_ref=ctx["workspaceRef"],
        owner_ref=ctx["ownerRef"],
        device_id=ctx["deviceRef"],
        origin_scope=ctx["originScope"],
        allowed_action_classes=tuple(ctx["allowedActionClasses"]),
        ttl_seconds=ctx["ttlSeconds"],
        max_actions=ctx["maxActions"],
    )
    assert req.fingerprint() == scope.request_fingerprint
    assert req.approval_invocation_sha256() == browser_control_tool_invocation_digest(wire)


def test_broker_rechecks_revocation_after_first_party_p01_lookup():
    """The P01 resolver runs OUTSIDE transactionSync, and a concurrent revoke
    before the registration CAS cannot register otherwise-valid material.
    """
    storage, broker, scope, wire = empty_fixture()
    source = broker._p01_approval_source
    original = source.resolve_approved_command

    def revoke_during_p01_lookup(*, scope, now):
        result = broker.revoke_binding({
            "binding_ref": scope.binding_ref,
            "now": (now + timedelta(milliseconds=1)).isoformat(),
        })
        assert result["ok"] is True
        return original(scope=scope, now=now)

    source.resolve_approved_command = revoke_during_p01_lookup
    with pytest.raises(ControlPlaneContractError):
        register(broker, scope, wire)
    assert source.calls == 1
    assert registered_rows(storage) == 0


def test_broker_rechecks_credential_rotation_after_p01_lookup():
    storage, broker, scope, wire = empty_fixture()
    source = broker._p01_approval_source
    original = source.resolve_approved_command
    from test_local_agent_broker_browser_authenticated_take_3782 import _encoded

    def rotate_during_p01_lookup(*, scope, now):
        result = broker.rotate_credential({
            "binding_ref": scope.binding_ref,
            "expected_generation": 1,
            "new_credential_b64": _encoded(b"new-different-credential-3782"),
            "now": (now + timedelta(milliseconds=1)).isoformat(),
        })
        assert result["ok"] is True
        return original(scope=scope, now=now)

    source.resolve_approved_command = rotate_during_p01_lookup
    with pytest.raises(ControlPlaneContractError):
        register(broker, scope, wire)
    assert source.calls == 1
    assert registered_rows(storage) == 0


@pytest.mark.parametrize("invalid", [
    "denied", "revoked_scope", "expired", "evidence_replaced",
    "different_session", "different_invocation", "local_denied",
])
def test_p01_revocation_between_registration_and_take_never_burns_command(invalid):
    """Registration is NOT enough: P01 must still be live at the one-shot take."""
    storage, broker, scope, wire = empty_fixture()
    register(broker, scope, wire)
    source = broker._p01_approval_source
    original = source.grant
    changes = {
        "denied": {"decision_outcome": "denied"},
        "revoked_scope": {"approval_scope": ("process.execute",)},
        "expired": {"expires_at": NOW},
        "evidence_replaced": {"evidence_ref": "evidence.replaced"},
        "different_session": {"request_fingerprint": "f" * 64},
        "different_invocation": {"approval_invocation_sha256": "e" * 64},
        "local_denied": {"local_permission_result": "denied"},
    }
    source.grant = replace(original, **changes[invalid])
    with pytest.raises(ValueError):
        take(broker, scope)
    assert taken_count(storage) == 0
    source.grant = original
    assert take(broker, scope) == wire
    assert taken_count(storage) == 1


def test_no_p01_source_after_restart_fails_closed_at_take():
    storage, broker, scope, wire = empty_fixture()
    register(broker, scope, wire)
    no_source = LocalAgentBrokerDurableRuntime(storage=storage, env=_Env())
    with pytest.raises(ValueError, match="P01 source not wired"):
        take(no_source, scope)
    assert taken_count(storage) == 0
    assert take(broker, scope) == wire


def test_p01_source_unavailable_after_registration_does_not_consume():
    storage, broker, scope, wire = empty_fixture()
    register(broker, scope, wire)
    source = broker._p01_approval_source
    original = source.resolve_approved_command
    def unavailable(*, scope, now):
        raise ValueError("trusted P01 issuer unavailable")
    source.resolve_approved_command = unavailable
    with pytest.raises(ValueError, match="P01 issuer unavailable"):
        take(broker, scope)
    assert taken_count(storage) == 0
    source.resolve_approved_command = original
    assert take(broker, scope) == wire


def test_action_mutation_during_p01_lookup_cannot_escape_exact_material_cas():
    """Stored action cannot be swapped while P01 is being revalidated."""
    storage, broker, scope, wire = empty_fixture()
    register(broker, scope, wire)
    source = broker._p01_approval_source
    original = source.resolve_approved_command

    def tamper_during_lookup(*, scope, now):
        rewritten = json.loads(json.dumps(wire))
        rewritten["action"]["elementRef"] = "el-0099"
        storage.sql.exec(
            "UPDATE local_agent_browser_control_command_take SET material_text = ? "
            "WHERE command_ref = ?",
            json.dumps(rewritten, sort_keys=True, separators=(",", ":")),
            scope.command_ref,
        )
        return original(scope=scope, now=now)

    source.resolve_approved_command = tamper_during_lookup
    with pytest.raises(ValueError, match="material changed"):
        take(broker, scope)
    assert taken_count(storage) == 0


def test_binding_revocation_during_p01_take_lookup_cannot_consume():
    storage, broker, scope, wire = empty_fixture()
    register(broker, scope, wire)
    source = broker._p01_approval_source
    original = source.resolve_approved_command

    def revoke_during_lookup(*, scope, now):
        result = broker.revoke_binding({
            "binding_ref": scope.binding_ref,
            "now": (now + timedelta(milliseconds=1)).isoformat(),
        })
        assert result["ok"] is True
        return original(scope=scope, now=now)

    source.resolve_approved_command = revoke_during_lookup
    with pytest.raises(ControlPlaneContractError):
        take(broker, scope)
    assert registered_rows(storage) == 0
