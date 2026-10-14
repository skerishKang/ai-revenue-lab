from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import re
from typing import Any

from .contracts import ContractError


_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")


def _id(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value.strip()):
        raise ContractError(f"{field_name} must be a bounded safe identifier")
    return value.strip()


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ContractError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _count(value: int, field_name: str, *, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= maximum:
        raise ContractError(f"{field_name} must be between 0 and {maximum}")
    return value


class EntitlementState(str, Enum):
    ACTIVE = "active"
    DISABLED = "disabled"
    SUSPENDED = "suspended"


class QuotaDenialReason(str, Enum):
    ENTITLEMENT_INACTIVE = "entitlement_inactive"
    ENTITLEMENT_STALE = "entitlement_stale"
    QUEUE_LIMIT = "queue_limit"
    ACTIVE_RUN_LIMIT = "active_run_limit"
    DAILY_RUNTIME_LIMIT = "daily_runtime_limit"


@dataclass(frozen=True, slots=True)
class ControlPlaneEntitlementProjection:
    workspace_id: str
    entitlement_ref: str
    state: EntitlementState
    max_queued_runs: int
    max_active_runs: int
    max_daily_runtime_minutes: int
    valid_until: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "workspace_id", _id(self.workspace_id, "workspace_id"))
        object.__setattr__(self, "entitlement_ref", _id(self.entitlement_ref, "entitlement_ref"))
        if not isinstance(self.state, EntitlementState):
            try:
                object.__setattr__(self, "state", EntitlementState(self.state))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid entitlement state") from exc
        object.__setattr__(self, "max_queued_runs", _count(self.max_queued_runs, "max_queued_runs", maximum=10000))
        object.__setattr__(self, "max_active_runs", _count(self.max_active_runs, "max_active_runs", maximum=1000))
        object.__setattr__(self, "max_daily_runtime_minutes", _count(self.max_daily_runtime_minutes, "max_daily_runtime_minutes", maximum=1_000_000))
        object.__setattr__(self, "valid_until", _aware(self.valid_until, "valid_until"))


@dataclass(frozen=True, slots=True)
class ControlPlaneUsageProjection:
    workspace_id: str
    usage_ref: str
    queued_runs: int
    active_runs: int
    daily_runtime_minutes: int
    observed_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "workspace_id", _id(self.workspace_id, "workspace_id"))
        object.__setattr__(self, "usage_ref", _id(self.usage_ref, "usage_ref"))
        object.__setattr__(self, "queued_runs", _count(self.queued_runs, "queued_runs", maximum=10000))
        object.__setattr__(self, "active_runs", _count(self.active_runs, "active_runs", maximum=1000))
        object.__setattr__(self, "daily_runtime_minutes", _count(self.daily_runtime_minutes, "daily_runtime_minutes", maximum=1_000_000))
        object.__setattr__(self, "observed_at", _aware(self.observed_at, "observed_at"))


@dataclass(frozen=True, slots=True)
class CloudRunAdmissionRequest:
    request_id: str
    workspace_id: str
    run_id: str
    requested_runtime_minutes: int

    def __post_init__(self) -> None:
        for field_name in ("request_id", "workspace_id", "run_id"):
            object.__setattr__(self, field_name, _id(getattr(self, field_name), field_name))
        if isinstance(self.requested_runtime_minutes, bool) or not isinstance(self.requested_runtime_minutes, int) or not 1 <= self.requested_runtime_minutes <= 1440:
            raise ContractError("requested_runtime_minutes must be between 1 and 1440")


@dataclass(frozen=True, slots=True)
class CloudRunAdmissionDecision:
    request_id: str
    workspace_id: str
    run_id: str
    allowed: bool
    denial_reason: QuotaDenialReason | None
    entitlement_ref: str
    usage_ref: str

    def safe_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "workspace_id": self.workspace_id,
            "run_id": self.run_id,
            "allowed": self.allowed,
            "denial_reason": self.denial_reason.value if self.denial_reason else None,
            "entitlement_ref": self.entitlement_ref,
            "usage_ref": self.usage_ref,
            "billing_authority": "control_plane",
            "price_or_credit_calculation_in_b54": False,
        }


class CloudRunQuotaGuard:
    def evaluate(
        self,
        *,
        request: CloudRunAdmissionRequest,
        entitlement: ControlPlaneEntitlementProjection,
        usage: ControlPlaneUsageProjection,
        now: datetime,
        max_usage_age_seconds: int = 300,
    ) -> CloudRunAdmissionDecision:
        if not isinstance(request, CloudRunAdmissionRequest):
            raise ContractError("request must be CloudRunAdmissionRequest")
        if not isinstance(entitlement, ControlPlaneEntitlementProjection) or not isinstance(usage, ControlPlaneUsageProjection):
            raise ContractError("trusted entitlement/usage projections are required")
        now = _aware(now, "now")
        if isinstance(max_usage_age_seconds, bool) or not isinstance(max_usage_age_seconds, int) or not 1 <= max_usage_age_seconds <= 3600:
            raise ContractError("max_usage_age_seconds must be between 1 and 3600")
        if request.workspace_id != entitlement.workspace_id or request.workspace_id != usage.workspace_id:
            raise ContractError("quota inputs belong to different workspaces")

        reason: QuotaDenialReason | None = None
        if entitlement.state is not EntitlementState.ACTIVE:
            reason = QuotaDenialReason.ENTITLEMENT_INACTIVE
        elif entitlement.valid_until < now or usage.observed_at > now or (now - usage.observed_at).total_seconds() > max_usage_age_seconds:
            reason = QuotaDenialReason.ENTITLEMENT_STALE
        elif usage.queued_runs >= entitlement.max_queued_runs:
            reason = QuotaDenialReason.QUEUE_LIMIT
        elif usage.active_runs >= entitlement.max_active_runs:
            reason = QuotaDenialReason.ACTIVE_RUN_LIMIT
        elif usage.daily_runtime_minutes + request.requested_runtime_minutes > entitlement.max_daily_runtime_minutes:
            reason = QuotaDenialReason.DAILY_RUNTIME_LIMIT

        return CloudRunAdmissionDecision(
            request_id=request.request_id,
            workspace_id=request.workspace_id,
            run_id=request.run_id,
            allowed=reason is None,
            denial_reason=reason,
            entitlement_ref=entitlement.entitlement_ref,
            usage_ref=usage.usage_ref,
        )


REAL_CONTROL_PLANE_QUOTA_CALLS = 0
BILLING_AUTHORITY_IN_B54 = False
