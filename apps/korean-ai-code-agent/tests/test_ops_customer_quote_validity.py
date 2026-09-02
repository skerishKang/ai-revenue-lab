from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import unittest

from kagent.contracts import ContractError
from kagent.ops_contracts import CommercialRequest, LineItem, Money, SupplierQuote, SupplierQuoteLine, SupplierQuoteStatus
from kagent.ops_customer_acceptance import CustomerQuoteDecisionOutcome, TrustedCustomerQuoteDecision
from kagent.ops_customer_quote import CustomerQuotePricingPolicy, build_customer_quote_draft
from kagent.ops_customer_quote_send import CustomerQuoteDeliveryReceipt
from kagent.ops_customer_quote_validity import (
    AUTO_REPRICE_ON_EXPIRY_SUPPORTED,
    AUTO_RESEND_ON_EXPIRY_SUPPORTED,
    FREE_FORM_VALIDITY_PARSING_SUPPORTED,
    MAX_QUOTE_VALIDITY_DAYS,
    MODEL_INFERRED_QUOTE_VALIDITY_SUPPORTED,
    CustomerQuoteValidityGate,
    TrustedQuoteValidityWindow,
)


NOW = datetime(2026, 9, 3, 6, 0, tzinfo=timezone.utc)


def quote(*, version=1, markup_bps=1000):
    request = CommercialRequest(
        request_id="req_1",
        workspace_id="ws_1",
        customer_id="customer_1",
        version=1,
        title="견적",
        line_items=(LineItem("line_1", "모터", Decimal("2"), "EA"),),
    )
    supplier = SupplierQuote(
        quote_id="supplier_quote_1",
        workspace_id="ws_1",
        rfq_id="rfq_1",
        supplier_id="supplier_1",
        version=1,
        lines=(SupplierQuoteLine("line_1", Decimal("2"), Money(1000, "KRW")),),
        status=SupplierQuoteStatus.RECEIVED,
        received_at=NOW,
    )
    return build_customer_quote_draft(
        customer_quote_id="customer_quote_1",
        request=request,
        supplier_quote=supplier,
        policy=CustomerQuotePricingPolicy("policy_1", markup_bps),
        version=version,
    )


def receipt(q, *, delivered_at=None):
    return CustomerQuoteDeliveryReceipt(
        request_id="send_1",
        customer_quote_id=q.customer_quote_id,
        quote_version=q.version,
        connector_ref="fake_connector",
        external_message_ref="fake_message_1",
        delivered_at=delivered_at or NOW + timedelta(minutes=1),
    )


def decision(q, *, outcome=CustomerQuoteDecisionOutcome.ACCEPTED, decided_at=None):
    return TrustedCustomerQuoteDecision(
        decision_id="decision_1",
        workspace_id=q.workspace_id,
        customer_id=q.customer_id,
        customer_quote_id=q.customer_quote_id,
        quote_version=q.version,
        pricing_fingerprint=q.pricing_fingerprint,
        outcome=outcome,
        authority_ref="trusted:customer-confirmation",
        evidence_ref="evidence:decision-1",
        decided_at=decided_at or NOW + timedelta(days=5),
    )


def validity(q, *, valid_until=None, validity_ref="validity_1"):
    return TrustedQuoteValidityWindow.bind(
        validity_ref=validity_ref,
        quote=q,
        valid_until=valid_until or NOW + timedelta(days=30),
        authority_ref="trusted:commercial-policy",
        evidence_ref="evidence:validity-1",
    )


class CustomerQuoteValidityTests(unittest.TestCase):
    def test_in_window_acceptance_creates_sales_order(self):
        q = quote()
        order = CustomerQuoteValidityGate().build_sales_order(
            quote=q,
            delivery_receipt=receipt(q),
            validity=validity(q),
            decision=decision(q),
        )
        self.assertEqual(order.customer_quote_id, q.customer_quote_id)
        self.assertEqual(order.customer_quote_version, q.version)

    def test_acceptance_after_valid_until_fails_closed(self):
        q = quote()
        with self.assertRaises(ContractError):
            CustomerQuoteValidityGate().build_sales_order(
                quote=q,
                delivery_receipt=receipt(q),
                validity=validity(q, valid_until=NOW + timedelta(days=10)),
                decision=decision(q, decided_at=NOW + timedelta(days=11)),
            )

    def test_validity_cannot_expire_before_delivery_or_exceed_365_days(self):
        q = quote()
        delivered = receipt(q, delivered_at=NOW + timedelta(days=2))
        with self.assertRaises(ContractError):
            CustomerQuoteValidityGate().build_sales_order(
                quote=q,
                delivery_receipt=delivered,
                validity=validity(q, valid_until=NOW + timedelta(days=1)),
                decision=decision(q, decided_at=NOW + timedelta(days=2)),
            )
        with self.assertRaises(ContractError):
            CustomerQuoteValidityGate().build_sales_order(
                quote=q,
                delivery_receipt=receipt(q),
                validity=validity(q, valid_until=NOW + timedelta(days=MAX_QUOTE_VALIDITY_DAYS + 2)),
                decision=decision(q),
            )

    def test_validity_binds_exact_quote_version_and_pricing_fingerprint(self):
        q = quote()
        stale = validity(q)
        changed_version = quote(version=2)
        with self.assertRaises(ContractError):
            CustomerQuoteValidityGate().build_sales_order(
                quote=changed_version,
                delivery_receipt=receipt(changed_version),
                validity=stale,
                decision=decision(changed_version),
            )
        changed_pricing = quote(markup_bps=1200)
        with self.assertRaises(ContractError):
            CustomerQuoteValidityGate().build_sales_order(
                quote=changed_pricing,
                delivery_receipt=receipt(changed_pricing),
                validity=stale,
                decision=decision(changed_pricing),
            )

    def test_rejected_or_expired_decision_never_creates_order(self):
        q = quote()
        for outcome in (CustomerQuoteDecisionOutcome.REJECTED, CustomerQuoteDecisionOutcome.EXPIRED):
            with self.subTest(outcome=outcome):
                with self.assertRaises(ContractError):
                    CustomerQuoteValidityGate().build_sales_order(
                        quote=q,
                        delivery_receipt=receipt(q),
                        validity=validity(q),
                        decision=decision(q, outcome=outcome),
                    )

    def test_safe_projection_has_no_inferred_or_automatic_commercial_behavior(self):
        rendered = validity(quote()).safe_dict()
        self.assertFalse(rendered["model_inferred"])
        self.assertFalse(rendered["auto_reprice"])
        self.assertFalse(rendered["auto_resend"])
        self.assertFalse(MODEL_INFERRED_QUOTE_VALIDITY_SUPPORTED)
        self.assertFalse(FREE_FORM_VALIDITY_PARSING_SUPPORTED)
        self.assertFalse(AUTO_REPRICE_ON_EXPIRY_SUPPORTED)
        self.assertFalse(AUTO_RESEND_ON_EXPIRY_SUPPORTED)


if __name__ == "__main__":
    unittest.main()
