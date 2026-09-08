from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from kagent.contracts import ContractError
from kagent.local_agent import LocalAgentDeviceProfile, LocalAgentPlatform, LocalCommandRequest, LocalRoot
from kagent.local_agent_pairing import DeviceBinding, DeviceLifecycle, DeviceSession
from kagent.local_agent_permissions import default_device_permission_profile
from kagent.local_agent_runtime_assembly import ONLINE_BINDING_REQUIRED, BoundLocalAgentRuntimeAssembly
from kagent.local_agent_secure_channel import PinnedOutboundBrokerBinding
from kagent.local_agent_secure_transport import OutboundBrokerEndpoint, OutboundTransportConfig, OutboundTransportMode

NOW = datetime(2026, 9, 3, 8, 50, tzinfo=timezone.utc)


class NeverRuntime:
    def __init__(self) -> None:
        self.called = False

    def execute_with_receipt(self, request, *, now):
        self.called = True
        raise AssertionError("runtime must not be called for PAIRED_OFFLINE binding")

    def cancel(self, request_id):
        self.called = True
        raise AssertionError("runtime must not be called for PAIRED_OFFLINE binding")


class OnlineLifecycleGateTests(unittest.TestCase):
    def test_paired_offline_binding_cannot_execute_even_with_structurally_current_session(self):
        device = LocalAgentDeviceProfile(
            device_id="device_1",
            workspace_ref="workspace_1",
            platform=LocalAgentPlatform.WINDOWS,
            roots=(LocalRoot(root_ref="root_code", windows_path=r"E:\padiem-claw"),),
        )
        binding = DeviceBinding(
            device_id="device_1",
            binding_ref="device-binding:one",
            account_ref="account_1",
            workspace_ref="workspace_1",
            credential_ref="device-credential:one",
            credential_generation=1,
            issued_at=NOW - timedelta(hours=1),
            credential_expires_at=NOW + timedelta(days=30),
            state=DeviceLifecycle.PAIRED_OFFLINE,
        )
        session = DeviceSession(
            session_id="session_1",
            device_id="device_1",
            binding_ref="device-binding:one",
            account_ref="account_1",
            workspace_ref="workspace_1",
            issued_at=NOW - timedelta(minutes=1),
            expires_at=NOW + timedelta(minutes=10),
        )
        broker = PinnedOutboundBrokerBinding.from_binding(
            binding=binding,
            config=OutboundTransportConfig(
                endpoint=OutboundBrokerEndpoint(
                    endpoint_ref="broker_primary",
                    url="https://broker.padiem.example/v1/local-agent",
                    mode=OutboundTransportMode.HTTPS_LONG_POLL,
                )
            ),
        )
        runtime = NeverRuntime()
        assembly = BoundLocalAgentRuntimeAssembly(
            device=device,
            binding=binding,
            permissions=default_device_permission_profile(device=device),
            broker_authority=broker,
            runtime=runtime,
        )
        request = LocalCommandRequest(
            request_id="request_1",
            run_id="run_1",
            device_id="device_1",
            root_ref="root_code",
            argv=(r"C:\Python313\python.exe", "-V"),
            cwd_relative=".",
            requested_at=NOW - timedelta(seconds=1),
            timeout_seconds=30,
        )
        with self.assertRaises(ContractError):
            assembly.execute(session=session, request=request, now=NOW)
        self.assertFalse(runtime.called)
        self.assertFalse(assembly.safe_dict(now=NOW)["current"])
        self.assertTrue(ONLINE_BINDING_REQUIRED)


if __name__ == "__main__":
    unittest.main()
