"""Engine-lane conformance tests for the shared public failure projection (#1558).

The Engine keeps exactly one API-surface error authority
(``app.error_contract.ENGINE_ERROR_TAXONOMY``). This projection is a separate
consumption-layer contract for product surfaces and must never mint Engine
error codes, accept raw Engine/provider text, or widen retry semantics.
"""

from __future__ import annotations

import hashlib

import pytest

from app.error_contract import ENGINE_ERROR_TAXONOMY, engine_error_contract
from padiem_ai_core.public_failure_projection import (
    SHARED_FAILURE_STAGE_CATEGORY,
    PublicFailureCategory,
    StageFailureReceipt,
    StageOutcome,
    project_stage_failure,
)

_PLAN_ID = "engine-plan-1558"
_FINGERPRINT = hashlib.sha256(b"engine-plan-material").hexdigest()


def _receipt(stage_id: str, summary_code: str) -> StageFailureReceipt:
    return StageFailureReceipt(
        plan_id=_PLAN_ID,
        plan_fingerprint=_FINGERPRINT,
        stage_id=stage_id,
        outcome=StageOutcome.FAILED,
        summary_code=summary_code,
    )


def _project(receipt_value: StageFailureReceipt):
    return project_stage_failure(
        receipt_value,
        expected_plan_id=_PLAN_ID,
        expected_plan_fingerprint=_FINGERPRINT,
    )


def test_projection_never_mints_or_reuses_engine_error_codes() -> None:
    taxonomy_codes = {item.code for item in ENGINE_ERROR_TAXONOMY}
    for stage_id in SHARED_FAILURE_STAGE_CATEGORY:
        projection = _project(_receipt(stage_id, "stage.failed"))
        assert projection.summary_code not in taxonomy_codes
        assert projection.category.value not in taxonomy_codes
        assert projection.to_public_dict()["category"] in {item.value for item in PublicFailureCategory}


def test_raw_engine_safe_message_cannot_be_smuggled_as_summary_code() -> None:
    internal = engine_error_contract("engine_internal_error")
    with pytest.raises(ValueError, match="bounded server-owned public-safe code"):
        _receipt("agent_execution", internal.safe_message)
    with pytest.raises(ValueError, match="bounded server-owned public-safe code"):
        _receipt("agent_execution", internal.code.replace("_", ".").capitalize())


def test_projection_retryable_never_inherits_taxonomy_retryability() -> None:
    retryable_codes = [item.code for item in ENGINE_ERROR_TAXONOMY if item.retryable]
    assert "b14_service_unavailable" in retryable_codes
    projection = _project(_receipt("agent_execution", "stage.failed"))
    assert projection.retryable is False


def test_failed_stage_projects_bounded_public_view() -> None:
    projection = _project(_receipt("teardown", "teardown.resource.unreleased"))
    public = projection.to_public_dict()
    assert public["category"] == "teardown_failed"
    assert public["raw_provider_error"] is False
    assert public["credentials"] is False
    assert public["hidden_reasoning"] is False
    assert public["internal_runtime_payload"] is False
    assert set(public["summary_code"]) <= set(
        "abcdefghijklmnopqrstuvwxyz0123456789._-"
    )


def test_non_failed_stage_receipt_cannot_project_on_engine_lane() -> None:
    for outcome in (StageOutcome.SUCCEEDED, StageOutcome.SKIPPED):
        with pytest.raises(ValueError, match="only a failed stage receipt"):
            project_stage_failure(
                StageFailureReceipt(
                    plan_id=_PLAN_ID,
                    plan_fingerprint=_FINGERPRINT,
                    stage_id="verification",
                    outcome=outcome,
                    summary_code="stage.done",
                ),
                expected_plan_id=_PLAN_ID,
                expected_plan_fingerprint=_FINGERPRINT,
            )
