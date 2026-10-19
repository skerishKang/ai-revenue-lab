"""One connected, source-only WSS duplex exercising BOTH real PC + server v1 code.

Ed25519 handshake → existing Broker SQLite one-use slot → canonical owner
consent/issue composition → SAME socket code delivery → existing Windows WSS
enrollment entry point (stubbed before real DPAPI). This is not live evidence.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
import sys
import json
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "claw-connect"))

from claw_connect.pending_pc_offer import (
    run_pending_pc_offer_and_enroll, pending_owner_approval_url,
)
from claw_connect.device_wss_enrollment import DeviceSessionRefused
from app.connector_pending_pc_offer_gateway import VerifiedPcOfferGateway
from app.connector_pending_pc_delivery import CanonicalPendingPcDelivery
from app.connector_one_click_approval import OneClickOwnerApproval
from padiem_control_plane.pending_pc_link import (
    DurablePendingPcLink, install_pending_pc_link_schema, MIGRATION_ID,
)
from test_4139_connector_one_click_approval import Fixture as CanonicalFixture, session
from test_4139_pending_pc_delivery_adapter import Storage
from test_4139_pending_pc_offer_gateway import TestVerifier

DEVICE = "windows.device.1"
REF = "link." + "a" * 32
CODE = "b" * 32
NONCE = "c" * 64


class Duplex:
    def __init__(self):
        self.pc_to_server = asyncio.Queue()
        self.server_to_pc = asyncio.Queue()
        self.frames_from_pc = []
        self.frames_from_server = []
        self.closed = False
        outer = self

        class Server:
            url = SimpleNamespace(scheme="wss")
            headers = {}
            @property
            def closed(self):
                return outer.closed
            async def receive_text(self):
                return await asyncio.wait_for(outer.pc_to_server.get(), 5)
            async def send_text(self, raw):
                outer.frames_from_server.append(json.loads(raw))
                await outer.server_to_pc.put(raw)
            async def close(self, *, code=1008):
                outer.closed = True
        class Pc:
            @property
            def closed(self):
                return outer.closed
            async def receive_text(self):
                return await asyncio.wait_for(outer.server_to_pc.get(), 5)
            async def send_text(self, raw):
                outer.frames_from_pc.append(json.loads(raw))
                await outer.pc_to_server.put(raw)
            async def close(self):
                outer.closed = True
        self.server = Server()
        self.pc = Pc()


class Trusted:
    async def verify(self, socket):
        return not socket.closed


class BrokerPort:
    def __init__(self, duplex):
        self.storage = Storage()
        install_pending_pc_link_schema(
            storage=self.storage, migration_id=MIGRATION_ID,
            operator_gate=True,
        )
        self.gateway = None
        self.ledger = DurablePendingPcLink(
            storage=self.storage, canonical_broker_storage=self.storage,
            channel_verified=lambda ref, dev, digest: (
                self.gateway is not None
                and self.gateway.owns_live_channel(ref, dev, digest)
                and not duplex.closed
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
            "SELECT * FROM canonical_broker_pending_pc_link"
        ).toArray()


def test_real_pc_and_real_server_protocol_frames_agree_on_same_socket(monkeypatch):
    # The PC runtime uses an explicit isolated Ed25519 dependency; B62 Worker
    # must not vendor cryptography/cffi into Pyodide merely to run this test.
    pytest.importorskip("cryptography")
    import claw_connect.device_wss_enrollment as original

    async def run():
        duplex = Duplex()
        broker = BrokerPort(duplex)
        gateway = VerifiedPcOfferGateway(
            socket=duplex.server, trusted_ingress=Trusted(),
            pending_ledger=broker.ledger,
            key_verifier=TestVerifier(), nonce_factory=lambda: NONCE,
        )
        broker.gateway = gateway
        canonical = CanonicalFixture()
        delivery = CanonicalPendingPcDelivery(broker=broker, socket=gateway)
        owner = OneClickOwnerApproval(
            identity=canonical, host=canonical, pc_rendezvous=delivery,
        )
        done = []
        browser_urls = []
        canonical_started = []
        saved_tasks = []

        def browser(url):
            browser_urls.append(url)
            assert url == pending_owner_approval_url(REF)
            assert CODE not in url
            async def approve():
                response = await owner.approve(
                    owner_session=session(), request_ref=REF, confirmed=True,
                )
                done.append(response)
            saved_tasks.append(asyncio.create_task(approve()))

        async def existing_wss(**kwargs):
            # The actual existing WSS/DPAPI state machine is independently
            # covered; this test proves the handoff keeps the same socket.
            assert kwargs["socket"] is duplex.pc
            assert kwargs["challenge_id"] == "challenge.1"
            assert kwargs["pairing_code"] == CODE
            assert kwargs["trusted_tls"].__class__ is Trusted
            canonical_started.append(kwargs)
            return "existing_wss_dpapi_entrypoint"

        monkeypatch.setattr(original, "run_and_stage_review_only_device_enrollment", existing_wss)
        server = asyncio.create_task(gateway.accept_offer())
        pc = asyncio.create_task(run_pending_pc_offer_and_enroll(
            socket=duplex.pc, trusted_tls=Trusted(),
            enrollment=SimpleNamespace(
                record=lambda: SimpleNamespace(device_id=DEVICE),
            ),
            receiver=object(), owner_approval_open=browser,
        ))
        receipt, result = await asyncio.wait_for(
            asyncio.gather(server, pc), timeout=8,
        )
        assert result == "existing_wss_dpapi_entrypoint"
        assert receipt["request_ref"] == REF
        await asyncio.gather(*saved_tasks)
        assert len(done) == 1
        assert done[0]["state"] == "awaiting_device_confirmation"
        assert done[0]["connected"] is False
        assert done[0]["registered"] is False
        assert len(canonical_started) == 1
        assert len(browser_urls) == 1
        assert [item["type"] for item in duplex.frames_from_pc] == [
            "pc_offer_begin", "pc_offer_prove",
        ]
        assert [item["type"] for item in duplex.frames_from_server] == [
            "pc_offer_challenge", "pc_offer_ready", "pc_offer_approved",
        ]
        assert CODE not in repr(broker.rows())
        assert broker.rows()[0]["state"] == "delivery_claimed"
        assert duplex.closed is True
    asyncio.run(run())
