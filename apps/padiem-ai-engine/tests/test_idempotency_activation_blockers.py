"""Guard #1235 idempotency activation blockers before Production binding."""

from __future__ import annotations

from pathlib import Path

from app.contract_manifest import EngineFeatureState, current_engine_contract_manifest


DOC_PATH = (
    Path(__file__).resolve().parents[3]
    / "docs"
    / "operations"
    / "P01_ENGINE_IDEMPOTENCY_ACTIVATION_BLOCKERS_v1.md"
)


def test_idempotency_manifest_remains_deferred_before_production_activation() -> None:
    manifest = current_engine_contract_manifest()

    assert manifest.feature_state("idempotency_replay") is EngineFeatureState.DEFERRED
    assert manifest.feature_state("execution_idempotency_replay_completed") is EngineFeatureState.DEFERRED
    assert manifest.feature_state("execution_idempotency_replay_streaming") is EngineFeatureState.DEFERRED


def test_activation_blocker_document_matches_manifest_boundary() -> None:
    text = DOC_PATH.read_text(encoding="utf-8")

    required_markers = {
        "IDEMPOTENCY_ADAPTER_BOUNDARY = SOURCE_PRESENT",
        "D1_SCHEMA_CONTRACT = SOURCE_PRESENT",
        "STALE_RESERVATION_EXPIRY_RECOVERY = SOURCE_PRESENT",
        "IDEMPOTENT_RESUME_GATE = SOURCE_PRESENT",
        "MANIFEST_IDEMPOTENCY_REPLAY = DEFERRED",
        "PRODUCTION_ACTIVATION = NOT_DONE",
        "ISSUE1235_CLOSE = NO",
        "BLOCKER_1_PRODUCTION_D1_BINDING_PROVISIONED = REQUIRED",
        "BLOCKER_2_D1_SCHEMA_APPLIED_TO_TARGET_ENVIRONMENT = REQUIRED",
        "BLOCKER_4_ADAPTER_READ_WRITE_SMOKE_AGAINST_BOUND_DURABLE_STORE = REQUIRED",
        "BLOCKER_9_PAUSE_RESUME_NO_SECOND_LOGICAL_RUN_SMOKE = REQUIRED",
        "BLOCKER_10_MANIFEST_AVAILABLE_CHANGE_SEPARATE_PR = REQUIRED",
        "SOURCE_PRESENT != AVAILABLE",
    }
    missing = sorted(marker for marker in required_markers if marker not in text)
    assert missing == []


def test_source_only_slice_forbids_premature_available_claims() -> None:
    text = DOC_PATH.read_text(encoding="utf-8")

    forbidden_markers = {
        "MANIFEST_IDEMPOTENCY_REPLAY_AVAILABLE = FORBIDDEN",
        "EXECUTION_IDEMPOTENCY_REPLAY_COMPLETED_AVAILABLE = FORBIDDEN",
        "EXECUTION_IDEMPOTENCY_REPLAY_STREAMING_AVAILABLE = FORBIDDEN",
        "PROCESS_LOCAL_FAKE_PRODUCTION_STORE = FORBIDDEN",
        "B62_IDEMPOTENCY_AUTHORITY = FORBIDDEN",
        "B14_IDEMPOTENCY_AUTHORITY = FORBIDDEN",
        "PRODUCTION_D1_PROVISIONING_IN_SOURCE_ONLY_SLICE = FORBIDDEN",
        "WRANGLER_BINDING_MUTATION_IN_SOURCE_ONLY_SLICE = FORBIDDEN",
    }
    missing = sorted(marker for marker in forbidden_markers if marker not in text)
    assert missing == []

    # Guard the literal contract: before activation, the document must not claim
    # that the real Worker-bound replay capability is available.
    assert "MANIFEST_IDEMPOTENCY_REPLAY = AVAILABLE" not in text
    assert "PRODUCTION_ACTIVATION = DONE" not in text
