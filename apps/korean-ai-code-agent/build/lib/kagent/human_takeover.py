from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
import hashlib
import re
from typing import Any, Protocol

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


class HumanTakeoverReason(str, Enum):
    LOGIN = "login"
    MFA = "mfa"
    MANUAL_BROWSER_STEP = "manual_browser_step"


class HumanControlLeaseState(str, Enum):
    ACTIVE = "active"
    RELEASED = "released"
    EXPIRED = "expired"


class HumanTakeoverOutcome(str, Enum):
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


@dataclass(frozen=True, slots=True)
class HumanTakeoverRequest:
    request_id: str
    run_id: str
    sandbox_lease_id: str
    browser_session_ref: str
    reason: HumanTakeoverReason
    requested_at: datetime
    requested_ttl_seconds: int = 300

    def __post_init__(self) -> None:
        for field_name in ("request_id", "run_id", "sandbox_lease_id", "browser_session_ref"):
            object.__setattr__(self, field_name, _id(getattr(self, field_name), field_name))
        if not isinstance(self.reason, HumanTakeoverReason):
            try:
                object.__setattr__(self, "reason", HumanTakeoverReason(self.reason))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid takeover reason") from exc
        object.__setattr__(self, "requested_at", _aware(self.requested_at, "requested_at"))
        if isinstance(self.requested_ttl_seconds, bool) or not isinstance(self.requested_ttl_seconds, int) or not 60 <= self.requested_ttl_seconds <= 900:
            raise ContractError("requested_ttl_seconds must be between 60 and 900")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "run_id": self.run_id,
            "sandbox_lease_id": self.sandbox_lease_id,
            "browser_session_ref": self.browser_session_ref,
            "reason": self.reason.value,
            "requested_at": self.requested_at.isoformat().replace("+00:00", "Z"),
            "requested_ttl_seconds": self.requested_ttl_seconds,
            "browser_control": True,
            "shell_control": False,
            "filesystem_control": False,
            "credential_capture": False,
        }


@dataclass(frozen=True, slots=True)
class HumanControlLease:
    control_lease_id: str
    request_id: str
    run_id: str
    sandbox_lease_id: str
    browser_session_ref: str
    issued_at: datetime
    expires_at: datetime
    state: HumanControlLeaseState = HumanControlLeaseState.ACTIVE

    def __post_init__(self) -> None:
        for field_name in ("control_lease_id", "request_id", "run_id", "sandbox_lease_id", "browser_session_ref"):
            object.__setattr__(self, field_name, _id(getattr(self, field_name), field_name))
        issued = _aware(self.issued_at, "issued_at")
        expires = _aware(self.expires_at, "expires_at")
        if expires <= issued or (expires - issued).total_seconds() > 900:
            raise ContractError("human control lease lifetime must be positive and at most 900 seconds")
        object.__setattr__(self, "issued_at", issued)
        object.__setattr__(self, "expires_at", expires)
        if not isinstance(self.state, HumanControlLeaseState):
            try:
                object.__setattr__(self, "state", HumanControlLeaseState(self.state))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid human control lease state") from exc

    @property
    def active(self) -> bool:
        return self.state is HumanControlLeaseState.ACTIVE


@dataclass(frozen=True, slots=True)
class HumanTakeoverReceipt:
    receipt_id: str
    control_lease_id: str
    request_id: str
    run_id: str
    sandbox_lease_id: str
    browser_session_ref: str
    outcome: HumanTakeoverOutcome
    completed_at: datetime
    evidence_ref: str

    def __post_init__(self) -> None:
        for field_name in (
            "receipt_id",
            "control_lease_id",
            "request_id",
            "run_id",
            "sandbox_lease_id",
            "browser_session_ref",
            "evidence_ref",
        ):
            object.__setattr__(self, field_name, _id(getattr(self, field_name), field_name))
        if not isinstance(self.outcome, HumanTakeoverOutcome):
            try:
                object.__setattr__(self, "outcome", HumanTakeoverOutcome(self.outcome))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid takeover outcome") from exc
        object.__setattr__(self, "completed_at", _aware(self.completed_at, "completed_at"))

    def safe_dict(self) -> dict[str, Any]:
        return {
            "receipt_id": self.receipt_id,
            "control_lease_id": self.control_lease_id,
            "request_id": self.request_id,
            "run_id": self.run_id,
            "sandbox_lease_id": self.sandbox_lease_id,
            "browser_session_ref": self.browser_session_ref,
            "outcome": self.outcome.value,
            "completed_at": self.completed_at.isoformat().replace("+00:00", "Z"),
            "evidence_ref": self.evidence_ref,
            "credential_material_in_receipt": False,
            "browser_cookie_or_dom_in_receipt": False,
            "takeover_implies_approval": False,
            "takeover_implies_p01_resume": False,
        }


class HumanBrowserControlPort(Protocol):
    def acquire(self, request: HumanTakeoverRequest) -> HumanControlLease:
        ...

    def release(self, lease: HumanControlLease, *, outcome: HumanTakeoverOutcome, completed_at: datetime) -> HumanTakeoverReceipt:
        ...


class UnconfiguredHumanBrowserControlPort:
    def acquire(self, request: HumanTakeoverRequest) -> HumanControlLease:
        raise ContractError("human browser takeover adapter is not configured")

    def release(self, lease: HumanControlLease, *, outcome: HumanTakeoverOutcome, completed_at: datetime) -> HumanTakeoverReceipt:
        raise ContractError("human browser takeover adapter is not configured")


class DeterministicFakeHumanBrowserControlPort:
    def __init__(self) -> None:
        self._active_by_run: dict[str, HumanControlLease] = {}

    def acquire(self, request: HumanTakeoverRequest) -> HumanControlLease:
        if not isinstance(request, HumanTakeoverRequest):
            raise ContractError("request must be HumanTakeoverRequest")
        existing = self._active_by_run.get(request.run_id)
        if existing is not None and existing.active:
            raise ContractError("run already has an active human control lease")
        digest = hashlib.sha256(f"{request.run_id}:{request.request_id}:{request.browser_session_ref}".encode("utf-8")).hexdigest()[:24]
        lease = HumanControlLease(
            control_lease_id=f"human_{digest}",
            request_id=request.request_id,
            run_id=request.run_id,
            sandbox_lease_id=request.sandbox_lease_id,
            browser_session_ref=request.browser_session_ref,
            issued_at=request.requested_at,
            expires_at=request.requested_at + timedelta(seconds=request.requested_ttl_seconds),
        )
        self._active_by_run[request.run_id] = lease
        return lease

    def expire(self, *, run_id: str, now: datetime) -> HumanControlLease:
        run_id = _id(run_id, "run_id")
        now = _aware(now, "now")
        lease = self._active_by_run.get(run_id)
        if lease is None or not lease.active:
            raise ContractError("no active human control lease")
        if now < lease.expires_at:
            raise ContractError("human control lease has not expired")
        expired = HumanControlLease(
            control_lease_id=lease.control_lease_id,
            request_id=lease.request_id,
            run_id=lease.run_id,
            sandbox_lease_id=lease.sandbox_lease_id,
            browser_session_ref=lease.browser_session_ref,
            issued_at=lease.issued_at,
            expires_at=lease.expires_at,
            state=HumanControlLeaseState.EXPIRED,
        )
        self._active_by_run[run_id] = expired
        return expired

    def release(self, lease: HumanControlLease, *, outcome: HumanTakeoverOutcome, completed_at: datetime) -> HumanTakeoverReceipt:
        if not isinstance(lease, HumanControlLease) or not lease.active:
            raise ContractError("only active human control lease can be released")
        current = self._active_by_run.get(lease.run_id)
        if current != lease:
            raise ContractError("human control lease is stale or unknown")
        completed = _aware(completed_at, "completed_at")
        if completed < lease.issued_at or completed > lease.expires_at:
            raise ContractError("completion time must fall within active control lease")
        if not isinstance(outcome, HumanTakeoverOutcome) or outcome is HumanTakeoverOutcome.EXPIRED:
            raise ContractError("release outcome must be completed or cancelled")
        released = HumanControlLease(
            control_lease_id=lease.control_lease_id,
            request_id=lease.request_id,
            run_id=lease.run_id,
            sandbox_lease_id=lease.sandbox_lease_id,
            browser_session_ref=lease.browser_session_ref,
            issued_at=lease.issued_at,
            expires_at=lease.expires_at,
            state=HumanControlLeaseState.RELEASED,
        )
        self._active_by_run[lease.run_id] = released
        receipt_digest = hashlib.sha256(f"{lease.control_lease_id}:{outcome.value}:{completed.isoformat()}".encode("utf-8")).hexdigest()[:24]
        return HumanTakeoverReceipt(
            receipt_id=f"takeover_{receipt_digest}",
            control_lease_id=lease.control_lease_id,
            request_id=lease.request_id,
            run_id=lease.run_id,
            sandbox_lease_id=lease.sandbox_lease_id,
            browser_session_ref=lease.browser_session_ref,
            outcome=outcome,
            completed_at=completed,
            evidence_ref=f"human_takeover:{receipt_digest}",
        )


REAL_BROWSER_TAKEOVER_PROVIDER_CONFIGURED = False
TAKEOVER_IMPLIES_APPROVAL = False
TAKEOVER_IMPLIES_P01_RESUME = False
SHELL_CONTROL_SUPPORTED = False
FILESYSTEM_CONTROL_SUPPORTED = False
