"""Provider-neutral canonical payment-event envelope.

This contract accepts only already-authenticated/server-verified payment facts.
It does not select a processor, verify webhook signatures itself, store raw
provider payloads, charge/refund money, or mutate subscriptions/credit balances.
Adapters remain responsible for authentication and translation into this shape.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
import re

from .contracts import CanonicalSubjectRef, ControlPlaneContractError

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
MAX_OPAQUE_ID_CHARS = 256


class PaymentEventKind(str, Enum):
    FUNDS_RECEIVED = "funds_received"
    PAYMENT_FAILED = "payment_failed"
    REFUND_RECORDED = "refund_recorded"
    REVERSAL_RECORDED = "reversal_recorded"


class PaymentEvidenceSource(str, Enum):
    AUTHENTICATED_WEBHOOK = "authenticated_webhook"
    SERVER_VERIFIED_API = "server_verified_api"


def _error(code: str, message: str) -> ControlPlaneContractError:
    return ControlPlaneContractError(code, message)


def _identifier(name: str, value: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER_RE.fullmatch(value):
        raise _error("invalid_payment_event", f"{name} must be a safe identifier")
    return value


def _opaque(name: str, value: str) -> str:
    if not isinstance(value, str):
        raise _error("invalid_payment_event", f"{name} must be a string")
    normalized = value.strip()
    if (
        not normalized
        or len(normalized) > MAX_OPAQUE_ID_CHARS
        or any(ord(char) < 32 or ord(char) == 127 for char in normalized)
    ):
        raise _error(
            "invalid_payment_event",
            f"{name} must be a bounded non-empty opaque identifier",
        )
    return normalized


def _aware(name: str, value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise _error("invalid_timestamp", f"{name} must be timezone-aware")
    return value


def _positive_decimal(value: Decimal) -> Decimal:
    try:
        normalized = Decimal(value)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise _error("invalid_payment_amount", "amount must be a finite positive decimal") from exc
    if not normalized.is_finite() or normalized <= 0:
        raise _error("invalid_payment_amount", "amount must be a finite positive decimal")
    return normalized


@dataclass(frozen=True, slots=True)
class CanonicalPaymentEvent:
    """One immutable trusted payment fact before product-specific translation."""

    event_id: str
    idempotency_key: str
    source_adapter_id: str
    provider_event_id: str
    product_id: str
    account_namespace: str
    subject: CanonicalSubjectRef
    kind: PaymentEventKind
    amount: Decimal
    currency: str
    occurred_at: datetime
    received_at: datetime
    evidence_source: PaymentEvidenceSource
    reason_code: str
    subscription_id: str | None = None
    credit_program_id: str | None = None
    related_payment_event_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_id", _identifier("event_id", self.event_id))
        object.__setattr__(self, "idempotency_key", _opaque("idempotency_key", self.idempotency_key))
        object.__setattr__(
            self,
            "source_adapter_id",
            _identifier("source_adapter_id", self.source_adapter_id),
        )
        object.__setattr__(
            self,
            "provider_event_id",
            _opaque("provider_event_id", self.provider_event_id),
        )
        object.__setattr__(self, "product_id", _identifier("product_id", self.product_id))
        object.__setattr__(
            self,
            "account_namespace",
            _identifier("account_namespace", self.account_namespace),
        )
        if not isinstance(self.subject, CanonicalSubjectRef):
            raise _error("invalid_payment_event", "subject must be CanonicalSubjectRef")
        if not isinstance(self.kind, PaymentEventKind):
            raise _error("invalid_payment_event", "kind must be PaymentEventKind")
        object.__setattr__(self, "amount", _positive_decimal(self.amount))
        if not isinstance(self.currency, str) or not _CURRENCY_RE.fullmatch(self.currency):
            raise _error(
                "invalid_payment_event",
                "currency must be an uppercase ISO-style three-letter code",
            )
        object.__setattr__(self, "occurred_at", _aware("occurred_at", self.occurred_at))
        object.__setattr__(self, "received_at", _aware("received_at", self.received_at))
        if self.received_at < self.occurred_at:
            raise _error(
                "invalid_payment_event",
                "received_at cannot be before occurred_at",
            )
        if not isinstance(self.evidence_source, PaymentEvidenceSource):
            raise _error(
                "invalid_payment_event",
                "evidence_source must be PaymentEvidenceSource",
            )
        object.__setattr__(self, "reason_code", _identifier("reason_code", self.reason_code))

        for name in ("subscription_id", "credit_program_id"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _identifier(name, value))

        if self.related_payment_event_id is not None:
            object.__setattr__(
                self,
                "related_payment_event_id",
                _opaque("related_payment_event_id", self.related_payment_event_id),
            )
            if self.related_payment_event_id == self.provider_event_id:
                raise _error(
                    "invalid_payment_event",
                    "related_payment_event_id cannot reference the same provider event",
                )

        if self.kind in {PaymentEventKind.REFUND_RECORDED, PaymentEventKind.REVERSAL_RECORDED}:
            if self.related_payment_event_id is None:
                raise _error(
                    "invalid_payment_event",
                    "refund/reversal events require related_payment_event_id",
                )
        elif self.related_payment_event_id is not None:
            raise _error(
                "invalid_payment_event",
                "only refund/reversal events may reference another payment event",
            )

    @property
    def source_event_key(self) -> tuple[str, str]:
        return (self.source_adapter_id, self.provider_event_id)

    def to_public_dict(self) -> dict[str, object]:
        return {
            "event_id": self.event_id,
            "idempotency_key": self.idempotency_key,
            "source_adapter_id": self.source_adapter_id,
            "provider_event_id": self.provider_event_id,
            "product_id": self.product_id,
            "account_namespace": self.account_namespace,
            "subject": self.subject.to_public_dict(),
            "kind": self.kind.value,
            "amount": format(self.amount, "f"),
            "currency": self.currency,
            "occurred_at": self.occurred_at.isoformat(),
            "received_at": self.received_at.isoformat(),
            "evidence_source": self.evidence_source.value,
            "reason_code": self.reason_code,
            "subscription_id": self.subscription_id,
            "credit_program_id": self.credit_program_id,
            "related_payment_event_id": self.related_payment_event_id,
        }


def validate_payment_event_batch(
    events: Sequence[CanonicalPaymentEvent],
) -> tuple[CanonicalPaymentEvent, ...]:
    """Reject duplicate canonical, idempotency, or authenticated source identities."""

    if isinstance(events, (str, bytes)):
        raise _error("invalid_payment_batch", "events must be a sequence")
    items = tuple(events)
    if any(not isinstance(item, CanonicalPaymentEvent) for item in items):
        raise _error(
            "invalid_payment_batch",
            "events must contain only CanonicalPaymentEvent values",
        )

    event_ids: set[str] = set()
    idempotency_keys: set[str] = set()
    source_event_keys: set[tuple[str, str]] = set()
    by_provider_event: dict[tuple[str, str], CanonicalPaymentEvent] = {}

    for item in items:
        if item.event_id in event_ids:
            raise _error("duplicate_payment_event", "duplicate event_id is not allowed")
        if item.idempotency_key in idempotency_keys:
            raise _error(
                "duplicate_payment_event",
                "duplicate idempotency_key is not allowed",
            )
        if item.source_event_key in source_event_keys:
            raise _error(
                "duplicate_payment_event",
                "one authenticated provider event cannot be ingested twice",
            )
        event_ids.add(item.event_id)
        idempotency_keys.add(item.idempotency_key)
        source_event_keys.add(item.source_event_key)
        by_provider_event[item.source_event_key] = item

    for item in items:
        if item.related_payment_event_id is None:
            continue
        related = by_provider_event.get((item.source_adapter_id, item.related_payment_event_id))
        if related is None:
            continue  # may reference an already-persisted historical provider event
        if related.product_id != item.product_id or related.account_namespace != item.account_namespace:
            raise _error(
                "cross_account_payment_reversal",
                "refund/reversal cannot target a different product account namespace",
            )
        if related.subject != item.subject:
            raise _error(
                "cross_subject_payment_reversal",
                "refund/reversal cannot target a different canonical subject",
            )
        if item.occurred_at < related.occurred_at:
            raise _error(
                "invalid_payment_event",
                "refund/reversal cannot occur before its related payment event",
            )

    return items
