"""Bounded audit/security event contract for the shared Padiem Control Plane."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from .contracts import CanonicalSubjectRef, ControlPlaneContractError


class AuditActorType(str, Enum):
    SUBJECT = "subject"
    ADMIN = "admin"
    SYSTEM = "system"


class AuditEventType(str, Enum):
    SESSION_REVOKED = "session_revoked"
    ENTITLEMENT_CHANGED = "entitlement_changed"
    USAGE_CORRECTION_RECORDED = "usage_correction_recorded"
    CONNECTOR_AUTH_CHANGED = "connector_auth_changed"
    ADMIN_CREDIT_ADJUSTMENT = "admin_credit_adjustment"
    TOOL_APPROVAL_CHANGED = "tool_approval_changed"


@dataclass(frozen=True)
class AuditEvent:
    """Immutable, secret-free audit fact with bounded semantics.

    There is intentionally no arbitrary metadata/payload map.  Sensitive
    request bodies, Provider credentials, payment credentials, prompts and
    responses do not belong in the canonical audit event contract.
    """

    event_id: str
    product_id: str
    event_type: AuditEventType
    actor_type: AuditActorType
    occurred_at: datetime
    actor_subject: CanonicalSubjectRef | None = None
    affected_subject: CanonicalSubjectRef | None = None
    correlation_id: str | None = None
    reason_code: str | None = None

    def __post_init__(self) -> None:
        if not self.event_id.strip():
            raise ControlPlaneContractError("audit event_id is required")
        if not self.product_id.strip():
            raise ControlPlaneContractError("audit product_id is required")
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ControlPlaneContractError("audit occurred_at must be timezone-aware")

        if self.actor_type is AuditActorType.SYSTEM:
            if self.actor_subject is not None:
                raise ControlPlaneContractError("system actor must not assert actor_subject")
        elif self.actor_subject is None:
            raise ControlPlaneContractError("subject/admin actor requires actor_subject")

        if self.correlation_id is not None and not self.correlation_id.strip():
            raise ControlPlaneContractError("correlation_id cannot be blank")
        if self.reason_code is not None:
            reason = self.reason_code.strip()
            if not reason:
                raise ControlPlaneContractError("reason_code cannot be blank")
            if len(reason) > 96:
                raise ControlPlaneContractError("reason_code is too long")
            if any(ch.isspace() for ch in reason):
                raise ControlPlaneContractError("reason_code must be a bounded machine code")
