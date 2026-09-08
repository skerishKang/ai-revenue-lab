"""B54 compatibility tests: shared Core projection vs the Cloud M1 scaffold (#1558).

Proves semantic parity between the promoted shared primitive
(``padiem_ai_core.public_failure_projection``) and the B54 product scaffold
(``kagent.cloud_public_failure``) without moving the B54 lifecycle into the
Engine authority: the Cloud M1 stage names stay in B54 and are supplied to the
shared primitive as a product stage mapping.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib

import pytest

from kagent.cloud_execution_plan import CloudM1Stage
from kagent.cloud_public_failure import (
    _STAGE_CATEGORY,
    PublicCloudFailureCategory,
    project_public_failure,
)
from kagent.cloud_stage_receipts import CloudM1StageReceipt, CloudStageOutcome
from kagent.contracts import ContractError
from padiem_ai_core.public_failure_projection import (
    PublicFailureCategory,
    StageFailureReceipt,
    StageOutcome,
    project_stage_failure,
)

_PLAN_ID = "claw-plan-1558"
_FINGERPRINT = hashlib.sha256(b"claw-plan-material").hexdigest()

# Product-owned projection of the B54 Cloud M1 lifecycle onto shared stages.
CLOUD_M1_TO_SHARED_CATEGORY = {
    CloudM1Stage.ADMISSION.value: PublicFailureCategory.POLICY_OR_ADMISSION_FAILED,
    CloudM1Stage.REPOSITORY_MATERIALIZATION.value: PublicFailureCategory.REPOSITORY_MATERIALIZATION_FAILED,
    CloudM1Stage.SANDBOX_READY.value: PublicFailureCategory.SANDBOX_OR_COMPUTER_FAILED,
    CloudM1Stage.AGENT_COMPUTER_READY.value: PublicFailureCategory.SANDBOX_OR_COMPUTER_FAILED,
    CloudM1Stage.P01_EXECUTION.value: PublicFailureCategory.AGENT_EXECUTION_FAILED,
    CloudM1Stage.VERIFICATION.value: PublicFailureCategory.VERIFICATION_FAILED,
    CloudM1Stage.ARTIFACT_COLLECTION.value: PublicFailureCategory.ARTIFACT_OR_OUTPUT_FAILED,
    CloudM1Stage.VERIFIED_DIFF.value: PublicFailureCategory.ARTIFACT_OR_OUTPUT_FAILED,
    CloudM1Stage.OPTIONAL_DRAFT_PR.value: PublicFailureCategory.ARTIFACT_OR_OUTPUT_FAILED,
    CloudM1Stage.TEARDOWN.value: PublicFailureCategory.TEARDOWN_FAILED,
}


def _now() -> datetime:
    return datetime(2026, 9, 8, 12, 0, 0, tzinfo=timezone.utc)


def _b54_receipt(stage: CloudM1Stage, outcome: CloudStageOutcome = CloudStageOutcome.FAILED) -> CloudM1StageReceipt:
    return CloudM1StageReceipt(
        event_id=f"evt-{stage.value}",
        plan_id=_PLAN_ID,
        plan_fingerprint=_FINGERPRINT,
        stage=stage,
        outcome=outcome,
        observed_at=_now(),
        evidence_ref=f"ev-{stage.value}",
        summary_code=f"claw.{stage.value}.failed",
    )


def _shared_receipt(stage_value: str) -> StageFailureReceipt:
    return StageFailureReceipt(
        plan_id=_PLAN_ID,
        plan_fingerprint=_FINGERPRINT,
        stage_id=stage_value,
        outcome=StageOutcome.FAILED,
        summary_code=f"claw.{stage_value}.failed",
        event_id=f"evt-{stage_value}",
        evidence_ref=f"ev-{stage_value}",
    )


def test_shared_stage_mapping_matches_b54_scaffold_for_every_stage() -> None:
    b54_map = {stage.value: category.value for stage, category in _STAGE_CATEGORY.items()}
    shared_map = {stage: category.value for stage, category in CLOUD_M1_TO_SHARED_CATEGORY.items()}
    assert shared_map == b54_map
    assert set(shared_map) == {stage.value for stage in CloudM1Stage}


@pytest.mark.parametrize("stage", list(CloudM1Stage))
def test_both_layers_project_the_same_category(stage: CloudM1Stage) -> None:
    b54_projection = project_public_failure(
        _b54_receipt(stage),
        expected_plan_id=_PLAN_ID,
        expected_plan_fingerprint=_FINGERPRINT,
    )
    shared_projection = project_stage_failure(
        _shared_receipt(stage.value),
        expected_plan_id=_PLAN_ID,
        expected_plan_fingerprint=_FINGERPRINT,
        stage_categories=CLOUD_M1_TO_SHARED_CATEGORY,
    )
    assert b54_projection.category.value == shared_projection.category.value
    assert b54_projection.summary_code == shared_projection.summary_code
    assert b54_projection.retryable is shared_projection.retryable is False
    assert stage is not CloudM1Stage.TEARDOWN or shared_projection.category is PublicFailureCategory.TEARDOWN_FAILED


def test_shared_public_dict_keeps_b54_inert_flags() -> None:
    public = project_stage_failure(
        _shared_receipt(CloudM1Stage.TEARDOWN.value),
        expected_plan_id=_PLAN_ID,
        expected_plan_fingerprint=_FINGERPRINT,
        stage_categories=CLOUD_M1_TO_SHARED_CATEGORY,
    ).to_public_dict()
    b54_public = project_public_failure(
        _b54_receipt(CloudM1Stage.TEARDOWN),
        expected_plan_id=_PLAN_ID,
        expected_plan_fingerprint=_FINGERPRINT,
    ).safe_dict()
    for key in (
        "raw_provider_error",
        "raw_terminal_output",
        "raw_diff",
        "tool_args",
        "credentials",
        "hidden_reasoning",
        "automatic_retry",
    ):
        assert public[key] is False
        assert b54_public[key] is False


@pytest.mark.parametrize(
    ("outcome", "shared_outcome"),
    [
        (CloudStageOutcome.SUCCEEDED, StageOutcome.SUCCEEDED),
        (CloudStageOutcome.SKIPPED, StageOutcome.SKIPPED),
    ],
)
def test_non_failed_receipt_rejected_by_both_layers(outcome: CloudStageOutcome, shared_outcome: StageOutcome) -> None:
    with pytest.raises(ContractError, match="only failed stage receipt"):
        project_public_failure(
            _b54_receipt(CloudM1Stage.VERIFICATION, outcome=outcome),
            expected_plan_id=_PLAN_ID,
            expected_plan_fingerprint=_FINGERPRINT,
        )
    with pytest.raises(ValueError, match="only a failed stage receipt"):
        project_stage_failure(
            StageFailureReceipt(
                plan_id=_PLAN_ID,
                plan_fingerprint=_FINGERPRINT,
                stage_id=CloudM1Stage.VERIFICATION.value,
                outcome=shared_outcome,
                summary_code="claw.verification.done",
            ),
            expected_plan_id=_PLAN_ID,
            expected_plan_fingerprint=_FINGERPRINT,
            stage_categories=CLOUD_M1_TO_SHARED_CATEGORY,
        )


def test_plan_binding_rejected_by_both_layers() -> None:
    with pytest.raises(ContractError, match="does not bind expected plan"):
        project_public_failure(
            _b54_receipt(CloudM1Stage.P01_EXECUTION),
            expected_plan_id="other-plan",
            expected_plan_fingerprint=_FINGERPRINT,
        )
    with pytest.raises(ValueError, match="does not bind the expected plan"):
        project_stage_failure(
            _shared_receipt(CloudM1Stage.P01_EXECUTION.value),
            expected_plan_id="other-plan",
            expected_plan_fingerprint=_FINGERPRINT,
            stage_categories=CLOUD_M1_TO_SHARED_CATEGORY,
        )


def test_raw_failure_text_rejected_by_both_layers() -> None:
    raw = "RuntimeError: sandbox vm-77 crashed at /srv/secret with key sk-123456"
    with pytest.raises((ContractError, ValueError)):
        _b54_receipt(CloudM1Stage.SANDBOX_READY).__class__(
            event_id="evt-x",
            plan_id=_PLAN_ID,
            plan_fingerprint=_FINGERPRINT,
            stage=CloudM1Stage.SANDBOX_READY,
            outcome=CloudStageOutcome.FAILED,
            observed_at=_now(),
            evidence_ref="ev-x",
            summary_code=raw,
        )
    with pytest.raises(ValueError, match="bounded server-owned public-safe code"):
        _shared_receipt(CloudM1Stage.SANDBOX_READY.value).__class__(
            plan_id=_PLAN_ID,
            plan_fingerprint=_FINGERPRINT,
            stage_id=CloudM1Stage.SANDBOX_READY.value,
            outcome=StageOutcome.FAILED,
            summary_code=raw,
        )
