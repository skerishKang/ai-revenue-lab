from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from typing import Any, ClassVar
import unittest

from kagent.contracts import ContractError
from kagent.local_agent import (
    LocalAgentDeviceProfile,
    LocalAgentPlatform,
    LocalCommandRequest,
    LocalCommandResult,
    LocalRoot,
)
from kagent.local_agent_broker_pairing_client import (
    BrokerPairingHttpsOperation,
    LocalAgentBrokerPairingClient,
    PAIRING_PROOF_TRANSCRIPT,
    pairing_proof_ref,
)
from kagent.local_agent_command_material import build_command_material_wire_projection
from kagent.local_agent_control_plane_admission import (
    ControlPlanePhysicalAdmissionChannel,
    ControlPlanePhysicalAdmissionTransport,
)
from kagent.local_agent_pairing import DeviceLifecycle
from kagent.local_agent_server_projection import (
    online_binding_evidence,
    project_server_backed_online_binding,
)
from kagent.local_agent_permissions import default_device_permission_profile
from kagent.local_agent_runtime_assembly import BoundLocalAgentRuntimeAssembly
from kagent.local_agent_runtime_host import (
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
from padiem_control_plane.local_agent_broker_http import (
    DurableLocalAgentSessionRecord,
    TrustedLocalAgentHttpAuthContext,
)
from padiem_control_plane import local_agent_broker_pairing as cloud_pairing
from padiem_control_plane.local_agent_broker_pairing import InMemoryBrokerPairingAuthority
from padiem_control_plane.local_agent_broker_pairing_http import (
    PAIRING_CHALLENGE_ROUTE,
    PAIRING_REDEEM_ROUTE,
    PairingAndAdmissionLocalAgentBrokerHttpHandler,
)
from padiem_control_plane.local_agent_broker_rpc import LocalAgentBrokerRpcFacade

_PAIRING_ROUTE = "v1/broker/pairings/redeem"

BASE = datetime(2026, 9, 26, 7, 0, tzinfo=timezone.utc)
CREDENTIAL = b"cross-contract-pairing-issued-credential"
BROKER_PEPPER = b"control-plane-broker-pepper-16bytes!!"
PAIRING_PEPPER = b"control-plane-pairing-pepper16byte!!"
AUTHORITY_REF = "control-plane.local-agent-broker.pairing.e2e.v1"
ADMISSION_REF = "admission_pairing_e2e_1"
EVIDENCE_REF = "evidence_pairing_e2e_1"
PROOF_TRANSCRIPT = "claw-local-agent-pairing-proof.v1"


class _ServerClock:
    def __init__(self) -> None:
        self.now = BASE

    def __call__(self) -> datetime:
        return self.now


class _SimulatedClock:
    def __init__(self) -> None:
        self.now = BASE

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
        record = self.load_session(session_id).with_last_seen(seen_at)
        self.records[session_id] = record
        return record


class InMemoryPairingProofContractTests(unittest.TestCase):
    """The desktop and cloud pairings must speak the identical proof contract."""

    def test_proof_transcript_is_identical_on_both_sides_of_the_broker(self):
        self.assertEqual(PAIRING_PROOF_TRANSCRIPT, cloud_pairing.PAIRING_PROOF_TRANSCRIPT)
        self.assertEqual(PAIRING_PROOF_TRANSCRIPT, "claw-local-agent-pairing-proof.v1")
        self.assertEqual(PROOF_TRANSCRIPT, cloud_pairing.PAIRING_PROOF_TRANSCRIPT)
        self.assertEqual(
            cloud_pairing.pairing_proof_message(challenge_id="pairing.1", device_id="device.1"),
            b"claw-local-agent-pairing-proof.v1\npairing.1\ndevice.1",
        )

    def test_proof_derivation_agrees_byte_for_byte(self):
        for challenge_id, device_id, code in (
            ("pairing." + "a" * 32, "device.1", "0" * 32),
            ("pairing.challenge.1", "device.cli.7", "9" * 32),
            ("pairing.x", "dev.x", "f" * 32),
        ):
            self.assertEqual(
                pairing_proof_ref(challenge_id=challenge_id, device_id=device_id, pairing_code=code),
                cloud_pairing.pairing_proof_ref(
                    challenge_id=challenge_id,
                    device_id=device_id,
                    pairing_code=code,
                ),
            )

    def test_pairing_route_names_agree_with_the_cloud_handler(self):
        self.assertEqual("/" + BrokerPairingHttpsOperation.CHALLENGE.value, PAIRING_CHALLENGE_ROUTE)
        self.assertEqual("/" + BrokerPairingHttpsOperation.REDEEM.value, PAIRING_REDEEM_ROUTE)


class _DeterministicProtectedDataPort:
    """Reversible test adapter only. It is not cryptography and never represents live DPAPI."""

    prefix = b"FAKE-PROTECTED-v1:"

    def protect(self, plaintext: bytes, *, entropy: bytes) -> bytes:
        if not plaintext or not entropy:
            raise AssertionError("test adapter requires non-empty material")
        mask = hashlib.sha256(entropy).digest()
        encoded = bytes(value ^ mask[index % len(mask)] for index, value in enumerate(plaintext))
        return self.prefix + encoded

    def unprotect(self, protected: bytes, *, entropy: bytes) -> bytes:
        if not protected.startswith(self.prefix):
            raise ContractError("test protected payload is invalid")
        encoded = protected[len(self.prefix):]
        mask = hashlib.sha256(entropy).digest()
        return bytes(value ^ mask[index % len(mask)] for index, value in enumerate(encoded))


class _StoreBackedCredentialStore(DeviceCredentialStore):
    """The canonical protected-file credential store used by deployed desktops."""

    def __init__(self, *, base_dir) -> None:
        from kagent.local_agent_secure_transport import ProtectedFileDeviceCredentialStore

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


class _MaterialResolver:
    def __init__(self, wire: dict) -> None:
        self.wire = wire
        self.requests: list[Any] = []

    def resolve(self, request: Any) -> dict:
        self.requests.append(request)
        return deepcopy(self.wire)


class _References:
    def __call__(self) -> tuple[str, str]:
        return ADMISSION_REF, EVIDENCE_REF


class _PairingRequestPort:
    """Outbound pairing redemption through the cloud handler without sockets."""

    def __init__(self, *, handler, browser_auth, device_auth, server_clock) -> None:
        self.handler = handler
        self.browser_auth = browser_auth
        self.device_auth = device_auth
        self.server_clock = server_clock
        self.calls: list[tuple[str, dict]] = []

    def post(self, *, config, operation, payload, timeout_seconds):
        del config, timeout_seconds
        name = operation.value
        self.server_clock.now = BASE + timedelta(seconds=1)
        self.calls.append((name, deepcopy(payload)))
        auth = self.browser_auth if operation is BrokerPairingHttpsOperation.CHALLENGE else self.device_auth
        response = self.handler.handle(
            method="POST",
            route=f"/{name}",
            content_type="application/json",
            body=json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8"),
            auth=auth,
        )
        return deepcopy(response.body)


class _DeviceRequestPort:
    SERVER_OFFSET: ClassVar[dict[str, timedelta]] = {
        "session": timedelta(seconds=5),
        "heartbeat": timedelta(seconds=10),
        "poll": timedelta(seconds=15),
        "material": timedelta(seconds=20),
        "admission": timedelta(seconds=25),
        "acknowledge": timedelta(seconds=30),
    }

    def __init__(self, *, handler, auth, server_clock, audit, fail_routes=None) -> None:
        self.handler = handler
        self.auth = auth
        self.server_clock = server_clock
        self.audit = audit
        self.fail_routes = set(fail_routes or ())
        self.calls: list[tuple[str, dict]] = []

    def post(self, *, config, operation, payload, timeout_seconds):
        del config, timeout_seconds
        name = operation.value
        self.calls.append((name, deepcopy(payload)))
        self.audit.append(name)
        if name in self.fail_routes:
            raise ConnectionError(f"simulated broker network failure on {name}")
        if name == "heartbeat" and isinstance(payload, dict) and "now" in payload:
            # Honour the heartbeat contract exactly like every other broker
            # cross-contract test: the server clock becomes the client's `now`.
            self.server_clock.now = datetime.fromisoformat(payload["now"].replace("Z", "+00:00"))
        elif name != "heartbeat":
            self.server_clock.now = BASE + self.SERVER_OFFSET[name]
        response = self.handler.handle(
            method="POST",
            route=f"/{name}",
            content_type="application/json",
            body=json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8"),
            auth=self.auth,
        )
        return deepcopy(response.body)


class _ReceiptRuntime:
    def __init__(self) -> None:
        self.executed: list[str] = []
        self.cancelled: list[str] = []

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
            authorization_ref="windows_p01_grant_e2e_1",
        )

    def cancel(self, request_id: str) -> None:
        self.cancelled.append(request_id)


def _config() -> OutboundTransportConfig:
    return OutboundTransportConfig(
        endpoint=OutboundBrokerEndpoint(
            endpoint_ref="broker_endpoint_pairing_e2e",
            url="https://local-agent.padiem.net:443/broker",
            mode=OutboundTransportMode.HTTPS_LONG_POLL,
        ),
        heartbeat_seconds=30,
        poll_timeout_seconds=15,
        max_response_bytes=65_536,
        tls_required=True,
        public_inbound_port=False,
    )


class OutboundOnlyPairingDispatchEndToEndTests(unittest.TestCase):
    """Issue #3080: pairing redemption + a real server projection boot dispatch.

    Mandated order (unchanged #3083 rule, never relaxed):

        redeem -> PAIRED_OFFLINE -> canonical broker session + heartbeat
               -> server-backed ONLINE projection -> dispatch
    """

    def setUp(self) -> None:
        InMemorySingleInstanceLock.reset()

    def tearDown(self) -> None:
        InMemorySingleInstanceLock.reset()

    def _auth(
        self,
        *,
        authenticated: bool,
        principal_ref: str = "device.e2e.1",
    ) -> TrustedLocalAgentHttpAuthContext:
        return TrustedLocalAgentHttpAuthContext(
            principal_ref=principal_ref,
            account_ref="account.e2e",
            workspace_ref="workspace.e2e",
            authenticated=authenticated,
            tls_verified=True,
        )

    def _fixture(self):
        server_clock = _ServerClock()
        authority = InMemoryLocalAgentBrokerAuthority(pepper=BROKER_PEPPER, authority_ref=AUTHORITY_REF)
        pairing = InMemoryBrokerPairingAuthority(
            pepper=PAIRING_PEPPER,
            authority=authority,
            code_nonce_factory=lambda: "a" * 32,
            credential_factory=lambda: CREDENTIAL,
        )
        durable = _DurableState()
        resolver = _MaterialResolver({"placeholder": True})
        handler = PairingAndAdmissionLocalAgentBrokerHttpHandler(
            pairing_authority=pairing,
            admission_reference_factory=_References(),
            rpc=LocalAgentBrokerRpcFacade(authority=authority),
            state=durable,
            material_resolver=resolver,
            clock=server_clock,
        )
        return server_clock, authority, pairing, durable, resolver, handler

    def _redeem(self, handler, store, *, server_clock):
        browser = self._auth(authenticated=True, principal_ref="principal.browser.e2e")
        issued = handler.handle(
            method="POST",
            route=PAIRING_CHALLENGE_ROUTE,
            content_type="application/json",
            body=json.dumps(
                {
                    "account_ref": "account.e2e",
                    "workspace_ref": "workspace.e2e",
                    "now": BASE.isoformat(),
                    "ttl_seconds": 300,
                }
            ).encode("utf-8"),
            auth=browser,
        ).body
        self.assertTrue(issued["ok"])
        client = LocalAgentBrokerPairingClient(
            config=_config(),
            credential_store=store,
            request_port=_PairingRequestPort(
                handler=handler,
                browser_auth=browser,
                device_auth=self._auth(authenticated=False),
                server_clock=server_clock,
            ),
        )
        return client.redeem(
            challenge_id=issued["challenge"]["challenge_id"],
            pairing_code=issued["pairing_code"],
            device_id="device.e2e.1",
            now=BASE,
        )

    def _device_channel(self, handler, store, *, server_clock, audit, fail_routes=None, binding):
        port = _DeviceRequestPort(
            handler=handler,
            auth=self._auth(authenticated=True),
            server_clock=server_clock,
            audit=audit,
            fail_routes=fail_routes,
        )
        transport = ControlPlanePhysicalAdmissionTransport(
            credential_store=store,
            expected_admission_authority_ref=AUTHORITY_REF,
            request_port=port,
        )
        broker_binding = PinnedOutboundBrokerBinding.from_binding(binding=binding, config=_config())
        return ControlPlanePhysicalAdmissionChannel(authority=broker_binding, transport=transport), broker_binding

    def test_pairing_redeem_then_server_projection_drives_outbound_polling_dispatch(self) -> None:
        import os
        import tempfile

        server_clock, authority, pairing, durable, resolver, handler = self._fixture()
        audit: list[str] = []

        with tempfile.TemporaryDirectory() as base_dir:
            store = _StoreBackedCredentialStore(base_dir=os.path.abspath(base_dir))
            enrollment = self._redeem(handler, store, server_clock=server_clock)

            # 1) Redeem alone is PAIRED_OFFLINE only, with no local ONLINE helper.
            paired_offline = enrollment.binding
            self.assertEqual(paired_offline.state, DeviceLifecycle.PAIRED_OFFLINE)
            self.assertFalse(hasattr(enrollment, "online_binding"))
            self.assertEqual(store.load(binding=paired_offline, now=BASE), CREDENTIAL)

            client_clock = _SimulatedClock()
            client_clock.now = BASE + timedelta(seconds=5)
            channel, broker_binding = self._device_channel(
                handler,
                store,
                server_clock=server_clock,
                audit=audit,
                binding=paired_offline,
            )

            # 2) canonical broker session, then 3) server-owned heartbeat.
            session = channel.open_session(
                binding=paired_offline,
                session_id="session.e2e.bootstrap",
                now=client_clock.now,
                ttl_seconds=900,
            )
            heartbeat = channel.heartbeat(binding=paired_offline, session=session, now=client_clock.now)
            self.assertEqual(audit, ["session", "heartbeat"])

            # 4) only now may the server-backed ONLINE projection exist.
            online = project_server_backed_online_binding(
                binding=paired_offline,
                session=session,
                heartbeat=heartbeat,
                now=client_clock.now,
            )
            self.assertEqual(online.state, DeviceLifecycle.ONLINE)
            evidence = online_binding_evidence(
                binding=paired_offline,
                session=session,
                heartbeat=heartbeat,
                now=client_clock.now,
            )
            self.assertTrue(evidence["evidence_backed"])
            self.assertEqual(evidence["server_projection_trigger"], "server_projection")
            self.assertFalse(evidence["local_online_claim"])

            # 5) dispatch runs with the server-backed ONLINE binding only.
            self._run_dispatch(
                server_clock=server_clock,
                authority=authority,
                pairing=pairing,
                durable=durable,
                resolver=resolver,
                store=store,
                broker_binding=broker_binding,
                channel=channel,
                online=online,
                client_clock=client_clock,
                audit=audit,
            )

    def test_online_is_impossible_without_a_server_session_and_heartbeat(self) -> None:
        import os
        import tempfile

        server_clock, _, _, _, _, handler = self._fixture()

        with tempfile.TemporaryDirectory() as base_dir:
            store = _StoreBackedCredentialStore(base_dir=os.path.abspath(base_dir))
            enrollment = self._redeem(handler, store, server_clock=server_clock)
            paired_offline = enrollment.binding
            self.assertEqual(paired_offline.state, DeviceLifecycle.PAIRED_OFFLINE)
            now = BASE + timedelta(seconds=5)

            # Case A: the broker session call itself fails.
            session_audit: list[str] = []
            failing, _ = self._device_channel(
                handler,
                store,
                server_clock=server_clock,
                audit=session_audit,
                fail_routes={"session"},
                binding=paired_offline,
            )
            with self.assertRaises(Exception):
                failing.open_session(binding=paired_offline, session_id="session.e2e.failed", now=now)
            self.assertEqual(session_audit, ["session"])

            # Case B: the session opens but the heartbeat never succeeds.
            heartbeat_audit: list[str] = []
            half_open, _ = self._device_channel(
                handler,
                store,
                server_clock=server_clock,
                audit=heartbeat_audit,
                fail_routes={"heartbeat"},
                binding=paired_offline,
            )
            session = half_open.open_session(
                binding=paired_offline,
                session_id="session.e2e.half",
                now=now,
                ttl_seconds=900,
            )
            with self.assertRaises(Exception):
                half_open.heartbeat(binding=paired_offline, session=session, now=now)
            self.assertEqual(heartbeat_audit, ["session", "heartbeat"])

            # Neither case can ever produce an ONLINE binding.
            for case_session, case_heartbeat in ((None, None), (session, None), (None, session)):
                with self.assertRaises(ContractError):
                    project_server_backed_online_binding(
                        binding=paired_offline,
                        session=case_session,
                        heartbeat=case_heartbeat,
                        now=now,
                    )
            self.assertEqual(paired_offline.state, DeviceLifecycle.PAIRED_OFFLINE)

            # The runtime still refuses a PAIRED_OFFLINE binding even with a
            # structurally current session.
            runtime = _ReceiptRuntime()
            device = LocalAgentDeviceProfile(
                device_id="device.e2e.1",
                workspace_ref="workspace.e2e",
                platform=LocalAgentPlatform.WINDOWS,
                roots=(LocalRoot(root_ref="root_repo", windows_path="C:\\\\padiem\\\\repo"),),
            )
            assembly = BoundLocalAgentRuntimeAssembly(
                device=device,
                binding=paired_offline,
                permissions=default_device_permission_profile(device=device),
                broker_authority=PinnedOutboundBrokerBinding.from_binding(
                    binding=paired_offline,
                    config=_config(),
                ),
                runtime=runtime,
            )
            with self.assertRaises(ContractError):
                assembly.execute(
                    session=session,
                    request=LocalCommandRequest(
                        request_id="req.e2e.1",
                        run_id="run.e2e.1",
                        device_id="device.e2e.1",
                        root_ref="root_repo",
                        argv=("python", "--version"),
                        cwd_relative=".",
                        requested_at=now,
                        timeout_seconds=30,
                    ),
                    now=now,
                )
            self.assertEqual(runtime.executed, [])
            self.assertFalse(assembly.safe_dict(now=now)["current"])

    def _run_dispatch(
        self,
        *,
        server_clock,
        authority,
        pairing,
        durable,
        resolver,
        store,
        broker_binding,
        channel,
        online,
        client_clock,
        audit,
    ) -> None:
        command_now = server_clock.now
        root = LocalRoot(root_ref="root_repo", windows_path="C:\\\\padiem\\\\repo")
        local_request = LocalCommandRequest(
            request_id="req.e2e.1",
            run_id="run.e2e.1",
            device_id="device.e2e.1",
            root_ref="root_repo",
            argv=("python", "--version"),
            cwd_relative=".",
            requested_at=command_now,
            timeout_seconds=30,
        )
        fingerprint = command_request_fingerprint(local_request)

        from kagent.local_agent_pairing import DeviceCommandEnvelope

        queued = authority.enqueue_command(
            command_id="command.e2e.1",
            binding_ref=online.binding_ref,
            run_id="run.e2e.1",
            tool_request_ref="tool.request.e2e.1",
            request_fingerprint=fingerprint,
            now=command_now,
            ttl_seconds=300,
        )
        resolver.wire = build_command_material_wire_projection(
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
            request=local_request,
            request_fingerprint=fingerprint,
        )

        device = LocalAgentDeviceProfile(
            device_id="device.e2e.1",
            workspace_ref="workspace.e2e",
            platform=LocalAgentPlatform.WINDOWS,
            roots=(root,),
        )
        runtime = _ReceiptRuntime()
        assembly = BoundLocalAgentRuntimeAssembly(
            device=device,
            binding=online,
            permissions=default_device_permission_profile(device=device),
            broker_authority=broker_binding,
            runtime=runtime,
        )
        host = LocalAgentResidentRuntimeHost(
            assembly=assembly,
            channel=channel,
            credential_store=store,
            clock=client_clock,
            session_id_factory=lambda: "session.e2e.host",
            heartbeat_interval_seconds=30,
            session_ttl_seconds=900,
        )
        host.start()
        self.assertEqual(host.state, ResidentHostState.ONLINE)
        self.assertEqual(host.run_once(), 1)

        finished = authority._commands[queued.command_id]
        self.assertEqual(finished.state.value, "acknowledged")
        self.assertEqual(finished.admission_ref, ADMISSION_REF)
        self.assertEqual(finished.evidence_ref, EVIDENCE_REF)
        self.assertEqual(runtime.executed, ["req.e2e.1"])

        # The mandated order is observable on the wire: the server projection
        # happened before any dispatch exchange.
        self.assertEqual(audit[:2], ["session", "heartbeat"])
        self.assertIn("admission", audit)
        for route in audit:
            self.assertIn(
                route,
                {"session", "heartbeat", "poll", "material", "admission", "acknowledge"},
            )
        self.assertEqual(host.status().state, ResidentHostState.ONLINE)
        host.stop()
        self.assertEqual(host.state, ResidentHostState.STOPPED)
        del pairing, durable


if __name__ == "__main__":
    unittest.main()
