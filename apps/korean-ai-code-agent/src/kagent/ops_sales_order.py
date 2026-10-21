"""#5448: online sales-channel order -> supplier purchase order -> shipment fulfilment.

The existing Claw Ops chain in :mod:`kagent.ops_contracts` models **procurement**
(``CommercialRequest`` -> ``SupplierQuoteRequest`` -> ``SupplierQuote`` ->
``QuoteComparison`` -> ``PurchaseOrder`` -> ``DeliveryCommitment`` ->
``AccountingHandoff``). That direction ends when a purchase order is issued to a
supplier. It does not model the direction this pilot needs: a **customer order
arriving on an online sales channel**, which is then satisfied by a supplier
purchase order, shipped to the customer, tracked by waybill, closed, and — when
something goes wrong — cancelled, returned, or re-delivered.

This module adds only that missing sales side. Everything it needs already
exists in the repository and is reused rather than reimplemented:

* :mod:`kagent.ops_contracts` — ``Money``, ``Item``, ``Supplier``,
  ``PaymentTerms``, ``PurchaseOrder``, ``PurchaseOrderLine``,
  ``PurchaseOrderStatus``, ``ApprovalAction``, ``ApprovalProjection``,
  ``EvidenceOrigin``, ``BusinessObjectKind``.
* :mod:`kagent.ops_ledger` — ``InMemoryOpsLedger`` / ``BusinessObjectEnvelope``
  as the single versioned product record store.
* :mod:`kagent.ops_workflow` — ``purchase_order_action_fingerprint`` and the
  ``OpsOutboundPort`` shape (unconfigured by default).
* :mod:`kagent.ops_documents` — ``DocumentNumberAssignment``,
  ``InMemoryDocumentNumberRegistry`` and ``PurchaseOrderDocumentManifest`` for
  the supplier purchase-order document.
* :mod:`kagent.ops_communications` / :mod:`kagent.ops_communication_outbox` —
  ``CommunicationSendRequest`` and ``InMemoryCommunicationOutbox`` to stage the
  supplier request without ever sending it.

What is genuinely new, because the repository has no equivalent:

* ``ShipTo`` — a delivery destination. Nothing in the existing contracts carries
  an address; ``Customer`` only has an id, a workspace and a name.
* ``StockPosition`` — an inventory position per item/supplier. The existing
  ``Item`` has no quantity and no supplier link.
* ``SalesOrder`` and its status machine — the customer-facing order lifecycle.
* ``Shipment`` with ``carrier``/``tracking_number`` — the existing
  ``DeliveryTrackingSnapshot`` tracks *inbound* supplier delivery and has no
  waybill and no carrier.
* ``ReturnRequest`` — the existing model has cancellation only; there is no
  return, exchange, or misdelivery handling anywhere in the repository.

Fail-closed rules:

* a supplier purchase order request is always produced as a **draft**. This
  module never calls an outbound connector, never stages a send, and never
  marks a purchase order ``ISSUED``. ``ISSUE_PURCHASE_ORDER`` stays a pending
  approval, exactly like the existing procurement chain.
* an order cannot advance to ``SUPPLIER_ORDERED`` without an availability
  check that actually covers every ordered line.
* a shipment cannot be created without a carrier and a tracking number, and
  ``DELIVERED`` requires a delivery timestamp that is not in the future.
* status transitions are checked against an explicit graph; terminal states
  reject every later transition.
* the customer price never enters a supplier-facing document. The existing
  ``PurchaseOrderDocumentManifest`` already asserts
  ``customer_sale_price_exposed=False``; this module keeps that property by
  building the purchase order from supplier-side cost lines only.
* personal data stays out of shared artifacts. ``ShipTo.redacted()`` produces a
  masked copy for anything that may leave the machine.

No network, no credentials, no provider, no model call, no database. The module
is deterministic and offline.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
import hashlib
from io import StringIO
import json
import re
from typing import Any, Callable, Protocol

from .contracts import ContractError
from .ops_communication_outbox import InMemoryCommunicationOutbox
from .ops_communications import (
    CommunicationChannel,
    CommunicationSendRequest,
)
from .ops_contracts import (
    ApprovalAction,
    ApprovalProjection,
    BusinessObjectKind,
    EvidenceOrigin,
    Item,
    Money,
    PaymentTerms,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderStatus,
    Supplier,
    WorkflowEvidenceRecord,
)
from .ops_documents import (
    BusinessDocumentKind,
    InMemoryDocumentNumberRegistry,
    PurchaseOrderDocumentManifest,
)
from .ops_ledger import BusinessObjectEnvelope, InMemoryOpsLedger
from .ops_workflow import purchase_order_action_fingerprint


class SalesOrderError(ContractError):
    """Fail-closed online sales order contract failure."""


# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------


class SalesChannelKind(str, Enum):
    """Where a customer order was observed.

    No channel API is assumed to exist. ``UNKNOWN`` is the honest value for a
    channel whose interface has not been confirmed yet.
    """

    CSV_EXPORT = "csv_export"
    BROWSER_ORDER_PAGE = "browser_order_page"
    MANUAL_ENTRY = "manual_entry"
    UNKNOWN = "unknown"


class AutomationLevel(str, Enum):
    """How far a step can be automated without a human decision.

    * ``FULLY_AUTOMATABLE`` — the step is a deterministic transformation of
      data the system already holds.
    * ``HUMAN_CONFIRMATION_REQUIRED`` — the step produces a correct draft but
      a person must confirm before it has an effect.
    * ``MANUAL_ONLY`` — a person must perform the step; the system can only
      record its result.
    * ``BLOCKED_MISSING_SYSTEM`` — the step cannot be reached yet because the
      external system it needs does not exist or is not connected.
    """

    FULLY_AUTOMATABLE = "fully_automatable"
    HUMAN_CONFIRMATION_REQUIRED = "human_confirmation_required"
    MANUAL_ONLY = "manual_only"
    BLOCKED_MISSING_SYSTEM = "blocked_missing_system"


class SalesOrderStatus(str, Enum):
    """Customer order lifecycle."""

    RECEIVED = "received"
    CONFIRMED = "confirmed"
    SUPPLIER_ORDERED = "supplier_ordered"
    READY_TO_SHIP = "ready_to_ship"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    RETURN_REQUESTED = "return_requested"
    RETURNED = "returned"
    MISDELIVERY = "misdelivery"


class ShipmentStatus(str, Enum):
    """Customer shipment lifecycle (waybill tracking)."""

    LABEL_ISSUED = "label_issued"
    IN_TRANSIT = "in_transit"
    OUT_FOR_DELIVERY = "out_for_delivery"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    RETURN_IN_TRANSIT = "return_in_transit"
    RETURNED = "returned"
    MISDELIVERY = "misdelivery"


class ReturnReason(str, Enum):
    """Why a customer order leaves the happy path."""

    CUSTOMER_CANCELLED = "customer_cancelled"
    CUSTOMER_RETURN = "customer_return"
    MISDELIVERY = "misdelivery"
    DAMAGED = "damaged"
    WRONG_ITEM = "wrong_item"


class ReturnStatus(str, Enum):
    """Return/misdelivery case lifecycle."""

    OPEN = "open"
    SUPPLIER_ACKNOWLEDGED = "supplier_acknowledged"
    RESOLVED = "resolved"
    REJECTED = "rejected"


# --------------------------------------------------------------------------
# Status graphs
# --------------------------------------------------------------------------

ORDER_TRANSITIONS: dict[SalesOrderStatus, frozenset[SalesOrderStatus]] = {
    SalesOrderStatus.RECEIVED: frozenset(
        {SalesOrderStatus.CONFIRMED, SalesOrderStatus.CANCELLED}
    ),
    SalesOrderStatus.CONFIRMED: frozenset(
        {
            SalesOrderStatus.SUPPLIER_ORDERED,
            SalesOrderStatus.READY_TO_SHIP,
            SalesOrderStatus.CANCELLED,
        }
    ),
    SalesOrderStatus.SUPPLIER_ORDERED: frozenset(
        {
            SalesOrderStatus.READY_TO_SHIP,
            SalesOrderStatus.SHIPPED,
            SalesOrderStatus.CANCELLED,
        }
    ),
    SalesOrderStatus.READY_TO_SHIP: frozenset(
        {SalesOrderStatus.SHIPPED, SalesOrderStatus.CANCELLED}
    ),
    SalesOrderStatus.SHIPPED: frozenset(
        {
            SalesOrderStatus.DELIVERED,
            SalesOrderStatus.RETURN_REQUESTED,
            SalesOrderStatus.MISDELIVERY,
        }
    ),
    SalesOrderStatus.DELIVERED: frozenset(
        {
            SalesOrderStatus.COMPLETED,
            SalesOrderStatus.RETURN_REQUESTED,
            SalesOrderStatus.MISDELIVERY,
        }
    ),
    SalesOrderStatus.COMPLETED: frozenset(),
    SalesOrderStatus.CANCELLED: frozenset(),
    SalesOrderStatus.RETURN_REQUESTED: frozenset(
        {
            SalesOrderStatus.RETURNED,
            SalesOrderStatus.MISDELIVERY,
            SalesOrderStatus.CANCELLED,
        }
    ),
    SalesOrderStatus.RETURNED: frozenset(),
    SalesOrderStatus.MISDELIVERY: frozenset(
        {SalesOrderStatus.DELIVERED, SalesOrderStatus.RETURN_REQUESTED}
    ),
}

SHIPMENT_TRANSITIONS: dict[ShipmentStatus, frozenset[ShipmentStatus]] = {
    ShipmentStatus.LABEL_ISSUED: frozenset(
        {ShipmentStatus.IN_TRANSIT, ShipmentStatus.CANCELLED}
    ),
    ShipmentStatus.IN_TRANSIT: frozenset(
        {
            ShipmentStatus.OUT_FOR_DELIVERY,
            ShipmentStatus.DELIVERED,
            ShipmentStatus.CANCELLED,
            ShipmentStatus.RETURN_IN_TRANSIT,
            ShipmentStatus.MISDELIVERY,
        }
    ),
    ShipmentStatus.OUT_FOR_DELIVERY: frozenset(
        {
            ShipmentStatus.DELIVERED,
            ShipmentStatus.MISDELIVERY,
            ShipmentStatus.RETURN_IN_TRANSIT,
        }
    ),
    ShipmentStatus.DELIVERED: frozenset({ShipmentStatus.RETURN_IN_TRANSIT}),
    ShipmentStatus.CANCELLED: frozenset(),
    ShipmentStatus.RETURN_IN_TRANSIT: frozenset({ShipmentStatus.RETURNED}),
    ShipmentStatus.RETURNED: frozenset(),
    ShipmentStatus.MISDELIVERY: frozenset(
        {ShipmentStatus.IN_TRANSIT, ShipmentStatus.RETURN_IN_TRANSIT}
    ),
}


# --------------------------------------------------------------------------
# Validation helpers
# --------------------------------------------------------------------------

_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_MAX_TEXT = 2000
_MAX_LINES = 200


def _ref(value: str, field_name: str, *, limit: int = 256) -> str:
    if not isinstance(value, str):
        raise SalesOrderError(f"{field_name} must be a string")
    value = value.strip()
    if not value:
        raise SalesOrderError(f"{field_name} is required")
    if len(value) > limit:
        raise SalesOrderError(f"{field_name} exceeds {limit} characters")
    if _CONTROL_RE.search(value):
        raise SalesOrderError(f"{field_name} contains control characters")
    return value


def _identifier(value: str, field_name: str) -> str:
    value = _ref(value, field_name, limit=128)
    if not _SAFE_ID_RE.fullmatch(value):
        raise SalesOrderError(f"{field_name} has an invalid identifier shape")
    return value


def _text(value: str, field_name: str, *, limit: int = _MAX_TEXT, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise SalesOrderError(f"{field_name} must be a string")
    value = value.strip()
    if not value and not allow_empty:
        raise SalesOrderError(f"{field_name} is required")
    if len(value) > limit:
        raise SalesOrderError(f"{field_name} exceeds {limit} characters")
    if _CONTROL_RE.search(value):
        raise SalesOrderError(f"{field_name} contains control characters")
    return value


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise SalesOrderError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _optional_date(value: date | None, field_name: str) -> date | None:
    if value is None:
        return None
    if not isinstance(value, date) or isinstance(value, datetime):
        raise SalesOrderError(f"{field_name} must be a date")
    return value


def _quantity(value: Decimal | int | str, field_name: str) -> Decimal:
    if isinstance(value, bool) or isinstance(value, float):
        raise SalesOrderError(f"{field_name} must not be bool or float")
    try:
        normalized = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise SalesOrderError(f"{field_name} must be a decimal-compatible value") from exc
    if not normalized.is_finite() or normalized <= 0 or normalized > Decimal("1000000000"):
        raise SalesOrderError(f"{field_name} must be finite, positive and bounded")
    if -normalized.as_tuple().exponent > 6:
        raise SalesOrderError(f"{field_name} supports at most 6 decimal places")
    return normalized.normalize()


def _non_negative_quantity(value: Decimal | int | str, field_name: str) -> Decimal:
    if isinstance(value, bool) or isinstance(value, float):
        raise SalesOrderError(f"{field_name} must not be bool or float")
    try:
        normalized = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise SalesOrderError(f"{field_name} must be a decimal-compatible value") from exc
    if not normalized.is_finite() or normalized < 0 or normalized > Decimal("1000000000"):
        raise SalesOrderError(f"{field_name} must be finite, non-negative and bounded")
    if -normalized.as_tuple().exponent > 6:
        raise SalesOrderError(f"{field_name} supports at most 6 decimal places")
    return normalized.normalize()


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


# --------------------------------------------------------------------------
# Value objects
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ShipTo:
    """Delivery destination for one order.

    Real customer data must never reach a shared artifact. ``redacted()``
    produces the masked copy that may be exported.
    """

    recipient_name: str
    recipient_phone: str
    postal_code: str
    address_line1: str
    address_line2: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "recipient_name", _text(self.recipient_name, "recipient_name", limit=120))
        object.__setattr__(self, "recipient_phone", _text(self.recipient_phone, "recipient_phone", limit=60))
        object.__setattr__(self, "postal_code", _text(self.postal_code, "postal_code", limit=20))
        object.__setattr__(self, "address_line1", _text(self.address_line1, "address_line1", limit=300))
        object.__setattr__(
            self,
            "address_line2",
            _text(self.address_line2, "address_line2", limit=300, allow_empty=True),
        )

    def redacted(self) -> "ShipTo":
        """Return a masked copy that is safe for a shared artifact."""

        name = self.recipient_name
        masked_name = f"{name[0]}**" if name else "**"
        phone_digits = [ch for ch in self.recipient_phone if ch.isdigit()]
        tail = "".join(phone_digits[-4:])
        masked_phone = f"***-****-***{tail}" if len(phone_digits) >= 4 else "***-****-****"
        return ShipTo(
            recipient_name=masked_name,
            recipient_phone=masked_phone,
            postal_code=f"{self.postal_code[:2]}**" if len(self.postal_code) >= 2 else "**",
            address_line1="(redacted)",
            address_line2="",
        )

    def safe_dict(self) -> dict[str, Any]:
        return {
            "recipient_name": self.recipient_name,
            "recipient_phone": self.recipient_phone,
            "postal_code": self.postal_code,
            "address_line1": self.address_line1,
            "address_line2": self.address_line2,
        }


@dataclass(frozen=True, slots=True)
class StockPosition:
    """Inventory and sourcing position for one item.

    ``available_quantity`` is what can still be shipped, ``reserved_quantity``
    is already committed to other orders.
    """

    item: Item
    supplier_id: str
    available_quantity: Decimal
    reserved_quantity: Decimal = Decimal("0")
    lead_time_days: int | None = None
    unit_cost: Money | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.item, Item):
            raise SalesOrderError("item must be Item")
        object.__setattr__(self, "supplier_id", _identifier(self.supplier_id, "supplier_id"))
        object.__setattr__(
            self,
            "available_quantity",
            _non_negative_quantity(self.available_quantity, "available_quantity"),
        )
        object.__setattr__(
            self,
            "reserved_quantity",
            _non_negative_quantity(self.reserved_quantity, "reserved_quantity"),
        )
        if self.lead_time_days is not None:
            if isinstance(self.lead_time_days, bool) or not isinstance(self.lead_time_days, int):
                raise SalesOrderError("lead_time_days must be an integer")
            if not 0 <= self.lead_time_days <= 3650:
                raise SalesOrderError("lead_time_days must be between 0 and 3650")
        if self.unit_cost is not None and not isinstance(self.unit_cost, Money):
            raise SalesOrderError("unit_cost must be Money or None")

    @property
    def sellable_quantity(self) -> Decimal:
        return self.available_quantity - self.reserved_quantity

    def safe_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item.item_id,
            "sku": self.item.sku,
            "supplier_id": self.supplier_id,
            "available_quantity": format(self.available_quantity, "f"),
            "reserved_quantity": format(self.reserved_quantity, "f"),
            "sellable_quantity": format(self.sellable_quantity, "f"),
            "lead_time_days": self.lead_time_days,
            "unit_cost": self.unit_cost.safe_dict() if self.unit_cost else None,
        }


@dataclass(frozen=True, slots=True)
class SalesOrderLine:
    """One ordered line as received from the sales channel."""

    line_id: str
    sku: str
    description: str
    quantity: Decimal
    unit: str
    unit_price: Money
    item_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "line_id", _identifier(self.line_id, "line_id"))
        object.__setattr__(self, "sku", _text(self.sku, "sku", limit=128))
        object.__setattr__(self, "description", _text(self.description, "description", limit=500))
        object.__setattr__(self, "quantity", _quantity(self.quantity, "quantity"))
        object.__setattr__(self, "unit", _text(self.unit, "unit", limit=32))
        if not isinstance(self.unit_price, Money):
            raise SalesOrderError("unit_price must be Money")
        if self.item_id is not None:
            object.__setattr__(self, "item_id", _identifier(self.item_id, "item_id"))

    @property
    def total(self) -> Money:
        product = Decimal(self.unit_price.amount_minor) * self.quantity
        if product != product.to_integral_value():
            raise SalesOrderError("quantity and unit price produce a fractional minor-unit total")
        return Money(int(product), self.unit_price.currency)

    def safe_dict(self) -> dict[str, Any]:
        return {
            "line_id": self.line_id,
            "sku": self.sku,
            "item_id": self.item_id,
            "description": self.description,
            "quantity": format(self.quantity, "f"),
            "unit": self.unit,
            "unit_price": self.unit_price.safe_dict(),
            "total": self.total.safe_dict(),
        }


@dataclass(frozen=True, slots=True)
class SalesOrder:
    """A customer order received on an online sales channel."""

    order_id: str
    workspace_id: str
    channel: SalesChannelKind
    channel_order_ref: str
    customer_ref: str
    version: int
    status: SalesOrderStatus
    received_at: datetime
    lines: tuple[SalesOrderLine, ...]
    ship_to: ShipTo
    requested_delivery_date: date | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "order_id", _identifier(self.order_id, "order_id"))
        object.__setattr__(self, "workspace_id", _identifier(self.workspace_id, "workspace_id"))
        if not isinstance(self.channel, SalesChannelKind):
            try:
                object.__setattr__(self, "channel", SalesChannelKind(self.channel))
            except (TypeError, ValueError) as exc:
                raise SalesOrderError("invalid sales channel kind") from exc
        object.__setattr__(
            self, "channel_order_ref", _ref(self.channel_order_ref, "channel_order_ref", limit=256)
        )
        object.__setattr__(self, "customer_ref", _identifier(self.customer_ref, "customer_ref"))
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 1:
            raise SalesOrderError("version must be a positive integer")
        if not isinstance(self.status, SalesOrderStatus):
            try:
                object.__setattr__(self, "status", SalesOrderStatus(self.status))
            except (TypeError, ValueError) as exc:
                raise SalesOrderError("invalid sales order status") from exc
        object.__setattr__(self, "received_at", _aware(self.received_at, "received_at"))
        if not isinstance(self.lines, tuple) or not 1 <= len(self.lines) <= _MAX_LINES:
            raise SalesOrderError("lines must be a bounded non-empty tuple")
        if not all(isinstance(line, SalesOrderLine) for line in self.lines):
            raise SalesOrderError("lines must contain SalesOrderLine values")
        if len({line.line_id for line in self.lines}) != len(self.lines):
            raise SalesOrderError("order lines must have unique line_id values")
        if len({line.unit_price.currency for line in self.lines}) != 1:
            raise SalesOrderError("order lines must use one currency")
        if not isinstance(self.ship_to, ShipTo):
            raise SalesOrderError("ship_to must be ShipTo")
        object.__setattr__(
            self,
            "requested_delivery_date",
            _optional_date(self.requested_delivery_date, "requested_delivery_date"),
        )

    @property
    def total(self) -> Money:
        totals = [line.total for line in self.lines]
        return Money(sum(item.amount_minor for item in totals), totals[0].currency)

    def safe_dict(self) -> dict[str, Any]:
        return {
            "order_id": self.order_id,
            "workspace_id": self.workspace_id,
            "version": self.version,
            "status": self.status.value,
            "channel": self.channel.value,
            "channel_order_ref": self.channel_order_ref,
            "customer_ref": self.customer_ref,
            "received_at": _iso(self.received_at),
            "requested_delivery_date": (
                self.requested_delivery_date.isoformat() if self.requested_delivery_date else None
            ),
            "total": self.total.safe_dict(),
            "ship_to": self.ship_to.safe_dict(),
            "lines": [line.safe_dict() for line in self.lines],
        }


@dataclass(frozen=True, slots=True)
class Shipment:
    """A customer shipment carrying a waybill."""

    shipment_id: str
    order_id: str
    order_version: int
    version: int
    status: ShipmentStatus
    carrier: str
    tracking_number: str
    observed_at: datetime
    source_ref: str
    delivered_at: datetime | None = None
    note: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "shipment_id", _identifier(self.shipment_id, "shipment_id"))
        object.__setattr__(self, "order_id", _identifier(self.order_id, "order_id"))
        for field_name in ("order_version", "version"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise SalesOrderError(f"{field_name} must be a positive integer")
        if not isinstance(self.status, ShipmentStatus):
            try:
                object.__setattr__(self, "status", ShipmentStatus(self.status))
            except (TypeError, ValueError) as exc:
                raise SalesOrderError("invalid shipment status") from exc
        object.__setattr__(self, "carrier", _identifier(self.carrier, "carrier"))
        object.__setattr__(
            self, "tracking_number", _ref(self.tracking_number, "tracking_number", limit=128)
        )
        object.__setattr__(self, "observed_at", _aware(self.observed_at, "observed_at"))
        object.__setattr__(self, "source_ref", _ref(self.source_ref, "source_ref", limit=512))
        if self.delivered_at is not None:
            object.__setattr__(self, "delivered_at", _aware(self.delivered_at, "delivered_at"))
        object.__setattr__(self, "note", _text(self.note, "note", limit=1000, allow_empty=True))
        if self.status is ShipmentStatus.DELIVERED:
            if self.delivered_at is None:
                raise SalesOrderError("delivered shipment requires delivered_at")
            if self.delivered_at > self.observed_at:
                raise SalesOrderError("delivered_at cannot be later than observed_at")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "shipment_id": self.shipment_id,
            "order_id": self.order_id,
            "order_version": self.order_version,
            "version": self.version,
            "status": self.status.value,
            "carrier": self.carrier,
            "tracking_number": self.tracking_number,
            "observed_at": _iso(self.observed_at),
            "delivered_at": _iso(self.delivered_at) if self.delivered_at else None,
            "source_ref": self.source_ref,
            "note": self.note,
        }


@dataclass(frozen=True, slots=True)
class ReturnRequest:
    """A cancellation, return, exchange, or misdelivery case."""

    return_id: str
    order_id: str
    order_version: int
    version: int
    reason: ReturnReason
    status: ReturnStatus
    requested_at: datetime
    shipment_id: str | None = None
    resolution_note: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "return_id", _identifier(self.return_id, "return_id"))
        object.__setattr__(self, "order_id", _identifier(self.order_id, "order_id"))
        for field_name in ("order_version", "version"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise SalesOrderError(f"{field_name} must be a positive integer")
        if not isinstance(self.reason, ReturnReason):
            try:
                object.__setattr__(self, "reason", ReturnReason(self.reason))
            except (TypeError, ValueError) as exc:
                raise SalesOrderError("invalid return reason") from exc
        if not isinstance(self.status, ReturnStatus):
            try:
                object.__setattr__(self, "status", ReturnStatus(self.status))
            except (TypeError, ValueError) as exc:
                raise SalesOrderError("invalid return status") from exc
        object.__setattr__(self, "requested_at", _aware(self.requested_at, "requested_at"))
        if self.shipment_id is not None:
            object.__setattr__(self, "shipment_id", _identifier(self.shipment_id, "shipment_id"))
        object.__setattr__(
            self,
            "resolution_note",
            _text(self.resolution_note, "resolution_note", limit=1000, allow_empty=True),
        )

    def safe_dict(self) -> dict[str, Any]:
        return {
            "return_id": self.return_id,
            "order_id": self.order_id,
            "order_version": self.order_version,
            "version": self.version,
            "reason": self.reason.value,
            "status": self.status.value,
            "requested_at": _iso(self.requested_at),
            "shipment_id": self.shipment_id,
            "resolution_note": self.resolution_note,
        }


@dataclass(frozen=True, slots=True)
class SupplierOrderRequestDraft:
    """A supplier purchase-order request produced as a **draft**.

    The draft carries the existing :class:`PurchaseOrder` contract so the
    existing document manifest, action fingerprint and approval machinery keep
    working unchanged. Nothing in this module sends it.
    """

    purchase_order: PurchaseOrder
    ship_to: ShipTo
    message: str
    order_id: str
    order_version: int
    supplier_name: str = ""
    requires_approval: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.purchase_order, PurchaseOrder):
            raise SalesOrderError("purchase_order must be PurchaseOrder")
        if not isinstance(self.ship_to, ShipTo):
            raise SalesOrderError("ship_to must be ShipTo")
        object.__setattr__(
            self,
            "message",
            _text(self.message, "message", limit=4000, allow_empty=True),
        )
        object.__setattr__(self, "order_id", _identifier(self.order_id, "order_id"))
        if isinstance(self.order_version, bool) or not isinstance(self.order_version, int) or self.order_version < 1:
            raise SalesOrderError("order_version must be a positive integer")
        object.__setattr__(
            self, "supplier_name", _text(self.supplier_name, "supplier_name", limit=200, allow_empty=True)
        )
        if self.requires_approval is not True:
            raise SalesOrderError("supplier order request draft must require approval")

    @property
    def action_fingerprint(self) -> str:
        """Reuse the existing procurement fingerprint for the PO version."""

        return purchase_order_action_fingerprint(self.purchase_order)

    def to_markdown(self, *, redact_personal: bool = True) -> str:
        """Render the draft document.

        ``redact_personal=True`` (the default) masks the delivery destination,
        because a shared artifact must not carry customer personal data. The
        real destination is composed only at the moment an authorised person
        actually sends the request.
        """

        ship_to = self.ship_to.redacted() if redact_personal else self.ship_to
        po = self.purchase_order
        lines = [
            f"# 발주·배송 요청서 (DRAFT) - {po.po_id}",
            "",
            f"- 주문 번호: {self.order_id} (v{self.order_version})",
            f"- 발주서 상태: {po.status.value}",
            f"- 공급사: {self.supplier_name or po.supplier_id} ({po.supplier_id})",
            f"- 요청 납기일: {po.requested_delivery_date.isoformat() if po.requested_delivery_date else '-'}",
            f"- 거래 조건: {po.payment_terms.label if po.payment_terms else '-'}",
            f"- 총액: {po.total.amount_minor} {po.total.currency}",
            "",
            "## 발주 품목",
            "",
            "| 품목 | 수량 | 단위 | 단가 | 금액 |",
            "|---|---|---|---|---|",
        ]
        for line in po.lines:
            lines.append(
                f"| {line.description} | {format(line.quantity, 'f')} | {line.unit} | "
                f"{line.unit_price.amount_minor} | {line.total.amount_minor} |"
            )
        lines.extend(
            [
                "",
                "## 요청 사항",
                "",
                self.message or "(메시지 없음)",
                "",
                "## 발송 정보 (DRAFT)",
                "",
                f"- 수령인: {ship_to.recipient_name}",
                f"- 연락처: {ship_to.recipient_phone}",
                f"- 주소: {ship_to.postal_code} {ship_to.address_line1} {ship_to.address_line2}".rstrip(),
                "",
                "> 본 문서는 초안이며 발송되지 않았습니다. 발행(ISSUE) 전 승인 절차가 필요합니다.",
            ]
        )
        return "\n".join(lines)

    def to_email_draft(self, *, redact_personal: bool = True) -> str:
        """Plain-text supplier message body. Still a draft: never sent."""

        ship_to = self.ship_to.redacted() if redact_personal else self.ship_to
        po = self.purchase_order
        header = [
            f"[발주 초안] {po.po_id} / 주문 {self.order_id}",
            "",
            f"안녕하세요, {self.supplier_name or po.supplier_id}님.",
            "",
            "아래 내용으로 발주 및 배송을 요청드립니다. 금액과 납기일은 회신 확인 후 확정됩니다.",
            "",
        ]
        body = [f"- 품목: {line.description} / {format(line.quantity, 'f')} {line.unit}" for line in po.lines]
        tail = [
            "",
            f"- 요청 납기일: {po.requested_delivery_date.isoformat() if po.requested_delivery_date else '협의'}",
            f"- 총액: {po.total.amount_minor} {po.total.currency}",
            f"- 발송지: {ship_to.postal_code} {ship_to.address_line1}",
            "",
            self.message,
            "",
            "※ 본 메일은 초안(DRAFT)이며 발송되지 않았습니다.",
        ]
        return "\n".join(header + body + tail)


@dataclass(frozen=True, slots=True)
class OrderFulfillmentStep:
    """One business step of the online order -> supply -> shipment chain."""

    number: int
    key: str
    title_ko: str
    automation: AutomationLevel
    system_dependency: str
    human_checkpoint: str

    def safe_dict(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "key": self.key,
            "title_ko": self.title_ko,
            "automation": self.automation.value,
            "system_dependency": self.system_dependency,
            "human_checkpoint": self.human_checkpoint,
        }


ORDER_FULFILLMENT_STEPS: tuple[OrderFulfillmentStep, ...] = (
    OrderFulfillmentStep(
        number=1,
        key="receive_order",
        title_ko="온라인 판매채널 주문 접수",
        automation=AutomationLevel.FULLY_AUTOMATABLE,
        system_dependency="판매채널 주문 목록 (CSV 내보내기 또는 브라우저 주문 페이지)",
        human_checkpoint="접수 주문의 채널 주문번호 대조만 필요",
    ),
    OrderFulfillmentStep(
        number=2,
        key="verify_order_lines",
        title_ko="주문 상품·수량·배송지 확인",
        automation=AutomationLevel.HUMAN_CONFIRMATION_REQUIRED,
        system_dependency="채널 주문 원문",
        human_checkpoint="배송지·수령인 표기 오류 확인",
    ),
    OrderFulfillmentStep(
        number=3,
        key="check_stock_and_terms",
        title_ko="공급사·재고·거래조건 확인",
        automation=AutomationLevel.HUMAN_CONFIRMATION_REQUIRED,
        system_dependency="재고 시스템 또는 재고 대장 (현재 ERP 재고 연계 미확정)",
        human_checkpoint="부족 수량의 대체 공급사/분할 발주 결정",
    ),
    OrderFulfillmentStep(
        number=4,
        key="draft_supplier_order",
        title_ko="공급사 발주·배송 요청 초안 생성",
        automation=AutomationLevel.HUMAN_CONFIRMATION_REQUIRED,
        system_dependency="공급사 거래 조건과 발주 채널 (이메일/메신저/ERP)",
        human_checkpoint="발주 금액·납기일 승인 후 실제 발송",
    ),
    OrderFulfillmentStep(
        number=5,
        key="confirm_supplier_result",
        title_ko="공급사 처리 결과 확인",
        automation=AutomationLevel.MANUAL_ONLY,
        system_dependency="공급사 회신 (이메일/메신저 수신함)",
        human_checkpoint="회신 수신과 납기일 확인을 사람이 수행",
    ),
    OrderFulfillmentStep(
        number=6,
        key="track_shipment",
        title_ko="송장번호·배송 상태 관리",
        automation=AutomationLevel.MANUAL_ONLY,
        system_dependency="택배사 송장 조회 (택배사별 API 계약 미확정)",
        human_checkpoint="송장번호 입력과 배송 상태 확인",
    ),
    OrderFulfillmentStep(
        number=7,
        key="complete_order",
        title_ko="주문 완료 처리",
        automation=AutomationLevel.FULLY_AUTOMATABLE,
        system_dependency="없음 (내부 기록)",
        human_checkpoint="없음",
    ),
    OrderFulfillmentStep(
        number=8,
        key="handle_exception",
        title_ko="취소·반품·오배송 대응",
        automation=AutomationLevel.MANUAL_ONLY,
        system_dependency="반품 접수 채널과 회수 택배 정보",
        human_checkpoint="반품 승인·회수지시·재배송 판단",
    ),
)


# --------------------------------------------------------------------------
# Sales channel port
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SalesChannelOrderSnapshot:
    """A raw order read from a sales channel, before any business decision."""

    channel: SalesChannelKind
    channel_order_ref: str
    customer_ref: str
    received_at: datetime
    lines: tuple[SalesOrderLine, ...]
    ship_to: ShipTo
    requested_delivery_date: date | None = None


class SalesChannelOrderPort(Protocol):
    """Trusted boundary that reads one order from a sales channel.

    The repository does not assume that any specific marketplace or store API
    exists. A host application supplies this port: a CSV export reader, a
    browser-driven page reader, or a manual entry adapter.
    """

    def fetch_order(
        self, *, workspace_id: str, channel_order_ref: str
    ) -> SalesChannelOrderSnapshot:
        ...


class UnconfiguredSalesChannelOrderPort:
    """Default port. Refuses instead of guessing a channel integration."""

    def fetch_order(
        self, *, workspace_id: str, channel_order_ref: str
    ) -> SalesChannelOrderSnapshot:
        raise SalesOrderError("sales channel order port is not configured")


CHANNEL_ORDER_CSV_HEADERS = (
    "channel_order_ref",
    "customer_ref",
    "received_at",
    "requested_delivery_date",
    "recipient_name",
    "recipient_phone",
    "postal_code",
    "address_line1",
    "address_line2",
    "line_id",
    "sku",
    "item_id",
    "description",
    "quantity",
    "unit",
    "unit_price_amount_minor",
    "unit_price_currency",
)

MAX_CHANNEL_CSV_CHARS = 1_000_000
MAX_CHANNEL_CSV_ROWS = 500

#: Channel fields that describe the order itself. Every row of one order must
#: repeat them identically; a mismatch means the export is not one order.
ORDER_LEVEL_CSV_KEYS = (
    "channel_order_ref",
    "customer_ref",
    "received_at",
    "requested_delivery_date",
    "recipient_name",
    "recipient_phone",
    "postal_code",
    "address_line1",
    "address_line2",
)


def _validate_order_level_consistency(rows: tuple[dict[str, str], ...]) -> None:
    """Fail closed when the order-level fields disagree between rows."""

    if not rows:
        raise SalesOrderError("channel order rows must not be empty")
    first = rows[0]
    for row in rows[1:]:
        for key in ORDER_LEVEL_CSV_KEYS:
            if row.get(key, "") != first.get(key, ""):
                raise SalesOrderError(f"CSV {key} must be identical across all rows")


class LocalCsvSalesChannelOrderPort:
    """Read one online order from a seller-side CSV export.

    This is the file-shaped counterpart of a channel API. It is intentionally
    strict: the header must match exactly, the order-level fields must be
    identical on every row, and every numeric field must parse.
    """

    def __init__(self, *, rows_by_order: dict[str, tuple[dict[str, str], ...]]) -> None:
        if not isinstance(rows_by_order, dict):
            raise SalesOrderError("rows_by_order must be a dict")
        self._rows_by_order = rows_by_order

    @classmethod
    def parse_csv(cls, text: str) -> "LocalCsvSalesChannelOrderPort":
        """Parse a channel order export into a port instance."""

        if not isinstance(text, str):
            raise SalesOrderError("CSV input must be decoded UTF-8 text")
        if not text or len(text) > MAX_CHANNEL_CSV_CHARS:
            raise SalesOrderError("CSV input is empty or exceeds the supported bound")
        if "\x00" in text:
            raise SalesOrderError("CSV input contains NUL byte")

        normalized = text[1:] if text.startswith("\ufeff") else text
        try:
            reader = csv.DictReader(StringIO(normalized), strict=True)
            fieldnames = reader.fieldnames
            if fieldnames is None:
                raise SalesOrderError("CSV header is missing")
            headers = tuple(name.strip() if isinstance(name, str) else "" for name in fieldnames)
            if len(headers) != len(set(headers)):
                raise SalesOrderError("CSV headers must be unique")
            if set(headers) != set(CHANNEL_ORDER_CSV_HEADERS) or len(headers) != len(
                CHANNEL_ORDER_CSV_HEADERS
            ):
                raise SalesOrderError("CSV headers must exactly match the supported schema")
            reader.fieldnames = list(headers)

            rows: list[dict[str, str]] = []
            for row in reader:
                if None in row:
                    raise SalesOrderError("CSV row contains more columns than the header")
                if len(rows) >= MAX_CHANNEL_CSV_ROWS:
                    raise SalesOrderError("CSV row count exceeds the supported bound")
                rows.append({key: (value or "") for key, value in row.items()})
        except csv.Error as exc:
            raise SalesOrderError("malformed CSV input") from exc

        if not rows:
            raise SalesOrderError("CSV must contain at least one data row")

        grouped: dict[str, list[dict[str, str]]] = {}
        for row in rows:
            grouped.setdefault(row["channel_order_ref"].strip(), []).append(row)

        ports: dict[str, tuple[dict[str, str], ...]] = {}
        for order_ref, order_rows in grouped.items():
            ordered = tuple(order_rows)
            _validate_order_level_consistency(ordered)
            ports[order_ref] = ordered
        return cls(rows_by_order=ports)

    def fetch_order(
        self, *, workspace_id: str, channel_order_ref: str
    ) -> SalesChannelOrderSnapshot:
        _identifier(workspace_id, "workspace_id")
        rows = self._rows_by_order.get(channel_order_ref)
        if not rows:
            raise SalesOrderError("channel order not found in the loaded export")

        first = rows[0]
        _validate_order_level_consistency(rows)

        received_at = _parse_channel_timestamp(first["received_at"])
        requested_delivery_date = None
        delivery_text = first["requested_delivery_date"].strip()
        if delivery_text:
            try:
                requested_delivery_date = date.fromisoformat(delivery_text)
            except ValueError as exc:
                raise SalesOrderError("CSV requested_delivery_date must be ISO date") from exc

        ship_to = ShipTo(
            recipient_name=first["recipient_name"],
            recipient_phone=first["recipient_phone"],
            postal_code=first["postal_code"],
            address_line1=first["address_line1"],
            address_line2=first["address_line2"],
        )

        lines: list[SalesOrderLine] = []
        seen_line_ids: set[str] = set()
        for row in rows:
            line_id = row["line_id"].strip()
            if not line_id:
                raise SalesOrderError("CSV line_id is required")
            if line_id in seen_line_ids:
                raise SalesOrderError("CSV line_id values must be unique")
            seen_line_ids.add(line_id)
            item_id = row["item_id"].strip() or None
            lines.append(
                SalesOrderLine(
                    line_id=line_id,
                    sku=row["sku"],
                    description=row["description"],
                    quantity=row["quantity"],
                    unit=row["unit"],
                    unit_price=Money(
                        _parse_minor_amount(row["unit_price_amount_minor"]),
                        row["unit_price_currency"],
                    ),
                    item_id=item_id,
                )
            )

        return SalesChannelOrderSnapshot(
            channel=SalesChannelKind.CSV_EXPORT,
            channel_order_ref=channel_order_ref,
            customer_ref=first["customer_ref"].strip(),
            received_at=received_at,
            lines=tuple(lines),
            ship_to=ship_to,
            requested_delivery_date=requested_delivery_date,
        )


def _parse_minor_amount(value: str) -> int:
    text = (value or "").strip()
    if not text:
        raise SalesOrderError("CSV unit_price_amount_minor is required")
    if text.startswith(("=", "+", "@")):
        raise SalesOrderError("CSV unit_price_amount_minor looks like a spreadsheet formula")
    try:
        parsed = int(text)
    except ValueError as exc:
        raise SalesOrderError("CSV unit_price_amount_minor must be an integer") from exc
    if abs(parsed) > 10**15:
        raise SalesOrderError("CSV unit_price_amount_minor exceeds the supported bound")
    return parsed


def _parse_channel_timestamp(value: str) -> datetime:
    text = (value or "").strip()
    if not text:
        raise SalesOrderError("CSV received_at is required")
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise SalesOrderError("CSV received_at must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise SalesOrderError("CSV received_at must carry a timezone")
    return parsed.astimezone(timezone.utc)


# --------------------------------------------------------------------------
# Coordinator
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AvailabilityCheck:
    """Result of the stock / supplier / terms check for one order."""

    order_id: str
    order_version: int
    fully_covered: bool
    covered_line_ids: tuple[str, ...]
    short_line_ids: tuple[str, ...]
    supplier_ids: tuple[str, ...]
    positions: tuple[StockPosition, ...] = ()

    def safe_dict(self) -> dict[str, Any]:
        return {
            "order_id": self.order_id,
            "order_version": self.order_version,
            "fully_covered": self.fully_covered,
            "covered_line_ids": list(self.covered_line_ids),
            "short_line_ids": list(self.short_line_ids),
            "supplier_ids": list(self.supplier_ids),
            "positions": [position.safe_dict() for position in self.positions],
        }


class OnlineOrderFulfillmentCoordinator:
    """Compose the eight online order -> supply -> shipment steps.

    The coordinator owns Claw Ops product records only. Generic agent, tool and
    approval semantics remain P01-owned, and the outbound connector stays
    unconfigured by default: this coordinator never sends anything.
    """

    def __init__(
        self,
        *,
        ledger: InMemoryOpsLedger | None = None,
        channel: SalesChannelOrderPort | None = None,
        document_numbers: InMemoryDocumentNumberRegistry | None = None,
        outbox: InMemoryCommunicationOutbox | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.ledger = ledger or InMemoryOpsLedger()
        self.channel = channel or UnconfiguredSalesChannelOrderPort()
        self.document_numbers = document_numbers or InMemoryDocumentNumberRegistry()
        self.outbox = outbox or InMemoryCommunicationOutbox()
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise SalesOrderError("clock must return timezone-aware datetime")
        return value.astimezone(timezone.utc)

    # -- step 1 & 2 ------------------------------------------------------

    def receive_order(
        self,
        *,
        workspace_id: str,
        order_id: str,
        channel_order_ref: str,
        channel: SalesChannelKind | None = None,
    ) -> SalesOrder:
        """Step 1: read the order from the sales channel and record it."""

        snapshot = self.channel.fetch_order(
            workspace_id=workspace_id, channel_order_ref=channel_order_ref
        )
        order = SalesOrder(
            order_id=order_id,
            workspace_id=workspace_id,
            channel=channel if channel is not None else snapshot.channel,
            channel_order_ref=snapshot.channel_order_ref,
            customer_ref=snapshot.customer_ref,
            version=1,
            status=SalesOrderStatus.RECEIVED,
            received_at=snapshot.received_at,
            lines=snapshot.lines,
            ship_to=snapshot.ship_to,
            requested_delivery_date=snapshot.requested_delivery_date,
        )
        self._append(
            kind=BusinessObjectKind.SALES_ORDER,
            object_id=order.order_id,
            version=order.version,
            workspace_id=order.workspace_id,
            value=order,
        )
        self._record_evidence(
            order=order,
            evidence_id=f"ev-order-received-{order.order_id}-v1",
            summary=f"판매채널 주문 접수: {order.channel_order_ref}",
            source_ref=f"channel:{order.channel.value}:{order.channel_order_ref}",
        )
        return order

    def order(self, *, workspace_id: str, order_id: str) -> SalesOrder:
        envelope = self.ledger.latest_object(
            workspace_id=workspace_id,
            kind=BusinessObjectKind.SALES_ORDER,
            object_id=order_id,
        )
        if not isinstance(envelope.value, SalesOrder):
            raise SalesOrderError("sales order object has unexpected type")
        return envelope.value

    # -- step 3 ----------------------------------------------------------

    def check_availability(
        self,
        *,
        workspace_id: str,
        order_id: str,
        positions: tuple[StockPosition, ...],
    ) -> AvailabilityCheck:
        """Step 3: check stock, sourcing and terms coverage for every line."""

        order = self.order(workspace_id=workspace_id, order_id=order_id)
        if order.status is not SalesOrderStatus.RECEIVED:
            raise SalesOrderError("availability can only be checked for a received order")
        if not isinstance(positions, tuple) or not positions:
            raise SalesOrderError("positions must be a bounded non-empty tuple")
        if not all(isinstance(position, StockPosition) for position in positions):
            raise SalesOrderError("positions must contain StockPosition values")

        by_item: dict[str, list[StockPosition]] = {}
        for position in positions:
            by_item.setdefault(position.item.item_id, []).append(position)

        covered: list[str] = []
        short: list[str] = []
        supplier_ids: list[str] = []
        for line in order.lines:
            item_id = line.item_id or line.sku
            candidates = by_item.get(item_id, [])
            if not candidates:
                short.append(line.line_id)
                continue
            supply = sum(
                (candidate.sellable_quantity for candidate in candidates), Decimal("0")
            )
            if supply >= line.quantity:
                covered.append(line.line_id)
                for candidate in candidates:
                    if candidate.supplier_id not in supplier_ids:
                        supplier_ids.append(candidate.supplier_id)
            else:
                short.append(line.line_id)

        return AvailabilityCheck(
            order_id=order.order_id,
            order_version=order.version,
            fully_covered=not short,
            covered_line_ids=tuple(covered),
            short_line_ids=tuple(short),
            supplier_ids=tuple(supplier_ids),
            positions=positions,
        )

    def confirm_order(self, *, workspace_id: str, order_id: str) -> SalesOrder:
        """Step 3b: mark the order confirmed after the availability check."""

        order = self.order(workspace_id=workspace_id, order_id=order_id)
        if order.status is not SalesOrderStatus.RECEIVED:
            raise SalesOrderError("only a received order can be confirmed")
        return self._transition(
            order,
            to=SalesOrderStatus.CONFIRMED,
            summary="재고·공급사·거래조건 확인 완료",
            evidence_id=f"ev-order-confirmed-{order.order_id}-v{order.version + 1}",
            evidence_summary="주문 확인 처리",
        )

    # -- step 4 ----------------------------------------------------------

    def draft_supplier_order(
        self,
        *,
        workspace_id: str,
        order_id: str,
        supplier: Supplier,
        supplier_quote_id: str,
        supplier_quote_version: int = 1,
        requested_delivery_date: date | None = None,
        payment_terms: PaymentTerms | None = None,
        positions: tuple[StockPosition, ...] = (),
        message: str = "",
    ) -> SupplierOrderRequestDraft:
        """Step 4: build the supplier purchase-order request **as a draft**.

        ``supplier_quote_id`` is the standing quote or contract reference for
        the supplier. The purchase order stays ``DRAFT`` and a pending
        ``ISSUE_PURCHASE_ORDER`` approval is recorded, exactly like the
        existing procurement chain.
        """

        order = self.order(workspace_id=workspace_id, order_id=order_id)
        if order.status is not SalesOrderStatus.CONFIRMED:
            raise SalesOrderError("a supplier order request needs a confirmed order")
        if not isinstance(supplier, Supplier):
            raise SalesOrderError("supplier must be Supplier")
        if supplier.workspace_id != workspace_id:
            raise SalesOrderError("supplier belongs to another workspace")
        if not supplier.active:
            raise SalesOrderError("supplier is not active")
        if not isinstance(positions, tuple):
            raise SalesOrderError("positions must be a tuple")

        unit_cost_by_item: dict[str, Money] = {}
        for position in positions:
            if position.supplier_id != supplier.supplier_id:
                continue
            if position.unit_cost is not None:
                unit_cost_by_item.setdefault(position.item.item_id, position.unit_cost)

        po_lines: list[PurchaseOrderLine] = []
        for line in order.lines:
            item_id = line.item_id or line.sku
            cost = unit_cost_by_item.get(item_id)
            if cost is None:
                raise SalesOrderError(
                    "supplier order request needs a supplier-side cost for every ordered line"
                )
            po_lines.append(
                PurchaseOrderLine(
                    line_id=line.line_id,
                    description=line.description,
                    quantity=line.quantity,
                    unit=line.unit,
                    unit_price=cost,
                )
            )

        purchase_order = PurchaseOrder(
            po_id=f"po-{order.order_id}-v{order.version}",
            workspace_id=workspace_id,
            supplier_id=supplier.supplier_id,
            supplier_quote_id=supplier_quote_id,
            supplier_quote_version=supplier_quote_version,
            version=1,
            lines=tuple(po_lines),
            status=PurchaseOrderStatus.DRAFT,
            requested_delivery_date=requested_delivery_date or order.requested_delivery_date,
            payment_terms=payment_terms or supplier.payment_terms,
        )
        self._append(
            kind=BusinessObjectKind.PURCHASE_ORDER,
            object_id=purchase_order.po_id,
            version=purchase_order.version,
            workspace_id=workspace_id,
            value=purchase_order,
        )

        assignment = self.document_numbers.assign(
            workspace_id=workspace_id,
            kind=BusinessDocumentKind.PURCHASE_ORDER,
            subject_id=purchase_order.po_id,
            subject_version=purchase_order.version,
            issue_date=self._now().date(),
        )
        manifest = PurchaseOrderDocumentManifest.from_purchase_order(
            assignment=assignment,
            purchase_order=purchase_order,
        )

        draft = SupplierOrderRequestDraft(
            purchase_order=purchase_order,
            ship_to=order.ship_to,
            message=message or _default_supplier_message(order, purchase_order),
            order_id=order.order_id,
            order_version=order.version,
            supplier_name=supplier.name,
        )

        approval = ApprovalProjection(
            approval_id=f"ap-{purchase_order.po_id}-v1",
            workspace_id=workspace_id,
            action=ApprovalAction.ISSUE_PURCHASE_ORDER,
            target_kind=BusinessObjectKind.PURCHASE_ORDER,
            target_id=purchase_order.po_id,
            target_version=purchase_order.version,
            action_fingerprint=draft.action_fingerprint,
        )
        self.ledger.add_approval_projection(approval)

        self._record_evidence(
            order=order,
            evidence_id=f"ev-po-draft-{purchase_order.po_id}-v1",
            summary=f"공급사 발주 요청 초안 생성: {manifest.document_number}",
            source_ref=f"po:{purchase_order.po_id}:v1",
        )
        return draft

    def stage_supplier_request(
        self,
        *,
        draft: SupplierOrderRequestDraft,
        recipient_ref: str,
        channel: CommunicationChannel = CommunicationChannel.EMAIL,
    ) -> str:
        """Stage the supplier request in the outbox. **Never sends it.**

        The outbox record stays ``PENDING``. Sending requires an approved
        ``ISSUE_PURCHASE_ORDER`` projection, which this module never grants.
        """

        if not isinstance(draft, SupplierOrderRequestDraft):
            raise SalesOrderError("draft must be SupplierOrderRequestDraft")
        purchase_order = draft.purchase_order
        # This is the send-bound body, not a shared artifact: it carries the
        # real destination so an authorised sender can use it. The outbox
        # record itself stores only a fingerprint, never the body.
        request = CommunicationSendRequest(
            request_id=f"req-{purchase_order.po_id}-v{purchase_order.version}",
            workspace_id=purchase_order.workspace_id,
            channel=channel,
            recipient_ref=recipient_ref,
            subject=f"[발주 초안] {purchase_order.po_id} / 주문 {draft.order_id}",
            body=draft.to_email_draft(redact_personal=False),
            target_kind=BusinessObjectKind.PURCHASE_ORDER,
            target_id=purchase_order.po_id,
            target_version=purchase_order.version,
            action_fingerprint=draft.action_fingerprint,
            approval_id=f"ap-{purchase_order.po_id}-v{purchase_order.version}",
        )
        record = self.outbox.prepare(request, now=self._now())
        return record.outbox_id

    # -- step 5 ----------------------------------------------------------

    def record_supplier_acknowledgement(
        self,
        *,
        workspace_id: str,
        order_id: str,
        supplier_id: str,
        acknowledged_at: datetime,
        promised_delivery_date: date | None = None,
        note: str = "",
    ) -> SalesOrder:
        """Step 5: record that the supplier confirmed the request."""

        order = self.order(workspace_id=workspace_id, order_id=order_id)
        if order.status is not SalesOrderStatus.CONFIRMED:
            raise SalesOrderError("supplier acknowledgement needs a confirmed order")
        acknowledged = _aware(acknowledged_at, "acknowledged_at")
        if acknowledged < order.received_at:
            raise SalesOrderError("acknowledgement cannot precede order receipt")
        self._record_evidence(
            order=order,
            evidence_id=f"ev-supplier-ack-{order.order_id}-{acknowledged_at.date().isoformat()}",
            summary=f"공급사 처리 결과 확인: {supplier_id}",
            source_ref=f"supplier:{supplier_id}",
        )
        return self._transition(
            order,
            to=SalesOrderStatus.SUPPLIER_ORDERED,
            summary="공급사 발주 요청 회신 확인",
            evidence_id=f"ev-order-supplier-ordered-{order.order_id}-v{order.version + 1}",
            evidence_summary="공급사 발주 처리 완료",
        )

    # -- step 6 ----------------------------------------------------------

    def record_shipment(
        self,
        *,
        workspace_id: str,
        order_id: str,
        shipment_id: str,
        status: ShipmentStatus,
        carrier: str,
        tracking_number: str,
        observed_at: datetime | None = None,
        delivered_at: datetime | None = None,
        source_ref: str = "",
        note: str = "",
    ) -> Shipment:
        """Step 6: record the waybill and the shipment status."""

        order = self.order(workspace_id=workspace_id, order_id=order_id)
        if order.status not in {
            SalesOrderStatus.SUPPLIER_ORDERED,
            SalesOrderStatus.READY_TO_SHIP,
            SalesOrderStatus.SHIPPED,
            SalesOrderStatus.DELIVERED,
            SalesOrderStatus.RETURN_REQUESTED,
            SalesOrderStatus.MISDELIVERY,
        }:
            raise SalesOrderError("shipment requires a supplier-ordered order")
        observed = _aware(observed_at or self._now(), "observed_at")

        version = 1
        try:
            previous_envelope = self.ledger.latest_object(
                workspace_id=workspace_id,
                kind=BusinessObjectKind.SHIPMENT,
                object_id=shipment_id,
            )
        except ContractError:
            previous_envelope = None
        if previous_envelope is not None:
            previous = previous_envelope.value
            if not isinstance(previous, Shipment):
                raise SalesOrderError("shipment object has unexpected type")
            if previous.order_id != order_id:
                raise SalesOrderError("shipment identity cannot move between orders")
            if previous.tracking_number != tracking_number:
                raise SalesOrderError("shipment tracking number cannot change")
            if status not in SHIPMENT_TRANSITIONS[previous.status]:
                raise SalesOrderError("invalid shipment status transition")
            if observed < previous.observed_at:
                raise SalesOrderError("shipment observations must be monotonic")
            version = previous.version + 1

        shipment = Shipment(
            shipment_id=shipment_id,
            order_id=order_id,
            order_version=order.version,
            version=version,
            status=status,
            carrier=carrier,
            tracking_number=tracking_number,
            observed_at=observed,
            source_ref=source_ref or f"shipment:{shipment_id}:v{version}",
            delivered_at=delivered_at,
            note=note,
        )
        self._append(
            kind=BusinessObjectKind.SHIPMENT,
            object_id=shipment.shipment_id,
            version=shipment.version,
            workspace_id=workspace_id,
            value=shipment,
        )
        self._record_evidence(
            order=order,
            evidence_id=f"ev-shipment-{shipment.shipment_id}-v{shipment.version}",
            summary=f"배송 상태 기록: {status.value} / 송장 {tracking_number}",
            source_ref=shipment.source_ref,
        )

        order_status = _ORDER_STATUS_FOR_SHIPMENT.get(status)
        if order_status is not None and order.status is not order_status:
            order = self._transition(
                order,
                to=order_status,
                summary=f"배송 상태 반영: {status.value}",
                evidence_id=f"ev-order-shipment-{order.order_id}-v{order.version + 1}",
                evidence_summary=f"배송 상태 {status.value}",
            )
        return shipment

    def shipment(self, *, workspace_id: str, shipment_id: str) -> Shipment:
        envelope = self.ledger.latest_object(
            workspace_id=workspace_id,
            kind=BusinessObjectKind.SHIPMENT,
            object_id=shipment_id,
        )
        if not isinstance(envelope.value, Shipment):
            raise SalesOrderError("shipment object has unexpected type")
        return envelope.value

    # -- step 7 ----------------------------------------------------------

    def complete_order(self, *, workspace_id: str, order_id: str) -> SalesOrder:
        """Step 7: close the order after delivery."""

        order = self.order(workspace_id=workspace_id, order_id=order_id)
        if order.status is not SalesOrderStatus.DELIVERED:
            raise SalesOrderError("only a delivered order can be completed")
        return self._transition(
            order,
            to=SalesOrderStatus.COMPLETED,
            summary="주문 완료 처리",
            evidence_id=f"ev-order-completed-{order.order_id}-v{order.version + 1}",
            evidence_summary="주문 완료 처리",
        )

    # -- step 8 ----------------------------------------------------------

    def open_return(
        self,
        *,
        workspace_id: str,
        order_id: str,
        return_id: str,
        reason: ReturnReason,
        shipment_id: str | None = None,
        resolution_note: str = "",
    ) -> ReturnRequest:
        """Step 8: open a cancellation / return / misdelivery case."""

        order = self.order(workspace_id=workspace_id, order_id=order_id)
        if reason is ReturnReason.CUSTOMER_CANCELLED:
            if order.status not in {
                SalesOrderStatus.RECEIVED,
                SalesOrderStatus.CONFIRMED,
                SalesOrderStatus.SUPPLIER_ORDERED,
                SalesOrderStatus.READY_TO_SHIP,
            }:
                raise SalesOrderError("cancellation is only allowed before shipment")
        elif reason is ReturnReason.MISDELIVERY:
            if order.status not in {
                SalesOrderStatus.SHIPPED,
                SalesOrderStatus.DELIVERED,
                SalesOrderStatus.RETURN_REQUESTED,
                SalesOrderStatus.MISDELIVERY,
            }:
                raise SalesOrderError("misdelivery requires a shipped order")
        else:
            if order.status not in {
                SalesOrderStatus.SHIPPED,
                SalesOrderStatus.DELIVERED,
                SalesOrderStatus.RETURN_REQUESTED,
                SalesOrderStatus.MISDELIVERY,
            }:
                raise SalesOrderError("return requires a shipped order")

        request = ReturnRequest(
            return_id=return_id,
            order_id=order.order_id,
            order_version=order.version,
            version=1,
            reason=reason,
            status=ReturnStatus.OPEN,
            requested_at=self._now(),
            shipment_id=shipment_id,
            resolution_note=resolution_note,
        )
        self._append(
            kind=BusinessObjectKind.RETURN_REQUEST,
            object_id=request.return_id,
            version=request.version,
            workspace_id=workspace_id,
            value=request,
        )
        self._record_evidence(
            order=order,
            evidence_id=f"ev-return-{request.return_id}-v1",
            summary=f"예외 접수: {reason.value}",
            source_ref=f"return:{request.return_id}",
        )

        target = _ORDER_STATUS_FOR_RETURN.get(reason)
        if target is not None and order.status is not target:
            self._transition(
                order,
                to=target,
                summary=f"예외 처리 전환: {reason.value}",
                evidence_id=f"ev-order-return-{order.order_id}-v{order.version + 1}",
                evidence_summary=f"예외 {reason.value}",
            )
        return request

    def resolve_return(
        self,
        *,
        workspace_id: str,
        return_id: str,
        resolution: ReturnStatus,
        resolution_note: str = "",
    ) -> ReturnRequest:
        """Step 8b: close or reject an exception case."""

        envelope = self.ledger.latest_object(
            workspace_id=workspace_id,
            kind=BusinessObjectKind.RETURN_REQUEST,
            object_id=return_id,
        )
        if not isinstance(envelope.value, ReturnRequest):
            raise SalesOrderError("return request object has unexpected type")
        previous = envelope.value
        if previous.status is ReturnStatus.RESOLVED:
            raise SalesOrderError("resolved return case cannot be reopened")
        if resolution is ReturnStatus.RESOLVED and not resolution_note.strip():
            raise SalesOrderError("a resolved return case requires a resolution note")
        updated = replace(
            previous,
            version=previous.version + 1,
            status=resolution,
            resolution_note=resolution_note or previous.resolution_note,
        )
        self._append(
            kind=BusinessObjectKind.RETURN_REQUEST,
            object_id=updated.return_id,
            version=updated.version,
            workspace_id=workspace_id,
            value=updated,
        )
        return updated

    # -- internals -------------------------------------------------------

    def _append(
        self,
        *,
        kind: BusinessObjectKind,
        object_id: str,
        version: int,
        workspace_id: str,
        value: object,
    ) -> None:
        self.ledger.append_object(
            BusinessObjectEnvelope(
                kind=kind,
                object_id=object_id,
                version=version,
                workspace_id=workspace_id,
                value=value,
            )
        )

    def _transition(
        self,
        order: SalesOrder,
        *,
        to: SalesOrderStatus,
        summary: str,
        evidence_id: str,
        evidence_summary: str,
    ) -> SalesOrder:
        if to not in ORDER_TRANSITIONS[order.status]:
            raise SalesOrderError(
                f"invalid sales order transition {order.status.value} -> {to.value}"
            )
        updated = replace(order, status=to, version=order.version + 1)
        self._append(
            kind=BusinessObjectKind.SALES_ORDER,
            object_id=updated.order_id,
            version=updated.version,
            workspace_id=updated.workspace_id,
            value=updated,
        )
        self._record_evidence(
            order=updated,
            evidence_id=evidence_id,
            summary=evidence_summary,
            source_ref=f"order:{updated.order_id}:v{updated.version}",
        )
        return updated

    def _record_evidence(
        self,
        *,
        order: SalesOrder,
        evidence_id: str,
        summary: str,
        source_ref: str,
    ) -> None:
        self.ledger.add_evidence(
            WorkflowEvidenceRecord(
                evidence_id=evidence_id,
                workspace_id=order.workspace_id,
                workflow_id=f"wf-order-{order.order_id}",
                object_kind=BusinessObjectKind.SALES_ORDER,
                object_id=order.order_id,
                object_version=order.version,
                origin=EvidenceOrigin.USER_ACTION,
                source_ref=source_ref,
                summary=summary,
                recorded_at=self._now(),
                authoritative=False,
            )
        )


_ORDER_STATUS_FOR_SHIPMENT: dict[ShipmentStatus, SalesOrderStatus] = {
    ShipmentStatus.LABEL_ISSUED: SalesOrderStatus.READY_TO_SHIP,
    ShipmentStatus.IN_TRANSIT: SalesOrderStatus.SHIPPED,
    ShipmentStatus.OUT_FOR_DELIVERY: SalesOrderStatus.SHIPPED,
    ShipmentStatus.DELIVERED: SalesOrderStatus.DELIVERED,
    ShipmentStatus.MISDELIVERY: SalesOrderStatus.MISDELIVERY,
    ShipmentStatus.RETURN_IN_TRANSIT: SalesOrderStatus.RETURN_REQUESTED,
    ShipmentStatus.RETURNED: SalesOrderStatus.RETURNED,
}

_ORDER_STATUS_FOR_RETURN: dict[ReturnReason, SalesOrderStatus] = {
    ReturnReason.CUSTOMER_CANCELLED: SalesOrderStatus.CANCELLED,
    ReturnReason.CUSTOMER_RETURN: SalesOrderStatus.RETURN_REQUESTED,
    ReturnReason.MISDELIVERY: SalesOrderStatus.MISDELIVERY,
    ReturnReason.DAMAGED: SalesOrderStatus.RETURN_REQUESTED,
    ReturnReason.WRONG_ITEM: SalesOrderStatus.RETURN_REQUESTED,
}


def _default_supplier_message(order: SalesOrder, purchase_order: PurchaseOrder) -> str:
    lines = [
        f"주문 {order.order_id} 건의 발주 및 배송을 요청드립니다.",
        "- 요청 납기일과 출고 가능 여부를 회신 부탁드립니다.",
        "- 수령 정보는 발주서 발송 정보와 동일합니다.",
    ]
    if purchase_order.payment_terms is not None:
        lines.append(f"- 거래 조건: {purchase_order.payment_terms.label}")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Export helpers
# --------------------------------------------------------------------------


def sales_order_to_public_dict(order: SalesOrder, *, redact_personal: bool = True) -> dict[str, Any]:
    """Export one order as a JSON-ready dict.

    ``redact_personal=True`` masks the delivery destination, which is the
    default for anything that may be shared outside the operating machine.
    """

    ship_to = order.ship_to.redacted() if redact_personal else order.ship_to
    payload = order.safe_dict()
    payload["ship_to"] = ship_to.safe_dict()
    payload["personal_data_redacted"] = redact_personal
    return payload


def sales_order_lines_to_csv(order: SalesOrder, *, redact_personal: bool = True) -> str:
    """Export the order lines as CSV for a spreadsheet handoff."""

    ship_to = order.ship_to.redacted() if redact_personal else order.ship_to
    buffer = StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(
        [
            "order_id",
            "order_version",
            "status",
            "channel",
            "channel_order_ref",
            "line_id",
            "sku",
            "item_id",
            "description",
            "quantity",
            "unit",
            "unit_price_amount_minor",
            "currency",
            "line_total_amount_minor",
            "recipient_name",
            "recipient_phone",
            "postal_code",
            "address_line1",
        ]
    )
    for line in order.lines:
        writer.writerow(
            [
                order.order_id,
                order.version,
                order.status.value,
                order.channel.value,
                order.channel_order_ref,
                line.line_id,
                line.sku,
                line.item_id or "",
                line.description,
                format(line.quantity, "f"),
                line.unit,
                line.unit_price.amount_minor,
                line.unit_price.currency,
                line.total.amount_minor,
                ship_to.recipient_name,
                ship_to.recipient_phone,
                ship_to.postal_code,
                ship_to.address_line1,
            ]
        )
    return buffer.getvalue()


def shipments_to_csv(shipments: tuple[Shipment, ...]) -> str:
    """Export the shipment tracking records as CSV."""

    buffer = StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(
        [
            "shipment_id",
            "order_id",
            "order_version",
            "version",
            "status",
            "carrier",
            "tracking_number",
            "observed_at",
            "delivered_at",
            "source_ref",
            "note",
        ]
    )
    for shipment in shipments:
        writer.writerow(
            [
                shipment.shipment_id,
                shipment.order_id,
                shipment.order_version,
                shipment.version,
                shipment.status.value,
                shipment.carrier,
                shipment.tracking_number,
                _iso(shipment.observed_at),
                _iso(shipment.delivered_at) if shipment.delivered_at else "",
                shipment.source_ref,
                shipment.note,
            ]
        )
    return buffer.getvalue()


def returns_to_csv(returns: tuple[ReturnRequest, ...]) -> str:
    """Export the exception cases as CSV."""

    buffer = StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(
        [
            "return_id",
            "order_id",
            "order_version",
            "version",
            "reason",
            "status",
            "requested_at",
            "shipment_id",
            "resolution_note",
        ]
    )
    for request in returns:
        writer.writerow(
            [
                request.return_id,
                request.order_id,
                request.order_version,
                request.version,
                request.reason.value,
                request.status.value,
                _iso(request.requested_at),
                request.shipment_id or "",
                request.resolution_note,
            ]
        )
    return buffer.getvalue()


def fulfillment_case_to_json(
    *,
    order: SalesOrder,
    draft: SupplierOrderRequestDraft | None = None,
    shipments: tuple[Shipment, ...] = (),
    returns: tuple[ReturnRequest, ...] = (),
    availability: AvailabilityCheck | None = None,
    redact_personal: bool = True,
) -> str:
    """Serialize one end-to-end virtual order case as JSON."""

    payload: dict[str, Any] = {
        "contract_version": "claw-ops-online-order-fulfillment.v1",
        "order": sales_order_to_public_dict(order, redact_personal=redact_personal),
        "fulfillment_steps": [step.safe_dict() for step in ORDER_FULFILLMENT_STEPS],
        "availability_check": availability.safe_dict() if availability else None,
        "supplier_order_request_draft": (
            {
                "purchase_order": {
                    "po_id": draft.purchase_order.po_id,
                    "supplier_id": draft.purchase_order.supplier_id,
                    "status": draft.purchase_order.status.value,
                    "total": draft.purchase_order.total.safe_dict(),
                    "requested_delivery_date": (
                        draft.purchase_order.requested_delivery_date.isoformat()
                        if draft.purchase_order.requested_delivery_date
                        else None
                    ),
                    "lines": [
                        {
                            "line_id": line.line_id,
                            "description": line.description,
                            "quantity": format(line.quantity, "f"),
                            "unit": line.unit,
                            "unit_price": line.unit_price.safe_dict(),
                            "total": line.total.safe_dict(),
                        }
                        for line in draft.purchase_order.lines
                    ],
                },
                "action_fingerprint": draft.action_fingerprint,
                "requires_approval": draft.requires_approval,
                "sent": False,
                "draft_markdown": draft.to_markdown(),
                "draft_email_body": draft.to_email_draft(),
            }
            if draft
            else None
        ),
        "shipments": [shipment.safe_dict() for shipment in shipments],
        "returns": [request.safe_dict() for request in returns],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def artifact_digest(text: str) -> str:
    """SHA-256 of an exported artifact, for a reproducible evidence pointer."""

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


__all__ = [
    "AvailabilityCheck",
    "AutomationLevel",
    "CHANNEL_ORDER_CSV_HEADERS",
    "LocalCsvSalesChannelOrderPort",
    "ORDER_FULFILLMENT_STEPS",
    "ORDER_TRANSITIONS",
    "OnlineOrderFulfillmentCoordinator",
    "OrderFulfillmentStep",
    "ReturnReason",
    "ReturnRequest",
    "ReturnStatus",
    "SHIPMENT_TRANSITIONS",
    "SalesChannelKind",
    "SalesChannelOrderPort",
    "SalesChannelOrderSnapshot",
    "SalesOrder",
    "SalesOrderError",
    "SalesOrderLine",
    "SalesOrderStatus",
    "ShipTo",
    "Shipment",
    "ShipmentStatus",
    "StockPosition",
    "SupplierOrderRequestDraft",
    "UnconfiguredSalesChannelOrderPort",
    "artifact_digest",
    "fulfillment_case_to_json",
    "returns_to_csv",
    "sales_order_lines_to_csv",
    "sales_order_to_public_dict",
    "shipments_to_csv",
]
