"""Bounded Cloud M1 resource-usage receipts for the Control Plane (#1556).

Promoted-lane projection of the reviewed B54 metering contract
(``apps/korean-ai-code-agent/src/kagent/cloud_usage_metering.py``). A
trusted runtime host records one resource-usage observation per executed
Cloud M1 plan run; the Control Plane converts it into exactly one
usage receipt bound to the plan identity.

This module owns only the resource-observation-to-receipt mechanics:

- the CloudM1ExecutionPlan identity refs (plan id + run id + workspace id
  + plan SHA-256 fingerprint) and their exact binding to the observation,
- bounded non-negative wall/CPU/memory/disk metrics,
- the Cloud-M1 network-off invariant: network egress must be zero,
- a deterministic receipt fingerprint and a public-safe projection.

It deliberately does NOT own:

- pricing, rates, money, credit balances or cost estimation — this is a
  measurement projection only and the existing token-billing
  ``UsageEvent`` remains a separate contract;
- provider credentials or raw provider payloads;
- runtime execution, sandbox control, database persistence or any network
  activity: receipt construction is pure offline validation;
- handoff beyond recording: receipts exist for Control Plane handoff only.

No authority is ever minted from a usage receipt.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any

from .contracts import ControlPlaneContractError

MIN_COUNTER = 0
MAX_COUNTER = 2**63 - 1

_USAGE_RECEIPT_CONTRACT_VERSION = "claw-cloud-m1-usage-receipt.v1"

# Honest capability flags (ported from the reviewed contract):
# this lane performs measurement projection only.
USAGE_RECEIPT_PRICING_AUTHORITY = False
USAGE_RECEIPT_CREDIT_DEBIT_AUTHORITY = False
ESTIMATED_PROVIDER_COST_SUPPORTED = False
REAL_BILLING_API_CONFIGURED = False

_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,511}$")
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")


def _ref(value: str, field_name: str, *, code: str) -> str:
    if not isinstance(value, str) or not _SAFE_REF_RE.fullmatch(value.strip()):
        raise ControlPlaneContractError(code, f"{field_name} must be a bounded safe reference")
    return value.strip()


def _counter(value: int, field_name: str, *, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not MIN_COUNTER <= value <= MAX_COUNTER:
        raise ControlPlaneContractError(code, f"{field_name} must be a bounded non-negative integer")
    return value


def _sha256(value: str, field_name: str, *, code: str) -> str:
    digest = value.strip().lower() if isinstance(value, str) else ""
    if not _SHA256_RE.fullmatch(digest):
        raise ControlPlaneContractError(code, f"{field_name} must be a lowercase SHA-256 digest")
    return digest


def _aware(value: datetime, field_name: str, *, code: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ControlPlaneContractError(code, f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


_OBS = "invalid_usage_observation"
_RCP = "invalid_usage_receipt"
_REF = "invalid_plan_ref"
_BIND = "plan_binding_mismatch"


@dataclass(frozen=True, slots=True)
class TrustedResourceUsageObservation:
    """One trusted server-issued resource measurement for one plan run.

    Carries bounded counters and references only — never provider
    credentials, raw provider payloads or attachment-like content.
    """

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
        for name in (
            "observation_id",
            "plan_id",
            "run_id",
            "workspace_id",
            "authority_ref",
            "evidence_ref",
        ):
            object.__setattr__(self, name, _ref(getattr(self, name), name, code=_OBS))
        object.__setattr__(self, "plan_fingerprint", _sha256(self.plan_fingerprint, "plan_fingerprint", code=_OBS))
        for name in (
            "wall_time_ms",
            "cpu_time_ms",
            "peak_memory_mib",
            "disk_read_bytes",
            "disk_write_bytes",
            "network_egress_bytes",
        ):
            object.__setattr__(self, name, _counter(getattr(self, name), name, code=_OBS))
        if self.network_egress_bytes != 0:
            raise ControlPlaneContractError(
                _OBS,
                "Cloud M1 network-off usage observation requires zero network egress",
            )
        object.__setattr__(self, "observed_at", _aware(self.observed_at, "observed_at", code=_OBS))

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": _USAGE_RECEIPT_CONTRACT_VERSION,
            "observation_id": self.observation_id,
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
            "authority_ref": self.authority_ref,
            "evidence_ref": self.evidence_ref,
            "raw_provider_payload": False,
            "provider_credential": False,
            "estimated_provider_cost": False,
        }


@dataclass(frozen=True, slots=True)
class CloudM1UsageReceipt:
    """The Control-Plane-handoff usage record for one plan run."""

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

    def __post_init__(self) -> None:
        for name in ("receipt_id", "plan_id", "run_id", "workspace_id", "evidence_ref"):
            object.__setattr__(self, name, _ref(getattr(self, name), name, code=_RCP))
        object.__setattr__(self, "plan_fingerprint", _sha256(self.plan_fingerprint, "plan_fingerprint", code=_RCP))
        for name in (
            "wall_time_ms",
            "cpu_time_ms",
            "peak_memory_mib",
            "disk_read_bytes",
            "disk_write_bytes",
            "network_egress_bytes",
        ):
            object.__setattr__(self, name, _counter(getattr(self, name), name, code=_RCP))
        if self.network_egress_bytes != 0:
            raise ControlPlaneContractError(_RCP, "usage receipt network egress must be zero")
        object.__setattr__(self, "observed_at", _aware(self.observed_at, "observed_at", code=_RCP))

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
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": _USAGE_RECEIPT_CONTRACT_VERSION,
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


def build_usage_receipt(
    *,
    plan_id: str,
    run_id: str,
    workspace_id: str,
    plan_fingerprint: str,
    observation: TrustedResourceUsageObservation,
) -> CloudM1UsageReceipt:
    """Bind one trusted observation to its exact Cloud M1 plan identity.

    The plan identity refs (the promoted stand-in for
    ``CloudM1ExecutionPlan`` until that contract lands in a promoted lane)
    must match the observation field-for-field; any mismatch fails closed.
    """

    plan_id = _ref(plan_id, "plan_id", code=_REF)
    run_id = _ref(run_id, "run_id", code=_REF)
    workspace_id = _ref(workspace_id, "workspace_id", code=_REF)
    plan_fingerprint = _sha256(plan_fingerprint, "plan_fingerprint", code=_REF)
    if not isinstance(observation, TrustedResourceUsageObservation):
        raise ControlPlaneContractError(_REF, "observation must be TrustedResourceUsageObservation")
    if (
        observation.plan_id != plan_id
        or observation.run_id != run_id
        or observation.workspace_id != workspace_id
        or observation.plan_fingerprint != plan_fingerprint
    ):
        raise ControlPlaneContractError(_BIND, "usage observation does not bind exact Cloud M1 execution plan")
    digest = hashlib.sha256(f"{observation.observation_id}:{plan_fingerprint}".encode("utf-8")).hexdigest()[:24]
    return CloudM1UsageReceipt(
        receipt_id=f"usage:{digest}",
        plan_id=plan_id,
        run_id=run_id,
        workspace_id=workspace_id,
        plan_fingerprint=plan_fingerprint,
        wall_time_ms=observation.wall_time_ms,
        cpu_time_ms=observation.cpu_time_ms,
        peak_memory_mib=observation.peak_memory_mib,
        disk_read_bytes=observation.disk_read_bytes,
        disk_write_bytes=observation.disk_write_bytes,
        network_egress_bytes=0,
        observed_at=observation.observed_at,
        evidence_ref=observation.evidence_ref,
    )
