from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import unittest

from padiem_ai_core import ApprovalOutcome, VerifiedApprovalDecision

from kagent.contracts import ContractError
from kagent.ops_contracts import CommercialRequest, LineItem, Money, SupplierQuote, SupplierQuoteLine, SupplierQuoteStatus
from kagent.ops_customer_quote import CustomerQuotePricingPolicy, build_customer_quote_draft
from kagent.ops_customer_quote_send import (
    REAL_CUSTOMER_QUOTE_SEND_CONFIGURED,
    ApprovalGatedCustomerQuoteSender,
    CustomerQuoteSendBinding,
    CustomerQuoteSendChannel,
    CustomerQuoteSendRequest,
    DeterministicFakeCustomerQuoteOutboundPort,
)


NOW = datetime(2026, 9, 3, 2, 30, tzinfo=timezone.utc)


def quote(markup_bps=1000, request_version=1, supplier_version=1):
    request = CommercialRequest(
        request_id="req_1",
        workspace_id="ws_1",
        customer_id="customer_1",
        version=request_version,
        title="고객 견적",
        line_items=(LineItem("line_1", "모터", Decimal("2"), "EA"),),
    )
    supplier = SupplierQuote(
        quote_id="supplier_quote_1",
        workspace_id="ws_1",
        rfq_id="rfq_1",
        supplier_id="supplier_1",
        version=supplier_version,
        lines=(SupplierQuoteLine("line_1", Decimal("2"), Money(1000)),),
        status=SupplierQuoteStatus.RECEIVED,
        received_at=NOW,
    )
    return build_customer_quote_draft(
        customer_quote_id="customer_quote_1",
        request=request,
        supplier_quote=supplier,
        policy=CustomerQuotePricingPolicy("pricing_1", markup_bps),
    )


def request_for(q=None, **kwargs):
    values = dict(
        request_id="send_1",
        quote=q or quote(),
        recipient_ref="customer_contact_1",
        channel=CustomerQuoteSendChannel.EMAIL,
        subject="견적서를 보내드립니다",
        body="검토 부탁드립니다.",
    )
    values.update(kwargs)
    return CustomerQuoteSendRequest(**values)


def decision(pause_id="pause_1", outcome=ApprovalOutcome.APPROVED):
    return VerifiedApprovalDecision(
        decision_id="decision_1",
        pause_id=pause_id,
        outcome=outcome,
        authority_ref="trusted_control_plane",
        evidence_ref="approval_evidence_1",
        decided_at=NOW,
    )


class CustomerQuoteSendTests(unittest.TestCase):
    def binding(self, req=None):
        req = req or request_for()
        return CustomerQuoteSendBinding.bind(
            binding_id="binding_1",
            pause_id="pause_1",
            quote=req.quote,
            recipient_ref=req.recipient_ref,
            channel=req.channel,
            subject=req.subject,
            body=req.body,
        )

    def test_binding_contains_hashes_not_raw_message(self):
        binding = self.binding()
        rendered = binding.safe_dict()
        self.assertFalse(rendered["raw_subject_or_body_in_binding"])
        self.assertEqual(len(rendered["subject_sha256"]), 64)
        self.assertEqual(len(rendered["body_sha256"]), 64)
        self.assertEqual(rendered["pricing_fingerprint"], quote().pricing_fingerprint)
        self.assertNotIn("subject", rendered)
        self.assertNotIn("body", rendered)

    def test_canonical_approved_decision_allows_network_free_fake_send(self):
        fake = DeterministicFakeCustomerQuoteOutboundPort(delivered_at=NOW)
        sender = ApprovalGatedCustomerQuoteSender(fake)
        req = request_for()
        receipt = sender.send(request=req, binding=self.binding(req), decision=decision())
        self.assertEqual(receipt.customer_quote_id, req.quote.customer_quote_id)
        self.assertEqual(receipt.quote_version, req.quote.version)
        self.assertEqual(len(fake.sent), 1)

    def test_rejected_decision_or_wrong_pause_fails_closed(self):
        req = request_for()
        sender = ApprovalGatedCustomerQuoteSender(DeterministicFakeCustomerQuoteOutboundPort(delivered_at=NOW))
        with self.assertRaises(ContractError):
            sender.send(request=req, binding=self.binding(req), decision=decision(outcome=ApprovalOutcome.REJECTED))
        with self.assertRaises(ContractError):
            sender.send(request=req, binding=self.binding(req), decision=decision(pause_id="other_pause"))

    def test_changed_message_recipient_or_channel_invalidates_binding(self):
        original = request_for()
        binding = self.binding(original)
        sender = ApprovalGatedCustomerQuoteSender(DeterministicFakeCustomerQuoteOutboundPort(delivered_at=NOW))
        variants = (
            request_for(body="내용 변경"),
            request_for(recipient_ref="customer_contact_2"),
            request_for(channel=CustomerQuoteSendChannel.BUSINESS_MESSAGING),
        )
        for changed in variants:
            with self.subTest(changed=changed):
                with self.assertRaises(ContractError):
                    sender.send(request=changed, binding=binding, decision=decision())

    def test_changed_pricing_or_source_version_invalidates_binding(self):
        original = request_for()
        binding = self.binding(original)
        sender = ApprovalGatedCustomerQuoteSender(DeterministicFakeCustomerQuoteOutboundPort(delivered_at=NOW))
        changed_quotes = (
            quote(markup_bps=1100),
            quote(request_version=2),
            quote(supplier_version=2),
        )
        for changed_quote in changed_quotes:
            with self.subTest(fingerprint=changed_quote.pricing_fingerprint):
                with self.assertRaises(ContractError):
                    sender.send(request=request_for(q=changed_quote), binding=binding, decision=decision())

    def test_default_real_send_fails_closed_after_valid_approval(self):
        req = request_for()
        sender = ApprovalGatedCustomerQuoteSender()
        with self.assertRaises(ContractError):
            sender.send(request=req, binding=self.binding(req), decision=decision())
        self.assertFalse(REAL_CUSTOMER_QUOTE_SEND_CONFIGURED)

    def test_secret_like_message_or_recipient_is_rejected_before_binding(self):
        with self.assertRaises(ContractError):
            request_for(body="api_key=should_not_be_here")
        with self.assertRaises(ContractError):
            request_for(recipient_ref="token=should_not_be_here")


if __name__ == "__main__":
    unittest.main()
