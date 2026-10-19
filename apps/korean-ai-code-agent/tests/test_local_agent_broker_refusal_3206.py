"""#3206 ? the non-Production shared-broker port refuses in bounded form.

The #3098 final real-Windows E2E reproduced a pairing refusal as a raw
``urllib.error.HTTPError`` escaping ``BrokerClientPort.post`` and crashing the
resident with a traceback. These regressions pin the bounded contract the
canonical Production adapter already honors:

* a 4xx carrying a valid bounded broker JSON error body reaches the canonical
  pairing client, which raises its own ``ContractError``;
* malformed, oversized or unreadable transports are bounded ``ContractError``
  at the port;
* the resident's refusal path therefore emits ``redemption_refused`` with no
  acknowledgement and no raw traceback;
* a replayed one-time code is denied by the authority without a second
  redemption.

No second pairing authority is introduced: every socket test crosses the same
canonical handler the owner process serves.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from kagent import local_agent_resident_process as resident_process
from kagent.contracts import ContractError
from kagent.local_agent_broker_pairing_client import LocalAgentBrokerPairingClient
from kagent.local_agent_broker_pairing_handoff_entry import (
    AUTHORITY_REF,
    BrokerClientPort,
    LoopbackPairingBroker,
)
from kagent.local_agent_resident_process import (
    HANDOFF_CONTRACT_VERSION,
    redeem_handoff,
)
from kagent.local_agent_secure_transport import (
    OutboundBrokerEndpoint,
    OutboundTransportConfig,
    OutboundTransportMode,
    StoredDeviceCredentialProjection,
)

BASE = datetime(2026, 9, 29, 0, 30, tzinfo=timezone.utc)
#: The owner's redeem route presents this fixed device principal; the possession
#: proof in the payload carries the redeeming device, so the ids may differ.
DEVICE_ID = "device.3140.resident"
CODE = "0123456789abcdef0123456789abcdef"
CHALLENGE_ID = "challenge.3206.1"
REFUSAL_CODE = "pairing_challenge_consumed"
REFUSAL_MESSAGE = "the challenge was already redeemed"


def _config() -> OutboundTransportConfig:
    return OutboundTransportConfig(
        endpoint=OutboundBrokerEndpoint(
            endpoint_ref="broker_endpoint_3206_refusal",
            url="https://local-agent.padiem.net:443/broker",
            mode=OutboundTransportMode.HTTPS_LONG_POLL,
        ),
        heartbeat_seconds=30,
        poll_timeout_seconds=15,
        max_response_bytes=65_536,
    )


class _CredentialStore:
    """Refusal paths must never touch the credential store; success saves once."""

    def __init__(self) -> None:
        self.saved: dict[str, bytes] = {}
        self.saves = 0

    def save(self, *, binding, credential: bytes, now: datetime) -> StoredDeviceCredentialProjection:
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

    def load(self, *, binding, now: datetime) -> bytes:
        del now
        return self.saved[binding.binding_ref]


def _client(port: BrokerClientPort) -> LocalAgentBrokerPairingClient:
    return LocalAgentBrokerPairingClient(
        config=_config(), credential_store=_CredentialStore(), request_port=port
    )


def _redeem(client: LocalAgentBrokerPairingClient, *, offset_seconds: int):
    return client.redeem(
        challenge_id=CHALLENGE_ID,
        pairing_code=CODE,
        device_id=DEVICE_ID,
        now=BASE + timedelta(seconds=offset_seconds),
    )


def _handoff() -> dict:
    return {
        "contract_version": HANDOFF_CONTRACT_VERSION,
        "pairing_code": CODE,
        "correlation_ref": "pairref.3206",
        "challenge_id": CHALLENGE_ID,
    }


class _ProtectedDataPort:
    """A portable protected-data double; the refusal path never uses it."""

    def _stream(self, entropy, length):
        out = b""
        block = 0
        while len(out) < length:
            out += hashlib.sha256(entropy + block.to_bytes(4, "big")).digest()
            block += 1
        return out[:length]

    def protect(self, credential, *, entropy):
        stream = self._stream(entropy, len(credential))
        return bytes(a ^ b for a, b in zip(credential, stream))

    def unprotect(self, protected, *, entropy):
        stream = self._stream(entropy, len(protected))
        return bytes(a ^ b for a, b in zip(protected, stream))


class _ScriptedBroker:
    """A loopback HTTP server that answers every POST with one scripted body."""

    def __init__(self, status: int, body: bytes) -> None:
        self.status = status
        self.body = body
        self.requests: list[str] = []
        self.statuses: list[int] = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802 ? stdlib surface
                length = int(self.headers.get("Content-Length", "0"))
                if length:
                    self.rfile.read(length)
                owner.requests.append(urlparse(self.path).path)
                owner.statuses.append(owner.status)
                self.send_response(owner.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(owner.body)))
                self.end_headers()
                self.wfile.write(owner.body)

            def log_message(self, *args) -> None:  # noqa: D102 ? silence
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


class _OwnerSurface:
    """The owner's exact loopback HTTP surface for one test process.

    Route principals are copied from the entry module's ``serve()`` so the
    socket tests cross the same canonical handler the owner serves, with no
    second authority anywhere in the chain.
    """

    def __init__(self) -> None:
        from padiem_control_plane.local_agent_broker_http import (
            TrustedLocalAgentHttpAuthContext,
        )

        # #3650: the host principal is now injected, never defaulted.
        self.broker = LoopbackPairingBroker(account_ref="account.1", workspace_ref="workspace.1")
        self.statuses: list[int] = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802 ? stdlib surface
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
                path = urlparse(self.path).path
                route = path if path.startswith("/v1/") else f"/{path.lstrip('/')}"
                if "pairings/challenge" in route:
                    auth = TrustedLocalAgentHttpAuthContext(
                        principal_ref="principal.browser.3140",
                        account_ref="account.1",
                        workspace_ref="workspace.1",
                        authenticated=True,
                        tls_verified=True,
                    )
                elif "pairings/redeem" in route:
                    auth = owner.broker._device_auth
                else:
                    auth = owner.broker._authenticated_device_auth
                response = owner.broker.handler.handle(
                    method="POST",
                    route=route,
                    content_type="application/json",
                    body=json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"),
                    auth=auth,
                )
                owner.statuses.append(response.status)
                out = json.dumps(response.body, sort_keys=True, separators=(",", ":")).encode("utf-8")
                self.send_response(response.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

            def log_message(self, *args) -> None:  # noqa: D102 ? silence
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def issue(self) -> tuple[str, str]:
        # Pin the owner's clock so the enrollment timestamps are deterministic
        # (the handler signs the enrollment with its own clock, not the payload).
        self.broker.clock.now = BASE
        issued = self.broker.web_issue_challenge(now=BASE)
        return issued["challenge"]["challenge_id"], issued["pairing_code"]

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


class NonProductionRefusal3206Test(unittest.TestCase):
    def test_a_canonical_4xx_rejection_is_a_bounded_refusal(self) -> None:
        body = json.dumps(
            {"ok": False, "error": {"code": REFUSAL_CODE, "message": REFUSAL_MESSAGE}},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        broker = _ScriptedBroker(400, body)
        try:
            client = _client(BrokerClientPort(broker.url))
            with self.assertRaises(ContractError) as caught:
                _redeem(client, offset_seconds=1)
            self.assertIn(REFUSAL_CODE, str(caught.exception))
            self.assertEqual(broker.requests, ["/v1/broker/pairings/redeem"])
        finally:
            broker.close()

    def test_a_malformed_4xx_body_is_a_bounded_contract_error(self) -> None:
        broker = _ScriptedBroker(400, b"{ this is not a json body")
        try:
            client = _client(BrokerClientPort(broker.url))
            with self.assertRaises(ContractError):
                _redeem(client, offset_seconds=1)
        finally:
            broker.close()

    def test_a_non_object_4xx_body_is_a_bounded_contract_error(self) -> None:
        broker = _ScriptedBroker(400, b'["not", "an", "object"]')
        try:
            client = _client(BrokerClientPort(broker.url))
            with self.assertRaises(ContractError) as caught:
                _redeem(client, offset_seconds=1)
            self.assertIn("HTTP status 400", str(caught.exception))
        finally:
            broker.close()

    def test_an_unreachable_broker_is_a_bounded_contract_error(self) -> None:
        probe = ThreadingHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
        closed_port = probe.server_address[1]
        probe.server_close()
        client = _client(BrokerClientPort(f"http://127.0.0.1:{closed_port}"))
        with self.assertRaises(ContractError):
            _redeem(client, offset_seconds=1)

    def test_a_replayed_code_over_the_socket_is_denied_without_a_second_redemption(self) -> None:
        surface = _OwnerSurface()
        try:
            challenge_id, pairing_code = surface.issue()
            store = _CredentialStore()
            client = LocalAgentBrokerPairingClient(
                config=_config(), credential_store=store, request_port=BrokerClientPort(surface.url)
            )
            first = client.redeem(
                challenge_id=challenge_id,
                pairing_code=pairing_code,
                device_id=DEVICE_ID,
                now=BASE + timedelta(seconds=1),
            )
            self.assertEqual(first.binding.state.value, "paired_offline")
            self.assertEqual(store.saves, 1)
            with self.assertRaises(ContractError):
                client.redeem(
                    challenge_id=challenge_id,
                    pairing_code=pairing_code,
                    device_id=DEVICE_ID,
                    now=BASE + timedelta(seconds=2),
                )
            self.assertEqual(store.saves, 1, "a replay must never enroll a second time")
            self.assertEqual(surface.statuses, [200, 400])
        finally:
            surface.close()

    @unittest.skipUnless(os.name == "nt", "the resident default protected-data port is Windows DPAPI")
    def test_a_rejected_resident_redemption_is_bounded_without_ack_or_traceback(self) -> None:
        body = json.dumps(
            {"ok": False, "error": {"code": REFUSAL_CODE, "message": REFUSAL_MESSAGE}},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        broker = _ScriptedBroker(400, body)
        credential_dir = tempfile.mkdtemp(prefix="claw1-3206-cred-")
        env_keys = (
            "PADIEM_AGENT_DEVICE_ID",
            "PADIEM_AGENT_AUTHORITY_REF",
            "PADIEM_AGENT_REQUEST_PORT",
            "PADIEM_AGENT_BROKER_URL",
            "PADIEM_AGENT_CREDENTIAL_DIR",
        )
        previous = {key: os.environ.get(key) for key in env_keys}
        os.environ.update(
            {
                "PADIEM_AGENT_DEVICE_ID": DEVICE_ID,
                "PADIEM_AGENT_AUTHORITY_REF": AUTHORITY_REF,
                "PADIEM_AGENT_REQUEST_PORT": "kagent.local_agent_broker_pairing_handoff_entry:make_request_port",
                "PADIEM_AGENT_BROKER_URL": broker.url,
                "PADIEM_AGENT_CREDENTIAL_DIR": credential_dir,
            }
        )
        old_stdin, old_stdout = sys.stdin, sys.stdout
        buffer = io.StringIO()
        try:
            sys.stdin = io.StringIO(
                json.dumps(_handoff(), sort_keys=True, separators=(",", ":")) + "\n"
            )
            sys.stdout = buffer
            exit_code = resident_process.main([])
        finally:
            sys.stdin = old_stdin
            sys.stdout = old_stdout
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            broker.close()
        output = buffer.getvalue()
        self.assertEqual(exit_code, 2)
        self.assertIn('"reason":"redemption_refused"', output)
        self.assertIn(REFUSAL_CODE, output)
        self.assertNotIn("handoff_ack", output, "a rejected redemption must never be acknowledged")
        self.assertNotIn("Traceback", output, "a bounded refusal must not print a raw traceback")

    def test_redeem_handoff_keeps_the_one_shot_armed_on_a_bounded_refusal(self) -> None:
        body = json.dumps(
            {"ok": False, "error": {"code": REFUSAL_CODE, "message": REFUSAL_MESSAGE}},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        broker = _ScriptedBroker(400, body)
        entry = resident_process.BrokerEntry(
            device_id=DEVICE_ID,
            authority_ref=AUTHORITY_REF,
            request_port=BrokerClientPort(broker.url),
            credential_dir=tempfile.mkdtemp(prefix="claw1-3206-entry-"),
        )
        acks: list[dict] = []
        try:
            with tempfile.TemporaryDirectory() as base_dir:
                with self.assertRaises(ContractError):
                    redeem_handoff(
                        _handoff(),
                        entry=entry,
                        base_dir=base_dir,
                        now=BASE + timedelta(seconds=1),
                        protected_data=_ProtectedDataPort(),
                        emit=acks.append,
                    )
        finally:
            broker.close()
        self.assertEqual(acks, [], "a refused redemption must not acknowledge ownership")
