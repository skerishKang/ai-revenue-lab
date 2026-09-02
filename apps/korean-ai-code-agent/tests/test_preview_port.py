from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from kagent.agent_computer import AgentComputerLease, AgentComputerLeaseState
from kagent.contracts import ContractError
from kagent.preview_port import (
    PERMANENT_PUBLIC_PREVIEW_SUPPORTED,
    PUBLIC_PREVIEW_BY_DEFAULT,
    REAL_PREVIEW_PORT_PROVIDER_CONFIGURED,
    DeterministicFakePreviewPortProvider,
    TrustedPreviewShareGrant,
    UnconfiguredPreviewPortProvider,
)


NOW = datetime(2026, 9, 3, 3, 0, tzinfo=timezone.utc)


def computer(*, run_id="run_1", computer_id="computer:1", state=AgentComputerLeaseState.ACTIVE, expires_at=None):
    return AgentComputerLease(
        computer_id=computer_id,
        request_id="computer-request:1",
        run_id=run_id,
        sandbox_lease_id="sandbox:1",
        workspace_ref=f"workspace:{run_id}",
        browser_session_ref=f"browser:{run_id}",
        issued_at=NOW,
        expires_at=expires_at or NOW + timedelta(minutes=20),
        state=state,
    )


def grant(endpoint, *, grant_id="grant:1", run_id=None, computer_id=None, port=None, issued_at=None, expires_at=None):
    return TrustedPreviewShareGrant(
        grant_id=grant_id,
        run_id=run_id or endpoint.run_id,
        computer_id=computer_id or endpoint.computer_id,
        endpoint_id=endpoint.endpoint_id,
        internal_port=port or endpoint.internal_port,
        authority_ref="control-plane:preview-share",
        issued_at=issued_at or NOW + timedelta(seconds=10),
        expires_at=expires_at or NOW + timedelta(minutes=5),
    )


class PreviewPortTests(unittest.TestCase):
    def test_private_endpoint_is_private_by_default_and_deterministic(self):
        provider = DeterministicFakePreviewPortProvider()
        lease = computer()
        first = provider.create_private(computer=lease, internal_port=3000, now=NOW + timedelta(seconds=1))
        second = provider.create_private(computer=lease, internal_port=3000, now=NOW + timedelta(seconds=2))
        self.assertEqual(first, second)
        rendered = first.safe_dict()
        self.assertTrue(rendered["private"])
        self.assertIsNone(rendered["public_url"])
        self.assertFalse(PUBLIC_PREVIEW_BY_DEFAULT)
        self.assertFalse(PERMANENT_PUBLIC_PREVIEW_SUPPORTED)

    def test_port_bounds_and_terminal_computer_fail_closed(self):
        provider = DeterministicFakePreviewPortProvider()
        for port in (0, 1023, 65536):
            with self.subTest(port=port):
                with self.assertRaises(ContractError):
                    provider.create_private(computer=computer(), internal_port=port, now=NOW + timedelta(seconds=1))
        with self.assertRaises(ContractError):
            provider.create_private(
                computer=computer(state=AgentComputerLeaseState.RELEASED),
                internal_port=3000,
                now=NOW + timedelta(seconds=1),
            )

    def test_share_requires_exact_trusted_grant_binding(self):
        provider = DeterministicFakePreviewPortProvider()
        lease = computer()
        endpoint = provider.create_private(computer=lease, internal_port=3000, now=NOW + timedelta(seconds=1))
        valid_now = NOW + timedelta(seconds=20)
        for bad_grant in (
            grant(endpoint, run_id="run_other"),
            grant(endpoint, computer_id="computer:other"),
            grant(endpoint, port=4000),
        ):
            with self.subTest(grant=bad_grant):
                with self.assertRaises(ContractError):
                    provider.share(endpoint=endpoint, computer=lease, grant=bad_grant, now=valid_now)

    def test_share_ttl_cannot_outlive_computer_and_grant_must_be_current(self):
        provider = DeterministicFakePreviewPortProvider()
        lease = computer(expires_at=NOW + timedelta(minutes=10))
        endpoint = provider.create_private(computer=lease, internal_port=3000, now=NOW + timedelta(seconds=1))
        with self.assertRaises(ContractError):
            provider.share(
                endpoint=endpoint,
                computer=lease,
                grant=grant(endpoint, expires_at=NOW + timedelta(minutes=11)),
                now=NOW + timedelta(seconds=20),
            )
        with self.assertRaises(ContractError):
            provider.share(
                endpoint=endpoint,
                computer=lease,
                grant=grant(endpoint, issued_at=NOW + timedelta(minutes=2), expires_at=NOW + timedelta(minutes=5)),
                now=NOW + timedelta(minutes=1),
            )

    def test_one_active_share_per_computer_port_and_terminal_share_no_reuse(self):
        provider = DeterministicFakePreviewPortProvider()
        lease = computer()
        endpoint = provider.create_private(computer=lease, internal_port=3000, now=NOW + timedelta(seconds=1))
        first = provider.share(endpoint=endpoint, computer=lease, grant=grant(endpoint), now=NOW + timedelta(seconds=20))
        with self.assertRaises(ContractError):
            provider.share(
                endpoint=endpoint,
                computer=lease,
                grant=grant(endpoint, grant_id="grant:2"),
                now=NOW + timedelta(seconds=30),
            )
        released = provider.release(first.share_id, now=NOW + timedelta(minutes=1))
        self.assertEqual(released.state.value, "released")
        with self.assertRaises(ContractError):
            provider.release(first.share_id, now=NOW + timedelta(minutes=2))
        second = provider.share(
            endpoint=endpoint,
            computer=lease,
            grant=grant(endpoint, grant_id="grant:3", issued_at=NOW + timedelta(minutes=2), expires_at=NOW + timedelta(minutes=6)),
            now=NOW + timedelta(minutes=3),
        )
        self.assertNotEqual(first.share_id, second.share_id)

    def test_safe_share_projection_has_no_cookie_or_credentials(self):
        provider = DeterministicFakePreviewPortProvider()
        lease = computer()
        endpoint = provider.create_private(computer=lease, internal_port=4173, now=NOW + timedelta(seconds=1))
        share = provider.share(endpoint=endpoint, computer=lease, grant=grant(endpoint), now=NOW + timedelta(seconds=20))
        rendered = share.safe_dict()
        self.assertTrue(rendered["temporary"])
        self.assertFalse(rendered["permanent_public_url"])
        self.assertFalse(rendered["authentication_cookie"])
        self.assertFalse(rendered["raw_credentials"])

    def test_unconfigured_real_provider_fails_closed(self):
        self.assertFalse(REAL_PREVIEW_PORT_PROVIDER_CONFIGURED)
        with self.assertRaises(ContractError):
            UnconfiguredPreviewPortProvider().create_private(computer=computer(), internal_port=3000, now=NOW)


if __name__ == "__main__":
    unittest.main()
