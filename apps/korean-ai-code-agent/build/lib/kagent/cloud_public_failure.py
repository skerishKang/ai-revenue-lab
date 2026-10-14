from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import Any

from .cloud_execution_plan import CloudM1Stage
from .cloud_stage_receipts import CloudM1StageReceipt, CloudStageOutcome
from .contracts import ContractError

_SAFE_CODE_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,95}$")


class PublicCloudFailureCategory(str, Enum):
    POLICY_OR_ADMISSION_FAILED = "policy_or_admission_failed"
    REPOSITORY_MATERIALIZATION_FAILED = "repository_materialization_failed"
    SANDBOX_OR_COMPUTER_FAILED = "sandbox_or_computer_failed"
    AGENT_EXECUTION_FAILED = "agent_execution_failed"
    VERIFICATION_FAILED = "verification_failed"
    ARTIFACT_OR_OUTPUT_FAILED = "artifact_or_output_failed"
    TEARDOWN_FAILED = "teardown_failed"


_STAGE_CATEGORY = {
    CloudM1Stage.ADMISSION: PublicCloudFailureCategory.POLICY_OR_ADMISSION_FAILED,
    CloudM1Stage.REPOSITORY_MATERIALIZATION: PublicCloudFailureCategory.REPOSITORY_MATERIALIZATION_FAILED,
    CloudM1Stage.SANDBOX_READY: PublicCloudFailureCategory.SANDBOX_OR_COMPUTER_FAILED,
    CloudM1Stage.AGENT_COMPUTER_READY: PublicCloudFailureCategory.SANDBOX_OR_COMPUTER_FAILED,
    CloudM1Stage.P01_EXECUTION: PublicCloudFailureCategory.AGENT_EXECUTION_FAILED,
    CloudM1Stage.VERIFICATION: PublicCloudFailureCategory.VERIFICATION_FAILED,
    CloudM1Stage.ARTIFACT_COLLECTION: PublicCloudFailureCategory.ARTIFACT_OR_OUTPUT_FAILED,
    CloudM1Stage.VERIFIED_DIFF: PublicCloudFailureCategory.ARTIFACT_OR_OUTPUT_FAILED,
    CloudM1Stage.OPTIONAL_DRAFT_PR: PublicCloudFailureCategory.ARTIFACT_OR_OUTPUT_FAILED,
    CloudM1Stage.TEARDOWN: PublicCloudFailureCategory.TEARDOWN_FAILED,
}


@dataclass(frozen=True, slots=True)
class PublicCloudFailureProjection:
    plan_id: str
    plan_fingerprint: str
    failed_stage: CloudM1Stage
    category: PublicCloudFailureCategory
    summary_code: str
    retryable: bool = False

    def __post_init__(self) -> None:
        if not _SAFE_CODE_RE.fullmatch(self.summary_code):
            raise ContractError("public failure summary_code must be a bounded server-owned code")
        if not isinstance(self.retryable, bool):
            raise ContractError("retryable must be boolean")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-cloud-public-failure.v1",
            "plan_id": self.plan_id,
            "plan_fingerprint": self.plan_fingerprint,
            "failed_stage": self.failed_stage.value,
            "category": self.category.value,
            "summary_code": self.summary_code,
            "retryable": self.retryable,
            "raw_provider_error": False,
            "raw_terminal_output": False,
            "raw_diff": False,
            "tool_args": False,
            "credentials": False,
            "hidden_reasoning": False,
            "automatic_retry": False,
        }


def project_public_failure(receipt: CloudM1StageReceipt, *, expected_plan_id: str, expected_plan_fingerprint: str) -> PublicCloudFailureProjection:
    if not isinstance(receipt, CloudM1StageReceipt):
        raise ContractError("receipt must be CloudM1StageReceipt")
    if receipt.outcome is not CloudStageOutcome.FAILED:
        raise ContractError("only failed stage receipt may create public failure projection")
    if receipt.plan_id != expected_plan_id or receipt.plan_fingerprint != expected_plan_fingerprint:
        raise ContractError("failed receipt does not bind expected plan")
    if not _SAFE_CODE_RE.fullmatch(receipt.summary_code):
        raise ContractError("receipt summary_code is not public-safe")
    return PublicCloudFailureProjection(
        plan_id=receipt.plan_id,
        plan_fingerprint=receipt.plan_fingerprint,
        failed_stage=receipt.stage,
        category=_STAGE_CATEGORY[receipt.stage],
        summary_code=receipt.summary_code,
        retryable=False,
    )


RAW_PROVIDER_FAILURE_UI_SUPPORTED = False
RAW_TERMINAL_FAILURE_UI_SUPPORTED = False
AUTOMATIC_FAILURE_RETRY_SUPPORTED = False
