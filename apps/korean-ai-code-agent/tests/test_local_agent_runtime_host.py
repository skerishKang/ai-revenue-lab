from __future__ import annotations

import json
import threading
import unittest
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any, ClassVar

from kagent.contracts import ContractError
from kagent.local_agent import (
    LocalAgentDeviceProfile,
    LocalAgentPlatform,
    LocalCommandRequest,
    LocalCommandResult,
    LocalRoot,
)
from kagent.local_agent_command_material import build_command_material_wire_projection
from kagent.local_agent_control_plane_admission import (
    ControlPlanePhysicalAdmissionChannel,
    ControlPlanePhysicalAdmissionTransport,
)
from kagent.local_agent_pairing import (
    DeviceBinding,
    DeviceCommandEnvelope,
    DeviceLifecycle,
)
from kagent.local_agent_permissions import default_device_permission_profile
from kagent.local_agent_runtime_assembly import BoundLocalAgentRuntimeAssembly
from kagent.local_agent_runtime_host import (
    ARBITRARY_BROKER_DESTINATION,
    BOUNDED_RECONNECT,
    CANCELLATION_AWARE,
    CANONICAL_COMMAND_ENVELOPE_REUSED,
    CANONICAL_CREDENTIAL_STORE_REUSED,
    CANONICAL_P01_APPROVAL_REUSED,
    CANONICAL_PERMISSION_AUTHORITY_REUSED,
    CANONICAL_SESSION_REUSED,
    CANONICAL_WINDOWS_EXECUTOR_REUSED,
    OUTBOUND_ONLY,
    PRODUCTION_MUTATION,
    PRODUCTION_READY,
    PRODUCTION_REMOTE_CONTROL_CLAIM,
    RAW_DEVICE_SECRET_IN_LOG,
    REAL_USER_PAIRING_CANARY,
    REAL_WINDOWS_SERVICE_INSTALL,
    SINGLE_INSTANCE,
    USER_LEVEL_DEFAULT,
    WINDOWS_RESIDENT_HOST_CONTRACT,
    WINDOWS_RESIDENT_HOST_IMPLEMENTATION,
    InMemorySingleInstanceLock,
    LocalAgentResidentRuntimeHost,
    ResidentHostState,
)
from kagent.local_agent_secure_channel import PinnedOutboundBrokerBinding
from kagent.local_agent_secure_transport import (
    DeviceCredentialStore,
    OutboundBrokerEndpoint,
    OutboundTransportConfig,
    OutboundTransportMode,
)
from kagent.windows_local_executor import (
    WindowsExecutionReceipt,
    WindowsExecutionTermination,
    command_request_fingerprint,
)
from padiem_control_plane.local_agent_broker import InMemoryLocalAgentBrokerAuthority
from padiem_control_plane.local_agent_broker_admission_http import (
    AdmissionEnabledLocalAgentBrokerHttpHandler,
)
from padiem_control_plane.local_agent_broker_http import (
    DurableLocalAgentSessionRecord,
    TrustedLocalAgentHttpAuthContext,
)

BASE = datetime(2026, 9, 24, 9, 0, tzinfo=timezone.utc)
CREDENTIAL = b"resident-host-cross-contract-credential"
AUTHORITY_REF = "control-plane.local-agent-broker.resident-host.v1"
ADMISSION_REF = "admission_resident_host_1"
EVIDENCE_REF = "evidence_resident_host_1"


class _ServerClock:
    def __init__(self) -> None:
        self.now = BASE

    def __call__(self) -> datetime:
        return self.now


class _SimulatedClock:
    def __init__(self, start: datetime = BASE) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


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


class _MockCredentialStore(DeviceCredentialStore):
    def __init__(self, credential: bytes = CREDENTIAL, *, expire: bool = False, missing: bool = False) -> None:
        self.credential = credential
        self.expire = expire
        self.missing = missing
        self.load_calls = 0

    def load(self, *, binding: DeviceBinding, now: datetime) -> bytes:
        self.load_calls += 1
        if self.missing:
            raise ContractError("stored device credential not found")
        if self.expire or now >= binding.credential_expires_at:
            raise ContractError("device credential binding is expired")
        return self.credential

    def store(self, *, binding: DeviceBinding, credential: bytes, now: datetime) -> None:
        del binding, credential, now

    def delete(self, binding_ref: str) -> None:
        del binding_ref


class _MaterialResolver:
    def __init__(self, wire: dict) -> None:
        self.wire = wire
        self.requests: list[Any] = []

    def resolve(self, request: Any) -> dict:
        self.requests.append(request)
        return deepcopy(self.wire)


class _References:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> tuple[str, str]:
        self.calls += 1
        return ADMISSION_REF, EVIDENCE_REF


class _HandlerBackedRequestPort:
    SERVER_OFFSET: ClassVar[dict[str, timedelta]] = {
        "session": timedelta(seconds=5),
        "heartbeat": timedelta(seconds=10),
        "poll": timedelta(seconds=15),
        "material": timedelta(seconds=20),
        "admission": timedelta(seconds=25),
        "acknowledge": timedelta(seconds=30),
    }

    def __init__(self, *, handler: Any, auth: Any, clock: _ServerClock, fail_network: bool = False) -> None:
        self.handler = handler
        self.auth = auth
        self.clock = clock
        self.fail_network = fail_network
        self.calls: list[tuple[str, dict]] = []

    def post(self, *, config: Any, operation: Any, payload: Any, timeout_seconds: Any) -> dict:
        del config, timeout_seconds
        if self.fail_network:
            raise ConnectionError("simulated broker connection failure")
        name = operation.value
        if name == "heartbeat" and isinstance(payload, dict) and "now" in payload:
            # The heartbeat contract requires last_seen_at == client_now.
            # Honour that by setting the server clock to exactly what the client sent.
            from datetime import datetime as _dt
            self.clock.now = _dt.fromisoformat(payload["now"].replace("Z", "+00:00"))
        else:
            offset = self.SERVER_OFFSET.get(name, timedelta(seconds=0))
            self.clock.now = BASE + offset
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
        self.cancelled: list[str] = []

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
            authorization_ref="windows_p01_grant_host_1",
        )

    def cancel(self, request_id: str) -> None:
        self.cancelled.append(request_id)


class _BlockingReceiptRuntime(_ReceiptRuntime):
    def __init__(self) -> None:
        super().__init__()
        self.started = threading.Event()
        self.cancelled_event = threading.Event()

    def execute_with_receipt(self, request: LocalCommandRequest, *, now: datetime) -> WindowsExecutionReceipt:
        self.started.set()
        if not self.cancelled_event.wait(timeout=2):
            raise RuntimeError("deterministic Windows execution cancellation timeout")
        return super().execute_with_receipt(request, now=now)

    def cancel(self, request_id: str) -> None:
        super().cancel(request_id)
        self.cancelled_event.set()


class _TransportFailureRuntime(_ReceiptRuntime):
    def execute_with_receipt(self, request: LocalCommandRequest, *, now: datetime) -> WindowsExecutionReceipt:
        del now
        self.executed.append(request.request_id)
        raise ConnectionError("simulated execution transport failure")


def _config() -> OutboundTransportConfig:
    return OutboundTransportConfig(
        endpoint=OutboundBrokerEndpoint(
            endpoint_ref="broker_endpoint_resident_host",
            url="https://local-agent.padiem.net:443/broker",
            mode=OutboundTransportMode.HTTPS_LONG_POLL,
        ),
        heartbeat_seconds=30,
        poll_timeout_seconds=15,
        max_response_bytes=65536,
        tls_required=True,
        public_inbound_port=False,
    )


def _harness(
    *,
    fail_network: bool = False,
    fail_runtime: bool = False,
    binding_state: DeviceLifecycle = DeviceLifecycle.ONLINE,
    credential_expired: bool = False,
    credential_missing: bool = False,
    blocking_runtime: bool = False,
    transport_failure_runtime: bool = False,
) -> tuple[LocalAgentResidentRuntimeHost, _ReceiptRuntime, _HandlerBackedRequestPort, _SimulatedClock]:
    server_clock = _ServerClock()
    authority = InMemoryLocalAgentBrokerAuthority(
        pepper=b"physical-admission-control-plane-pepper",
        authority_ref=AUTHORITY_REF,
    )
    durable = _DurableState()
    auth = TrustedLocalAgentHttpAuthContext(
        principal_ref="principal.resident.1",
        account_ref="acc_host_1",
        workspace_ref="ws_host_1",
        authenticated=True,
        tls_verified=True,
    )

    authority.register_binding(
        binding_ref="bind_host_1",
        device_id="dev_host_1",
        account_ref="acc_host_1",
        workspace_ref="ws_host_1",
        credential=CREDENTIAL,
        now=BASE,
    )

    root = LocalRoot(root_ref="root_repo", windows_path="C:\\padiem\\repo")
    local_request = LocalCommandRequest(
        request_id="req_host_1",
        run_id="run_host_1",
        device_id="dev_host_1",
        root_ref="root_repo",
        argv=("python", "--version"),
        cwd_relative=".",
        requested_at=BASE + timedelta(seconds=1),
        timeout_seconds=30,
    )
    fingerprint = command_request_fingerprint(local_request)

    cp_command = authority.enqueue_command(
        command_id="cmd_host_1",
        binding_ref="bind_host_1",
        run_id="run_host_1",
        tool_request_ref="tool_req_host_1",
        request_fingerprint=fingerprint,
        now=BASE + timedelta(seconds=2),
        ttl_seconds=300,
    )
    if binding_state is DeviceLifecycle.REVOKED:
        authority.revoke_binding(binding_ref="bind_host_1", now=BASE + timedelta(seconds=2, milliseconds=1))

    envelope = DeviceCommandEnvelope(
        command_id=cp_command.command_id,
        run_id=cp_command.run_id,
        tool_request_ref=cp_command.tool_request_ref,
        binding_ref=cp_command.binding_ref,
        sequence=cp_command.sequence,
        issued_at=cp_command.issued_at,
        expires_at=cp_command.expires_at,
        revision_ref=cp_command.revision_ref,
    )

    wire = build_command_material_wire_projection(
        command=envelope,
        request=local_request,
        request_fingerprint=fingerprint,
    )
    material_resolver = _MaterialResolver(wire)
    references = _References()

    from padiem_control_plane.local_agent_broker_rpc import LocalAgentBrokerRpcFacade

    handler = AdmissionEnabledLocalAgentBrokerHttpHandler(
        rpc=LocalAgentBrokerRpcFacade(authority=authority),
        state=durable,
        material_resolver=material_resolver,
        clock=server_clock,
        admission_reference_factory=references,
    )
    request_port = _HandlerBackedRequestPort(handler=handler, auth=auth, clock=server_clock, fail_network=fail_network)
    credential_store = _MockCredentialStore(CREDENTIAL, expire=credential_expired, missing=credential_missing)

    transport = ControlPlanePhysicalAdmissionTransport(
        credential_store=credential_store,
        expected_admission_authority_ref=AUTHORITY_REF,
        request_port=request_port,
    )

    client_binding = DeviceBinding(
        binding_ref="bind_host_1",
        device_id="dev_host_1",
        account_ref="acc_host_1",
        workspace_ref="ws_host_1",
        credential_generation=1,
        credential_ref="cred_host_1",
        credential_expires_at=BASE + timedelta(days=30),
        issued_at=BASE,
        state=binding_state,
    )

    broker_binding = PinnedOutboundBrokerBinding.from_binding(
        binding=client_binding,
        config=_config(),
    )

    channel = ControlPlanePhysicalAdmissionChannel(
        authority=broker_binding,
        transport=transport,
    )

    device = LocalAgentDeviceProfile(
        device_id="dev_host_1",
        workspace_ref="ws_host_1",
        platform=LocalAgentPlatform.WINDOWS,
        roots=(root,),
    )
    permissions = default_device_permission_profile(device=device)
    if blocking_runtime:
        runtime = _BlockingReceiptRuntime()
    elif transport_failure_runtime:
        runtime = _TransportFailureRuntime()
    else:
        runtime = _ReceiptRuntime(fail=fail_runtime)

    assembly = BoundLocalAgentRuntimeAssembly(
        device=device,
        binding=client_binding,
        permissions=permissions,
        broker_authority=broker_binding,
        runtime=runtime,
    )

    clock = _SimulatedClock(BASE + timedelta(seconds=6))
    host = LocalAgentResidentRuntimeHost(
        assembly=assembly,
        channel=channel,
        credential_store=credential_store,
        clock=clock,
        session_id_factory=lambda: "session_host_cross_1",
    )
    return host, runtime, request_port, clock


class LocalAgentResidentRuntimeHostTests(unittest.TestCase):
    def setUp(self) -> None:
        InMemorySingleInstanceLock.reset()

    def tearDown(self) -> None:
        InMemorySingleInstanceLock.reset()

    def test_invariants_and_truth_flags(self) -> None:
        self.assertTrue(WINDOWS_RESIDENT_HOST_CONTRACT)
        self.assertTrue(WINDOWS_RESIDENT_HOST_IMPLEMENTATION)
        self.assertTrue(USER_LEVEL_DEFAULT)
        self.assertTrue(SINGLE_INSTANCE)
        self.assertTrue(OUTBOUND_ONLY)
        self.assertTrue(BOUNDED_RECONNECT)
        self.assertTrue(CANCELLATION_AWARE)
        self.assertTrue(CANONICAL_SESSION_REUSED)
        self.assertTrue(CANONICAL_COMMAND_ENVELOPE_REUSED)
        self.assertTrue(CANONICAL_WINDOWS_EXECUTOR_REUSED)
        self.assertTrue(CANONICAL_P01_APPROVAL_REUSED)
        self.assertTrue(CANONICAL_PERMISSION_AUTHORITY_REUSED)
        self.assertTrue(CANONICAL_CREDENTIAL_STORE_REUSED)
        self.assertFalse(RAW_DEVICE_SECRET_IN_LOG)
        self.assertFalse(ARBITRARY_BROKER_DESTINATION)
        self.assertFalse(REAL_WINDOWS_SERVICE_INSTALL)
        self.assertFalse(REAL_USER_PAIRING_CANARY)
        self.assertFalse(PRODUCTION_REMOTE_CONTROL_CLAIM)
        self.assertFalse(PRODUCTION_MUTATION)
        self.assertFalse(PRODUCTION_READY)

    def test_normal_startup_heartbeat_poll_dispatch_clean_shutdown(self) -> None:
        host, runtime, port, clock = _harness()
        self.assertEqual(host.state, ResidentHostState.STOPPED)

        # 1. Start host -> CONNECTING -> ONLINE
        host.start()
        self.assertEqual(host.state, ResidentHostState.ONLINE)

        # Verify initial status projection
        status = host.status()
        self.assertEqual(status.state, ResidentHostState.ONLINE)
        self.assertEqual(status.device_id, "dev_host_1")
        self.assertEqual(status.workspace_ref, "ws_host_1")
        self.assertEqual(status.binding_ref, "bind_host_1")
        self.assertEqual(status.session_id, "session_host_cross_1")
        self.assertIsNotNone(status.last_heartbeat_at)
        self.assertIsNotNone(status.last_seen_at)

        # Verify safe_dict contains zero raw credentials
        safe = status.safe_dict()
        self.assertFalse(safe["raw_device_credential"])
        self.assertFalse(safe["authorization_header"])
        self.assertFalse(safe["raw_argv"])
        self.assertFalse(safe["raw_payload"])

        # 2. Run one cycle -> Polls, resolves material, admits, executes in Windows executor, acknowledges
        clock.advance(5)
        executed = host.run_once(now=clock.now)
        self.assertEqual(executed, 1)
        self.assertEqual(runtime.executed, ["req_host_1"])

        # Verify post-execution calls
        operation_names = [call[0] for call in port.calls]
        self.assertIn("session", operation_names)
        self.assertIn("heartbeat", operation_names)
        self.assertIn("poll", operation_names)
        self.assertIn("material", operation_names)
        self.assertIn("admission", operation_names)
        self.assertIn("acknowledge", operation_names)

        # 3. Clean shutdown
        host.stop()
        self.assertEqual(host.state, ResidentHostState.STOPPED)
        self.assertFalse(host._lock_acquired)

    def test_single_instance_duplicate_start_fails_closed(self) -> None:
        host1, _, _, _ = _harness()
        host2, _, _, _ = _harness()

        host1.start()
        self.assertEqual(host1.state, ResidentHostState.ONLINE)

        # Second instance for same device fails closed immediately
        with self.assertRaises(ContractError) as ctx:
            host2.start()
        self.assertIn("duplicate Local Agent instance", str(ctx.exception))
        self.assertEqual(host2.state, ResidentHostState.FAILED)

        # After host1 stops, host2 can start cleanly
        host1.stop()
        self.assertEqual(host1.state, ResidentHostState.STOPPED)

        host2.start()
        self.assertEqual(host2.state, ResidentHostState.ONLINE)
        host2.stop()

    def test_missing_credential_fails_closed(self) -> None:
        host, _, _, _ = _harness(credential_missing=True)
        with self.assertRaises(ContractError) as ctx:
            host.start()
        self.assertIn("not found", str(ctx.exception))
        self.assertEqual(host.state, ResidentHostState.FAILED)

    def test_expired_credential_transitions_to_credential_expired(self) -> None:
        host, _, _, _ = _harness(credential_expired=True)
        with self.assertRaises(ContractError) as ctx:
            host.start()
        self.assertIn("expired", str(ctx.exception))
        self.assertEqual(host.state, ResidentHostState.CREDENTIAL_EXPIRED)

    def test_revoked_binding_transitions_to_revoked(self) -> None:
        host, _, _, _ = _harness(binding_state=DeviceLifecycle.REVOKED)
        with self.assertRaises(ContractError) as ctx:
            host.start()
        self.assertIn("revoked", str(ctx.exception))
        self.assertEqual(host.state, ResidentHostState.REVOKED)

    def test_update_required_binding_fails_closed(self) -> None:
        host, _, _, _ = _harness(binding_state=DeviceLifecycle.UPDATE_REQUIRED)
        with self.assertRaises(ContractError) as ctx:
            host.start()
        self.assertIn("update", str(ctx.exception))
        self.assertEqual(host.state, ResidentHostState.UPDATE_REQUIRED)
        self.assertTrue(host.status().update_required)

    def test_broker_unavailable_enters_offline_and_reconnects(self) -> None:
        host, _, port, clock = _harness(fail_network=True)
        with self.assertRaises(ConnectionError):
            host.start()
        self.assertEqual(host.state, ResidentHostState.OFFLINE)
        self.assertEqual(host.status().consecutive_failures, 1)

        # Reconnect fails while network is down
        clock.advance(2)
        success = host.reconnect(now=clock.now)
        self.assertFalse(success)
        self.assertEqual(host.state, ResidentHostState.OFFLINE)
        self.assertGreater(host.status().consecutive_failures, 1)

        # Network recovers -> reconnect succeeds
        port.fail_network = False
        clock.advance(5)
        success = host.reconnect(now=clock.now)
        self.assertTrue(success)
        self.assertEqual(host.state, ResidentHostState.ONLINE)
        self.assertEqual(host.status().consecutive_failures, 0)
        host.stop()

    def test_reconnect_cancellation_aware(self) -> None:
        host, _, _, _ = _harness(fail_network=True)
        with self.assertRaises(ConnectionError):
            host.start()
        self.assertEqual(host.state, ResidentHostState.OFFLINE)

        # When stopped during offline state, host terminates cleanly and releases lock
        host.stop()
        self.assertEqual(host.state, ResidentHostState.STOPPED)
        self.assertFalse(host._lock_acquired)

    def test_active_execution_cancellation_during_shutdown(self) -> None:
        host, runtime, _, _ = _harness()
        host.start()

        # Simulate active command in progress: set both the host-level tracking
        # AND the assembly's ownership map so assembly.cancel() ownership check passes.
        host._active_command_id = "cmd_active_1"
        host._active_request_id = "req_host_1"
        host._active_session = host._session
        host._assembly._active_owners["req_host_1"] = host._session.session_id

        host.stop()
        self.assertEqual(host.state, ResidentHostState.STOPPED)
        # Verify cancellation was dispatched to runtime
        self.assertIn("req_host_1", runtime.cancelled)

    def test_shutdown_cancels_real_active_execution(self) -> None:
        host, runtime, _, _ = _harness(blocking_runtime=True)
        host.start()
        errors: list[Exception] = []

        def run_cycle() -> None:
            try:
                host.run_once()
            except Exception as exc:
                errors.append(exc)

        worker = threading.Thread(target=run_cycle)
        worker.start()
        self.assertTrue(runtime.started.wait(timeout=1))
        host.stop()
        worker.join(timeout=1)
        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])
        self.assertIn("req_host_1", runtime.cancelled)
        self.assertEqual(host.state, ResidentHostState.STOPPED)

    def test_execution_transport_failure_moves_host_offline(self) -> None:
        host, _, _, _ = _harness(transport_failure_runtime=True)
        host.start()
        with self.assertRaises(ConnectionError):
            host.run_once()
        self.assertEqual(host.state, ResidentHostState.OFFLINE)
        host.stop()

    def test_arbitrary_broker_destination_rejected_at_init(self) -> None:
        credential_store = _MockCredentialStore()
        transport = ControlPlanePhysicalAdmissionTransport(
            credential_store=credential_store,
            expected_admission_authority_ref=AUTHORITY_REF,
            request_port=None,
        )

        client_binding = DeviceBinding(
            binding_ref="bind_host_1",
            device_id="dev_host_1",
            account_ref="acc_host_1",
            workspace_ref="ws_host_1",
            credential_generation=1,
            credential_ref="cred_host_1",
            credential_expires_at=BASE + timedelta(days=30),
            issued_at=BASE,
            state=DeviceLifecycle.ONLINE,
        )
        broker_binding = PinnedOutboundBrokerBinding.from_binding(
            binding=client_binding,
            config=_config(),
        )

        # Mismatch device in authority
        mismatch_binding = PinnedOutboundBrokerBinding(
            binding_ref="bind_host_1",
            device_id="dev_attacker_2",
            account_ref="acc_host_1",
            workspace_ref="ws_host_1",
            credential_generation=1,
            credential_ref_fingerprint="0" * 64,
            config=_config(),
        )
        mismatch_channel = ControlPlanePhysicalAdmissionChannel(
            authority=mismatch_binding,
            transport=transport,
        )

        device = LocalAgentDeviceProfile(
            device_id="dev_host_1",
            workspace_ref="ws_host_1",
            platform=LocalAgentPlatform.WINDOWS,
            roots=(LocalRoot(root_ref="root_repo", windows_path="C:\\padiem\\repo"),),
        )
        assembly = BoundLocalAgentRuntimeAssembly(
            device=device,
            binding=client_binding,
            permissions=default_device_permission_profile(device=device),
            broker_authority=broker_binding,
            runtime=_ReceiptRuntime(),
        )

        with self.assertRaises(ContractError) as ctx:
            LocalAgentResidentRuntimeHost(
                assembly=assembly,
                channel=mismatch_channel,
                credential_store=credential_store,
            )
        self.assertIn("channel device does not match assembly device", str(ctx.exception))

    def test_channel_authority_must_match_pinned_configuration(self) -> None:
        host, _, _, _ = _harness()
        alternate_config = OutboundTransportConfig(
            endpoint=OutboundBrokerEndpoint(
                endpoint_ref="broker_endpoint_resident_host_alt",
                url="https://alternate-broker.padiem.net:443/broker",
                mode=OutboundTransportMode.HTTPS_LONG_POLL,
            ),
            heartbeat_seconds=30,
            poll_timeout_seconds=15,
            max_response_bytes=65536,
            tls_required=True,
            public_inbound_port=False,
        )
        alternate_authority = PinnedOutboundBrokerBinding.from_binding(
            binding=host._assembly._binding,
            config=alternate_config,
        )
        alternate_channel = ControlPlanePhysicalAdmissionChannel(
            authority=alternate_authority,
            transport=host._channel._transport,
        )
        with self.assertRaises(ContractError) as ctx:
            LocalAgentResidentRuntimeHost(
                assembly=host._assembly,
                channel=alternate_channel,
                credential_store=_MockCredentialStore(),
            )
        self.assertIn("broker configuration", str(ctx.exception))

    def test_status_redacts_and_bounds_error_message(self) -> None:
        host, _, _, _ = _harness()
        host.start()
        secret = "secret_token_12345678901234567890"
        host._handle_transport_error(ConnectionError(f"Authorization: Bearer {secret}"))
        safe = host.status().safe_dict()
        self.assertNotIn(secret, safe["error_message"])
        self.assertLessEqual(len(safe["error_message"]), 1024)
        host.stop()

    def test_diagnostics_secrets_redaction(self) -> None:
        host, _, _, _ = _harness()
        host.start()
        # Diagnostic message with sensitive string is redacted
        host._record_diagnostic("auth", "TEST_EVENT", "Bearer secret_token_12345678901234567890")
        diag = host.diagnostics()
        last = diag[-1]
        self.assertNotIn("secret_token_12345678901234567890", last.message)
        safe = last.safe_dict()
        self.assertFalse(safe["raw_device_credential"])
        self.assertFalse(safe["authorization_header"])
        host.stop()


if __name__ == "__main__":
    unittest.main()
