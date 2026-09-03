from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from kagent.contracts import ContractError
from kagent.local_agent_pairing import (
    FAKE_COUNTS_AS_LIVE,
    OUTBOUND_ONLY_TRANSPORT,
    PAIRING_REPLAY_ALLOWED,
    PAIRING_SINGLE_USE,
    PUBLIC_INBOUND_PORT_REQUIRED,
    RAW_DEVICE_SECRET_IN_LOG,
    REAL_PAIRING_BROKER_CONFIGURED,
    UPNP_PORT_FORWARD_SUPPORTED,
    DeterministicFakeLocalAgentPairingPort,
    DeviceCommandEnvelope,
    DeviceLifecycle,
    PairingChallenge,
    UnconfiguredLocalAgentPairingPort,
    deterministic_fake_pairing_proof,
)


NOW = datetime(2026, 9, 3, 6, 10, tzinfo=timezone.utc)


def paired(fake: DeterministicFakeLocalAgentPairingPort, *, now: datetime = NOW):
    challenge = fake.issue_pairing(
        account_ref="account_1",
        workspace_ref="workspace_1",
        now=now,
    )
    binding = fake.pair_device(
        challenge_id=challenge.challenge_id,
        proof_ref=deterministic_fake_pairing_proof(challenge.challenge_id),
        device_id="device_1",
        now=now + timedelta(seconds=1),
    )
    return challenge, binding


def command(binding_ref: str, **kwargs):
    values = dict(
        command_id="command_1",
        run_id="run_1",
        tool_request_ref="tool_request_1",
        binding_ref=binding_ref,
        sequence=1,
        issued_at=NOW + timedelta(seconds=3),
        expires_at=NOW + timedelta(minutes=5),
    )
    values.update(kwargs)
    return DeviceCommandEnvelope(**values)


class LocalAgentPairingTests(unittest.TestCase):
    def test_pairing_challenge_is_short_lived_single_use_and_secret_free(self):
        challenge = PairingChallenge(
            challenge_id="pair_1",
            account_ref="account_1",
            workspace_ref="workspace_1",
            issued_at=NOW,
            expires_at=NOW + timedelta(minutes=5),
        )
        rendered = challenge.safe_dict()
        self.assertTrue(rendered["single_use"])
        self.assertFalse(rendered["raw_pairing_secret"])
        with self.assertRaises(ContractError):
            PairingChallenge(
                challenge_id="pair_2",
                account_ref="account_1",
                workspace_ref="workspace_1",
                issued_at=NOW,
                expires_at=NOW + timedelta(minutes=11),
            )

    def test_fake_pairing_binds_exact_account_workspace_and_hides_credential_ref(self):
        fake = DeterministicFakeLocalAgentPairingPort()
        _, binding = paired(fake)
        self.assertEqual(binding.state, DeviceLifecycle.PAIRED_OFFLINE)
        rendered = binding.safe_dict()
        self.assertEqual(rendered["account_ref"], "account_1")
        self.assertEqual(rendered["workspace_ref"], "workspace_1")
        self.assertFalse(rendered["credential_ref_exposed"])
        self.assertFalse(rendered["raw_device_secret"])

    def test_pairing_challenge_replay_and_bad_proof_fail_closed(self):
        fake = DeterministicFakeLocalAgentPairingPort()
        challenge = fake.issue_pairing(account_ref="account_1", workspace_ref="workspace_1", now=NOW)
        with self.assertRaises(ContractError):
            fake.pair_device(
                challenge_id=challenge.challenge_id,
                proof_ref="proof:wrong",
                device_id="device_1",
                now=NOW + timedelta(seconds=1),
            )
        proof = deterministic_fake_pairing_proof(challenge.challenge_id)
        fake.pair_device(
            challenge_id=challenge.challenge_id,
            proof_ref=proof,
            device_id="device_1",
            now=NOW + timedelta(seconds=1),
        )
        with self.assertRaises(ContractError):
            fake.pair_device(
                challenge_id=challenge.challenge_id,
                proof_ref=proof,
                device_id="device_2",
                now=NOW + timedelta(seconds=2),
            )

    def test_expired_pairing_challenge_fails_closed(self):
        fake = DeterministicFakeLocalAgentPairingPort()
        challenge = fake.issue_pairing(
            account_ref="account_1",
            workspace_ref="workspace_1",
            now=NOW,
            ttl_seconds=30,
        )
        with self.assertRaises(ContractError):
            fake.pair_device(
                challenge_id=challenge.challenge_id,
                proof_ref=deterministic_fake_pairing_proof(challenge.challenge_id),
                device_id="device_1",
                now=NOW + timedelta(seconds=30),
            )

    def test_connect_requires_exact_account_and_workspace_binding(self):
        fake = DeterministicFakeLocalAgentPairingPort()
        _, binding = paired(fake)
        with self.assertRaises(ContractError):
            fake.connect(
                binding.binding_ref,
                account_ref="account_other",
                workspace_ref="workspace_1",
                now=NOW + timedelta(seconds=2),
            )
        with self.assertRaises(ContractError):
            fake.connect(
                binding.binding_ref,
                account_ref="account_1",
                workspace_ref="workspace_other",
                now=NOW + timedelta(seconds=2),
            )
        session = fake.connect(
            binding.binding_ref,
            account_ref="account_1",
            workspace_ref="workspace_1",
            now=NOW + timedelta(seconds=2),
        )
        rendered = session.safe_dict()
        self.assertTrue(rendered["outbound_only"])
        self.assertFalse(rendered["transport_secret"])

    def test_rotation_invalidates_existing_session_and_increments_generation(self):
        fake = DeterministicFakeLocalAgentPairingPort()
        _, binding = paired(fake)
        session = fake.connect(
            binding.binding_ref,
            account_ref="account_1",
            workspace_ref="workspace_1",
            now=NOW + timedelta(seconds=2),
        )
        rotated = fake.rotate_credential(binding.binding_ref, now=NOW + timedelta(seconds=3))
        self.assertEqual(rotated.credential_generation, 2)
        self.assertEqual(rotated.state, DeviceLifecycle.PAIRED_OFFLINE)
        with self.assertRaises(ContractError):
            fake.accept_command(
                session.session_id,
                command(binding.binding_ref),
                now=NOW + timedelta(seconds=4),
            )

    def test_revoked_device_cannot_reconnect(self):
        fake = DeterministicFakeLocalAgentPairingPort()
        _, binding = paired(fake)
        revoked = fake.revoke(binding.binding_ref, now=NOW + timedelta(seconds=2))
        self.assertEqual(revoked.state, DeviceLifecycle.REVOKED)
        with self.assertRaises(ContractError):
            fake.connect(
                binding.binding_ref,
                account_ref="account_1",
                workspace_ref="workspace_1",
                now=NOW + timedelta(seconds=3),
            )

    def test_command_replay_and_non_monotonic_sequence_are_rejected_across_reconnects(self):
        fake = DeterministicFakeLocalAgentPairingPort()
        _, binding = paired(fake)
        first_session = fake.connect(
            binding.binding_ref,
            account_ref="account_1",
            workspace_ref="workspace_1",
            now=NOW + timedelta(seconds=2),
        )
        first = command(binding.binding_ref)
        fake.accept_command(first_session.session_id, first, now=NOW + timedelta(seconds=4))
        with self.assertRaises(ContractError):
            fake.accept_command(first_session.session_id, first, now=NOW + timedelta(seconds=5))

        second_session = fake.connect(
            binding.binding_ref,
            account_ref="account_1",
            workspace_ref="workspace_1",
            now=NOW + timedelta(seconds=6),
        )
        with self.assertRaises(ContractError):
            fake.accept_command(
                second_session.session_id,
                command(binding.binding_ref, command_id="command_2", sequence=1),
                now=NOW + timedelta(seconds=7),
            )
        fake.accept_command(
            second_session.session_id,
            command(binding.binding_ref, command_id="command_3", sequence=2),
            now=NOW + timedelta(seconds=7),
        )

    def test_expired_command_is_rejected(self):
        fake = DeterministicFakeLocalAgentPairingPort()
        _, binding = paired(fake)
        session = fake.connect(
            binding.binding_ref,
            account_ref="account_1",
            workspace_ref="workspace_1",
            now=NOW + timedelta(seconds=2),
        )
        expired = command(
            binding.binding_ref,
            issued_at=NOW + timedelta(seconds=2),
            expires_at=NOW + timedelta(seconds=3),
        )
        with self.assertRaises(ContractError):
            fake.accept_command(session.session_id, expired, now=NOW + timedelta(seconds=3))

    def test_unconfigured_pairing_authority_fails_closed_and_live_claims_remain_false(self):
        port = UnconfiguredLocalAgentPairingPort()
        with self.assertRaises(ContractError):
            port.issue_pairing(account_ref="account_1", workspace_ref="workspace_1", now=NOW)
        self.assertTrue(OUTBOUND_ONLY_TRANSPORT)
        self.assertTrue(PAIRING_SINGLE_USE)
        self.assertFalse(PAIRING_REPLAY_ALLOWED)
        self.assertFalse(PUBLIC_INBOUND_PORT_REQUIRED)
        self.assertFalse(UPNP_PORT_FORWARD_SUPPORTED)
        self.assertFalse(RAW_DEVICE_SECRET_IN_LOG)
        self.assertFalse(REAL_PAIRING_BROKER_CONFIGURED)
        self.assertFalse(FAKE_COUNTS_AS_LIVE)


if __name__ == "__main__":
    unittest.main()
