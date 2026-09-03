from __future__ import annotations

from datetime import datetime, timedelta, timezone
import inspect
import unittest

from kagent.contracts import ContractError
from kagent.local_agent_control_plane_runtime import (
    ADMISSION_BOUND_ACKNOWLEDGE,
    CLIENT_LAST_SEEN_AUTHORITY,
    GENERIC_ACKNOWLEDGE_DISABLED,
    HEARTBEAT_BOUNDED,
    LIVE_BROKER_CONFIGURED,
    PRODUCTION_MUTATION,
    PRODUCTION_READY,
    PUBLIC_INBOUND_PORT,
    SERVER_LAST_SEEN_REQUIRED,
    UPNP,
    ControlPlanePhysicalRuntimeChannel,
    ControlPlanePhysicalRuntimeTransport,
    ControlPlaneRuntimeHttpsOperation,
    RuntimeStdlibPinnedHttpsJsonRequestPort,
)
from kagent.local_agent_pairing import DeviceBinding, DeviceLifecycle, DeviceSession
from kagent.local_agent_secure_channel import PinnedOutboundBrokerBinding
from kagent.local_agent_secure_transport import (
    OutboundBrokerEndpoint,
    OutboundTransportConfig,
    OutboundTransportMode,
)

BASE = datetime(2026, 9, 3, 16, 0, tzinfo=timezone.utc)
CREDENTIAL = b"deterministic-runtime-heartbeat-credential"


def binding() -> DeviceBinding:
    return DeviceBinding(
        device_id="device_runtime_1",
        binding_ref="binding_runtime_1",
        account_ref="account_runtime_1",
        workspace_ref="workspace_runtime_1",
        credential_ref="credential-ref:runtime-1",
        credential_generation=1,
        issued_at=BASE - timedelta(minutes=1),
        credential_expires_at=BASE + timedelta(days=30),
        state=DeviceLifecycle.ONLINE,
    )


def session() -> DeviceSession:
    return DeviceSession(
        session_id="session_runtime_1",
        device_id="device_runtime_1",
        binding_ref="binding_runtime_1",
        account_ref="account_runtime_1",
        workspace_ref="workspace_runtime_1",
        issued_at=BASE - timedelta(seconds=30),
        expires_at=BASE + timedelta(minutes=10),
    )


def config(*, heartbeat_seconds: int = 30) -> OutboundTransportConfig:
    return OutboundTransportConfig(
        endpoint=OutboundBrokerEndpoint(
            endpoint_ref="broker_runtime",
            url="https://broker.padiem.example/v1/local-agent",
            mode=OutboundTransportMode.HTTPS_LONG_POLL,
        ),
        heartbeat_seconds=heartbeat_seconds,
        poll_timeout_seconds=30,
    )


class _CredentialStore:
    def __init__(self) -> None:
        self.loads: list[tuple[str, datetime]] = []

    def load(self, *, binding: DeviceBinding, now: datetime) -> bytes:
        self.loads.append((binding.binding_ref, now))
        return CREDENTIAL


class _HeartbeatRequestPort:
    def __init__(self, current_session: DeviceSession) -> None:
        self.current_session = current_session
        self.calls: list[tuple[object, frozenset[str], OutboundTransportConfig]] = []
        self.last_seen_offset_seconds = 0
        self.raw_device_credential = False

    def post(self, *, config, operation, payload, timeout_seconds):
        del timeout_seconds
        self.calls.append((operation, frozenset(payload), config))
        if operation is not ControlPlaneRuntimeHttpsOperation.HEARTBEAT:
            raise AssertionError(f"unexpected operation {operation}")
        observed = datetime.fromisoformat(payload["now"].replace("Z", "+00:00")) + timedelta(
            seconds=self.last_seen_offset_seconds
        )
        return {
            "ok": True,
            "heartbeat": {
                "session_id": self.current_session.session_id,
                "binding_ref": self.current_session.binding_ref,
                "device_id": self.current_session.device_id,
                "account_ref": self.current_session.account_ref,
                "workspace_ref": self.current_session.workspace_ref,
                "credential_generation": 1,
                "last_seen_at": observed.isoformat().replace("+00:00", "Z"),
                "session_expires_at": self.current_session.expires_at.isoformat().replace("+00:00", "Z"),
                "raw_device_credential": self.raw_device_credential,
            },
        }


class PhysicalRuntimeHeartbeatTests(unittest.TestCase):
    def make_runtime(self):
        current_binding = binding()
        current_session = session()
        request_port = _HeartbeatRequestPort(current_session)
        transport = ControlPlanePhysicalRuntimeTransport(
            credential_store=_CredentialStore(),
            request_port=request_port,
        )
        authority = PinnedOutboundBrokerBinding.from_binding(binding=current_binding, config=config())
        channel = ControlPlanePhysicalRuntimeChannel(authority=authority, transport=transport)
        return current_binding, current_session, request_port, transport, channel

    def test_heartbeat_requires_exact_server_last_seen_receipt(self) -> None:
        current_binding, current_session, request_port, transport, channel = self.make_runtime()
        receipt = channel.heartbeat(
            binding=current_binding,
            session=current_session,
            now=BASE,
        )
        self.assertEqual(receipt.last_seen_at, BASE)
        self.assertEqual(receipt.session_expires_at, current_session.expires_at)
        self.assertEqual(receipt.binding_ref, current_binding.binding_ref)
        self.assertEqual(request_port.calls[0][0], ControlPlaneRuntimeHttpsOperation.HEARTBEAT)
        self.assertEqual(
            request_port.calls[0][1],
            frozenset({"session_id", "binding_ref", "credential_b64", "now"}),
        )
        safe = receipt.safe_dict()
        self.assertTrue(safe["server_last_seen_authority"])
        self.assertFalse(safe["client_last_seen_authority"])
        self.assertFalse(safe["raw_device_credential"])
        self.assertTrue(transport.safe_dict()["heartbeat_bounded"])
        self.assertEqual(transport.safe_dict()["heartbeat_seconds_min"], 5)
        self.assertEqual(transport.safe_dict()["heartbeat_seconds_max"], 300)

    def test_heartbeat_rejects_stale_last_seen_or_raw_credential_claim(self) -> None:
        current_binding, current_session, request_port, _, channel = self.make_runtime()
        request_port.last_seen_offset_seconds = -1
        with self.assertRaisesRegex(ContractError, "last_seen_at"):
            channel.heartbeat(binding=current_binding, session=current_session, now=BASE)

        request_port.last_seen_offset_seconds = 0
        request_port.raw_device_credential = True
        with self.assertRaisesRegex(ContractError, "raw device credential"):
            channel.heartbeat(binding=current_binding, session=current_session, now=BASE)

    def test_heartbeat_cadence_is_bounded_by_existing_transport_config(self) -> None:
        self.assertEqual(config(heartbeat_seconds=5).heartbeat_seconds, 5)
        self.assertEqual(config(heartbeat_seconds=300).heartbeat_seconds, 300)
        for invalid in (4, 301):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ContractError):
                    config(heartbeat_seconds=invalid)

    def test_default_runtime_source_pins_heartbeat_under_existing_https_authority(self) -> None:
        host, port, path = RuntimeStdlibPinnedHttpsJsonRequestPort()._path(
            config(),
            ControlPlaneRuntimeHttpsOperation.HEARTBEAT,
        )
        self.assertEqual(host, "broker.padiem.example")
        self.assertEqual(port, 443)
        self.assertEqual(path, "/v1/local-agent/heartbeat")


class AdmissionAckFailClosedTests(unittest.TestCase):
    def test_generic_ack_path_is_explicitly_disabled(self) -> None:
        current_binding, current_session, _, _, channel = PhysicalRuntimeHeartbeatTests().make_runtime()
        params = inspect.signature(ControlPlanePhysicalRuntimeChannel.acknowledge).parameters
        self.assertNotIn("admission_ref", params)
        with self.assertRaisesRegex(ContractError, "requires admission_ref and evidence_ref"):
            channel.acknowledge(
                binding=current_binding,
                session=current_session,
                command_id="command_runtime_1",
                evidence_ref="evidence_runtime_1",
                now=BASE,
            )
        safe = channel.safe_dict()
        self.assertTrue(safe["generic_acknowledge_disabled"])
        self.assertTrue(safe["admission_bound_acknowledge"])


class RuntimeTruthTests(unittest.TestCase):
    def test_issue_1719_runtime_truth_flags(self) -> None:
        self.assertTrue(HEARTBEAT_BOUNDED)
        self.assertTrue(SERVER_LAST_SEEN_REQUIRED)
        self.assertFalse(CLIENT_LAST_SEEN_AUTHORITY)
        self.assertTrue(GENERIC_ACKNOWLEDGE_DISABLED)
        self.assertTrue(ADMISSION_BOUND_ACKNOWLEDGE)
        self.assertFalse(PUBLIC_INBOUND_PORT)
        self.assertFalse(UPNP)
        self.assertFalse(LIVE_BROKER_CONFIGURED)
        self.assertFalse(PRODUCTION_MUTATION)
        self.assertFalse(PRODUCTION_READY)


if __name__ == "__main__":
    unittest.main()
