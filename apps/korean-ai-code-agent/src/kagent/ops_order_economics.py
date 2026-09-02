from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import hashlib
import re
from typing import Any

from .contracts import ContractError
from .ops_contracts import Money, PurchaseOrder
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


@dataclass(frozen=True, slots=True)
class CustomerPaymentTerms:
    terms_ref: str
    due_days: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "terms_ref", _ref(self.terms_ref, "terms_ref"))
        if isinstance(self.due_days, bool) or not isinstance(self.due_days, int) or not 0 <= self.due_days <= 3650:
            raise ContractError("due_days must be an integer between 0 and 3650")

    def safe_dict(self) -> dict[str, Any]:
        return {"terms_ref": self.terms_ref, "due_days": self.due_days, "trusted_master_data": True}


@dataclass(frozen=True, slots=True)
class SalesOrderReceivableHandoff:
    handoff_id: str
    workspace_id: str
    sales_order_id: str
    customer_id: str
    customer_quote_id: str
    customer_quote_version: int
    payment_terms_ref: str
    amount: Money
    expected_payment_date: date

    def __post_init__(self) -> None:
        for field_name in (
            "handoff_id",
            "workspace_id",
            "sales_order_id",
            "customer_id",
            "customer_quote_id",
            "payment_terms_ref",
        ):
            object.__setattr__(self, field_name, _ref(getattr(self, field_name), field_name))
        if isinstance(self.customer_quote_version, bool) or not isinstance(self.customer_quote_version, int) or self.customer_quote_version < 1:
            raise ContractError("customer_quote_version must be positive")
        if not isinstance(self.amount, Money) or self.amount.amount_minor < 0:
            raise ContractError("receivable amount must be non-negative Money")
        if not isinstance(self.expected_payment_date, date):
            raise ContractError("expected_payment_date must be date")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-ops-sales-order-receivable.v1",
            "handoff_id": self.handoff_id,
            "workspace_id": self.workspace_id,
            "sales_order_id": self.sales_order_id,
            "customer_id": self.customer_id,
            "customer_quote_id": self.customer_quote_id,
            "customer_quote_version": self.customer_quote_version,
            "payment_terms_ref": self.payment_terms_ref,
            "amount": self.amount.safe_dict(),
            "expected_payment_date": self.expected_payment_date.isoformat(),
            "advisory_projection": True,
            "accounting_authority": False,
            "tax_authority": False,
            "payment_authority": False,
            "invoice_created": False,
        }


@dataclass(frozen=True, slots=True)
class OrderEconomicsProjection:
    projection_id: str
    workspace_id: str
    sales_order_id: str
    purchase_order_id: str
    supplier_quote_id: str
    supplier_quote_version: int
    currency: str
    sale_total: Money
    purchase_total: Money
    gross_profit: Money
    gross_margin_bps: int

    def __post_init__(self) -> None:
        for field_name in ("projection_id", "workspace_id", "sales_order_id", "purchase_order_id", "supplier_quote_id"):
            object.__setattr__(self, field_name, _ref(getattr(self, field_name), field_name))
        if isinstance(self.supplier_quote_version, bool) or not isinstance(self.supplier_quote_version, int) or self.supplier_quote_version < 1:
            raise ContractError("supplier_quote_version must be positive")
        if not isinstance(self.sale_total, Money) or not isinstance(self.purchase_total, Money) or not isinstance(self.gross_profit, Money):
            raise ContractError("economics totals must use Money")
        if self.sale_total.currency != self.purchase_total.currency or self.sale_total.currency != self.gross_profit.currency:
            raise ContractError("order economics currencies must match")
        if self.currency != self.sale_total.currency:
            raise ContractError("currency must match totals")
        expected_profit = self.sale_total.amount_minor - self.purchase_total.amount_minor
        if self.gross_profit.amount_minor != expected_profit:
            raise ContractError("gross_profit must equal sale_total minus purchase_total")
        expected_margin = 0 if self.sale_total.amount_minor == 0 else (expected_profit * 10_000) // self.sale_total.amount_minor
        if self.gross_margin_bps != expected_margin:
            raise ContractError("gross_margin_bps is inconsistent with totals")

    @property
    def negative_gross_profit(self) -> bool:
        return self.gross_profit.amount_minor < 0

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-ops-order-economics.v1",
            "projection_id": self.projection_id,
            "workspace_id": self.workspace_id,
            "sales_order_id": self.sales_order_id,
            "purchase_order_id": self.purchase_order_id,
            "supplier_quote_id": self.supplier_quote_id,
            "supplier_quote_version": self.supplier_quote_version,
            "currency": self.currency,
            "sale_total": self.sale_total.safe_dict(),
            "purchase_total": self.purchase_total.safe_dict(),
            "gross_profit": self.gross_profit.safe_dict(),
            "gross_margin_bps": self.gross_margin_bps,
            "negative_gross_profit": self.negative_gross_profit,
            "advisory_only": True,
            "hidden_model_recommendation": False,
            "accounting_authority": False,
            "tax_authority": False,
            "payment_authority": False,
        }


def build_sales_order_receivable(
    *,
    sales_order: SalesOrderProjection,
    payment_terms: CustomerPaymentTerms,
) -> SalesOrderReceivableHandoff:
    if not isinstance(sales_order, SalesOrderProjection):
        raise ContractError("sales_order must be SalesOrderProjection")
    if not isinstance(payment_terms, CustomerPaymentTerms):
        raise ContractError("explicit CustomerPaymentTerms are required")
    expected = sales_order.accepted_at.date() + timedelta(days=payment_terms.due_days)
    digest = hashlib.sha256(
        f"{sales_order.sales_order_id}:{payment_terms.terms_ref}:{payment_terms.due_days}".encode("utf-8")
    ).hexdigest()[:24]
    return SalesOrderReceivableHandoff(
        handoff_id=f"receivable:{digest}",
        workspace_id=sales_order.workspace_id,
        sales_order_id=sales_order.sales_order_id,
        customer_id=sales_order.customer_id,
        customer_quote_id=sales_order.customer_quote_id,
        customer_quote_version=sales_order.customer_quote_version,
        payment_terms_ref=payment_terms.terms_ref,
        amount=sales_order.sale_total,
        expected_payment_date=expected,
    )


def project_order_economics(
    *,
    sales_order: SalesOrderProjection,
    purchase_order: PurchaseOrder,
) -> OrderEconomicsProjection:
    if not isinstance(sales_order, SalesOrderProjection):
        raise ContractError("sales_order must be SalesOrderProjection")
    if not isinstance(purchase_order, PurchaseOrder):
        raise ContractError("purchase_order must be PurchaseOrder")
    if purchase_order.workspace_id != sales_order.workspace_id:
        raise ContractError("sales order and purchase order belong to different workspaces")
    if (
        purchase_order.supplier_quote_id != sales_order.supplier_quote_id
        or purchase_order.supplier_quote_version != sales_order.supplier_quote_version
    ):
        raise ContractError("purchase order does not share exact supplier quote lineage with sales order")
    purchase_total = purchase_order.total
    if purchase_total.currency != sales_order.sale_total.currency:
        raise ContractError("order economics requires one currency; FX conversion is not supported")
    profit_minor = sales_order.sale_total.amount_minor - purchase_total.amount_minor
    margin_bps = 0 if sales_order.sale_total.amount_minor == 0 else (profit_minor * 10_000) // sales_order.sale_total.amount_minor
    digest = hashlib.sha256(
        f"{sales_order.sales_order_id}:{purchase_order.po_id}:{purchase_order.version}:{sales_order.pricing_fingerprint}".encode("utf-8")
    ).hexdigest()[:24]
    return OrderEconomicsProjection(
        projection_id=f"economics:{digest}",
        workspace_id=sales_order.workspace_id,
        sales_order_id=sales_order.sales_order_id,
        purchase_order_id=purchase_order.po_id,
        supplier_quote_id=sales_order.supplier_quote_id,
        supplier_quote_version=sales_order.supplier_quote_version,
        currency=sales_order.currency,
        sale_total=sales_order.sale_total,
        purchase_total=purchase_total,
        gross_profit=Money(profit_minor, sales_order.currency),
        gross_margin_bps=margin_bps,
    )


ACCOUNTING_WRITE_FROM_ORDER_ECONOMICS_SUPPORTED = False
TAX_CALCULATION_FROM_ORDER_ECONOMICS_SUPPORTED = False
PAYMENT_EXECUTION_FROM_ORDER_ECONOMICS_SUPPORTED = False
DUE_DATE_GUESSING_SUPPORTED = False
