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
from padiem_control_plane.local_agent_broker_pairing import pairing_proof_ref
from canonical_broker_gateway_bootstrap import bootstrap_mac, session_mac
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
async def test_real_pairing_bootstrap_direct_and_relay(monkeypatch, tmp_path):
    monkeypatch.setenv('PADIEM_COM2_PC_OFFER_RELAY_ENABLED', 'true')
    env = {'PADIEM_BROKER_RPC_INGRESS_SECRET': SECRET,
           'LOCAL_AGENT_BROKER_PEPPER': 'synthetic-pepper-' + 'y' * 32,
           'LOCAL_AGENT_BROKER_AUTHORITY_REF': 'staging.test',
           'LOCAL_AGENT_BROKER_PENDING_PC_OWNER_RPC_ENABLED': 'enabled',
           'LOCAL_AGENT_BROKER_PENDING_PC_SCHEMA_INSTALLED': 'installed',
           'LOCAL_AGENT_BROKER_PENDING_PC_RELEASE_SCOPE': 'isolated-operator-acceptance-4139',
           'LOCAL_AGENT_BROKER_PENDING_PC_WSS_ENABLED': 'enabled',
           'LOCAL_AGENT_BROKER_PENDING_PC_CANONICAL_BOOTSTRAP_ENABLED': 'enabled',
           'LOCAL_AGENT_BROKER_PAIRING_RPC_ENABLED': 'true',
           'LOCAL_AGENT_BROKER_PAIRING_SCHEMA_INSTALL_ENABLED': 'true',
           'LOCAL_AGENT_BROKER_PAIRING_SCHEMA_INSTALLED': 'true',
           'LOCAL_AGENT_BROKER_PAIRING_ISSUANCE_RATE_LIMIT': '5',
           'LOCAL_AGENT_BROKER_GATEWAY_BOOTSTRAP_SCHEMA_INSTALL_ENABLED': 'true',
           'LOCAL_AGENT_BROKER_GATEWAY_BOOTSTRAP_SCHEMA_INSTALLED': 'true',
           'LOCAL_AGENT_BROKER_GATEWAY_BOOTSTRAP_ENABLED': 'true',
           'LOCAL_AGENT_BROKER_PENDING_PC_IDENTITY_HANDOFF_ENABLED': 'enabled',
           'LOCAL_AGENT_BROKER_PENDING_PC_NATIVE_DELIVERY_ENABLED': 'enabled'}
    app = build_app(environ=env, db_path=str(tmp_path / 'broker.sqlite'))
    storage = app.state.broker_storage
    install_pending_pc_link_schema(storage=storage, migration_id=MIGRATION_ID, operator_gate=True)
    owner = app.state.broker
    installed = await owner.install_pairing_schema({'migration_id': 'canonical-broker-pairing-v1'})
    assert installed['ok'] is True
    installed = await owner.gateway_bootstrap_rpc({'operation': 'install', 'args': {'migration_id': 'canonical-broker-gateway-bootstrap-v1'}})
    assert installed['ok'] is True
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
        bs = serve(app, 8799)
        cs = serve(gateway)
        for _ in range(300):
            if bs[1].started and cs[1].started: break
            await asyncio.sleep(.01)
        assert bs[1].started and cs[1].started
        relay_url = f'ws://127.0.0.1:{cs[0].getsockname()[1]}{CONNECTOR_GATEWAY_WSS_PATH}'
        with pytest.raises(InvalidStatusCode):
            async with connect(relay_url): pass
        results = []
        for url, headers in ((f'ws://127.0.0.1:8799{BROKER_PATH}', broker_headers('a' * 32)),
                             (relay_url, edge_headers('b' * 32))):
            issued = await owner.issue_enrollment_challenge({'account_ref':'account.test', 'workspace_ref':'workspace.test', 'consent_ref':'consent.test', 'owner_ref':'subject.test', 'device_id': DEVICE})
            assert issued['ok'] is True
            cid, code = issued['challenge']['challenge_id'], issued['pairing_code']
            async with connect(url, extra_headers=headers) as ws:
                await ws.send(json.dumps({'type': 'pc_offer_begin', 'device_id': DEVICE,
                                          'public_key_b64': base64.b64encode(public).decode()}))
                challenge = json.loads(await asyncio.wait_for(ws.recv(), 5))
                transcript = (b'padiem.connector-pending-pc.v1\n' + DEVICE.encode() + b'\n'
                              + bytes.fromhex(challenge['nonce_hex']) + b'\n' + public)
                await ws.send(json.dumps({'type': 'pc_offer_prove', 'signature_b64': base64.b64encode(key.sign(transcript)).decode()}))
                ready = json.loads(await asyncio.wait_for(ws.recv(), 5))
                async with httpx.AsyncClient(base_url='http://127.0.0.1:8799') as client:
                    async def rpc(method, payload):
                        path = '/internal/rpc/' + method
                        body = json.dumps(payload, separators=(',', ':')).encode()
                        at = int(time.time())
                        return await client.post(path, content=body, headers={'x-padiem-service-at': str(at),
                            'x-padiem-service-proof': proof_for(SECRET, method='POST', path=path, at=at, body=body)})
                    reserved = await rpc('reserve_pending_pc_link', {'request_ref': ready['request_ref']})
                    assert reserved.status_code == 200 and reserved.json()['reserved_once'] is True
                    delivery = await rpc('deliver_pending_pc_link', {'request_ref': ready['request_ref'],
                        'device_id': DEVICE, 'challenge_id': cid, 'pairing_code': code})
                    assert delivery.status_code == 200 and delivery.json()['sent_once'] is True
                    approved = json.loads(await asyncio.wait_for(ws.recv(), 5))
                results.append((challenge['type'], ready['type'], approved['type'], approved['device_id']))
                proof = pairing_proof_ref(challenge_id=cid, device_id=DEVICE, pairing_code=code)
                await ws.send(json.dumps({'type':'begin','challenge_id':cid,'device_id':DEVICE,'proof_ref':proof}))
                nonce = json.loads(await asyncio.wait_for(ws.recv(), 5))
                assert nonce['type'] == 'nonce'
                mac = bootstrap_mac(pairing_code=code, challenge_id=cid, device_id=DEVICE,
                                    nonce_hex=nonce['nonce_hex'], lease_ref=nonce['lease_ref'])
                await ws.send(json.dumps({'type':'finish','lease_ref':nonce['lease_ref'],'proof_hex':mac}))
                verified = json.loads(await asyncio.wait_for(ws.recv(), 5))
                assert verified['type'] == 'bootstrap_verified'
                actor = next(a for a in owner._com2_pc_sessions if a._request_ref == ready['request_ref'])
                fetch_mac = session_mac(pairing_code=code, challenge_id=cid, device_id=DEVICE,
                                        nonce_hex=nonce['nonce_hex'], lease_ref=nonce['lease_ref'],
                                        action='credential_fetch', counter=1,
                                        payload_sha256=hashlib.sha256(b'').hexdigest())
                await ws.send(json.dumps({'type':'credential_fetch','counter':1,'proof_hex':fetch_mac}))
                for _ in range(200):
                    if actor._canonical_bootstrap._stage == 'identity_required':
                        break
                    await asyncio.sleep(.01)
                assert actor._canonical_bootstrap._stage == 'identity_required'
                assert not getattr(owner, '_pending_pc_wss_by_id', {})
                from padiem_control_plane.broker_pending_pc_identity_handoff import BrokerPcIdentityHandoffDenied
                with pytest.raises(BrokerPcIdentityHandoffDenied, match='pending_pc_identity_live_proof_missing'):
                    await owner.pending_pc_identity_status({'request_ref': ready['request_ref']})
                results[-1] += (nonce['type'], verified['type'])
        assert results == [('pc_offer_challenge','pc_offer_ready','pc_offer_approved',DEVICE,'nonce','bootstrap_verified')] * 2

    finally:
        for server in (cs, bs):
            if server:
                server[1].should_exit = True
                await asyncio.to_thread(server[2].join, 5)
                server[0].close()
        storage.close()
