"""Gated acceptance URL -> existing Broker DO native WSS Service Binding.

No DNS, deploy, owner login, credential, or live Windows PC used. The public
Worker must reconstruct a clean private Upgrade request and NEVER reveal
the canonical Broker internal URL or switch production traffic.
"""
from __future__ import annotations

import asyncio
import sys
from types import ModuleType, SimpleNamespace

import pytest

from app.connector_gateway_broker_do_upgrade import (
    ACCEPTANCE_NATIVE_WSS_BRIDGE_PRODUCTION_ENABLED,
    dispatch_isolated_native_pc_wss,
    is_review_native_wss_bridge_armed,
    _PRIVATE_URL,
    _STAGE_URL,
)
from app.connector_gateway_runtime_mount import maybe_dispatch_connector_gateway


class Result:
    def __init__(self, text=None, *, status, headers=None):
        self.text=text
        self.status=status
        self.headers=headers or {}


class InternalRequest:
    def __init__(self, url, *, method, headers):
        self.url=url
        self.method=method
        self.headers=headers


class Broker:
    def __init__(self, *, status=101):
        self.calls=[]
        self.status=status

    async def fetch(self, request):
        self.calls.append(request)
        return Result(status=self.status)


def env(*, broker=None):
    return {
        "PADIEM_CONNECTOR_ACCEPTANCE_BROKER_NATIVE_WSS_ENABLED":"enabled",
        "PADIEM_CONNECTOR_GATEWAY_WSS_ENABLED":"enabled",
        "PADIEM_CONNECTOR_GATEWAY_RELEASE_SCOPE":"isolated-operator-acceptance-4139",
        "PADIEM_CONNECTOR_ACCEPTANCE_PUBLIC_ORIGIN":
            "https://connector-acceptance.padiem.net",
        "PADIEM_CHAT_PUBLIC_BASE_URL":
            "https://connector-acceptance.padiem.net",
        "PADIEM_CHAT_RUNTIME_MODE":"mock",
        "IDENTITY_AUTHORITY_SERVICE":object(),
        "LOCAL_AGENT_BROKER_AUTHORITY_SERVICE":broker or Broker(),
    }


def request(*, url=_STAGE_URL, headers=None, tls="TLSv1.3", method="GET"):
    return SimpleNamespace(
        url=url,method=method,
        headers={"upgrade":"websocket"} if headers is None else headers,
        cf=SimpleNamespace(tlsVersion=tls),
    )


def run(request_value, settings):
    return asyncio.run(dispatch_isolated_native_pc_wss(
        request=request_value,worker_env=settings,
        request_factory=InternalRequest,response_factory=Result,
    ))


def test_exact_acceptance_WSS_only_uses_same_existing_private_broker_DO():
    broker=Broker()
    settings=env(broker=broker)
    result=run(request(),settings)
    assert result.status==101
    assert len(broker.calls)==1
    internal=broker.calls[0]
    assert internal.url==_PRIVATE_URL
    assert internal.method=="GET"
    assert internal.headers=={"upgrade":"websocket"}
    assert "connector-acceptance" not in internal.url
    assert not any(x in internal.headers for x in (
        "cookie","authorization","origin","sec-websocket-protocol",
    ))
    assert ACCEPTANCE_NATIVE_WSS_BRIDGE_PRODUCTION_ENABLED is False


@pytest.mark.parametrize("broken",[
    {"PADIEM_CONNECTOR_ACCEPTANCE_BROKER_NATIVE_WSS_ENABLED":True},
    {"PADIEM_CONNECTOR_GATEWAY_WSS_ENABLED":"true"},
    {"PADIEM_CONNECTOR_GATEWAY_RELEASE_SCOPE":"production"},
    {"PADIEM_CHAT_RUNTIME_MODE":"live"},
    {"PADIEM_CHAT_PUBLIC_BASE_URL":"https://chat.padiem.net"},
    {"PADIEM_CONNECTOR_ACCEPTANCE_PUBLIC_ORIGIN":"https://chat.padiem.net"},
])
def test_partial_or_product_configuration_does_not_forward(broken):
    b=Broker()
    settings=env(broker=b)
    settings.update(broken)
    assert is_review_native_wss_bridge_armed(settings) is False
    assert run(request(),settings).status==503
    assert b.calls==[]


@pytest.mark.parametrize("bad",[
    {"url":"https://chat.padiem.net/api/claw/connector/gateway/session"},
    {"url":_STAGE_URL+"?token=never"},
    {"url":_STAGE_URL+"#fragment"},
    {"url":_STAGE_URL.replace("connector-acceptance.","connector-acceptance.evil.")},
    {"url":_STAGE_URL.replace("https://","http://")},
    {"url":_STAGE_URL.replace("session","%73ession")},
    {"method":"POST"},
    {"headers":{"upgrade":"WebSocket"}},
    {"headers":{"upgrade":"websocket","cookie":"secret"}},
    {"headers":{"upgrade":"websocket","origin":"https://example.com"}},
    {"headers":{"upgrade":"websocket","authorization":"Bearer key"}},
    {"headers":{"upgrade":"websocket","sec-websocket-protocol":"auth"}},
    {"headers":{"upgrade":"websocket","cf-tls-client-auth":"SUCCESS"}},
    {"tls":None},
    {"tls":"TLSv1.1"},
])
def test_untrusted_request_never_reaches_private_broker(bad):
    b=Broker()
    assert run(request(**bad),env(broker=b)).status==503
    assert b.calls==[]


def test_real_service_binding_refusal_has_no_asgi_or_production_fallback():
    b=Broker(status=404)
    result=run(request(),env(broker=b))
    assert result.status==503
    assert len(b.calls)==1
    assert result.text=="Connector acceptance unavailable."


def test_bridge_does_not_route_browser_credentials_or_exception_text():
    class RaisingBroker:
        async def fetch(self, request):
            raise RuntimeError("secret device credential")
    settings=env()
    settings["LOCAL_AGENT_BROKER_AUTHORITY_SERVICE"]=RaisingBroker()
    result=run(request(),settings)
    assert result.status==503
    assert "secret" not in repr(vars(result))


def test_product_worker_mount_requires_opt_in_and_returns_existing_DO_101(monkeypatch):
    sdk=ModuleType("workers")
    sdk.Request=InternalRequest
    monkeypatch.setitem(sys.modules,"workers",sdk)
    b=Broker()
    settings=env(broker=b)
    result=asyncio.run(maybe_dispatch_connector_gateway(
        request=request(),worker_env=settings,response_factory=Result,
    ))
    assert result.status==101 and len(b.calls)==1
    assert b.calls[0].url==_PRIVATE_URL
    settings.pop("PADIEM_CONNECTOR_ACCEPTANCE_BROKER_NATIVE_WSS_ENABLED")
    assert is_review_native_wss_bridge_armed(settings) is False
    # Existing ASGI route is still a separate unmounted review path, not
    # silently rewritten or made into a new production WSS authority.


def test_unconfigured_broker_binding_fails_without_creating_socket():
    settings=env()
    settings["LOCAL_AGENT_BROKER_AUTHORITY_SERVICE"]=object()
    assert run(request(),settings).status==503


def test_headers_are_whitelisted_even_with_cloudflare_transport_headers():
    b=Broker()
    assert run(request(headers={
        "upgrade":"websocket",
        "cf-visitor":'{"scheme":"https"}',
        "x-forwarded-proto":"http",
        "user-agent":"PADIEM Connector Windows",
    }),env(broker=b)).status==101
    assert b.calls[0].headers=={"upgrade":"websocket"}


def test_checked_in_manifests_never_auto_activate_native_broker_bridge():
    from pathlib import Path
    import tomllib

    root=Path(__file__).resolve().parents[1]
    for path in (
        root/"wrangler.toml",
        root/"wrangler.connector-acceptance-4139.toml",
    ):
        with path.open("rb") as stream:
            settings=tomllib.load(stream)
        assert settings.get("vars",{}).get(
            "PADIEM_CONNECTOR_ACCEPTANCE_BROKER_NATIVE_WSS_ENABLED"
        ) != "enabled"
    assert ACCEPTANCE_NATIVE_WSS_BRIDGE_PRODUCTION_ENABLED is False


def test_internal_review_path_matches_single_broker_DO_native_WSS():
    from padiem_control_plane.broker_pending_pc_wss import WSS_REVIEW_PATH
    assert _PRIVATE_URL == "https://canonical-broker-connector.internal"+WSS_REVIEW_PATH


# #4139 live product: the already existing Chat worker and canonical Broker.
# Account selection never comes from the public WebSocket request.
def test_product_wss_uses_only_existing_broker_and_exact_product_hostname():
    from app.connector_gateway_broker_do_upgrade import (
        _PRODUCT_URL, dispatch_product_native_pc_wss,
        is_product_native_wss_bridge_armed,
    )
    broker = Broker()
    cfg = {
        "PADIEM_CONNECTOR_GATEWAY_WSS_ENABLED": "enabled",
        "PADIEM_CONNECTOR_GATEWAY_RELEASE_SCOPE": "owner-controlled-production-4139",
        "PADIEM_CONNECTOR_PRODUCTION_ENABLED": "enabled",
        "PADIEM_CHAT_PUBLIC_BASE_URL": "https://chat.padiem.net",
        "LOCAL_AGENT_BROKER_AUTHORITY_SERVICE": broker,
    }
    assert is_product_native_wss_bridge_armed(cfg) is True
    result = asyncio.run(dispatch_product_native_pc_wss(
        request=request(url=_PRODUCT_URL), worker_env=cfg,
        request_factory=InternalRequest, response_factory=Result,
    ))
    assert result.status == 101
    assert len(broker.calls) == 1
    assert broker.calls[0].url == _PRIVATE_URL
    assert broker.calls[0].headers == {"upgrade": "websocket"}
    assert "cookie" not in broker.calls[0].headers


@pytest.mark.parametrize("delta", [
    {"PADIEM_CONNECTOR_PRODUCTION_ENABLED": None},
    {"PADIEM_CONNECTOR_PRODUCTION_ENABLED": True},
    {"PADIEM_CONNECTOR_GATEWAY_RELEASE_SCOPE": "isolated-operator-acceptance-4139"},
    {"PADIEM_CHAT_PUBLIC_BASE_URL": "https://connector-acceptance.padiem.net"},
    {"PADIEM_CONNECTOR_GATEWAY_WSS_ENABLED": None},
    {"LOCAL_AGENT_BROKER_AUTHORITY_SERVICE": None},
])
def test_live_wss_config_fails_closed_on_any_missing_gate(delta):
    from app.connector_gateway_broker_do_upgrade import (
        _PRODUCT_URL, dispatch_product_native_pc_wss,
    )
    broker = Broker()
    cfg = {
        "PADIEM_CONNECTOR_GATEWAY_WSS_ENABLED": "enabled",
        "PADIEM_CONNECTOR_GATEWAY_RELEASE_SCOPE": "owner-controlled-production-4139",
        "PADIEM_CONNECTOR_PRODUCTION_ENABLED": "enabled",
        "PADIEM_CHAT_PUBLIC_BASE_URL": "https://chat.padiem.net",
        "LOCAL_AGENT_BROKER_AUTHORITY_SERVICE": broker,
    }
    cfg.update(delta)
    result = asyncio.run(dispatch_product_native_pc_wss(
        request=request(url=_PRODUCT_URL), worker_env=cfg,
        request_factory=InternalRequest, response_factory=Result,
    ))
    assert result.status == 503
    assert broker.calls == []


@pytest.mark.parametrize("changes", [
    {"url": "https://elsewhere.invalid/api/claw/connector/gateway/session"},
    {"url": "https://chat.padiem.net/api/claw/connector/gateway/session?x=1"},
    {"headers": {"upgrade": "websocket", "cookie": "synthetic"}},
    {"headers": {"upgrade": "websocket", "origin": "https://example.invalid"}},
    {"headers": {"upgrade": "websocket", "authorization": "Bearer synthetic"}},
    {"tls": "TLSv1.1"},
    {"method": "POST"},
])
def test_live_wss_never_accepts_spoofed_transport(changes):
    from app.connector_gateway_broker_do_upgrade import (
        _PRODUCT_URL, dispatch_product_native_pc_wss,
    )
    broker = Broker()
    cfg = {
        "PADIEM_CONNECTOR_GATEWAY_WSS_ENABLED": "enabled",
        "PADIEM_CONNECTOR_GATEWAY_RELEASE_SCOPE": "owner-controlled-production-4139",
        "PADIEM_CONNECTOR_PRODUCTION_ENABLED": "enabled",
        "PADIEM_CHAT_PUBLIC_BASE_URL": "https://chat.padiem.net",
        "LOCAL_AGENT_BROKER_AUTHORITY_SERVICE": broker,
    }
    result = asyncio.run(dispatch_product_native_pc_wss(
        request=request(**{"url": _PRODUCT_URL, **changes}), worker_env=cfg,
        request_factory=InternalRequest, response_factory=Result,
    ))
    assert result.status == 503
    assert broker.calls == []


def test_canonical_broker_private_rpc_requires_real_release_and_schema():
    from padiem_control_plane.broker_pending_pc_private_rpc import _enabled
    state = {
        "LOCAL_AGENT_BROKER_PENDING_PC_OWNER_RPC_ENABLED": "enabled",
        "LOCAL_AGENT_BROKER_PENDING_PC_SCHEMA_INSTALLED": "installed",
        "LOCAL_AGENT_BROKER_PENDING_PC_RELEASE_SCOPE": "owner-controlled-production-4139",
        "LOCAL_AGENT_BROKER_PENDING_PC_PRODUCTION_ENABLED": "enabled",
    }
    assert _enabled(SimpleNamespace(**state)) is True
    for missing in state:
        with_only_one_missing = dict(state)
        with_only_one_missing.pop(missing)
        assert _enabled(SimpleNamespace(**with_only_one_missing)) is False
    assert _enabled(SimpleNamespace(
        **{**state, "LOCAL_AGENT_BROKER_PENDING_PC_RELEASE_SCOPE": "unexpected"}
    )) is False
