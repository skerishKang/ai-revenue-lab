from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import re
from typing import Any

from .contracts import ContractError
from .ops_contracts import Money
from .ops_customer_quote import CustomerQuoteDraft
from .ops_customer_quote_send import CustomerQuoteDeliveryReceipt
from .security import redact_secrets


_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,511}$")
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")


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


def _sha(value: str, field_name: str) -> str:
    value = value.strip().lower() if isinstance(value, str) else ""
    if not _SHA256_RE.fullmatch(value):
        raise ContractError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


class CustomerQuoteDecisionOutcome(str, Enum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    EXPIRED = "expired"


@dataclass(frozen=True, slots=True)
class TrustedCustomerQuoteDecision:
    decision_id: str
    workspace_id: str
    customer_id: str
    customer_quote_id: str
    quote_version: int
    pricing_fingerprint: str
    outcome: CustomerQuoteDecisionOutcome
    authority_ref: str
    evidence_ref: str
    decided_at: datetime

    def __post_init__(self) -> None:
        for field_name in ("decision_id", "workspace_id", "customer_id", "customer_quote_id", "authority_ref", "evidence_ref"):
            object.__setattr__(self, field_name, _ref(getattr(self, field_name), field_name))
        if isinstance(self.quote_version, bool) or not isinstance(self.quote_version, int) or self.quote_version < 1:
            raise ContractError("quote_version must be positive")
        object.__setattr__(self, "pricing_fingerprint", _sha(self.pricing_fingerprint, "pricing_fingerprint"))
        if not isinstance(self.outcome, CustomerQuoteDecisionOutcome):
            try:
                object.__setattr__(self, "outcome", CustomerQuoteDecisionOutcome(self.outcome))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid customer quote decision outcome") from exc
        object.__setattr__(self, "decided_at", _aware(self.decided_at, "decided_at"))

    def safe_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "workspace_id": self.workspace_id,
            "customer_id": self.customer_id,
            "customer_quote_id": self.customer_quote_id,
            "quote_version": self.quote_version,
            "pricing_fingerprint": self.pricing_fingerprint,
            "outcome": self.outcome.value,
            "authority_ref": self.authority_ref,
            "evidence_ref": self.evidence_ref,
            "decided_at": self.decided_at.isoformat().replace("+00:00", "Z"),
            "model_inferred": False,
        }


@dataclass(frozen=True, slots=True)
class SalesOrderProjection:
    sales_order_id: str
    workspace_id: str
    customer_id: str
    customer_quote_id: str
    customer_quote_version: int
    pricing_fingerprint: str
    acceptance_decision_id: str
    accepted_at: datetime
    currency: str
    sale_total: Money
    commercial_request_id: str
    commercial_request_version: int
    supplier_quote_id: str
    supplier_quote_version: int
    line_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        for field_name in (
            "sales_order_id",
            "workspace_id",
            "customer_id",
            "customer_quote_id",
            "acceptance_decision_id",
            "commercial_request_id",
            "supplier_quote_id",
        ):
            object.__setattr__(self, field_name, _ref(getattr(self, field_name), field_name))
        for field_name in ("customer_quote_version", "commercial_request_version", "supplier_quote_version"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ContractError(f"{field_name} must be positive")
        object.__setattr__(self, "pricing_fingerprint", _sha(self.pricing_fingerprint, "pricing_fingerprint"))
        object.__setattr__(self, "accepted_at", _aware(self.accepted_at, "accepted_at"))
        if not isinstance(self.sale_total, Money) or self.sale_total.amount_minor < 0:
            raise ContractError("sale_total must be non-negative Money")
        if not isinstance(self.currency, str) or self.currency != self.sale_total.currency:
            raise ContractError("sales-order currency must match sale_total")
        if not isinstance(self.line_refs, tuple) or not self.line_refs or len(self.line_refs) > 200:
            raise ContractError("line_refs must be a non-empty bounded tuple")
        normalized = tuple(_ref(value, "line_ref") for value in self.line_refs)
        if len(normalized) != len(set(normalized)):
            raise ContractError("line_refs must be unique")
        object.__setattr__(self, "line_refs", normalized)

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-ops-sales-order-projection.v2",
            "sales_order_id": self.sales_order_id,
            "workspace_id": self.workspace_id,
            "customer_id": self.customer_id,
            "customer_quote_id": self.customer_quote_id,
            "customer_quote_version": self.customer_quote_version,
            "pricing_fingerprint": self.pricing_fingerprint,
            "acceptance_decision_id": self.acceptance_decision_id,
            "accepted_at": self.accepted_at.isoformat().replace("+00:00", "Z"),
            "currency": self.currency,
            "sale_total": self.sale_total.safe_dict(),
            "commercial_request_id": self.commercial_request_id,
            "commercial_request_version": self.commercial_request_version,
            "supplier_quote_id": self.supplier_quote_id,
            "supplier_quote_version": self.supplier_quote_version,
            "line_refs": list(self.line_refs),
            "accounting_authority": False,
            "payment_authority": False,
            "fulfillment_authority": False,
        }


class InMemoryCustomerQuoteDecisionLedger:
    def __init__(self) -> None:
        self._decisions: dict[str, TrustedCustomerQuoteDecision] = {}
        self._by_quote: dict[tuple[str, str, int], str] = {}

    def record(self, decision: TrustedCustomerQuoteDecision) -> TrustedCustomerQuoteDecision:
        if not isinstance(decision, TrustedCustomerQuoteDecision):
            raise ContractError("decision must be TrustedCustomerQuoteDecision")
        existing = self._decisions.get(decision.decision_id)
        if existing is not None:
            if existing != decision:
                raise ContractError("conflicting customer quote decision replay")
            return existing
        quote_key = (decision.workspace_id, decision.customer_quote_id, decision.quote_version)
        prior_id = self._by_quote.get(quote_key)
        if prior_id is not None:
            prior = self._decisions[prior_id]
            if prior != decision:
                raise ContractError("customer quote version already has a different terminal decision")
            return prior
        self._decisions[decision.decision_id] = decision
        self._by_quote[quote_key] = decision.decision_id
        return decision

    def build_sales_order(
        self,
        *,
        quote: CustomerQuoteDraft,
        delivery_receipt: CustomerQuoteDeliveryReceipt,
        decision: TrustedCustomerQuoteDecision,
    ) -> SalesOrderProjection:
        if not isinstance(quote, CustomerQuoteDraft):
            raise ContractError("quote must be CustomerQuoteDraft")
        if not isinstance(delivery_receipt, CustomerQuoteDeliveryReceipt):
            raise ContractError("delivery_receipt must be CustomerQuoteDeliveryReceipt")
        decision = self.record(decision)
        if (
            delivery_receipt.customer_quote_id != quote.customer_quote_id
            or delivery_receipt.quote_version != quote.version
        ):
            raise ContractError("customer quote send receipt does not match exact quote version")
        if delivery_receipt.delivered_at > decision.decided_at:
            raise ContractError("customer quote decision cannot predate quote delivery")
        if (
            decision.workspace_id != quote.workspace_id
            or decision.customer_id != quote.customer_id
            or decision.customer_quote_id != quote.customer_quote_id
            or decision.quote_version != quote.version
            or decision.pricing_fingerprint != quote.pricing_fingerprint
        ):
            raise ContractError("trusted customer decision does not bind exact quote pricing/version")
        if decision.outcome is not CustomerQuoteDecisionOutcome.ACCEPTED:
            raise ContractError("only accepted customer quote may create sales-order projection")
        digest = hashlib.sha256(
            f"{quote.workspace_id}:{quote.customer_quote_id}:{quote.version}:{quote.pricing_fingerprint}".encode("utf-8")
        ).hexdigest()[:24]
        return SalesOrderProjection(
            sales_order_id=f"sales-order:{digest}",
            workspace_id=quote.workspace_id,
            customer_id=quote.customer_id,
            customer_quote_id=quote.customer_quote_id,
            customer_quote_version=quote.version,
            pricing_fingerprint=quote.pricing_fingerprint,
            acceptance_decision_id=decision.decision_id,
            accepted_at=decision.decided_at,
            currency=quote.currency,
            sale_total=quote.sale_total,
            commercial_request_id=quote.commercial_request_id,
            commercial_request_version=quote.commercial_request_version,
            supplier_quote_id=quote.supplier_quote_id,
            supplier_quote_version=quote.supplier_quote_version,
            line_refs=tuple(line.line_id for line in quote.lines),
        )


MODEL_INFERRED_CUSTOMER_ACCEPTANCE_SUPPORTED = False
INBOUND_MESSAGE_DIRECT_ACCEPTANCE_SUPPORTED = False
