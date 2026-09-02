from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from kagent.agent_computer import (
    AGENT_COMPUTER_ALLOCATION_IMPLIES_P01_START,
    CROSS_RUN_COMPUTER_REUSE_SUPPORTED,
    REAL_AGENT_COMPUTER_PROVIDER_CONFIGURED,
    AgentComputerRequest,
    AgentComputerLeaseState,
    DeterministicFakeAgentComputerPort,
    UnconfiguredAgentComputerPort,
)
from kagent.contracts import (
    ContractError,
    ExecutionMode,
    NetworkPolicy,
    ResourceClass,
    SandboxLease,
    SandboxLeaseState,
)


NOW = datetime(2026, 9, 3, 2, 0, tzinfo=timezone.utc)


def sandbox(**kwargs):
    values = dict(
        lease_id="sandbox_1",
        run_id="run_1",
        execution_mode=ExecutionMode.CLOUD,
        resource_class=ResourceClass.STANDARD,
        network_policy=NetworkPolicy.OFF,
        writable_workspace=True,
        created_at=NOW,
        expires_at=NOW + timedelta(minutes=30),
        state=SandboxLeaseState.RESERVED,
    )
    values.update(kwargs)
    return SandboxLease(**values)


def request(**kwargs):
    values = dict(
        request_id="computer_request_1",
        run_id="run_1",
        sandbox_lease_id="sandbox_1",
        workspace_ref="workspace_run_1",
        browser_required=True,
        requested_at=NOW + timedelta(seconds=1),
        ttl_seconds=600,
    )
    values.update(kwargs)
    return AgentComputerRequest(**values)


class AgentComputerTests(unittest.TestCase):
    def test_safe_request_contains_no_provider_host_or_credential_authority(self):
        rendered = request().safe_dict()
        self.assertFalse(rendered["raw_credentials"])
        self.assertFalse(rendered["provider_endpoint"])
        self.assertFalse(rendered["host_mount"])
        self.assertFalse(rendered["runtime_socket"])

    def test_network_free_cloud_sandbox_allocates_isolated_workspace_and_browser(self):
        fake = DeterministicFakeAgentComputerPort()
        lease = fake.allocate(request(), sandbox_lease=sandbox())
        self.assertTrue(lease.active)
        self.assertEqual(lease.workspace_ref, "workspace_run_1")
        self.assertIsNotNone(lease.browser_session_ref)
        rendered = lease.safe_dict()
        self.assertTrue(rendered["isolated_workspace"])
        self.assertFalse(rendered["cross_run_reuse"])
        self.assertFalse(rendered["allocation_implies_p01_started"])

    def test_browser_is_optional_but_workspace_is_always_isolated(self):
        fake = DeterministicFakeAgentComputerPort()
        lease = fake.allocate(request(browser_required=False), sandbox_lease=sandbox())
        self.assertIsNone(lease.browser_session_ref)
        self.assertTrue(lease.safe_dict()["isolated_workspace"])

    def test_run_and_sandbox_lease_identity_must_match(self):
        fake = DeterministicFakeAgentComputerPort()
        with self.assertRaises(ContractError):
            fake.allocate(request(run_id="run_2"), sandbox_lease=sandbox())
        with self.assertRaises(ContractError):
            fake.allocate(request(sandbox_lease_id="other_lease"), sandbox_lease=sandbox())

    def test_local_restricted_network_or_terminal_sandbox_lease_is_rejected(self):
        fake = DeterministicFakeAgentComputerPort()
        with self.assertRaises(ContractError):
            fake.allocate(request(), sandbox_lease=sandbox(execution_mode=ExecutionMode.LOCAL))
        with self.assertRaises(ContractError):
            fake.allocate(request(), sandbox_lease=sandbox(network_policy=NetworkPolicy.RESTRICTED))
        with self.assertRaises(ContractError):
            fake.allocate(request(), sandbox_lease=sandbox(state=SandboxLeaseState.RELEASED))

    def test_agent_computer_ttl_cannot_outlive_sandbox(self):
        fake = DeterministicFakeAgentComputerPort()
        with self.assertRaises(ContractError):
            fake.allocate(request(ttl_seconds=1800), sandbox_lease=sandbox(expires_at=NOW + timedelta(minutes=10)))

    def test_one_active_computer_per_run(self):
        fake = DeterministicFakeAgentComputerPort()
        fake.allocate(request(), sandbox_lease=sandbox())
        with self.assertRaises(ContractError):
            fake.allocate(request(request_id="computer_request_2", workspace_ref="workspace_run_2"), sandbox_lease=sandbox())

    def test_workspace_ref_is_never_reused_even_after_release(self):
        fake = DeterministicFakeAgentComputerPort()
        first = fake.allocate(request(), sandbox_lease=sandbox())
        released = fake.release(first.computer_id, now=NOW + timedelta(minutes=2))
        self.assertEqual(released.state, AgentComputerLeaseState.RELEASED)
        with self.assertRaises(ContractError):
            fake.allocate(
                request(request_id="computer_request_2", workspace_ref="workspace_run_1", requested_at=NOW + timedelta(minutes=3)),
                sandbox_lease=sandbox(),
            )

    def test_terminal_computer_cannot_be_released_twice_or_resurrected(self):
        fake = DeterministicFakeAgentComputerPort()
        first = fake.allocate(request(), sandbox_lease=sandbox())
        fake.release(first.computer_id, now=NOW + timedelta(minutes=2))
        with self.assertRaises(ContractError):
            fake.release(first.computer_id, now=NOW + timedelta(minutes=3))

    def test_expiry_is_terminal(self):
        fake = DeterministicFakeAgentComputerPort()
        first = fake.allocate(request(ttl_seconds=60), sandbox_lease=sandbox())
        expired = fake.release(first.computer_id, now=NOW + timedelta(minutes=2))
        self.assertEqual(expired.state, AgentComputerLeaseState.EXPIRED)

    def test_default_real_provider_fails_closed_and_no_authority_claims(self):
        with self.assertRaises(ContractError):
            UnconfiguredAgentComputerPort().allocate(request(), sandbox_lease=sandbox())
        self.assertFalse(REAL_AGENT_COMPUTER_PROVIDER_CONFIGURED)
        self.assertFalse(AGENT_COMPUTER_ALLOCATION_IMPLIES_P01_START)
        self.assertFalse(CROSS_RUN_COMPUTER_REUSE_SUPPORTED)


if __name__ == "__main__":
    unittest.main()
