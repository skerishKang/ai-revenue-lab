from dataclasses import fields
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from padiem_control_plane.contracts import (
    CanonicalSubjectRef,
    ControlPlaneContractError,
    SubjectType,
)
from padiem_control_plane.payment_events import (
    CanonicalPaymentEvent,
    PaymentEventKind,
    PaymentEvidenceSource,
    validate_payment_event_batch,
)


NOW = datetime(2026, 8, 31, 0, 0, tzinfo=timezone.utc)
SUBJECT = CanonicalSubjectRef(SubjectType.USER, "subject_123")


def event(
    event_id: str,
    *,
    provider_event_id: str | None = None,
    kind: PaymentEventKind = PaymentEventKind.FUNDS_RECEIVED,
    product_id: str = "b62",
    account_namespace: str = "consumer",
    subject: CanonicalSubjectRef = SUBJECT,
    amount: str = "9.90",
    currency: str = "USD",
    occurred_at: datetime = NOW,
    received_at: datetime = NOW + timedelta(seconds=2),
    related_payment_event_id: str | None = None,
) -> CanonicalPaymentEvent:
    return CanonicalPaymentEvent(
        event_id=event_id,
        idempotency_key=f"idem:{event_id}",
        source_adapter_id="payment.adapter.v1",
        provider_event_id=provider_event_id or f"provider:{event_id}",
        product_id=product_id,
        account_namespace=account_namespace,
        subject=subject,
        kind=kind,
        amount=Decimal(amount),
        currency=currency,
        occurred_at=occurred_at,
        received_at=received_at,
        evidence_source=PaymentEvidenceSource.AUTHENTICATED_WEBHOOK,
        reason_code="TRUSTED_PAYMENT_EVENT",
        subscription_id="subscription_123",
        credit_program_id="monthly.allowance",
        related_payment_event_id=related_payment_event_id,
    )


def test_authenticated_payment_fact_keeps_product_account_namespace() -> None:
    item = event("payment_1")

    public = item.to_public_dict()
    assert public["product_id"] == "b62"
    assert public["account_namespace"] == "consumer"
    assert public["evidence_source"] == "authenticated_webhook"
    assert public["amount"] == "9.90"
    assert public["currency"] == "USD"


def test_processor_event_identity_is_deduplicated_even_with_different_canonical_ids() -> None:
    first = event("payment_a", provider_event_id="provider:one")
    second = CanonicalPaymentEvent(
        event_id="payment_b",
        idempotency_key="idem:payment_b",
        source_adapter_id="payment.adapter.v1",
        provider_event_id="provider:one",
        product_id="b62",
        account_namespace="consumer",
        subject=SUBJECT,
        kind=PaymentEventKind.FUNDS_RECEIVED,
        amount=Decimal("9.90"),
        currency="USD",
        occurred_at=NOW,
        received_at=NOW + timedelta(seconds=3),
        evidence_source=PaymentEvidenceSource.SERVER_VERIFIED_API,
        reason_code="TRUSTED_PAYMENT_EVENT",
    )

    with pytest.raises(ControlPlaneContractError) as exc:
        validate_payment_event_batch((first, second))
    assert exc.value.code == "duplicate_payment_event"


def test_refund_and_reversal_require_related_provider_event() -> None:
    for kind in (PaymentEventKind.REFUND_RECORDED, PaymentEventKind.REVERSAL_RECORDED):
        with pytest.raises(ControlPlaneContractError):
            event(f"missing_{kind.value}", kind=kind)

    refund = event(
        "refund_1",
        kind=PaymentEventKind.REFUND_RECORDED,
        provider_event_id="provider:refund_1",
        related_payment_event_id="provider:original",
    )
    assert refund.related_payment_event_id == "provider:original"


def test_non_reversal_event_cannot_claim_related_payment_event() -> None:
    with pytest.raises(ControlPlaneContractError):
        event(
            "bad_related",
            kind=PaymentEventKind.FUNDS_RECEIVED,
            related_payment_event_id="provider:old",
        )


def test_refund_with_in_batch_target_must_preserve_subject_and_account_namespace() -> None:
    original = event("original", provider_event_id="provider:original")
    refund = event(
        "refund",
        provider_event_id="provider:refund",
        kind=PaymentEventKind.REFUND_RECORDED,
        related_payment_event_id="provider:original",
        occurred_at=NOW + timedelta(minutes=1),
        received_at=NOW + timedelta(minutes=1, seconds=2),
    )
    assert validate_payment_event_batch((original, refund)) == (original, refund)

    foreign_refund = event(
        "foreign_refund",
        provider_event_id="provider:foreign_refund",
        kind=PaymentEventKind.REFUND_RECORDED,
        product_id="b14",
        account_namespace="api",
        related_payment_event_id="provider:original",
        occurred_at=NOW + timedelta(minutes=1),
        received_at=NOW + timedelta(minutes=1, seconds=2),
    )
    with pytest.raises(ControlPlaneContractError) as exc:
        validate_payment_event_batch((original, foreign_refund))
    assert exc.value.code == "cross_account_payment_reversal"


def test_refund_cannot_predate_related_payment_event() -> None:
    original = event(
        "original_late",
        provider_event_id="provider:original_late",
        occurred_at=NOW + timedelta(minutes=2),
        received_at=NOW + timedelta(minutes=2, seconds=1),
    )
    refund = event(
        "refund_early",
        provider_event_id="provider:refund_early",
        kind=PaymentEventKind.REFUND_RECORDED,
        related_payment_event_id="provider:original_late",
        occurred_at=NOW + timedelta(minutes=1),
        received_at=NOW + timedelta(minutes=1, seconds=1),
    )

    with pytest.raises(ControlPlaneContractError):
        validate_payment_event_batch((original, refund))


def test_received_at_cannot_be_before_provider_occurrence() -> None:
    with pytest.raises(ControlPlaneContractError):
        event(
            "bad_time",
            occurred_at=NOW + timedelta(seconds=5),
            received_at=NOW,
        )


def test_amount_and_currency_fail_closed() -> None:
    for amount in ("0", "-1", "NaN", "Infinity"):
        with pytest.raises(ControlPlaneContractError):
            event(f"bad_amount_{amount}", amount=amount)

    with pytest.raises(ControlPlaneContractError):
        event("bad_currency", currency="usd")


def test_evidence_source_must_be_trusted_server_side_enum() -> None:
    with pytest.raises(ControlPlaneContractError):
        CanonicalPaymentEvent(
            event_id="bad_source",
            idempotency_key="idem:bad_source",
            source_adapter_id="payment.adapter.v1",
            provider_event_id="provider:bad_source",
            product_id="b62",
            account_namespace="consumer",
            subject=SUBJECT,
            kind=PaymentEventKind.FUNDS_RECEIVED,
            amount=Decimal("1"),
            currency="USD",
            occurred_at=NOW,
            received_at=NOW,
            evidence_source="browser" ,  # type: ignore[arg-type]
            reason_code="TRUSTED_PAYMENT_EVENT",
        )


def test_payment_contract_has_no_raw_payload_credentials_or_payment_method_fields() -> None:
    names = {field.name for field in fields(CanonicalPaymentEvent)}
    for forbidden in (
        "raw_payload",
        "payload",
        "webhook_body",
        "secret",
        "signature_secret",
        "payment_method",
        "card_number",
        "authorization",
    ):
        assert forbidden not in names


def test_naive_timestamps_fail_closed() -> None:
    with pytest.raises(ControlPlaneContractError):
        event(
            "naive_occurred",
            occurred_at=datetime(2026, 8, 31, 0, 0),
        )
