from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import base64
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from kagent.contracts import ContractError
from kagent.local_agent_pairing import DeviceBinding, DeviceLifecycle, DeviceSession
from kagent.local_agent_secure_transport import (
    ATOMIC_CREDENTIAL_REPLACEMENT,
    CALLER_ENDPOINT_OVERRIDE,
    CRYPTPROTECT_LOCAL_MACHINE,
    CRYPTPROTECT_UI_FORBIDDEN,
    DPAPI_UI_FORBIDDEN,
    LOCAL_MACHINE_DPAPI_SCOPE,
    OUTBOUND_TLS_ONLY,
    PLAINTEXT_CREDENTIAL_PERSISTED,
    PUBLIC_INBOUND_PORT_REQUIRED,
    REAL_LOCAL_AGENT_BROKER_CONFIGURED,
    REAL_REMOTE_CONTROL_CONFIGURED,
    WINDOWS_DPAPI_CURRENT_USER,
    OutboundBrokerEndpoint,
    OutboundPollRequest,
    OutboundTransportConfig,
    OutboundTransportMode,
    ProtectedFileDeviceCredentialStore,
    UnconfiguredOutboundLocalAgentTransportPort,
)

NOW = datetime(2026, 9, 3, 8, 15, tzinfo=timezone.utc)


class DeterministicProtectedDataPort:
    """Deterministic reversible test adapter. It is not cryptography and never represents live DPAPI."""

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


def binding(
    *,
    generation: int = 1,
    state: DeviceLifecycle = DeviceLifecycle.PAIRED_OFFLINE,
    expires_at: datetime | None = None,
    credential_ref: str | None = None,
) -> DeviceBinding:
    return DeviceBinding(
        device_id="device_1",
        binding_ref="device-binding:one",
        account_ref="account_1",
        workspace_ref="workspace_1",
        credential_ref=credential_ref or f"device-credential:generation-{generation}",
        credential_generation=generation,
        issued_at=NOW - timedelta(hours=1),
        credential_expires_at=expires_at or NOW + timedelta(days=30),
        state=state,
    )


def session(*, expires_at: datetime | None = None) -> DeviceSession:
    return DeviceSession(
        session_id="session_1",
        device_id="device_1",
        binding_ref="device-binding:one",
        account_ref="account_1",
        workspace_ref="workspace_1",
        issued_at=NOW - timedelta(minutes=1),
        expires_at=expires_at or NOW + timedelta(minutes=10),
    )


class ProtectedCredentialStoreTests(unittest.TestCase):
    def test_store_persists_protected_payload_not_plaintext(self):
        raw = b"device-secret-material-for-test"
        with tempfile.TemporaryDirectory() as directory:
            store = ProtectedFileDeviceCredentialStore(
                base_dir=Path(directory).resolve(),
                protected_data=DeterministicProtectedDataPort(),
            )
            projection = store.save(binding=binding(), credential=raw, now=NOW)
            files = tuple(Path(directory).glob("*.credential.json"))
            self.assertEqual(len(files), 1)
            disk = files[0].read_bytes()
            self.assertNotIn(raw, disk)
            record = json.loads(disk.decode("utf-8"))
            self.assertNotIn("credential_ref", record)
            protected = base64.b64decode(record["protected_blob_b64"])
            self.assertNotEqual(protected, raw)
            self.assertEqual(store.load(binding=binding(), now=NOW), raw)

            safe = projection.safe_dict()
            self.assertFalse(safe["credential_ref_present"])
            self.assertFalse(safe["protected_blob_present"])
            self.assertFalse(safe["plaintext_credential_present"])
            self.assertFalse(safe["local_machine_scope"])

    def test_rotation_stale_record_fails_closed_until_replaced(self):
        raw_v1 = b"credential-v1"
        raw_v2 = b"credential-v2"
        with tempfile.TemporaryDirectory() as directory:
            store = ProtectedFileDeviceCredentialStore(
                base_dir=Path(directory).resolve(),
                protected_data=DeterministicProtectedDataPort(),
            )
            current = binding(generation=1)
            store.save(binding=current, credential=raw_v1, now=NOW)
            rotated = binding(generation=2)
            with self.assertRaises(ContractError):
                store.load(binding=rotated, now=NOW)
            store.save(binding=rotated, credential=raw_v2, now=NOW + timedelta(seconds=1))
            self.assertEqual(store.load(binding=rotated, now=NOW + timedelta(seconds=2)), raw_v2)
            with self.assertRaises(ContractError):
                store.load(binding=current, now=NOW + timedelta(seconds=2))

    def test_expired_and_revoked_bindings_cannot_load_or_save(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ProtectedFileDeviceCredentialStore(
                base_dir=Path(directory).resolve(),
                protected_data=DeterministicProtectedDataPort(),
            )
            expired = binding(expires_at=NOW - timedelta(seconds=1))
            revoked = binding(state=DeviceLifecycle.REVOKED)
            for candidate in (expired, revoked):
                with self.assertRaises(ContractError):
                    store.save(binding=candidate, credential=b"secret", now=NOW)
                with self.assertRaises(ContractError):
                    store.load(binding=candidate, now=NOW)

    def test_context_tamper_fails_before_unprotect(self):
        raw = b"credential-v1"
        with tempfile.TemporaryDirectory() as directory:
            store = ProtectedFileDeviceCredentialStore(
                base_dir=Path(directory).resolve(),
                protected_data=DeterministicProtectedDataPort(),
            )
            current = binding()
            store.save(binding=current, credential=raw, now=NOW)
            tampered = replace(current, account_ref="account_other")
            with self.assertRaises(ContractError):
                store.load(binding=tampered, now=NOW)


class OutboundEndpointTests(unittest.TestCase):
    def test_https_and_wss_are_tls_only_and_canonical(self):
        https_endpoint = OutboundBrokerEndpoint(
            endpoint_ref="broker_primary",
            url="https://Broker.Example.com:443/v1/local-agent",
            mode=OutboundTransportMode.HTTPS_LONG_POLL,
        )
        wss_endpoint = OutboundBrokerEndpoint(
            endpoint_ref="broker_ws",
            url="wss://Broker.Example.com/v1/local-agent/socket",
            mode=OutboundTransportMode.WSS,
        )
        self.assertEqual(https_endpoint.url, "https://broker.example.com:443/v1/local-agent")
        self.assertEqual(wss_endpoint.url, "wss://broker.example.com/v1/local-agent/socket")
        self.assertTrue(https_endpoint.safe_dict()["tls_required"])
        self.assertFalse(https_endpoint.safe_dict()["caller_endpoint_override"])
        self.assertFalse(wss_endpoint.safe_dict()["public_inbound_port"])

    def test_downgrade_userinfo_query_fragment_non443_and_path_escape_are_rejected(self):
        invalid = (
            ("http://broker.example.com/v1", OutboundTransportMode.HTTPS_LONG_POLL),
            ("ws://broker.example.com/v1", OutboundTransportMode.WSS),
            ("https://user:pass@broker.example.com/v1", OutboundTransportMode.HTTPS_LONG_POLL),
            ("https://broker.example.com:8443/v1", OutboundTransportMode.HTTPS_LONG_POLL),
            ("https://broker.example.com/v1?endpoint=evil", OutboundTransportMode.HTTPS_LONG_POLL),
            ("https://broker.example.com/v1#evil", OutboundTransportMode.HTTPS_LONG_POLL),
            ("https://broker.example.com/v1/../admin", OutboundTransportMode.HTTPS_LONG_POLL),
        )
        for url, mode in invalid:
            with self.subTest(url=url):
                with self.assertRaises(ContractError):
                    OutboundBrokerEndpoint(endpoint_ref="broker", url=url, mode=mode)

    def test_transport_config_cannot_disable_tls_or_require_public_inbound_port(self):
        endpoint = OutboundBrokerEndpoint(
            endpoint_ref="broker",
            url="https://broker.example.com/v1/local-agent",
            mode=OutboundTransportMode.HTTPS_LONG_POLL,
        )
        with self.assertRaises(ContractError):
            OutboundTransportConfig(endpoint=endpoint, tls_required=False)
        with self.assertRaises(ContractError):
            OutboundTransportConfig(endpoint=endpoint, public_inbound_port=True)

    def test_poll_requires_current_bound_session(self):
        current = session()
        request = OutboundPollRequest(
            request_ref="poll_1",
            session=current,
            after_sequence=0,
            requested_at=NOW,
        )
        self.assertTrue(request.safe_dict()["outbound_only"])
        self.assertFalse(request.safe_dict()["caller_endpoint_override"])
        with self.assertRaises(ContractError):
            OutboundPollRequest(
                request_ref="poll_expired",
                session=session(expires_at=NOW),
                after_sequence=0,
                requested_at=NOW,
            )

    def test_real_transport_is_fail_closed_until_broker_exists(self):
        port = UnconfiguredOutboundLocalAgentTransportPort()
        with self.assertRaises(ContractError):
            port.poll()
        with self.assertRaises(ContractError):
            port.acknowledge()


class RepositoryNonClaimTests(unittest.TestCase):
    def test_dpapi_and_transport_truth_constants(self):
        self.assertEqual(CRYPTPROTECT_UI_FORBIDDEN, 0x00000001)
        self.assertEqual(CRYPTPROTECT_LOCAL_MACHINE, 0x00000004)
        self.assertTrue(WINDOWS_DPAPI_CURRENT_USER)
        self.assertFalse(LOCAL_MACHINE_DPAPI_SCOPE)
        self.assertTrue(DPAPI_UI_FORBIDDEN)
        self.assertFalse(PLAINTEXT_CREDENTIAL_PERSISTED)
        self.assertTrue(ATOMIC_CREDENTIAL_REPLACEMENT)
        self.assertTrue(OUTBOUND_TLS_ONLY)
        self.assertFalse(PUBLIC_INBOUND_PORT_REQUIRED)
        self.assertFalse(CALLER_ENDPOINT_OVERRIDE)
        self.assertFalse(REAL_LOCAL_AGENT_BROKER_CONFIGURED)
        self.assertFalse(REAL_REMOTE_CONTROL_CONFIGURED)


if __name__ == "__main__":
    unittest.main()
