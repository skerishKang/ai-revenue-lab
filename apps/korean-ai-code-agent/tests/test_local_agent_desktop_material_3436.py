"""#3436 B2d — the bounded trusted-local Desktop session material channel.

What these tests pin down:

* a valid ONLINE resident projects exactly its current session material —
  sessionId/bindingRef/credentialB64 — from state it already holds (its own
  canonical broker session, the existing protected credential store);
* every unavailable condition fails closed: no resident, stopped, no session,
  expired session, expired credential, missing store, load failure, binding
  mismatch, rotated credential generation;
* a restarted resident never re-projects the old session;
* the responder answers exactly one bounded request kind over the existing
  stdio boundary, and every refusal is secret-free (no credential, no session
  id, no binding ref);
* nothing is persisted a second time: the credential directory keeps only the
  canonical store record.

    SECOND_SESSION_AUTHORITY=0
    DESKTOP_SESSION_OPEN=0
    RAW_CREDENTIAL_LOGGED=0
    RAW_CREDENTIAL_SECOND_PERSISTENCE=0
"""

from __future__ import annotations

import base64
import io
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from kagent.contracts import ContractError
from kagent.local_agent import LocalAgentDeviceProfile, LocalAgentPlatform, LocalRoot
from kagent.local_agent_control_plane_admission import (
    ControlPlanePhysicalAdmissionChannel,
    ControlPlanePhysicalAdmissionTransport,
)
from kagent.local_agent_desktop_material import (
    MATERIAL_REQUEST_CONTRACT_VERSION,
    MATERIAL_RESPONSE_CONTRACT_VERSION,
    MAX_REQUEST_LINE_CHARS,
    ResidentDesktopMaterialResponder,
    material_response_line,
    parse_material_request,
)
from kagent.local_agent_pairing import DeviceBinding, DeviceLifecycle, DeviceSession
from kagent.local_agent_runtime_assembly import BoundLocalAgentRuntimeAssembly
from kagent.local_agent_runtime_host import (
    InMemorySingleInstanceLock,
    LocalAgentResidentRuntimeHost,
    ResidentHostState,
)
from kagent.local_agent_secure_channel import PinnedOutboundBrokerBinding
from kagent.local_agent_secure_transport import (
    OutboundBrokerEndpoint,
    OutboundTransportConfig,
    OutboundTransportMode,
    ProtectedFileDeviceCredentialStore,
)
from kagent.local_agent_permissions import default_device_permission_profile
from kagent.local_agent_durable_run_store import DurableRunStore

BASE = datetime(2026, 10, 3, 9, 0, tzinfo=timezone.utc)
CREDENTIAL = b"b2d-trusted-local-material-credential"
BINDING_REF = "bind.b2d.resident"
DEVICE_ID = "dev.b2d.resident"
AUTHORITY_REF = "control-plane.local-agent-broker.b2d.v1"


def _transport_config() -> OutboundTransportConfig:
    return OutboundTransportConfig(
        endpoint=OutboundBrokerEndpoint(
            endpoint_ref="broker_endpoint_b2d_test",
            url="https://local-agent.padiem.net:443/broker",
            mode=OutboundTransportMode.HTTPS_LONG_POLL,
        ),
    )


class _ProtectedDataPort:
    """Deterministic XOR stand-in for the Windows DPAPI adapter."""

    def _stream(self, entropy: bytes, length: int) -> bytes:
        import hashlib

        out = b""
        block = 0
        while len(out) < length:
            out += hashlib.sha256(entropy + block.to_bytes(4, "big")).digest()
            block += 1
        return out[:length]

    def protect(self, credential: bytes, *, entropy: bytes) -> bytes:
        stream = self._stream(entropy, len(credential))
        return bytes(a ^ b for a, b in zip(credential, stream))

    def unprotect(self, protected: bytes, *, entropy: bytes) -> bytes:
        stream = self._stream(entropy, len(protected))
        return bytes(a ^ b for a, b in zip(protected, stream))


class _SimulatedClock:
    def __init__(self, start: datetime = BASE) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


class _OfflineAdmissionChannel(ControlPlanePhysicalAdmissionChannel):
    """A real canonical channel whose session seams are faked locally.

    The host requires the canonical channel type, so the fixture subclasses it
    and overrides only the network seams. The material projection never
    executes commands and never opens a session of its own: `open_session` is
    called exclusively by the host's own lifecycle, exactly as in production.
    """

    def __init__(self, *, binding: DeviceBinding, store, fail_open: bool = False) -> None:
        super().__init__(
            authority=PinnedOutboundBrokerBinding.from_binding(
                binding=binding, config=_transport_config()
            ),
            transport=ControlPlanePhysicalAdmissionTransport(
                credential_store=store,
                expected_admission_authority_ref=AUTHORITY_REF,
                request_port=None,
            ),
        )
        self._fail_open = fail_open
        self.open_calls = 0

    def open_session(
        self, *, binding: DeviceBinding, session_id: str, now: datetime, ttl_seconds: int = 900
    ) -> DeviceSession:
        self.open_calls += 1
        self.authority.require_current_binding(binding, now=now)
        if self._fail_open:
            raise ContractError("simulated broker connection failure")
        return DeviceSession(
            session_id=session_id,
            device_id=binding.device_id,
            binding_ref=binding.binding_ref,
            account_ref=binding.account_ref,
            workspace_ref=binding.workspace_ref,
            issued_at=now,
            expires_at=now + timedelta(seconds=ttl_seconds),
        )

    def heartbeat(self, *, binding: DeviceBinding, session: DeviceSession, now: datetime, previous_last_seen_at=None):
        del binding, previous_last_seen_at
        return SimpleNamespace(session_id=session.session_id, last_seen_at=now)

    def poll(self, *, binding: DeviceBinding, request) -> tuple:
        del binding, request
        return ()


class _HostFixture:
    """A real host with a real protected credential store and a fake channel."""

    def __init__(self, *, credential_expires_in=timedelta(days=30), fail_open=False):
        self.tmp = tempfile.TemporaryDirectory(prefix="claw-b2d-")
        self.store = ProtectedFileDeviceCredentialStore(
            base_dir=self.tmp.name, protected_data=_ProtectedDataPort()
        )
        self.binding = DeviceBinding(
            binding_ref=BINDING_REF,
            device_id=DEVICE_ID,
            account_ref="account.b2d",
            workspace_ref="workspace.b2d",
            credential_generation=1,
            credential_ref="cred.b2d.1",
            credential_expires_at=BASE + credential_expires_in,
            issued_at=BASE,
            state=DeviceLifecycle.PAIRED_OFFLINE,
        )
        self.store.save(binding=self.binding, credential=CREDENTIAL, now=BASE)
        self.clock = _SimulatedClock(BASE + timedelta(seconds=1))
        self.channel = _OfflineAdmissionChannel(
            binding=self.binding, store=self.store, fail_open=fail_open
        )
        device = LocalAgentDeviceProfile(
            device_id=DEVICE_ID,
            workspace_ref=self.binding.workspace_ref,
            platform=LocalAgentPlatform.WINDOWS,
            roots=(LocalRoot(root_ref="root.b2d", windows_path="C:/b2d/root"),),
        )
        self.host = LocalAgentResidentRuntimeHost(
            assembly=BoundLocalAgentRuntimeAssembly(
                device=device,
                binding=self.binding,
                permissions=default_device_permission_profile(device=device),
                broker_authority=self.channel.authority,
                # The material projection never executes anything; a refused
                # stand-in runtime is enough for the constructor's seam check.
                runtime=SimpleNamespace(
                    execute_with_receipt=lambda *args, **kwargs: (_ for _ in ()).throw(
                        ContractError("not exercised by the material projection")
                    ),
                    cancel=lambda *args, **kwargs: None,
                ),
            ),
            channel=self.channel,
            credential_store=self.store,
            durable_store=DurableRunStore(":memory:"),
            clock=self.clock,
            session_id_factory=lambda: "sess_b2d_current_1",
        )

    def start(self) -> None:
        self.host.start()

    def stop(self) -> None:
        self.host.stop()

    def cleanup(self) -> None:
        self.host.stop()
        self.tmp.cleanup()


class DesktopSessionMaterial3436Test(unittest.TestCase):
    def test_valid_online_resident_projects_its_current_session(self) -> None:
        fixture = _HostFixture()
        try:
            fixture.start()
            projection = fixture.host.current_desktop_session_material()
            self.assertEqual(
                set(projection),
                {
                    "ok",
                    "session_id",
                    "binding_ref",
                    "credential_b64",
                    "credential_generation",
                    "expires_at",
                },
            )
            self.assertTrue(projection["ok"])
            self.assertEqual(projection["session_id"], "sess_b2d_current_1")
            self.assertEqual(projection["binding_ref"], BINDING_REF)
            self.assertEqual(
                base64.b64decode(projection["credential_b64"]), CREDENTIAL
            )
            self.assertEqual(projection["credential_generation"], 1)
            self.assertTrue(projection["expires_at"].endswith("Z"))
        finally:
            fixture.cleanup()

    def test_stopped_resident_and_missing_resident_refuse(self) -> None:
        fixture = _HostFixture()
        try:
            # No start call at all: STOPPED is the no-resident answer.
            with self.assertRaises(ContractError):
                fixture.host.current_desktop_session_material()
        finally:
            fixture.cleanup()

    def test_offline_resident_refuses(self) -> None:
        fixture = _HostFixture(fail_open=True)
        try:
            with self.assertRaises(ContractError):
                fixture.start()
            self.assertIs(fixture.host.state, ResidentHostState.OFFLINE)
            with self.assertRaises(ContractError):
                fixture.host.current_desktop_session_material()
        finally:
            fixture.cleanup()

    def test_session_missing_refuses_even_if_state_says_online(self) -> None:
        fixture = _HostFixture()
        try:
            fixture.start()
            fixture.host.stop()
            # Defensive: an ONLINE claim without a session is still refused.
            fixture.host._state = ResidentHostState.ONLINE
            with self.assertRaises(ContractError):
                fixture.host.current_desktop_session_material()
        finally:
            fixture.cleanup()

    def test_session_expired_refuses(self) -> None:
        fixture = _HostFixture()
        try:
            fixture.start()
            fixture.clock.advance(901)
            with self.assertRaises(ContractError):
                fixture.host.current_desktop_session_material()
        finally:
            fixture.cleanup()

    def test_credential_expired_refuses(self) -> None:
        # The binding's credential expires while the session is still current:
        # exactly the stale-material condition the Desktop must never see.
        fixture = _HostFixture(credential_expires_in=timedelta(seconds=2))
        try:
            fixture.start()
            fixture.clock.advance(2)
            with self.assertRaises(ContractError) as caught:
                fixture.host.current_desktop_session_material()
            self.assertIn("expired", str(caught.exception))
        finally:
            fixture.cleanup()

    def test_credential_store_missing_refuses(self) -> None:
        fixture = _HostFixture()
        try:
            fixture.start()
            fixture.store.delete(BINDING_REF)
            with self.assertRaises(ContractError):
                fixture.host.current_desktop_session_material()
        finally:
            fixture.cleanup()

    def test_credential_load_failure_refuses(self) -> None:
        fixture = _HostFixture()
        try:
            fixture.start()
            record_path = next(Path(fixture.tmp.name).glob("*.credential.json"))
            record_path.write_bytes(b"{not json")
            with self.assertRaises(ContractError):
                fixture.host.current_desktop_session_material()
        finally:
            fixture.cleanup()

    def test_binding_context_mismatch_refuses(self) -> None:
        fixture = _HostFixture()
        try:
            fixture.start()
            record_path = next(Path(fixture.tmp.name).glob("*.credential.json"))
            record = json.loads(record_path.read_text(encoding="utf-8"))
            record["workspace_ref"] = "workspace.other"
            record_path.write_text(json.dumps(record), encoding="utf-8")
            with self.assertRaises(ContractError) as caught:
                fixture.host.current_desktop_session_material()
            self.assertIn("does not match", str(caught.exception))
        finally:
            fixture.cleanup()

    def test_session_binding_exact_correlation_is_enforced_before_projection(self) -> None:
        """FIX 3: the existing canonical authority re-validates the exact
        session/binding correlation right before projection. Same session id
        and same times, but one correlated field wrong → no material."""

        fixture = _HostFixture()
        try:
            fixture.start()
            session = fixture.host._session
            overrides = {
                "binding_ref": "bind.other",
                "device_id": "dev.other",
                "account_ref": "account.other",
                "workspace_ref": "workspace.other",
            }
            for field, wrong in overrides.items():
                forged = DeviceSession(
                    session_id=session.session_id,
                    device_id=session.device_id,
                    binding_ref=session.binding_ref,
                    account_ref=session.account_ref,
                    workspace_ref=session.workspace_ref,
                    issued_at=session.issued_at,
                    expires_at=session.expires_at,
                )
                object.__setattr__(forged, field, wrong)
                fixture.host._session = forged
                with self.assertRaises(ContractError) as caught:
                    fixture.host.current_desktop_session_material()
                self.assertIn("does not match", str(caught.exception), field)
        finally:
            fixture.cleanup()

    def test_credential_rotation_leaves_stale_material_unavailable(self) -> None:
        fixture = _HostFixture()
        try:
            fixture.start()
            rotated = DeviceBinding(
                binding_ref=BINDING_REF,
                device_id=DEVICE_ID,
                account_ref="account.b2d",
                workspace_ref="workspace.b2d",
                credential_generation=2,
                credential_ref="cred.b2d.2",
                credential_expires_at=BASE + timedelta(days=30),
                issued_at=BASE,
                state=DeviceLifecycle.PAIRED_OFFLINE,
            )
            fixture.store.save(binding=rotated, credential=b"rotated-credential", now=BASE)
            # The host still holds the generation-1 binding: its projection is
            # refused instead of silently presenting the rotated credential.
            with self.assertRaises(ContractError):
                fixture.host.current_desktop_session_material()
        finally:
            fixture.cleanup()

    def test_resident_restart_never_reprojects_the_old_session(self) -> None:
        fixture = _HostFixture()
        try:
            fixture.start()
            old_projection = fixture.host.current_desktop_session_material()
            self.assertEqual(old_projection["session_id"], "sess_b2d_current_1")
            fixture.stop()
            with self.assertRaises(ContractError):
                fixture.host.current_desktop_session_material()
        finally:
            fixture.cleanup()

        # A fresh resident projects a NEW session; the old one is gone.
        InMemorySingleInstanceLock.reset()
        second = _HostFixture()
        try:
            second.host._session_id_factory = lambda: "sess_b2d_current_2"
            second.start()
            new_projection = second.host.current_desktop_session_material()
            self.assertEqual(new_projection["session_id"], "sess_b2d_current_2")
            self.assertNotEqual(new_projection["session_id"], "sess_b2d_current_1")
        finally:
            second.cleanup()

    def test_projection_persists_nothing_new(self) -> None:
        fixture = _HostFixture()
        try:
            fixture.start()
            before = sorted(p.name for p in Path(fixture.tmp.name).iterdir())
            fixture.host.current_desktop_session_material()
            fixture.host.current_desktop_session_material()
            after = sorted(p.name for p in Path(fixture.tmp.name).iterdir())
            self.assertEqual(before, after)
        finally:
            fixture.cleanup()


class MaterialRequestResponseContractTest(unittest.TestCase):
    def test_request_contract_is_exact(self) -> None:
        parsed = parse_material_request(
            json.dumps(
                {
                    "contract_version": MATERIAL_REQUEST_CONTRACT_VERSION,
                    "request": "desktop_device_session_material",
                }
            )
        )
        self.assertEqual(parsed["request"], "desktop_device_session_material")
        for bad in [
            "",
            "not json",
            "[]",
            json.dumps({"contract_version": "other", "request": "desktop_device_session_material"}),
            json.dumps({"contract_version": MATERIAL_REQUEST_CONTRACT_VERSION, "request": "everything"}),
            json.dumps(
                {
                    "contract_version": MATERIAL_REQUEST_CONTRACT_VERSION,
                    "request": "desktop_device_session_material",
                    "session_id": "caller-chosen",
                }
            ),
            "x" * (MAX_REQUEST_LINE_CHARS + 1),
        ]:
            with self.assertRaises(ContractError):
                parse_material_request(bad)

    def test_response_line_carries_exactly_the_closed_payload(self) -> None:
        projection = {
            "ok": True,
            "session_id": "sess_b2d_current_1",
            "binding_ref": BINDING_REF,
            "credential_b64": base64.b64encode(CREDENTIAL).decode("ascii"),
            "credential_generation": 1,
            "expires_at": (BASE + timedelta(seconds=900)).isoformat().replace("+00:00", "Z"),
        }
        line = material_response_line(projection)
        payload = json.loads(line)
        self.assertEqual(payload["event"], "desktop_device_session_material")
        self.assertEqual(payload["contract_version"], MATERIAL_RESPONSE_CONTRACT_VERSION)
        # The success schema is exact-closed: the projection is widened by
        # nothing, so no owner/workspace/user field can ever ride along.
        self.assertEqual(
            set(payload),
            {
                "event",
                "contract_version",
                "ok",
                "session_id",
                "binding_ref",
                "credential_b64",
                "credential_generation",
                "expires_at",
            },
        )
        # A credential larger than the repository bound is refused outright.
        with self.assertRaises(ContractError):
            material_response_line({**projection, "credential_b64": "QQ==" * 20_000})

    def test_responder_answers_a_valid_request_with_material(self) -> None:
        fixture = _HostFixture()
        try:
            fixture.start()
            emitted: list[str] = []
            responder = ResidentDesktopMaterialResponder(
                material_projection=fixture.host.current_desktop_session_material,
                reader=io.StringIO(),
                emit=emitted.append,
            )
            line = responder.respond(
                json.dumps(
                    {
                        "contract_version": MATERIAL_REQUEST_CONTRACT_VERSION,
                        "request": "desktop_device_session_material",
                    }
                )
            )
            payload = json.loads(line)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["session_id"], "sess_b2d_current_1")
            self.assertEqual(base64.b64decode(payload["credential_b64"]), CREDENTIAL)
            self.assertEqual(emitted, [])
        finally:
            fixture.cleanup()

    def test_responder_refusals_are_secret_free(self) -> None:
        fixture = _HostFixture()
        try:
            fixture.start()
            fixture.store.delete(BINDING_REF)
            responder = ResidentDesktopMaterialResponder(
                material_projection=fixture.host.current_desktop_session_material,
                reader=io.StringIO(),
            )
            request = json.dumps(
                {
                    "contract_version": MATERIAL_REQUEST_CONTRACT_VERSION,
                    "request": "desktop_device_session_material",
                }
            )
            for raw in [request, "", "junk", "x" * (MAX_REQUEST_LINE_CHARS + 1)]:
                payload = json.loads(responder.respond(raw))
                self.assertFalse(payload["ok"])
                self.assertNotIn("credential_b64", payload)
                self.assertNotIn("session_id", payload)
                self.assertNotIn("binding_ref", payload)
                self.assertNotIn(CREDENTIAL.decode("ascii"), json.dumps(payload))
        finally:
            fixture.cleanup()

    def test_responder_maps_failures_to_bounded_reasons(self) -> None:
        cases = {
            "resident host is not online": "resident_not_online",
            "resident host has no current broker session": "session_missing",
            "resident broker session is not current": "session_not_current",
            "device session is not current": "session_not_current",
            "device session does not match pinned outbound broker authority": "binding_mismatch",
            "device credential binding is expired": "credential_expired",
            "protected device credential is not stored": "credential_store_missing",
            "stored device credential does not match current binding context": "binding_mismatch",
            "some other failure": "material_refused",
        }
        for message, expected in cases.items():
            def raise_it(message=message):
                raise ContractError(message)

            responder = ResidentDesktopMaterialResponder(
                material_projection=raise_it, reader=io.StringIO()
            )
            payload = json.loads(
                responder.respond(
                    json.dumps(
                        {
                            "contract_version": MATERIAL_REQUEST_CONTRACT_VERSION,
                            "request": "desktop_device_session_material",
                        }
                    )
                )
            )
            self.assertEqual(payload["reason"], expected, message)

    def test_responder_thread_starts_exactly_once(self) -> None:
        responder = ResidentDesktopMaterialResponder(
            material_projection=lambda: {}, reader=io.StringIO()
        )
        responder.start()
        with self.assertRaises(ContractError):
            responder.start()


if __name__ == "__main__":
    unittest.main()
