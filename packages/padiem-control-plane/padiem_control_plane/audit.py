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


def _audit_error(code: str, message: str) -> ControlPlaneContractError:
    return ControlPlaneContractError(code, message)


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """Immutable, secret-free audit fact with bounded semantics.

    There is intentionally no arbitrary metadata/payload map. Sensitive
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
        if not isinstance(self.event_type, AuditEventType):
            raise _audit_error("invalid_audit_event", "event_type must be AuditEventType")
        if not isinstance(self.actor_type, AuditActorType):
            raise _audit_error("invalid_audit_actor", "actor_type must be AuditActorType")
        if not isinstance(self.event_id, str) or not self.event_id.strip():
            raise _audit_error("invalid_audit_event", "audit event_id is required")
        if not isinstance(self.product_id, str) or not self.product_id.strip():
            raise _audit_error("invalid_audit_event", "audit product_id is required")
        if not isinstance(self.occurred_at, datetime) or self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise _audit_error("invalid_timestamp", "audit occurred_at must be timezone-aware")

        if self.actor_type is AuditActorType.SYSTEM:
            if self.actor_subject is not None:
                raise _audit_error(
                    "invalid_audit_actor",
                    "system actor must not assert actor_subject",
                )
        elif self.actor_subject is None:
            raise _audit_error(
                "invalid_audit_actor",
                "subject/admin actor requires actor_subject",
            )

        if self.correlation_id is not None:
            if not isinstance(self.correlation_id, str) or not self.correlation_id.strip():
                raise _audit_error(
                    "invalid_audit_event",
                    "correlation_id cannot be blank",
                )
        if self.reason_code is not None:
            if not isinstance(self.reason_code, str):
                raise _audit_error(
                    "invalid_audit_event",
                    "reason_code must be a string",
                )
            reason = self.reason_code.strip()
            if not reason:
                raise _audit_error("invalid_audit_event", "reason_code cannot be blank")
            if len(reason) > 96:
                raise _audit_error("invalid_audit_event", "reason_code is too long")
            if any(ch.isspace() for ch in reason):
                raise _audit_error(
                    "invalid_audit_event",
                    "reason_code must be a bounded machine code",
                )
