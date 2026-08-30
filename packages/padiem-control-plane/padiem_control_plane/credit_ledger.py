"""Provider-neutral credit-ledger contracts for the Padiem Control Plane.

This module defines immutable accounting semantics only. It does not select a
payment processor, charge money, persist balances, derive product entitlements,
or replace product-local admission/quota enforcement.
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
MAX_IDEMPOTENCY_KEY_CHARS = 256


class CreditEntryDirection(str, Enum):
    CREDIT = "credit"
    DEBIT = "debit"


class CreditEntryKind(str, Enum):
    GRANT = "grant"
    CONSUMPTION = "consumption"
    REFUND = "refund"
    CORRECTION = "correction"


def _error(code: str, message: str) -> ControlPlaneContractError:
    return ControlPlaneContractError(code, message)


def _identifier(name: str, value: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER_RE.fullmatch(value):
        raise _error("invalid_credit_ledger", f"{name} must be a safe identifier")
    return value


def _opaque_id(name: str, value: str, *, limit: int = MAX_IDEMPOTENCY_KEY_CHARS) -> str:
    if not isinstance(value, str):
        raise _error("invalid_credit_ledger", f"{name} must be a string")
    normalized = value.strip()
    if (
        not normalized
        or len(normalized) > limit
        or any(ord(char) < 32 or ord(char) == 127 for char in normalized)
    ):
        raise _error(
            "invalid_credit_ledger",
            f"{name} must be a bounded non-empty opaque identifier",
        )
    return normalized


def _aware(name: str, value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise _error("invalid_timestamp", f"{name} must be timezone-aware")
    return value


def _decimal(name: str, value: Decimal, *, positive: bool = False) -> Decimal:
    try:
        normalized = Decimal(value)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise _error("invalid_credit_amount", f"{name} must be a finite decimal") from exc
    if not normalized.is_finite():
        raise _error("invalid_credit_amount", f"{name} must be a finite decimal")
    if positive and normalized <= 0:
        raise _error("invalid_credit_amount", f"{name} must be greater than zero")
    return normalized


@dataclass(frozen=True, slots=True)
class CreditAccountRef:
    """Canonical credit account namespace.

    Product policy remains product-owned. The shared ledger only guarantees that
    entries cannot silently mix products, account namespaces, credit programs,
    subjects, or units.
    """

    product_id: str
    account_namespace: str
    credit_program_id: str
    subject: CanonicalSubjectRef
    unit: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "product_id", _identifier("product_id", self.product_id))
        object.__setattr__(
            self,
            "account_namespace",
            _identifier("account_namespace", self.account_namespace),
        )
        object.__setattr__(
            self,
            "credit_program_id",
            _identifier("credit_program_id", self.credit_program_id),
        )
        if not isinstance(self.subject, CanonicalSubjectRef):
            raise _error("invalid_credit_account", "subject must be CanonicalSubjectRef")
        object.__setattr__(self, "unit", _identifier("unit", self.unit))

    @property
    def ledger_key(self) -> tuple[str, str, str, str, str, str]:
        return (
            self.product_id,
            self.account_namespace,
            self.credit_program_id,
            self.subject.subject_type.value,
            self.subject.subject_id,
            self.unit,
        )

    def to_public_dict(self) -> dict[str, object]:
        return {
            "product_id": self.product_id,
            "account_namespace": self.account_namespace,
            "credit_program_id": self.credit_program_id,
            "subject": self.subject.to_public_dict(),
            "unit": self.unit,
        }


@dataclass(frozen=True, slots=True)
class CreditLedgerEntry:
    """One immutable canonical credit posting.

    `trusted_reference_id` identifies the trusted server event that caused the
    posting (for example a subscription-cycle grant, authenticated payment
    event, or authoritative usage event). No arbitrary payload or credential is
    carried in the ledger entry.
    """

    event_id: str
    idempotency_key: str
    account: CreditAccountRef
    kind: CreditEntryKind
    direction: CreditEntryDirection
    amount: Decimal
    occurred_at: datetime
    trusted_reference_id: str
    reason_code: str
    billing_semantic_id: str | None = None
    related_entry_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_id", _identifier("event_id", self.event_id))
        object.__setattr__(
            self,
            "idempotency_key",
            _opaque_id("idempotency_key", self.idempotency_key),
        )
        if not isinstance(self.account, CreditAccountRef):
            raise _error("invalid_credit_ledger", "account must be CreditAccountRef")
        if not isinstance(self.kind, CreditEntryKind):
            raise _error("invalid_credit_ledger", "kind must be CreditEntryKind")
        if not isinstance(self.direction, CreditEntryDirection):
            raise _error("invalid_credit_ledger", "direction must be CreditEntryDirection")
        object.__setattr__(self, "amount", _decimal("amount", self.amount, positive=True))
        object.__setattr__(self, "occurred_at", _aware("occurred_at", self.occurred_at))
        object.__setattr__(
            self,
            "trusted_reference_id",
            _opaque_id("trusted_reference_id", self.trusted_reference_id),
        )
        object.__setattr__(self, "reason_code", _identifier("reason_code", self.reason_code))

        if self.billing_semantic_id is not None:
            object.__setattr__(
                self,
                "billing_semantic_id",
                _identifier("billing_semantic_id", self.billing_semantic_id),
            )
        if self.related_entry_id is not None:
            object.__setattr__(
                self,
                "related_entry_id",
                _identifier("related_entry_id", self.related_entry_id),
            )
            if self.related_entry_id == self.event_id:
                raise _error(
                    "invalid_credit_ledger",
                    "related_entry_id cannot reference the entry itself",
                )

        if self.kind is CreditEntryKind.GRANT:
            if self.direction is not CreditEntryDirection.CREDIT:
                raise _error("invalid_credit_ledger", "grant entries must credit the account")
            if self.billing_semantic_id is not None or self.related_entry_id is not None:
                raise _error(
                    "invalid_credit_ledger",
                    "grant entries cannot claim usage or reversal semantics",
                )
        elif self.kind is CreditEntryKind.CONSUMPTION:
            if self.direction is not CreditEntryDirection.DEBIT:
                raise _error(
                    "invalid_credit_ledger",
                    "consumption entries must debit the account",
                )
            if self.billing_semantic_id is None:
                raise _error(
                    "invalid_credit_ledger",
                    "consumption entries require billing_semantic_id",
                )
            if self.related_entry_id is not None:
                raise _error(
                    "invalid_credit_ledger",
                    "consumption entries cannot be reversal entries",
                )
        elif self.kind is CreditEntryKind.REFUND:
            if self.direction is not CreditEntryDirection.CREDIT:
                raise _error("invalid_credit_ledger", "refund entries must credit the account")
            if self.related_entry_id is None:
                raise _error(
                    "invalid_credit_ledger",
                    "refund entries require related_entry_id",
                )
            if self.billing_semantic_id is None:
                raise _error(
                    "invalid_credit_ledger",
                    "refund entries require billing_semantic_id",
                )
        elif self.kind is CreditEntryKind.CORRECTION:
            if self.related_entry_id is None:
                raise _error(
                    "invalid_credit_ledger",
                    "correction entries require related_entry_id",
                )
        else:  # pragma: no cover - enum exhaustiveness guard
            raise _error("invalid_credit_ledger", "unsupported credit entry kind")

    @property
    def signed_amount(self) -> Decimal:
        return self.amount if self.direction is CreditEntryDirection.CREDIT else -self.amount

    def to_public_dict(self) -> dict[str, object]:
        return {
            "event_id": self.event_id,
            "idempotency_key": self.idempotency_key,
            "account": self.account.to_public_dict(),
            "kind": self.kind.value,
            "direction": self.direction.value,
            "amount": format(self.amount, "f"),
            "occurred_at": self.occurred_at.isoformat(),
            "trusted_reference_id": self.trusted_reference_id,
            "reason_code": self.reason_code,
            "billing_semantic_id": self.billing_semantic_id,
            "related_entry_id": self.related_entry_id,
        }


@dataclass(frozen=True, slots=True)
class CreditBalanceSnapshot:
    """Immutable balance snapshot for one exact credit-account namespace."""

    account: CreditAccountRef
    revision: int
    balance: Decimal
    as_of: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.account, CreditAccountRef):
            raise _error("invalid_credit_balance", "account must be CreditAccountRef")
        if isinstance(self.revision, bool) or not isinstance(self.revision, int) or self.revision < 0:
            raise _error("invalid_credit_balance", "revision must be a non-negative integer")
        object.__setattr__(self, "balance", _decimal("balance", self.balance))
        object.__setattr__(self, "as_of", _aware("as_of", self.as_of))

    def to_public_dict(self) -> dict[str, object]:
        return {
            "account": self.account.to_public_dict(),
            "revision": self.revision,
            "balance": format(self.balance, "f"),
            "as_of": self.as_of.isoformat(),
        }


def validate_credit_ledger_batch(
    entries: Sequence[CreditLedgerEntry],
) -> tuple[CreditLedgerEntry, ...]:
    """Validate immutable identities and double-debit protection within a batch."""

    if isinstance(entries, (str, bytes)):
        raise _error("invalid_credit_batch", "entries must be a sequence")
    items = tuple(entries)
    if any(not isinstance(item, CreditLedgerEntry) for item in items):
        raise _error(
            "invalid_credit_batch",
            "entries must contain only CreditLedgerEntry values",
        )

    event_ids: set[str] = set()
    idempotency_keys: set[str] = set()
    consumption_semantics: set[str] = set()
    by_event_id: dict[str, CreditLedgerEntry] = {}

    for item in items:
        if item.event_id in event_ids:
            raise _error("duplicate_credit_entry", "duplicate event_id is not allowed")
        if item.idempotency_key in idempotency_keys:
            raise _error(
                "duplicate_credit_entry",
                "duplicate idempotency_key is not allowed",
            )
        if item.kind is CreditEntryKind.CONSUMPTION:
            assert item.billing_semantic_id is not None
            if item.billing_semantic_id in consumption_semantics:
                raise _error(
                    "duplicate_credit_consumption",
                    "one billing_semantic_id cannot be debited twice in one batch",
                )
            consumption_semantics.add(item.billing_semantic_id)
        event_ids.add(item.event_id)
        idempotency_keys.add(item.idempotency_key)
        by_event_id[item.event_id] = item

    for item in items:
        if item.related_entry_id is None:
            continue
        related = by_event_id.get(item.related_entry_id)
        if related is None:
            continue  # target may be an already-persisted historical entry
        if related.account.ledger_key != item.account.ledger_key:
            raise _error(
                "cross_account_correction",
                "refund/correction cannot target a different credit account",
            )
        if item.occurred_at < related.occurred_at:
            raise _error(
                "invalid_credit_ledger",
                "refund/correction cannot occur before its related entry",
            )

    return items


def apply_credit_ledger_batch(
    snapshot: CreditBalanceSnapshot,
    entries: Sequence[CreditLedgerEntry],
    *,
    next_revision: int,
    as_of: datetime,
) -> CreditBalanceSnapshot:
    """Apply validated postings to one immutable balance snapshot.

    Negative balances are represented rather than silently clamped; whether a
    product permits a debit is an admission/entitlement policy decision outside
    this accounting primitive.
    """

    if not isinstance(snapshot, CreditBalanceSnapshot):
        raise _error("invalid_credit_balance", "snapshot must be CreditBalanceSnapshot")
    items = validate_credit_ledger_batch(entries)
    as_of = _aware("as_of", as_of)
    if (
        isinstance(next_revision, bool)
        or not isinstance(next_revision, int)
        or next_revision != snapshot.revision + 1
    ):
        raise _error(
            "invalid_credit_revision",
            "next_revision must increment exactly by one",
        )
    if as_of < snapshot.as_of:
        raise _error("stale_credit_batch", "as_of cannot move backwards")

    delta = Decimal("0")
    for item in items:
        if item.account.ledger_key != snapshot.account.ledger_key:
            raise _error(
                "mixed_credit_account",
                "all entries must target the snapshot's exact credit account",
            )
        if item.occurred_at < snapshot.as_of:
            raise _error(
                "stale_credit_batch",
                "new ledger entries cannot predate the current snapshot",
            )
        if item.occurred_at > as_of:
            raise _error(
                "future_credit_entry",
                "ledger entry cannot occur after the requested as_of time",
            )
        delta += item.signed_amount

    return CreditBalanceSnapshot(
        account=snapshot.account,
        revision=next_revision,
        balance=snapshot.balance + delta,
        as_of=as_of,
    )
