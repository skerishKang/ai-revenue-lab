from __future__ import annotations

from datetime import date, datetime, timezone
import unittest

from kagent.contracts import ContractError
from kagent.ops_contracts import Money
from kagent.ops_customer_acceptance import SalesOrderProjection
from kagent.ops_customer_delivery import (
    AUTO_CUSTOMER_DELIVERY_MESSAGE_SUPPORTED,
    FULFILLMENT_MUTATION_SUPPORTED,
    REFUND_AUTHORITY_SUPPORTED,
    SUPPLIER_ETA_AUTO_PROMOTION_SUPPORTED,
    CustomerDeliveryStatus,
    TrustedCustomerDeliveryCommitment,
    TrustedCustomerDeliveryObservation,
    project_customer_delivery,
)


NOW = datetime(2026, 9, 3, 8, 0, tzinfo=timezone.utc)


def order():
    return SalesOrderProjection(
        sales_order_id="sales_order_1",
        workspace_id="ws_1",
        customer_id="customer_1",
        customer_quote_id="quote_1",
        customer_quote_version=1,
        pricing_fingerprint="a" * 64,
        acceptance_decision_id="decision_1",
        accepted_at=NOW,
        currency="KRW",
        sale_total=Money(10000, "KRW"),
        commercial_request_id="request_1",
        commercial_request_version=1,
        supplier_quote_id="supplier_quote_1",
        supplier_quote_version=1,
        line_refs=("line_1",),
    )


def commitment(o=None, *, promised=date(2026, 9, 20)):
    o = o or order()
    return TrustedCustomerDeliveryCommitment.bind(
        commitment_ref="customer_delivery_1",
        sales_order=o,
        promised_date=promised,
        authority_ref="trusted:commercial-contract",
        evidence_ref="evidence:customer-delivery-1",
    )


class CustomerDeliveryTests(unittest.TestCase):
    def test_status_is_on_track_due_soon_overdue_and_delivered(self):
        o = order()
        c = commitment(o)
        self.assertEqual(project_customer_delivery(sales_order=o, commitment=c, as_of=date(2026, 9, 10)).status, CustomerDeliveryStatus.ON_TRACK)
        self.assertEqual(project_customer_delivery(sales_order=o, commitment=c, as_of=date(2026, 9, 18)).status, CustomerDeliveryStatus.DUE_SOON)
        overdue = project_customer_delivery(sales_order=o, commitment=c, as_of=date(2026, 9, 23))
        self.assertEqual(overdue.status, CustomerDeliveryStatus.OVERDUE)
        self.assertEqual(overdue.days_overdue, 3)
        observation = TrustedCustomerDeliveryObservation(
            observation_id="delivery_obs_1",
            workspace_id=o.workspace_id,
            sales_order_id=o.sales_order_id,
            delivered_date=date(2026, 9, 22),
            observed_at=NOW,
            authority_ref="trusted:fulfillment-connector",
            evidence_ref="evidence:delivery-obs-1",
        )
        delivered = project_customer_delivery(sales_order=o, commitment=c, as_of=date(2026, 9, 23), observation=observation)
        self.assertEqual(delivered.status, CustomerDeliveryStatus.DELIVERED)
        self.assertEqual(delivered.days_overdue, 2)

    def test_commitment_and_observation_must_bind_exact_sales_order(self):
        o = order()
        c = TrustedCustomerDeliveryCommitment(
            commitment_ref="bad",
            workspace_id="ws_other",
            sales_order_id=o.sales_order_id,
            customer_id=o.customer_id,
            customer_quote_id=o.customer_quote_id,
            customer_quote_version=o.customer_quote_version,
            promised_date=date(2026, 9, 20),
            authority_ref="trusted:contract",
            evidence_ref="evidence:bad",
        )
        with self.assertRaises(ContractError):
            project_customer_delivery(sales_order=o, commitment=c, as_of=date(2026, 9, 10))
        observation = TrustedCustomerDeliveryObservation(
            observation_id="obs_bad",
            workspace_id="ws_other",
            sales_order_id=o.sales_order_id,
            delivered_date=date(2026, 9, 20),
            observed_at=NOW,
            authority_ref="trusted:fulfillment",
            evidence_ref="evidence:bad-obs",
        )
        with self.assertRaises(ContractError):
            project_customer_delivery(sales_order=o, commitment=commitment(o), as_of=date(2026, 9, 20), observation=observation)

    def test_safe_projection_keeps_supplier_and_customer_promises_separate(self):
        rendered = project_customer_delivery(sales_order=order(), commitment=commitment(), as_of=date(2026, 9, 10)).safe_dict()
        self.assertFalse(rendered["supplier_eta_used_as_customer_promise"])
        self.assertFalse(rendered["auto_customer_send"])
        self.assertFalse(rendered["refund_authority"])
        self.assertFalse(rendered["fulfillment_authority"])
        self.assertFalse(SUPPLIER_ETA_AUTO_PROMOTION_SUPPORTED)
        self.assertFalse(AUTO_CUSTOMER_DELIVERY_MESSAGE_SUPPORTED)
        self.assertFalse(REFUND_AUTHORITY_SUPPORTED)
        self.assertFalse(FULFILLMENT_MUTATION_SUPPORTED)


if __name__ == "__main__":
    unittest.main()
