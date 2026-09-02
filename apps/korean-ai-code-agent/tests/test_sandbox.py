from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from kagent.contracts import (
    ExecutionMode,
    NetworkPolicy,
    ResourceClass,
    SandboxLeaseRequest,
    SandboxLeaseState,
)
from kagent.sandbox import (
    DeterministicFakeSandboxProvider,
    SandboxLeaseError,
    SandboxUnavailableError,
    UnconfiguredSandboxProvider,
)


class SandboxBoundaryTests(unittest.TestCase):
    def request(self, run_id: str = "run_001", *, ttl_seconds: int = 900) -> SandboxLeaseRequest:
        return SandboxLeaseRequest(
            run_id=run_id,
            execution_mode=ExecutionMode.CLOUD,
            repository_ref="skerishKang/example",
            requested_revision="abc123",
            resource_class=ResourceClass.STANDARD,
            ttl_seconds=ttl_seconds,
        )

    def test_unconfigured_provider_fails_closed_without_cloud_claim(self):
        provider = UnconfiguredSandboxProvider()
        with self.assertRaises(SandboxUnavailableError) as caught:
            provider.allocate(self.request())
        self.assertIn("not configured", str(caught.exception))
        self.assertIn("unexecuted", str(caught.exception))

    def test_fake_allocation_is_deterministic_and_network_off(self):
        now = datetime(2026, 9, 2, 10, 0, tzinfo=timezone.utc)
        provider = DeterministicFakeSandboxProvider(clock=lambda: now)
        lease = provider.allocate(self.request())
        self.assertEqual(lease.lease_id, "fake_lease_0001")
        self.assertEqual(lease.run_id, "run_001")
        self.assertEqual(lease.network_policy, NetworkPolicy.OFF)
        self.assertEqual(lease.state, SandboxLeaseState.RESERVED)
        self.assertEqual(lease.expires_at - lease.created_at, timedelta(seconds=900))
        rendered = lease.safe_dict()
        self.assertNotIn("host", rendered)
        self.assertNotIn("endpoint", rendered)
        self.assertNotIn("credential", rendered)

    def test_one_active_lease_per_run(self):
        now = datetime(2026, 9, 2, 10, 0, tzinfo=timezone.utc)
        provider = DeterministicFakeSandboxProvider(clock=lambda: now)
        provider.allocate(self.request())
        with self.assertRaises(SandboxLeaseError):
            provider.allocate(self.request())

    def test_release_rejects_cross_run_and_allows_reallocation_after_release(self):
        now = datetime(2026, 9, 2, 10, 0, tzinfo=timezone.utc)
        provider = DeterministicFakeSandboxProvider(clock=lambda: now)
        first = provider.allocate(self.request("run_001"))
        with self.assertRaises(SandboxLeaseError):
            provider.release(first.lease_id, run_id="run_002")
        released = provider.release(first.lease_id, run_id="run_001")
        self.assertEqual(released.state, SandboxLeaseState.RELEASED)
        second = provider.allocate(self.request("run_001"))
        self.assertEqual(second.lease_id, "fake_lease_0002")

    def test_expired_lease_is_not_reused(self):
        clock = [datetime(2026, 9, 2, 10, 0, tzinfo=timezone.utc)]
        provider = DeterministicFakeSandboxProvider(clock=lambda: clock[0])
        first = provider.allocate(self.request("run_001", ttl_seconds=60))
        clock[0] = clock[0] + timedelta(seconds=61)
        expired = provider.get(first.lease_id)
        self.assertEqual(expired.state, SandboxLeaseState.EXPIRED)
        second = provider.allocate(self.request("run_001", ttl_seconds=60))
        self.assertNotEqual(second.lease_id, first.lease_id)
        self.assertEqual(second.state, SandboxLeaseState.RESERVED)

    def test_release_of_expired_or_released_lease_fails_closed(self):
        clock = [datetime(2026, 9, 2, 10, 0, tzinfo=timezone.utc)]
        provider = DeterministicFakeSandboxProvider(clock=lambda: clock[0])
        lease = provider.allocate(self.request(ttl_seconds=60))
        released = provider.release(lease.lease_id, run_id="run_001")
        self.assertEqual(released.state, SandboxLeaseState.RELEASED)
        with self.assertRaises(SandboxLeaseError):
            provider.release(lease.lease_id, run_id="run_001")

        second = provider.allocate(self.request(ttl_seconds=60))
        clock[0] = clock[0] + timedelta(seconds=61)
        with self.assertRaises(SandboxLeaseError):
            provider.release(second.lease_id, run_id="run_001")


if __name__ == "__main__":
    unittest.main()
