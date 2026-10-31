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


def test_pc_offer_first_frame_production_and_com2_are_not_equivalent(monkeypatch, tmp_path):
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

        host = create_com2_gateway(verifier=EdgeProofVerifier(SECRET, str(tmp_path / "seen.db")),
                                   identity_binding=Identity(), broker_binding=Broker())
        with TestClient(host) as client:
            with client.websocket_connect(CONNECTOR_GATEWAY_WSS_PATH, headers=signed("f" * 32)) as ws:
                ws.send_json(frame)
                with pytest.raises(WebSocketDisconnect) as closed:
                    ws.receive_json()
        assert closed.value.code == 1011
    finally:
        storage.close()
