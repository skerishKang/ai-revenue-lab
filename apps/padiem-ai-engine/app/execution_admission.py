"""Trusted execution admission contract for Padiem AI Engine.

This module defines the server-side admission seam used by Engine orchestration
before executing privileged Core work. It deliberately does not parse or trust
client-supplied entitlement, plan, quota, credit, or allow fields.

The contract is product-neutral: Control Plane or another trusted server adapter
may issue an admission decision, while the Engine only validates that the
trusted decision matches the requested app/subject/capability and is still
fresh. Service identity remains a separate boundary from entitlement authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Protocol

_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,127}$")
_CAPABILITY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class ExecutionAdmissionError(ValueError):
    """Fail-closed trusted admission validation error."""

    def __init__(self, code: str, safe_message: str, *, status_code: int = 403) -> None:
        super().__init__(safe_message)
        if not isinstance(code, str) or not _CAPABILITY_RE.fullmatch(code):
            raise ValueError("admission error code must be a bounded safe identifier")
        self.code = code
        self.safe_message = safe_message
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class ExecutionAdmissionRequest:
    """Server-constructed admission query for one Engine capability."""

    app_id: str
    subject_id: str | None
    capability: str
    trace_id: str | None = None
    request_fingerprint: str | None = None

    def __post_init__(self) -> None:
        _require_safe_id(self.app_id, "app_id")
        if self.subject_id is not None:
            _require_safe_id(self.subject_id, "subject_id")
        _require_capability(self.capability, "capability")
        if self.trace_id is not None:
            _require_safe_id(self.trace_id, "trace_id")
        if self.request_fingerprint is not None:
            _require_safe_id(self.request_fingerprint, "request_fingerprint")


@dataclass(frozen=True, slots=True)
class TrustedExecutionAdmission:
    """Trusted server-side admission decision.

    This is not a wire object. Browser/client JSON must never be coerced into
    this type. It is produced by a server-owned adapter after checking trusted
    entitlement/admission authority.
    """

    decision_id: str
    app_id: str
    subject_id: str | None
    capability: str
    allowed: bool
    authority_ref: str
    policy_revision: str
    issued_at: datetime
    expires_at: datetime
    request_fingerprint: str | None = None

    def __post_init__(self) -> None:
        _require_safe_id(self.decision_id, "decision_id")
        _require_safe_id(self.app_id, "app_id")
        if self.subject_id is not None:
            _require_safe_id(self.subject_id, "subject_id")
        _require_capability(self.capability, "capability")
        if not isinstance(self.allowed, bool):
            raise ExecutionAdmissionError("invalid_admission", "admission allowed must be explicit.")
        _require_safe_id(self.authority_ref, "authority_ref")
        _require_safe_id(self.policy_revision, "policy_revision")
        _require_timestamp(self.issued_at, "issued_at")
        _require_timestamp(self.expires_at, "expires_at")
        if self.expires_at <= self.issued_at:
            raise ExecutionAdmissionError("invalid_admission", "admission expiry must be after issuance.")
        if self.request_fingerprint is not None:
            _require_safe_id(self.request_fingerprint, "request_fingerprint")


class ExecutionAdmissionAdapter(Protocol):
    """Trusted server adapter that resolves execution admission."""

    def resolve_admission(self, request: ExecutionAdmissionRequest) -> TrustedExecutionAdmission: ...


def require_trusted_admission(
    *,
    request: ExecutionAdmissionRequest,
    admission: TrustedExecutionAdmission | None,
    now: datetime | None = None,
) -> TrustedExecutionAdmission:
    """Validate that a trusted admission decision authorizes the request.

    Missing, denied, stale, mismatched, or client-shaped values fail closed.
    """

    if not isinstance(request, ExecutionAdmissionRequest):
        raise ExecutionAdmissionError("invalid_admission_request", "execution admission request is invalid.")
    if not isinstance(admission, TrustedExecutionAdmission):
        raise ExecutionAdmissionError("missing_entitlement", "Trusted execution admission is required.")
    current = now or datetime.now(timezone.utc)
    _require_timestamp(current, "now")

    if not admission.allowed:
        raise ExecutionAdmissionError("entitlement_denied", "Trusted execution admission denied the request.")
    if admission.expires_at <= current:
        raise ExecutionAdmissionError("entitlement_expired", "Trusted execution admission is expired.")
    if admission.issued_at > current:
        raise ExecutionAdmissionError("invalid_admission", "Trusted execution admission is from the future.")
    if admission.app_id != request.app_id:
        raise ExecutionAdmissionError("entitlement_app_mismatch", "Trusted execution admission app does not match.")
    if admission.subject_id != request.subject_id:
        raise ExecutionAdmissionError("entitlement_subject_mismatch", "Trusted execution admission subject does not match.")
    if admission.capability != request.capability:
        raise ExecutionAdmissionError(
            "entitlement_capability_mismatch",
            "Trusted execution admission capability does not match.",
        )
    if admission.request_fingerprint is not None and request.request_fingerprint != admission.request_fingerprint:
        raise ExecutionAdmissionError(
            "entitlement_request_mismatch",
            "Trusted execution admission request identity does not match.",
        )
    return admission


def _require_safe_id(value: str, name: str) -> None:
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value):
        raise ExecutionAdmissionError("invalid_admission", f"{name} must be a bounded safe identifier.")


def _require_capability(value: str, name: str) -> None:
    if not isinstance(value, str) or not _CAPABILITY_RE.fullmatch(value):
        raise ExecutionAdmissionError("invalid_admission", f"{name} must be a bounded capability identifier.")


def _require_timestamp(value: datetime, name: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ExecutionAdmissionError("invalid_admission", f"{name} must be timezone-aware.")
