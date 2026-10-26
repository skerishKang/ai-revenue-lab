"""#5784: the Engine's Business 14 lane can be pointed at a different upstream.

Three contracts, all offline. The default must be the Service Binding and must
still address ``https://b14.internal`` with the same allowlist, because that is
what every running deployment does today. The https mode must send the same
method, path and body-bound proof to the configured origin and nothing else.
And a mistyped switch must be refused before any client exists, because this is
the lane that spends platform-owned provider credentials.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx
import pytest

from app.b14_service_proof import PROOF_HEADER, PROOF_TIME_HEADER
from app.cloudflare_transport import (
    B14_INTERNAL_ORIGIN,
    B14_UPSTREAM_BINDING,
    B14_UPSTREAM_HTTPS,
    B14HTTPSProofTransport,
    CloudflareB14ServiceBindingTransport,
    build_b14_execution_configs,
    resolve_b14_upstream,
    resolve_b14_upstream_from_env,
)

from padiem_ai_core import B14_CHAT_COMPLETIONS_PATH

SECRET = "a-real-looking-deployment-proof-secret-not-a-real-one"
ORIGIN = "https://b14.example.test"
BODY = b'{"model":"m","messages":[]}'


def _run(coro):
    return asyncio.run(coro)


def test_the_default_upstream_is_the_service_binding_and_stays_internal():
    mode, origin = resolve_b14_upstream()
    assert (mode, origin) == (B14_UPSTREAM_BINDING, B14_INTERNAL_ORIGIN)
    # An unset switch with a stray URL is still the binding: only https reads it.
    assert resolve_b14_upstream(mode=None, url=ORIGIN) == (B14_UPSTREAM_BINDING, B14_INTERNAL_ORIGIN)
    assert resolve_b14_upstream(mode="BINDING", url=None)[0] == B14_UPSTREAM_BINDING

    completed, streaming = build_b14_execution_configs(timeout_seconds=600.0)
    assert completed.base_url == B14_INTERNAL_ORIGIN
    assert streaming.base_url == B14_INTERNAL_ORIGIN
    # The budgets do not move with the switch.
    switched = build_b14_execution_configs(timeout_seconds=600.0, base_url=ORIGIN)
    assert (switched[0].max_response_bytes, switched[1].max_response_bytes) == (
        completed.max_response_bytes,
        streaming.max_response_bytes,
    )
    # The binding lane still refuses anything but the internal origin.
    with pytest.raises(httpx.RequestError):
        _run(
            CloudflareB14ServiceBindingTransport(
                binding=object(), request_factory=lambda *a, **k: None
            )._validate_target(httpx.URL(f"{ORIGIN}{B14_CHAT_COMPLETIONS_PATH}"))
        )


def test_https_mode_sends_the_same_path_method_body_and_body_bound_proof():
    captured: list[httpx.Request] = []

    class Delegate(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            captured.append(request)
            return httpx.Response(200, headers={"content-type": "application/json"}, json={"ok": True})

    transport = B14HTTPSProofTransport(base_url=ORIGIN, proof_secret=SECRET, delegate=Delegate())
    request = httpx.Request("POST", f"{ORIGIN}{B14_CHAT_COMPLETIONS_PATH}", content=BODY)
    response = _run(transport.handle_async_request(request))

    assert response.status_code == 200
    assert response.request is request, "the caller keeps its own request object"
    outbound = captured[0]
    assert outbound.method == "POST"
    assert outbound.url.path == B14_CHAT_COMPLETIONS_PATH
    assert outbound.url.scheme == "https" and str(outbound.url.host) == "b14.example.test"
    assert outbound.url.port is None
    assert _run(outbound.aread()) == BODY
    assert PROOF_HEADER in outbound.headers and PROOF_TIME_HEADER in outbound.headers
    assert outbound.headers["content-type"] == "application/json"

    # A path outside the three the lane may use never reaches the network.
    for bad in (f"{ORIGIN}/api/pilot/v1/admin/model-calls", f"{ORIGIN}{B14_CHAT_COMPLETIONS_PATH}?x=1",
                "https://other.example.test/api/pilot/v1/chat/completions"):
        with pytest.raises(httpx.RequestError):
            _run(transport.handle_async_request(httpx.Request("POST", bad, content=BODY)))
    with pytest.raises(httpx.RequestError):
        _run(transport.handle_async_request(httpx.Request("GET", f"{ORIGIN}{B14_CHAT_COMPLETIONS_PATH}")))
    assert len(captured) == 1


def test_a_mistyped_upstream_switch_is_refused_before_any_client_exists():
    with pytest.raises(ValueError):
        resolve_b14_upstream(mode="thrift")
    for bad_url in (None, "", "http://b14.example.test", "https://b14.example.test:8443",
                    "https://b14.example.test/prefix", "https://user@b14.example.test",
                    "https://b14.example.test/?x=1"):
        with pytest.raises(ValueError):
            resolve_b14_upstream(mode=B14_UPSTREAM_HTTPS, url=bad_url)
    # The internal origin is never a valid https target: that would claim a
    # public route while naming the private binding host.
    with pytest.raises(ValueError):
        resolve_b14_upstream(mode=B14_UPSTREAM_HTTPS, url=B14_INTERNAL_ORIGIN)
    assert resolve_b14_upstream(mode=B14_UPSTREAM_HTTPS, url="https://b14.example.test/")[1] == ORIGIN

    assert resolve_b14_upstream_from_env(SimpleNamespace()) == (
        B14_UPSTREAM_BINDING,
        B14_INTERNAL_ORIGIN,
    )
    assert resolve_b14_upstream_from_env(
        SimpleNamespace(B14_UPSTREAM_MODE="https", B14_UPSTREAM_URL=ORIGIN)
    ) == (B14_UPSTREAM_HTTPS, ORIGIN)
    # A mode without its URL fails closed rather than defaulting to the binding.
    with pytest.raises(ValueError):
        resolve_b14_upstream_from_env(SimpleNamespace(B14_UPSTREAM_MODE="https"))
    with pytest.raises(ValueError):
        resolve_b14_upstream_from_env(SimpleNamespace(B14_UPSTREAM_MODE="nope", B14_UPSTREAM_URL=ORIGIN))
