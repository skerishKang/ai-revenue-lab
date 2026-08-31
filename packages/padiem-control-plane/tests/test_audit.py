from datetime import datetime, timezone

import pytest

from padiem_control_plane.audit import AuditActorType, AuditEvent, AuditEventType
from padiem_control_plane.contracts import (
    CanonicalSubjectRef,
    ControlPlaneContractError,
    SubjectType,
)


NOW = datetime(2026, 8, 30, 12, 30, tzinfo=timezone.utc)
SUBJECT = CanonicalSubjectRef(
    subject_type=SubjectType.USER,
    subject_id="sub_test_123",
)


def test_system_actor_cannot_assert_actor_subject() -> None:
    with pytest.raises(ControlPlaneContractError):
        AuditEvent(
            event_id="aud_1",
            product_id="b62",
            event_type=AuditEventType.ENTITLEMENT_CHANGED,
            actor_type=AuditActorType.SYSTEM,
            actor_subject=SUBJECT,
            affected_subject=SUBJECT,
            occurred_at=NOW,
        )


def test_subject_actor_requires_actor_subject() -> None:
    with pytest.raises(ControlPlaneContractError):
        AuditEvent(
            event_id="aud_2",
            product_id="b62",
            event_type=AuditEventType.SESSION_REVOKED,
            actor_type=AuditActorType.SUBJECT,
            occurred_at=NOW,
        )


def test_admin_actor_requires_actor_subject() -> None:
    with pytest.raises(ControlPlaneContractError):
        AuditEvent(
            event_id="aud_3",
            product_id="b14",
            event_type=AuditEventType.ADMIN_CREDIT_ADJUSTMENT,
            actor_type=AuditActorType.ADMIN,
            affected_subject=SUBJECT,
            occurred_at=NOW,
        )


def test_reason_code_is_bounded_machine_code() -> None:
    with pytest.raises(ControlPlaneContractError):
        AuditEvent(
            event_id="aud_4",
            product_id="b62",
            event_type=AuditEventType.TOOL_APPROVAL_CHANGED,
            actor_type=AuditActorType.SYSTEM,
            affected_subject=SUBJECT,
            occurred_at=NOW,
            reason_code="contains human prose",
        )


def test_naive_timestamp_fails_closed() -> None:
    with pytest.raises(ControlPlaneContractError):
        AuditEvent(
            event_id="aud_5",
            product_id="b62",
            event_type=AuditEventType.CONNECTOR_AUTH_CHANGED,
            actor_type=AuditActorType.SYSTEM,
            occurred_at=datetime(2026, 8, 30, 12, 30),
        )


def test_valid_system_audit_event_contains_no_arbitrary_payload() -> None:
    event = AuditEvent(
        event_id="aud_6",
        product_id="b62",
        event_type=AuditEventType.ENTITLEMENT_CHANGED,
        actor_type=AuditActorType.SYSTEM,
        affected_subject=SUBJECT,
        occurred_at=NOW,
        correlation_id="exec_123",
        reason_code="ENTITLEMENT_RECALCULATED",
    )
    assert event.actor_subject is None
    assert not hasattr(event, "metadata")
    assert not hasattr(event, "payload")
