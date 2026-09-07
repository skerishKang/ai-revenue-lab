"""Guard #1235 idempotency activation blockers after the WO-8 production activation."""

from __future__ import annotations

from pathlib import Path

from app.contract_manifest import EngineFeatureState, current_engine_contract_manifest


DOC_PATH = (
    Path(__file__).resolve().parents[3]
    / "docs"
    / "operations"
    / "P01_ENGINE_IDEMPOTENCY_ACTIVATION_BLOCKERS_v1.md"
)


def test_idempotency_manifest_activated_after_production_evidence() -> None:
    manifest = current_engine_contract_manifest()

    assert manifest.feature_state("idempotency_replay") is EngineFeatureState.AVAILABLE
    assert manifest.feature_state("execution_idempotency_replay_completed") is EngineFeatureState.AVAILABLE
    # Streaming replay stays DEFERRED: streaming_service rejects keyed streams
    # with 422 stream_idempotency_unavailable — the adapter is not wired (SOURCE_PRESENT != AVAILABLE).
    assert manifest.feature_state("execution_idempotency_replay_streaming") is EngineFeatureState.DEFERRED


def test_activation_blocker_document_matches_manifest_boundary() -> None:
    text = DOC_PATH.read_text(encoding="utf-8")

    required_markers = {
        "MANIFEST_IDEMPOTENCY_REPLAY = AVAILABLE",
        "EXECUTION_IDEMPOTENCY_REPLAY_STREAMING = DEFERRED",
        "BLOCKER_1_PRODUCTION_D1_BINDING_PROVISIONED = PROVEN",
        "BLOCKER_4_ADAPTER_READ_WRITE_SMOKE_AGAINST_BOUND_DURABLE_STORE = PROVEN",
        "BLOCKER_8_STALE_RESERVATION_EXPIRY_RECOVERY_SMOKE = PROVEN_BY_SOURCE_TEST",
        "BLOCKER_9_PAUSE_RESUME_NO_SECOND_LOGICAL_RUN_SMOKE = PROVEN_BY_SOURCE_TEST",
        "BLOCKER_10_MANIFEST_AVAILABLE_CHANGE_SEPARATE_PR = PROVEN",
        "SOURCE_PRESENT != AVAILABLE",
    }
    missing = sorted(marker for marker in required_markers if marker not in text)
    assert missing == []


def test_streaming_replay_remains_forbidden_until_adapter() -> None:
    text = DOC_PATH.read_text(encoding="utf-8")

    forbidden_markers = {
        "EXECUTION_IDEMPOTENCY_REPLAY_STREAMING_AVAILABLE = FORBIDDEN",
        "PROCESS_LOCAL_FAKE_PRODUCTION_STORE = FORBIDDEN",
        "B62_IDEMPOTENCY_AUTHORITY = FORBIDDEN",
        "B14_IDEMPOTENCY_AUTHORITY = FORBIDDEN",
    }
    missing = sorted(marker for marker in forbidden_markers if marker not in text)
    assert missing == []

    # Guard the literal contract: the document must not claim the streaming
    # replay capability is DONE-activated while the adapter is unwired.
    assert "PRODUCTION_ACTIVATION = DONE" not in text
