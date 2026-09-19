from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from kagent.contracts import (
    SANDBOX_LEASE_MAX_TTL_SECONDS,
    ContractError,
    ExecutionMode,
    NetworkPolicy,
    ResourceClass,
    SandboxLease,
    SandboxLeaseRequest,
    SandboxLeaseState,
)
from kagent.sandbox import (
    DeterministicFakeSandboxProvider,
    SandboxLeaseError,
    SandboxUnavailableError,
    UnconfiguredSandboxProvider,
    supports_workload_cancellation,
)


class SandboxBoundaryTests(unittest.TestCase):
    def request(self, run_id: str = "run_001", *, ttl_seconds: int = 900) -> SandboxLeaseRequest:
        return SandboxLeaseRequest(
            run_id=run_id,
            execution_mode=ExecutionMode.CLOUD,
            repository_ref="skerishKang/example",
            requested_revision="abcdef1234567890abcdef1234567890abcdef12",
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


class SandboxLeaseRenewalProviderTests(unittest.TestCase):
    """A run may extend its reservation, but only inside the bounded lifetime gate."""

    START = datetime(2026, 9, 2, 10, 0, tzinfo=timezone.utc)

    def request(self, run_id: str = "run_001", *, ttl_seconds: int = 900) -> SandboxLeaseRequest:
        return SandboxLeaseRequest(
            run_id=run_id,
            execution_mode=ExecutionMode.CLOUD,
            repository_ref="skerishKang/example",
            requested_revision="abcdef1234567890abcdef1234567890abcdef12",
            resource_class=ResourceClass.STANDARD,
            ttl_seconds=ttl_seconds,
        )

    def provider(self) -> tuple[DeterministicFakeSandboxProvider, list[datetime]]:
        clock = [self.START]
        return DeterministicFakeSandboxProvider(clock=lambda: clock[0]), clock

    def advance(self, clock: list[datetime], *, seconds: int) -> None:
        clock[0] = self.START + timedelta(seconds=seconds)

    def test_renew_extends_expiry_and_keeps_one_active_lease_per_run(self):
        provider, clock = self.provider()
        lease = provider.allocate(self.request())
        self.advance(clock, seconds=600)

        renewed = provider.renew(lease.lease_id, run_id="run_001", ttl_seconds=600)

        self.assertEqual(renewed.lease_id, lease.lease_id)
        self.assertEqual(renewed.run_id, "run_001")
        self.assertEqual(renewed.state, SandboxLeaseState.RESERVED)
        self.assertEqual(renewed.expires_at, self.START + timedelta(seconds=1_200))
        with self.assertRaises(SandboxLeaseError):
            provider.allocate(self.request("run_001"))

    def test_renew_lets_a_run_survive_the_original_ttl_boundary(self):
        provider, clock = self.provider()
        lease = provider.allocate(self.request(ttl_seconds=900))
        self.advance(clock, seconds=899)
        provider.renew(lease.lease_id, run_id="run_001", ttl_seconds=600)

        self.advance(clock, seconds=1_400)
        observed = provider.get(lease.lease_id)

        self.assertEqual(observed.state, SandboxLeaseState.RESERVED)
        self.assertEqual(observed.expires_at, self.START + timedelta(seconds=1_499))

    def test_renew_stores_the_extension_so_a_later_release_sees_it(self):
        provider, clock = self.provider()
        lease = provider.allocate(self.request(ttl_seconds=900))
        self.advance(clock, seconds=600)
        provider.renew(lease.lease_id, run_id="run_001", ttl_seconds=600)

        released = provider.release(lease.lease_id, run_id="run_001")

        self.assertEqual(released.state, SandboxLeaseState.RELEASED)
        self.assertEqual(released.expires_at, self.START + timedelta(seconds=1_200))

    def test_renew_cannot_push_lifetime_past_the_maximum_permitted_ttl(self):
        provider, clock = self.provider()
        lease = provider.allocate(self.request(ttl_seconds=900))

        # Walk the reservation up to the ceiling in legal steps: each renewal has to
        # land before the current expiry, so the cap can only be reached, never passed.
        for elapsed, ttl in ((800, 600), (1_300, 1_200), (2_400, 1_200)):
            self.advance(clock, seconds=elapsed)
            capped = provider.renew(lease.lease_id, run_id="run_001", ttl_seconds=ttl)
            self.assertEqual(capped.expires_at, self.START + timedelta(seconds=elapsed + ttl))

        self.assertEqual(
            capped.expires_at - capped.created_at, timedelta(seconds=SANDBOX_LEASE_MAX_TTL_SECONDS)
        )

        self.advance(clock, seconds=SANDBOX_LEASE_MAX_TTL_SECONDS - 1)
        with self.assertRaises(SandboxLeaseError) as caught:
            provider.renew(lease.lease_id, run_id="run_001", ttl_seconds=60)
        self.assertIn("lifetime", str(caught.exception))
        # Translation keeps one error type at the port while the contract stays the reason.
        self.assertIsInstance(caught.exception.__cause__, ContractError)

    def test_renew_that_would_shorten_the_lease_fails_closed(self):
        provider, clock = self.provider()
        lease = provider.allocate(self.request(ttl_seconds=900))

        with self.assertRaises(SandboxLeaseError) as caught:
            provider.renew(lease.lease_id, run_id="run_001", ttl_seconds=60)
        self.assertIn("forward", str(caught.exception))

        self.assertEqual(provider.get(lease.lease_id).expires_at, self.START + timedelta(seconds=900))

    def test_renew_after_expiry_cannot_resurrect_the_lease(self):
        provider, clock = self.provider()
        lease = provider.allocate(self.request(ttl_seconds=60))
        self.advance(clock, seconds=61)

        self.assertEqual(provider.get(lease.lease_id).state, SandboxLeaseState.EXPIRED)
        with self.assertRaises(SandboxLeaseError):
            provider.renew(lease.lease_id, run_id="run_001", ttl_seconds=60)

    def test_renew_after_release_fails_closed(self):
        provider, clock = self.provider()
        lease = provider.allocate(self.request())
        provider.release(lease.lease_id, run_id="run_001")

        with self.assertRaises(SandboxLeaseError):
            provider.renew(lease.lease_id, run_id="run_001", ttl_seconds=600)

    def test_renew_rejects_cross_run_and_unknown_lease(self):
        provider, clock = self.provider()
        lease = provider.allocate(self.request())

        with self.assertRaises(SandboxLeaseError):
            provider.renew(lease.lease_id, run_id="run_002", ttl_seconds=600)
        with self.assertRaises(SandboxLeaseError):
            provider.renew("fake_lease_9999", run_id="run_001", ttl_seconds=600)

    def test_renew_validates_ttl_bounds_and_types(self):
        provider, clock = self.provider()
        lease = provider.allocate(self.request())

        for invalid in (59, SANDBOX_LEASE_MAX_TTL_SECONDS + 1, 0, -60, True, 600.0, "600", None):
            with self.subTest(ttl_seconds=invalid):
                with self.assertRaises(SandboxLeaseError):
                    provider.renew(lease.lease_id, run_id="run_001", ttl_seconds=invalid)

    def test_renewal_projection_still_leaks_no_host_endpoint_or_credential(self):
        provider, clock = self.provider()
        lease = provider.allocate(self.request())
        self.advance(clock, seconds=600)
        renewed = provider.renew(lease.lease_id, run_id="run_001", ttl_seconds=600)

        rendered = renewed.safe_dict()

        self.assertEqual(rendered, provider.get(lease.lease_id).safe_dict())
        for forbidden in ("host", "endpoint", "credential", "image", "mount"):
            self.assertNotIn(forbidden, rendered)

    def test_unconfigured_provider_renew_fails_closed_without_cloud_claim(self):
        provider = UnconfiguredSandboxProvider()
        with self.assertRaises(SandboxUnavailableError) as caught:
            provider.renew("lease_001", run_id="run_001", ttl_seconds=600)
        self.assertIn("not configured", str(caught.exception))


class SandboxLeaseWithExpiryContractTests(unittest.TestCase):
    """The lifetime ceiling is a property of the contract, not of caller discipline."""

    START = datetime(2026, 9, 2, 10, 0, tzinfo=timezone.utc)

    def lease(self, *, ttl_seconds: int = 900, state: SandboxLeaseState = SandboxLeaseState.RESERVED) -> SandboxLease:
        return SandboxLease(
            lease_id="lease_001",
            run_id="run_001",
            execution_mode=ExecutionMode.CLOUD,
            resource_class=ResourceClass.STANDARD,
            network_policy=NetworkPolicy.OFF,
            writable_workspace=True,
            created_at=self.START,
            expires_at=self.START + timedelta(seconds=ttl_seconds),
            state=state,
        )

    def test_with_expiry_advances_only_the_expiry_field(self):
        extended = self.lease().with_expiry(self.START + timedelta(seconds=1_200))

        self.assertEqual(extended.expires_at, self.START + timedelta(seconds=1_200))
        self.assertEqual(extended.created_at, self.START)
        self.assertEqual(extended.lease_id, "lease_001")
        self.assertEqual(extended.run_id, "run_001")
        self.assertEqual(extended.execution_mode, ExecutionMode.CLOUD)
        self.assertEqual(extended.resource_class, ResourceClass.STANDARD)
        self.assertEqual(extended.network_policy, NetworkPolicy.OFF)
        self.assertTrue(extended.writable_workspace)
        self.assertEqual(extended.state, SandboxLeaseState.RESERVED)

    def test_with_expiry_rejects_forward_only_violations(self):
        source = self.lease()
        for candidate in (
            self.START + timedelta(seconds=100),
            self.START + timedelta(seconds=900),
        ):
            with self.subTest(expires_at=candidate):
                with self.assertRaises(ContractError):
                    source.with_expiry(candidate)

    def test_with_expiry_rejects_lifetimes_past_the_cap(self):
        with self.assertRaises(ContractError) as caught:
            self.lease().with_expiry(self.START + timedelta(seconds=SANDBOX_LEASE_MAX_TTL_SECONDS + 1))
        self.assertIn("lifetime", str(caught.exception))

    def test_with_expiry_allows_a_lifetime_exactly_at_the_cap(self):
        extended = self.lease().with_expiry(
            self.START + timedelta(seconds=SANDBOX_LEASE_MAX_TTL_SECONDS)
        )
        self.assertEqual(
            extended.expires_at - extended.created_at, timedelta(seconds=SANDBOX_LEASE_MAX_TTL_SECONDS)
        )

    def test_with_expiry_rejects_non_reserved_states(self):
        for state in (SandboxLeaseState.RELEASED, SandboxLeaseState.EXPIRED):
            with self.subTest(state=state):
                with self.assertRaises(ContractError):
                    self.lease(state=state).with_expiry(self.START + timedelta(seconds=1_200))

    def test_with_expiry_requires_timezone_aware_expiry(self):
        with self.assertRaises(ContractError):
            self.lease().with_expiry(datetime(2026, 9, 2, 10, 30))

    def test_with_expiry_rejects_non_datetime(self):
        with self.assertRaises(ContractError):
            self.lease().with_expiry("2026-09-02T10:30:00Z")

    def test_cap_constant_matches_the_lease_request_bound(self):
        request = SandboxLeaseRequest(
            run_id="run_001",
            execution_mode=ExecutionMode.CLOUD,
            repository_ref="skerishKang/example",
            requested_revision="abcdef1234567890abcdef1234567890abcdef12",
            ttl_seconds=SANDBOX_LEASE_MAX_TTL_SECONDS,
        )
        with self.assertRaises(ContractError):
            SandboxLeaseRequest(
                run_id="run_001",
                execution_mode=ExecutionMode.CLOUD,
                repository_ref="skerishKang/example",
                requested_revision="abcdef1234567890abcdef1234567890abcdef12",
                ttl_seconds=SANDBOX_LEASE_MAX_TTL_SECONDS + 1,
            )
        self.assertEqual(request.ttl_seconds, SANDBOX_LEASE_MAX_TTL_SECONDS)


class WorkloadCancellationTests(unittest.TestCase):
    """#1405 / #2790: cancellation must be a real operation, not a declaration."""

    START = datetime(2026, 9, 2, 10, 0, tzinfo=timezone.utc)

    def request(self, run_id: str = "run_cancel") -> SandboxLeaseRequest:
        return SandboxLeaseRequest(
            run_id=run_id,
            execution_mode=ExecutionMode.CLOUD,
            repository_ref="skerishKang/example",
            requested_revision="abcdef1234567890abcdef1234567890abcdef12",
            ttl_seconds=900,
        )

    def provider(self) -> DeterministicFakeSandboxProvider:
        return DeterministicFakeSandboxProvider(clock=lambda: self.START)

    def test_cancel_terminates_the_lease(self):
        provider = self.provider()
        lease = provider.allocate(self.request())
        cancelled = provider.cancel(lease.lease_id, run_id="run_cancel")
        self.assertIs(cancelled.state, SandboxLeaseState.RELEASED)
        self.assertIs(provider.get(lease.lease_id).state, SandboxLeaseState.RELEASED)

    def test_cancel_requires_the_matching_run(self):
        provider = self.provider()
        lease = provider.allocate(self.request())
        with self.assertRaises(SandboxLeaseError):
            provider.cancel(lease.lease_id, run_id="run_someone_else")
        # a rejected cancellation must not have ended anything
        self.assertIs(provider.get(lease.lease_id).state, SandboxLeaseState.RESERVED)

    def test_cancel_of_unknown_lease_fails_closed(self):
        with self.assertRaises(SandboxLeaseError):
            self.provider().cancel("fake_lease_missing", run_id="run_cancel")

    def test_double_cancel_fails_closed(self):
        provider = self.provider()
        lease = provider.allocate(self.request())
        provider.cancel(lease.lease_id, run_id="run_cancel")
        with self.assertRaises(SandboxLeaseError):
            provider.cancel(lease.lease_id, run_id="run_cancel")

    def test_cancelled_lease_cannot_be_renewed_or_released(self):
        provider = self.provider()
        lease = provider.allocate(self.request())
        provider.cancel(lease.lease_id, run_id="run_cancel")
        with self.assertRaises(SandboxLeaseError):
            provider.renew(lease.lease_id, run_id="run_cancel", ttl_seconds=900)
        with self.assertRaises(SandboxLeaseError):
            provider.release(lease.lease_id, run_id="run_cancel")

    def test_cancel_frees_the_run_without_resurrecting_the_lease(self):
        # Cancellation is not a lock: the one-active-lease rule tracks active
        # leases, so the run may allocate again...
        provider = self.provider()
        first = provider.allocate(self.request())
        provider.cancel(first.lease_id, run_id="run_cancel")
        second = provider.allocate(self.request())
        self.assertNotEqual(first.lease_id, second.lease_id)
        # ...but the cancelled lease stays dead.
        with self.assertRaises(SandboxLeaseError):
            provider.release(first.lease_id, run_id="run_cancel")

    def test_release_and_cancel_share_one_terminal_rule(self):
        provider = self.provider()
        released = provider.release(provider.allocate(self.request("run_a")).lease_id, run_id="run_a")
        provider2 = self.provider()
        cancelled = provider2.cancel(provider2.allocate(self.request("run_a")).lease_id, run_id="run_a")
        self.assertIs(released.state, cancelled.state)

    def test_unconfigured_provider_reports_no_cancellation(self):
        provider = UnconfiguredSandboxProvider()
        with self.assertRaises(SandboxUnavailableError) as caught:
            provider.cancel("any_lease", run_id="run_cancel")
        message = str(caught.exception)
        self.assertIn("not configured", message)
        self.assertIn("no workload cancellation was performed", message)

    def test_capability_probe_reads_the_operation_not_a_declaration(self):
        self.assertTrue(supports_workload_cancellation(self.provider()))
        # The unconfigured provider exposes cancel too — and refuses it. The probe
        # answers "is there an operation to call", never "will it succeed"; that
        # question is answered by exercising it, which is conformance's job.
        self.assertTrue(supports_workload_cancellation(UnconfiguredSandboxProvider()))

        class LeaseOnlyProvider:
            """Satisfies SandboxLeasePort but cannot cancel."""

            def allocate(self, request):
                raise AssertionError("unused")

            def get(self, lease_id):
                raise AssertionError("unused")

            def renew(self, lease_id, *, run_id, ttl_seconds):
                raise AssertionError("unused")

            def release(self, lease_id, *, run_id):
                raise AssertionError("unused")

        self.assertFalse(supports_workload_cancellation(LeaseOnlyProvider()))
        self.assertFalse(supports_workload_cancellation(object()))
        # a non-callable attribute named cancel is not an operation, and a
        # self-declared boolean cannot rescue it — trusting that boolean is exactly
        # the failure mode #1405 recorded.
        decoy = self.provider()
        decoy.cancel = "not callable"  # type: ignore[method-assign]
        decoy.cancellation_kills_workload = True
        self.assertFalse(supports_workload_cancellation(decoy))


if __name__ == "__main__":
    unittest.main()
