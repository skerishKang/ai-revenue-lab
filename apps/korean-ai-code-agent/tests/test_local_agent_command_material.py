from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import unittest

from kagent.contracts import ContractError
from kagent.local_agent import LocalCommandRequest
from kagent.local_agent_command_material import (
    ADMIN_AUTHORITY,
    COMMAND_MATERIAL_RESOLUTION_CONTRACT,
    ENVIRONMENT_PAYLOAD,
    EXACT_POLLED_COMMAND_CORRELATION,
    EXISTING_OUTBOUND_TRANSPORT_REUSED,
    LOCAL_COMMAND_REQUEST_RECONSTRUCTED,
    MAX_COMMAND_MATERIAL_BYTES,
    NUMERIC_COERCION,
    PRODUCTION_READY,
    PUBLIC_ENDPOINT,
    REAL_COMMAND_MATERIAL_TRANSPORT_CONFIGURED,
    REAL_REMOTE_EXECUTION,
    REQUEST_FINGERPRINT_RECOMPUTED,
    SHELL_AUTHORITY,
    UNKNOWN_WIRE_FIELDS_FAIL_CLOSED,
    OutboundCommandMaterialRequest,
    UnconfiguredOutboundCommandMaterialTransportPort,
    build_command_material_wire_projection,
    parse_command_material_wire_projection,
)
from kagent.local_agent_pairing import DeviceBinding, DeviceCommandEnvelope, DeviceLifecycle, DeviceSession
from kagent.local_agent_secure_channel import (
    COMMAND_MATERIAL_REQUIRES_POLLED_COMMAND,
    PinnedOutboundBrokerBinding,
    PinnedOutboundLocalAgentChannel,
)
from kagent.local_agent_secure_transport import (
    OutboundBrokerEndpoint,
    OutboundPollRequest,
    OutboundTransportConfig,
    OutboundTransportMode,
)
from kagent.windows_local_executor import command_request_fingerprint

NOW = datetime(2026, 9, 3, 14, 10, tzinfo=timezone.utc)


def binding() -> DeviceBinding:
    return DeviceBinding(
        device_id="device_1",
        binding_ref="device-binding:one",
        account_ref="account_1",
        workspace_ref="workspace_1",
        credential_ref="device-credential:generation-1",
        credential_generation=1,
        issued_at=NOW - timedelta(hours=1),
        credential_expires_at=NOW + timedelta(days=30),
        state=DeviceLifecycle.ONLINE,
    )


def session(session_id: str = "session_1") -> DeviceSession:
    return DeviceSession(
        session_id=session_id,
        device_id="device_1",
        binding_ref="device-binding:one",
        account_ref="account_1",
        workspace_ref="workspace_1",
        issued_at=NOW - timedelta(minutes=5),
        expires_at=NOW + timedelta(minutes=10),
    )


def local_request() -> LocalCommandRequest:
    return LocalCommandRequest(
        request_id="request_1",
        run_id="run_1",
        device_id="device_1",
        root_ref="root_repo",
        argv=("C:\\Program Files\\Git\\cmd\\git.exe", "status", "--short"),
        cwd_relative="src",
        requested_at=NOW - timedelta(minutes=1),
        timeout_seconds=120,
    )


def command() -> DeviceCommandEnvelope:
    return DeviceCommandEnvelope(
        command_id="command_1",
        run_id="run_1",
        tool_request_ref="tool_request_1",
        binding_ref="device-binding:one",
        sequence=1,
        issued_at=NOW - timedelta(seconds=10),
        expires_at=NOW + timedelta(minutes=5),
    )


def config(host: str = "broker.padiem.example") -> OutboundTransportConfig:
    return OutboundTransportConfig(
        endpoint=OutboundBrokerEndpoint(
            endpoint_ref="broker_primary",
            url=f"https://{host}/v1/local-agent",
            mode=OutboundTransportMode.HTTPS_LONG_POLL,
        )
    )


def material_request(*, current_session: DeviceSession | None = None, current_command: DeviceCommandEnvelope | None = None):
    request = local_request()
    return OutboundCommandMaterialRequest(
        request_ref="material_1",
        session=current_session or session(),
        command=current_command or command(),
        request_fingerprint=command_request_fingerprint(request),
        requested_at=NOW,
    )


class RecordingMaterialTransport:
    def __init__(self) -> None:
        self.poll_config = None
        self.resolve_config = None
        self.resolve_calls = 0
        self.payload_mutator = None

    def poll(self, *, config, binding, request):
        self.poll_config = config
        return (command(),)

    def resolve_material(self, *, config, binding, request):
        self.resolve_config = config
        self.resolve_calls += 1
        payload = build_command_material_wire_projection(
            command=request.command,
            request=local_request(),
            request_fingerprint=request.request_fingerprint,
        )
        if self.payload_mutator is not None:
            payload = self.payload_mutator(deepcopy(payload))
        return payload

    def acknowledge(self, **kwargs):
        return None


class CommandMaterialContractTests(unittest.TestCase):
    def test_round_trip_reconstructs_exact_canonical_request(self):
        current_request = local_request()
        fingerprint = command_request_fingerprint(current_request)
        outbound = material_request()
        wire = build_command_material_wire_projection(
            command=command(),
            request=current_request,
            request_fingerprint=fingerprint,
        )
        resolved = parse_command_material_wire_projection(wire, outbound_request=outbound)
        self.assertEqual(resolved.request, current_request)
        self.assertEqual(resolved.request_fingerprint, fingerprint)
        safe = resolved.safe_dict()
        self.assertFalse(safe["raw_argv"])
        self.assertFalse(safe["environment_payload"])
        self.assertFalse(safe["shell_authority"])
        self.assertFalse(safe["admin_elevation"])

    def test_schema_and_authority_expansion_fail_closed(self):
        outbound = material_request()
        base = build_command_material_wire_projection(
            command=command(), request=local_request(), request_fingerprint=outbound.request_fingerprint
        )
        mutations = []

        def unknown_top(payload):
            payload["endpoint"] = "https://evil.invalid"
            return payload
        mutations.append(unknown_top)

        def unknown_material(payload):
            payload["material"]["env"] = {"TOKEN": "x"}
            return payload
        mutations.append(unknown_material)

        def shell(payload):
            payload["material"]["shell_authority"] = True
            return payload
        mutations.append(shell)

        def admin(payload):
            payload["material"]["admin_elevation"] = True
            return payload
        mutations.append(admin)

        def environment(payload):
            payload["material"]["environment_payload"] = {"PATH": "x"}
            return payload
        mutations.append(environment)

        def provider(payload):
            payload["material"]["provider_authority"] = "provider_1"
            return payload
        mutations.append(provider)

        def approval(payload):
            payload["material"]["p01_approval_payload"] = {"approved": True}
            return payload
        mutations.append(approval)

        for mutate in mutations:
            with self.subTest(mutate=mutate.__name__):
                with self.assertRaises(ContractError):
                    parse_command_material_wire_projection(mutate(deepcopy(base)), outbound_request=outbound)

    def test_numeric_coercion_and_fingerprint_tamper_fail_closed(self):
        outbound = material_request()
        base = build_command_material_wire_projection(
            command=command(), request=local_request(), request_fingerprint=outbound.request_fingerprint
        )
        variants = []
        sequence_string = deepcopy(base)
        sequence_string["sequence"] = "1"
        variants.append(sequence_string)
        timeout_bool = deepcopy(base)
        timeout_bool["material"]["timeout_seconds"] = True
        variants.append(timeout_bool)
        timeout_string = deepcopy(base)
        timeout_string["material"]["timeout_seconds"] = "120"
        variants.append(timeout_string)
        argv_tamper = deepcopy(base)
        argv_tamper["material"]["argv"][-1] = "--porcelain"
        variants.append(argv_tamper)
        fingerprint_tamper = deepcopy(base)
        fingerprint_tamper["request_fingerprint"] = "0" * 64
        variants.append(fingerprint_tamper)

        for candidate in variants:
            with self.subTest(candidate=candidate):
                with self.assertRaises(ContractError):
                    parse_command_material_wire_projection(candidate, outbound_request=outbound)

    def test_oversized_wire_projection_is_rejected_before_use(self):
        outbound = material_request()
        payload = build_command_material_wire_projection(
            command=command(), request=local_request(), request_fingerprint=outbound.request_fingerprint
        )
        payload["material"]["argv"] = ["x" * (MAX_COMMAND_MATERIAL_BYTES + 1)]
        with self.assertRaises(ContractError):
            parse_command_material_wire_projection(payload, outbound_request=outbound)

    def test_unconfigured_material_transport_remains_fail_closed(self):
        with self.assertRaises(ContractError):
            UnconfiguredOutboundCommandMaterialTransportPort().resolve_material()


class PinnedChannelMaterialTests(unittest.TestCase):
    def make_channel(self, transport: RecordingMaterialTransport):
        current_binding = binding()
        pinned = config()
        authority = PinnedOutboundBrokerBinding.from_binding(binding=current_binding, config=pinned)
        return current_binding, pinned, PinnedOutboundLocalAgentChannel(authority=authority, transport=transport)

    def poll(self, channel, current_binding, current_session=None):
        return channel.poll(
            binding=current_binding,
            request=OutboundPollRequest(
                request_ref="poll_1",
                session=current_session or session(),
                after_sequence=0,
                requested_at=NOW,
            ),
        )

    def test_material_resolution_reuses_exact_pinned_transport_and_polled_command(self):
        transport = RecordingMaterialTransport()
        current_binding, pinned, channel = self.make_channel(transport)
        polled = self.poll(channel, current_binding)
        outbound = material_request(current_command=polled[0])
        resolved = channel.resolve_material(binding=current_binding, request=outbound)
        self.assertEqual(resolved.request, local_request())
        self.assertIs(transport.poll_config, pinned)
        self.assertIs(transport.resolve_config, pinned)
        self.assertEqual(transport.resolve_calls, 1)
        safe = channel.safe_dict()
        self.assertTrue(safe["command_material_resolution"])
        self.assertFalse(safe["caller_endpoint_override"])
        self.assertFalse(safe["public_inbound_port"])

    def test_material_for_command_never_polled_by_channel_is_rejected_before_transport(self):
        transport = RecordingMaterialTransport()
        current_binding, _, channel = self.make_channel(transport)
        with self.assertRaises(ContractError):
            channel.resolve_material(binding=current_binding, request=material_request())
        self.assertEqual(transport.resolve_calls, 0)

    def test_polled_command_cannot_be_rebound_to_another_session(self):
        transport = RecordingMaterialTransport()
        current_binding, _, channel = self.make_channel(transport)
        first_session = session("session_1")
        polled = self.poll(channel, current_binding, first_session)
        second_session = session("session_2")
        outbound = material_request(current_session=second_session, current_command=polled[0])
        with self.assertRaises(ContractError):
            channel.resolve_material(binding=current_binding, request=outbound)
        self.assertEqual(transport.resolve_calls, 0)

    def test_fabricated_metadata_with_same_command_id_is_rejected(self):
        transport = RecordingMaterialTransport()
        current_binding, _, channel = self.make_channel(transport)
        polled = self.poll(channel, current_binding)
        forged = replace(polled[0], sequence=2)
        outbound = material_request(current_command=forged)
        with self.assertRaises(ContractError):
            channel.resolve_material(binding=current_binding, request=outbound)
        self.assertEqual(transport.resolve_calls, 0)

    def test_transport_payload_tamper_is_rejected_after_resolution_call(self):
        transport = RecordingMaterialTransport()
        current_binding, _, channel = self.make_channel(transport)
        polled = self.poll(channel, current_binding)
        transport.payload_mutator = lambda payload: (
            payload["material"].__setitem__("root_ref", "root_other") or payload
        )
        with self.assertRaises(ContractError):
            channel.resolve_material(
                binding=current_binding,
                request=material_request(current_command=polled[0]),
            )
        self.assertEqual(transport.resolve_calls, 1)

    def test_poll_rejects_command_id_rebinding(self):
        class RebindingTransport(RecordingMaterialTransport):
            def __init__(self):
                super().__init__()
                self.calls = 0

            def poll(self, *, config, binding, request):
                self.calls += 1
                base = command()
                if self.calls == 1:
                    return (base,)
                return (replace(base, run_id="run_other"),)

        transport = RebindingTransport()
        current_binding, _, channel = self.make_channel(transport)
        self.poll(channel, current_binding)
        with self.assertRaises(ContractError):
            self.poll(channel, current_binding)


class RepositoryTruthTests(unittest.TestCase):
    def test_m2d_truth_constants(self):
        self.assertTrue(EXISTING_OUTBOUND_TRANSPORT_REUSED)
        self.assertTrue(COMMAND_MATERIAL_RESOLUTION_CONTRACT)
        self.assertTrue(LOCAL_COMMAND_REQUEST_RECONSTRUCTED)
        self.assertTrue(REQUEST_FINGERPRINT_RECOMPUTED)
        self.assertTrue(EXACT_POLLED_COMMAND_CORRELATION)
        self.assertTrue(UNKNOWN_WIRE_FIELDS_FAIL_CLOSED)
        self.assertTrue(COMMAND_MATERIAL_REQUIRES_POLLED_COMMAND)
        self.assertFalse(NUMERIC_COERCION)
        self.assertFalse(ENVIRONMENT_PAYLOAD)
        self.assertFalse(SHELL_AUTHORITY)
        self.assertFalse(ADMIN_AUTHORITY)
        self.assertFalse(PUBLIC_ENDPOINT)
        self.assertFalse(REAL_COMMAND_MATERIAL_TRANSPORT_CONFIGURED)
        self.assertFalse(REAL_REMOTE_EXECUTION)
        self.assertFalse(PRODUCTION_READY)


if __name__ == "__main__":
    unittest.main()
