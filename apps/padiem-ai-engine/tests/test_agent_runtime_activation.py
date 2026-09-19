"""Network-free contract tests for the #2754 A5-Agent readiness gate."""

from __future__ import annotations

import asyncio
import json

import pytest

from app.agent_runtime_activation import (
    AGENT_REFERENCE_CONSUMERS,
    CONFIRMATION_TOKEN,
    DEPLOYMENT_TARGET,
    EvidenceState,
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


@pytest.mark.parametrize(
    "field,value",
    [
        ("current_deployed_version", "secret=value"),
        ("rollback_version", "Bearer token"),
        ("current_deployed_version", "sk-live-value"),
        ("rollback_version", "provider://route/private"),
        ("current_deployed_version", "line1\nline2"),
        ("rollback_version", '{"secret":"value"}'),
        ("current_deployed_version", "bad\x00control"),
        ("rollback_version", "x" * 1000),
    ],
)
def test_hostile_readiness_versions_are_rejected(field: str, value: str) -> None:
    with pytest.raises(ActivationError) as caught:
        RollbackReadinessMetadata(**{field: value})
    assert caught.value.code == "invalid_readiness_metadata"


@pytest.mark.parametrize("field", ["rollback_config", "config_binding_diff", "secret_name_diff"])
def test_free_text_readiness_states_are_rejected(field: str) -> None:
    with pytest.raises(ActivationError) as caught:
        RollbackReadinessMetadata(**{field: "secret=value"})
    assert caught.value.code == "invalid_readiness_metadata"


def test_closed_readiness_states_and_unresolved_sentinel_serialize_safely() -> None:
    value = RollbackReadinessMetadata(
        rollback_config=EvidenceState.NONE,
        config_binding_diff=EvidenceState.UNCHANGED,
        secret_name_diff=EvidenceState.CHANGED,
    ).to_public_dict()
    assert value == {
        "current_deployed_version": "UNRESOLVED_FOR_LIVE_AUTHORITY",
        "rollback_version": "UNRESOLVED_FOR_LIVE_AUTHORITY",
        "rollback_config": "NONE",
        "config_binding_diff": "UNCHANGED",
        "secret_name_diff": "CHANGED",
    }


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


def test_reference_parity_is_real_agent_contract_and_agent_only() -> None:
    results = run(run_reference_parity_probe())
    assert tuple(item.consumer for item in results) == AGENT_REFERENCE_CONSUMERS
    assert all(item.ok for item in results)
    assert all(item.error_code is None for item in results)
    assert all(len(item.rejected_authority_keys) == 13 for item in results)
    serialized = json.dumps([item.to_public_dict() for item in results], sort_keys=True)
    assert "padiem-chat" in serialized
    assert "padiem-claw" in serialized
    assert "provider://" not in serialized
    assert "route=" not in serialized
    assert "authority key was not rejected" not in serialized
    expected_keys = {
        "subject_id",
        "tool_authorization",
        "authorization",
        "connector_grants",
        "provider",
        "provider_route",
        "policy",
        "model_policy",
        "entitlement",
        "skill_registry",
        "skill_installations",
        "skill_runtime_policy",
        "skill_id",
    }
    assert all(set(item.rejected_authority_keys) == expected_keys for item in results)


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
    assert all(item.error_code is None for item in evidence.reference_parity)
    assert all(item.ok for item in evidence.reference_parity)


def test_manifest_and_skill_are_not_activated_by_gate_source() -> None:
    from app.capability_manifest import CapabilityState, current_capability_manifest
    from app.contract_manifest import EngineFeatureState, current_engine_contract_manifest

    assert current_capability_manifest().capability_state("agent_skill_runtime") is CapabilityState.DEFERRED
    manifest = current_engine_contract_manifest()
    assert manifest.feature_state("agent_runtime_projection") is EngineFeatureState.DEFERRED
    assert manifest.feature_state("skill_runtime_projection") is EngineFeatureState.DEFERRED
