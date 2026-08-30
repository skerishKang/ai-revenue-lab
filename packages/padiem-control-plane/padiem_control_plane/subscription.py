"""Provider-neutral subscription state contract for the Padiem Control Plane.

This module defines canonical internal lifecycle semantics only. It does not
select a payment processor, charge money, store payment credentials, or derive
product entitlements by itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from .contracts import CanonicalSubjectRef, ControlPlaneContractError


class SubscriptionState(str, Enum):
    PENDING = "pending"
    TRIALING = "trialing"
    ACTIVE = "active"
    PAST_DUE = "past_due"
    PAUSED = "paused"
    CANCELED = "canceled"
    EXPIRED = "expired"


_ALLOWED_TRANSITIONS: dict[SubscriptionState, frozenset[SubscriptionState]] = {
    SubscriptionState.PENDING: frozenset(
        {
            SubscriptionState.TRIALING,
            SubscriptionState.ACTIVE,
            SubscriptionState.CANCELED,
            SubscriptionState.EXPIRED,
        }
    ),
    SubscriptionState.TRIALING: frozenset(
        {
            SubscriptionState.ACTIVE,
            SubscriptionState.PAST_DUE,
            SubscriptionState.CANCELED,
            SubscriptionState.EXPIRED,
        }
    ),
    SubscriptionState.ACTIVE: frozenset(
        {
            SubscriptionState.PAST_DUE,
            SubscriptionState.PAUSED,
            SubscriptionState.CANCELED,
            SubscriptionState.EXPIRED,
        }
    ),
    SubscriptionState.PAST_DUE: frozenset(
        {
            SubscriptionState.ACTIVE,
            SubscriptionState.PAUSED,
            SubscriptionState.CANCELED,
            SubscriptionState.EXPIRED,
        }
    ),
    SubscriptionState.PAUSED: frozenset(
        {
            SubscriptionState.ACTIVE,
            SubscriptionState.CANCELED,
            SubscriptionState.EXPIRED,
        }
    ),
    SubscriptionState.CANCELED: frozenset(),
    SubscriptionState.EXPIRED: frozenset(),
}


def _error(code: str, message: str) -> ControlPlaneContractError:
    return ControlPlaneContractError(code, message)


def _require_id(name: str, value: str) -> str:
    if not isinstance(value, str):
        raise _error("invalid_subscription", f"{name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise _error("invalid_subscription", f"{name} is required")
    if len(normalized) > 128:
        raise _error("invalid_subscription", f"{name} is too long")
    if any(ch.isspace() for ch in normalized):
        raise _error("invalid_subscription", f"{name} must be a machine identifier")
    return normalized


def _require_aware(name: str, value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise _error("invalid_timestamp", f"{name} must be timezone-aware")
    return value


@dataclass(frozen=True, slots=True)
class SubscriptionSnapshot:
    subscription_id: str
    product_id: str
    subject: CanonicalSubjectRef
    state: SubscriptionState
    revision: int
    effective_at: datetime
    current_period_end: datetime | None = None
    cancel_at_period_end: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "subscription_id", _require_id("subscription_id", self.subscription_id))
        object.__setattr__(self, "product_id", _require_id("product_id", self.product_id))
        if not isinstance(self.subject, CanonicalSubjectRef):
            raise _error("invalid_subscription", "subject must be CanonicalSubjectRef")
        if not isinstance(self.state, SubscriptionState):
            raise _error("invalid_subscription", "state must be SubscriptionState")
        if isinstance(self.revision, bool) or not isinstance(self.revision, int) or self.revision < 1:
            raise _error("invalid_subscription", "revision must be a positive integer")
        _require_aware("effective_at", self.effective_at)
        if self.current_period_end is not None:
            _require_aware("current_period_end", self.current_period_end)
            if self.current_period_end <= self.effective_at:
                raise _error(
                    "invalid_subscription",
                    "current_period_end must be after effective_at",
                )
        if not isinstance(self.cancel_at_period_end, bool):
            raise _error("invalid_subscription", "cancel_at_period_end must be boolean")
        if self.state in {SubscriptionState.CANCELED, SubscriptionState.EXPIRED} and self.cancel_at_period_end:
            raise _error(
                "invalid_subscription",
                "terminal subscription cannot remain cancel_at_period_end",
            )


@dataclass(frozen=True, slots=True)
class SubscriptionTransition:
    event_id: str
    idempotency_key: str
    subscription_id: str
    from_state: SubscriptionState
    to_state: SubscriptionState
    occurred_at: datetime
    reason_code: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_id", _require_id("event_id", self.event_id))
        object.__setattr__(self, "idempotency_key", _require_id("idempotency_key", self.idempotency_key))
        object.__setattr__(self, "subscription_id", _require_id("subscription_id", self.subscription_id))
        if not isinstance(self.from_state, SubscriptionState) or not isinstance(self.to_state, SubscriptionState):
            raise _error("invalid_subscription_transition", "states must be SubscriptionState")
        if self.to_state not in _ALLOWED_TRANSITIONS[self.from_state]:
            raise _error(
                "invalid_subscription_transition",
                f"transition {self.from_state.value}->{self.to_state.value} is not allowed",
            )
        _require_aware("occurred_at", self.occurred_at)
        reason = _require_id("reason_code", self.reason_code)
        object.__setattr__(self, "reason_code", reason)


def apply_subscription_transition(
    snapshot: SubscriptionSnapshot,
    transition: SubscriptionTransition,
    *,
    next_revision: int,
    current_period_end: datetime | None = None,
    cancel_at_period_end: bool = False,
) -> SubscriptionSnapshot:
    """Build the next immutable snapshot after a validated lifecycle event.

    This function does not perform persistence, webhook authentication,
    payment processing, or entitlement calculation.
    """

    if transition.subscription_id != snapshot.subscription_id:
        raise _error(
            "invalid_subscription_transition",
            "transition subscription_id does not match snapshot",
        )
    if transition.from_state is not snapshot.state:
        raise _error(
            "stale_subscription_transition",
            "transition from_state does not match current snapshot",
        )
    if isinstance(next_revision, bool) or not isinstance(next_revision, int) or next_revision != snapshot.revision + 1:
        raise _error(
            "invalid_subscription_revision",
            "next_revision must increment exactly by one",
        )
    if transition.occurred_at < snapshot.effective_at:
        raise _error(
            "stale_subscription_transition",
            "transition occurred before current snapshot became effective",
        )

    return SubscriptionSnapshot(
        subscription_id=snapshot.subscription_id,
        product_id=snapshot.product_id,
        subject=snapshot.subject,
        state=transition.to_state,
        revision=next_revision,
        effective_at=transition.occurred_at,
        current_period_end=current_period_end,
        cancel_at_period_end=cancel_at_period_end,
    )


def validate_transition_batch(transitions: tuple[SubscriptionTransition, ...]) -> None:
    """Reject duplicate immutable/idempotency identities within one batch."""
    event_ids: set[str] = set()
    idempotency_keys: set[str] = set()
    for transition in transitions:
        if not isinstance(transition, SubscriptionTransition):
            raise _error(
                "invalid_subscription_transition",
                "batch contains non-SubscriptionTransition value",
            )
        if transition.event_id in event_ids:
            raise _error("duplicate_subscription_event", "duplicate event_id")
        if transition.idempotency_key in idempotency_keys:
            raise _error(
                "duplicate_subscription_event",
                "duplicate idempotency_key",
            )
        event_ids.add(transition.event_id)
        idempotency_keys.add(transition.idempotency_key)
