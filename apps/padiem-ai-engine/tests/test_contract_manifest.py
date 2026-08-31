import pytest

from app.contract_manifest import (
    ENGINE_CONTRACT_FAMILY,
    ENGINE_CONTRACT_MAJOR,
    ENGINE_CONTRACT_VERSION,
    ContractManifestError,
    EngineFeatureState,
    current_engine_contract_manifest,
    require_compatible_engine_contract,
)
from app.service import EXECUTE_PATH, HEALTH_PATH
from app.streaming_service import STREAM_PATH


def test_manifest_matches_existing_internal_v1_routes() -> None:
    manifest = current_engine_contract_manifest()

    assert manifest.family == ENGINE_CONTRACT_FAMILY
    assert manifest.major == ENGINE_CONTRACT_MAJOR == 1
    assert manifest.version == ENGINE_CONTRACT_VERSION == "1.0"
    assert [(item.method, item.path) for item in manifest.endpoints] == [
        ("POST", EXECUTE_PATH),
        ("POST", STREAM_PATH),
        ("GET", HEALTH_PATH),
    ]


def test_current_completed_and_streaming_features_are_available() -> None:
    manifest = current_engine_contract_manifest()

    assert manifest.feature_state("completed_run") is EngineFeatureState.AVAILABLE
    assert manifest.feature_state("streaming_run") is EngineFeatureState.AVAILABLE
    assert manifest.feature_state("service_identity_contract") is EngineFeatureState.AVAILABLE


def test_future_core_projection_features_are_truthfully_deferred() -> None:
    manifest = current_engine_contract_manifest()

    for feature_id in (
        "service_identity_wire_enforcement",
        "tool_runtime_projection",
        "skill_runtime_projection",
        "agent_runtime_projection",
        "memory_rag_projection",
    ):
        assert manifest.feature_state(feature_id) is EngineFeatureState.DEFERRED


def test_public_browser_api_and_provider_selection_are_unavailable() -> None:
    manifest = current_engine_contract_manifest()

    assert manifest.feature_state("public_browser_api") is EngineFeatureState.UNAVAILABLE
    assert manifest.feature_state("provider_selection") is EngineFeatureState.UNAVAILABLE


def test_compatible_client_can_require_available_features() -> None:
    manifest = require_compatible_engine_contract(
        requested_major=1,
        required_features=("completed_run", "streaming_run"),
    )
    assert manifest.major == 1


def test_wrong_major_fails_closed() -> None:
    with pytest.raises(ContractManifestError) as exc_info:
        require_compatible_engine_contract(requested_major=2)
    assert exc_info.value.code == "incompatible_engine_contract"


def test_client_cannot_require_deferred_or_unavailable_feature() -> None:
    for feature_id in (
        "memory_rag_projection",
        "public_browser_api",
        "provider_selection",
    ):
        with pytest.raises(ContractManifestError) as exc_info:
            require_compatible_engine_contract(
                requested_major=1,
                required_features=(feature_id,),
            )
        assert exc_info.value.code == "engine_feature_unavailable"


def test_unknown_feature_is_not_assumed_available() -> None:
    with pytest.raises(ContractManifestError) as exc_info:
        require_compatible_engine_contract(
            requested_major=1,
            required_features=("future_magic_feature",),
        )
    assert exc_info.value.code == "unknown_engine_feature"


def test_manifest_exposes_no_provider_inventory_or_credentials() -> None:
    public = current_engine_contract_manifest().to_public_dict()
    serialized = repr(public).lower()

    for forbidden in (
        "api_key",
        "authorization",
        "credential_sha256",
        "openrouter",
        "poolside",
        "provider_models",
        "account_id",
    ):
        assert forbidden not in serialized
