from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from enum import Enum
import hashlib
import re
from typing import Any

from .contracts import ContractError
from .ops_contracts import Money
from .ops_order_economics import SalesOrderReceivableHandoff
from .security import redact_secrets


_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,511}$")


def _ref(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_REF_RE.fullmatch(value.strip()):
        raise ContractError(f"{field_name} must be a bounded safe reference")
    value = value.strip()
    if redact_secrets(value) != value:
        raise ContractError(f"{field_name} must not contain credential material")
    return value


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ContractError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


class ReceivableStatus(str, Enum):
    OPEN = "open"
    DUE_SOON = "due_soon"
    OVERDUE = "overdue"
    PAID = "paid"


@dataclass(frozen=True, slots=True)
class TrustedPaymentObservation:
    observation_id: str
    workspace_id: str
    sales_order_id: str
    handoff_id: str
    amount_paid: Money
    observed_at: datetime
    authority_ref: str
    evidence_ref: str

    def __post_init__(self) -> None:
        for name in ("observation_id", "workspace_id", "sales_order_id", "handoff_id", "authority_ref", "evidence_ref"):
            object.__setattr__(self, name, _ref(getattr(self, name), name))
        if not isinstance(self.amount_paid, Money) or self.amount_paid.amount_minor < 0:
            raise ContractError("amount_paid must be non-negative Money")
        object.__setattr__(self, "observed_at", _aware(self.observed_at, "observed_at"))


@dataclass(frozen=True, slots=True)
class ReceivableProjection:
    handoff_id: str
    workspace_id: str
    sales_order_id: str
    status: ReceivableStatus
    total_amount: Money
    paid_amount: Money
    remaining_amount: Money
    expected_payment_date: date
    days_overdue: int

    def safe_dict(self) -> dict[str, Any]:
        return {
            "handoff_id": self.handoff_id,
            "workspace_id": self.workspace_id,
            "sales_order_id": self.sales_order_id,
            "status": self.status.value,
            "total_amount": self.total_amount.safe_dict(),
            "paid_amount": self.paid_amount.safe_dict(),
            "remaining_amount": self.remaining_amount.safe_dict(),
            "expected_payment_date": self.expected_payment_date.isoformat(),
            "days_overdue": self.days_overdue,
            "message_inferred_payment": False,
            "accounting_write": False,
            "payment_collection": False,
        }


@dataclass(frozen=True, slots=True)
class ReceivableReminderDraft:
    reminder_id: str
    handoff_id: str
    sales_order_id: str
    customer_id: str
    status: ReceivableStatus
    remaining_amount: Money
    expected_payment_date: date
    approval_required: bool = True

    def __post_init__(self) -> None:
        for name in ("reminder_id", "handoff_id", "sales_order_id", "customer_id"):
            object.__setattr__(self, name, _ref(getattr(self, name), name))
        if self.status not in {ReceivableStatus.DUE_SOON, ReceivableStatus.OVERDUE}:
            raise ContractError("reminder draft requires due-soon or overdue receivable")
        if self.remaining_amount.amount_minor <= 0:
            raise ContractError("reminder requires positive remaining amount")
        if self.approval_required is not True:
            raise ContractError("receivable reminder must require approval")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "reminder_id": self.reminder_id,
            "handoff_id": self.handoff_id,
            "sales_order_id": self.sales_order_id,
            "customer_id": self.customer_id,
            "status": self.status.value,
            "remaining_amount": self.remaining_amount.safe_dict(),
            "expected_payment_date": self.expected_payment_date.isoformat(),
            "approval_required": True,
            "auto_send": False,
        }


def project_receivable(
    *,
    handoff: SalesOrderReceivableHandoff,
    as_of: date,
    payments: tuple[TrustedPaymentObservation, ...] = (),
    due_soon_days: int = 3,
) -> ReceivableProjection:
    if not isinstance(handoff, SalesOrderReceivableHandoff):
        raise ContractError("handoff must be SalesOrderReceivableHandoff")
    if not isinstance(as_of, date):
        raise ContractError("as_of must be date")
    if isinstance(due_soon_days, bool) or not isinstance(due_soon_days, int) or not 0 <= due_soon_days <= 30:
        raise ContractError("due_soon_days must be between 0 and 30")
    paid_minor = 0
    seen: set[str] = set()
    for item in payments:
        if not isinstance(item, TrustedPaymentObservation):
            raise ContractError("payments must contain TrustedPaymentObservation")
        if item.observation_id in seen:
            raise ContractError("duplicate payment observation")
        seen.add(item.observation_id)
        if item.workspace_id != handoff.workspace_id or item.sales_order_id != handoff.sales_order_id or item.handoff_id != handoff.handoff_id:
            raise ContractError("payment observation does not bind exact receivable")
        if item.amount_paid.currency != handoff.amount.currency:
            raise ContractError("payment currency mismatch")
        paid_minor += item.amount_paid.amount_minor
    if paid_minor > handoff.amount.amount_minor:
        raise ContractError("trusted payments exceed receivable amount")
    remaining = handoff.amount.amount_minor - paid_minor
    if remaining == 0:
        status = ReceivableStatus.PAID
        overdue = 0
    elif as_of > handoff.expected_payment_date:
        status = ReceivableStatus.OVERDUE
        overdue = (as_of - handoff.expected_payment_date).days
    elif (handoff.expected_payment_date - as_of).days <= due_soon_days:
        status = ReceivableStatus.DUE_SOON
        overdue = 0
    else:
        status = ReceivableStatus.OPEN
        overdue = 0
    return ReceivableProjection(
        handoff_id=handoff.handoff_id,
        workspace_id=handoff.workspace_id,
        sales_order_id=handoff.sales_order_id,
        status=status,
        total_amount=handoff.amount,
        paid_amount=Money(paid_minor, handoff.amount.currency),
        remaining_amount=Money(remaining, handoff.amount.currency),
        expected_payment_date=handoff.expected_payment_date,
        days_overdue=overdue,
    )


def build_receivable_reminder(*, handoff: SalesOrderReceivableHandoff, projection: ReceivableProjection) -> ReceivableReminderDraft:
    if projection.handoff_id != handoff.handoff_id or projection.sales_order_id != handoff.sales_order_id:
        raise ContractError("projection does not belong to receivable handoff")
    digest = hashlib.sha256(
        f"{handoff.handoff_id}:{projection.status.value}:{projection.remaining_amount.amount_minor}:{projection.expected_payment_date.isoformat()}".encode("utf-8")
    ).hexdigest()[:24]
    return ReceivableReminderDraft(
        reminder_id=f"receivable-reminder:{digest}",
        handoff_id=handoff.handoff_id,
        sales_order_id=handoff.sales_order_id,
        customer_id=handoff.customer_id,
        status=projection.status,
        remaining_amount=projection.remaining_amount,
        expected_payment_date=projection.expected_payment_date,
    )


MESSAGE_INFERRED_PAYMENT_SUPPORTED = False
AUTO_RECEIVABLE_REMINDER_SEND_SUPPORTED = False
PAYMENT_COLLECTION_SUPPORTED = False
ACCOUNTING_WRITE_FROM_RECEIVABLE_SUPPORTED = False
