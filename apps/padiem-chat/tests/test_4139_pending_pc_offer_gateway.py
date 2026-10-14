"""Source-only real Ed25519 key-possession PC offer over one fake WSS peer.

The Broker SQLite is real local sqlite3; the network ingress is synthetic.
No live Cloudflare route or hardware attestation is claimed.
"""
from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timezone
import hashlib
import json
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from app.connector_pending_pc_offer_gateway import (
    VerifiedPcOfferGateway, PendingOfferDenied, ownership_transcript,
    PENDING_PC_OFFER_SERVER_PRODUCTION_ENABLED,
    PENDING_PC_OFFER_WEBSOCKET_ROUTE_MOUNTED,
)
from app.connector_pending_pc_delivery import CanonicalPendingPcDelivery
from canonical_broker_pending_pc_link import (
    DurablePendingPcLink, install_pending_pc_link_schema, MIGRATION_ID,
)
from test_4139_pending_pc_delivery_adapter import Storage

DEVICE = "windows.device.1"
REF = "link." + "a" * 32
CODE = "e" * 32
CHALLENGE = "challenge.1"
NONCE = "b" * 64


class FakeSocket:
    def __init__(self, *, origin=None, cookie=None, tls=True):
        self.url = SimpleNamespace(scheme="wss" if tls else "ws")
        self.headers = {}
        if origin:
            self.headers["origin"] = origin
        if cookie:
            self.headers["cookie"] = cookie
        self.input = asyncio.Queue()
        self.output = asyncio.Queue()
        self.closed = False
    async def receive_text(self):
        return await self.input.get()
    async def send_text(self, data):
        await self.output.put(data)
    async def close(self, *, code=1008):
        self.closed = True


class TrustedIngress:
    def __init__(self):
        self.ok = True
    async def verify(self, socket):
        return self.ok and socket.url.scheme == "wss" and not socket.closed


class Broker:
    def __init__(self, *, socket, tls):
        self.storage = Storage()
        install_pending_pc_link_schema(
            storage=self.storage, migration_id=MIGRATION_ID, operator_gate=True,
        )
        self.gateway = None
        self.ledger = DurablePendingPcLink(
            storage=self.storage,
            canonical_broker_storage=self.storage,
            channel_verified=lambda ref, dev, finger: (
                self.gateway is not None
                and self.gateway.owns_live_channel(ref, dev, finger)
                and tls.ok and not socket.closed
            ),
            ref_factory=lambda: REF,
        )
    async def reserve_once(self, *, request_ref):
        return self.ledger.reserve_once(
            request_ref=request_ref, now=datetime.now(timezone.utc),
        )
    async def claim_delivery_once(self, *, request_ref, device_id):
        self.ledger.claim_delivery_once(
            request_ref=request_ref, device_id=device_id,
            now=datetime.now(timezone.utc),
        )
    def rows(self):
        return self.storage.exec(
            "SELECT * FROM canonical_broker_pending_pc_link",
        ).toArray()


def build(*, origin=None, cookie=None, tls_ok=True):
    socket = FakeSocket(origin=origin, cookie=cookie, tls=tls_ok)
    tls = TrustedIngress()
    broker = Broker(socket=socket, tls=tls)
    gateway = VerifiedPcOfferGateway(
        socket=socket, trusted_ingress=tls,
        pending_ledger=broker.ledger, nonce_factory=lambda: NONCE,
    )
    broker.gateway = gateway
    return socket, tls, broker, gateway


async def handshake(*, tamper=False):
    socket, tls, broker, gateway = build()
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    await socket.input.put(json.dumps({
        "type": "pc_offer_begin", "device_id": DEVICE,
        "public_key_b64": base64.b64encode(public).decode(),
    }))
    job = asyncio.create_task(gateway.accept_offer())
    challenge = json.loads(await asyncio.wait_for(socket.output.get(), 2))
    assert challenge == {
        "type": "pc_offer_challenge", "device_id": DEVICE, "nonce_hex": NONCE,
    }
    signature = private.sign(ownership_transcript(
        device_id=DEVICE, nonce_hex=NONCE, public_key=public,
    ))
    if tamper:
        signature = b"\x00" * 64
    await socket.input.put(json.dumps({
        "type": "pc_offer_prove",
        "signature_b64": base64.b64encode(signature).decode(),
    }))
    if tamper:
        with pytest.raises(PendingOfferDenied, match="signature_invalid"):
            await job
        return socket, tls, broker, gateway, None
    ready = json.loads(await asyncio.wait_for(socket.output.get(), 2))
    result = await job
    assert ready == {
        "type": "pc_offer_ready", "device_id": DEVICE,
        "request_ref": REF, "expires_at": result["expires_at"],
    }
    return socket, tls, broker, gateway, ready


def test_signed_offer_reserves_once_and_delivers_once_on_same_connection():
    async def run():
        socket, tls, broker, gateway, offer = await handshake()
        assert len(broker.rows()) == 1
        assert broker.rows()[0]["state"] == "pending"
        assert broker.rows()[0]["possession_key_sha256"] != CODE
        assert gateway.owns_live_channel(
            REF, DEVICE, broker.rows()[0]["possession_key_sha256"],
        )
        delivery = CanonicalPendingPcDelivery(broker=broker, socket=gateway)
        receipt = await delivery.reserve_once(request_ref=REF)
        assert receipt["reserved_once"] is True
        await delivery.deliver_once(
            request_ref=REF, device_id=DEVICE,
            challenge_id=CHALLENGE, pairing_code=CODE,
        )
        approved = json.loads(await socket.output.get())
        assert approved == {
            "type": "pc_offer_approved", "device_id": DEVICE,
            "request_ref": REF, "challenge_id": CHALLENGE,
            "pairing_code": CODE,
        }
        assert broker.rows()[0]["state"] == "delivery_claimed"
        assert CODE not in str(broker.rows())
        with pytest.raises(PendingOfferDenied, match="delivery_denied"):
            await gateway.send_once(
                request_ref=REF, device_id=DEVICE,
                challenge_id=CHALLENGE, pairing_code=CODE,
            )
        assert socket.output.empty()
    asyncio.run(run())


def test_fake_crypto_signature_never_creates_an_offer():
    async def run():
        socket, tls, broker, gateway, _ = await handshake(tamper=True)
        assert broker.rows() == []
        assert gateway._verified is False
        assert socket.output.empty()
        assert socket.closed is True
    asyncio.run(run())


def test_tls_cookie_and_origin_denied_before_framing_or_schema_mutation():
    async def run():
        for options in (
            {"tls_ok": False},
            {"origin": "https://evil.example"},
            {"cookie": "session=fake"},
        ):
            socket, tls, broker, gateway = build(**options)
            with pytest.raises(PendingOfferDenied, match="ingress_denied"):
                await gateway.accept_offer()
            assert socket.input.empty() and socket.output.empty()
            assert broker.rows() == []
            assert socket.closed is True
    asyncio.run(run())


def test_lost_channel_between_offer_and_owner_approval_does_not_reserve():
    async def run():
        socket, tls, broker, gateway, _ = await handshake()
        socket.closed = True
        delivery = CanonicalPendingPcDelivery(broker=broker, socket=gateway)
        with pytest.raises(Exception):
            await delivery.reserve_once(request_ref=REF)
        assert broker.rows()[0]["state"] == "pending"
        assert socket.output.empty()
    asyncio.run(run())


def test_lost_tls_after_reservation_never_sends_code():
    async def run():
        socket, tls, broker, gateway, _ = await handshake()
        delivery = CanonicalPendingPcDelivery(broker=broker, socket=gateway)
        await delivery.reserve_once(request_ref=REF)
        tls.ok = False
        with pytest.raises(Exception):
            await delivery.deliver_once(
                request_ref=REF, device_id=DEVICE,
                challenge_id=CHALLENGE, pairing_code=CODE,
            )
        assert socket.output.empty()
        assert broker.rows()[0]["state"] == "reserved"
    asyncio.run(run())


def test_one_offer_per_live_socket_even_with_valid_key():
    async def run():
        socket, tls, broker, gateway, _ = await handshake()
        with pytest.raises(PendingOfferDenied, match="already_used"):
            await gateway.accept_offer()
    asyncio.run(run())


def test_transcript_is_distinct_from_pairing_wss_domain():
    key = bytes(range(32))
    value = ownership_transcript(device_id=DEVICE, nonce_hex=NONCE, public_key=key)
    assert value.startswith(b"padiem.connector-pending-pc.v1\n")
    assert key in value
    assert b"connector-gateway-bootstrap" not in value


def test_offer_wire_source_remains_default_unmounted():
    assert PENDING_PC_OFFER_SERVER_PRODUCTION_ENABLED is False
    assert PENDING_PC_OFFER_WEBSOCKET_ROUTE_MOUNTED is False
