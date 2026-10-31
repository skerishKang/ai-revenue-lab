"""COM2 Chat relay to the actual broker route over loopback, with edge proof."""
import asyncio
import base64
import hashlib
import hmac
import json
import socket
import sys
import threading
import time
from pathlib import Path

import httpx
import pytest
import uvicorn
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from websockets.exceptions import InvalidStatusCode, ConnectionClosed
from websockets.legacy.client import connect

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'apps/padiem-broker'))
sys.path.insert(0, str(ROOT / 'packages/padiem-control-plane'))
from service import build_app
from internal_rpc_ingress import proof_for
from padiem_control_plane.pending_pc_link import install_pending_pc_link_schema, MIGRATION_ID
from com2_edge_proof import EdgeProofVerifier
from app.com2_connector_websocket import create_com2_gateway
from app.com2_edge_middleware import EdgeProofMiddleware
from app.canonical_connector_gateway_source_composition import CONNECTOR_GATEWAY_WSS_PATH
from test_com2_connector_websocket import Broker, Identity

SECRET = 'synthetic-service-' + 'x' * 32
DEVICE = 'device.test'
BROKER_PATH = '/internal/connector/pc-offer-4139'


def serve(app, port=0):
    sock = socket.socket()
    sock.bind(('127.0.0.1', port))
    sock.listen(128)
    server = uvicorn.Server(uvicorn.Config(app, log_level='critical', lifespan='off'))
    thread = threading.Thread(target=server.run, kwargs={'sockets': [sock]}, daemon=True)
    thread.start()
    return sock, server, thread


def edge_headers(rid):
    at = str(int(time.time()))
    raw = '\n'.join(('v1', 'GET', CONNECTOR_GATEWAY_WSS_PATH, at, rid, 'TLSv1.3')).encode()
    return {'x-padiem-edge-at': at, 'x-padiem-edge-id': rid,
            'x-padiem-edge-tls': 'TLSv1.3',
            'x-padiem-edge-proof': 'v1=' + hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()}


def broker_headers(rid):
    at = int(time.time())
    return {'x-padiem-request-id': rid, 'x-padiem-service-at': str(at),
            'x-padiem-service-proof': proof_for(SECRET, method='GET', path=BROKER_PATH, at=at, body=rid.encode())}


@pytest.mark.asyncio
async def test_actual_relay_broker_offer_and_signed_edge(monkeypatch, tmp_path):
    monkeypatch.setenv('PADIEM_COM2_PC_OFFER_RELAY_ENABLED', 'true')
    env = {'PADIEM_BROKER_RPC_INGRESS_SECRET': SECRET,
           'LOCAL_AGENT_BROKER_PEPPER': 'synthetic-pepper-' + 'y' * 32,
           'LOCAL_AGENT_BROKER_AUTHORITY_REF': 'staging.test',
           'LOCAL_AGENT_BROKER_PENDING_PC_OWNER_RPC_ENABLED': 'enabled',
           'LOCAL_AGENT_BROKER_PENDING_PC_SCHEMA_INSTALLED': 'installed',
           'LOCAL_AGENT_BROKER_PENDING_PC_RELEASE_SCOPE': 'isolated-operator-acceptance-4139',
           'LOCAL_AGENT_BROKER_PENDING_PC_WSS_ENABLED': 'enabled',
           'LOCAL_AGENT_BROKER_PENDING_PC_CANONICAL_BOOTSTRAP_ENABLED': 'enabled'}
    app = build_app(environ=env, db_path=str(tmp_path / 'broker.sqlite'))
    storage = app.state.broker_storage
    install_pending_pc_link_schema(storage=storage, migration_id=MIGRATION_ID, operator_gate=True)
    # Fixed test fixture key from RFC 8032. No keys are generated.
    key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex('9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60'))
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    binding = Broker()
    binding._secret = SECRET
    secret_file = tmp_path / 'edge-secret.txt'
    secret_file.write_text(SECRET, encoding='utf-8')
    verifier = EdgeProofVerifier(secret_file.read_text(encoding='utf-8'), str(tmp_path / 'edge-replay.sqlite'))
    gateway = EdgeProofMiddleware(create_com2_gateway(verifier=verifier, identity_binding=Identity(), broker_binding=binding), verifier=verifier)
    bs = cs = None
    try:
        # #5992: try to bind the broker to 8799 first; if occupied, use a free
        # port and update all broker references accordingly.
        try:
            bs = serve(app, 8799)
            broker_port = 8799
        except OSError:
            bs = serve(app, 0)
            broker_port = bs[0].getsockname()[1]
        broker_addr = f'http://127.0.0.1:{broker_port}'
        broker_wss = f'ws://127.0.0.1:{broker_port}'
        cs = serve(gateway)
        for _ in range(300):
            if bs[1].started and cs[1].started: break
            await asyncio.sleep(.01)
        assert bs[1].started and cs[1].started
        relay_url = f'ws://127.0.0.1:{cs[0].getsockname()[1]}{CONNECTOR_GATEWAY_WSS_PATH}'
        with pytest.raises(InvalidStatusCode):
            async with connect(relay_url): pass
        results = []
        for url, headers in ((f'{broker_wss}{BROKER_PATH}', broker_headers('a' * 32)),
                              (relay_url, edge_headers('b' * 32))):
            async with connect(url, extra_headers=headers) as ws:
                await ws.send(json.dumps({'type': 'pc_offer_begin', 'device_id': DEVICE,
                                          'public_key_b64': base64.b64encode(public).decode()}))
                challenge = json.loads(await asyncio.wait_for(ws.recv(), 5))
                transcript = (b'padiem.connector-pending-pc.v1\n' + DEVICE.encode() + b'\n'
                              + bytes.fromhex(challenge['nonce_hex']) + b'\n' + public)
                await ws.send(json.dumps({'type': 'pc_offer_prove', 'signature_b64': base64.b64encode(key.sign(transcript)).decode()}))
                ready = json.loads(await asyncio.wait_for(ws.recv(), 5))
                async with httpx.AsyncClient(base_url=broker_addr) as client:
                    async def rpc(method, payload):
                        path = '/internal/rpc/' + method
                        body = json.dumps(payload, separators=(',', ':')).encode()
                        at = int(time.time())
                        return await client.post(path, content=body, headers={'x-padiem-service-at': str(at),
                            'x-padiem-service-proof': proof_for(SECRET, method='POST', path=path, at=at, body=body)})
                    reserved = await rpc('reserve_pending_pc_link', {'request_ref': ready['request_ref']})
                    assert reserved.status_code == 200 and reserved.json()['reserved_once'] is True
                    delivery = await rpc('deliver_pending_pc_link', {'request_ref': ready['request_ref'],
                        'device_id': DEVICE, 'challenge_id': 'pairing.' + 'f' * 32, 'pairing_code': 'd' * 32})
                    assert delivery.status_code == 200 and delivery.json()['sent_once'] is True
                    approved = json.loads(await asyncio.wait_for(ws.recv(), 5))
                results.append((challenge['type'], ready['type'], approved['type'], approved['device_id']))
                # The synthetic approval has no issued canonical pairing record; fail closed.
                await ws.send(json.dumps({'type': 'begin', 'challenge_id': 'pairing.' + 'f' * 32,
                    'device_id': DEVICE, 'proof_ref': 'pairing-proof:' + 'b' * 64}))
                with pytest.raises(ConnectionClosed) as closed:
                    await asyncio.wait_for(ws.recv(), 5)
                results[-1] += (closed.value.code,)
        assert results == [('pc_offer_challenge', 'pc_offer_ready', 'pc_offer_approved', DEVICE, 1008)] * 2
    finally:
        for server in (cs, bs):
            if server:
                server[1].should_exit = True
                await asyncio.to_thread(server[2].join, 5)
                server[0].close()
        storage.close()
