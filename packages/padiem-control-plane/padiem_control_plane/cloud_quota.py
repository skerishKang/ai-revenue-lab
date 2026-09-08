"""Managed Cloud execution admission and quota guard for the Control Plane (#1484).

Promoted-lane projection of the reviewed B54 admission/quota contract
(``apps/korean-ai-code-agent/src/kagent/cloud_quota.py``). A trusted
host supplies one entitlement projection and one usage projection per
workspace; the guard evaluates whether a new cloud run may be admitted.

This module owns only the admission-decision mechanics:

- trusted entitlement projection (workspace id + entitlement ref +
  ACTIVE/DISABLED/SUSPENDED state + queue/active/daily-runtime limits +
  validity deadline),
- trusted usage projection (workspace id + usage ref + queued runs +
  active runs + daily runtime minutes + observation timestamp),
- the cloud-run admission request (request id + workspace id + run id +
  requested runtime minutes),
- the fail-closed admission decision: disabled/suspended entitlement,
  expired entitlement, stale or future usage projection, queue limit,
  active-run limit and daily-runtime limit all deny; cross-workspace
  projection mix fails closed.

It deliberately does NOT own:

- pricing, rates, money, credit balances or cost estimation — this is a
  quota/measurement gate only;
- provider credentials, raw provider payloads or runtime sandbox calls;
- existing run mutation on deny: the decision is advisory;
- entitlement or usage data acquisition: a trusted host supplies both
  projections.

No authority is ever minted from an admission decision.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import re
from typing import Any

from .contracts import ControlPlaneContractError

_ENTITLEMENT_MAX_QUEUED = 10_000
_ENTITLEMENT_MAX_ACTIVE = 1_000
_ENTITLEMENT_MAX_DAILY_MINUTES = 1_000_000
_REQUESTED_RUNTIME_MIN = 1
_REQUESTED_RUNTIME_MAX = 1_440
_MAX_USAGE_AGE_SECONDS_MIN = 1
_MAX_USAGE_AGE_SECONDS_MAX = 3_600

# Honest capability flags (ported from the reviewed contract):
# this lane performs quota/measurement projection only.
BILLING_PRICE_CREDIT_AUTHORITY = False
REAL_CONTROL_PLANE_QUOTA_CALLS = 0

_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")

_E = "invalid_entitlement_projection"
_U = "invalid_usage_projection"
_R = "invalid_admission_request"
_W = "workspace_mismatch"
_G = "invalid_guard_config"


def _id(value: str, field_name: str, *, code: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value.strip()):
        raise ControlPlaneContractError(code, f"{field_name} must be a bounded safe identifier")
    return value.strip()


def _aware(value: datetime, field_name: str, *, code: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ControlPlaneContractError(code, f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _count(value: int, field_name: str, *, maximum: int, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= maximum:
        raise ControlPlaneContractError(code, f"{field_name} must be between 0 and {maximum}")
    return value


class EntitlementState(str, Enum):
    """Lifecycle state of a workspace entitlement projection."""

    ACTIVE = "active"
    DISABLED = "disabled"
    SUSPENDED = "suspended"


class QuotaDenialReason(str, Enum):
    """Machine-readable denial reason for a cloud-run admission decision."""

    ENTITLEMENT_INACTIVE = "entitlement_inactive"
    ENTITLEMENT_STALE = "entitlement_stale"
    QUEUE_LIMIT = "queue_limit"
    ACTIVE_RUN_LIMIT = "active_run_limit"
    DAILY_RUNTIME_LIMIT = "daily_runtime_limit"


@dataclass(frozen=True, slots=True)
class ControlPlaneEntitlementProjection:
    """Server-trusted entitlement projection for one workspace.

    Carries limits and validity only — never billing or pricing data.
    """

    workspace_id: str
    entitlement_ref: str
    state: EntitlementState
    max_queued_runs: int
    max_active_runs: int
    max_daily_runtime_minutes: int
    valid_until: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "workspace_id", _id(self.workspace_id, "workspace_id", code=_E))
        object.__setattr__(self, "entitlement_ref", _id(self.entitlement_ref, "entitlement_ref", code=_E))
        if not isinstance(self.state, EntitlementState):
            try:
                object.__setattr__(self, "state", EntitlementState(self.state))
            except (TypeError, ValueError) as exc:
                raise ControlPlaneContractError(_E, "invalid entitlement state") from exc
        object.__setattr__(self, "max_queued_runs", _count(self.max_queued_runs, "max_queued_runs", maximum=_ENTITLEMENT_MAX_QUEUED, code=_E))
        object.__setattr__(self, "max_active_runs", _count(self.max_active_runs, "max_active_runs", maximum=_ENTITLEMENT_MAX_ACTIVE, code=_E))
        object.__setattr__(self, "max_daily_runtime_minutes", _count(self.max_daily_runtime_minutes, "max_daily_runtime_minutes", maximum=_ENTITLEMENT_MAX_DAILY_MINUTES, code=_E))
        object.__setattr__(self, "valid_until", _aware(self.valid_until, "valid_until", code=_E))


@dataclass(frozen=True, slots=True)
class ControlPlaneUsageProjection:
    """Server-trusted usage projection for one workspace.

    Carries bounded counters and references only — never provider
    credentials or raw provider payloads.
    """

    workspace_id: str
    usage_ref: str
    queued_runs: int
    active_runs: int
    daily_runtime_minutes: int
    observed_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "workspace_id", _id(self.workspace_id, "workspace_id", code=_U))
        object.__setattr__(self, "usage_ref", _id(self.usage_ref, "usage_ref", code=_U))
        object.__setattr__(self, "queued_runs", _count(self.queued_runs, "queued_runs", maximum=_ENTITLEMENT_MAX_QUEUED, code=_U))
        object.__setattr__(self, "active_runs", _count(self.active_runs, "active_runs", maximum=_ENTITLEMENT_MAX_ACTIVE, code=_U))
        object.__setattr__(self, "daily_runtime_minutes", _count(self.daily_runtime_minutes, "daily_runtime_minutes", maximum=_ENTITLEMENT_MAX_DAILY_MINUTES, code=_U))
        object.__setattr__(self, "observed_at", _aware(self.observed_at, "observed_at", code=_U))


@dataclass(frozen=True, slots=True)
class CloudRunAdmissionRequest:
    """One inbound request to admit a new cloud run."""

    request_id: str
    workspace_id: str
    run_id: str
    requested_runtime_minutes: int

    def __post_init__(self) -> None:
        for field_name in ("request_id", "workspace_id", "run_id"):
            object.__setattr__(self, field_name, _id(getattr(self, field_name), field_name, code=_R))
        if (
            isinstance(self.requested_runtime_minutes, bool)
            or not isinstance(self.requested_runtime_minutes, int)
            or not _REQUESTED_RUNTIME_MIN <= self.requested_runtime_minutes <= _REQUESTED_RUNTIME_MAX
        ):
            raise ControlPlaneContractError(
                _R,
                f"requested_runtime_minutes must be between {_REQUESTED_RUNTIME_MIN} and {_REQUESTED_RUNTIME_MAX}",
            )


@dataclass(frozen=True, slots=True)
class CloudRunAdmissionDecision:
    """The server-owned admission decision for one cloud-run request."""

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
            "price_or_credit_calculation": False,
            "pricing_authority": False,
            "credit_debit_authority": False,
        }


class CloudRunQuotaGuard:
    """Fail-closed admission guard over trusted entitlement + usage projections.

    The guard owns only the decision logic.  It performs no network calls,
    no database reads and no existing-run mutation on deny.
    """

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
            raise ControlPlaneContractError(_R, "request must be CloudRunAdmissionRequest")
        if not isinstance(entitlement, ControlPlaneEntitlementProjection) or not isinstance(usage, ControlPlaneUsageProjection):
            raise ControlPlaneContractError(_R, "trusted entitlement/usage projections are required")
        now = _aware(now, "now", code=_G)
        if (
            isinstance(max_usage_age_seconds, bool)
            or not isinstance(max_usage_age_seconds, int)
            or not _MAX_USAGE_AGE_SECONDS_MIN <= max_usage_age_seconds <= _MAX_USAGE_AGE_SECONDS_MAX
        ):
            raise ControlPlaneContractError(
                _G,
                f"max_usage_age_seconds must be between {_MAX_USAGE_AGE_SECONDS_MIN} and {_MAX_USAGE_AGE_SECONDS_MAX}",
            )
        if request.workspace_id != entitlement.workspace_id or request.workspace_id != usage.workspace_id:
            raise ControlPlaneContractError(_W, "quota inputs belong to different workspaces")

        reason: QuotaDenialReason | None = None
        if entitlement.state is not EntitlementState.ACTIVE:
            reason = QuotaDenialReason.ENTITLEMENT_INACTIVE
        elif (
            entitlement.valid_until < now
            or usage.observed_at > now
            or (now - usage.observed_at).total_seconds() > max_usage_age_seconds
        ):
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
