from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import hashlib
import json
import unittest

from kagent.contracts import ContractError
from kagent.local_agent_control_plane_https import ControlPlaneHttpsOperation
from kagent.local_agent_broker_pairing_client import (
    CALLER_ENDPOINT_OVERRIDE,
    CANONICAL_CREDENTIAL_STORE_REUSED,
    CLIENT_CHALLENGE_AUTHORITY,
    LIVE_BROKER_CONFIGURED,
    MAX_ENROLLMENT_CLOCK_SKEW_SECONDS,
    OUTBOUND_ONLY_ENROLLMENT,
    PAIRING_PROOF_TRANSCRIPT,
    PRODUCTION_MUTATION,
    PRODUCTION_READY,
    PUBLIC_INBOUND_PORT,
    RAW_DEVICE_CREDENTIAL_LOGGED,
    RAW_PAIRING_CODE_LOGGED,
    REAL_USER_PAIRING_CANARY,
    TLS_REQUIRED,
    UPNP_PORT_FORWARD_SUPPORTED,
    BrokerPairingHttpsOperation,
    LocalAgentBrokerPairingClient,
    StdlibPinnedHttpsBrokerPairingJsonRequestPort,
    UnconfiguredLocalAgentBrokerPairingClient,
    pairing_proof_ref,
)
from kagent.local_agent_pairing import DeviceBinding, DeviceLifecycle
from kagent.local_agent_secure_transport import (
    OutboundBrokerEndpoint,
    OutboundTransportConfig,
    OutboundTransportMode,
    StoredDeviceCredentialProjection,
)
from padiem_control_plane.local_agent_broker import InMemoryLocalAgentBrokerAuthority
from padiem_control_plane.local_agent_broker_http import (
    DurableLocalAgentSessionRecord,
    TrustedLocalAgentHttpAuthContext,
)
from padiem_control_plane.local_agent_broker_pairing import InMemoryBrokerPairingAuthority
from padiem_control_plane.local_agent_broker_pairing_http import (
    PAIRING_CHALLENGE_ROUTE,
    PairingEnabledLocalAgentBrokerHttpHandler,
)
from padiem_control_plane.local_agent_broker_rpc import LocalAgentBrokerRpcFacade

BASE = datetime(2026, 9, 26, 6, 0, tzinfo=timezone.utc)
CREDENTIAL = b"desktop-pairing-client-credential"
BROKER_PEPPER = b"control-plane-local-agent-broker-pepper"
PAIRING_PEPPER = b"control-plane-local-agent-pairing-pepper"
CODE = "0123456789abcdef0123456789abcdef"


# Synthetic non-secret marker, encoded at runtime. No credential-like literal is
# committed, so secret scanning stays clean for this branch history.
_SYNTHETIC_CREDENTIAL_B64 = base64.b64encode(b"synthetic-test-credential-marker").decode("ascii")


def _config(*, url: str = "https://local-agent.padiem.net:443/broker") -> OutboundTransportConfig:
    return OutboundTransportConfig(
        endpoint=OutboundBrokerEndpoint(
            endpoint_ref="broker_endpoint_pairing_client",
            url=url,
            mode=OutboundTransportMode.HTTPS_LONG_POLL,
        ),
        heartbeat_seconds=30,
        poll_timeout_seconds=15,
        max_response_bytes=65_536,
    )


class _Clock:
    def __init__(self, now: datetime = BASE) -> None:
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
        try:
            return self.records[session_id]
        except KeyError as exc:
            raise RuntimeError("session is not present in durable test state") from exc

    def record_last_seen(self, session_id: str, *, seen_at: datetime) -> DurableLocalAgentSessionRecord:
        record = self.load_session(session_id).with_last_seen(seen_at)
        self.records[session_id] = record
        return record


class _Resolver:
    def resolve(self, request):  # pragma: no cover - pairing tests never materialize commands
        raise AssertionError(request)


class _CredentialStore:
    def __init__(self) -> None:
        self.saved: dict[str, bytes] = {}
        self.saves = 0
        self.loads = 0

    def save(self, *, binding: DeviceBinding, credential: bytes, now: datetime) -> StoredDeviceCredentialProjection:
        self.saves += 1
        self.saved[binding.binding_ref] = credential
        return StoredDeviceCredentialProjection(
            binding_ref=binding.binding_ref,
            device_id=binding.device_id,
            account_ref=binding.account_ref,
            workspace_ref=binding.workspace_ref,
            credential_generation=binding.credential_generation,
            credential_ref_fingerprint=hashlib.sha256(binding.credential_ref.encode("utf-8")).hexdigest(),
            stored_at=now,
            credential_expires_at=binding.credential_expires_at,
        )

    def load(self, *, binding: DeviceBinding, now: datetime) -> bytes:
        del now
        self.loads += 1
        return self.saved[binding.binding_ref]

    def delete(self, binding_ref: str) -> None:
        self.saved.pop(binding_ref, None)


def _pairing_handler(*, nonce: str = "a" * 32):
    authority = InMemoryLocalAgentBrokerAuthority(pepper=BROKER_PEPPER, authority_ref="control-plane.local-agent-broker.v1")
    pairing = InMemoryBrokerPairingAuthority(
        pepper=PAIRING_PEPPER,
        authority=authority,
        code_nonce_factory=lambda: nonce,
        credential_factory=lambda: CREDENTIAL,
    )
    handler = PairingEnabledLocalAgentBrokerHttpHandler(
        pairing_authority=pairing,
        rpc=LocalAgentBrokerRpcFacade(authority=authority),
        state=_DurableState(),
        material_resolver=_Resolver(),
        clock=_Clock(),
    )
    return handler, authority


def _browser_auth() -> TrustedLocalAgentHttpAuthContext:
    return TrustedLocalAgentHttpAuthContext(
        principal_ref="principal.browser.1",
        account_ref="account.1",
        workspace_ref="workspace.1",
        authenticated=True,
        tls_verified=True,
    )


def _device_auth(device_id: str = "device.cli.1") -> TrustedLocalAgentHttpAuthContext:
    return TrustedLocalAgentHttpAuthContext(
        principal_ref=device_id,
        account_ref="account.1",
        workspace_ref="workspace.1",
        authenticated=False,
        tls_verified=True,
    )


def _issue_challenge(handler, *, ttl_seconds: int = 300) -> dict:
    response = handler.handle(
        method="POST",
        route=PAIRING_CHALLENGE_ROUTE,
        content_type="application/json",
        body=json.dumps(
            {
                "account_ref": "account.1",
                "workspace_ref": "workspace.1",
                "now": BASE.isoformat(),
                "ttl_seconds": ttl_seconds,
            }
        ).encode("utf-8"),
        auth=_browser_auth(),
    )
    assert response.status == 200
    return response.body


class _HandlerPairingPort:
    """In-process stand-in for the pinned outbound HTTPS pairing route."""

    def __init__(self, *, handler, device_auth) -> None:
        self.handler = handler
        self.device_auth = device_auth
        self.calls: list[tuple[str, dict]] = []

    def post(self, *, config, operation, payload, timeout_seconds):
        del timeout_seconds
        assert isinstance(config, OutboundTransportConfig)
        assert operation is BrokerPairingHttpsOperation.REDEEM
        self.calls.append((operation.value, json.loads(json.dumps(payload))))
        response = self.handler.handle(
            method="POST",
            route=f"/{operation.value}",
            content_type="application/json",
            body=json.dumps(payload).encode("utf-8"),
            auth=self.device_auth,
        )
        return json.loads(json.dumps(response.body))


class _ScriptedPairingPort:
    """Returns one scripted broker response and never performs network I/O."""

    def __init__(self, response) -> None:
        self.response = response
        self.calls: list[tuple[str, dict]] = []

    def post(self, *, config, operation, payload, timeout_seconds):
        del config, timeout_seconds
        self.calls.append((operation.value, payload))
        return self.response


def _enrollment_response(**overrides) -> dict:
    enrollment = {
        "binding_ref": "pairing-binding." + "b" * 32,
        "device_id": "device.cli.1",
        "account_ref": "account.1",
        "workspace_ref": "workspace.1",
        "credential_ref": "pairing-credential." + "b" * 32,
        "credential_generation": 1,
        "issued_at": BASE.isoformat().replace("+00:00", "Z"),
        "credential_expires_at": (BASE + timedelta(days=30)).isoformat().replace("+00:00", "Z"),
        "challenge_id": "pairing." + "c" * 32,
        "server_owned_binding_refs": True,
        "raw_device_credential": False,
        "production_ready": False,
    }
    enrollment.update(overrides)
    return enrollment


class LocalAgentBrokerPairingClientTests(unittest.TestCase):
    def test_pinned_pairing_route_resolves_against_the_pinned_broker_base_path(self):
        port = StdlibPinnedHttpsBrokerPairingJsonRequestPort()
        self.assertEqual(
            port._path(_config(), BrokerPairingHttpsOperation.REDEEM),
            ("local-agent.padiem.net", 443, "/broker/v1/broker/pairings/redeem"),
        )
        self.assertEqual(
            port._path(_config(url="https://local-agent.padiem.net:443"), BrokerPairingHttpsOperation.REDEEM),
            ("local-agent.padiem.net", 443, "/v1/broker/pairings/redeem"),
        )
        self.assertEqual(
            port._path(_config(), BrokerPairingHttpsOperation.CHALLENGE),
            ("local-agent.padiem.net", 443, "/broker/v1/broker/pairings/challenge"),
        )
        self.assertEqual(
            port._path(_config(), ControlPlaneHttpsOperation.POLL),
            ("local-agent.padiem.net", 443, "/broker/poll"),
        )

    def test_redeem_persists_the_credential_once_and_never_claims_online(self):
        handler, authority = _pairing_handler()
        issued = _issue_challenge(handler)
        store = _CredentialStore()
        port = _HandlerPairingPort(handler=handler, device_auth=_device_auth())
        client = LocalAgentBrokerPairingClient(config=_config(), credential_store=store, request_port=port)

        enrollment = client.redeem(
            challenge_id=issued["challenge"]["challenge_id"],
            pairing_code=issued["pairing_code"],
            device_id="device.cli.1",
            now=BASE,
        )

        self.assertEqual(len(port.calls), 1)
        operation, payload = port.calls[0]
        self.assertEqual(operation, BrokerPairingHttpsOperation.REDEEM.value)
        self.assertEqual(sorted(payload), ["challenge_id", "device_id", "now", "proof_ref"])
        self.assertEqual(payload["now"], "2026-09-26T06:00:00Z")
        self.assertEqual(
            payload["proof_ref"],
            pairing_proof_ref(
                challenge_id=issued["challenge"]["challenge_id"],
                device_id="device.cli.1",
                pairing_code=issued["pairing_code"],
            ),
        )

        binding = enrollment.binding
        self.assertEqual(binding.state, DeviceLifecycle.PAIRED_OFFLINE)
        self.assertEqual(binding.device_id, "device.cli.1")
        self.assertEqual(binding.account_ref, "account.1")
        self.assertEqual(binding.workspace_ref, "workspace.1")
        self.assertEqual(binding.credential_generation, 1)
        self.assertEqual(store.saves, 1)
        self.assertEqual(store.load(binding=binding, now=BASE), CREDENTIAL)
        self.assertEqual(store.saved[binding.binding_ref], CREDENTIAL)

        # #3083 rule: redemption can never produce ONLINE, and the enrollment
        # exposes no local ONLINE projection at all.
        self.assertFalse(hasattr(enrollment, "online_binding"))

        rendered = enrollment.safe_dict()
        self.assertEqual(rendered["pairing_challenge_id"], issued["challenge"]["challenge_id"])
        self.assertTrue(rendered["credential_persisted_once"])
        self.assertEqual(rendered["binding_state"], DeviceLifecycle.PAIRED_OFFLINE.value)
        self.assertTrue(rendered["online_requires_server_projection"])
        self.assertFalse(rendered["local_online_claim"])
        self.assertFalse(rendered["raw_device_credential"])
        self.assertFalse(rendered["pairing_code_persisted"])
        self.assertFalse(rendered["public_inbound_port"])
        self.assertNotIn(CREDENTIAL.decode(), json.dumps(rendered))
        self.assertNotIn(issued["pairing_code"], json.dumps(rendered))
        self.assertEqual(len(authority._bindings), 1)

    def test_redeem_rejects_untrusted_or_tampered_broker_responses(self):
        store = _CredentialStore()
        challenge_id = "pairing." + "c" * 32
        cases = {
            "missing one-time confirmation": {
                "ok": True,
                "enrollment": _enrollment_response(challenge_id=challenge_id),
                "credential_b64": _SYNTHETIC_CREDENTIAL_B64,
                "credential_returned_once": False,
            },
            "device substitution": {
                "ok": True,
                "enrollment": _enrollment_response(challenge_id=challenge_id, device_id="device.other"),
                "credential_b64": _SYNTHETIC_CREDENTIAL_B64,
                "credential_returned_once": True,
            },
            "challenge substitution": {
                "ok": True,
                "enrollment": _enrollment_response(challenge_id="pairing." + "d" * 32),
                "credential_b64": _SYNTHETIC_CREDENTIAL_B64,
                "credential_returned_once": True,
            },
            "client-owned binding authority": {
                "ok": True,
                "enrollment": _enrollment_response(challenge_id=challenge_id, server_owned_binding_refs=False),
                "credential_b64": _SYNTHETIC_CREDENTIAL_B64,
                "credential_returned_once": True,
            },
            "credential expansion": {
                "ok": True,
                "enrollment": _enrollment_response(challenge_id=challenge_id, raw_device_credential=True),
                "credential_b64": _SYNTHETIC_CREDENTIAL_B64,
                "credential_returned_once": True,
            },
            "clock skew": {
                "ok": True,
                "enrollment": _enrollment_response(
                    challenge_id=challenge_id,
                    issued_at=(BASE + timedelta(seconds=MAX_ENROLLMENT_CLOCK_SKEW_SECONDS + 1))
                    .isoformat()
                    .replace("+00:00", "Z"),
                ),
                "credential_b64": _SYNTHETIC_CREDENTIAL_B64,
                "credential_returned_once": True,
            },
            "invalid credential encoding": {
                "ok": True,
                "enrollment": _enrollment_response(challenge_id=challenge_id),
                "credential_b64": "not-base64!!",
                "credential_returned_once": True,
            },
            "unexpected response fields": {
                "ok": True,
                "enrollment": _enrollment_response(challenge_id=challenge_id),
                "credential_b64": _SYNTHETIC_CREDENTIAL_B64,
                "credential_returned_once": True,
                "secret_expansion": True,
            },
            "broker error": {"ok": False, "error": {"code": "pairing_challenge_expired", "message": "expired"}},
            "malformed error": {"ok": False, "error": {"code": "pairing_challenge_expired"}},
            "not a mapping": ["ok"],
        }

        for label, response in cases.items():
            with self.subTest(label=label):
                port = _ScriptedPairingPort(response)
                client = LocalAgentBrokerPairingClient(
                    config=_config(),
                    credential_store=store,
                    request_port=port,
                )
                with self.assertRaises(ContractError):
                    client.redeem(
                        challenge_id=challenge_id,
                        pairing_code=CODE,
                        device_id="device.cli.1",
                        now=BASE,
                    )
                self.assertEqual(len(port.calls), 1)
                self.assertEqual(store.saves, 0)

    def test_redeem_never_sends_a_request_for_a_malformed_pairing_code(self):
        store = _CredentialStore()
        port = _ScriptedPairingPort({"ok": True})
        client = LocalAgentBrokerPairingClient(config=_config(), credential_store=store, request_port=port)

        for pairing_code in ("", "ABCDEF", "z" * 32, 123):
            with self.subTest(pairing_code=pairing_code):
                with self.assertRaises(ContractError):
                    client.redeem(
                        challenge_id="pairing." + "c" * 32,
                        pairing_code=pairing_code,
                        device_id="device.cli.1",
                        now=BASE,
                    )
        self.assertEqual(port.calls, [])
        self.assertEqual(store.saves, 0)

    def test_redeem_rejects_replayed_and_expired_challenges_from_the_broker(self):
        handler, _ = _pairing_handler()
        issued = _issue_challenge(handler, ttl_seconds=30)
        store = _CredentialStore()
        client = LocalAgentBrokerPairingClient(
            config=_config(),
            credential_store=store,
            request_port=_HandlerPairingPort(handler=handler, device_auth=_device_auth()),
        )
        client.redeem(
            challenge_id=issued["challenge"]["challenge_id"],
            pairing_code=issued["pairing_code"],
            device_id="device.cli.1",
            now=BASE,
        )
        with self.assertRaises(ContractError) as replay:
            client.redeem(
                challenge_id=issued["challenge"]["challenge_id"],
                pairing_code=issued["pairing_code"],
                device_id="device.cli.1",
                now=BASE,
            )
        self.assertIn("pairing_challenge_already_redeemed", str(replay.exception))
        self.assertEqual(store.saves, 1)

        with self.assertRaises(ContractError) as wrong_code:
            client.redeem(
                challenge_id=issued["challenge"]["challenge_id"],
                pairing_code="f" * 32,
                device_id="device.cli.1",
                now=BASE,
            )
        self.assertIn("pairing_challenge_already_redeemed", str(wrong_code.exception))

    def test_unconfigured_client_fails_closed_and_pairing_claims_remain_false(self):
        port = UnconfiguredLocalAgentBrokerPairingClient()
        with self.assertRaises(ContractError):
            port.redeem(
                challenge_id="pairing." + "c" * 32,
                pairing_code=CODE,
                device_id="device.cli.1",
                now=BASE,
            )

        client = LocalAgentBrokerPairingClient(config=_config(), credential_store=_CredentialStore())
        rendered = client.safe_dict()
        self.assertEqual(rendered["pairing_proof_algorithm"], "HMAC-SHA256")
        self.assertEqual(rendered["pairing_proof_transcript"], PAIRING_PROOF_TRANSCRIPT)
        self.assertEqual(
            rendered["pairing_routes"],
            ["v1/broker/pairings/challenge", "v1/broker/pairings/redeem"],
        )
        self.assertTrue(rendered["outbound_only"])
        self.assertTrue(rendered["tls_required"])
        self.assertTrue(rendered["canonical_credential_store_reused"])
        self.assertFalse(rendered["public_inbound_port"])
        self.assertFalse(rendered["client_challenge_authority"])
        self.assertTrue(OUTBOUND_ONLY_ENROLLMENT)
        self.assertTrue(TLS_REQUIRED)
        self.assertTrue(CANONICAL_CREDENTIAL_STORE_REUSED)
        self.assertFalse(PUBLIC_INBOUND_PORT)
        self.assertFalse(UPNP_PORT_FORWARD_SUPPORTED)
        self.assertFalse(CALLER_ENDPOINT_OVERRIDE)
        self.assertFalse(CLIENT_CHALLENGE_AUTHORITY)
        self.assertFalse(RAW_PAIRING_CODE_LOGGED)
        self.assertFalse(RAW_DEVICE_CREDENTIAL_LOGGED)
        self.assertFalse(LIVE_BROKER_CONFIGURED)
        self.assertFalse(REAL_USER_PAIRING_CANARY)
        self.assertFalse(PRODUCTION_MUTATION)
        self.assertFalse(PRODUCTION_READY)


if __name__ == "__main__":
    unittest.main()
