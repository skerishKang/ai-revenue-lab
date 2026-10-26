"""#5784: Chat's Business 14 lane learns the same upstream switch as the Engine.

The default has to be the Service Binding, unchanged, because that is what every
Chat deployment does right now. ``https`` is only ever read as an origin, it must
carry the same body-bound proof the binding lane sends, and a bad value is
refused while the settings are still being built — before any client exists that
could spend platform provider credentials.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest

from app.b14_client import B14HTTPSUpstreamTransport, B14_UPSTREAM_PATHS
from app.b14_service_proof import PROOF_HEADER, PROOF_TIME_HEADER
from app.config import ConfigError, Settings

ORIGIN = "https://b14.example.test"
INTERNAL = "https://b14.internal"
COMPLETIONS = "/api/pilot/v1/chat/completions"
SECRET = "a-real-looking-deployment-proof-secret-not-a-real-one"
BODY = b'{"model":"m","messages":[]}'


def _settings(**overrides):
    values = {"runtime_mode": "b14", "b14_base_url": INTERNAL}
    values.update(overrides)
    return Settings.from_values(**values)


def test_the_default_upstream_is_the_service_binding_and_the_url_is_ignored():
    assert _settings().b14_upstream_mode == "binding"
    assert _settings(b14_upstream_mode="BINDING", b14_base_url=INTERNAL).b14_base_url == INTERNAL
    # A stray mode value is refused instead of being read as https.
    with pytest.raises(ConfigError):
        _settings(b14_upstream_mode="thrift")


def test_https_mode_sends_the_same_path_and_body_bound_proof():
    settings = _settings(b14_upstream_mode="https", b14_base_url=ORIGIN)
    assert settings.b14_upstream_mode == "https"

    captured: list[httpx.Request] = []

    class Delegate(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            captured.append(request)
            return httpx.Response(200, headers={"content-type": "application/json"}, json={"ok": True})

    transport = B14HTTPSUpstreamTransport(settings.b14_base_url, SECRET, delegate=Delegate())
    request = httpx.Request("POST", f"{ORIGIN}{COMPLETIONS}", content=BODY)
    response = asyncio.run(transport.handle_async_request(request))

    assert response.status_code == 200
    assert response.request is request
    outbound = captured[0]
    assert outbound.method == "POST"
    assert outbound.url.path == COMPLETIONS and outbound.url.path in B14_UPSTREAM_PATHS
    assert _run_read(outbound) == BODY
    assert PROOF_HEADER in outbound.headers and PROOF_TIME_HEADER in outbound.headers

    with pytest.raises(httpx.RequestError):
        asyncio.run(transport.handle_async_request(
            httpx.Request("POST", f"{ORIGIN}/api/pilot/v1/admin/model-calls", content=BODY)
        ))
    assert len(captured) == 1

    # The https transport can never be pointed back at the binding host.
    with pytest.raises(ValueError):
        B14HTTPSUpstreamTransport(INTERNAL, SECRET)
    with pytest.raises(ValueError):
        B14HTTPSUpstreamTransport("http://b14.example.test", SECRET)


def test_an_https_setting_without_a_public_origin_is_refused():
    for bad in (INTERNAL, "http://b14.example.test", None, ""):
        with pytest.raises(ConfigError):
            _settings(b14_upstream_mode="https", b14_base_url=bad)


def _run_read(request: httpx.Request) -> bytes:
    return asyncio.run(request.aread())
