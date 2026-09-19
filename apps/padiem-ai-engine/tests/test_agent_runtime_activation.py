"""Network-free contract tests for the #2754 A5-Agent readiness gate."""

from __future__ import annotations

import asyncio
import json

import pytest

from app.agent_runtime_activation import (
    AGENT_REFERENCE_CONSUMERS,
    CONFIRMATION_TOKEN,
    DEPLOYMENT_TARGET,
    RollbackReadinessMetadata,
    ActivationError,
    evaluate_activation,
    run_reference_parity_probe,
    run_synthetic_probes,
    verify_confirmation_token,
    verify_exact_main,
)

MAIN = "5d152fdc6fd008eed44a8e7b638e4c165917340b"
SOURCE = "f7c52ce1245f16db7a9961a203915b0fd11fab34"


def run(coro):
    return asyncio.run(coro)


def metadata() -> RollbackReadinessMetadata:
    return RollbackReadinessMetadata()


def test_exact_confirmation_token_is_required() -> None:
    verify_confirmation_token(CONFIRMATION_TOKEN)
    with pytest.raises(ActivationError) as caught:
        verify_confirmation_token("ACTIVATE_ENGINE_A5_SKILL")
    assert caught.value.code == "activation_not_authorized"


@pytest.mark.parametrize("value", ["main", "", "A" * 40])
def test_exact_main_rejects_non_sha(value: str) -> None:
    with pytest.raises(ActivationError) as caught:
        verify_exact_main(value)
    assert caught.value.code == "invalid_sha"


def test_synthetic_agent_only_probes_are_network_free() -> None:
    results = run(run_synthetic_probes())
    assert results
    assert all(result.ok for result in results)
    assert {result.case for result in results} >= {
        "agent_only_run",
        "unknown_agent",
        "plan_agent_mismatch",
        "plan_tool_outside_profile",
        "caller_subject_id",
        "caller_authority_fields",
        "unsafe_subject",
        "skill_runtime_deferred",
    }


def test_reference_parity_is_opaque_and_agent_only() -> None:
    results = run_reference_parity_probe()
    assert tuple(item.case for item in results) == AGENT_REFERENCE_CONSUMERS
    serialized = json.dumps([item.to_public_dict() for item in results], sort_keys=True)
    assert "padiem-chat" in serialized
    assert "padiem-claw" in serialized
    assert "route" not in serialized
    assert "provider" not in serialized


def test_evaluate_activation_records_pending_secret_free_evidence() -> None:
    evidence = run(
        evaluate_activation(
            confirmation_token=CONFIRMATION_TOKEN,
            current_main=MAIN,
            accepted_source_head=SOURCE,
            readiness_metadata=metadata(),
        )
    )
    public = evidence.to_public_dict()
    assert evidence.deployment_target == DEPLOYMENT_TARGET
    assert evidence.final_disposition == "PENDING_PRODUCTION_AUTHORIZATION"
    assert evidence.skill_activation == "DEFERRED"
    assert evidence.real_provider_call_count == 0
    assert evidence.real_user_data == 0
    assert public["current_deployed_version"] == "UNRESOLVED_FOR_LIVE_AUTHORITY"
    serialized = json.dumps(public, sort_keys=True).lower()
    assert "secret-value" not in serialized
    assert "private" not in serialized


def test_manifest_and_skill_are_not_activated_by_gate_source() -> None:
    from app.capability_manifest import CapabilityState, current_capability_manifest
    from app.contract_manifest import EngineFeatureState, current_engine_contract_manifest

    assert current_capability_manifest().capability_state("agent_skill_runtime") is CapabilityState.DEFERRED
    manifest = current_engine_contract_manifest()
    assert manifest.feature_state("agent_runtime_projection") is EngineFeatureState.DEFERRED
    assert manifest.feature_state("skill_runtime_projection") is EngineFeatureState.DEFERRED
