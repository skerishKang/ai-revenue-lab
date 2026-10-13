"""#4139 canonical Worker-binding admission and honest release state.

No real Cloudflare account, browser, cookies, production route, Broker or TLS.
The source-only app is never mounted into production here.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.canonical_connector_gateway_source_composition import (
    CONNECTOR_GATEWAY_WSS_PATH,
    CONNECTOR_GATEWAY_WSS_PRODUCTION_MOUNTED,
)
from app.connector_gateway_release_preflight import (
    RELEASE_PREFLIGHT_VERSION,
    inspect_checked_in_gateway_release,
)
from app.connector_gateway_worker_binding_composition import (
    WORKER_GATEWAY_PUBLIC_ENTRYPOINT_MOUNTED,
    WORKER_GATEWAY_SERVICE_BINDINGS_PRODUCTION_WIRED,
    WORKER_GATEWAY_TRUSTED_INGRESS_PRODUCTION_WIRED,
    build_review_only_gateway_from_worker_env,
)
from app.worker_config import (
    IDENTITY_AUTHORITY_SERVICE_BINDING_NAME,
    LOCAL_AGENT_BROKER_AUTHORITY_SERVICE_BINDING_NAME,
)

CHAT_ROOT = Path(__file__).resolve().parents[1]


class PrivateIdentity:
    async def resolve_connector_enrollment_consent_for_device(self, payload):
        raise AssertionError("untrusted PC may not resolve Identity")
    async def bind_connector_enrollment_challenge(self, payload):
        raise AssertionError("untrusted PC may not create consent")
    async def authorize_connector_enrollment_redeem(self, payload):
        raise AssertionError("untrusted PC may not authorize redeem")


class PrivateBroker:
    def __init__(self):
        self.operations = []
    async def gateway_bootstrap_rpc(self, payload):
        self.operations.append(payload)
        return {"ok": False, "error": {"code": "gateway_bootstrap_disabled",
                                        "message": "source review only"}}
    async def get_enrollment_binding(self, payload):
        raise AssertionError("untrusted PC cannot read binding")
    async def verify_enrollment_bootstrap(self, payload):
        raise AssertionError("untrusted PC cannot verify challenge")
    async def redeem_enrollment(self, payload):
        raise AssertionError("untrusted PC cannot consume credential")
    async def revoke_binding(self, payload):
        raise AssertionError("untrusted PC cannot revoke binding")


class UnverifiedIngress:
    def __init__(self):
        self.calls = 0
    async def verify(self, websocket):
        self.calls += 1
        return False


def test_source_default_never_exposes_gateway_or_uses_request_as_worker_env():
    env = {
        IDENTITY_AUTHORITY_SERVICE_BINDING_NAME: PrivateIdentity(),
        LOCAL_AGENT_BROKER_AUTHORITY_SERVICE_BINDING_NAME: PrivateBroker(),
    }
    with pytest.raises(RuntimeError, match="not activated"):
        build_review_only_gateway_from_worker_env(
            worker_env=env, trusted_tls_ingress=UnverifiedIngress(),
        )
    with pytest.raises(RuntimeError, match="not activated"):
        build_review_only_gateway_from_worker_env(
            worker_env=env, trusted_tls_ingress=UnverifiedIngress(),
            source_test_authorized=1,
        )
    with pytest.raises(ValueError, match="environment unavailable"):
        build_review_only_gateway_from_worker_env(
            source_test_authorized=True,
            trusted_tls_ingress=UnverifiedIngress(),
        )


@pytest.mark.parametrize("missing", [
    IDENTITY_AUTHORITY_SERVICE_BINDING_NAME,
    LOCAL_AGENT_BROKER_AUTHORITY_SERVICE_BINDING_NAME,
])
def test_missing_single_canonical_private_service_fails_before_route_construction(missing):
    env = {
        IDENTITY_AUTHORITY_SERVICE_BINDING_NAME: PrivateIdentity(),
        LOCAL_AGENT_BROKER_AUTHORITY_SERVICE_BINDING_NAME: PrivateBroker(),
    }
    env.pop(missing)
    with pytest.raises(ValueError, match="private bindings unavailable"):
        build_review_only_gateway_from_worker_env(
            worker_env=env, trusted_tls_ingress=UnverifiedIngress(),
            source_test_authorized=True,
        )


def test_no_header_or_user_supplied_forwarding_fact_can_replace_trusted_tls():
    broker, ingress = PrivateBroker(), UnverifiedIngress()
    env = SimpleNamespace(
        IDENTITY_AUTHORITY_SERVICE=PrivateIdentity(),
        LOCAL_AGENT_BROKER_AUTHORITY_SERVICE=broker,
    )
    app = build_review_only_gateway_from_worker_env(
        worker_env=env, trusted_tls_ingress=ingress,
        source_test_authorized=True,
    )
    assert len(app.routes) == 1
    assert app.routes[0].path == CONNECTOR_GATEWAY_WSS_PATH
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect(
                "wss://testserver" + CONNECTOR_GATEWAY_WSS_PATH,
                headers={
                    "x-forwarded-proto": "wss",
                    "cf-visitor": '{"scheme":"https"}',
                    "cf-tls-client-auth": "SUCCESS",
                    "x-padiem-device-id": "device.attacker",
                },
            ):
                pytest.fail("unverified ingress must never accept")
    assert exc.value.code == 1008
    assert ingress.calls == 1 and broker.operations == []


def test_worker_composition_refuses_raw_request_headers_in_place_of_ingress_port():
    broker = PrivateBroker()
    env = {
        IDENTITY_AUTHORITY_SERVICE_BINDING_NAME: PrivateIdentity(),
        LOCAL_AGENT_BROKER_AUTHORITY_SERVICE_BINDING_NAME: broker,
    }
    with pytest.raises(ValueError, match="TLS ingress verifier missing"):
        build_review_only_gateway_from_worker_env(
            worker_env=env,
            trusted_tls_ingress={"cf-tls-client-auth": "SUCCESS"},
            source_test_authorized=True,
        )
    assert broker.operations == []


def test_checked_in_worker_cannot_be_misrepresented_as_production_ready():
    manifest = (CHAT_ROOT / "wrangler.toml").read_text(encoding="utf-8")
    source = (CHAT_ROOT / "worker.py").read_text(encoding="utf-8")
    receipt = inspect_checked_in_gateway_release(
        wrangler_toml=manifest, worker_entrypoint_source=source,
    )
    assert receipt.deployment_ready is False
    assert receipt.evidence_scope == "repository_source_only"
    assert receipt.contract_version == RELEASE_PREFLIGHT_VERSION
    assert receipt.missing_required_bindings == tuple(sorted((
        IDENTITY_AUTHORITY_SERVICE_BINDING_NAME,
        LOCAL_AGENT_BROKER_AUTHORITY_SERVICE_BINDING_NAME,
    )))
    assert "B14_SERVICE" in receipt.declared_bindings
    assert "required_private_service_bindings_not_declared" in receipt.blockers
    assert "worker_tls_ingress_provenance_not_verified" in receipt.blockers
    assert "public_worker_wss_route_not_mounted" in receipt.blockers
    assert "two_pc_owner_consent_dpapi_restart_heartbeat_e2e_not_proven" in receipt.blockers
    assert WORKER_GATEWAY_PUBLIC_ENTRYPOINT_MOUNTED is False
    assert WORKER_GATEWAY_SERVICE_BINDINGS_PRODUCTION_WIRED is False
    assert WORKER_GATEWAY_TRUSTED_INGRESS_PRODUCTION_WIRED is False
    assert CONNECTOR_GATEWAY_WSS_PRODUCTION_MOUNTED is False
    safe = receipt.safe_dict()
    assert safe["deployment_ready"] is False
    assert set(safe) == {
        "contract_version", "evidence_scope", "deployment_ready",
        "declared_bindings", "missing_required_bindings", "blockers",
    }
    assert "credential" not in str(safe).lower()


def test_declarations_cannot_fake_edge_attestation_or_release_gates():
    doc = (
        'name = "test"\n'
        '[[services]]\nbinding = "IDENTITY_AUTHORITY_SERVICE"\nservice = "canonical-identity"\n'
        '[[services]]\nbinding = "LOCAL_AGENT_BROKER_AUTHORITY_SERVICE"\nservice = "canonical-broker"\n'
    )
    report = inspect_checked_in_gateway_release(
        wrangler_toml=doc,
        worker_entrypoint_source="build_review_only_gateway_from_worker_env(...)",
    )
    assert report.missing_required_bindings == ()
    assert report.deployment_ready is False
    assert "worker_tls_ingress_provenance_not_verified" in report.blockers
    assert "public_worker_wss_route_not_mounted" in report.blockers


@pytest.mark.parametrize("bad", [
    "not valid TOML!!",
    '[[services]]\nbinding="DUPLICATE"\n[[services]]\nbinding="DUPLICATE"\n',
    "[services]\nbinding = 'IDENTITY_AUTHORITY_SERVICE'\n",
    "[[services]]\nservice='unnamed'\n",
])
def test_bad_source_declarations_fail_closed_without_guessing_service_authority(bad):
    with pytest.raises(ValueError):
        inspect_checked_in_gateway_release(
            wrangler_toml=bad, worker_entrypoint_source="",
        )
