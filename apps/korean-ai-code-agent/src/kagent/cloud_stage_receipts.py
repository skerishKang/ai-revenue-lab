from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import re
from typing import Any

from .cloud_execution_plan import CloudM1ExecutionPlan, CloudM1Stage, FIXED_CLOUD_M1_STAGE_ORDER
from .contracts import ContractError


_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")


def _id(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value.strip()):
        raise ContractError(f"{field_name} must be a bounded safe identifier")
    return value.strip()


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ContractError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


class CloudStageOutcome(str, Enum):
    SUCCEEDED = "succeeded"
    SKIPPED = "skipped"
    FAILED = "failed"


class CloudExecutionTerminal(str, Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED_CLEANED_UP = "failed_cleaned_up"
    TEARDOWN_FAILED = "teardown_failed"


@dataclass(frozen=True, slots=True)
class CloudM1StageReceipt:
    event_id: str
    plan_id: str
    plan_fingerprint: str
    stage: CloudM1Stage
    outcome: CloudStageOutcome
    observed_at: datetime
    evidence_ref: str
    summary_code: str

    def __post_init__(self) -> None:
        for field_name in ("event_id", "plan_id", "evidence_ref", "summary_code"):
            object.__setattr__(self, field_name, _id(getattr(self, field_name), field_name))
        digest = self.plan_fingerprint.strip().lower() if isinstance(self.plan_fingerprint, str) else ""
        if not _SHA256_RE.fullmatch(digest):
            raise ContractError("plan_fingerprint must be SHA-256")
        object.__setattr__(self, "plan_fingerprint", digest)
        if not isinstance(self.stage, CloudM1Stage):
            try:
                object.__setattr__(self, "stage", CloudM1Stage(self.stage))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid Cloud M1 stage") from exc
        if not isinstance(self.outcome, CloudStageOutcome):
            try:
                object.__setattr__(self, "outcome", CloudStageOutcome(self.outcome))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid Cloud M1 stage outcome") from exc
        object.__setattr__(self, "observed_at", _aware(self.observed_at, "observed_at"))

    @property
    def fingerprint(self) -> str:
        payload = {
            "event_id": self.event_id,
            "plan_id": self.plan_id,
            "plan_fingerprint": self.plan_fingerprint,
            "stage": self.stage.value,
            "outcome": self.outcome.value,
            "observed_at": self.observed_at.isoformat(),
            "evidence_ref": self.evidence_ref,
            "summary_code": self.summary_code,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()

    def safe_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "plan_id": self.plan_id,
            "plan_fingerprint": self.plan_fingerprint,
            "stage": self.stage.value,
            "outcome": self.outcome.value,
            "observed_at": self.observed_at.isoformat().replace("+00:00", "Z"),
            "evidence_ref": self.evidence_ref,
            "summary_code": self.summary_code,
            "receipt_fingerprint": self.fingerprint,
            "raw_runtime_payload": False,
            "raw_diff": False,
            "tool_args": False,
            "hidden_reasoning": False,
        }


@dataclass(frozen=True, slots=True)
class CloudM1ExecutionProjection:
    plan_id: str
    plan_fingerprint: str
    terminal: CloudExecutionTerminal
    next_stage: CloudM1Stage | None
    completed_stages: tuple[CloudM1Stage, ...]
    failed_stage: CloudM1Stage | None
    receipt_count: int

    def safe_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "plan_fingerprint": self.plan_fingerprint,
            "terminal": self.terminal.value,
            "next_stage": self.next_stage.value if self.next_stage else None,
            "completed_stages": [stage.value for stage in self.completed_stages],
            "failed_stage": self.failed_stage.value if self.failed_stage else None,
            "receipt_count": self.receipt_count,
            "automatic_retry": False,
            "post_failure_continuation": False,
        }


class CloudM1StageReceiptLedger:
    def __init__(self, plan: CloudM1ExecutionPlan) -> None:
        if not isinstance(plan, CloudM1ExecutionPlan):
            raise ContractError("plan must be CloudM1ExecutionPlan")
        self.plan = plan
        self._receipts: list[CloudM1StageReceipt] = []
        self._by_event_id: dict[str, CloudM1StageReceipt] = {}
        self._failed_stage: CloudM1Stage | None = None
        self._terminal = CloudExecutionTerminal.ACTIVE

    def _expected_stage(self) -> CloudM1Stage | None:
        if self._terminal is not CloudExecutionTerminal.ACTIVE:
            return None
        if self._failed_stage is not None:
            return CloudM1Stage.TEARDOWN
        if not self._receipts:
            return FIXED_CLOUD_M1_STAGE_ORDER[0]
        last = self._receipts[-1]
        if last.stage is CloudM1Stage.TEARDOWN:
            return None
        index = FIXED_CLOUD_M1_STAGE_ORDER.index(last.stage)
        return FIXED_CLOUD_M1_STAGE_ORDER[index + 1]

    def append(self, receipt: CloudM1StageReceipt) -> CloudM1ExecutionProjection:
        if not isinstance(receipt, CloudM1StageReceipt):
            raise ContractError("receipt must be CloudM1StageReceipt")
        if receipt.plan_id != self.plan.plan_id or receipt.plan_fingerprint != self.plan.fingerprint:
            raise ContractError("stage receipt does not belong to this execution plan")
        replay = self._by_event_id.get(receipt.event_id)
        if replay is not None:
            if replay.fingerprint != receipt.fingerprint:
                raise ContractError("conflicting stage receipt event replay")
            return self.projection()
        if self._terminal is not CloudExecutionTerminal.ACTIVE:
            raise ContractError("terminal Cloud execution cannot accept more receipts")
        if self._receipts and receipt.observed_at < self._receipts[-1].observed_at:
            raise ContractError("stage receipt timestamps must be monotonic")
        expected = self._expected_stage()
        if receipt.stage is not expected:
            raise ContractError("stage receipt is out of server-owned execution order")
        if receipt.outcome is CloudStageOutcome.SKIPPED:
            if receipt.stage is not CloudM1Stage.OPTIONAL_DRAFT_PR or self.plan.draft_pr_requested:
                raise ContractError("only unrequested optional Draft PR stage may be skipped")
        if receipt.stage is CloudM1Stage.TEARDOWN and receipt.outcome is CloudStageOutcome.SKIPPED:
            raise ContractError("teardown cannot be skipped")

        self._receipts.append(receipt)
        self._by_event_id[receipt.event_id] = receipt

        if receipt.stage is CloudM1Stage.TEARDOWN:
            if receipt.outcome is CloudStageOutcome.FAILED:
                self._terminal = CloudExecutionTerminal.TEARDOWN_FAILED
            elif self._failed_stage is not None:
                self._terminal = CloudExecutionTerminal.FAILED_CLEANED_UP
            else:
                self._terminal = CloudExecutionTerminal.COMPLETED
            return self.projection()

        if receipt.outcome is CloudStageOutcome.FAILED:
            self._failed_stage = receipt.stage
        return self.projection()

    def projection(self) -> CloudM1ExecutionProjection:
        completed = tuple(
            item.stage
            for item in self._receipts
            if item.outcome in {CloudStageOutcome.SUCCEEDED, CloudStageOutcome.SKIPPED}
        )
        return CloudM1ExecutionProjection(
            plan_id=self.plan.plan_id,
            plan_fingerprint=self.plan.fingerprint,
            terminal=self._terminal,
            next_stage=self._expected_stage(),
            completed_stages=completed,
            failed_stage=self._failed_stage,
            receipt_count=len(self._receipts),
        )

    def safe_receipts(self) -> tuple[dict[str, Any], ...]:
        return tuple(item.safe_dict() for item in self._receipts)


AUTOMATIC_STAGE_RETRY_SUPPORTED = False
POST_FAILURE_STAGE_CONTINUATION_SUPPORTED = False
