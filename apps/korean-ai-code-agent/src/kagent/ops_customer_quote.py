from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import hashlib
import json
import re
from typing import Any

from .contracts import ContractError
from .ops_contracts import (
    CommercialRequest,
    Money,
    SupplierQuote,
    SupplierQuoteStatus,
)
from .security import redact_secrets


_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")


def _id(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value.strip()):
        raise ContractError(f"{field_name} must be a bounded safe identifier")
    return value.strip()


def _text(value: str, field_name: str, *, limit: int) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{field_name} must be a string")
    value = value.strip()
    if not value or len(value) > limit or any(ord(ch) < 32 for ch in value):
        raise ContractError(f"{field_name} must be bounded non-empty text")
    if redact_secrets(value) != value:
        raise ContractError(f"{field_name} must not contain credential material")
    return value


def _basis_points(value: int, field_name: str, *, maximum: int = 50_000) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= maximum:
        raise ContractError(f"{field_name} must be integer basis points between 0 and {maximum}")
    return value


def _ceil_markup_minor(cost_minor: int, markup_bps: int) -> int:
    if cost_minor < 0:
        raise ContractError("supplier cost cannot be negative")
    numerator = cost_minor * (10_000 + markup_bps)
    return (numerator + 9_999) // 10_000


def _line_total_minor(unit_minor: int, quantity: Decimal) -> int:
    product = Decimal(unit_minor) * quantity
    if product != product.to_integral_value():
        raise ContractError("quantity and unit price produce fractional minor-unit total")
    return int(product)


@dataclass(frozen=True, slots=True)
class CustomerQuotePricingPolicy:
    policy_ref: str
    markup_bps: int
    maximum_markup_bps: int = 50_000

    def __post_init__(self) -> None:
        object.__setattr__(self, "policy_ref", _id(self.policy_ref, "policy_ref"))
        maximum = _basis_points(self.maximum_markup_bps, "maximum_markup_bps", maximum=100_000)
        markup = _basis_points(self.markup_bps, "markup_bps", maximum=maximum)
        object.__setattr__(self, "maximum_markup_bps", maximum)
        object.__setattr__(self, "markup_bps", markup)


@dataclass(frozen=True, slots=True)
class CustomerQuoteLine:
    line_id: str
    description: str
    quantity: Decimal
    unit: str
    cost_unit_price: Money
    sale_unit_price: Money

    def __post_init__(self) -> None:
        object.__setattr__(self, "line_id", _id(self.line_id, "line_id"))
        object.__setattr__(self, "description", _text(self.description, "description", limit=500))
        object.__setattr__(self, "unit", _text(self.unit, "unit", limit=32))
        if not isinstance(self.quantity, Decimal) or not self.quantity.is_finite() or self.quantity <= 0:
            raise ContractError("quantity must be a positive finite Decimal")
        if not isinstance(self.cost_unit_price, Money) or not isinstance(self.sale_unit_price, Money):
            raise ContractError("cost and sale unit prices must be Money")
        if self.cost_unit_price.currency != self.sale_unit_price.currency:
            raise ContractError("cost and sale unit prices must use one currency")
        if self.cost_unit_price.amount_minor < 0:
            raise ContractError("cost unit price cannot be negative")
        if self.sale_unit_price.amount_minor < self.cost_unit_price.amount_minor:
            raise ContractError("sale unit price cannot be below source cost in M1")

    @property
    def cost_total(self) -> Money:
        return Money(_line_total_minor(self.cost_unit_price.amount_minor, self.quantity), self.cost_unit_price.currency)

    @property
    def sale_total(self) -> Money:
        return Money(_line_total_minor(self.sale_unit_price.amount_minor, self.quantity), self.sale_unit_price.currency)

    @property
    def margin_total(self) -> Money:
        return Money(self.sale_total.amount_minor - self.cost_total.amount_minor, self.sale_total.currency)

    def safe_dict(self) -> dict[str, Any]:
        return {
            "line_id": self.line_id,
            "description": self.description,
            "quantity": format(self.quantity, "f"),
            "unit": self.unit,
            "cost_unit_price": self.cost_unit_price.safe_dict(),
            "sale_unit_price": self.sale_unit_price.safe_dict(),
            "cost_total": self.cost_total.safe_dict(),
            "sale_total": self.sale_total.safe_dict(),
            "margin_total": self.margin_total.safe_dict(),
        }


@dataclass(frozen=True, slots=True)
class CustomerQuoteDraft:
    customer_quote_id: str
    workspace_id: str
    customer_id: str
    version: int
    commercial_request_id: str
    commercial_request_version: int
    supplier_quote_id: str
    supplier_quote_version: int
    pricing_policy_ref: str
    markup_bps: int
    lines: tuple[CustomerQuoteLine, ...]
    title: str
    approval_required: bool = True

    def __post_init__(self) -> None:
        for field_name in (
            "customer_quote_id",
            "workspace_id",
            "customer_id",
            "commercial_request_id",
            "supplier_quote_id",
            "pricing_policy_ref",
        ):
            object.__setattr__(self, field_name, _id(getattr(self, field_name), field_name))
        for field_name in ("version", "commercial_request_version", "supplier_quote_version"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ContractError(f"{field_name} must be positive")
        object.__setattr__(self, "markup_bps", _basis_points(self.markup_bps, "markup_bps", maximum=100_000))
        if not isinstance(self.lines, tuple) or not self.lines or not all(isinstance(item, CustomerQuoteLine) for item in self.lines):
            raise ContractError("lines must be a non-empty tuple of CustomerQuoteLine")
        if len({item.line_id for item in self.lines}) != len(self.lines):
            raise ContractError("customer quote line IDs must be unique")
        currencies = {item.sale_unit_price.currency for item in self.lines}
        if len(currencies) != 1:
            raise ContractError("customer quote must use one currency")
        object.__setattr__(self, "title", _text(self.title, "title", limit=300))
        if self.approval_required is not True:
            raise ContractError("customer sales quotation requires approval in M1")

    @property
    def currency(self) -> str:
        return self.lines[0].sale_unit_price.currency

    @property
    def cost_total(self) -> Money:
        return Money(sum(item.cost_total.amount_minor for item in self.lines), self.currency)

    @property
    def sale_total(self) -> Money:
        return Money(sum(item.sale_total.amount_minor for item in self.lines), self.currency)

    @property
    def margin_total(self) -> Money:
        return Money(self.sale_total.amount_minor - self.cost_total.amount_minor, self.currency)

    @property
    def gross_margin_bps(self) -> int:
        if self.sale_total.amount_minor == 0:
            return 0
        return (self.margin_total.amount_minor * 10_000) // self.sale_total.amount_minor

    @property
    def pricing_fingerprint(self) -> str:
        payload = {
            "customer_quote_id": self.customer_quote_id,
            "workspace_id": self.workspace_id,
            "customer_id": self.customer_id,
            "version": self.version,
            "commercial_request_id": self.commercial_request_id,
            "commercial_request_version": self.commercial_request_version,
            "supplier_quote_id": self.supplier_quote_id,
            "supplier_quote_version": self.supplier_quote_version,
            "pricing_policy_ref": self.pricing_policy_ref,
            "markup_bps": self.markup_bps,
            "lines": [
                {
                    "line_id": item.line_id,
                    "quantity": format(item.quantity, "f"),
                    "cost_unit_minor": item.cost_unit_price.amount_minor,
                    "sale_unit_minor": item.sale_unit_price.amount_minor,
                    "currency": item.sale_unit_price.currency,
                }
                for item in self.lines
            ],
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()

    def safe_dict(self) -> dict[str, Any]:
        return {
            "customer_quote_id": self.customer_quote_id,
            "workspace_id": self.workspace_id,
            "customer_id": self.customer_id,
            "version": self.version,
            "commercial_request_id": self.commercial_request_id,
            "commercial_request_version": self.commercial_request_version,
            "supplier_quote_id": self.supplier_quote_id,
            "supplier_quote_version": self.supplier_quote_version,
            "pricing_policy_ref": self.pricing_policy_ref,
            "markup_bps": self.markup_bps,
            "gross_margin_bps": self.gross_margin_bps,
            "cost_total": self.cost_total.safe_dict(),
            "sale_total": self.sale_total.safe_dict(),
            "margin_total": self.margin_total.safe_dict(),
            "lines": [item.safe_dict() for item in self.lines],
            "pricing_fingerprint": self.pricing_fingerprint,
            "approval_required": True,
            "auto_send": False,
            "hidden_model_pricing": False,
            "rounding_rule": "ceil_to_minor_unit_after_markup",
        }


def build_customer_quote_draft(
    *,
    customer_quote_id: str,
    request: CommercialRequest,
    supplier_quote: SupplierQuote,
    policy: CustomerQuotePricingPolicy,
    version: int = 1,
) -> CustomerQuoteDraft:
    if not isinstance(request, CommercialRequest) or not isinstance(supplier_quote, SupplierQuote):
        raise ContractError("exact CommercialRequest and SupplierQuote are required")
    if not isinstance(policy, CustomerQuotePricingPolicy):
        raise ContractError("pricing policy must be CustomerQuotePricingPolicy")
    if request.workspace_id != supplier_quote.workspace_id:
        raise ContractError("customer request and supplier quote belong to different workspaces")
    if supplier_quote.status is SupplierQuoteStatus.REJECTED:
        raise ContractError("rejected supplier quote cannot be used as customer quote cost basis")
    request_by_line = {item.line_id: item for item in request.line_items}
    quote_by_line = {item.line_id: item for item in supplier_quote.lines}
    if set(request_by_line) != set(quote_by_line):
        raise ContractError("supplier quote line set does not match commercial request")

    lines: list[CustomerQuoteLine] = []
    for line_id in request_by_line:
        requested = request_by_line[line_id]
        cost = quote_by_line[line_id]
        if requested.quantity != cost.quantity:
            raise ContractError("supplier quote quantity does not match commercial request")
        if cost.unit_price.amount_minor < 0:
            raise ContractError("negative supplier cost cannot be used for sales quotation")
        sale_minor = _ceil_markup_minor(cost.unit_price.amount_minor, policy.markup_bps)
        lines.append(
            CustomerQuoteLine(
                line_id=line_id,
                description=requested.description,
                quantity=requested.quantity,
                unit=requested.unit,
                cost_unit_price=cost.unit_price,
                sale_unit_price=Money(sale_minor, cost.unit_price.currency),
            )
        )

    return CustomerQuoteDraft(
        customer_quote_id=customer_quote_id,
        workspace_id=request.workspace_id,
        customer_id=request.customer_id,
        version=version,
        commercial_request_id=request.request_id,
        commercial_request_version=request.version,
        supplier_quote_id=supplier_quote.quote_id,
        supplier_quote_version=supplier_quote.version,
        pricing_policy_ref=policy.policy_ref,
        markup_bps=policy.markup_bps,
        lines=tuple(lines),
        title=request.title,
    )


AUTO_CUSTOMER_QUOTE_SEND_SUPPORTED = False
MODEL_DRIVEN_HIDDEN_PRICING_SUPPORTED = False
FX_CONVERSION_SUPPORTED = False
