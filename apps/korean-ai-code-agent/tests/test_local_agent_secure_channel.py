from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import inspect
import unittest

from kagent.contracts import ContractError
from kagent.local_agent_pairing import DeviceBinding, DeviceCommandEnvelope, DeviceLifecycle, DeviceSession
from kagent.local_agent_secure_channel import (
    CALLER_FACING_CONFIG_ARGUMENT,
    PINNED_BROKER_AUTHORITY,
    PinnedOutboundBrokerBinding,
    PinnedOutboundLocalAgentChannel,
)
from kagent.local_agent_secure_transport import (
    OutboundBrokerEndpoint,
    OutboundPollRequest,
    OutboundTransportConfig,
    OutboundTransportMode,
)

NOW = datetime(2026, 9, 3, 8, 30, tzinfo=timezone.utc)


def device_binding(*, generation: int = 1, state: DeviceLifecycle = DeviceLifecycle.PAIRED_OFFLINE) -> DeviceBinding:
    return DeviceBinding(
        device_id="device_1",
        binding_ref="device-binding:one",
        account_ref="account_1",
        workspace_ref="workspace_1",
        credential_ref=f"device-credential:generation-{generation}",
        credential_generation=generation,
        issued_at=NOW - timedelta(hours=1),
        credential_expires_at=NOW + timedelta(days=30),
        state=state,
    )


def device_session(*, account_ref: str = "account_1") -> DeviceSession:
    return DeviceSession(
        session_id="session_1",
        device_id="device_1",
        binding_ref="device-binding:one",
        account_ref=account_ref,
        workspace_ref="workspace_1",
        issued_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=10),
    )


def config(host: str = "broker.padiem.example") -> OutboundTransportConfig:
    endpoint = OutboundBrokerEndpoint(
        endpoint_ref="broker_primary",
        url=f"https://{host}/v1/local-agent",
        mode=OutboundTransportMode.HTTPS_LONG_POLL,
    )
    return OutboundTransportConfig(endpoint=endpoint)


class RecordingPhysicalTransport:
    def __init__(self) -> None:
        self.poll_configs: list[OutboundTransportConfig] = []
        self.ack_configs: list[OutboundTransportConfig] = []

    def poll(self, *, config, binding, request):
        self.poll_configs.append(config)
        return (
            DeviceCommandEnvelope(
                command_id="command_1",
                run_id="run_1",
                tool_request_ref="tool_request_1",
                binding_ref=binding.binding_ref,
                sequence=request.after_sequence + 1,
                issued_at=NOW,
                expires_at=NOW + timedelta(minutes=1),
            ),
        )

    def acknowledge(self, *, config, binding, session, command_id, evidence_ref, now):
        self.ack_configs.append(config)


class PinnedAuthorityTests(unittest.TestCase):
    def test_caller_facing_channel_has_no_config_or_endpoint_parameter(self):
        poll_params = inspect.signature(PinnedOutboundLocalAgentChannel.poll).parameters
        ack_params = inspect.signature(PinnedOutboundLocalAgentChannel.acknowledge).parameters
        self.assertNotIn("config", poll_params)
        self.assertNotIn("endpoint", poll_params)
        self.assertNotIn("url", poll_params)
        self.assertNotIn("config", ack_params)
        self.assertNotIn("endpoint", ack_params)
        self.assertFalse(CALLER_FACING_CONFIG_ARGUMENT)
        self.assertTrue(PINNED_BROKER_AUTHORITY)

    def test_physical_transport_receives_only_the_pinned_config(self):
        current_binding = device_binding()
        pinned = config()
        authority = PinnedOutboundBrokerBinding.from_binding(binding=current_binding, config=pinned)
        physical = RecordingPhysicalTransport()
        channel = PinnedOutboundLocalAgentChannel(authority=authority, transport=physical)
        request = OutboundPollRequest(
            request_ref="poll_1",
            session=device_session(),
            after_sequence=0,
            requested_at=NOW,
        )
        commands = channel.poll(binding=current_binding, request=request)
        self.assertEqual(commands[0].command_id, "command_1")
        self.assertEqual(physical.poll_configs, [pinned])
        channel.acknowledge(
            binding=current_binding,
            session=device_session(),
            command_id="command_1",
            evidence_ref="evidence_1",
            now=NOW,
        )
        self.assertEqual(physical.ack_configs, [pinned])
        safe = channel.safe_dict()
        self.assertFalse(safe["caller_endpoint_override"])
        self.assertFalse(safe["public_inbound_port"])
        self.assertFalse(safe["raw_device_credential"])

    def test_rotation_requires_new_pinned_authority(self):
        current_binding = device_binding(generation=1)
        authority = PinnedOutboundBrokerBinding.from_binding(binding=current_binding, config=config())
        channel = PinnedOutboundLocalAgentChannel(authority=authority, transport=RecordingPhysicalTransport())
        rotated = device_binding(generation=2)
        request = OutboundPollRequest(
            request_ref="poll_1",
            session=device_session(),
            after_sequence=0,
            requested_at=NOW,
        )
        with self.assertRaises(ContractError):
            channel.poll(binding=rotated, request=request)

    def test_account_workspace_device_and_credential_context_are_exact(self):
        current_binding = device_binding()
        authority = PinnedOutboundBrokerBinding.from_binding(binding=current_binding, config=config())
        bad_bindings = (
            replace(current_binding, account_ref="account_other"),
            replace(current_binding, workspace_ref="workspace_other"),
            replace(current_binding, device_id="device_other"),
            replace(current_binding, credential_ref="device-credential:other"),
        )
        for candidate in bad_bindings:
            with self.subTest(candidate=candidate):
                with self.assertRaises(ContractError):
                    authority.require_current_binding(candidate, now=NOW)

    def test_revoked_or_expired_binding_and_wrong_session_fail_closed(self):
        current_binding = device_binding()
        authority = PinnedOutboundBrokerBinding.from_binding(binding=current_binding, config=config())
        with self.assertRaises(ContractError):
            authority.require_current_binding(
                replace(current_binding, state=DeviceLifecycle.REVOKED),
                now=NOW,
            )
        with self.assertRaises(ContractError):
            authority.require_current_binding(
                replace(current_binding, credential_expires_at=NOW),
                now=NOW,
            )
        with self.assertRaises(ContractError):
            authority.require_session(device_session(account_ref="account_other"), now=NOW)

    def test_config_fingerprint_changes_when_pinned_endpoint_changes(self):
        current_binding = device_binding()
        first = PinnedOutboundBrokerBinding.from_binding(binding=current_binding, config=config("broker-a.padiem.example"))
        second = PinnedOutboundBrokerBinding.from_binding(binding=current_binding, config=config("broker-b.padiem.example"))
        self.assertNotEqual(first.config_fingerprint, second.config_fingerprint)


if __name__ == "__main__":
    unittest.main()
