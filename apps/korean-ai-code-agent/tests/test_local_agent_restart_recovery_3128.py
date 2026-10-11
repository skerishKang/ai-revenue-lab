"""#3128 — the execute→ack crash window, driven through the real paths.

Every scenario here runs the deployed composition, not a stub of the transition
under test:

* the canonical `StateBackedLocalAgentBrokerAuthority` over its serialized wire
  state, addressed through the real device HTTP boundary;
* the real pinned-HTTPS transport and admission channel, including the real
  #3128 `/reconcile` recovery route;
* the real `ControlPlaneAdmittedExecutionCoordinator` with a real SQLite
  `DurableRunStore` on disk, so a "restart" is genuinely a second process
  opening the same file;
* the real `LocalAgentRestartRecoveryDriver`.

A crash is injected by dropping the acknowledgement at the wire: either before
the request reaches the broker, or after the broker committed and the response
was lost. Nothing here re-executes, re-enqueues or mints correlation.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any, ClassVar

from kagent.local_agent import (
    LocalAgentDeviceProfile,
    LocalAgentPlatform,
    LocalCommandRequest,
    LocalCommandResult,
    LocalRoot,
)
from kagent.local_agent_command_material import build_command_material_wire_projection
from kagent.local_agent_control_plane_admission import (
    ControlPlaneAdmittedExecutionCoordinator,
    ControlPlanePhysicalAdmissionChannel,
    ControlPlanePhysicalAdmissionTransport,
)
from kagent.local_agent_durable_run_store import DurableRunRecoveryClass, DurableRunStore
from kagent.local_agent_pairing import DeviceBinding, DeviceCommandEnvelope, DeviceLifecycle
from kagent.local_agent_permissions import default_device_permission_profile
from kagent.local_agent_restart_recovery import LocalAgentRestartRecoveryDriver
from kagent.local_agent_runtime_assembly import BoundLocalAgentRuntimeAssembly
from kagent.local_agent_runtime_host import LocalAgentResidentRuntimeHost, ResidentHostState
from kagent.local_agent_server_projection import project_server_backed_online_binding
from kagent.local_agent_secure_channel import PinnedOutboundBrokerBinding
from kagent.local_agent_secure_transport import (
    DeviceCredentialStore,
    OutboundBrokerEndpoint,
    OutboundTransportConfig,
    OutboundTransportMode,
    ProtectedFileDeviceCredentialStore,
)
from kagent.windows_local_executor import (
    WindowsExecutionReceipt,
    WindowsExecutionTermination,
    command_request_fingerprint,
)
from padiem_control_plane.local_agent_broker_admission_http import (
    AdmissionEnabledLocalAgentBrokerHttpHandler,
)
from padiem_control_plane.local_agent_broker_http import (
    DurableLocalAgentSessionRecord,
    LocalAgentBrokerHttpResponse,
    TrustedLocalAgentHttpAuthContext,
)
from padiem_control_plane.local_agent_broker_rpc import LocalAgentBrokerRpcFacade
from padiem_control_plane.local_agent_broker_state import StateBackedLocalAgentBrokerAuthority
from padiem_control_plane.local_agent_broker_state_wire import (
    InMemorySerializedLocalAgentBrokerStateBackend,
    SerializedLocalAgentBrokerStatePort,
)

BASE = datetime(2026, 9, 27, 3, 0, tzinfo=timezone.utc)
PEPPER = b"control-plane-broker-pepper-16bytes!!"
CREDENTIAL = b"3128-runner-device-credential"
AUTHORITY_REF = "control-plane.local-agent-broker.3128.v1"
DEVICE_ID = "device.3128.1"
BINDING_REF = "binding.3128.1"
ACCOUNT_REF = "account.3128.1"
WORKSPACE_REF = "workspace.3128.1"
COMMAND_TTL_SECONDS = 300
SERVER_ROUTE_OFFSET: ClassVar[dict[str, int]] = {
    "session": 5,
    "heartbeat": 10,
    "poll": 15,
    "material": 20,
    "admission": 25,
    "acknowledge": 30,
    "reconcile": 35,
}


class _ServerClock:
    def __init__(self) -> None:
        self.now = BASE

    def __call__(self) -> datetime:
        return self.now


class _ClientClock:
    def __init__(self) -> None:
        self.now = BASE + timedelta(seconds=5)

    def __call__(self) -> datetime:
        return self.now


class _DeterministicProtectedDataPort:
    """Reversible test adapter only, never live DPAPI."""

    prefix = b"FAKE-PROTECTED-v1:"

    def protect(self, plaintext: bytes, *, entropy: bytes) -> bytes:
        mask = hashlib.sha256(entropy).digest()
        return self.prefix + bytes(value ^ mask[index % len(mask)] for index, value in enumerate(plaintext))

    def unprotect(self, ciphertext: bytes, *, entropy: bytes) -> bytes:
        assert ciphertext.startswith(self.prefix)
        mask = hashlib.sha256(entropy).digest()
        body = ciphertext[len(self.prefix) :]
        return bytes(value ^ mask[index % len(mask)] for index, value in enumerate(body))


class _FileCredentialStore(DeviceCredentialStore):
    def __init__(self, *, base_dir: str) -> None:
        self._store = ProtectedFileDeviceCredentialStore(
            base_dir=base_dir,
            protected_data=_DeterministicProtectedDataPort(),
        )

    def save(self, *, binding, credential, now):
        return self._store.save(binding=binding, credential=credential, now=now)

    def load(self, *, binding, now):
        return self._store.load(binding=binding, now=now)

    def delete(self, binding_ref: str) -> None:
        return self._store.delete(binding_ref)


class _SessionStatePort:
    durable = True

    def __init__(self) -> None:
        self.records: dict[str, DurableLocalAgentSessionRecord] = {}

    def save_session(self, record: DurableLocalAgentSessionRecord) -> None:
        self.records[record.session_id] = record

    def load_session(self, session_id: str) -> DurableLocalAgentSessionRecord:
        return self.records[session_id]

    def record_last_seen(self, session_id: str, *, seen_at: datetime) -> DurableLocalAgentSessionRecord:
        record = self.load_session(session_id).with_last_seen(seen_at)
        self.records[session_id] = record
        return record


class _MaterialResolver:
    """Serves the exact material projection for the one queued command."""

    def __init__(self) -> None:
        self.wire: dict[str, Any] | None = None
        self.requests: list[Any] = []

    def resolve(self, request: Any) -> dict:
        self.requests.append(request)
        assert self.wire is not None
        return deepcopy(self.wire)


class _References:
    """Server-owned admission references, distinct per admission."""

    def __init__(self) -> None:
        self.count = 0

    def __call__(self) -> tuple[str, str]:
        self.count += 1
        return f"admission.3128.{self.count}", f"evidence.3128.{self.count}"


class _CrashRequestPort:
    """The device transport port, with wire-level crash injection.

    `drop_before` removes the request before the broker ever sees it (a crash
    between local execution and the acknowledgement). `drop_after` lets the
    broker commit and then discards the response (a lost acknowledgement).
    """

    def __init__(
        self,
        *,
        handler,
        auth,
        server_clock: _ServerClock,
        audit: list[str],
        drop_before: str | None = None,
        drop_after: str | None = None,
        freeze_clock: bool = False,
    ) -> None:
        self.handler = handler
        self.auth = auth
        self.server_clock = server_clock
        self.audit = audit
        self.drop_before = drop_before
        self.drop_after = drop_after
        # During restart recovery the test owns the clock: recovery has to run at
        # a moment the harness chose (after the hard deadline), so a route must
        # never rewind the server clock to its per-route offset.
        self.freeze_clock = freeze_clock
        self.dropped: list[str] = []
        self.calls: list[tuple[str, dict]] = []

    def post(self, *, config, operation, payload, timeout_seconds):
        del config, timeout_seconds
        name = operation.value
        self.calls.append((name, deepcopy(payload)))
        if name == self.drop_before:
            # The request never reached the broker, so it is not a broker call.
            self.dropped.append(name)
            raise ConnectionError(f"simulated runner death before {name}")
        self.audit.append(name)
        if self.freeze_clock:
            pass
        elif name == "heartbeat" and isinstance(payload, dict) and "now" in payload:
            # Honour the heartbeat contract exactly like every other broker
            # cross-contract test: the server clock becomes the client's `now`.
            self.server_clock.now = datetime.fromisoformat(payload["now"].replace("Z", "+00:00"))
        else:
            self.server_clock.now = BASE + timedelta(seconds=SERVER_ROUTE_OFFSET[name])
        response: LocalAgentBrokerHttpResponse = self.handler.handle(
            method="POST",
            route=f"/{name}",
            content_type="application/json",
            body=json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8"),
            auth=self.auth,
        )
        if name == self.drop_after:
            self.drop_after = None
            self.dropped.append(name)
            raise ConnectionError(f"simulated lost {name} response after the broker committed")
        return deepcopy(response.body)


class _CountingRuntime:
    """Real execution receipts, counted so recovery can be proven inert."""

    def __init__(self) -> None:
        self.executed: list[str] = []

    def execute_with_receipt(self, request: LocalCommandRequest, *, now: datetime) -> WindowsExecutionReceipt:
        self.executed.append(request.request_id)
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
            authorization_ref="windows_p01_grant_3128",
        )

    def cancel(self, request_id: str) -> None:
        raise AssertionError("recovery must never cancel a running execution")


class _IsolatedInstanceLock:
    """Per-host single-instance lock so each simulated process owns its own."""

    def __init__(self) -> None:
        self._held: str | None = None

    def acquire(self, lock_key: str) -> bool:
        if self._held is not None:
            return False
        self._held = lock_key
        return True

    def release(self, lock_key: str) -> None:
        if self._held == lock_key:
            self._held = None


def _config() -> OutboundTransportConfig:
    return OutboundTransportConfig(
        endpoint=OutboundBrokerEndpoint(
            endpoint_ref="broker_endpoint_3128",
            url="https://broker.3128.padiem.test:443/broker",
            mode=OutboundTransportMode.HTTPS_LONG_POLL,
        ),
        heartbeat_seconds=30,
        poll_timeout_seconds=15,
        max_response_bytes=65536,
        tls_required=True,
        public_inbound_port=False,
    )


def _auth() -> TrustedLocalAgentHttpAuthContext:
    return TrustedLocalAgentHttpAuthContext(
        principal_ref="principal.3128",
        account_ref=ACCOUNT_REF,
        workspace_ref=WORKSPACE_REF,
        authenticated=True,
        tls_verified=True,
    )


class _Runner:
    """One device + one broker, with an injectable crash point."""

    def __init__(self, base_dir: str) -> None:
        self.base_dir = base_dir
        self.server_clock = _ServerClock()
        self.client_clock = _ClientClock()
        self.state_port = SerializedLocalAgentBrokerStatePort(
            backend=InMemorySerializedLocalAgentBrokerStateBackend()
        )
        self.authority = StateBackedLocalAgentBrokerAuthority(
            pepper=PEPPER,
            authority_ref=AUTHORITY_REF,
            state_port=self.state_port,
        )
        self.authority.register_binding(
            binding_ref=BINDING_REF,
            device_id=DEVICE_ID,
            account_ref=ACCOUNT_REF,
            workspace_ref=WORKSPACE_REF,
            credential=CREDENTIAL,
            now=BASE,
        )
        self.session_state = _SessionStatePort()
        self.resolver = _MaterialResolver()
        self.references = _References()
        self.handler = AdmissionEnabledLocalAgentBrokerHttpHandler(
            admission_reference_factory=self.references,
            rpc=LocalAgentBrokerRpcFacade(authority=self.authority),
            state=self.session_state,
            material_resolver=self.resolver,
            clock=self.server_clock,
        )
        self.credentials = _FileCredentialStore(base_dir=base_dir)
        # The state-backed authority keeps its own cache empty, so the canonical
        # registered binding is read back from the persisted snapshot.
        registered = self.state_port.load(authority_ref=AUTHORITY_REF).snapshot.bindings[0]
        self.online = None
        self.binding = DeviceBinding(
            device_id=registered.device_id,
            binding_ref=registered.binding_ref,
            account_ref=registered.account_ref,
            workspace_ref=registered.workspace_ref,
            credential_ref="credential_ref_3128",
            credential_generation=registered.credential_generation,
            issued_at=registered.issued_at,
            credential_expires_at=registered.credential_expires_at,
            state=DeviceLifecycle.PAIRED_OFFLINE,
        )
        self.credentials.save(binding=self.binding, credential=CREDENTIAL, now=BASE)
        self.broker_binding = PinnedOutboundBrokerBinding.from_binding(
            binding=self.binding, config=_config()
        )
        self.runtime = _CountingRuntime()
        self.store_path = str(Path(base_dir) / "durable_runs.sqlite3")
        self.store = DurableRunStore(self.store_path)
        self.audit: list[str] = []

    # --- device composition -------------------------------------------------
    def channel(self, *, drop_before=None, drop_after=None, freeze_clock=False) -> ControlPlanePhysicalAdmissionChannel:
        port = _CrashRequestPort(
            handler=self.handler,
            auth=_auth(),
            server_clock=self.server_clock,
            audit=self.audit,
            drop_before=drop_before,
            drop_after=drop_after,
            freeze_clock=freeze_clock,
        )
        transport = ControlPlanePhysicalAdmissionTransport(
            credential_store=self.credentials,
            expected_admission_authority_ref=AUTHORITY_REF,
            request_port=port,
        )
        return ControlPlanePhysicalAdmissionChannel(authority=self.broker_binding, transport=transport)

    def connect(self, channel, *, session_id: str) -> tuple[Any, DeviceBinding]:
        """The real bring-up: broker session, heartbeat, ONLINE projection.

        A restarted Desktop repeats exactly this. It never resurrects an old
        session id; it opens a new one and rebuilds the projection from the
        server heartbeat.
        """

        session = channel.open_session(
            binding=self.binding,
            session_id=session_id,
            now=self.client_clock.now,
            ttl_seconds=900,
        )
        heartbeat = channel.heartbeat(
            binding=self.binding, session=session, now=self.client_clock.now
        )
        online = project_server_backed_online_binding(
            binding=self.binding,
            session=session,
            heartbeat=heartbeat,
            now=self.client_clock.now,
        )
        self.online = online
        return session, online

    def host(self, channel, *, binding, session_id: str) -> LocalAgentResidentRuntimeHost:
        device = LocalAgentDeviceProfile(
            device_id=DEVICE_ID,
            workspace_ref=WORKSPACE_REF,
            platform=LocalAgentPlatform.WINDOWS,
            roots=(LocalRoot(root_ref="root_repo", windows_path="C:\\padiem\\repo"),),
        )
        assembly = BoundLocalAgentRuntimeAssembly(
            device=device,
            binding=binding,
            permissions=default_device_permission_profile(device=device),
            broker_authority=self.broker_binding,
            runtime=self.runtime,
        )
        return LocalAgentResidentRuntimeHost(
            assembly=assembly,
            channel=channel,
            credential_store=self.credentials,
            durable_store=self.store,
            clock=self.client_clock,
            instance_lock=_IsolatedInstanceLock(),
            session_id_factory=lambda: session_id,
            heartbeat_interval_seconds=30,
            session_ttl_seconds=900,
        )

    # --- one command --------------------------------------------------------
    def enqueue(self, *, command_id: str = "command.3128.1") -> Any:
        request = LocalCommandRequest(
            request_id=f"req.{command_id}",
            run_id="run.3128.1",
            device_id=DEVICE_ID,
            root_ref="root_repo",
            argv=("python", "--version"),
            cwd_relative=".",
            requested_at=self.server_clock.now,
            timeout_seconds=30,
        )
        fingerprint = command_request_fingerprint(request)
        queued = self.authority.enqueue_command(
            command_id=command_id,
            binding_ref=BINDING_REF,
            run_id=request.run_id,
            tool_request_ref=f"tool.{command_id}",
            request_fingerprint=fingerprint,
            now=self.server_clock.now,
            ttl_seconds=COMMAND_TTL_SECONDS,
        )
        self.resolver.wire = build_command_material_wire_projection(
            command=DeviceCommandEnvelope(
                command_id=queued.command_id,
                run_id=queued.run_id,
                tool_request_ref=queued.tool_request_ref,
                binding_ref=queued.binding_ref,
                sequence=queued.sequence,
                issued_at=queued.issued_at,
                expires_at=queued.expires_at,
                revision_ref=queued.revision_ref,
            ),
            request=request,
            request_fingerprint=fingerprint,
        )
        return queued

    # --- restart ------------------------------------------------------------
    def broker_command(self, command_id: str) -> Any:
        """Read the canonical broker state from its durable snapshot."""

        commands = self.state_port.load(authority_ref=AUTHORITY_REF).snapshot.commands
        return next(item for item in commands if item.command_id == command_id)

    def restart(self) -> None:
        """Close every process-local object and reopen the durable store."""

        self.store.close()
        self.store = DurableRunStore(self.store_path)

    def driver(self, channel, *, binding) -> LocalAgentRestartRecoveryDriver:
        return LocalAgentRestartRecoveryDriver(
            store=self.store,
            channel=channel,
            binding=binding,
        )


class LocalAgentRestartRecoveryCrossContractTests(unittest.TestCase):
    """The #3128 acceptance scenarios, each on the real composition."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.runner = _Runner(os.path.abspath(self._tmp.name))
        # Close whichever durable store the last simulated process left open, so
        # the temporary directory can be removed on every platform.
        self.addCleanup(self._close_runner)

    def _close_runner(self) -> None:
        try:
            self.runner.store.close()
        except Exception:  # noqa: BLE001 - teardown only
            pass

    def _run_cycle(self, *, drop_before=None, drop_after=None, session_id="session.3128.host"):
        """Execute one full poll -> admit -> execute -> acknowledge cycle."""

        channel = self.runner.channel(drop_before=drop_before, drop_after=drop_after)
        # The harness brings the projection up on its own bootstrap session; the
        # host then opens the session it will actually dispatch from.
        _session, online = self.runner.connect(channel, session_id=session_id + ".bootstrap")
        host = self.runner.host(channel, binding=online, session_id=session_id)
        host.start()
        self.assertEqual(host.state, ResidentHostState.ONLINE)
        return host, channel, online

    def _restart(self, *, session_id: str, at_seconds: int = 60):
        """Simulate a restarted Desktop: same durable file, new session."""

        self.runner.restart()
        self.runner.client_clock.now = BASE + timedelta(seconds=at_seconds)
        self.runner.server_clock.now = self.runner.client_clock.now
        channel = self.runner.channel(freeze_clock=True)
        session, online = self.runner.connect(channel, session_id=session_id)
        return channel, session, online

    # 1) crash after the execute call, before the acknowledgement
    def test_crash_after_execute_before_ack_leaves_terminal_durable_and_unacked(self) -> None:
        queued = self.runner.enqueue()
        host, _channel, _online = self._run_cycle(drop_before="acknowledge")

        with self.assertRaises(ConnectionError):
            host.run_once()

        record = self.runner.store.get(command_id=queued.command_id)
        self.assertIsNotNone(record, "the terminal result must be durable before the ack is sent")
        self.assertEqual(record.state.value, "terminal")
        self.assertEqual(record.termination.value, "exited")
        self.assertEqual(record.exit_code, 0)
        self.assertIsNotNone(record.admission_ref)
        self.assertIsNotNone(record.admission_evidence_ref)
        self.assertIsNone(record.server_acknowledged_at)
        self.assertEqual(
            self.runner.store.classify(record, now=self.runner.client_clock.now),
            DurableRunRecoveryClass.TERMINAL_SERVER_UNACKED,
        )
        # The broker was never told: the command is still admitted, not acknowledged.
        self.assertEqual(self.runner.broker_command(queued.command_id).state.value, "admitted")
        self.assertEqual(self.runner.runtime.executed, [f"req.{queued.command_id}"])
        self.assertNotIn("acknowledge", self.runner.audit)

    # 2) the broker committed the ack, the response was lost
    def test_lost_ack_response_is_recovered_after_restart_without_reexecution(self) -> None:
        queued = self.runner.enqueue()
        host, _channel, _online = self._run_cycle(drop_after="acknowledge")

        with self.assertRaises(ConnectionError):
            host.run_once()
        self.assertIn("acknowledge", self.runner.audit)
        self.assertEqual(self.runner.broker_command(queued.command_id).state.value, "acknowledged")
        record = self.runner.store.get(command_id=queued.command_id)
        self.assertIsNone(record.server_acknowledged_at, "the server fact is unknown to the device")

        # Restart: a brand new process, a brand new session, the same durable file.
        channel, session, online = self._restart(session_id="session.3128.restarted")
        report = self.runner.driver(channel, binding=online).recover_once(
            session=session, now=self.runner.client_clock.now
        )

        self.assertEqual(report.settled_command_ids, (queued.command_id,))
        self.assertEqual(report.refusals, ())
        self.assertEqual(report.executor_calls, 0)
        self.assertEqual(report.reexecution, False)
        self.assertEqual(report.replay_candidates, ())
        settled = self.runner.store.get(command_id=queued.command_id)
        self.assertEqual(settled.state.value, "terminal")
        # The same bounded result the execution produced is preserved, not
        # re-derived: recovery re-reads it, it never re-computes or invents one.
        self.assertEqual(settled.termination.value, "exited")
        self.assertEqual(settled.exit_code, 0)
        self.assertIsNotNone(settled.server_acknowledged_at)
        self.assertEqual(
            self.runner.store.classify(settled, now=self.runner.client_clock.now),
            DurableRunRecoveryClass.TERMINAL,
        )
        self.assertEqual(self.runner.runtime.executed, [f"req.{queued.command_id}"])
        self.assertEqual(self.runner.broker_command(queued.command_id).state.value, "acknowledged")

    # 3) restart with a fresh session before the hard deadline
    def test_restart_with_fresh_session_before_deadline_never_reexecutes(self) -> None:
        queued = self.runner.enqueue()
        host, _channel, _online = self._run_cycle(drop_before="acknowledge")
        with self.assertRaises(ConnectionError):
            host.run_once()

        channel, session, online = self._restart(session_id="session.3128.fresh")
        report = self.runner.driver(channel, binding=online).recover_once(
            session=session, now=self.runner.client_clock.now
        )

        # The ADMITTED acknowledgement path still requires the admitting session,
        # so the honest outcome is a bounded refusal, never a guess and never a
        # re-execution. The record stays durable for the post-deadline exit.
        self.assertEqual(report.settled_command_ids, ())
        self.assertEqual(report.pending_command_ids, (queued.command_id,))
        self.assertEqual(len(report.refusals), 1)
        self.assertEqual(report.executor_calls, 0)
        self.assertEqual(self.runner.runtime.executed, [f"req.{queued.command_id}"])
        self.assertEqual(self.runner.broker_command(queued.command_id).state.value, "admitted")
        pending = self.runner.store.get(command_id=queued.command_id)
        self.assertEqual(pending.state.value, "terminal")
        self.assertIsNone(pending.server_acknowledged_at)

    # 4) restart after the hard deadline uses the #3121 reconciliation
    def test_restart_after_deadline_reconciles_expired_admitted_without_replay(self) -> None:
        queued = self.runner.enqueue()
        host, _channel, _online = self._run_cycle(drop_before="acknowledge")
        with self.assertRaises(ConnectionError):
            host.run_once()
        self.assertEqual(self.runner.broker_command(queued.command_id).state.value, "admitted")

        self.runner.restart()
        self.runner.client_clock.now = queued.expires_at + timedelta(seconds=5)
        self.runner.server_clock.now = self.runner.client_clock.now
        channel = self.runner.channel(freeze_clock=True)
        session, online = self.runner.connect(channel, session_id="session.3128.deadline")
        report = self.runner.driver(channel, binding=online).recover_once(
            session=session, now=self.runner.client_clock.now
        )

        self.assertEqual(report.refusals, ())
        self.assertEqual(report.settled_command_ids, (queued.command_id,))
        self.assertIn("reconcile", self.runner.audit)
        # The proven local outcome reached the broker; the command is terminal and
        # the same bounded result is preserved end to end.
        reconciled = self.runner.broker_command(queued.command_id)
        self.assertEqual(reconciled.state.value, "acknowledged")
        self.assertEqual(reconciled.termination, "exited")
        self.assertEqual(reconciled.exit_code, 0)
        self.assertEqual(reconciled.request_id, f"req.{queued.command_id}")
        record = self.runner.store.get(command_id=queued.command_id)
        self.assertIsNotNone(record.server_acknowledged_at)
        self.assertEqual(record.exit_code, reconciled.exit_code)
        self.assertEqual(record.termination.value, reconciled.termination)
        self.assertEqual(self.runner.runtime.executed, [f"req.{queued.command_id}"])

    # 5) an already terminal restart is inert
    def test_already_terminal_restart_is_idempotent_and_silent(self) -> None:
        queued = self.runner.enqueue()
        host, _channel, _online = self._run_cycle(drop_after="acknowledge")
        with self.assertRaises(ConnectionError):
            host.run_once()
        channel, session, online = self._restart(session_id="session.3128.second")
        first = self.runner.driver(channel, binding=online).recover_once(
            session=session, now=self.runner.client_clock.now
        )
        settled = self.runner.store.get(command_id=queued.command_id)

        channel2, session2, online2 = self._restart(session_id="session.3128.third", at_seconds=120)
        second = self.runner.driver(channel2, binding=online2).recover_once(
            session=session2, now=self.runner.client_clock.now
        )

        self.assertEqual(first.settled_command_ids, (queued.command_id,))
        self.assertEqual(second.settled_command_ids, ())
        self.assertEqual(second.pending_command_ids, ())
        self.assertEqual(second.refusals, ())
        self.assertEqual(second.executor_calls, 0)
        self.assertEqual(self.runner.store.get(command_id=queued.command_id), settled)
        self.assertEqual(self.runner.runtime.executed, [f"req.{queued.command_id}"])

    # 6) recovery itself never reaches the executor
    def test_recovery_never_calls_the_executor_and_never_claims_replay(self) -> None:
        queued = self.runner.enqueue()
        host, _channel, _online = self._run_cycle(drop_before="acknowledge")
        with self.assertRaises(ConnectionError):
            host.run_once()
        executions = list(self.runner.runtime.executed)

        self.runner.restart()
        self.runner.client_clock.now = queued.expires_at + timedelta(seconds=5)
        self.runner.server_clock.now = self.runner.client_clock.now
        channel = self.runner.channel(freeze_clock=True)
        session, online = self.runner.connect(channel, session_id="session.3128.inert")
        report = self.runner.driver(channel, binding=online).recover_once(
            session=session, now=self.runner.client_clock.now
        )

        self.assertEqual(self.runner.runtime.executed, executions)
        self.assertEqual(report.executor_calls, 0)
        self.assertIs(report.reexecution, False)
        self.assertEqual(report.replay_candidates, ())
        self.assertEqual(self.runner.store.recover(now=self.runner.client_clock.now).replay_candidates, ())
        safe = self.runner.driver(channel, binding=online).safe_dict()
        self.assertIs(safe["executor_reference_held"], False)
        self.assertIs(safe["replay_engine"], False)
        self.assertIs(safe["old_session_resurrection"], False)

    # 7) an unprovable outcome reconciles fail-closed to EXPIRED, not a guess
    def test_non_terminal_record_reconciles_to_expired_without_inventing_a_result(self) -> None:
        queued = self.runner.enqueue()
        channel = self.runner.channel()
        session, _online = self.runner.connect(channel, session_id="session.3128.admitted")

        # A real canonical admission with no local execution fact at all: the
        # runner is gone before anything ran.
        # The canonical authority itself: this is exactly what the admission
        # route and the RPC facade delegate to.
        admission = self.runner.authority.admit_command(
            admission_ref="admission.3128.unknown",
            evidence_ref="evidence.3128.unknown",
            session_id=session.session_id,
            binding_ref=BINDING_REF,
            credential=CREDENTIAL,
            command_id=queued.command_id,
            request_fingerprint=queued.request_fingerprint,
            request_id=f"req.{queued.command_id}",
            now=self.runner.server_clock.now,
        )
        self.assertEqual(admission.admission_ref, "admission.3128.unknown")
        self.runner.store.put(self._admitted_only_record(queued, admission))

        self.runner.restart()
        self.runner.client_clock.now = queued.expires_at + timedelta(seconds=5)
        self.runner.server_clock.now = self.runner.client_clock.now
        recovery_channel = self.runner.channel(freeze_clock=True)
        recovered, online = self.runner.connect(recovery_channel, session_id="session.3128.unknown")
        report = self.runner.driver(recovery_channel, binding=online).recover_once(
            session=recovered, now=self.runner.client_clock.now
        )

        self.assertEqual(report.refusals, ())
        self.assertEqual(report.settled_command_ids, (queued.command_id,))
        reconciled = self.runner.broker_command(queued.command_id)
        self.assertEqual(reconciled.state.value, "expired")
        self.assertIsNone(reconciled.termination)
        self.assertIsNone(reconciled.exit_code)
        self.assertEqual(self.runner.runtime.executed, [])
        self.assertEqual(report.executor_calls, 0)
        self.assertEqual(report.replay_candidates, ())
        settled = self.runner.store.get(command_id=queued.command_id)
        self.assertEqual(settled.state.value, "terminal")
        self.assertEqual(settled.termination.value, "expired")
        self.assertIsNone(settled.exit_code)
        self.assertIsNotNone(settled.server_acknowledged_at)

    def _admitted_only_record(self, queued: Any, admission: Any) -> Any:
        from kagent.local_agent_durable_run import DurableRunRecord

        projection = queued.safe_dict()
        return DurableRunRecord(
            command_id=projection["command_id"],
            run_id=projection["run_id"],
            tool_request_ref=projection["tool_request_ref"],
            request_id=admission.request_id,
            revision_ref=projection["revision_ref"],
            device_id=DEVICE_ID,
            binding_ref=BINDING_REF,
            session_id=admission.session_id,
            account_ref=ACCOUNT_REF,
            workspace_ref=WORKSPACE_REF,
            sequence=projection["sequence"],
            credential_generation=projection["credential_generation"],
            request_fingerprint=projection["request_fingerprint"],
            fingerprint_source="broker",
            command_issued_at=queued.issued_at,
            command_expires_at=queued.expires_at,
            admitted_at=admission.accepted_at,
            admission_ref=admission.admission_ref,
            admission_evidence_ref=admission.evidence_ref,
        )


if __name__ == "__main__":
    unittest.main()
