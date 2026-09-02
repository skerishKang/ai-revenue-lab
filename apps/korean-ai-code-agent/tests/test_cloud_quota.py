from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from kagent.cloud_quota import (
    BILLING_AUTHORITY_IN_B54,
    REAL_CONTROL_PLANE_QUOTA_CALLS,
    CloudRunAdmissionRequest,
    CloudRunQuotaGuard,
    ControlPlaneEntitlementProjection,
    ControlPlaneUsageProjection,
    EntitlementState,
    QuotaDenialReason,
)
from kagent.contracts import ContractError


NOW = datetime(2026, 9, 3, 1, 0, tzinfo=timezone.utc)


def entitlement(**kwargs):
    values = dict(
        workspace_id="ws_1",
        entitlement_ref="ent_1",
        state=EntitlementState.ACTIVE,
        max_queued_runs=3,
        max_active_runs=2,
        max_daily_runtime_minutes=120,
        valid_until=NOW + timedelta(hours=1),
    )
    values.update(kwargs)
    return ControlPlaneEntitlementProjection(**values)


def usage(**kwargs):
    values = dict(
        workspace_id="ws_1",
        usage_ref="usage_1",
        queued_runs=0,
        active_runs=0,
        daily_runtime_minutes=0,
        observed_at=NOW,
    )
    values.update(kwargs)
    return ControlPlaneUsageProjection(**values)


def request(**kwargs):
    values = dict(request_id="admit_1", workspace_id="ws_1", run_id="run_1", requested_runtime_minutes=30)
    values.update(kwargs)
    return CloudRunAdmissionRequest(**values)


class CloudQuotaTests(unittest.TestCase):
    def setUp(self):
        self.guard = CloudRunQuotaGuard()

    def evaluate(self, req=None, ent=None, use=None, now=NOW):
        return self.guard.evaluate(request=req or request(), entitlement=ent or entitlement(), usage=use or usage(), now=now)

    def test_bounded_active_entitlement_allows_run(self):
        decision = self.evaluate()
        self.assertTrue(decision.allowed)
        self.assertIsNone(decision.denial_reason)
        self.assertEqual(decision.safe_dict()["billing_authority"], "control_plane")
        self.assertFalse(decision.safe_dict()["price_or_credit_calculation_in_b54"])

    def test_disabled_or_suspended_entitlement_denies(self):
        for state in (EntitlementState.DISABLED, EntitlementState.SUSPENDED):
            with self.subTest(state=state):
                decision = self.evaluate(ent=entitlement(state=state))
                self.assertFalse(decision.allowed)
                self.assertEqual(decision.denial_reason, QuotaDenialReason.ENTITLEMENT_INACTIVE)

    def test_expired_entitlement_or_stale_usage_fails_closed(self):
        expired = self.evaluate(ent=entitlement(valid_until=NOW - timedelta(seconds=1)))
        self.assertEqual(expired.denial_reason, QuotaDenialReason.ENTITLEMENT_STALE)
        stale = self.evaluate(use=usage(observed_at=NOW - timedelta(seconds=301)))
        self.assertEqual(stale.denial_reason, QuotaDenialReason.ENTITLEMENT_STALE)
        future = self.evaluate(use=usage(observed_at=NOW + timedelta(seconds=1)))
        self.assertEqual(future.denial_reason, QuotaDenialReason.ENTITLEMENT_STALE)

    def test_queue_concurrency_and_daily_runtime_limits(self):
        queue = self.evaluate(use=usage(queued_runs=3))
        self.assertEqual(queue.denial_reason, QuotaDenialReason.QUEUE_LIMIT)
        active = self.evaluate(use=usage(active_runs=2))
        self.assertEqual(active.denial_reason, QuotaDenialReason.ACTIVE_RUN_LIMIT)
        daily = self.evaluate(use=usage(daily_runtime_minutes=100), req=request(requested_runtime_minutes=21))
        self.assertEqual(daily.denial_reason, QuotaDenialReason.DAILY_RUNTIME_LIMIT)
        exact = self.evaluate(use=usage(daily_runtime_minutes=100), req=request(requested_runtime_minutes=20))
        self.assertTrue(exact.allowed)

    def test_cross_workspace_projection_mix_fails_closed(self):
        with self.assertRaises(ContractError):
            self.evaluate(ent=entitlement(workspace_id="ws_2"))
        with self.assertRaises(ContractError):
            self.evaluate(use=usage(workspace_id="ws_2"))

    def test_negative_usage_and_invalid_requested_runtime_are_rejected(self):
        with self.assertRaises(ContractError):
            usage(active_runs=-1)
        with self.assertRaises(ContractError):
            request(requested_runtime_minutes=0)

    def test_b54_claims_no_billing_authority_or_real_control_plane_calls(self):
        self.assertFalse(BILLING_AUTHORITY_IN_B54)
        self.assertEqual(REAL_CONTROL_PLANE_QUOTA_CALLS, 0)


if __name__ == "__main__":
    unittest.main()
