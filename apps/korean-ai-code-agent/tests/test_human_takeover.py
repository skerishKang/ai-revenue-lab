from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from kagent.contracts import ContractError
from kagent.human_takeover import (
    FILESYSTEM_CONTROL_SUPPORTED,
    REAL_BROWSER_TAKEOVER_PROVIDER_CONFIGURED,
    SHELL_CONTROL_SUPPORTED,
    TAKEOVER_IMPLIES_APPROVAL,
    TAKEOVER_IMPLIES_P01_RESUME,
    DeterministicFakeHumanBrowserControlPort,
    HumanTakeoverOutcome,
    HumanTakeoverReason,
    HumanTakeoverRequest,
    UnconfiguredHumanBrowserControlPort,
)


NOW = datetime(2026, 9, 3, 2, 0, tzinfo=timezone.utc)


def request(**kwargs):
    values = dict(
        request_id="takeover_req_1",
        run_id="run_1",
        sandbox_lease_id="sandbox_1",
        browser_session_ref="browser_1",
        reason=HumanTakeoverReason.MFA,
        requested_at=NOW,
        requested_ttl_seconds=300,
    )
    values.update(kwargs)
    return HumanTakeoverRequest(**values)


class HumanTakeoverTests(unittest.TestCase):
    def test_request_is_browser_only_and_captures_no_credentials(self):
        rendered = request().safe_dict()
        self.assertTrue(rendered["browser_control"])
        self.assertFalse(rendered["shell_control"])
        self.assertFalse(rendered["filesystem_control"])
        self.assertFalse(rendered["credential_capture"])

    def test_ttl_is_bounded_to_one_through_fifteen_minutes(self):
        for ttl in (59, 901):
            with self.subTest(ttl=ttl):
                with self.assertRaises(ContractError):
                    request(requested_ttl_seconds=ttl)
        self.assertEqual(request(requested_ttl_seconds=60).requested_ttl_seconds, 60)
        self.assertEqual(request(requested_ttl_seconds=900).requested_ttl_seconds, 900)

    def test_one_active_control_lease_per_run(self):
        fake = DeterministicFakeHumanBrowserControlPort()
        lease = fake.acquire(request())
        self.assertTrue(lease.active)
        with self.assertRaises(ContractError):
            fake.acquire(request(request_id="takeover_req_2"))

    def test_release_creates_safe_receipt_but_not_approval_or_resume(self):
        fake = DeterministicFakeHumanBrowserControlPort()
        lease = fake.acquire(request())
        receipt = fake.release(lease, outcome=HumanTakeoverOutcome.COMPLETED, completed_at=NOW + timedelta(minutes=2))
        rendered = receipt.safe_dict()
        self.assertEqual(receipt.outcome, HumanTakeoverOutcome.COMPLETED)
        self.assertFalse(rendered["credential_material_in_receipt"])
        self.assertFalse(rendered["browser_cookie_or_dom_in_receipt"])
        self.assertFalse(rendered["takeover_implies_approval"])
        self.assertFalse(rendered["takeover_implies_p01_resume"])

    def test_release_after_expiry_or_before_issue_fails_closed(self):
        fake = DeterministicFakeHumanBrowserControlPort()
        lease = fake.acquire(request())
        with self.assertRaises(ContractError):
            fake.release(lease, outcome=HumanTakeoverOutcome.COMPLETED, completed_at=NOW - timedelta(seconds=1))
        with self.assertRaises(ContractError):
            fake.release(lease, outcome=HumanTakeoverOutcome.COMPLETED, completed_at=NOW + timedelta(minutes=6))

    def test_expired_lease_cannot_be_released_or_reused(self):
        fake = DeterministicFakeHumanBrowserControlPort()
        lease = fake.acquire(request(requested_ttl_seconds=60))
        expired = fake.expire(run_id="run_1", now=NOW + timedelta(seconds=61))
        self.assertFalse(expired.active)
        with self.assertRaises(ContractError):
            fake.release(expired, outcome=HumanTakeoverOutcome.COMPLETED, completed_at=NOW + timedelta(seconds=61))
        # a new request can obtain a fresh lease after explicit expiry
        fresh = fake.acquire(request(request_id="takeover_req_2", requested_at=NOW + timedelta(seconds=62)))
        self.assertTrue(fresh.active)
        self.assertNotEqual(fresh.control_lease_id, lease.control_lease_id)

    def test_expire_before_deadline_fails_closed(self):
        fake = DeterministicFakeHumanBrowserControlPort()
        fake.acquire(request())
        with self.assertRaises(ContractError):
            fake.expire(run_id="run_1", now=NOW + timedelta(seconds=299))

    def test_default_real_browser_adapter_fails_closed(self):
        port = UnconfiguredHumanBrowserControlPort()
        with self.assertRaises(ContractError):
            port.acquire(request())

    def test_product_claims_no_shell_filesystem_approval_or_resume_authority(self):
        self.assertFalse(REAL_BROWSER_TAKEOVER_PROVIDER_CONFIGURED)
        self.assertFalse(SHELL_CONTROL_SUPPORTED)
        self.assertFalse(FILESYSTEM_CONTROL_SUPPORTED)
        self.assertFalse(TAKEOVER_IMPLIES_APPROVAL)
        self.assertFalse(TAKEOVER_IMPLIES_P01_RESUME)


if __name__ == "__main__":
    unittest.main()
