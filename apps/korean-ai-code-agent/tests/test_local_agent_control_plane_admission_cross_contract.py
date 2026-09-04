from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json

import pytest

from padiem_control_plane.local_agent_broker import InMemoryLocalAgentBrokerAuthority
from padiem_control_plane.local_agent_broker_admission_http import AdmissionEnabledLocalAgentBrokerHttpHandler
from padiem_control_plane.local_agent_broker_http import (
    DurableLocalAgentSessionRecord,
    TrustedLocalAgentHttpAuthContext,
)
from padiem_control_plane.local_agent_broker_rpc import LocalAgentBrokerRpcFacade

from kagent.local_agent import (
    LocalAgentDeviceProfile,
    LocalAgentPlatform,
    LocalCommandRequest,
    LocalCommandResult,
    LocalRoot,
)
from kagent.local_agent_command_material import build_command_material_wire_projection
from kagent.local_agent_control_plane_admission import (
    ACK_EXACT_ADMISSION_EVIDENCE,
    ACK_ON_EXECUTION_FAILURE,
    ADMITTED_EXECUTION_BRIDGE_REUSED,
    CLIENT_ADMISSION_AUTHORITY,
    CONTROL_PLANE_ADMISSION_CONFORMANCE_REUSED,
    EVIDENCE_REF_END_TO_END,
    LIVE_BROKER_CONFIGURED,
    LIVE_WINDOWS_ACCEPTANCE,
    PHYSICAL_ADMISSION_EVIDENCE_SOURCE,
    POST_MATERIAL_ADMISSION_ORDER,
    PRODUCTION_MUTATION,
    PRODUCTION_READY,
    P01_AUTHORITY_DUPLICATED,
    SECOND_FINGERPRINT_AUTHORITY,
    SECOND_REPLAY_SEQUENCE_AUTHORITY,
    SERVER_OWNED_ADMISSION_REFS,
    WINDOWS_AUTHORIZATION_REUSED,
    ControlPlaneAdmittedExecutionCoordinator,
    ControlPlanePhysicalAdmissionChannel,
    ControlPlanePhysicalAdmissionTransport,
)
from kagent.local_agent_pairing import DeviceBinding, DeviceCommandEnvelope, DeviceLifecycle
from kagent.local_agent_permissions import default_device_permission_profile
from kagent.local_agent_runtime_assembly import BoundLocalAgentRuntimeAssembly
from kagent.local_agent_secure_channel import PinnedOutboundBrokerBinding
from kagent.local_agent_secure_transport import (
    OutboundBrokerEndpoint,
    OutboundPollRequest,
    OutboundTransportConfig,
    OutboundTransportMode,
)
from kagent.windows_local_executor import (
    WindowsExecutionReceipt,
    WindowsExecutionTermination,
    command_request_fingerprint,
)


BASE = datetime(2026, 9, 4, 2, 40, tzinfo=timezone.utc)
CREDENTIAL = b"physical-admission-cross-contract-credential"
AUTHORITY_REF = "control-plane.local-agent-broker.physical-admission.v1"
ADMISSION_REF = "admission_physical_server_1"
EVIDENCE_REF = "evidence_physical_server_1"


class _ServerClock:
    def __init__(self) -> None:
        self.now = BASE

    def __call__(self) -> datetime:
        return self.now


class _SequenceClock:
    def __init__(self, values: list[datetime]) -> None:
        self.values = list(values)
        self.calls: list[datetime] = []

    def __call__(self) -> datetime:
        if not self.values:
            raise AssertionError("runtime clock was called more times than expected")
        value = self.values.pop(0)
        self.calls.append(value)
        return value


class _DurableState:
    durable = True

    def __init__(self) -> None:
        self.records: dict[str, DurableLocalAgentSessionRecord] = {}

    def save_session(self, record: DurableLocalAgentSessionRecord) -> None:
        self.records[record.session_id] = record

    def load_session(self, session_id: str) -> DurableLocalAgentSessionRecord:
        return self.records[session_id]

    def record_last_seen(self, session_id: str, *, seen_at: datetime) -> DurableLocalAgentSessionRecord:
        changed = self.records[session_id].with_last_seen(seen_at)
        self.records[session_id] = changed
        return changed


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


class _References:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> tuple[str, str]:
        self.calls += 1
        return ADMISSION_REF, EVIDENCE_REF


class _HandlerBackedRequestPort:
    SERVER_OFFSET = {
        "session": timedelta(seconds=24),
        "poll": timedelta(seconds=31),
        "material": timedelta(seconds=36),
        "admission": timedelta(seconds=41),
        "acknowledge": timedelta(seconds=52),
    }

    def __init__(self, *, handler, auth, clock: _ServerClock) -> None:
        self.handler = handler
        self.auth = auth
        self.clock = clock
        self.calls: list[tuple[str, dict]] = []

    def post(self, *, config, operation, payload, timeout_seconds):
        del config, timeout_seconds
        name = operation.value
        self.clock.now = BASE + self.SERVER_OFFSET[name]
        self.calls.append((name, deepcopy(payload)))
        response = self.handler.handle(
            method="POST",
            route=f"/{name}",
            content_type="application/json",
            body=json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8"),
            auth=self.auth,
        )
        return deepcopy(response.body)


class _ReceiptRuntime:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.executed: list[str] = []

    def execute_with_receipt(self, request: LocalCommandRequest, *, now: datetime) -> WindowsExecutionReceipt:
        self.executed.append(request.request_id)
        if self.fail:
            raise RuntimeError("deterministic Windows execution failure")
        return WindowsExecutionReceipt(
            result=LocalCommandResult(
                request_id=request.request_id,
                run_id=request.run_id,
                device_id=request.device_id,
                root_ref=request.root_ref,
                started_at=now,
                ended_at=now + timedelta(milliseconds=1),
                exit_code=0,
                stdout="Python 3.13.0",
                stderr="",
                cancelled=False,
                dirty_worktree_before=False,
                dirty_worktree_after=False,
            ),
            termination=WindowsExecutionTermination.EXITED,
            executable_profile_ref="python_profile",
            authorization_ref="windows_p01_grant_cross_1",
        )

    def cancel(self, request_id: str) -> None:
        del request_id


def _config() -> OutboundTransportConfig:
    return OutboundTransportConfig(
        endpoint=OutboundBrokerEndpoint(
            endpoint_ref="broker_physical_admission_cross",
            url="https://broker.padiem.example/v1/local-agent",
            mode=OutboundTransportMode.HTTPS_LONG_POLL,
        ),
        poll_timeout_seconds=30,
        max_response_bytes=262_144,
    )


def _fixture(*, fail_runtime: bool = False):
    authority = InMemoryLocalAgentBrokerAuthority(
        pepper=b"physical-admission-control-plane-pepper",
        authority_ref=AUTHORITY_REF,
    )
    cp_binding = authority.register_binding(
        binding_ref="binding.physical.1",
        device_id="device.physical.1",
        account_ref="account.physical.1",
        workspace_ref="workspace.physical.1",
        credential=CREDENTIAL,
        now=BASE,
    )
    binding = DeviceBinding(
        device_id=cp_binding.device_id,
        binding_ref=cp_binding.binding_ref,
        account_ref=cp_binding.account_ref,
        workspace_ref=cp_binding.workspace_ref,
        credential_ref="credential-ref:physical-admission-1",
        credential_generation=cp_binding.credential_generation,
        issued_at=BASE,
        credential_expires_at=cp_binding.credential_expires_at,
        state=DeviceLifecycle.ONLINE,
    )
    local_request = LocalCommandRequest(
        request_id="request_physical_1",
        run_id="run_physical_1",
        device_id=binding.device_id,
        root_ref="root_code",
        argv=(r"C:\Python313\python.exe", "-V"),
        cwd_relative=".",
        requested_at=BASE + timedelta(seconds=10),
        timeout_seconds=30,
    )
    fingerprint = command_request_fingerprint(local_request)
    cp_command = authority.enqueue_command(
        command_id="command_physical_1",
        binding_ref=binding.binding_ref,
        run_id=local_request.run_id,
        tool_request_ref="tool_request_physical_1",
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
    server_clock = _ServerClock()
    references = _References()
    handler = AdmissionEnabledLocalAgentBrokerHttpHandler(
        rpc=LocalAgentBrokerRpcFacade(authority=authority),
        state=_DurableState(),
        material_resolver=resolver,
        clock=server_clock,
        admission_reference_factory=references,
    )
    auth = TrustedLocalAgentHttpAuthContext(
        principal_ref="principal.physical.1",
        account_ref=binding.account_ref,
        workspace_ref=binding.workspace_ref,
        authenticated=True,
        tls_verified=True,
    )
    request_port = _HandlerBackedRequestPort(handler=handler, auth=auth, clock=server_clock)
    transport = ControlPlanePhysicalAdmissionTransport(
        credential_store=_CredentialStore(),
        expected_admission_authority_ref=AUTHORITY_REF,
        request_port=request_port,
    )
    pinned = PinnedOutboundBrokerBinding.from_binding(binding=binding, config=_config())
    channel = ControlPlanePhysicalAdmissionChannel(authority=pinned, transport=transport)

    device = LocalAgentDeviceProfile(
        device_id=binding.device_id,
        workspace_ref=binding.workspace_ref,
        platform=LocalAgentPlatform.WINDOWS,
        roots=(LocalRoot(root_ref="root_code", windows_path=r"E:\padiem-claw"),),
    )
    runtime = _ReceiptRuntime(fail=fail_runtime)
    assembly = BoundLocalAgentRuntimeAssembly(
        device=device,
        binding=binding,
        permissions=default_device_permission_profile(device=device),
        broker_authority=pinned,
        runtime=runtime,
    )
    return authority, binding, local_request, resolver, references, request_port, channel, assembly, runtime


def _open_and_poll(binding, channel):
    session = channel.open_session(
        binding=binding,
        session_id="session_physical_1",
        now=BASE + timedelta(seconds=25),
    )
    command = channel.poll(
        binding=binding,
        request=OutboundPollRequest(
            request_ref="poll_physical_1",
            session=session,
            after_sequence=0,
            requested_at=BASE + timedelta(seconds=30),
        ),
    )[0]
    return session, command


def test_full_physical_material_admission_execution_ack_order_and_evidence_ref() -> None:
    authority, binding, local_request, resolver, references, request_port, channel, assembly, runtime = _fixture()
    session, command = _open_and_poll(binding, channel)
    local_clock = _SequenceClock(
        [
            BASE + timedelta(seconds=35),  # material request
            BASE + timedelta(seconds=40),  # admission request (server accepts at 41)
            BASE + timedelta(seconds=42),  # Windows execution
            BASE + timedelta(seconds=50),  # ack request (server acks at 52)
        ]
    )
    coordinator = ControlPlaneAdmittedExecutionCoordinator(
        channel=channel,
        assembly=assembly,
        clock=local_clock,
    )

    receipt = coordinator.execute_polled_command(
        binding=binding,
        session=session,
        command=command,
        material_request_ref="material_physical_1",
    )

    assert [name for name, _ in request_port.calls] == [
        "session",
        "poll",
        "material",
        "admission",
        "acknowledge",
    ]
    assert resolver.requests[0].command_id == command.command_id
    assert resolver.requests[0].request_fingerprint == command_request_fingerprint(local_request)
    assert references.calls == 1
    assert runtime.executed == [local_request.request_id]
    assert receipt.execution.admission_ref == ADMISSION_REF
    assert receipt.evidence_ref == EVIDENCE_REF
    assert receipt.execution.authorization_ref == "windows_p01_grant_cross_1"
    assert request_port.calls[-1][1]["admission_ref"] == ADMISSION_REF
    assert request_port.calls[-1][1]["evidence_ref"] == EVIDENCE_REF

    stored = authority._commands[command.command_id]
    assert stored.state.value == "acknowledged"
    assert stored.admission_ref == ADMISSION_REF
    assert stored.evidence_ref == EVIDENCE_REF
    assert stored.admitted_at == BASE + timedelta(seconds=41)
    assert stored.acknowledged_at == BASE + timedelta(seconds=52)

    safe = receipt.safe_dict()
    assert safe["material_before_admission"] is True
    assert safe["ack_exact_admission_evidence"] is True
    assert safe["raw_argv"] is False
    assert safe["stdout"] is False
    assert safe["stderr"] is False
    assert safe["raw_device_credential"] is False
    assert safe["p01_payload"] is False


def test_execution_failure_does_not_emit_acknowledgement() -> None:
    authority, binding, _request, _resolver, references, request_port, channel, assembly, runtime = _fixture(
        fail_runtime=True
    )
    session, command = _open_and_poll(binding, channel)
    coordinator = ControlPlaneAdmittedExecutionCoordinator(
        channel=channel,
        assembly=assembly,
        clock=_SequenceClock(
            [
                BASE + timedelta(seconds=35),
                BASE + timedelta(seconds=40),
                BASE + timedelta(seconds=42),
            ]
        ),
    )

    with pytest.raises(RuntimeError, match="Windows execution failure"):
        coordinator.execute_polled_command(
            binding=binding,
            session=session,
            command=command,
            material_request_ref="material_physical_fail_1",
        )

    assert [name for name, _ in request_port.calls] == ["session", "poll", "material", "admission"]
    assert references.calls == 1
    assert runtime.executed == ["request_physical_1"]
    stored = authority._commands[command.command_id]
    assert stored.state.value == "admitted"
    assert stored.acknowledged_at is None


def test_conformed_admission_preserves_evidence_ref_without_changing_execution_evidence_type() -> None:
    _authority, binding, local_request, _resolver, _references, _request_port, channel, _assembly, _runtime = _fixture()
    session, command = _open_and_poll(binding, channel)
    resolved = channel.resolve_broker_material(
        binding=binding,
        session=session,
        command=command,
        request_ref="material_physical_conformance_1",
        now=BASE + timedelta(seconds=35),
    )
    conformed = channel.admit_resolved(
        binding=binding,
        session=session,
        command=command,
        resolved=resolved,
        now=BASE + timedelta(seconds=40),
    )
    assert conformed.evidence.admission_ref == ADMISSION_REF
    assert conformed.evidence_ref == EVIDENCE_REF
    assert "evidence_ref" not in conformed.evidence.safe_dict()
    assert conformed.evidence.request_fingerprint == command_request_fingerprint(local_request)
    assert conformed.safe_dict()["evidence_ref"] == EVIDENCE_REF


def test_runtime_truth_flags_preserve_authority_and_production_nonclaims() -> None:
    assert PHYSICAL_ADMISSION_EVIDENCE_SOURCE is True
    assert SERVER_OWNED_ADMISSION_REFS is True
    assert CLIENT_ADMISSION_AUTHORITY is False
    assert POST_MATERIAL_ADMISSION_ORDER is True
    assert CONTROL_PLANE_ADMISSION_CONFORMANCE_REUSED is True
    assert EVIDENCE_REF_END_TO_END is True
    assert ADMITTED_EXECUTION_BRIDGE_REUSED is True
    assert WINDOWS_AUTHORIZATION_REUSED is True
    assert ACK_EXACT_ADMISSION_EVIDENCE is True
    assert ACK_ON_EXECUTION_FAILURE is False
    assert SECOND_REPLAY_SEQUENCE_AUTHORITY is False
    assert SECOND_FINGERPRINT_AUTHORITY is False
    assert P01_AUTHORITY_DUPLICATED is False
    assert LIVE_BROKER_CONFIGURED is False
    assert LIVE_WINDOWS_ACCEPTANCE is False
    assert PRODUCTION_MUTATION is False
    assert PRODUCTION_READY is False
