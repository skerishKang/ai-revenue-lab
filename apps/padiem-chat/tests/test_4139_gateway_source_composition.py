"""#4139 source-composition targeted checks. No live Windows/Cloudflare calls."""
from __future__ import annotations

import asyncio

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.canonical_connector_gateway_source_composition import (
    CONNECTOR_GATEWAY_WSS_PATH,
    CONNECTOR_GATEWAY_WSS_PRODUCTION_MOUNTED,
    CONNECTOR_GATEWAY_WORKER_TLS_PROVENANCE_WIRED,
    create_review_only_connector_gateway_app,
)
from app.control_plane_broker_pairing_client import CloudflareCanonicalBrokerPairingClient
from app.control_plane_identity import IdentityBridgeError


class IdentityBinding:
    async def resolve_connector_enrollment_consent_for_device(self, payload):
        raise AssertionError("No Identity call before Broker challenge proof")

    async def bind_connector_enrollment_challenge(self, payload):
        raise AssertionError("New challenge minting is forbidden")

    async def authorize_connector_enrollment_redeem(self, payload):
        raise AssertionError("No consent check before successful Gateway proof")


class BrokerBinding:
    def __init__(self):
        self.calls = []

    async def gateway_bootstrap_rpc(self, payload):
        self.calls.append(payload)
        return {"ok": False, "error": {
            "code": "gateway_bootstrap_disabled",
            "message": "disabled",
        }}

    async def get_enrollment_binding(self, payload):
        raise AssertionError("Must not redeem on refused bootstrap")

    async def verify_enrollment_bootstrap(self, payload):
        raise AssertionError("Must not call Host on refused bootstrap")

    async def redeem_enrollment(self, payload):
        raise AssertionError("No credential issuance on refused bootstrap")

    async def revoke_binding(self, payload):
        raise AssertionError("No canonical binding exists to revoke")


class Ingress:
    def __init__(self, verified):
        self.verified = verified
        self.calls = 0

    async def verify(self, websocket):
        self.calls += 1
        return self.verified


def test_review_only_gateway_has_no_default_production_mount():
    assert CONNECTOR_GATEWAY_WSS_PRODUCTION_MOUNTED is False
    assert CONNECTOR_GATEWAY_WORKER_TLS_PROVENANCE_WIRED is False
    with pytest.raises(RuntimeError):
        create_review_only_connector_gateway_app()
    with pytest.raises(RuntimeError):
        create_review_only_connector_gateway_app(
            source_test_authorized=1,
            identity_binding=IdentityBinding(),
            broker_binding=BrokerBinding(),
            trusted_tls_ingress=Ingress(True),
        )


def test_all_authoritative_private_ports_are_required_before_route_construction():
    identity = IdentityBinding()
    broker = BrokerBinding()
    verifier = Ingress(True)
    for identity_port, broker_port, ingress_port in (
        (None, broker, verifier), (identity, None, verifier),
        (identity, broker, None),
        (object(), broker, verifier), (identity, object(), verifier),
    ):
        with pytest.raises(ValueError):
            create_review_only_connector_gateway_app(
                source_test_authorized=True,
                identity_binding=identity_port,
                broker_binding=broker_port,
                trusted_tls_ingress=ingress_port,
            )


def test_rejected_peer_cannot_reach_private_broker_or_identity():
    broker = BrokerBinding()
    ingress = Ingress(False)
    app = create_review_only_connector_gateway_app(
        source_test_authorized=True, identity_binding=IdentityBinding(),
        broker_binding=broker, trusted_tls_ingress=ingress,
    )
    assert len(app.routes) == 1 and app.routes[0].path == CONNECTOR_GATEWAY_WSS_PATH
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as error:
            with client.websocket_connect(CONNECTOR_GATEWAY_WSS_PATH):
                pass
    assert error.value.code == 1008
    assert ingress.calls == 1 and broker.calls == []


def test_fake_header_never_replaces_actual_trusted_tls_verifier():
    broker = BrokerBinding()
    ingress = Ingress(False)
    app = create_review_only_connector_gateway_app(
        source_test_authorized=True, identity_binding=IdentityBinding(),
        broker_binding=broker, trusted_tls_ingress=ingress,
    )
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(CONNECTOR_GATEWAY_WSS_PATH, headers={
                "X-Forwarded-Proto": "wss",
                "Cf-Tls-Client-Auth": "SUCCESS",
                "X-Padiem-Device-Id": "device.forged",
            }):
                pass
    assert broker.calls == []


def test_valid_ingress_still_cannot_issue_a_credential_when_broker_refuses():
    broker = BrokerBinding()
    ingress = Ingress(True)
    app = create_review_only_connector_gateway_app(
        source_test_authorized=True, identity_binding=IdentityBinding(),
        broker_binding=broker, trusted_tls_ingress=ingress,
    )
    begin = {
        "type": "begin",
        "challenge_id": "pairing." + "a" * 32,
        "device_id": "device.1",
        "proof_ref": "pairing-proof:" + "b" * 64,
    }
    with TestClient(app) as client:
        with client.websocket_connect(CONNECTOR_GATEWAY_WSS_PATH) as ws:
            ws.send_json(begin)
            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()
    assert broker.calls == [{
        "operation": "begin",
        "args": {k: begin[k] for k in ("challenge_id", "device_id", "proof_ref")},
    }]
    assert ingress.calls == 1


def test_gateway_cannot_use_private_rpc_for_migrations_or_arbitrary_method():
    broker = BrokerBinding()
    client = CloudflareCanonicalBrokerPairingClient(broker)
    for payload in (
        {"operation": "install", "args": {"migration_id": "unapproved"}},
        {"operation": "unknown", "args": {}},
        {"operation": "begin", "args": {"challenge_id": "pairing.1"}},
        {"operation": "begin", "args": {"challenge_id": "pairing.1",
                                      "device_id": "device.1", "proof_ref": "x",
                                      "owner_ref": "forged"}},
    ):
        with pytest.raises(IdentityBridgeError):
            asyncio.run(client.gateway_bootstrap_rpc(payload))
    assert broker.calls == []
