from datetime import datetime, timedelta, timezone

import pytest

from padiem_control_plane.contracts import (
    CanonicalSubjectRef,
    ControlPlaneContractError,
    SubjectType,
)
from padiem_control_plane.subscription import (
    SubscriptionSnapshot,
    SubscriptionState,
    SubscriptionTransition,
    apply_subscription_transition,
    validate_transition_batch,
)


NOW = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
SUBJECT = CanonicalSubjectRef(
    subject_type=SubjectType.USER,
    subject_id="sub_test_123",
)


def snapshot(state: SubscriptionState = SubscriptionState.PENDING) -> SubscriptionSnapshot:
    return SubscriptionSnapshot(
        subscription_id="subscr_123",
        product_id="b62",
        subject=SUBJECT,
        state=state,
        revision=1,
        effective_at=NOW,
        current_period_end=NOW + timedelta(days=30),
    )


def transition(
    from_state: SubscriptionState,
    to_state: SubscriptionState,
    *,
    event_id: str = "evt_1",
    idempotency_key: str = "idem_1",
    occurred_at: datetime = NOW + timedelta(minutes=1),
) -> SubscriptionTransition:
    return SubscriptionTransition(
        event_id=event_id,
        idempotency_key=idempotency_key,
        subscription_id="subscr_123",
        from_state=from_state,
        to_state=to_state,
        occurred_at=occurred_at,
        reason_code="TRUSTED_STATE_UPDATE",
    )


def test_pending_can_activate() -> None:
    current = snapshot()
    event = transition(SubscriptionState.PENDING, SubscriptionState.ACTIVE)
    updated = apply_subscription_transition(
        current,
        event,
        next_revision=2,
        current_period_end=NOW + timedelta(days=30),
    )
    assert updated.state is SubscriptionState.ACTIVE
    assert updated.revision == 2


def test_terminal_subscription_cannot_reactivate_in_place() -> None:
    with pytest.raises(ControlPlaneContractError):
        transition(SubscriptionState.CANCELED, SubscriptionState.ACTIVE)
    with pytest.raises(ControlPlaneContractError):
        transition(SubscriptionState.EXPIRED, SubscriptionState.ACTIVE)


def test_stale_from_state_fails_closed() -> None:
    current = snapshot(SubscriptionState.ACTIVE)
    event = transition(SubscriptionState.PAST_DUE, SubscriptionState.ACTIVE)
    with pytest.raises(ControlPlaneContractError):
        apply_subscription_transition(
            current,
            event,
            next_revision=2,
            current_period_end=NOW + timedelta(days=30),
        )


def test_revision_must_increment_exactly_once() -> None:
    current = snapshot()
    event = transition(SubscriptionState.PENDING, SubscriptionState.ACTIVE)
    with pytest.raises(ControlPlaneContractError):
        apply_subscription_transition(
            current,
            event,
            next_revision=3,
            current_period_end=NOW + timedelta(days=30),
        )


def test_duplicate_event_and_idempotency_keys_fail_closed() -> None:
    first = transition(
        SubscriptionState.PENDING,
        SubscriptionState.ACTIVE,
        event_id="evt_a",
        idempotency_key="idem_a",
    )
    duplicate_idempotency = transition(
        SubscriptionState.PENDING,
        SubscriptionState.CANCELED,
        event_id="evt_b",
        idempotency_key="idem_a",
    )
    with pytest.raises(ControlPlaneContractError):
        validate_transition_batch((first, duplicate_idempotency))


def test_naive_transition_timestamp_fails_closed() -> None:
    with pytest.raises(ControlPlaneContractError):
        transition(
            SubscriptionState.PENDING,
            SubscriptionState.ACTIVE,
            occurred_at=datetime(2026, 8, 30, 12, 1),
        )


def test_terminal_snapshot_cannot_keep_cancel_at_period_end() -> None:
    with pytest.raises(ControlPlaneContractError):
        SubscriptionSnapshot(
            subscription_id="subscr_123",
            product_id="b62",
            subject=SUBJECT,
            state=SubscriptionState.CANCELED,
            revision=2,
            effective_at=NOW,
            cancel_at_period_end=True,
        )


def test_contract_contains_no_payment_processor_or_credential_fields() -> None:
    current = snapshot()
    assert not hasattr(current, "payment_provider")
    assert not hasattr(current, "payment_method")
    assert not hasattr(current, "card_number")
    assert not hasattr(current, "processor_customer_id")
