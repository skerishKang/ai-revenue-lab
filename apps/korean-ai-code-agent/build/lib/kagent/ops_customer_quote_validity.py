from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re
from typing import Any

from .contracts import ContractError
from .ops_customer_acceptance import (
    CustomerQuoteDecisionOutcome,
    InMemoryCustomerQuoteDecisionLedger,
    SalesOrderProjection,
    TrustedCustomerQuoteDecision,
)
from .ops_customer_quote import CustomerQuoteDraft
from .ops_customer_quote_send import CustomerQuoteDeliveryReceipt
from .security import redact_secrets


_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,511}$")
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
MAX_QUOTE_VALIDITY_DAYS = 365


def _ref(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_REF_RE.fullmatch(value.strip()):
        raise ContractError(f"{field_name} must be a bounded safe reference")
    value = value.strip()
    if redact_secrets(value) != value:
        raise ContractError(f"{field_name} must not contain credential material")
    return value


def _sha(value: str, field_name: str) -> str:
    value = value.strip().lower() if isinstance(value, str) else ""
    if not _SHA256_RE.fullmatch(value):
        raise ContractError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ContractError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class TrustedQuoteValidityWindow:
    validity_ref: str
    workspace_id: str
    customer_id: str
    customer_quote_id: str
    quote_version: int
    pricing_fingerprint: str
    valid_until: datetime
    authority_ref: str
    evidence_ref: str

    def __post_init__(self) -> None:
        for field_name in (
            "validity_ref",
            "workspace_id",
            "customer_id",
            "customer_quote_id",
            "authority_ref",
            "evidence_ref",
        ):
            object.__setattr__(self, field_name, _ref(getattr(self, field_name), field_name))
        if isinstance(self.quote_version, bool) or not isinstance(self.quote_version, int) or self.quote_version < 1:
            raise ContractError("quote_version must be positive")
        object.__setattr__(self, "pricing_fingerprint", _sha(self.pricing_fingerprint, "pricing_fingerprint"))
        object.__setattr__(self, "valid_until", _aware(self.valid_until, "valid_until"))

    @classmethod
    def bind(
        cls,
        *,
        validity_ref: str,
        quote: CustomerQuoteDraft,
        valid_until: datetime,
        authority_ref: str,
        evidence_ref: str,
    ) -> "TrustedQuoteValidityWindow":
        if not isinstance(quote, CustomerQuoteDraft):
            raise ContractError("quote must be CustomerQuoteDraft")
        return cls(
            validity_ref=validity_ref,
            workspace_id=quote.workspace_id,
            customer_id=quote.customer_id,
            customer_quote_id=quote.customer_quote_id,
            quote_version=quote.version,
            pricing_fingerprint=quote.pricing_fingerprint,
            valid_until=valid_until,
            authority_ref=authority_ref,
            evidence_ref=evidence_ref,
        )

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-ops-quote-validity.v1",
            "validity_ref": self.validity_ref,
            "workspace_id": self.workspace_id,
            "customer_id": self.customer_id,
            "customer_quote_id": self.customer_quote_id,
            "quote_version": self.quote_version,
            "pricing_fingerprint": self.pricing_fingerprint,
            "valid_until": self.valid_until.isoformat().replace("+00:00", "Z"),
            "authority_ref": self.authority_ref,
            "evidence_ref": self.evidence_ref,
            "model_inferred": False,
            "auto_reprice": False,
            "auto_resend": False,
        }


class CustomerQuoteValidityGate:
    def __init__(self, ledger: InMemoryCustomerQuoteDecisionLedger | None = None) -> None:
        self.ledger = ledger or InMemoryCustomerQuoteDecisionLedger()

    def build_sales_order(
        self,
        *,
        quote: CustomerQuoteDraft,
        delivery_receipt: CustomerQuoteDeliveryReceipt,
        validity: TrustedQuoteValidityWindow,
        decision: TrustedCustomerQuoteDecision,
    ) -> SalesOrderProjection:
        if not isinstance(quote, CustomerQuoteDraft):
            raise ContractError("quote must be CustomerQuoteDraft")
        if not isinstance(delivery_receipt, CustomerQuoteDeliveryReceipt):
            raise ContractError("delivery_receipt must be CustomerQuoteDeliveryReceipt")
        if not isinstance(validity, TrustedQuoteValidityWindow):
            raise ContractError("validity must be TrustedQuoteValidityWindow")
        if not isinstance(decision, TrustedCustomerQuoteDecision):
            raise ContractError("decision must be TrustedCustomerQuoteDecision")

        if (
            validity.workspace_id != quote.workspace_id
            or validity.customer_id != quote.customer_id
            or validity.customer_quote_id != quote.customer_quote_id
            or validity.quote_version != quote.version
            or validity.pricing_fingerprint != quote.pricing_fingerprint
        ):
            raise ContractError("quote validity does not bind exact quote pricing/version")
        if (
            delivery_receipt.customer_quote_id != quote.customer_quote_id
            or delivery_receipt.quote_version != quote.version
        ):
            raise ContractError("delivery receipt does not bind exact quote version")
        if validity.valid_until < delivery_receipt.delivered_at:
            raise ContractError("quote validity cannot expire before delivery")
        if validity.valid_until - delivery_receipt.delivered_at > timedelta(days=MAX_QUOTE_VALIDITY_DAYS):
            raise ContractError("quote validity cannot exceed 365 days after delivery")
        if decision.decided_at < delivery_receipt.delivered_at:
            raise ContractError("customer decision cannot predate quote delivery")
        if decision.outcome is CustomerQuoteDecisionOutcome.ACCEPTED and decision.decided_at > validity.valid_until:
            raise ContractError("stale customer quote cannot be accepted after valid_until")
        if decision.outcome is not CustomerQuoteDecisionOutcome.ACCEPTED:
            raise ContractError("only accepted in-window quote may create sales order")

        return self.ledger.build_sales_order(
            quote=quote,
            delivery_receipt=delivery_receipt,
            decision=decision,
        )


MODEL_INFERRED_QUOTE_VALIDITY_SUPPORTED = False
FREE_FORM_VALIDITY_PARSING_SUPPORTED = False
AUTO_REPRICE_ON_EXPIRY_SUPPORTED = False
AUTO_RESEND_ON_EXPIRY_SUPPORTED = False
