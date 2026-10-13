"""Worker ASGI dispatch source-test only. Zero Cloudflare network or credential."""
from __future__ import annotations

import asyncio
import sys
from types import ModuleType, SimpleNamespace

import pytest

from app.canonical_connector_gateway_source_composition import CONNECTOR_GATEWAY_WSS_PATH
from app.connector_gateway_worker_asgi_review import (
    REVIEW_WORKER_WSS_URL, WORKER_GATEWAY_ASGI_FETCH_PRODUCTION_WIRED,
    dispatch_review_only_worker_wss_upgrade,
)
from app.worker_config import (
    IDENTITY_AUTHORITY_SERVICE_BINDING_NAME,
    LOCAL_AGENT_BROKER_AUTHORITY_SERVICE_BINDING_NAME,
)

_IDENTITY_METHODS = {
    "resolve_connector_enrollment_consent_for_device",
    "bind_connector_enrollment_challenge",
    "authorize_connector_enrollment_redeem",
}
_BROKER_METHODS = {
    "gateway_bootstrap_rpc", "get_enrollment_binding",
    "verify_enrollment_bootstrap", "redeem_enrollment", "revoke_binding",
}


class PrivateBinding:
    def __init__(self, names):
        self.names = names
    def __getattr__(self, attr):
        if attr in self.names:
            async def deny(payload):
                raise AssertionError("source test must not call Broker/Identity")
            return deny
        raise AttributeError(attr)


class ReviewIngress:
    async def verify(self, websocket):
        return False


def env():
    return {
        IDENTITY_AUTHORITY_SERVICE_BINDING_NAME: PrivateBinding(_IDENTITY_METHODS),
        LOCAL_AGENT_BROKER_AUTHORITY_SERVICE_BINDING_NAME: PrivateBinding(_BROKER_METHODS),
    }


def request(url=REVIEW_WORKER_WSS_URL, headers=None):
    return SimpleNamespace(url=url, headers={"upgrade": "websocket"} if headers is None else headers)


def run(*, req=None, worker_env=None, trusted=None, allowed=True):
    return asyncio.run(dispatch_review_only_worker_wss_upgrade(
        request=request() if req is None else req,
        worker_env=env() if worker_env is None else worker_env,
        trusted_tls_ingress=ReviewIngress() if trusted is None else trusted,
        source_test_authorized=allowed,
    ))


def test_asgi_source_only_default_blocked_before_cloudflare_module_import():
    assert WORKER_GATEWAY_ASGI_FETCH_PRODUCTION_WIRED is False
    assert REVIEW_WORKER_WSS_URL == "https://chat.padiem.net" + CONNECTOR_GATEWAY_WSS_PATH
    with pytest.raises(RuntimeError, match="not activated"):
        run(allowed=False)
    with pytest.raises(RuntimeError, match="not activated"):
        run(allowed=1)


@pytest.mark.parametrize("url", [
    "http://chat.padiem.net/api/claw/connector/gateway/session",
    "wss://chat.padiem.net/api/claw/connector/gateway/session",
    "https://chat.padiem.net:443/api/claw/connector/gateway/session",
    "https://attacker.example/api/claw/connector/gateway/session",
    "https://chat.padiem.net.evil.example/api/claw/connector/gateway/session",
    "https://chat.padiem.net/api/claw/connector/gateway/session?token=secret",
    "https://chat.padiem.net/api/claw/connector/gateway/../session",
    "https://chat.padiem.net/api/claw/connector/gateway/%73ession",
])
def test_source_bridge_rejects_unreviewed_worker_upgrade_targets(url):
    with pytest.raises(ValueError, match="Unreviewed WebSocket"):
        run(req=request(url=url))


@pytest.mark.parametrize("headers", [
    {"upgrade": "h2c"},
    {"upgrade": "websocket", "origin": "https://attacker.example"},
    {"upgrade": "websocket", "cookie": "session=stolen"},
    {"upgrade": "websocket", "authorization": "Bearer bad"},
    {"upgrade": "websocket", "sec-websocket-protocol": "credentials"},
])
def test_source_bridge_refuses_browser_and_credential_headers(headers):
    with pytest.raises(ValueError, match="Unreviewed WebSocket"):
        run(req=request(headers=headers))


def test_worker_bridge_refuses_missing_private_broker_or_trust_port():
    with pytest.raises(ValueError, match="private bindings unavailable"):
        run(worker_env={IDENTITY_AUTHORITY_SERVICE_BINDING_NAME: PrivateBinding(_IDENTITY_METHODS)})
    with pytest.raises(ValueError, match="TLS ingress verifier missing"):
        run(trusted=SimpleNamespace(headers={"cf-tls-client-auth": "SUCCESS"}))


def test_bridge_delegates_to_real_asgi_websocket_only_after_all_guards(monkeypatch):
    captured = {}
    async def fake_websocket(app, req, worker_env):
        captured["app"] = app
        captured["request"] = req
        captured["env"] = worker_env
        return "source-review-asgi-receipt"
    workers = ModuleType("workers")
    async def reject_http_fetch(*args):
        raise AssertionError("WSS upgrade must NEVER be dispatched via asgi.fetch()")
    workers.asgi = SimpleNamespace(websocket=fake_websocket, fetch=reject_http_fetch)
    monkeypatch.setitem(sys.modules, "workers", workers)
    req, bindings = request(), env()
    assert run(req=req, worker_env=bindings) == "source-review-asgi-receipt"
    assert captured["request"] is req
    assert captured["env"] is bindings
    assert len(captured["app"].routes) == 1
    assert captured["app"].routes[0].path == CONNECTOR_GATEWAY_WSS_PATH


def test_public_worker_does_not_mount_or_import_source_review_asgi_bridge():
    from pathlib import Path
    worker = (Path(__file__).resolve().parents[1] / "worker.py").read_text(encoding="utf-8")
    assert "dispatch_review_only_worker_wss_upgrade" not in worker
    assert "connector_gateway_worker_asgi_review" not in worker
