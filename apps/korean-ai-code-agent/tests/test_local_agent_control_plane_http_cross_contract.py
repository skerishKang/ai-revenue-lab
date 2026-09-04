from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json

from padiem_control_plane.local_agent_broker import InMemoryLocalAgentBrokerAuthority
from padiem_control_plane.local_agent_broker_http import (
    DurableLocalAgentSessionRecord,
    LocalAgentBrokerHttpHandler,
    TrustedLocalAgentHttpAuthContext,
)
from padiem_control_plane.local_agent_broker_rpc import LocalAgentBrokerRpcFacade

from kagent.local_agent import LocalCommandRequest
from kagent.local_agent_command_material import build_command_material_wire_projection
from kagent.local_agent_control_plane_channel import ControlPlanePinnedHttpsChannel
from kagent.local_agent_control_plane_https import (
    SERVER_ACK_TIME_AUTHORITY,
    ControlPlaneHttpsLongPollTransport,
    ControlPlaneHttpsOperation,
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

BASE = datetime(2026, 9, 4, 1, 0, tzinfo=timezone.utc)
CREDENTIAL = b"cross-contract-device-credential"


class _Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


class _DurableState:
    durable = True

    def __init__(self) -> None:
        self.records: dict[str, DurableLocalAgentSessionRecord] = {}

    def save_session(self, record: DurableLocalAgentSessionRecord) -> None:
        self.records[record.session_id] = record

    def load_session(self, session_id: str) -> DurableLocalAgentSessionRecord:
        return self.records[session_id]

    def record_last_seen(self, session_id: str, *, seen_at: datetime) -> DurableLocalAgentSessionRecord:
        record = self.records[session_id].with_last_seen(seen_at)
        self.records[session_id] = record
        return record


class _CredentialStore:
    def load(self, *, binding: DeviceBinding, now: datetime) -> bytes:
        del binding, now
        return CREDENTIAL


class _MaterialResolver:
    def __init__(self, wire: dict) -> None:
        self.wire = wire
        self.requests = []

    def resolve(self, request):
        self.requests.append(request)
        return deepcopy(self.wire)


class _HandlerBackedHttpsJsonRequestPort:
    """Cross-contract bridge at the physical client's JSON request-port boundary."""

    def __init__(self, *, handler: LocalAgentBrokerHttpHandler, auth: TrustedLocalAgentHttpAuthContext) -> None:
        self.handler = handler
        self.auth = auth
        self.calls: list[tuple[ControlPlaneHttpsOperation, int, str]] = []

    def post(self, *, config, operation, payload, timeout_seconds):
        del config
        content_type = "application/json"
        self.calls.append((operation, timeout_seconds, content_type))
        response = self.handler.handle(
            method="POST",
            route=f"/{operation.value}",
            content_type=content_type,
            body=json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8"),
            auth=self.auth,
        )
        return deepcopy(response.body)


def _config() -> OutboundTransportConfig:
    return OutboundTransportConfig(
        endpoint=OutboundBrokerEndpoint(
            endpoint_ref="broker_cross_contract",
            url="https://broker.padiem.example/v1/local-agent",
            mode=OutboundTransportMode.HTTPS_LONG_POLL,
        ),
        poll_timeout_seconds=30,
        max_response_bytes=262_144,
    )


def test_physical_b54_client_composes_with_authenticated_http_handler_and_server_clock() -> None:
    authority = InMemoryLocalAgentBrokerAuthority(
        pepper=b"cross-contract-control-plane-pepper",
        authority_ref="control-plane.local-agent-broker.cross-contract.v1",
    )
    cp_binding = authority.register_binding(
        binding_ref="binding.cross.1",
        device_id="device.cross.1",
        account_ref="account.cross.1",
        workspace_ref="workspace.cross.1",
        credential=CREDENTIAL,
        now=BASE,
    )
    binding = DeviceBinding(
        device_id=cp_binding.device_id,
        binding_ref=cp_binding.binding_ref,
        account_ref=cp_binding.account_ref,
        workspace_ref=cp_binding.workspace_ref,
        credential_ref="credential-ref:cross-1",
        credential_generation=cp_binding.credential_generation,
        issued_at=BASE,
        credential_expires_at=cp_binding.credential_expires_at,
        state=DeviceLifecycle.PAIRED_OFFLINE,
    )
    local_request = LocalCommandRequest(
        request_id="request_cross_1",
        run_id="run_cross_1",
        device_id=binding.device_id,
        root_ref="root_cross_1",
        argv=(r"C:\Python311\python.exe", "-V"),
        cwd_relative=".",
        requested_at=BASE + timedelta(seconds=10),
        timeout_seconds=30,
    )
    fingerprint = command_request_fingerprint(local_request)
    cp_command = authority.enqueue_command(
        command_id="command_cross_1",
        binding_ref=binding.binding_ref,
        run_id=local_request.run_id,
        tool_request_ref="tool_request_cross_1",
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
    resolver = _MaterialResolver(
        build_command_material_wire_projection(
            command=envelope,
            request=local_request,
            request_fingerprint=fingerprint,
        )
    )
    clock = _Clock(BASE + timedelta(seconds=24))
    handler = LocalAgentBrokerHttpHandler(
        rpc=LocalAgentBrokerRpcFacade(authority=authority),
        state=_DurableState(),
        material_resolver=resolver,
        clock=clock,
    )
    auth = TrustedLocalAgentHttpAuthContext(
        principal_ref="principal.cross.1",
        account_ref=binding.account_ref,
        workspace_ref=binding.workspace_ref,
        authenticated=True,
        tls_verified=True,
    )
    request_port = _HandlerBackedHttpsJsonRequestPort(handler=handler, auth=auth)
    transport = ControlPlaneHttpsLongPollTransport(
        credential_store=_CredentialStore(),
        request_port=request_port,
    )
    channel = ControlPlanePinnedHttpsChannel(
        authority=PinnedOutboundBrokerBinding.from_binding(binding=binding, config=_config()),
        transport=transport,
    )

    session = channel.open_session(
        binding=binding,
        session_id="session_cross_1",
        now=BASE + timedelta(seconds=25),
    )
    assert session.issued_at == BASE + timedelta(seconds=24)

    clock.now = BASE + timedelta(seconds=31)
    command = channel.poll(
        binding=binding,
        request=OutboundPollRequest(
            request_ref="poll_cross_1",
            session=session,
            after_sequence=0,
            requested_at=BASE + timedelta(seconds=30),
        ),
    )[0]
    assert command.command_id == envelope.command_id

    clock.now = BASE + timedelta(seconds=36)
    material_request = channel.build_material_request(
        binding=binding,
        session=session,
        command=command,
        request_ref="material_cross_1",
        now=BASE + timedelta(seconds=35),
    )
    assert material_request.request_fingerprint == fingerprint
    resolved = channel.resolve_material(binding=binding, request=material_request)
    assert resolved.request == local_request
    assert resolver.requests[0].request_fingerprint == fingerprint
    assert resolver.requests[0].server_requested_at == BASE + timedelta(seconds=36)

    admission = authority.admit_command(
        admission_ref="admission_cross_1",
        evidence_ref="evidence_cross_1",
        session_id=session.session_id,
        binding_ref=binding.binding_ref,
        credential=CREDENTIAL,
        command_id=command.command_id,
        request_fingerprint=fingerprint,
        now=BASE + timedelta(seconds=40),
    )

    # The server is deliberately two seconds ahead of the client at acknowledgement.
    # A client-time equality check would reject this valid server-authoritative response.
    clock.now = BASE + timedelta(seconds=52)
    channel.acknowledge_admitted(
        binding=binding,
        session=session,
        command_id=command.command_id,
        admission_ref=admission.admission_ref,
        evidence_ref="evidence_cross_1",
        now=BASE + timedelta(seconds=50),
    )

    assert [item[0] for item in request_port.calls] == [
        ControlPlaneHttpsOperation.OPEN_SESSION,
        ControlPlaneHttpsOperation.POLL,
        ControlPlaneHttpsOperation.MATERIAL,
        ControlPlaneHttpsOperation.ACKNOWLEDGE,
    ]
    assert all(item[2] == "application/json" for item in request_port.calls)
    assert SERVER_ACK_TIME_AUTHORITY is True
    assert transport.safe_dict()["server_ack_time_authority"] is True
