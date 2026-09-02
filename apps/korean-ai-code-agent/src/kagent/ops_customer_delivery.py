from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from enum import Enum
import re
from typing import Any

from .contracts import ContractError
from .ops_customer_acceptance import SalesOrderProjection
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


class CustomerDeliveryStatus(str, Enum):
    ON_TRACK = "on_track"
    DUE_SOON = "due_soon"
    OVERDUE = "overdue"
    DELIVERED = "delivered"


@dataclass(frozen=True, slots=True)
class TrustedCustomerDeliveryCommitment:
    commitment_ref: str
    workspace_id: str
    sales_order_id: str
    customer_id: str
    customer_quote_id: str
    customer_quote_version: int
    promised_date: date
    authority_ref: str
    evidence_ref: str

    def __post_init__(self) -> None:
        for name in ("commitment_ref", "workspace_id", "sales_order_id", "customer_id", "customer_quote_id", "authority_ref", "evidence_ref"):
            object.__setattr__(self, name, _ref(getattr(self, name), name))
        if isinstance(self.customer_quote_version, bool) or not isinstance(self.customer_quote_version, int) or self.customer_quote_version < 1:
            raise ContractError("customer_quote_version must be positive")
        if not isinstance(self.promised_date, date):
            raise ContractError("promised_date must be date")

    @classmethod
    def bind(cls, *, commitment_ref: str, sales_order: SalesOrderProjection, promised_date: date, authority_ref: str, evidence_ref: str) -> "TrustedCustomerDeliveryCommitment":
        if not isinstance(sales_order, SalesOrderProjection):
            raise ContractError("sales_order must be SalesOrderProjection")
        return cls(
            commitment_ref=commitment_ref,
            workspace_id=sales_order.workspace_id,
            sales_order_id=sales_order.sales_order_id,
            customer_id=sales_order.customer_id,
            customer_quote_id=sales_order.customer_quote_id,
            customer_quote_version=sales_order.customer_quote_version,
            promised_date=promised_date,
            authority_ref=authority_ref,
            evidence_ref=evidence_ref,
        )


@dataclass(frozen=True, slots=True)
class TrustedCustomerDeliveryObservation:
    observation_id: str
    workspace_id: str
    sales_order_id: str
    delivered_date: date
    observed_at: datetime
    authority_ref: str
    evidence_ref: str

    def __post_init__(self) -> None:
        for name in ("observation_id", "workspace_id", "sales_order_id", "authority_ref", "evidence_ref"):
            object.__setattr__(self, name, _ref(getattr(self, name), name))
        if not isinstance(self.delivered_date, date):
            raise ContractError("delivered_date must be date")
        object.__setattr__(self, "observed_at", _aware(self.observed_at, "observed_at"))


@dataclass(frozen=True, slots=True)
class CustomerDeliveryProjection:
    sales_order_id: str
    customer_id: str
    promised_date: date
    status: CustomerDeliveryStatus
    delivered_date: date | None
    days_overdue: int

    def safe_dict(self) -> dict[str, Any]:
        return {
            "sales_order_id": self.sales_order_id,
            "customer_id": self.customer_id,
            "promised_date": self.promised_date.isoformat(),
            "status": self.status.value,
            "delivered_date": self.delivered_date.isoformat() if self.delivered_date else None,
            "days_overdue": self.days_overdue,
            "supplier_eta_used_as_customer_promise": False,
            "auto_customer_send": False,
            "refund_authority": False,
            "fulfillment_authority": False,
        }


def project_customer_delivery(*, sales_order: SalesOrderProjection, commitment: TrustedCustomerDeliveryCommitment, as_of: date, observation: TrustedCustomerDeliveryObservation | None = None, due_soon_days: int = 3) -> CustomerDeliveryProjection:
    if not isinstance(sales_order, SalesOrderProjection):
        raise ContractError("sales_order must be SalesOrderProjection")
    if not isinstance(commitment, TrustedCustomerDeliveryCommitment):
        raise ContractError("commitment must be TrustedCustomerDeliveryCommitment")
    if not isinstance(as_of, date):
        raise ContractError("as_of must be date")
    if isinstance(due_soon_days, bool) or not isinstance(due_soon_days, int) or not 0 <= due_soon_days <= 30:
        raise ContractError("due_soon_days must be between 0 and 30")
    if (
        commitment.workspace_id != sales_order.workspace_id
        or commitment.sales_order_id != sales_order.sales_order_id
        or commitment.customer_id != sales_order.customer_id
        or commitment.customer_quote_id != sales_order.customer_quote_id
        or commitment.customer_quote_version != sales_order.customer_quote_version
    ):
        raise ContractError("customer delivery commitment does not bind exact sales order")
    delivered_date = None
    if observation is not None:
        if not isinstance(observation, TrustedCustomerDeliveryObservation):
            raise ContractError("observation must be TrustedCustomerDeliveryObservation")
        if observation.workspace_id != sales_order.workspace_id or observation.sales_order_id != sales_order.sales_order_id:
            raise ContractError("delivery observation does not bind exact sales order")
        delivered_date = observation.delivered_date
        status = CustomerDeliveryStatus.DELIVERED
        overdue = max(0, (delivered_date - commitment.promised_date).days)
    elif as_of > commitment.promised_date:
        status = CustomerDeliveryStatus.OVERDUE
        overdue = (as_of - commitment.promised_date).days
    elif (commitment.promised_date - as_of).days <= due_soon_days:
        status = CustomerDeliveryStatus.DUE_SOON
        overdue = 0
    else:
        status = CustomerDeliveryStatus.ON_TRACK
        overdue = 0
    return CustomerDeliveryProjection(
        sales_order_id=sales_order.sales_order_id,
        customer_id=sales_order.customer_id,
        promised_date=commitment.promised_date,
        status=status,
        delivered_date=delivered_date,
        days_overdue=overdue,
    )


SUPPLIER_ETA_AUTO_PROMOTION_SUPPORTED = False
AUTO_CUSTOMER_DELIVERY_MESSAGE_SUPPORTED = False
REFUND_AUTHORITY_SUPPORTED = False
FULFILLMENT_MUTATION_SUPPORTED = False
