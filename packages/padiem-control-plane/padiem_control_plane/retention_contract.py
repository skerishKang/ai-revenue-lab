"""Server-owned retention and deletion contracts for the Control Plane.

Retention policy is defined before any live data is imported.  Every
retained data class carries an explicit TTL.  A legal-hold reference
suspends delete-due dispositions; when active, deletion eligibility
is always ``False`` regardless of the TTL deadline.

This module contains no real storage mutation.  Deletion receipts
record the content SHA-256 digest and a safe reference — never the
original body or model/client metadata.

Design principles:
    RETENTION_DEFINED_BEFORE_LIVE_DATA = YES
    RAW_CONTENT_TTL = EXPLICIT
    LEGAL_HOLD_FAILS_SAFE = YES
    MODEL_SET_RETENTION = NO
    DELETION_RECEIPT = YES
    DELETED_CONTENT_IN_RECEIPT = NO
    REAL_STORAGE_DELETE = NO
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
import hashlib
import re

from .contracts import ControlPlaneContractError


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MIN_RETENTION_TTL_SECONDS = 1
MAX_RETENTION_TTL_SECONDS = 31_536_000  # 365 days

_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,255}$")
_POLICY_VERSION_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")

_FORBIDDEN_OWNER_TERMS = (
    "model",
    "client",
    "user",
    "partner",
    "design_partner",
)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class RetentionDecision(str, Enum):
    """Outcome of evaluating a resource against its retention policy."""

    ACTIVE = "active"
    DELETE_DUE = "delete_due"
    LEGAL_HOLD = "legal_hold"


class RetentionDataClass(str, Enum):
    """Initial data classes from issue #1570.

    Each class represents a distinct kind of live data whose retention
    TTL must be defined before that data is imported.
    """

    INBOUND_MESSAGE_BODY = "inbound_message_body"
    SOURCE_DOCUMENT = "source_document"
    EXTRACTED_CANDIDATE = "extracted_candidate"
    BUSINESS_RECORD = "business_record"
    RENDERED_ARTIFACT = "rendered_artifact"
    PRODUCT_EVIDENCE_PROJECTION = "product_evidence_projection"
    PILOT_AGGREGATE = "pilot_aggregate"


class RetentionPurpose(str, Enum):
    """Bounded server-owned reason for retaining a data class.

    Model/client callers must never supply or override this value;
    the Control Plane determines purpose at policy-authoring time.
    """

    SERVICE_DELIVERY = "service_delivery"
    REGULATORY_COMPLIANCE = "regulatory_compliance"
    AUDIT_EVIDENCE = "audit_evidence"
    LEGAL_PRESERVATION = "legal_preservation"


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RetentionPolicy:
    """A server-owned retention TTL for a specific data class and purpose.

    ``owner`` must be a server-actor identifier; model/client/partner
    identifiers are rejected at construction time.  ``purpose`` is a
    bounded server-owned enum; model/client callers must never supply
    or override it.
    """

    data_class: RetentionDataClass
    purpose: RetentionPurpose
    ttl_seconds: int
    owner: str
    policy_version: str

    def __post_init__(self) -> None:
        if not isinstance(self.data_class, RetentionDataClass):
            raise ControlPlaneContractError(
                "invalid_retention_policy",
                "data_class must be a RetentionDataClass member",
            )
        if not isinstance(self.purpose, RetentionPurpose):
            raise ControlPlaneContractError(
                "invalid_retention_policy",
                "purpose must be a RetentionPurpose member",
            )
        if (
            isinstance(self.ttl_seconds, bool)
            or not isinstance(self.ttl_seconds, int)
            or not MIN_RETENTION_TTL_SECONDS <= self.ttl_seconds <= MAX_RETENTION_TTL_SECONDS
        ):
            raise ControlPlaneContractError(
                "invalid_retention_policy",
                f"ttl_seconds must be an integer between "
                f"{MIN_RETENTION_TTL_SECONDS} and {MAX_RETENTION_TTL_SECONDS}",
            )
        if not isinstance(self.owner, str) or not self.owner.strip():
            raise ControlPlaneContractError(
                "invalid_retention_policy",
                "owner must be a non-empty string",
            )
        owner_lower = self.owner.lower()
        if any(term in owner_lower for term in _FORBIDDEN_OWNER_TERMS):
            raise ControlPlaneContractError(
                "invalid_retention_policy",
                "retention owner must not be a model/client/partner identifier",
            )
        if not isinstance(self.policy_version, str) or not _POLICY_VERSION_RE.fullmatch(
            self.policy_version
        ):
            raise ControlPlaneContractError(
                "invalid_retention_policy",
                "policy_version must match ^[a-z][a-z0-9_]{0,63}$",
            )


# ---------------------------------------------------------------------------
# Legal hold
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LegalHold:
    """A reference that prevents deletion of associated resources.

    When any legal hold is active for a resource, the deletion
    eligibility check fails safe: ``LegalHoldActive`` is returned
    regardless of whether the retention TTL has expired.
    """

    hold_ref: str
    reason: str
    issued_at: datetime

    def __post_init__(self) -> None:
        if not _SAFE_REF_RE.fullmatch(self.hold_ref):
            raise ControlPlaneContractError(
                "invalid_legal_hold",
                "hold_ref must be a safe identifier (^[A-Za-z0-9][A-Za-z0-9._:/@+\\-]{0,255}$)",
            )
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ControlPlaneContractError(
                "invalid_legal_hold",
                "reason must be a non-empty string",
            )
        if self.issued_at.tzinfo is None or self.issued_at.tzinfo.utcoffset(self.issued_at) is None:
            raise ControlPlaneContractError(
                "invalid_legal_hold",
                "issued_at must be timezone-aware",
            )


# ---------------------------------------------------------------------------
# Eligibility
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DeletionEligibility:
    """Input to the deletion-eligibility evaluation."""

    resource_ref: str
    resource_type: str
    created_at: datetime
    policy: RetentionPolicy
    legal_holds: tuple[LegalHold, ...]
    check_deadline: datetime

    def __post_init__(self) -> None:
        if not _SAFE_REF_RE.fullmatch(self.resource_ref):
            raise ControlPlaneContractError(
                "invalid_deletion_eligibility",
                "resource_ref must be a safe identifier",
            )
        if not isinstance(self.resource_type, str) or not self.resource_type.strip():
            raise ControlPlaneContractError(
                "invalid_deletion_eligibility",
                "resource_type must be a non-empty string",
            )
        if self.created_at.tzinfo is None or self.created_at.tzinfo.utcoffset(self.created_at) is None:
            raise ControlPlaneContractError(
                "invalid_deletion_eligibility",
                "created_at must be timezone-aware",
            )
        if self.check_deadline.tzinfo is None or self.check_deadline.tzinfo.utcoffset(self.check_deadline) is None:
            raise ControlPlaneContractError(
                "invalid_deletion_eligibility",
                "check_deadline must be timezone-aware",
            )
        for hold in self.legal_holds:
            if not isinstance(hold, LegalHold):
                raise ControlPlaneContractError(
                    "invalid_deletion_eligibility",
                    "every legal_hold must be a LegalHold instance",
                )


@dataclass(frozen=True, slots=True)
class EligibilityResult:
    """The evaluated deletion-eligibility decision."""

    decision: RetentionDecision
    resource_ref: str
    deadline: datetime | None
    active_hold_ref: str | None


# ---------------------------------------------------------------------------
# Deletion receipt
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DeletionReceipt:
    """A safe record of a completed deletion decision.

    Contains only the content SHA-256 digest and a resource reference.
    The original body, model metadata, and client metadata are never
    stored in the receipt.
    """

    deletion_id: str
    resource_ref: str
    resource_type: str
    policy_ref: str
    legal_hold_ref: str | None
    deleted_at: datetime
    content_sha256: str
    decision: RetentionDecision

    def __post_init__(self) -> None:
        if not _SAFE_REF_RE.fullmatch(self.deletion_id):
            raise ControlPlaneContractError(
                "invalid_deletion_receipt",
                "deletion_id must be a safe identifier",
            )
        if not _SAFE_REF_RE.fullmatch(self.resource_ref):
            raise ControlPlaneContractError(
                "invalid_deletion_receipt",
                "resource_ref must be a safe identifier",
            )
        if not isinstance(self.resource_type, str) or not self.resource_type.strip():
            raise ControlPlaneContractError(
                "invalid_deletion_receipt",
                "resource_type must be a non-empty string",
            )
        if not _SAFE_REF_RE.fullmatch(self.policy_ref):
            raise ControlPlaneContractError(
                "invalid_deletion_receipt",
                "policy_ref must be a safe identifier",
            )
        if self.legal_hold_ref is not None and not _SAFE_REF_RE.fullmatch(self.legal_hold_ref):
            raise ControlPlaneContractError(
                "invalid_deletion_receipt",
                "legal_hold_ref must be a safe identifier or None",
            )
        if self.deleted_at.tzinfo is None or self.deleted_at.tzinfo.utcoffset(self.deleted_at) is None:
            raise ControlPlaneContractError(
                "invalid_deletion_receipt",
                "deleted_at must be timezone-aware",
            )
        if not isinstance(self.content_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", self.content_sha256):
            raise ControlPlaneContractError(
                "invalid_deletion_receipt",
                "content_sha256 must be a 64-char lowercase hex SHA-256 digest",
            )
        if self.decision is not RetentionDecision.DELETE_DUE:
            raise ControlPlaneContractError(
                "invalid_deletion_receipt",
                "deletion receipt requires DELETE_DUE decision",
            )


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------


def evaluate_deletion_eligibility(eligibility: DeletionEligibility) -> EligibilityResult:
    """Determine whether a resource is eligible for deletion.

    Fails safe: if any legal hold is active, ``LEGAL_HOLD`` is returned
    regardless of the TTL deadline.  ``DELETE_DUE`` requires a
    timezone-aware ``check_deadline`` at or past the retention deadline.
    """
    deadline = eligibility.created_at + timedelta(seconds=eligibility.policy.ttl_seconds)

    if eligibility.legal_holds:
        most_recent = max(eligibility.legal_holds, key=lambda h: h.issued_at)
        return EligibilityResult(
            decision=RetentionDecision.LEGAL_HOLD,
            resource_ref=eligibility.resource_ref,
            deadline=None,
            active_hold_ref=most_recent.hold_ref,
        )

    if eligibility.check_deadline >= deadline:
        return EligibilityResult(
            decision=RetentionDecision.DELETE_DUE,
            resource_ref=eligibility.resource_ref,
            deadline=deadline,
            active_hold_ref=None,
        )

    return EligibilityResult(
        decision=RetentionDecision.ACTIVE,
        resource_ref=eligibility.resource_ref,
        deadline=deadline,
        active_hold_ref=None,
    )


def build_deletion_receipt(
    *,
    deletion_id: str,
    eligibility: DeletionEligibility,
    result: EligibilityResult,
    deleted_at: datetime,
    content_bytes: bytes,
) -> DeletionReceipt:
    """Build a deletion receipt from a ``DELETE_DUE`` eligibility result.

    ``content_bytes`` is hashed and the digest recorded; the original
    content is never stored in the receipt.
    """
    if result.decision is not RetentionDecision.DELETE_DUE:
        raise ControlPlaneContractError(
            "invalid_deletion_receipt",
            "receipt requires DELETE_DUE eligibility result",
        )
    if deleted_at.tzinfo is None or deleted_at.tzinfo.utcoffset(deleted_at) is None:
        raise ControlPlaneContractError(
            "invalid_deletion_receipt",
            "deleted_at must be timezone-aware",
        )
    if not isinstance(content_bytes, bytes):
        raise ControlPlaneContractError(
            "invalid_deletion_receipt",
            "content_bytes must be bytes",
        )

    return DeletionReceipt(
        deletion_id=deletion_id,
        resource_ref=eligibility.resource_ref,
        resource_type=eligibility.resource_type,
        policy_ref=f"{eligibility.policy.data_class.value}:{eligibility.policy.purpose.value}:{eligibility.policy.policy_version}",
        legal_hold_ref=result.active_hold_ref,
        deleted_at=deleted_at,
        content_sha256=hashlib.sha256(content_bytes).hexdigest(),
        decision=result.decision,
    )


def validate_retention_policy(policy: RetentionPolicy) -> RetentionPolicy:
    """Pass-through validation; raises on construction failure."""
    if not isinstance(policy, RetentionPolicy):
        raise ControlPlaneContractError(
            "invalid_retention_policy",
            "expected a RetentionPolicy instance",
        )
    return policy


def validate_legal_hold(hold: LegalHold) -> LegalHold:
    """Pass-through validation; raises on construction failure."""
    if not isinstance(hold, LegalHold):
        raise ControlPlaneContractError(
            "invalid_legal_hold",
            "expected a LegalHold instance",
        )
    return hold
