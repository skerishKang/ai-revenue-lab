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
    dispatch_review_only_worker_first_pairing_upgrade,
    strict_source_only_websocket_scope,
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


def request(url=REVIEW_WORKER_WSS_URL, headers=None, method="GET"):
    return SimpleNamespace(url=url, method=method, headers={"upgrade": "websocket"} if headers is None else headers)


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
    async def fake_websocket(app, req):
        captured["app"] = app
        captured["request"] = req
        return "source-review-asgi-receipt"
    workers = ModuleType("workers")
    async def reject_http_fetch(*args):
        raise AssertionError("WSS upgrade must NEVER be dispatched via asgi.fetch()")
    workers.asgi = SimpleNamespace(websocket=fake_websocket, fetch=reject_http_fetch)
    monkeypatch.setitem(sys.modules, "workers", workers)
    req, bindings = request(), env()
    assert run(req=req, worker_env=bindings) == "source-review-asgi-receipt"
    assert captured["request"] is req
    assert callable(captured["app"])  # one strict ASGI protocol adapter


def test_public_worker_does_not_mount_or_import_source_review_asgi_bridge():
    from pathlib import Path
    worker = (Path(__file__).resolve().parents[1] / "worker.py").read_text(encoding="utf-8")
    assert "dispatch_review_only_worker_wss_upgrade" not in worker
    assert "connector_gateway_worker_asgi_review" not in worker



def test_cloudflare_https_ws_scope_is_normalized_not_used_as_tls_authority():
    events = []
    async def simulated_source_app(scope, receive, send):
        events.append(("child", scope))
    adapter = strict_source_only_websocket_scope(simulated_source_app)
    expected = {
        "type": "websocket",
        "scheme": "https",
        "path": CONNECTOR_GATEWAY_WSS_PATH,
        "raw_path": CONNECTOR_GATEWAY_WSS_PATH.encode("ascii"),
        "query_string": b"",
        "headers": [(b"upgrade", b"websocket")],
    }
    async def fake_send(event):
        events.append(("send", event))
    async def read():
        return {"type": "websocket.connect"}
    asyncio.run(adapter(expected, read, fake_send))
    assert len(events) == 1
    assert events[0][0] == "child"
    assert events[0][1]["scheme"] == "wss"
    assert expected["scheme"] == "https"
    assert events[0][1]["headers"] is expected["headers"]
    # Trust still belongs to canonical trusted_tls_ingress.verify(websocket),
    # never to the scheme, headers, or presence of this adapter.


@pytest.mark.parametrize("changes", [
    {"scheme": "http"},
    {"scheme": "ws"},
    {"scheme": "wss"},
    {"type": "http"},
    {"path": "/api/claw/connector/gateway/other"},
    {"raw_path": b"/api/claw/connector/gateway/%73ession"},
    {"query_string": b"token=secret"},
    {"raw_path": None},
])
def test_non_https_or_ambiguous_ws_scopes_are_denied_before_host_invocation(changes):
    calls = []
    async def never_enter(scope, receive, send):
        calls.append("untrusted_scope_reached_host")
    async def send(event):
        calls.append(event)
    values = {
        "type": "websocket",
        "scheme": "https",
        "path": CONNECTOR_GATEWAY_WSS_PATH,
        "raw_path": CONNECTOR_GATEWAY_WSS_PATH.encode("ascii"),
        "query_string": b"",
    }
    values.update(changes)
    adapter = strict_source_only_websocket_scope(never_enter)
    asyncio.run(adapter(values, None, send))
    assert calls == [{"type": "websocket.close", "code": 1008}]


def test_first_pairing_dispatch_default_blocked_without_loading_sdk():
    req = request()
    req.cf = {"tlsVersion": "TLSv1.3"}
    with pytest.raises(RuntimeError, match="not activated"):
        asyncio.run(dispatch_review_only_worker_first_pairing_upgrade(
            request=req, worker_env=env(),
        ))
    with pytest.raises(RuntimeError, match="not activated"):
        asyncio.run(dispatch_review_only_worker_first_pairing_upgrade(
            request=req, worker_env=env(), source_test_authorized=1,
        ))


@pytest.mark.parametrize("cf", [
    None, {}, {"tlsVersion": "TLSv1.0"}, {"tlsVersion": "TLSv1.1"},
    {"tlsVersion": False}, {"tlsVersion": ["TLSv1.3"]},
    {"tlsVersion": "TLSv1.3,TLSv1.2"},
])
def test_first_pairing_dispatch_refuses_ineligible_tls_before_websocket_sdk(cf):
    req = request()
    req.cf = cf
    with pytest.raises(ValueError, match="Untrusted Cloudflare first-pair"):
        asyncio.run(dispatch_review_only_worker_first_pairing_upgrade(
            request=req, worker_env=env(), source_test_authorized=True,
        ))


def test_first_pairing_dispatch_uses_correct_two_argument_cloudflare_asgi_api(monkeypatch):
    called = {}
    async def official_signature(app, req):
        called["app"] = app
        called["request"] = req
        return "preflight-pass-not-live-credential"
    worker_module = ModuleType("workers")
    async def reject_http_fetch(*args, **kwargs):
        raise AssertionError("bootstrap WSS may not use HTTP asgi.fetch")
    worker_module.asgi = SimpleNamespace(
        websocket=official_signature, fetch=reject_http_fetch,
    )
    monkeypatch.setitem(sys.modules, "workers", worker_module)
    req = request()
    req.cf = {"tlsVersion": "TLSv1.3", "tlsClientAuth": None}
    bindings = env()
    result = asyncio.run(dispatch_review_only_worker_first_pairing_upgrade(
        request=req, worker_env=bindings, source_test_authorized=True,
    ))
    assert result == "preflight-pass-not-live-credential"
    assert called["request"] is req
    assert callable(called["app"])


def test_first_pairing_dispatch_does_not_construct_gateway_if_bindings_absent(monkeypatch):
    async def uncalled(*args):
        raise AssertionError("socket cannot upgrade without private Broker")
    workers = ModuleType("workers")
    workers.asgi = SimpleNamespace(websocket=uncalled)
    monkeypatch.setitem(sys.modules, "workers", workers)
    req = request()
    req.cf = {"tlsVersion": "TLSv1.3"}
    with pytest.raises(ValueError, match="private bindings unavailable"):
        asyncio.run(dispatch_review_only_worker_first_pairing_upgrade(
            request=req, worker_env={},
            source_test_authorized=True,
        ))


@pytest.mark.parametrize("headers", [
    {"upgrade": "websocket", "cookie": "forged"},
    {"upgrade": "websocket", "origin": "https://attacker.test"},
    {"upgrade": "websocket", "authorization": "Bearer stolen"},
    {"upgrade": "websocket", "x-forwarded-proto": "https"},
])
def test_first_pairing_dispatch_refuses_client_assertions_before_socket(headers):
    req = request(headers=headers)
    req.cf = {"tlsVersion": "TLSv1.3"}
    with pytest.raises(ValueError):
        asyncio.run(dispatch_review_only_worker_first_pairing_upgrade(
            request=req, worker_env=env(), source_test_authorized=True,
        ))


def test_first_pairing_review_bridge_remains_unmounted_in_public_worker():
    from pathlib import Path
    worker = (Path(__file__).resolve().parents[1] / "worker.py").read_text(encoding="utf-8")
    assert "dispatch_review_only_worker_first_pairing_upgrade" not in worker
    assert "connector_gateway_first_pairing_tls_review" not in worker
