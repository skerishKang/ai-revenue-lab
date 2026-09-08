"""Shared public-safe execution failure projection contract (#1558).

This module is the promoted-lane (Core/Engine) normalization boundary for
turning a server-owned *stage failure receipt* into a bounded, public-safe
failure projection. It owns only the shared projection mechanics:

- the fixed public failure categories,
- exact plan identity/fingerprint binding,
- the only-failed-state rule,
- the bounded server-owned summary code,
- conservative server-owned ``retryable`` (false by default),
- inert safety flags proving no raw provider error, terminal output, tool
  args/results, diff, filesystem path, provider endpoint, credential, hidden
  reasoning, or internal runtime payload can be carried.

It deliberately does NOT own:

- product lifecycle stage names (product lanes map their stages onto the
  shared categories; B54 Cloud M1 stages stay in B54),
- provider/model error origin classification (B14 ``ErrorClass`` stays the
  origin authority; this projection never carries raw provider text),
- orchestration/tool/evidence semantics (P01 owns those),
- the Engine HTTP error taxonomy (``apps/padiem-ai-engine/app/error_contract.py``
  is the API-surface authority; this is the execution-failure projection layer
  consumed by product UIs),
- any event-stream transport or protocol (that is #1490, out of scope here).

No authority is ever minted from a projection: retry, redispatch, and resume
remain server-owned decisions made elsewhere, and are false here by contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import Any, Mapping

from .execution_context import _safe_identifier, request_fingerprint

_SUMMARY_CODE_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,95}$")
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")

CONTRACT_VERSION = "padiem-public-failure.v1"

# The projection is presentation-normalization only. It cannot mint retry,
# redispatch, or resume authority; those remain server-owned decisions.
PUBLIC_FAILURE_AUTHORITY_MINTING = False
AUTOMATIC_RETRY = False
AUTOMATIC_REDISPATCH = False
AUTOMATIC_RESUME = False


class PublicFailureCategory(str, Enum):
    """Fixed bounded public failure categories (#1558 minimum semantics)."""

    POLICY_OR_ADMISSION_FAILED = "policy_or_admission_failed"
    REPOSITORY_MATERIALIZATION_FAILED = "repository_materialization_failed"
    SANDBOX_OR_COMPUTER_FAILED = "sandbox_or_computer_failed"
    AGENT_EXECUTION_FAILED = "agent_execution_failed"
    VERIFICATION_FAILED = "verification_failed"
    ARTIFACT_OR_OUTPUT_FAILED = "artifact_or_output_failed"
    TEARDOWN_FAILED = "teardown_failed"


class StageOutcome(str, Enum):
    """Outcome recorded on a stage receipt."""

    SUCCEEDED = "succeeded"
    SKIPPED = "skipped"
    FAILED = "failed"


# Shared canonical stage identifiers. Product lanes may supply their own
# stage->category mapping at projection time; unknown stages fail closed.
SHARED_FAILURE_STAGE_CATEGORY: Mapping[str, PublicFailureCategory] = {
    "admission": PublicFailureCategory.POLICY_OR_ADMISSION_FAILED,
    "repository_materialization": PublicFailureCategory.REPOSITORY_MATERIALIZATION_FAILED,
    "sandbox": PublicFailureCategory.SANDBOX_OR_COMPUTER_FAILED,
    "computer": PublicFailureCategory.SANDBOX_OR_COMPUTER_FAILED,
    "agent_execution": PublicFailureCategory.AGENT_EXECUTION_FAILED,
    "verification": PublicFailureCategory.VERIFICATION_FAILED,
    "artifact": PublicFailureCategory.ARTIFACT_OR_OUTPUT_FAILED,
    "output": PublicFailureCategory.ARTIFACT_OR_OUTPUT_FAILED,
    "teardown": PublicFailureCategory.TEARDOWN_FAILED,
}


def _safe_summary_code(value: str) -> str:
    if not isinstance(value, str) or not _SUMMARY_CODE_RE.fullmatch(value):
        raise ValueError(
            "summary_code must be a bounded server-owned public-safe code"
        )
    return value


def _safe_fingerprint(value: str) -> str:
    digest = value.strip().lower() if isinstance(value, str) else ""
    if not _SHA256_RE.fullmatch(digest):
        raise ValueError("plan_fingerprint must be a SHA-256 hex digest")
    return digest


@dataclass(frozen=True, slots=True)
class StageFailureReceipt:
    """Server-owned stage receipt fact accepted by the shared projection.

    Only bounded safe identifiers and a server-owned summary code are carried;
    raw error text, provider payloads, and runtime state cannot be represented
    by this type.
    """

    plan_id: str
    plan_fingerprint: str
    stage_id: str
    outcome: StageOutcome
    summary_code: str
    event_id: str = ""
    evidence_ref: str = ""
    retryable: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "plan_id", _safe_identifier("plan_id", self.plan_id))
        object.__setattr__(self, "stage_id", _safe_identifier("stage_id", self.stage_id))
        object.__setattr__(self, "plan_fingerprint", _safe_fingerprint(self.plan_fingerprint))
        _safe_summary_code(self.summary_code)
        if self.event_id:
            object.__setattr__(self, "event_id", _safe_identifier("event_id", self.event_id))
        if self.evidence_ref:
            object.__setattr__(self, "evidence_ref", _safe_identifier("evidence_ref", self.evidence_ref))
        if not isinstance(self.outcome, StageOutcome):
            try:
                object.__setattr__(self, "outcome", StageOutcome(self.outcome))
            except (TypeError, ValueError) as exc:
                raise ValueError("outcome must be a StageOutcome") from exc
        if not isinstance(self.retryable, bool):
            raise ValueError("retryable must be a server-owned boolean")

    @property
    def fingerprint(self) -> str:
        return request_fingerprint(
            {
                "plan_id": self.plan_id,
                "plan_fingerprint": self.plan_fingerprint,
                "stage_id": self.stage_id,
                "outcome": self.outcome.value,
                "summary_code": self.summary_code,
                "event_id": self.event_id,
                "evidence_ref": self.evidence_ref,
            }
        )


@dataclass(frozen=True, slots=True)
class PublicFailureProjection:
    """Bounded public-safe failure view; carries no free-form payload fields."""

    plan_id: str
    plan_fingerprint: str
    stage_id: str
    category: PublicFailureCategory
    summary_code: str
    retryable: bool = False

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "contract_version": CONTRACT_VERSION,
            "plan_id": self.plan_id,
            "plan_fingerprint": self.plan_fingerprint,
            "stage": self.stage_id,
            "category": self.category.value,
            "summary_code": self.summary_code,
            "retryable": self.retryable,
            "raw_provider_error": False,
            "raw_terminal_output": False,
            "tool_args": False,
            "tool_results": False,
            "raw_diff": False,
            "filesystem_path": False,
            "provider_endpoint": False,
            "credentials": False,
            "hidden_reasoning": False,
            "internal_runtime_payload": False,
            "automatic_retry": AUTOMATIC_RETRY,
            "automatic_redispatch": AUTOMATIC_REDISPATCH,
            "automatic_resume": AUTOMATIC_RESUME,
        }


def project_stage_failure(
    receipt: StageFailureReceipt,
    *,
    expected_plan_id: str,
    expected_plan_fingerprint: str,
    stage_categories: Mapping[str, PublicFailureCategory] | None = None,
) -> PublicFailureProjection:
    """Project one failed stage receipt into a bounded public failure view.

    Fails closed on: non-receipt input, non-failed outcomes, plan identity or
    fingerprint mismatch, non-public-safe summary codes, and unknown stage
    identifiers. Only the failed state ever produces a projection.
    """
    if not isinstance(receipt, StageFailureReceipt):
        raise ValueError("receipt must be a StageFailureReceipt")
    if receipt.outcome is not StageOutcome.FAILED:
        raise ValueError("only a failed stage receipt may produce a public failure projection")
    if receipt.plan_id != expected_plan_id or receipt.plan_fingerprint != _safe_fingerprint(
        expected_plan_fingerprint
    ):
        raise ValueError("failed receipt does not bind the expected plan identity")
    summary_code = _safe_summary_code(receipt.summary_code)
    mapping = SHARED_FAILURE_STAGE_CATEGORY if stage_categories is None else stage_categories
    try:
        category = mapping[receipt.stage_id]
    except (KeyError, TypeError):
        raise ValueError("stage identifier has no public failure category mapping") from None
    if not isinstance(category, PublicFailureCategory):
        raise ValueError("stage failure category must be a PublicFailureCategory")
    return PublicFailureProjection(
        plan_id=receipt.plan_id,
        plan_fingerprint=receipt.plan_fingerprint,
        stage_id=receipt.stage_id,
        category=category,
        summary_code=summary_code,
        retryable=receipt.retryable,
    )


__all__ = [
    "AUTOMATIC_REDISPATCH",
    "AUTOMATIC_RESUME",
    "AUTOMATIC_RETRY",
    "CONTRACT_VERSION",
    "PUBLIC_FAILURE_AUTHORITY_MINTING",
    "PublicFailureCategory",
    "PublicFailureProjection",
    "SHARED_FAILURE_STAGE_CATEGORY",
    "StageFailureReceipt",
    "StageOutcome",
    "project_stage_failure",
]
