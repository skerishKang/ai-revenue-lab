"""#4139 Worker→canonical WSS admission, without enabling production."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.connector_gateway_runtime_mount import (
    PRODUCTION_GATEWAY_DEFAULT_ON,
    maybe_dispatch_connector_gateway,
)
from app.canonical_connector_gateway_source_composition import CONNECTOR_GATEWAY_WSS_PATH

URL = "https://chat.padiem.net" + CONNECTOR_GATEWAY_WSS_PATH
_ON = {
    "PADIEM_CONNECTOR_GATEWAY_WSS_ENABLED": "enabled",
    "PADIEM_CONNECTOR_GATEWAY_RELEASE_SCOPE": "isolated-operator-acceptance-4139",
}
_ID = "IDENTITY_AUTHORITY_SERVICE"
_BROKER = "LOCAL_AGENT_BROKER_AUTHORITY_SERVICE"


class Response:
    def __init__(self, text, *, status, headers):
        self.text = text
        self.status = status
        self.headers = headers


def request(*, url=URL):
    return SimpleNamespace(url=url, method="GET", headers={"upgrade": "websocket"})


def dispatch(request_value, worker_env):
    return asyncio.run(maybe_dispatch_connector_gateway(
        request=request_value, worker_env=worker_env,
        response_factory=Response,
    ))


def test_neither_http_user_header_nor_partial_feature_flag_enables_connector():
    assert PRODUCTION_GATEWAY_DEFAULT_ON is False
    for config in (
        {}, {_ON.__iter__().__next__(): "enabled"},
        {"PADIEM_CONNECTOR_GATEWAY_RELEASE_SCOPE": _ON["PADIEM_CONNECTOR_GATEWAY_RELEASE_SCOPE"]},
        {**_ON, "PADIEM_CONNECTOR_GATEWAY_RELEASE_SCOPE": "production"},
        {**_ON, "PADIEM_CONNECTOR_GATEWAY_WSS_ENABLED": True},
    ):
        assert dispatch(request(), config) is None


def test_only_canonical_route_is_considered():
    for path in ("/api/claw/connector/gateway/another", "/",
                 CONNECTOR_GATEWAY_WSS_PATH + "/x"):
        assert dispatch(request(url="https://chat.padiem.net" + path), _ON) is None


def test_armed_but_missing_private_binding_fails_before_sdk_dispatch(monkeypatch):
    import app.connector_gateway_worker_asgi_review as review
    called = []
    async def untrusted(*args, **kwargs):
        called.append(True)
        return "unexpected"
    monkeypatch.setattr(review, "dispatch_review_only_worker_first_pairing_upgrade", untrusted)
    for env in (_ON, {**_ON, _ID: object()}, {**_ON, _BROKER: object()}):
        result = dispatch(request(), env)
        assert isinstance(result, Response)
        assert result.status == 503
        assert "unavailable" in result.text
        assert called == []


def test_approved_private_binding_uses_existing_real_canonical_wss_bridge(monkeypatch):
    import app.connector_gateway_worker_asgi_review as review
    seen = []
    async def fake_bridge(**kwargs):
        seen.append(kwargs)
        return SimpleNamespace(status=101)
    monkeypatch.setattr(review, "dispatch_review_only_worker_first_pairing_upgrade", fake_bridge)
    env = {**_ON, _ID: object(), _BROKER: object()}
    req = request()
    result = dispatch(req, env)
    assert result.status == 101
    assert len(seen) == 1
    assert seen[0] == {
        "request": req, "worker_env": env, "source_test_authorized": True,
    }


def test_rejected_tls_or_invalid_request_is_closed_and_redacted(monkeypatch):
    import app.connector_gateway_worker_asgi_review as review
    async def denied(**kwargs):
        raise ValueError("SYNTHETIC_PRIVATE_CREDENTIAL_SHOULD_NOT_ESCAPE")
    monkeypatch.setattr(review, "dispatch_review_only_worker_first_pairing_upgrade", denied)
    result = dispatch(request(), {**_ON, _ID: object(), _BROKER: object()})
    assert result.status == 503
    assert "SYNTHETIC" not in result.text


def test_worker_real_fetch_seam_invoked_before_normal_app_asgi():
    from pathlib import Path
    code = (Path(__file__).resolve().parents[1] / "worker.py").read_text(encoding="utf-8")
    assert "maybe_dispatch_connector_gateway" in code
    assert 'request=request, worker_env=self.env' in code
    assert code.index("await maybe_dispatch_connector_gateway(") < code.index("if _worker_app is None:")
    assert "PADIEM_CONNECTOR_GATEWAY_WSS_ENABLED" not in (
        Path(__file__).resolve().parents[1] / "wrangler.toml"
    ).read_text(encoding="utf-8")


def test_production_wss_uses_existing_private_native_broker_not_asgi(monkeypatch):
    import sys
    import types
    from app import connector_gateway_broker_do_upgrade as bridge
    invoked = []
    async def fake_product(**kwargs):
        invoked.append(kwargs)
        return SimpleNamespace(status=101)

    monkeypatch.setattr(bridge, "dispatch_product_native_pc_wss", fake_product)
    monkeypatch.setitem(sys.modules, "workers", types.SimpleNamespace(Request=object()))
    cfg = {
        "PADIEM_CONNECTOR_GATEWAY_WSS_ENABLED": "enabled",
        "PADIEM_CONNECTOR_GATEWAY_RELEASE_SCOPE": "owner-controlled-production-4139",
        "PADIEM_CONNECTOR_PRODUCTION_ENABLED": "enabled",
        _ID: object(), _BROKER: object(),
    }
    assert dispatch(request(), cfg).status == 101
    assert len(invoked) == 1
    assert invoked[0]["worker_env"] is cfg


def test_production_wss_rejects_missing_second_release_flag():
    cfg = {
        "PADIEM_CONNECTOR_GATEWAY_WSS_ENABLED": "enabled",
        "PADIEM_CONNECTOR_GATEWAY_RELEASE_SCOPE": "owner-controlled-production-4139",
        _ID: object(), _BROKER: object(),
    }
    assert dispatch(request(), cfg) is None
    assert dispatch(request(), {**cfg, "PADIEM_CONNECTOR_PRODUCTION_ENABLED": True}) is None
