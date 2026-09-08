from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import inspect
import json
import ssl
import unittest
from unittest.mock import patch

from padiem_control_plane.local_agent_broker import InMemoryLocalAgentBrokerAuthority
from padiem_control_plane.local_agent_broker_rpc import LocalAgentBrokerRpcFacade

import kagent.local_agent_control_plane_https as https_module
from kagent.contracts import ContractError
from kagent.local_agent import LocalCommandRequest
from kagent.local_agent_command_material import build_command_material_wire_projection
from kagent.local_agent_control_plane_channel import (
    ACK_ADMISSION_REF_REQUIRED as CHANNEL_ACK_ADMISSION_REF_REQUIRED,
    ACK_EVIDENCE_REF_REQUIRED as CHANNEL_ACK_EVIDENCE_REF_REQUIRED,
    MATERIAL_FINGERPRINT_CALLER_SUPPLIED,
    PINNED_CONTROL_PLANE_HTTPS_CHANNEL,
    PRODUCTION_BROKER_CONFIGURED as CHANNEL_PRODUCTION_BROKER_CONFIGURED,
    PRODUCTION_READY as CHANNEL_PRODUCTION_READY,
    PUBLIC_INBOUND_PORT as CHANNEL_PUBLIC_INBOUND_PORT,
    ControlPlanePinnedHttpsChannel,
)
from kagent.local_agent_control_plane_https import (
    ACK_ADMISSION_REF_REQUIRED,
    ACK_EVIDENCE_REF_REQUIRED,
    CALLER_ENDPOINT_OVERRIDE,
    POLL_FINGERPRINT_FROM_CONTROL_PLANE,
    PRODUCTION_BROKER_CONFIGURED,
    PRODUCTION_READY,
    PUBLIC_INBOUND_PORT,
    RAW_DEVICE_CREDENTIAL_IN_SAFE_STATE,
    REAL_REMOTE_EXECUTION,
    REDIRECT_AUTO_FOLLOW,
    STDLIB_HTTPS_TRANSPORT_SOURCE,
    TLS_DEFAULT_CONTEXT,
    ControlPlaneHttpsLongPollTransport,
    ControlPlaneHttpsOperation,
    StdlibPinnedHttpsJsonRequestPort,
)
from kagent.local_agent_pairing import DeviceBinding, DeviceCommandEnvelope, DeviceLifecycle
from kagent.local_agent_secure_channel import PinnedOutboundBrokerBinding
from kagent.local_agent_secure_transport import (
    OutboundBrokerEndpoint,
    OutboundPollRequest,
    OutboundTransportConfig,
    OutboundTransportMode,
)
from kagent.windows_local_executor import command_request_fingerprint

BASE = datetime(2026, 9, 3, 15, 0, tzinfo=timezone.utc)
CREDENTIAL = b"disposable-local-agent-device-credential"


class _CredentialStore:
    def __init__(self, credential: bytes = CREDENTIAL) -> None:
        self.credential = credential
        self.calls: list[tuple[str, datetime]] = []

    def load(self, *, binding: DeviceBinding, now: datetime) -> bytes:
        self.calls.append((binding.binding_ref, now))
        return self.credential


class _DeterministicBrokerRequestPort:
    def __init__(self, *, rpc: LocalAgentBrokerRpcFacade, material_wire: dict) -> None:
        self.rpc = rpc
        self.material_wire = material_wire
        self.calls: list[tuple[ControlPlaneHttpsOperation, frozenset[str], OutboundTransportConfig]] = []

    def post(self, *, config, operation, payload, timeout_seconds):
        del timeout_seconds
        self.calls.append((operation, frozenset(payload), config))
        if operation is ControlPlaneHttpsOperation.OPEN_SESSION:
            return self.rpc.open_session(payload)
        if operation is ControlPlaneHttpsOperation.POLL:
            return self.rpc.poll(payload)
        if operation is ControlPlaneHttpsOperation.MATERIAL:
            if payload.get("credential_b64") is None:
                return {"ok": False, "error": {"code": "missing_credential", "message": "missing"}}
            return {"ok": True, "material": deepcopy(self.material_wire)}
        if operation is ControlPlaneHttpsOperation.ACKNOWLEDGE:
            return self.rpc.acknowledge(payload)
        raise AssertionError(f"unexpected operation {operation}")


def _config() -> OutboundTransportConfig:
    return OutboundTransportConfig(
        endpoint=OutboundBrokerEndpoint(
            endpoint_ref="broker_primary",
            url="https://broker.padiem.example/v1/local-agent",
            mode=OutboundTransportMode.HTTPS_LONG_POLL,
        ),
        poll_timeout_seconds=30,
        max_response_bytes=262_144,
    )


def _fixture():
    authority = InMemoryLocalAgentBrokerAuthority(
        pepper=b"deterministic-local-agent-broker-pepper",
        authority_ref="local_agent_broker_authority",
    )
    cp_binding = authority.register_binding(
        binding_ref="binding_https_1",
        device_id="device_https_1",
        account_ref="account_https_1",
        workspace_ref="workspace_https_1",
        credential=CREDENTIAL,
        now=BASE,
    )
    binding = DeviceBinding(
        device_id=cp_binding.device_id,
        binding_ref=cp_binding.binding_ref,
        account_ref=cp_binding.account_ref,
        workspace_ref=cp_binding.workspace_ref,
        credential_ref="credential-ref:https-1",
        credential_generation=cp_binding.credential_generation,
        issued_at=BASE,
        credential_expires_at=cp_binding.credential_expires_at,
        state=DeviceLifecycle.PAIRED_OFFLINE,
    )
    local_request = LocalCommandRequest(
        request_id="request_https_1",
        run_id="run_https_1",
        device_id=binding.device_id,
        root_ref="root_https_1",
        argv=(r"C:\Python311\python.exe", "-V"),
        cwd_relative=".",
        requested_at=BASE + timedelta(seconds=10),
        timeout_seconds=30,
    )
    fingerprint = command_request_fingerprint(local_request)
    cp_command = authority.enqueue_command(
        command_id="command_https_1",
        binding_ref=binding.binding_ref,
        run_id=local_request.run_id,
        tool_request_ref="tool_request_https_1",
        request_fingerprint=fingerprint,
        now=BASE + timedelta(seconds=20),
        ttl_seconds=300,
    )
    envelope = DeviceCommandEnvelope(
        command_id=cp_command.command_id,
        run_id=cp_command.run_id,
        tool_request_ref=cp_command.tool_request_ref,
        binding_ref=cp_command.binding_ref,
        sequence=cp_command.sequence,
        issued_at=cp_command.issued_at,
        expires_at=cp_command.expires_at,
    )
    material_wire = build_command_material_wire_projection(
        command=envelope,
        request=local_request,
        request_fingerprint=fingerprint,
    )
    rpc = LocalAgentBrokerRpcFacade(authority=authority)
    request_port = _DeterministicBrokerRequestPort(rpc=rpc, material_wire=material_wire)
    transport = ControlPlaneHttpsLongPollTransport(
        credential_store=_CredentialStore(),
        request_port=request_port,
    )
    pinned = PinnedOutboundBrokerBinding.from_binding(binding=binding, config=_config())
    channel = ControlPlanePinnedHttpsChannel(authority=pinned, transport=transport)
    return authority, binding, local_request, fingerprint, request_port, channel


class ControlPlanePhysicalCompositionTests(unittest.TestCase):
    def test_session_poll_fingerprint_material_and_ack_are_exactly_composed(self) -> None:
        authority, binding, local_request, fingerprint, request_port, channel = _fixture()
        session = channel.open_session(
            binding=binding,
            session_id="session_https_1",
            now=BASE + timedelta(seconds=25),
        )
        commands = channel.poll(
            binding=binding,
            request=OutboundPollRequest(
                request_ref="poll_https_1",
                session=session,
                after_sequence=0,
                requested_at=BASE + timedelta(seconds=30),
            ),
        )
        self.assertEqual(len(commands), 1)
        command = commands[0]
        material_request = channel.build_material_request(
            binding=binding,
            session=session,
            command=command,
            request_ref="material_https_1",
            now=BASE + timedelta(seconds=35),
        )
        self.assertEqual(material_request.request_fingerprint, fingerprint)
        resolved = channel.resolve_material(binding=binding, request=material_request)
        self.assertEqual(resolved.request, local_request)
        self.assertEqual(resolved.request_fingerprint, fingerprint)

        admission = authority.admit_command(
            admission_ref="admission_https_1",
            evidence_ref="evidence_https_1",
            session_id=session.session_id,
            binding_ref=binding.binding_ref,
            credential=CREDENTIAL,
            command_id=command.command_id,
            request_fingerprint=fingerprint,
            now=BASE + timedelta(seconds=40),
        )
        channel.acknowledge_admitted(
            binding=binding,
            session=session,
            command_id=command.command_id,
            admission_ref=admission.admission_ref,
            evidence_ref="evidence_https_1",
            now=BASE + timedelta(seconds=50),
        )
        operations = [item[0] for item in request_port.calls]
        self.assertEqual(
            operations,
            [
                ControlPlaneHttpsOperation.OPEN_SESSION,
                ControlPlaneHttpsOperation.POLL,
                ControlPlaneHttpsOperation.MATERIAL,
                ControlPlaneHttpsOperation.ACKNOWLEDGE,
            ],
        )
        with self.assertRaisesRegex(ContractError, "previously polled"):
            channel.acknowledge_admitted(
                binding=binding,
                session=session,
                command_id=command.command_id,
                admission_ref=admission.admission_ref,
                evidence_ref="evidence_https_1",
                now=BASE + timedelta(seconds=55),
            )

    def test_material_fingerprint_is_not_a_caller_parameter(self) -> None:
        _, binding, _, fingerprint, _, channel = _fixture()
        session = channel.open_session(
            binding=binding,
            session_id="session_https_2",
            now=BASE + timedelta(seconds=25),
        )
        command = channel.poll(
            binding=binding,
            request=OutboundPollRequest(
                request_ref="poll_https_2",
                session=session,
                after_sequence=0,
                requested_at=BASE + timedelta(seconds=30),
            ),
        )[0]
        params = inspect.signature(ControlPlanePinnedHttpsChannel.build_material_request).parameters
        self.assertNotIn("request_fingerprint", params)
        request = channel.build_material_request(
            binding=binding,
            session=session,
            command=command,
            request_ref="material_https_2",
            now=BASE + timedelta(seconds=35),
        )
        self.assertEqual(request.request_fingerprint, fingerprint)
        self.assertFalse(channel.safe_dict()["material_fingerprint_caller_supplied"])

    def test_wrong_ack_evidence_fails_at_control_plane_and_correct_retry_succeeds(self) -> None:
        authority, binding, _, fingerprint, _, channel = _fixture()
        session = channel.open_session(
            binding=binding,
            session_id="session_https_3",
            now=BASE + timedelta(seconds=25),
        )
        command = channel.poll(
            binding=binding,
            request=OutboundPollRequest(
                request_ref="poll_https_3",
                session=session,
                after_sequence=0,
                requested_at=BASE + timedelta(seconds=30),
            ),
        )[0]
        admission = authority.admit_command(
            admission_ref="admission_https_3",
            evidence_ref="evidence_https_3",
            session_id=session.session_id,
            binding_ref=binding.binding_ref,
            credential=CREDENTIAL,
            command_id=command.command_id,
            request_fingerprint=fingerprint,
            now=BASE + timedelta(seconds=40),
        )
        with self.assertRaisesRegex(ContractError, "broker_ack_correlation_mismatch"):
            channel.acknowledge_admitted(
                binding=binding,
                session=session,
                command_id=command.command_id,
                admission_ref=admission.admission_ref,
                evidence_ref="evidence_wrong",
                now=BASE + timedelta(seconds=50),
            )
        channel.acknowledge_admitted(
            binding=binding,
            session=session,
            command_id=command.command_id,
            admission_ref=admission.admission_ref,
            evidence_ref="evidence_https_3",
            now=BASE + timedelta(seconds=55),
        )


class _FakeHttpResponse:
    def __init__(self, *, status: int, body: bytes, content_type: str = "application/json") -> None:
        self.status = status
        self._body = body
        self._content_type = content_type

    def read(self, amount: int) -> bytes:
        return self._body[:amount]

    def getheader(self, name: str):
        if name.lower() == "content-type":
            return self._content_type
        return None


class _FakeHttpsConnection:
    def __init__(self, response: _FakeHttpResponse, captured: dict, host, port, timeout, context) -> None:
        captured["host"] = host
        captured["port"] = port
        captured["timeout"] = timeout
        captured["context"] = context
        self._response = response
        self._captured = captured

    def request(self, method, path, body=None, headers=None):
        self._captured["method"] = method
        self._captured["path"] = path
        self._captured["body"] = body
        self._captured["headers"] = headers

    def getresponse(self):
        return self._response

    def close(self):
        self._captured["closed"] = True


class StdlibPinnedHttpsSourceTests(unittest.TestCase):
    def test_default_tls_context_exact_host_and_no_redirecting_stack(self) -> None:
        captured: dict = {}
        response = _FakeHttpResponse(status=200, body=json.dumps({"ok": True, "commands": []}).encode())

        def factory(host, port, timeout, context):
            return _FakeHttpsConnection(response, captured, host, port, timeout, context)

        with patch.object(https_module.http.client, "HTTPSConnection", side_effect=factory):
            result = StdlibPinnedHttpsJsonRequestPort().post(
                config=_config(),
                operation=ControlPlaneHttpsOperation.POLL,
                payload={"probe": "safe"},
                timeout_seconds=10,
            )
        self.assertEqual(result, {"ok": True, "commands": []})
        self.assertEqual(captured["host"], "broker.padiem.example")
        self.assertEqual(captured["port"], 443)
        self.assertEqual(captured["path"], "/v1/local-agent/poll")
        self.assertEqual(captured["method"], "POST")
        self.assertEqual(captured["context"].verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(captured["context"].check_hostname)
        self.assertTrue(captured["closed"])

    def test_redirect_and_non_json_responses_fail_closed(self) -> None:
        for response, message in (
            (_FakeHttpResponse(status=302, body=b""), "redirect"),
            (_FakeHttpResponse(status=200, body=b"not-json", content_type="application/json"), "invalid JSON"),
            (_FakeHttpResponse(status=200, body=b"{}", content_type="text/html"), "application/json"),
        ):
            captured: dict = {}

            def factory(host, port, timeout, context, _response=response, _captured=captured):
                return _FakeHttpsConnection(_response, _captured, host, port, timeout, context)

            with self.subTest(message=message):
                with patch.object(https_module.http.client, "HTTPSConnection", side_effect=factory):
                    with self.assertRaisesRegex(ContractError, message):
                        StdlibPinnedHttpsJsonRequestPort().post(
                            config=_config(),
                            operation=ControlPlaneHttpsOperation.POLL,
                            payload={"probe": "safe"},
                            timeout_seconds=10,
                        )


class PhysicalSourceTruthTests(unittest.TestCase):
    def test_source_and_non_claim_flags(self) -> None:
        self.assertTrue(STDLIB_HTTPS_TRANSPORT_SOURCE)
        self.assertTrue(TLS_DEFAULT_CONTEXT)
        self.assertFalse(REDIRECT_AUTO_FOLLOW)
        self.assertFalse(CALLER_ENDPOINT_OVERRIDE)
        self.assertFalse(RAW_DEVICE_CREDENTIAL_IN_SAFE_STATE)
        self.assertTrue(POLL_FINGERPRINT_FROM_CONTROL_PLANE)
        self.assertTrue(ACK_ADMISSION_REF_REQUIRED)
        self.assertTrue(ACK_EVIDENCE_REF_REQUIRED)
        self.assertFalse(PUBLIC_INBOUND_PORT)
        self.assertFalse(PRODUCTION_BROKER_CONFIGURED)
        self.assertFalse(REAL_REMOTE_EXECUTION)
        self.assertFalse(PRODUCTION_READY)
        self.assertTrue(PINNED_CONTROL_PLANE_HTTPS_CHANNEL)
        self.assertFalse(MATERIAL_FINGERPRINT_CALLER_SUPPLIED)
        self.assertTrue(CHANNEL_ACK_ADMISSION_REF_REQUIRED)
        self.assertTrue(CHANNEL_ACK_EVIDENCE_REF_REQUIRED)
        self.assertFalse(CHANNEL_PUBLIC_INBOUND_PORT)
        self.assertFalse(CHANNEL_PRODUCTION_BROKER_CONFIGURED)
        self.assertFalse(CHANNEL_PRODUCTION_READY)


if __name__ == "__main__":
    unittest.main()
