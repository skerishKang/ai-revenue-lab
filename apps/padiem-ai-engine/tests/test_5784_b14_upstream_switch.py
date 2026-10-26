"""#5784 PR-2: the Engine picks its B14 upstream from one deployment variable.

Default is the Service Binding, byte-for-byte what the Engine does today. The
HTTPS side is the same caller proof over the same exact body, and it refuses a
state the deployment did not actually choose.
"""

from __future__ import annotations

import sys
from types import SimpleNamespace

import httpx
import pytest

from app.cloudflare_transport import (
    B14_INTERNAL_ORIGIN,
    CloudflareB14ServiceBindingTransport,
    b14_upstream_from_bindings,
    build_b14_execution_configs,
    build_b14_transport,
)
from app.b14_service_proof import service_proof_headers
import padiem_ai_core.b14_upstream as upstream_module
from padiem_ai_core.b14_upstream import B14HttpsTransport, B14UpstreamConfigError

TUNNEL_ORIGIN = "https://b14.padiem.net"
COMPLETED_PATH = "/api/pilot/v1/chat/completions"


def _env(**values) -> SimpleNamespace:
    return SimpleNamespace(**values)


def test_default_mode_is_the_binding_transport_and_the_old_origin() -> None:
    binding = object()
    transport = build_b14_transport(
        binding=binding, request_factory=lambda *a, **k: None, proof_secret=None
    )
    assert isinstance(transport, CloudflareB14ServiceBindingTransport)
    completed, streaming = build_b14_execution_configs(timeout_seconds=30.0)
    assert completed.base_url == B14_INTERNAL_ORIGIN == "https://b14.internal"
    assert streaming.base_url == B14_INTERNAL_ORIGIN


def test_https_mode_selects_the_http_transport_on_both_configs() -> None:
    resolved = upstream_module.resolve_b14_upstream(
        {
            upstream_module.UPSTREAM_MODE_ENV: "https",
            upstream_module.UPSTREAM_URL_ENV: TUNNEL_ORIGIN,
        }
    )
    transport = build_b14_transport(
        binding=None,
        request_factory=lambda *a, **k: None,
        proof_secret=None,
        upstream=resolved,
        https_client_factory=lambda: httpx.AsyncClient(),
    )
    assert isinstance(transport, B14HttpsTransport)
    completed, streaming = build_b14_execution_configs(timeout_seconds=30.0, upstream=resolved)
    assert completed.base_url == streaming.base_url == TUNNEL_ORIGIN


def test_switch_is_read_from_bindings_only(monkeypatch) -> None:
    """A stray process value must not flip an Engine that was not switched."""
    monkeypatch.setenv(upstream_module.UPSTREAM_MODE_ENV, "https")
    monkeypatch.setenv(upstream_module.UPSTREAM_URL_ENV, TUNNEL_ORIGIN)
    assert b14_upstream_from_bindings(_env()).uses_service_binding
    flipped = b14_upstream_from_bindings(
        _env(B14_UPSTREAM_MODE="https", B14_UPSTREAM_URL=TUNNEL_ORIGIN)
    )
    assert flipped.uses_https and flipped.origin == TUNNEL_ORIGIN


def test_https_on_workers_composes_the_fetch_backed_upstream(monkeypatch) -> None:
    # A Worker has no socket to open, so the upstream rides JavaScript fetch. The
    # bound that lane used to inherit from the public-web path is lifted for B14
    # only, and both halves are pinned in
    # ``test_5784_engine_b14_https_body_headroom.py``.
    module = SimpleNamespace(fetch=None, AbortSignal=None)
    monkeypatch.setitem(sys.modules, "js", module)
    transport = build_b14_transport(
        binding=object(),
        request_factory=lambda *a, **k: None,
        proof_secret=None,
        upstream=upstream_module.B14Upstream(mode="https", origin=TUNNEL_ORIGIN),
    )
    assert isinstance(transport, B14HttpsTransport)


def test_a_half_flipped_switch_refuses_to_start() -> None:
    with pytest.raises(B14UpstreamConfigError) as error:
        b14_upstream_from_bindings(_env(B14_UPSTREAM_URL=TUNNEL_ORIGIN))
    assert error.value.code == "b14_upstream_url_ignored_in_binding_mode"


@pytest.mark.asyncio
async def test_the_http_side_signs_the_same_body_the_binding_side_signs() -> None:
    body = b'{"model":"m","messages":[]}'
    secret = "a-deployment-proof-secret-0123456789ab"
    sent: list[dict] = []

    class _Response:
        status_code = 200
        headers: dict = {}
        request = None

        async def aread(self) -> bytes:
            return b"{}"

        async def aclose(self) -> None:
            return None

    class _Client:
        def build_request(self, method, url, headers=None, content=None):
            return {"method": method, "url": url, "headers": dict(headers or {}), "content": content}

        async def send(self, request, stream=False):
            sent.append(request)
            return _Response()

        async def aclose(self) -> None:
            return None

    transport = B14HttpsTransport(
        origin=TUNNEL_ORIGIN,
        allowed_paths=frozenset({COMPLETED_PATH}),
        headers_for_body=lambda raw: service_proof_headers(secret, raw),
        correlation_headers=lambda: {"X-Request-Id": "req_engine_1"},
        client=_Client(),
    )
    await transport.handle_async_request(
        httpx.Request("POST", TUNNEL_ORIGIN + COMPLETED_PATH, content=body)
    )

    expected = service_proof_headers(secret, body)
    assert sent[0]["headers"]["X-Padiem-B14-Proof"] == expected["X-Padiem-B14-Proof"]
    assert sent[0]["headers"]["X-Padiem-B14-Time"] == expected["X-Padiem-B14-Time"]
    assert sent[0]["content"] == body
