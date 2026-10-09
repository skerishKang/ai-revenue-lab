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
        engine_run_id="torun.engine.browser.3782",
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
        run_id=join.engine_run_id,
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
        run_id=join.engine_run_id,
        invocation_sha256=join.browser_invocation_sha256,
        user_approval_evidence_ref=join.user_p01_evidence_ref,
    )


def test_three_authority_join_then_actual_durable_broker_one_shot_take():
    storage, broker, scope, material, join, engine, local = _harness()
    assert ENGINE_SHA != scope.request_fingerprint
    assert join.result.engine_run_id != scope.run_ref
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
    ("engine_run_id", "torun.other.engine"),
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


def test_real_engine_d1_approved_receipt_drives_broker_cas_with_distinct_run_ids():
    """Hermetic cross-package D1 integration; approval owner is TEST-ONLY.

    Skip for minimal control-plane-only distributions without Engine. This
    exercises the REAL Engine D1 query and real Broker transaction/take, not
    an EnginePort stub. NO real human P01 issuer or cross-service auth exists.
    """
    import asyncio

    pytest.importorskip("app.browser_control_p01_receipt")
    pytest.importorskip("test_browser_control_p01_receipt_3782")
    from app.browser_control_p01_receipt import (
        AdmittedBrowserControlP01ReceiptQuery,
        CloudflareD1BrowserControlP01ReceiptStore,
    )
    from app.continuation_d1 import _identity_json
    from app.continuation_identity import ContinuationExecutionIdentity
    from app.execution_admission_resume import OriginalAdmissionBinding
    from padiem_ai_core.agent_approval import (
        ApprovalOutcome,
        VerifiedApprovalDecision,
    )
    from test_browser_control_p01_receipt_3782 import (
        _D1,
        pause,
        seed,
    )

    storage, broker, scope, wire, join_port, _stub_engine, local_port = _harness()
    join = join_port.result
    assert join.engine_run_id != scope.run_ref
    assert join.engine_request_sha256 != scope.request_fingerprint
    db = _D1()
    try:
        stamp = NOW
        p = replace(
            pause(),
            pause_id="pause.cross.stack.3782",
            run_id=join.engine_run_id,
            invocation_sha256=join.browser_invocation_sha256,
            created_at=stamp - timedelta(seconds=30),
            expires_at=stamp + timedelta(seconds=100),
        )
        seed(
            db, p, state="claimed", app_id=join.engine_app_id,
            continuation_ref=join.engine_continuation_ref,
        )
        # Original execution identity is server-derived and separate
        # from the Broker session fingerprint.
        identity = ContinuationExecutionIdentity(
            request_fingerprint=join.engine_request_sha256,
            plan_fingerprint=None,
            subject_id=scope.owner_ref,
            recovery_policy_fingerprint=None,
            max_retries=0,
            require_evidence=True,
            require_verification=True,
        )
        original = OriginalAdmissionBinding(
            decision_id=join.engine_original_admission_decision_id,
            app_id=join.engine_app_id,
            subject_id=scope.owner_ref,
            authority_ref="authority.engine.original.test",
            policy_revision="rev.engine.original.test",
            request_fingerprint=join.engine_request_sha256,
        )
        db.db.execute(
            "UPDATE padiem_engine_continuations "
            "SET claim_token=?, execution_identity_json=? "
            "WHERE app_id=? AND continuation_ref=?",
            ("claim_cross.stack.3782", _identity_json(identity, original),
             join.engine_app_id, join.engine_continuation_ref),
        )
        db.db.commit()
        approved = VerifiedApprovalDecision(
            decision_id="decision.cross.stack.3782",
            pause_id=p.pause_id,
            outcome=ApprovalOutcome.APPROVED,
            authority_ref="p01.test.human.authority",
            evidence_ref=join.user_p01_evidence_ref,
            decided_at=stamp - timedelta(seconds=4),
        )
        receipts = CloudflareD1BrowserControlP01ReceiptStore(db)
        asyncio.run(receipts.commit_claimed_browser_approval(
            app_id=join.engine_app_id,
            continuation_ref=join.engine_continuation_ref,
            claim_token="claim_cross.stack.3782",
            pause=p, decision=approved, now=stamp,
        ))

        class _ActualD1EnginePort:
            def __init__(self):
                self.reads = 0

            def resolve_admitted(self, *, query, now):
                self.reads += 1
                read = AdmittedBrowserControlP01ReceiptQuery(
                    app_id=query.app_id,
                    continuation_ref=query.continuation_ref,
                    user_subject_id=query.user_subject_id,
                    original_request_fingerprint=query.original_request_fingerprint,
                    original_admission_decision_id=query.original_admission_decision_id,
                    run_id=query.run_id,
                    invocation_sha256=query.invocation_sha256,
                    user_approval_evidence_ref=query.user_approval_evidence_ref,
                )
                r = asyncio.run(receipts.resolve_admitted(query=read, now=now))
                return (
                    AuthenticatedEngineP01ReceiptProjection(
                        app_id=r.app_id, continuation_ref=r.continuation_ref,
                        pause_id=r.pause_id, decision_id=r.decision_id,
                        evidence_ref=r.evidence_ref, authority_ref=r.authority_ref,
                        run_id=r.run_id, invocation_sha256=r.invocation_sha256,
                        approved_at=r.approved_at, expires_at=r.expires_at,
                    ) if r is not None else None
                )

        real_port = _ActualD1EnginePort()
        bridge = SourceOnlyBrokerEngineBrowserP01Bridge(
            join_port=join_port, engine_port=real_port,
            local_port=local_port,
        )
        broker = LocalAgentBrokerDurableRuntime(
            storage=storage, env=_Env(), p01_approval_source=bridge,
        )
        registered = broker._bind_browser_material_to_admitted_command(
            scope=scope, credential=DEVICE_CREDENTIAL, material=wire, now=NOW,
        )
        assert registered["stored"] is True
        assert take(broker, scope) == wire
        assert real_port.reads == 2
        assert taken_count(storage) == 1

        # A revoked receipt cannot be re-read for a different future
        # authenticated Broker command.
        assert asyncio.run(receipts.revoke(
            app_id=join.engine_app_id,
            continuation_ref=join.engine_continuation_ref,
            now=NOW,
        ))
        assert asyncio.run(receipts.resolve_admitted(
            query=AdmittedBrowserControlP01ReceiptQuery(
                app_id=join.engine_app_id,
                continuation_ref=join.engine_continuation_ref,
                user_subject_id=scope.owner_ref,
                original_request_fingerprint=join.engine_request_sha256,
                original_admission_decision_id=join.engine_original_admission_decision_id,
                run_id=join.engine_run_id,
                invocation_sha256=join.browser_invocation_sha256,
                user_approval_evidence_ref=join.user_p01_evidence_ref,
            ),
            now=NOW,
        )) is None
    finally:
        db.db.close()
