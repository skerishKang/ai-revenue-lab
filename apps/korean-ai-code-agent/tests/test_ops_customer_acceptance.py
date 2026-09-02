from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import unittest

from kagent.contracts import ContractError
from kagent.ops_contracts import CommercialRequest, LineItem, Money, SupplierQuote, SupplierQuoteLine, SupplierQuoteStatus
from kagent.ops_customer_acceptance import (
    INBOUND_MESSAGE_DIRECT_ACCEPTANCE_SUPPORTED,
    MODEL_INFERRED_CUSTOMER_ACCEPTANCE_SUPPORTED,
    CustomerQuoteDecisionOutcome,
    InMemoryCustomerQuoteDecisionLedger,
    TrustedCustomerQuoteDecision,
)
from kagent.ops_customer_quote import CustomerQuotePricingPolicy, build_customer_quote_draft
from kagent.ops_customer_quote_send import CustomerQuoteDeliveryReceipt


NOW = datetime(2026, 9, 3, 5, 0, tzinfo=timezone.utc)


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


def receipt(q=None, *, delivered_at=None):
    q = q or quote()
    return CustomerQuoteDeliveryReceipt(
        request_id="send_1",
        customer_quote_id=q.customer_quote_id,
        quote_version=q.version,
        connector_ref="fake_connector",
        external_message_ref="fake_message_1",
        delivered_at=delivered_at or NOW + timedelta(minutes=1),
    )


def decision(q=None, *, decision_id="decision_1", outcome=CustomerQuoteDecisionOutcome.ACCEPTED, decided_at=None, workspace_id=None, customer_id=None):
    q = q or quote()
    return TrustedCustomerQuoteDecision(
        decision_id=decision_id,
        workspace_id=workspace_id or q.workspace_id,
        customer_id=customer_id or q.customer_id,
        customer_quote_id=q.customer_quote_id,
        quote_version=q.version,
        pricing_fingerprint=q.pricing_fingerprint,
        outcome=outcome,
        authority_ref="trusted:customer-confirmation",
        evidence_ref="evidence:customer-confirmation-1",
        decided_at=decided_at or NOW + timedelta(minutes=5),
    )


class CustomerAcceptanceTests(unittest.TestCase):
    def test_accepted_exact_sent_quote_creates_sales_order_projection(self):
        q = quote()
        ledger = InMemoryCustomerQuoteDecisionLedger()
        order = ledger.build_sales_order(quote=q, delivery_receipt=receipt(q), decision=decision(q))
        self.assertEqual(order.customer_quote_id, q.customer_quote_id)
        self.assertEqual(order.customer_quote_version, q.version)
        self.assertEqual(order.sale_total, q.sale_total)
        self.assertEqual(order.pricing_fingerprint, q.pricing_fingerprint)
        rendered = order.safe_dict()
        self.assertFalse(rendered["accounting_authority"])
        self.assertFalse(rendered["payment_authority"])
        self.assertFalse(rendered["fulfillment_authority"])

    def test_rejected_and_expired_quote_cannot_create_sales_order(self):
        q = quote()
        for outcome in (CustomerQuoteDecisionOutcome.REJECTED, CustomerQuoteDecisionOutcome.EXPIRED):
            with self.subTest(outcome=outcome):
                ledger = InMemoryCustomerQuoteDecisionLedger()
                with self.assertRaises(ContractError):
                    ledger.build_sales_order(quote=q, delivery_receipt=receipt(q), decision=decision(q, outcome=outcome))

    def test_send_receipt_must_match_exact_quote_version(self):
        q = quote(version=2)
        wrong = CustomerQuoteDeliveryReceipt(
            request_id="send_wrong",
            customer_quote_id=q.customer_quote_id,
            quote_version=1,
            connector_ref="fake_connector",
            external_message_ref="fake_wrong",
            delivered_at=NOW + timedelta(minutes=1),
        )
        with self.assertRaises(ContractError):
            InMemoryCustomerQuoteDecisionLedger().build_sales_order(quote=q, delivery_receipt=wrong, decision=decision(q))

    def test_decision_must_bind_workspace_customer_version_and_pricing(self):
        q = quote()
        ledger = InMemoryCustomerQuoteDecisionLedger()
        with self.assertRaises(ContractError):
            ledger.build_sales_order(quote=q, delivery_receipt=receipt(q), decision=decision(q, workspace_id="ws_other"))
        with self.assertRaises(ContractError):
            ledger.build_sales_order(quote=q, delivery_receipt=receipt(q), decision=decision(q, customer_id="customer_other"))
        changed = quote(markup_bps=1200)
        stale = decision(q)
        with self.assertRaises(ContractError):
            InMemoryCustomerQuoteDecisionLedger().build_sales_order(quote=changed, delivery_receipt=receipt(changed), decision=stale)

    def test_decision_cannot_predate_delivery(self):
        q = quote()
        with self.assertRaises(ContractError):
            InMemoryCustomerQuoteDecisionLedger().build_sales_order(
                quote=q,
                delivery_receipt=receipt(q, delivered_at=NOW + timedelta(minutes=10)),
                decision=decision(q, decided_at=NOW + timedelta(minutes=5)),
            )

    def test_exact_decision_replay_is_idempotent_and_conflict_is_rejected(self):
        q = quote()
        ledger = InMemoryCustomerQuoteDecisionLedger()
        accepted = decision(q)
        self.assertEqual(ledger.record(accepted), ledger.record(accepted))
        conflict = decision(q, decision_id=accepted.decision_id, outcome=CustomerQuoteDecisionOutcome.REJECTED)
        with self.assertRaises(ContractError):
            ledger.record(conflict)

    def test_one_terminal_decision_per_quote_version(self):
        q = quote()
        ledger = InMemoryCustomerQuoteDecisionLedger()
        ledger.record(decision(q, decision_id="decision_accept"))
        with self.assertRaises(ContractError):
            ledger.record(decision(q, decision_id="decision_reject", outcome=CustomerQuoteDecisionOutcome.REJECTED))

    def test_acceptance_is_never_inferred_from_inbound_text_or_model_sentiment(self):
        self.assertFalse(MODEL_INFERRED_CUSTOMER_ACCEPTANCE_SUPPORTED)
        self.assertFalse(INBOUND_MESSAGE_DIRECT_ACCEPTANCE_SUPPORTED)
        rendered = decision().safe_dict()
        self.assertFalse(rendered["model_inferred"])


if __name__ == "__main__":
    unittest.main()
