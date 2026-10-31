"""Compare first real PC-offer frame at the two actual gateway entrypoints.

The production Service Binding transport is a test double: it hands the
unchanged frame to the actual Broker LivePcWssOffer actor and real SQLite.
No Cloudflare deployment or real PC is involved.
"""
import asyncio
import base64
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.canonical_connector_gateway_source_composition import CONNECTOR_GATEWAY_WSS_PATH
from app.com2_connector_websocket import create_com2_gateway
from app.connector_gateway_runtime_mount import maybe_dispatch_connector_gateway
from test_com2_connector_websocket import Broker, Identity, SECRET, signed
from test_4139_gateway_broker_do_upgrade import InternalRequest, Result, request

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps/padiem-broker"))
from storage import SqLiteDurableStorage
from com2_edge_proof import EdgeProofVerifier
from padiem_control_plane.broker_pending_pc_wss import LivePcWssOffer, NativePcWss


def test_pc_offer_first_frame_production_and_com2_match(monkeypatch, tmp_path):
    monkeypatch.setenv("PADIEM_COM2_PC_OFFER_RELAY_ENABLED", "true")
    frame = {"type": "pc_offer_begin", "device_id": "device.test",
             "public_key_b64": base64.b64encode(b"p" * 32).decode()}
    received = []
    class RawSocket:
        readyState = 1
        def send(self, value): received.append(json.loads(value))
        def close(self, *args): pass

    storage = SqLiteDurableStorage.open(str(tmp_path / "broker.sqlite"))
    try:
        actor = LivePcWssOffer(storage=storage, socket=NativePcWss(RawSocket()),
                               verifier=lambda **kw: True, nonce_factory=lambda: "a" * 64)
        class Binding:
            async def fetch(self, req):
                assert req.url.endswith("/internal/connector/pc-offer-4139")
                await actor.message(json.dumps(frame), owner_do=SimpleNamespace())
                return Result(status=101)

        workers = ModuleType("workers")
        workers.Request = InternalRequest
        monkeypatch.setitem(sys.modules, "workers", workers)
        config = {
            "PADIEM_CONNECTOR_GATEWAY_WSS_ENABLED": "enabled",
            "PADIEM_CONNECTOR_GATEWAY_RELEASE_SCOPE": "owner-controlled-production-4139",
            "PADIEM_CONNECTOR_PRODUCTION_ENABLED": "enabled",
            "PADIEM_CHAT_PUBLIC_BASE_URL": "https://chat.padiem.net",
            "IDENTITY_AUTHORITY_SERVICE": object(),
            "LOCAL_AGENT_BROKER_AUTHORITY_SERVICE": Binding(),
        }
        result = asyncio.run(maybe_dispatch_connector_gateway(
            request=request(url="https://chat.padiem.net" + CONNECTOR_GATEWAY_WSS_PATH),
            worker_env=config, response_factory=Result,
        ))
        assert result.status == 101
        assert received == [{"type": "pc_offer_challenge", "device_id": "device.test", "nonce_hex": "a" * 64}]

        # Test transport sends the same frame to the actual broker actor.
        # The real loopback route is separately implemented by the broker lane.
        import app.com2_pc_offer_relay as relay
        class Bridge:
            async def __aenter__(self):
                self.queue = asyncio.Queue()
                outer = self
                class ActorSocket:
                    closed = False
                    async def send_text(self, value):
                        await outer.queue.put(value)
                    async def close(self, *, code=1008):
                        self.closed = True
                self.actor = LivePcWssOffer(storage=storage, socket=ActorSocket(),
                    verifier=lambda **kw: True, nonce_factory=lambda: "a" * 64)
                return self
            async def __aexit__(self, *args): pass
            async def send(self, value):
                await self.actor.message(value, owner_do=SimpleNamespace())
            def __aiter__(self): return self
            async def __anext__(self): return await self.queue.get()
        monkeypatch.setattr(relay, "_upstream", lambda secret: Bridge())
        binding = Broker()
        binding._secret = SECRET
        host = create_com2_gateway(verifier=EdgeProofVerifier(SECRET, str(tmp_path / "seen.db")),
                                   identity_binding=Identity(), broker_binding=binding)
        with TestClient(host) as client:
            with client.websocket_connect(CONNECTOR_GATEWAY_WSS_PATH, headers=signed("f" * 32)) as ws:
                ws.send_json(frame)
                assert ws.receive_json() == received[0]
    finally:
        storage.close()


def test_broker_upgrade_request_id_is_covered_by_service_proof(monkeypatch):
    import app.com2_pc_offer_relay as relay
    from app.local_service_bridge import service_proof_headers
    captured = {}
    def connect(url, **kwargs):
        captured.update(url=url, **kwargs)
        return object()
    monkeypatch.setattr(relay, "_NoRedirect", connect)
    monkeypatch.setattr(relay.secrets, "token_hex", lambda n: "c" * 32)
    relay._upstream(SECRET)
    assert captured["url"] == "ws://127.0.0.1:8799" + relay.PATH
    headers = captured["extra_headers"]
    assert headers["x-padiem-request-id"] == "c" * 32
    at = int(headers["x-padiem-service-at"])
    expected = service_proof_headers(SECRET, method="GET", path=relay.PATH,
                                     body=b"c" * 32, at=at)
    assert headers["x-padiem-service-proof"] == expected["x-padiem-service-proof"]
