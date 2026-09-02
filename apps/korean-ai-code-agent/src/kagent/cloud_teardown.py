from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any

from .cloud_execution_plan import CloudM1ExecutionPlan, CloudM1Stage
from .cloud_stage_receipts import CloudM1StageReceipt, CloudStageOutcome
from .contracts import ContractError
from .security import redact_secrets


_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,511}$")


def _ref(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_REF_RE.fullmatch(value.strip()):
        raise ContractError(f"{field_name} must be a bounded safe reference")
    value = value.strip()
    if redact_secrets(value) != value:
        raise ContractError(f"{field_name} must not contain credential material")
    return value


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ContractError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class TrustedTeardownObservation:
    observation_id: str
    plan_id: str
    run_id: str
    sandbox_lease_ref: str
    computer_ref: str | None
    observed_at: datetime
    process_tree_killed: bool
    active_child_process_count: int
    workspace_destroyed: bool
    sandbox_terminal: bool
    computer_terminal: bool
    preview_shares_terminal: bool
    human_control_terminal: bool
    artifacts_finalized: bool
    authority_ref: str

    def __post_init__(self) -> None:
        for field_name in ("observation_id", "plan_id", "run_id", "sandbox_lease_ref", "authority_ref"):
            object.__setattr__(self, field_name, _ref(getattr(self, field_name), field_name))
        if self.computer_ref is not None:
            object.__setattr__(self, "computer_ref", _ref(self.computer_ref, "computer_ref"))
        object.__setattr__(self, "observed_at", _aware(self.observed_at, "observed_at"))
        for field_name in (
            "process_tree_killed",
            "workspace_destroyed",
            "sandbox_terminal",
            "computer_terminal",
            "preview_shares_terminal",
            "human_control_terminal",
            "artifacts_finalized",
        ):
            if not isinstance(getattr(self, field_name), bool):
                raise ContractError(f"{field_name} must be boolean")
        if isinstance(self.active_child_process_count, bool) or not isinstance(self.active_child_process_count, int) or not 0 <= self.active_child_process_count <= 1_000_000:
            raise ContractError("active_child_process_count must be a non-negative bounded integer")
        if self.computer_ref is None and self.computer_terminal is not True:
            raise ContractError("computer_terminal must be true when no Agent Computer was allocated")

    @property
    def clean(self) -> bool:
        return (
            self.process_tree_killed
            and self.active_child_process_count == 0
            and self.workspace_destroyed
            and self.sandbox_terminal
            and self.computer_terminal
            and self.preview_shares_terminal
            and self.human_control_terminal
            and self.artifacts_finalized
        )

    def safe_dict(self) -> dict[str, Any]:
        return {
            "observation_id": self.observation_id,
            "plan_id": self.plan_id,
            "run_id": self.run_id,
            "sandbox_lease_ref": self.sandbox_lease_ref,
            "computer_ref": self.computer_ref,
            "observed_at": self.observed_at.isoformat().replace("+00:00", "Z"),
            "process_tree_killed": self.process_tree_killed,
            "active_child_process_count": self.active_child_process_count,
            "workspace_destroyed": self.workspace_destroyed,
            "sandbox_terminal": self.sandbox_terminal,
            "computer_terminal": self.computer_terminal,
            "preview_shares_terminal": self.preview_shares_terminal,
            "human_control_terminal": self.human_control_terminal,
            "artifacts_finalized": self.artifacts_finalized,
            "authority_ref": self.authority_ref,
            "clean": self.clean,
            "raw_runtime_payload": False,
            "provider_endpoint": False,
            "credential_value": False,
        }


@dataclass(frozen=True, slots=True)
class CloudM1TeardownReceipt:
    receipt_id: str
    plan_id: str
    plan_fingerprint: str
    run_id: str
    observation_id: str
    observed_at: datetime
    clean: bool
    evidence_sha256: str

    @classmethod
    def from_observation(
        cls,
        *,
        receipt_id: str,
        plan: CloudM1ExecutionPlan,
        observation: TrustedTeardownObservation,
    ) -> "CloudM1TeardownReceipt":
        if not isinstance(plan, CloudM1ExecutionPlan):
            raise ContractError("plan must be CloudM1ExecutionPlan")
        if not isinstance(observation, TrustedTeardownObservation):
            raise ContractError("observation must be TrustedTeardownObservation")
        if observation.plan_id != plan.plan_id or observation.run_id != plan.run_id:
            raise ContractError("teardown observation does not belong to execution plan")
        payload = observation.safe_dict()
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return cls(
            receipt_id=_ref(receipt_id, "receipt_id"),
            plan_id=plan.plan_id,
            plan_fingerprint=plan.fingerprint,
            run_id=plan.run_id,
            observation_id=observation.observation_id,
            observed_at=observation.observed_at,
            clean=observation.clean,
            evidence_sha256=hashlib.sha256(encoded).hexdigest(),
        )

    def __post_init__(self) -> None:
        for field_name in ("receipt_id", "plan_id", "run_id", "observation_id"):
            object.__setattr__(self, field_name, _ref(getattr(self, field_name), field_name))
        if not isinstance(self.plan_fingerprint, str) or not re.fullmatch(r"[a-f0-9]{64}", self.plan_fingerprint):
            raise ContractError("plan_fingerprint must be SHA-256")
        object.__setattr__(self, "observed_at", _aware(self.observed_at, "observed_at"))
        if not isinstance(self.clean, bool):
            raise ContractError("clean must be boolean")
        if not isinstance(self.evidence_sha256, str) or not re.fullmatch(r"[a-f0-9]{64}", self.evidence_sha256):
            raise ContractError("evidence_sha256 must be SHA-256")

    def as_stage_receipt(self, *, event_id: str) -> CloudM1StageReceipt:
        return CloudM1StageReceipt(
            event_id=_ref(event_id, "event_id"),
            plan_id=self.plan_id,
            plan_fingerprint=self.plan_fingerprint,
            stage=CloudM1Stage.TEARDOWN,
            outcome=CloudStageOutcome.SUCCEEDED if self.clean else CloudStageOutcome.FAILED,
            observed_at=self.observed_at,
            evidence_ref=f"teardown:{self.receipt_id}:{self.evidence_sha256[:24]}",
            summary_code="teardown_clean" if self.clean else "teardown_incomplete",
        )

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-cloud-m1-teardown-receipt.v1",
            "receipt_id": self.receipt_id,
            "plan_id": self.plan_id,
            "plan_fingerprint": self.plan_fingerprint,
            "run_id": self.run_id,
            "observation_id": self.observation_id,
            "observed_at": self.observed_at.isoformat().replace("+00:00", "Z"),
            "clean": self.clean,
            "evidence_sha256": self.evidence_sha256,
            "false_clean_teardown_supported": False,
            "raw_runtime_payload": False,
            "provider_endpoint": False,
            "credential_value": False,
        }


REAL_TEARDOWN_PROBE_CONFIGURED = False
FALSE_CLEAN_TEARDOWN_SUPPORTED = False
