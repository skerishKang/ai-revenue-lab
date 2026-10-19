from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any

from .cloud_execution_plan import CloudM1ExecutionPlan
from .contracts import ContractError
from .security import redact_secrets

_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,511}$")
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_MAX_COUNTER = 2**63 - 1


def _ref(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_REF_RE.fullmatch(value.strip()):
        raise ContractError(f"{field_name} must be a bounded safe reference")
    value = value.strip()
    if redact_secrets(value) != value:
        raise ContractError(f"{field_name} must not contain credential material")
    return value


def _counter(value: int, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= _MAX_COUNTER:
        raise ContractError(f"{field_name} must be a bounded non-negative integer")
    return value


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ContractError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class TrustedResourceUsageObservation:
    observation_id: str
    plan_id: str
    run_id: str
    workspace_id: str
    plan_fingerprint: str
    wall_time_ms: int
    cpu_time_ms: int
    peak_memory_mib: int
    disk_read_bytes: int
    disk_write_bytes: int
    network_egress_bytes: int
    observed_at: datetime
    authority_ref: str
    evidence_ref: str

    def __post_init__(self) -> None:
        for name in ("observation_id", "plan_id", "run_id", "workspace_id", "authority_ref", "evidence_ref"):
            object.__setattr__(self, name, _ref(getattr(self, name), name))
        fingerprint = self.plan_fingerprint.strip().lower() if isinstance(self.plan_fingerprint, str) else ""
        if not _SHA256_RE.fullmatch(fingerprint):
            raise ContractError("plan_fingerprint must be SHA-256")
        object.__setattr__(self, "plan_fingerprint", fingerprint)
        for name in ("wall_time_ms", "cpu_time_ms", "peak_memory_mib", "disk_read_bytes", "disk_write_bytes", "network_egress_bytes"):
            object.__setattr__(self, name, _counter(getattr(self, name), name))
        if self.network_egress_bytes != 0:
            raise ContractError("Cloud M1 network-off usage observation requires zero network egress")
        object.__setattr__(self, "observed_at", _aware(self.observed_at, "observed_at"))


@dataclass(frozen=True, slots=True)
class CloudM1UsageReceipt:
    receipt_id: str
    plan_id: str
    run_id: str
    workspace_id: str
    plan_fingerprint: str
    wall_time_ms: int
    cpu_time_ms: int
    peak_memory_mib: int
    disk_read_bytes: int
    disk_write_bytes: int
    network_egress_bytes: int
    observed_at: datetime
    evidence_ref: str

    @property
    def fingerprint(self) -> str:
        payload = {
            "plan_id": self.plan_id,
            "run_id": self.run_id,
            "workspace_id": self.workspace_id,
            "plan_fingerprint": self.plan_fingerprint,
            "wall_time_ms": self.wall_time_ms,
            "cpu_time_ms": self.cpu_time_ms,
            "peak_memory_mib": self.peak_memory_mib,
            "disk_read_bytes": self.disk_read_bytes,
            "disk_write_bytes": self.disk_write_bytes,
            "network_egress_bytes": self.network_egress_bytes,
            "observed_at": self.observed_at.isoformat(),
            "evidence_ref": self.evidence_ref,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-cloud-m1-usage-receipt.v1",
            "receipt_id": self.receipt_id,
            "plan_id": self.plan_id,
            "run_id": self.run_id,
            "workspace_id": self.workspace_id,
            "plan_fingerprint": self.plan_fingerprint,
            "wall_time_ms": self.wall_time_ms,
            "cpu_time_ms": self.cpu_time_ms,
            "peak_memory_mib": self.peak_memory_mib,
            "disk_read_bytes": self.disk_read_bytes,
            "disk_write_bytes": self.disk_write_bytes,
            "network_egress_bytes": 0,
            "observed_at": self.observed_at.isoformat().replace("+00:00", "Z"),
            "evidence_ref": self.evidence_ref,
            "receipt_fingerprint": self.fingerprint,
            "measured": True,
            "estimated_provider_cost": False,
            "pricing_authority": False,
            "credit_debit_authority": False,
            "control_plane_handoff_only": True,
        }


def build_usage_receipt(*, plan: CloudM1ExecutionPlan, observation: TrustedResourceUsageObservation) -> CloudM1UsageReceipt:
    if not isinstance(plan, CloudM1ExecutionPlan):
        raise ContractError("plan must be CloudM1ExecutionPlan")
    if not isinstance(observation, TrustedResourceUsageObservation):
        raise ContractError("observation must be TrustedResourceUsageObservation")
    if (
        observation.plan_id != plan.plan_id
        or observation.run_id != plan.run_id
        or observation.workspace_id != plan.workspace_id
        or observation.plan_fingerprint != plan.fingerprint
    ):
        raise ContractError("usage observation does not bind exact Cloud M1 execution plan")
    digest = hashlib.sha256(f"{observation.observation_id}:{plan.fingerprint}".encode("utf-8")).hexdigest()[:24]
    return CloudM1UsageReceipt(
        receipt_id=f"usage:{digest}",
        plan_id=plan.plan_id,
        run_id=plan.run_id,
        workspace_id=plan.workspace_id,
        plan_fingerprint=plan.fingerprint,
        wall_time_ms=observation.wall_time_ms,
        cpu_time_ms=observation.cpu_time_ms,
        peak_memory_mib=observation.peak_memory_mib,
        disk_read_bytes=observation.disk_read_bytes,
        disk_write_bytes=observation.disk_write_bytes,
        network_egress_bytes=0,
        observed_at=observation.observed_at,
        evidence_ref=observation.evidence_ref,
    )


B54_PRICING_AUTHORITY = False
B54_CREDIT_DEBIT_AUTHORITY = False
ESTIMATED_PROVIDER_COST_SUPPORTED = False
REAL_BILLING_API_CONFIGURED = False
