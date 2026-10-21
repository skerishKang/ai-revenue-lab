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
from types import MappingProxyType
from typing import Mapping, Protocol

_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,127}$")
_CAPABILITY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

# #5015 (F-032): the Engine carries two product vocabularies and must not
# conflate them.
#
# * The EXECUTION app id is the Engine's own app/caller identity. The caller
#   registry authorizes it (``allowed_app_ids``) and the Engine admission binds
#   it (``admission.app_id``). The Chat product executes as ``padiem-chat``.
# * The PERMISSION product id is the Control Plane entitlement/usage product.
#   The Control Plane resolves a session, a grant and a usage reservation for
#   it. The Chat product's existing permission semantics are the ``b62``
#   product, and the Claw product's are ``b54-padiem-claw``.
#
# The two vocabularies are connected by this server-owned, closed mapping so
# the snapshot, the admission, the usage reservation and the usage receipt all
# name the same permission product for the same execution. The mapping is not
# a permission list: an app id without an entry keeps its own id as the
# permission product, so every other path is still decided by the Control
# Plane's own product-eligibility check exactly as before.
ENGINE_EXECUTION_APP_PERMISSION_PRODUCT_IDS: Mapping[str, str] = MappingProxyType(
    {
        "padiem-chat": "b62",
        "b54-padiem-claw": "b54-padiem-claw",
    }
)


def permission_product_id_for_execution_app(app_id: str) -> str:
    """The Control Plane permission product id of one execution app id.

    The app id is a validated bounded identifier at every call site (the
    admission request, the trusted admission and the persisted evidence), so an
    app id without a mapping entry simply keeps its own id and stays subject
    to the Control Plane's own product-eligibility check.
    """
    return ENGINE_EXECUTION_APP_PERMISSION_PRODUCT_IDS.get(app_id, app_id)


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
    usage_reservation_identity: str | None = None

    def __post_init__(self) -> None:
        _require_safe_id(self.app_id, "app_id")
        if self.subject_id is not None:
            _require_safe_id(self.subject_id, "subject_id")
        _require_capability(self.capability, "capability")
        if self.trace_id is not None:
            _require_safe_id(self.trace_id, "trace_id")
        if self.request_fingerprint is not None:
            _require_safe_id(self.request_fingerprint, "request_fingerprint")
        if self.usage_reservation_identity is not None:
            _require_safe_id(self.usage_reservation_identity, "usage_reservation_identity")


@dataclass(frozen=True, slots=True)
class TrustedUsageReservation:
    """Typed server-only evidence for one admitted Control Plane usage reservation."""

    reservation_ref: str
    idempotency_key: str
    billing_semantic_id: str
    product_id: str
    subject_type: str
    subject_id: str
    request_fingerprint: str
    reserved_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        _require_safe_id(self.reservation_ref, "reservation_ref")
        _require_safe_id(self.idempotency_key, "idempotency_key")
        _require_capability(self.billing_semantic_id, "billing_semantic_id")
        _require_safe_id(self.product_id, "product_id")
        if self.subject_type not in {"user", "account"}:
            raise ExecutionAdmissionError("invalid_admission", "usage reservation subject type is invalid.")
        _require_safe_id(self.subject_id, "usage reservation subject_id")
        if not isinstance(self.request_fingerprint, str) or not _SHA256_RE.fullmatch(self.request_fingerprint):
            raise ExecutionAdmissionError("invalid_admission", "usage reservation request_fingerprint must be lowercase SHA-256.")
        _require_timestamp(self.reserved_at, "reserved_at")
        _require_timestamp(self.expires_at, "usage reservation expires_at")
        if self.expires_at <= self.reserved_at:
            raise ExecutionAdmissionError("invalid_admission", "usage reservation expiry must be after reservation time.")


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
    usage_reservation: TrustedUsageReservation | None = None
    # #5015 (F-032): the Control Plane permission product this decision was
    # granted under. It is derived from the execution app id by the server-owned
    # mapping, never from the request, so the admission, the usage reservation
    # and the usage receipt all name one permission product for one execution.
    permission_product_id: str | None = None

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
        expected_permission_product = permission_product_id_for_execution_app(self.app_id)
        if self.permission_product_id is None:
            object.__setattr__(self, "permission_product_id", expected_permission_product)
        elif self.permission_product_id != expected_permission_product:
            # The permission product is derived from the execution app id by the
            # server-owned mapping. It is not a free field, so an admission that
            # names another product is refused here — at the only place every
            # later consumer (the gate, the persisted evidence, the usage
            # reservation and the usage receipt) reads it from.
            raise ExecutionAdmissionError(
                "invalid_admission",
                "admission permission product does not match the execution app.",
            )
        _require_safe_id(self.permission_product_id, "permission_product_id")
        reservation = self.usage_reservation
        if reservation is not None:
            if not isinstance(reservation, TrustedUsageReservation):
                raise ExecutionAdmissionError("invalid_admission", "usage reservation evidence is invalid.")
            if not self.allowed:
                raise ExecutionAdmissionError("invalid_admission", "denied admission cannot carry usage reservation evidence.")
            if (
                reservation.product_id != self.permission_product_id
                or reservation.billing_semantic_id != self.capability
            ):
                raise ExecutionAdmissionError("invalid_admission", "usage reservation scope does not match admission.")
            if reservation.request_fingerprint != self.request_fingerprint:
                raise ExecutionAdmissionError("invalid_admission", "usage reservation request identity does not match admission.")
            expected_subject_type = "user" if self.subject_id is not None else "account"
            expected_subject_id = self.subject_id if self.subject_id is not None else self.permission_product_id
            if reservation.subject_type != expected_subject_type or reservation.subject_id != expected_subject_id:
                raise ExecutionAdmissionError("invalid_admission", "usage reservation subject does not match admission.")


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
