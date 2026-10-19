from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
import re
from typing import Any, TypeVar

from .contracts import ContractError
from .security import redact_secrets


class BusinessObjectKind(str, Enum):
    COMMERCIAL_REQUEST = "commercial_request"
    SUPPLIER_RFQ = "supplier_rfq"
    SUPPLIER_QUOTE = "supplier_quote"
    QUOTE_COMPARISON = "quote_comparison"
    NEGOTIATION_DRAFT = "negotiation_draft"
    PURCHASE_ORDER = "purchase_order"
    DELIVERY_COMMITMENT = "delivery_commitment"
    ACCOUNTING_HANDOFF = "accounting_handoff"


class CommercialRequestStatus(str, Enum):
    DRAFT = "draft"
    READY = "ready"
    IN_RFQ = "in_rfq"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class RfqStatus(str, Enum):
    DRAFT = "draft"
    APPROVAL_REQUIRED = "approval_required"
    SENT = "sent"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class SupplierQuoteStatus(str, Enum):
    RECEIVED = "received"
    REVISED = "revised"
    SELECTED = "selected"
    REJECTED = "rejected"


class PurchaseOrderStatus(str, Enum):
    DRAFT = "draft"
    APPROVAL_REQUIRED = "approval_required"
    ISSUED = "issued"
    CANCELLED = "cancelled"


class DeliveryStatus(str, Enum):
    PLANNED = "planned"
    CONFIRMED = "confirmed"
    AT_RISK = "at_risk"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


class ApprovalAction(str, Enum):
    SEND_RFQ = "send_rfq"
    SEND_NEGOTIATION = "send_negotiation"
    SELECT_SUPPLIER = "select_supplier"
    ISSUE_PURCHASE_ORDER = "issue_purchase_order"
    ACCOUNTING_WRITE = "accounting_write"
    PAYMENT = "payment"


class ApprovalDecision(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    HELD = "held"


class EvidenceOrigin(str, Enum):
    SOURCE_DOCUMENT = "source_document"
    COMMUNICATION = "communication"
    USER_ACTION = "user_action"
    CONNECTOR_RESULT = "connector_result"
    MODEL_PROJECTION = "model_projection"


class RecommendationKind(str, Enum):
    LOWEST_PRICE = "lowest_price"
    FASTEST_DELIVERY = "fastest_delivery"
    BEST_CASHFLOW_FIT = "best_cashflow_fit"
    BALANCED = "balanced"


_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_EnumT = TypeVar("_EnumT", bound=Enum)


def _safe_id(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{field_name} must be a string")
    value = value.strip()
    if not _SAFE_ID_RE.fullmatch(value):
        raise ContractError(f"{field_name} has an invalid identifier shape")
    return value


def _text(value: str, field_name: str, *, limit: int, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{field_name} must be a string")
    value = value.strip()
    if not value and not allow_empty:
        raise ContractError(f"{field_name} is required")
    if len(value) > limit:
        raise ContractError(f"{field_name} exceeds {limit} characters")
    if _CONTROL_RE.search(value):
        raise ContractError(f"{field_name} contains control characters")
    return value


def _version(value: int, field_name: str = "version") -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1 or value > 1_000_000:
        raise ContractError(f"{field_name} must be an integer between 1 and 1000000")
    return value


def _strict_bool(value: bool, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ContractError(f"{field_name} must be a boolean")
    return value


def _enum(enum_type: type[_EnumT], value: object, field_name: str) -> _EnumT:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        allowed = ", ".join(str(item.value) for item in enum_type)
        raise ContractError(f"{field_name} must be one of: {allowed}") from exc


def _aware_utc(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ContractError(f"{field_name} must be a timezone-aware datetime")
    return value.astimezone(timezone.utc)


def _date(value: date | None, field_name: str) -> date | None:
    if value is None:
        return None
    if not isinstance(value, date) or isinstance(value, datetime):
        raise ContractError(f"{field_name} must be a date")
    return value


def _quantity(value: Decimal | int | str) -> Decimal:
    if isinstance(value, bool) or isinstance(value, float):
        raise ContractError("quantity must not be bool or float")
    try:
        normalized = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ContractError("quantity must be a decimal-compatible value") from exc
    if not normalized.is_finite() or normalized <= 0 or normalized > Decimal("1000000000"):
        raise ContractError("quantity must be finite, positive, and bounded")
    if -normalized.as_tuple().exponent > 6:
        raise ContractError("quantity supports at most 6 decimal places")
    return normalized.normalize()


def _tuple(value: tuple[Any, ...], field_name: str, *, minimum: int = 0, maximum: int = 200) -> tuple[Any, ...]:
    if not isinstance(value, tuple):
        raise ContractError(f"{field_name} must be a tuple")
    if not minimum <= len(value) <= maximum:
        raise ContractError(f"{field_name} must contain between {minimum} and {maximum} entries")
    return value


@dataclass(frozen=True, slots=True)
class Money:
    amount_minor: int
    currency: str = "KRW"

    def __post_init__(self) -> None:
        if isinstance(self.amount_minor, bool) or not isinstance(self.amount_minor, int):
            raise ContractError("amount_minor must be an integer; floats are not accepted")
        if abs(self.amount_minor) > 10**15:
            raise ContractError("amount_minor exceeds the supported bound")
        currency = self.currency.strip().upper() if isinstance(self.currency, str) else ""
        if not _CURRENCY_RE.fullmatch(currency):
            raise ContractError("currency must be a 3-letter ISO-style code")
        object.__setattr__(self, "currency", currency)

    def safe_dict(self) -> dict[str, Any]:
        return {"amount_minor": self.amount_minor, "currency": self.currency}


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    artifact_id: str
    kind: str
    display_name: str = ""
    content_sha256: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "artifact_id", _safe_id(self.artifact_id, "artifact_id"))
        object.__setattr__(self, "kind", _safe_id(self.kind, "kind"))
        object.__setattr__(self, "display_name", _text(self.display_name, "display_name", limit=256, allow_empty=True))
        if self.content_sha256 is not None:
            value = self.content_sha256.strip().lower()
            if not _SHA256_RE.fullmatch(value):
                raise ContractError("content_sha256 must be a lowercase SHA-256 hex digest")
            object.__setattr__(self, "content_sha256", value)

    def safe_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "kind": self.kind,
            "display_name": redact_secrets(self.display_name),
            "content_sha256": self.content_sha256,
        }


@dataclass(frozen=True, slots=True)
class CompanyWorkspace:
    workspace_id: str
    name: str
    currency: str = "KRW"

    def __post_init__(self) -> None:
        object.__setattr__(self, "workspace_id", _safe_id(self.workspace_id, "workspace_id"))
        object.__setattr__(self, "name", _text(self.name, "name", limit=200))
        object.__setattr__(self, "currency", Money(0, self.currency).currency)


@dataclass(frozen=True, slots=True)
class Customer:
    customer_id: str
    workspace_id: str
    name: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "customer_id", _safe_id(self.customer_id, "customer_id"))
        object.__setattr__(self, "workspace_id", _safe_id(self.workspace_id, "workspace_id"))
        object.__setattr__(self, "name", _text(self.name, "name", limit=200))


@dataclass(frozen=True, slots=True)
class PaymentTerms:
    terms_id: str
    label: str
    due_days: int | None = None
    prepaid: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "terms_id", _safe_id(self.terms_id, "terms_id"))
        object.__setattr__(self, "label", _text(self.label, "label", limit=300))
        if self.due_days is not None:
            if isinstance(self.due_days, bool) or not isinstance(self.due_days, int) or not 0 <= self.due_days <= 3650:
                raise ContractError("due_days must be between 0 and 3650")
        object.__setattr__(self, "prepaid", _strict_bool(self.prepaid, "prepaid"))


@dataclass(frozen=True, slots=True)
class Supplier:
    supplier_id: str
    workspace_id: str
    name: str
    payment_terms: PaymentTerms | None = None
    active: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "supplier_id", _safe_id(self.supplier_id, "supplier_id"))
        object.__setattr__(self, "workspace_id", _safe_id(self.workspace_id, "workspace_id"))
        object.__setattr__(self, "name", _text(self.name, "name", limit=200))
        object.__setattr__(self, "active", _strict_bool(self.active, "active"))
        if self.payment_terms is not None and not isinstance(self.payment_terms, PaymentTerms):
            raise ContractError("payment_terms must be PaymentTerms or None")


@dataclass(frozen=True, slots=True)
class Item:
    item_id: str
    workspace_id: str
    sku: str
    name: str
    unit: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "item_id", _safe_id(self.item_id, "item_id"))
        object.__setattr__(self, "workspace_id", _safe_id(self.workspace_id, "workspace_id"))
        object.__setattr__(self, "sku", _text(self.sku, "sku", limit=128))
        object.__setattr__(self, "name", _text(self.name, "name", limit=300))
        object.__setattr__(self, "unit", _text(self.unit, "unit", limit=32))


@dataclass(frozen=True, slots=True)
class LineItem:
    line_id: str
    description: str
    quantity: Decimal | int | str
    unit: str
    item_id: str | None = None
    target_unit_price: Money | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "line_id", _safe_id(self.line_id, "line_id"))
        object.__setattr__(self, "description", _text(self.description, "description", limit=500))
        object.__setattr__(self, "quantity", _quantity(self.quantity))
        object.__setattr__(self, "unit", _text(self.unit, "unit", limit=32))
        if self.item_id is not None:
            object.__setattr__(self, "item_id", _safe_id(self.item_id, "item_id"))
        if self.target_unit_price is not None and not isinstance(self.target_unit_price, Money):
            raise ContractError("target_unit_price must be Money or None")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "line_id": self.line_id,
            "description": redact_secrets(self.description),
            "quantity": format(self.quantity, "f"),
            "unit": self.unit,
            "item_id": self.item_id,
            "target_unit_price": self.target_unit_price.safe_dict() if self.target_unit_price else None,
        }


@dataclass(frozen=True, slots=True)
class CommercialRequest:
    request_id: str
    workspace_id: str
    customer_id: str
    version: int
    title: str
    line_items: tuple[LineItem, ...]
    status: CommercialRequestStatus = CommercialRequestStatus.DRAFT
    requested_delivery_date: date | None = None
    source_artifact: ArtifactRef | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "request_id", _safe_id(self.request_id, "request_id"))
        object.__setattr__(self, "workspace_id", _safe_id(self.workspace_id, "workspace_id"))
        object.__setattr__(self, "customer_id", _safe_id(self.customer_id, "customer_id"))
        object.__setattr__(self, "version", _version(self.version))
        object.__setattr__(self, "title", _text(self.title, "title", limit=300))
        _tuple(self.line_items, "line_items", minimum=1, maximum=200)
        if not all(isinstance(item, LineItem) for item in self.line_items):
            raise ContractError("line_items must contain only LineItem values")
        if len({item.line_id for item in self.line_items}) != len(self.line_items):
            raise ContractError("line_items must have unique line_id values")
        object.__setattr__(self, "status", _enum(CommercialRequestStatus, self.status, "status"))
        object.__setattr__(self, "requested_delivery_date", _date(self.requested_delivery_date, "requested_delivery_date"))
        if self.source_artifact is not None and not isinstance(self.source_artifact, ArtifactRef):
            raise ContractError("source_artifact must be ArtifactRef or None")


@dataclass(frozen=True, slots=True)
class SupplierQuoteRequest:
    rfq_id: str
    workspace_id: str
    commercial_request_id: str
    commercial_request_version: int
    supplier_id: str
    version: int
    line_items: tuple[LineItem, ...]
    status: RfqStatus = RfqStatus.DRAFT
    message: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "rfq_id", _safe_id(self.rfq_id, "rfq_id"))
        object.__setattr__(self, "workspace_id", _safe_id(self.workspace_id, "workspace_id"))
        object.__setattr__(self, "commercial_request_id", _safe_id(self.commercial_request_id, "commercial_request_id"))
        object.__setattr__(self, "commercial_request_version", _version(self.commercial_request_version, "commercial_request_version"))
        object.__setattr__(self, "supplier_id", _safe_id(self.supplier_id, "supplier_id"))
        object.__setattr__(self, "version", _version(self.version))
        _tuple(self.line_items, "line_items", minimum=1, maximum=200)
        if not all(isinstance(item, LineItem) for item in self.line_items):
            raise ContractError("line_items must contain only LineItem values")
        object.__setattr__(self, "status", _enum(RfqStatus, self.status, "status"))
        object.__setattr__(self, "message", _text(self.message, "message", limit=4000, allow_empty=True))


@dataclass(frozen=True, slots=True)
class SupplierQuoteLine:
    line_id: str
    quantity: Decimal | int | str
    unit_price: Money

    def __post_init__(self) -> None:
        object.__setattr__(self, "line_id", _safe_id(self.line_id, "line_id"))
        object.__setattr__(self, "quantity", _quantity(self.quantity))
        if not isinstance(self.unit_price, Money):
            raise ContractError("unit_price must be Money")

    @property
    def total(self) -> Money:
        product = Decimal(self.unit_price.amount_minor) * self.quantity
        if product != product.to_integral_value():
            raise ContractError("quantity and unit price produce a fractional minor-unit total")
        return Money(int(product), self.unit_price.currency)


@dataclass(frozen=True, slots=True)
class SupplierQuote:
    quote_id: str
    workspace_id: str
    rfq_id: str
    supplier_id: str
    version: int
    lines: tuple[SupplierQuoteLine, ...]
    status: SupplierQuoteStatus
    received_at: datetime
    promised_delivery_date: date | None = None
    payment_terms: PaymentTerms | None = None
    source_artifact: ArtifactRef | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "quote_id", _safe_id(self.quote_id, "quote_id"))
        object.__setattr__(self, "workspace_id", _safe_id(self.workspace_id, "workspace_id"))
        object.__setattr__(self, "rfq_id", _safe_id(self.rfq_id, "rfq_id"))
        object.__setattr__(self, "supplier_id", _safe_id(self.supplier_id, "supplier_id"))
        object.__setattr__(self, "version", _version(self.version))
        _tuple(self.lines, "lines", minimum=1, maximum=200)
        if not all(isinstance(line, SupplierQuoteLine) for line in self.lines):
            raise ContractError("lines must contain only SupplierQuoteLine values")
        if len({line.line_id for line in self.lines}) != len(self.lines):
            raise ContractError("quote lines must have unique line_id values")
        object.__setattr__(self, "status", _enum(SupplierQuoteStatus, self.status, "status"))
        object.__setattr__(self, "received_at", _aware_utc(self.received_at, "received_at"))
        object.__setattr__(self, "promised_delivery_date", _date(self.promised_delivery_date, "promised_delivery_date"))
        if self.payment_terms is not None and not isinstance(self.payment_terms, PaymentTerms):
            raise ContractError("payment_terms must be PaymentTerms or None")
        if self.source_artifact is not None and not isinstance(self.source_artifact, ArtifactRef):
            raise ContractError("source_artifact must be ArtifactRef or None")
        currencies = {line.unit_price.currency for line in self.lines}
        if len(currencies) != 1:
            raise ContractError("all quote lines must use one currency")

    @property
    def total(self) -> Money:
        totals = [line.total for line in self.lines]
        return Money(sum(item.amount_minor for item in totals), totals[0].currency)


@dataclass(frozen=True, slots=True)
class QuoteComparisonEntry:
    supplier_id: str
    quote_id: str
    quote_version: int
    total: Money
    promised_delivery_date: date | None = None
    payment_terms_label: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "supplier_id", _safe_id(self.supplier_id, "supplier_id"))
        object.__setattr__(self, "quote_id", _safe_id(self.quote_id, "quote_id"))
        object.__setattr__(self, "quote_version", _version(self.quote_version, "quote_version"))
        if not isinstance(self.total, Money):
            raise ContractError("total must be Money")
        object.__setattr__(self, "promised_delivery_date", _date(self.promised_delivery_date, "promised_delivery_date"))
        object.__setattr__(self, "payment_terms_label", _text(self.payment_terms_label, "payment_terms_label", limit=300, allow_empty=True))


@dataclass(frozen=True, slots=True)
class QuoteComparison:
    comparison_id: str
    workspace_id: str
    commercial_request_id: str
    version: int
    entries: tuple[QuoteComparisonEntry, ...]
    recommendation: RecommendationKind | None = None
    recommended_supplier_id: str | None = None
    recommendation_summary: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "comparison_id", _safe_id(self.comparison_id, "comparison_id"))
        object.__setattr__(self, "workspace_id", _safe_id(self.workspace_id, "workspace_id"))
        object.__setattr__(self, "commercial_request_id", _safe_id(self.commercial_request_id, "commercial_request_id"))
        object.__setattr__(self, "version", _version(self.version))
        _tuple(self.entries, "entries", minimum=1, maximum=100)
        if not all(isinstance(entry, QuoteComparisonEntry) for entry in self.entries):
            raise ContractError("entries must contain only QuoteComparisonEntry values")
        if len({entry.supplier_id for entry in self.entries}) != len(self.entries):
            raise ContractError("comparison must contain at most one entry per supplier")
        if len({entry.total.currency for entry in self.entries}) != 1:
            raise ContractError("comparison entries must use one currency")
        if self.recommendation is not None:
            object.__setattr__(self, "recommendation", _enum(RecommendationKind, self.recommendation, "recommendation"))
        if self.recommended_supplier_id is not None:
            supplier_id = _safe_id(self.recommended_supplier_id, "recommended_supplier_id")
            if supplier_id not in {entry.supplier_id for entry in self.entries}:
                raise ContractError("recommended_supplier_id must reference a comparison entry")
            object.__setattr__(self, "recommended_supplier_id", supplier_id)
        object.__setattr__(self, "recommendation_summary", _text(self.recommendation_summary, "recommendation_summary", limit=1500, allow_empty=True))


@dataclass(frozen=True, slots=True)
class NegotiationDraft:
    negotiation_id: str
    workspace_id: str
    supplier_id: str
    quote_id: str
    quote_version: int
    version: int
    message: str
    target_total: Money | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "negotiation_id", _safe_id(self.negotiation_id, "negotiation_id"))
        object.__setattr__(self, "workspace_id", _safe_id(self.workspace_id, "workspace_id"))
        object.__setattr__(self, "supplier_id", _safe_id(self.supplier_id, "supplier_id"))
        object.__setattr__(self, "quote_id", _safe_id(self.quote_id, "quote_id"))
        object.__setattr__(self, "quote_version", _version(self.quote_version, "quote_version"))
        object.__setattr__(self, "version", _version(self.version))
        object.__setattr__(self, "message", _text(self.message, "message", limit=4000))
        if self.target_total is not None and not isinstance(self.target_total, Money):
            raise ContractError("target_total must be Money or None")


@dataclass(frozen=True, slots=True)
class PurchaseOrderLine:
    line_id: str
    description: str
    quantity: Decimal | int | str
    unit: str
    unit_price: Money

    def __post_init__(self) -> None:
        object.__setattr__(self, "line_id", _safe_id(self.line_id, "line_id"))
        object.__setattr__(self, "description", _text(self.description, "description", limit=500))
        object.__setattr__(self, "quantity", _quantity(self.quantity))
        object.__setattr__(self, "unit", _text(self.unit, "unit", limit=32))
        if not isinstance(self.unit_price, Money):
            raise ContractError("unit_price must be Money")

    @property
    def total(self) -> Money:
        return SupplierQuoteLine(self.line_id, self.quantity, self.unit_price).total


@dataclass(frozen=True, slots=True)
class PurchaseOrder:
    po_id: str
    workspace_id: str
    supplier_id: str
    supplier_quote_id: str
    supplier_quote_version: int
    version: int
    lines: tuple[PurchaseOrderLine, ...]
    status: PurchaseOrderStatus = PurchaseOrderStatus.DRAFT
    requested_delivery_date: date | None = None
    payment_terms: PaymentTerms | None = None
    document_artifact: ArtifactRef | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "po_id", _safe_id(self.po_id, "po_id"))
        object.__setattr__(self, "workspace_id", _safe_id(self.workspace_id, "workspace_id"))
        object.__setattr__(self, "supplier_id", _safe_id(self.supplier_id, "supplier_id"))
        object.__setattr__(self, "supplier_quote_id", _safe_id(self.supplier_quote_id, "supplier_quote_id"))
        object.__setattr__(self, "supplier_quote_version", _version(self.supplier_quote_version, "supplier_quote_version"))
        object.__setattr__(self, "version", _version(self.version))
        _tuple(self.lines, "lines", minimum=1, maximum=200)
        if not all(isinstance(line, PurchaseOrderLine) for line in self.lines):
            raise ContractError("lines must contain only PurchaseOrderLine values")
        if len({line.line_id for line in self.lines}) != len(self.lines):
            raise ContractError("purchase-order lines must have unique line_id values")
        if len({line.unit_price.currency for line in self.lines}) != 1:
            raise ContractError("purchase-order lines must use one currency")
        object.__setattr__(self, "status", _enum(PurchaseOrderStatus, self.status, "status"))
        object.__setattr__(self, "requested_delivery_date", _date(self.requested_delivery_date, "requested_delivery_date"))
        if self.payment_terms is not None and not isinstance(self.payment_terms, PaymentTerms):
            raise ContractError("payment_terms must be PaymentTerms or None")
        if self.document_artifact is not None and not isinstance(self.document_artifact, ArtifactRef):
            raise ContractError("document_artifact must be ArtifactRef or None")

    @property
    def total(self) -> Money:
        totals = [line.total for line in self.lines]
        return Money(sum(item.amount_minor for item in totals), totals[0].currency)


@dataclass(frozen=True, slots=True)
class DeliveryCommitment:
    delivery_id: str
    workspace_id: str
    po_id: str
    po_version: int
    version: int
    promised_date: date
    status: DeliveryStatus = DeliveryStatus.PLANNED
    note: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "delivery_id", _safe_id(self.delivery_id, "delivery_id"))
        object.__setattr__(self, "workspace_id", _safe_id(self.workspace_id, "workspace_id"))
        object.__setattr__(self, "po_id", _safe_id(self.po_id, "po_id"))
        object.__setattr__(self, "po_version", _version(self.po_version, "po_version"))
        object.__setattr__(self, "version", _version(self.version))
        normalized_date = _date(self.promised_date, "promised_date")
        assert normalized_date is not None
        object.__setattr__(self, "promised_date", normalized_date)
        object.__setattr__(self, "status", _enum(DeliveryStatus, self.status, "status"))
        object.__setattr__(self, "note", _text(self.note, "note", limit=1000, allow_empty=True))


@dataclass(frozen=True, slots=True)
class AccountingHandoff:
    handoff_id: str
    workspace_id: str
    po_id: str
    po_version: int
    version: int
    obligation_amount: Money
    expected_payment_date: date | None
    source_artifact: ArtifactRef | None = None
    note: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "handoff_id", _safe_id(self.handoff_id, "handoff_id"))
        object.__setattr__(self, "workspace_id", _safe_id(self.workspace_id, "workspace_id"))
        object.__setattr__(self, "po_id", _safe_id(self.po_id, "po_id"))
        object.__setattr__(self, "po_version", _version(self.po_version, "po_version"))
        object.__setattr__(self, "version", _version(self.version))
        if not isinstance(self.obligation_amount, Money):
            raise ContractError("obligation_amount must be Money")
        object.__setattr__(self, "expected_payment_date", _date(self.expected_payment_date, "expected_payment_date"))
        if self.source_artifact is not None and not isinstance(self.source_artifact, ArtifactRef):
            raise ContractError("source_artifact must be ArtifactRef or None")
        object.__setattr__(self, "note", _text(self.note, "note", limit=1000, allow_empty=True))


@dataclass(frozen=True, slots=True)
class CommunicationRef:
    communication_id: str
    workspace_id: str
    channel: str
    counterpart_ref: str
    thread_ref: str
    occurred_at: datetime
    artifact_ref: ArtifactRef | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "communication_id", _safe_id(self.communication_id, "communication_id"))
        object.__setattr__(self, "workspace_id", _safe_id(self.workspace_id, "workspace_id"))
        object.__setattr__(self, "channel", _safe_id(self.channel, "channel"))
        object.__setattr__(self, "counterpart_ref", _safe_id(self.counterpart_ref, "counterpart_ref"))
        object.__setattr__(self, "thread_ref", _text(self.thread_ref, "thread_ref", limit=512))
        object.__setattr__(self, "occurred_at", _aware_utc(self.occurred_at, "occurred_at"))
        if self.artifact_ref is not None and not isinstance(self.artifact_ref, ArtifactRef):
            raise ContractError("artifact_ref must be ArtifactRef or None")


@dataclass(frozen=True, slots=True)
class ApprovalProjection:
    approval_id: str
    workspace_id: str
    action: ApprovalAction
    target_kind: BusinessObjectKind
    target_id: str
    target_version: int
    action_fingerprint: str
    decision: ApprovalDecision = ApprovalDecision.PENDING
    actor_ref: str | None = None
    decided_at: datetime | None = None
    evidence_ref: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "approval_id", _safe_id(self.approval_id, "approval_id"))
        object.__setattr__(self, "workspace_id", _safe_id(self.workspace_id, "workspace_id"))
        object.__setattr__(self, "action", _enum(ApprovalAction, self.action, "action"))
        object.__setattr__(self, "target_kind", _enum(BusinessObjectKind, self.target_kind, "target_kind"))
        object.__setattr__(self, "target_id", _safe_id(self.target_id, "target_id"))
        object.__setattr__(self, "target_version", _version(self.target_version, "target_version"))
        fingerprint = self.action_fingerprint.strip().lower() if isinstance(self.action_fingerprint, str) else ""
        if not _SHA256_RE.fullmatch(fingerprint):
            raise ContractError("action_fingerprint must be a lowercase SHA-256 hex digest")
        object.__setattr__(self, "action_fingerprint", fingerprint)
        decision = _enum(ApprovalDecision, self.decision, "decision")
        object.__setattr__(self, "decision", decision)
        if decision is ApprovalDecision.PENDING:
            if self.actor_ref is not None or self.decided_at is not None or self.evidence_ref is not None:
                raise ContractError("pending approval cannot have decision metadata")
        else:
            if self.actor_ref is None or self.decided_at is None:
                raise ContractError("decided approval requires actor_ref and decided_at")
            object.__setattr__(self, "actor_ref", _safe_id(self.actor_ref, "actor_ref"))
            object.__setattr__(self, "decided_at", _aware_utc(self.decided_at, "decided_at"))
            if self.evidence_ref is not None:
                object.__setattr__(self, "evidence_ref", _safe_id(self.evidence_ref, "evidence_ref"))

    @property
    def approved(self) -> bool:
        return self.decision is ApprovalDecision.APPROVED


@dataclass(frozen=True, slots=True)
class WorkflowEvidenceRecord:
    evidence_id: str
    workspace_id: str
    workflow_id: str
    object_kind: BusinessObjectKind
    object_id: str
    object_version: int
    origin: EvidenceOrigin
    source_ref: str
    summary: str
    recorded_at: datetime
    authoritative: bool = False
    metadata: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_id", _safe_id(self.evidence_id, "evidence_id"))
        object.__setattr__(self, "workspace_id", _safe_id(self.workspace_id, "workspace_id"))
        object.__setattr__(self, "workflow_id", _safe_id(self.workflow_id, "workflow_id"))
        object.__setattr__(self, "object_kind", _enum(BusinessObjectKind, self.object_kind, "object_kind"))
        object.__setattr__(self, "object_id", _safe_id(self.object_id, "object_id"))
        object.__setattr__(self, "object_version", _version(self.object_version, "object_version"))
        origin = _enum(EvidenceOrigin, self.origin, "origin")
        object.__setattr__(self, "origin", origin)
        object.__setattr__(self, "source_ref", _text(self.source_ref, "source_ref", limit=512))
        object.__setattr__(self, "summary", _text(self.summary, "summary", limit=2000))
        object.__setattr__(self, "recorded_at", _aware_utc(self.recorded_at, "recorded_at"))
        authoritative = _strict_bool(self.authoritative, "authoritative")
        if origin is EvidenceOrigin.MODEL_PROJECTION and authoritative:
            raise ContractError("model projection cannot be authoritative evidence")
        object.__setattr__(self, "authoritative", authoritative)
        _tuple(self.metadata, "metadata", maximum=32)
        normalized: list[tuple[str, str]] = []
        for item in self.metadata:
            if not isinstance(item, tuple) or len(item) != 2:
                raise ContractError("metadata entries must be (key, value) tuples")
            key, value = item
            normalized.append((_safe_id(key, "metadata key"), _text(value, "metadata value", limit=500, allow_empty=True)))
        object.__setattr__(self, "metadata", tuple(normalized))

    def safe_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "workspace_id": self.workspace_id,
            "workflow_id": self.workflow_id,
            "object_kind": self.object_kind.value,
            "object_id": self.object_id,
            "object_version": self.object_version,
            "origin": self.origin.value,
            "source_ref": redact_secrets(self.source_ref),
            "summary": redact_secrets(self.summary),
            "recorded_at": self.recorded_at.isoformat().replace("+00:00", "Z"),
            "authoritative": self.authoritative,
            "metadata": {key: redact_secrets(value) for key, value in self.metadata},
        }
