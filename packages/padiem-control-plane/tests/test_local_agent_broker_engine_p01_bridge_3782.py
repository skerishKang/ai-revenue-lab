"""#3782: closed Broker <- authenticated Engine P01 mapping (test ports ONLY).

Test ports do NOT authenticate human identity and cannot serve production;
these tests prove exact triple-correlation, expiry, local policy, and real
Broker one-shot CAS. Nothing activates P01 in a deployed Broker or Engine.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest
from local_agent_broker_browser_p01_source import (
    browser_control_tool_invocation_digest,
)
from local_agent_broker_durable_runtime import LocalAgentBrokerDurableRuntime
from local_agent_broker_engine_p01_bridge import (
    BROKER_ENGINE_BROWSER_P01_BRIDGE_WIRED,
    AuthenticatedEngineP01ReceiptProjection,
    BrokerEngineP01Join,
    CurrentLocalBrowserPermission,
    SourceOnlyBrokerEngineBrowserP01Bridge,
)
from test_local_agent_broker_browser_authenticated_take_3782 import (
    DEVICE_CREDENTIAL,
    NOW,
    _Env,
    take,
)
from test_local_agent_broker_browser_control_take_3782 import taken_count
from test_local_agent_broker_browser_registration_3782 import (
    EVIDENCE_REF,
    empty_fixture,
    register,
)

ENGINE_SHA = "d" * 64


class _JoinPort:
    def __init__(self, result):
        self.result = result
        self.calls = 0

    def resolve_for_admitted_command(self, *, scope, now):
        self.calls += 1
        return self.result


class _EnginePort:
    def __init__(self, projection, expected):
        self.projection = projection
        self.expected = expected
        self.calls = 0

    def resolve_admitted(self, *, query, now):
        self.calls += 1
        if query != self.expected:
            return None
        return self.projection


class _LocalPort:
    def __init__(self, result):
        self.result = result
        self.calls = 0

    def resolve_current(self, *, scope, now):
        self.calls += 1
        return self.result


def _harness():
    storage, _prior, scope, material = empty_fixture()
    digest = browser_control_tool_invocation_digest(material)
    join = BrokerEngineP01Join(
        command_ref=scope.command_ref,
        binding_ref=scope.binding_ref,
        request_id=scope.request_id,
        run_ref=scope.run_ref,
        broker_request_fingerprint=scope.request_fingerprint,
        admission_ref=scope.admission_ref,
        revision_ref=scope.revision_ref,
        engine_app_id="app.engine.browser.3782",
        engine_continuation_ref="cont_engine_browser.3782",
        engine_user_subject_id=scope.owner_ref,
        engine_request_sha256=ENGINE_SHA,
        engine_original_admission_decision_id="decision.original.engine.3782",
        browser_invocation_sha256=digest,
        user_p01_evidence_ref=EVIDENCE_REF,
    )
    projection = AuthenticatedEngineP01ReceiptProjection(
        app_id=join.engine_app_id,
        continuation_ref=join.engine_continuation_ref,
        pause_id="pause.engine.3782",
        decision_id="decision.engine.3782",
        evidence_ref=EVIDENCE_REF,
        authority_ref="authority.human.3782",
        run_id=scope.run_ref,
        invocation_sha256=digest,
        approved_at=NOW - timedelta(seconds=12),
        expires_at=NOW + timedelta(seconds=44),
    )
    permission = CurrentLocalBrowserPermission(
        binding_ref=scope.binding_ref,
        device_ref=scope.device_ref,
        owner_ref=scope.owner_ref,
        workspace_ref=scope.workspace_ref,
        result="require_p01_approval",
        verified_at=NOW - timedelta(seconds=5),
        expires_at=NOW + timedelta(seconds=35),
    )
    join_port = _JoinPort(join)
    engine_port = _EnginePort(projection, expected_query(join))
    local_port = _LocalPort(permission)
    bridge = SourceOnlyBrokerEngineBrowserP01Bridge(
        join_port=join_port, engine_port=engine_port, local_port=local_port,
    )
    broker = LocalAgentBrokerDurableRuntime(
        storage=storage, env=_Env(), p01_approval_source=bridge,
    )
    return storage, broker, scope, material, join_port, engine_port, local_port


def expected_query(join):
    from local_agent_broker_engine_p01_bridge import EngineP01ReadQuery

    return EngineP01ReadQuery(
        app_id=join.engine_app_id,
        continuation_ref=join.engine_continuation_ref,
        user_subject_id=join.engine_user_subject_id,
        original_request_fingerprint=join.engine_request_sha256,
        original_admission_decision_id=join.engine_original_admission_decision_id,
        run_id=join.run_ref,
        invocation_sha256=join.browser_invocation_sha256,
        user_approval_evidence_ref=join.user_p01_evidence_ref,
    )


def test_three_authority_join_then_actual_durable_broker_one_shot_take():
    storage, broker, scope, material, join, engine, local = _harness()
    assert ENGINE_SHA != scope.request_fingerprint
    result = register(broker, scope, material)
    assert result["stored"] is True
    assert result["action_executed"] is False
    assert result["raw_approval_payload"] is False
    assert join.calls == engine.calls == local.calls == 1
    # Broker's existing one-shot CAS still re-resolves user P01 and local
    # permission before consuming, even across a Broker restart.
    reopened = LocalAgentBrokerDurableRuntime(
        storage=storage, env=_Env(), p01_approval_source=broker._p01_approval_source,
    )
    assert take(reopened, scope) == material
    assert taken_count(storage) == 1
    assert join.calls == engine.calls == local.calls == 2
    with pytest.raises(ValueError, match="already taken"):
        take(broker, scope)


def test_injection_requires_all_three_live_owner_ports():
    with pytest.raises(TypeError, match="all authenticated"):
        SourceOnlyBrokerEngineBrowserP01Bridge(
            join_port=object(), engine_port=object(), local_port=object(),
        )
    assert BROKER_ENGINE_BROWSER_P01_BRIDGE_WIRED is False
    assert DEVICE_CREDENTIAL


@pytest.mark.parametrize("wrong_field,replacement", [
    ("command_ref", "command.other.3782"),
    ("binding_ref", "bind.other.3782"),
    ("request_id", "request.other.3782"),
    ("run_ref", "run.other.3782"),
    ("broker_request_fingerprint", "e" * 64),
    ("admission_ref", "admission.other.3782"),
    ("revision_ref", "revision.other.3782"),
    ("engine_user_subject_id", "other.user"),
])
def test_other_command_or_user_mapping_never_reads_engine_or_registers(
    wrong_field, replacement,
):
    storage, broker, scope, wire, join, engine, local = _harness()
    join.result = replace(join.result, **{wrong_field: replacement})
    with pytest.raises(ValueError, match="does not match"):
        register(broker, scope, wire)
    assert join.calls == 1 and engine.calls == 0 and local.calls == 0
    assert taken_count(storage) == 0


@pytest.mark.parametrize("wrong_field,replacement", [
    ("engine_app_id", "another.engine.app"),
    ("engine_continuation_ref", "cont_other.engine"),
    ("engine_request_sha256", "e" * 64),
    ("engine_original_admission_decision_id", "decision.other.engine"),
    ("browser_invocation_sha256", "e" * 64),
    ("user_p01_evidence_ref", "evidence.other"),
])
def test_engine_owner_read_refuses_different_original_admission_or_invocation(
    wrong_field, replacement,
):
    storage, broker, scope, wire, join, engine, local = _harness()
    join.result = replace(join.result, **{wrong_field: replacement})
    with pytest.raises(ValueError, match="Engine P01"):
        register(broker, scope, wire)
    assert join.calls == 1 and engine.calls == 1 and local.calls == 0
    assert taken_count(storage) == 0


@pytest.mark.parametrize("wrong_field,replacement", [
    ("app_id", "another.engine.app"),
    ("continuation_ref", "cont_other.engine"),
    ("run_id", "run.other"),
    ("invocation_sha256", "e" * 64),
    ("evidence_ref", "evidence.other"),
    ("expires_at", NOW - timedelta(seconds=1)),
    ("approved_at", NOW + timedelta(seconds=1)),
])
def test_wrong_stale_or_mismatched_engine_receipt_never_trusts_local_permission(
    wrong_field, replacement,
):
    storage, broker, scope, wire, _join, engine, local = _harness()
    engine.projection = replace(engine.projection, **{wrong_field: replacement})
    with pytest.raises(ValueError, match="Engine P01"):
        register(broker, scope, wire)
    assert engine.calls == 1 and local.calls == 0
    assert taken_count(storage) == 0


@pytest.mark.parametrize("wrong_field,replacement", [
    ("binding_ref", "bind.other"),
    ("device_ref", "device.other"),
    ("owner_ref", "owner.other"),
    ("workspace_ref", "workspace.other"),
    ("result", "denied"),
    ("verified_at", NOW + timedelta(seconds=1)),
    ("expires_at", NOW - timedelta(seconds=1)),
])
def test_changed_local_device_permission_refuses_approved_engine_receipt(
    wrong_field, replacement,
):
    storage, broker, scope, wire, join, engine, local = _harness()
    local.result = replace(local.result, **{wrong_field: replacement})
    with pytest.raises(ValueError, match="local browser permission"):
        register(broker, scope, wire)
    assert join.calls == engine.calls == local.calls == 1
    assert taken_count(storage) == 0


def test_revoked_local_permission_between_registration_and_take_blocks_cas():
    storage, broker, scope, material, _join, _engine, local = _harness()
    register(broker, scope, material)
    local.result = replace(local.result, result="denied")
    with pytest.raises(ValueError, match="local browser permission"):
        take(broker, scope)
    assert taken_count(storage) == 0


def test_expired_engine_approval_between_registration_and_take_blocks_cas():
    storage, broker, scope, material, _join, engine, _local = _harness()
    register(broker, scope, material)
    engine.projection = replace(engine.projection, expires_at=NOW - timedelta(seconds=1))
    with pytest.raises(ValueError, match="Engine P01"):
        take(broker, scope)
    assert taken_count(storage) == 0


def test_hard_missing_engine_authority_fails_closed_without_registration():
    storage, broker, scope, wire, join, engine, local = _harness()
    engine.projection = None
    with pytest.raises(ValueError, match="current independently approved"):
        register(broker, scope, wire)
    assert join.calls == engine.calls == 1
    assert local.calls == 0
    assert taken_count(storage) == 0
