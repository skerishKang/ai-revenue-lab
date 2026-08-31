from datetime import datetime, timedelta, timezone
from decimal import Decimal
from dataclasses import fields

import pytest

from padiem_control_plane.contracts import (
    CanonicalSubjectRef,
    ControlPlaneContractError,
    SubjectType,
)
from padiem_control_plane.credit_ledger import (
    CreditAccountRef,
    CreditBalanceSnapshot,
    CreditEntryDirection,
    CreditEntryKind,
    CreditLedgerEntry,
    apply_credit_ledger_batch,
    validate_credit_ledger_batch,
)


NOW = datetime(2026, 8, 31, 0, 0, tzinfo=timezone.utc)
SUBJECT = CanonicalSubjectRef(SubjectType.USER, "subject_123")


def account(
    *,
    product_id: str = "b62",
    account_namespace: str = "consumer",
    credit_program_id: str = "monthly.allowance",
    unit: str = "credits",
) -> CreditAccountRef:
    return CreditAccountRef(
        product_id=product_id,
        account_namespace=account_namespace,
        credit_program_id=credit_program_id,
        subject=SUBJECT,
        unit=unit,
    )


def entry(
    event_id: str,
    *,
    kind: CreditEntryKind,
    direction: CreditEntryDirection,
    amount: str = "10",
    ledger_account: CreditAccountRef | None = None,
    billing_semantic_id: str | None = None,
    related_entry_id: str | None = None,
    occurred_at: datetime = NOW + timedelta(minutes=1),
) -> CreditLedgerEntry:
    return CreditLedgerEntry(
        event_id=event_id,
        idempotency_key=f"idem:{event_id}",
        account=ledger_account or account(),
        kind=kind,
        direction=direction,
        amount=Decimal(amount),
        occurred_at=occurred_at,
        trusted_reference_id=f"trusted:{event_id}",
        reason_code="TEST_REASON",
        billing_semantic_id=billing_semantic_id,
        related_entry_id=related_entry_id,
    )


def test_credit_account_namespace_prevents_product_program_unit_collisions() -> None:
    b62 = account()
    b14 = account(
        product_id="b14",
        account_namespace="api",
        credit_program_id="prepaid",
        unit="USD_credit",
    )

    assert b62.ledger_key != b14.ledger_key
    assert b62.to_public_dict()["account_namespace"] == "consumer"
    assert b14.to_public_dict()["credit_program_id"] == "prepaid"


def test_grant_and_consumption_apply_as_immutable_credit_and_debit() -> None:
    acc = account()
    snapshot = CreditBalanceSnapshot(acc, revision=0, balance=Decimal("0"), as_of=NOW)
    grant = entry(
        "grant_1",
        kind=CreditEntryKind.GRANT,
        direction=CreditEntryDirection.CREDIT,
        amount="100",
    )
    consume = entry(
        "consume_1",
        kind=CreditEntryKind.CONSUMPTION,
        direction=CreditEntryDirection.DEBIT,
        amount="12.5",
        billing_semantic_id="billing.request.1",
        occurred_at=NOW + timedelta(minutes=2),
    )

    updated = apply_credit_ledger_batch(
        snapshot,
        (grant, consume),
        next_revision=1,
        as_of=NOW + timedelta(minutes=3),
    )

    assert updated.balance == Decimal("87.5")
    assert snapshot.balance == Decimal("0")
    assert grant.signed_amount == Decimal("100")
    assert consume.signed_amount == Decimal("-12.5")


def test_consumption_requires_trusted_billing_semantic_and_debit_direction() -> None:
    with pytest.raises(ControlPlaneContractError):
        entry(
            "consume_missing_semantic",
            kind=CreditEntryKind.CONSUMPTION,
            direction=CreditEntryDirection.DEBIT,
        )

    with pytest.raises(ControlPlaneContractError):
        entry(
            "consume_wrong_direction",
            kind=CreditEntryKind.CONSUMPTION,
            direction=CreditEntryDirection.CREDIT,
            billing_semantic_id="billing.request.2",
        )


def test_same_billing_semantic_cannot_be_debited_twice_in_one_batch() -> None:
    first = entry(
        "consume_a",
        kind=CreditEntryKind.CONSUMPTION,
        direction=CreditEntryDirection.DEBIT,
        billing_semantic_id="billing.request.same",
    )
    second = entry(
        "consume_b",
        kind=CreditEntryKind.CONSUMPTION,
        direction=CreditEntryDirection.DEBIT,
        billing_semantic_id="billing.request.same",
        occurred_at=NOW + timedelta(minutes=2),
    )

    with pytest.raises(ControlPlaneContractError) as exc:
        validate_credit_ledger_batch((first, second))
    assert exc.value.code == "duplicate_credit_consumption"


def test_refund_is_a_new_credit_event_linked_to_original_consumption() -> None:
    consume = entry(
        "consume_original",
        kind=CreditEntryKind.CONSUMPTION,
        direction=CreditEntryDirection.DEBIT,
        billing_semantic_id="billing.request.refund",
    )
    refund = entry(
        "refund_1",
        kind=CreditEntryKind.REFUND,
        direction=CreditEntryDirection.CREDIT,
        amount="4",
        billing_semantic_id="billing.request.refund",
        related_entry_id="consume_original",
        occurred_at=NOW + timedelta(minutes=2),
    )

    assert validate_credit_ledger_batch((consume, refund)) == (consume, refund)
    assert refund.related_entry_id == consume.event_id
    assert refund.signed_amount == Decimal("4")

    with pytest.raises(ControlPlaneContractError):
        entry(
            "bad_refund",
            kind=CreditEntryKind.REFUND,
            direction=CreditEntryDirection.DEBIT,
            billing_semantic_id="billing.request.refund",
            related_entry_id="consume_original",
        )


def test_correction_can_move_either_direction_but_never_mutates_history() -> None:
    original = entry(
        "grant_original",
        kind=CreditEntryKind.GRANT,
        direction=CreditEntryDirection.CREDIT,
        amount="10",
    )
    correction = entry(
        "correction_1",
        kind=CreditEntryKind.CORRECTION,
        direction=CreditEntryDirection.DEBIT,
        amount="2",
        related_entry_id="grant_original",
        occurred_at=NOW + timedelta(minutes=2),
    )

    validate_credit_ledger_batch((original, correction))
    assert original.amount == Decimal("10")
    assert correction.signed_amount == Decimal("-2")

    with pytest.raises(ControlPlaneContractError):
        entry(
            "bad_correction",
            kind=CreditEntryKind.CORRECTION,
            direction=CreditEntryDirection.CREDIT,
        )


def test_cross_account_refund_or_correction_fails_closed_when_target_is_in_batch() -> None:
    original = entry(
        "consume_cross",
        kind=CreditEntryKind.CONSUMPTION,
        direction=CreditEntryDirection.DEBIT,
        billing_semantic_id="billing.cross",
    )
    other_account = account(product_id="b14", account_namespace="api", credit_program_id="prepaid")
    refund = entry(
        "refund_cross",
        kind=CreditEntryKind.REFUND,
        direction=CreditEntryDirection.CREDIT,
        billing_semantic_id="billing.cross",
        related_entry_id="consume_cross",
        ledger_account=other_account,
        occurred_at=NOW + timedelta(minutes=2),
    )

    with pytest.raises(ControlPlaneContractError) as exc:
        validate_credit_ledger_batch((original, refund))
    assert exc.value.code == "cross_account_correction"


def test_balance_batch_requires_exact_account_revision_and_monotonic_time() -> None:
    acc = account()
    snapshot = CreditBalanceSnapshot(acc, revision=3, balance=Decimal("25"), as_of=NOW)
    grant = entry(
        "grant_revision",
        kind=CreditEntryKind.GRANT,
        direction=CreditEntryDirection.CREDIT,
    )

    with pytest.raises(ControlPlaneContractError):
        apply_credit_ledger_batch(
            snapshot,
            (grant,),
            next_revision=5,
            as_of=NOW + timedelta(minutes=2),
        )

    foreign = entry(
        "foreign_grant",
        kind=CreditEntryKind.GRANT,
        direction=CreditEntryDirection.CREDIT,
        ledger_account=account(product_id="b14", account_namespace="api", credit_program_id="prepaid"),
    )
    with pytest.raises(ControlPlaneContractError) as exc:
        apply_credit_ledger_batch(
            snapshot,
            (foreign,),
            next_revision=4,
            as_of=NOW + timedelta(minutes=2),
        )
    assert exc.value.code == "mixed_credit_account"


def test_negative_balance_is_not_silently_clamped_by_accounting_primitive() -> None:
    acc = account()
    snapshot = CreditBalanceSnapshot(acc, revision=0, balance=Decimal("5"), as_of=NOW)
    debit = entry(
        "consume_over",
        kind=CreditEntryKind.CONSUMPTION,
        direction=CreditEntryDirection.DEBIT,
        amount="8",
        billing_semantic_id="billing.over",
    )

    updated = apply_credit_ledger_batch(
        snapshot,
        (debit,),
        next_revision=1,
        as_of=NOW + timedelta(minutes=2),
    )
    assert updated.balance == Decimal("-3")


def test_ledger_contract_has_no_arbitrary_payload_or_secret_fields() -> None:
    names = {field.name for field in fields(CreditLedgerEntry)}
    assert "metadata" not in names
    assert "payload" not in names
    assert "secret" not in names
    assert "payment_method" not in names
    assert "provider_credential" not in names


def test_naive_timestamps_and_non_positive_postings_fail_closed() -> None:
    with pytest.raises(ControlPlaneContractError):
        entry(
            "naive",
            kind=CreditEntryKind.GRANT,
            direction=CreditEntryDirection.CREDIT,
            occurred_at=datetime(2026, 8, 31, 0, 1),
        )

    with pytest.raises(ControlPlaneContractError):
        entry(
            "zero",
            kind=CreditEntryKind.GRANT,
            direction=CreditEntryDirection.CREDIT,
            amount="0",
        )
