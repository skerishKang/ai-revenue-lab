"""#5784: the Engine's B14 https upstream carries a whole model request.

The public-web lanes post small fixed payloads to third-party endpoints, and their
8,192-byte bound is a decision about those endpoints. The B14 upstream is a
different lane: the Service Binding path it replaces has never capped a model
request body (#4379), so reaching a COM2 B14 from a Worker must not truncate one
either. Both halves are asserted here — the lifted bound on the B14 lane and the
unchanged bound everywhere else.
"""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from app.cloudflare_external_transport import (
    CloudflareB14UpstreamTransport,
    CloudflarePublicWebTransport,
)
from app.cloudflare_transport import build_b14_transport
from padiem_ai_core.b14_upstream import B14HttpsTransport, resolve_b14_upstream

ORIGIN = "https://b14.padiem.net"
COMPLETED_PATH = "/api/pilot/v1/chat/completions"
LARGE_BODY = b'{"model":"m","messages":[{"role":"user","content":"' + b"x" * (1024 * 1024) + b'"}]}'


class _Iterator:
    """The JavaScript iterator shape ``_headers`` walks: successive ``next()``."""

    def __init__(self, pairs):
        self._pairs = list(pairs)

    def next(self):
        if not self._pairs:
            return SimpleNamespace(done=True, value=None)
        return SimpleNamespace(done=False, value=self._pairs.pop(0))


class _Headers:
    def __init__(self, values):
        self._values = dict(values)

    def entries(self):
        return _Iterator(list(self._values.items()))

    def get(self, key):
        return self._values.get(key)

    def __iter__(self):
        return iter(self._values)


class _Abort:
    def timeout(self, milliseconds):
        return SimpleNamespace(aborted=False)


def _transport(cls, **kwargs):
    seen: dict = {}

    async def fetch(url, init):
        seen["url"] = url
        seen["init"] = init
        return SimpleNamespace(
            status=200,
            headers=_Headers({"content-type": "application/json"}),
            body=None,
        )

    return cls(fetch_impl=fetch, abort_signal_api=_Abort(), **kwargs), seen


@pytest.mark.asyncio
async def test_b14_upstream_lane_carries_a_whole_model_request() -> None:
    transport, seen = _transport(CloudflareB14UpstreamTransport, origin=ORIGIN)
    async with httpx.AsyncClient(transport=transport, timeout=60.0) as client:
        response = await client.post(ORIGIN + COMPLETED_PATH, content=LARGE_BODY)
        assert response.status_code == 200
    assert len(seen["init"]["body"]) == len(LARGE_BODY)
    assert seen["init"]["method"] == "POST"


@pytest.mark.asyncio
async def test_the_public_web_lane_keeps_its_own_body_bound() -> None:
    transport, _seen = _transport(CloudflarePublicWebTransport)
    async with httpx.AsyncClient(transport=transport, timeout=5.0) as client:
        with pytest.raises(httpx.RequestError) as error:
            await client.post(
                "https://api.fetch.tinyfish.ai/", content=b"y" * (8_192 + 1)
            )
    assert "Public-web Fetch body exceeds the safe bound." in str(error.value)


@pytest.mark.asyncio
async def test_the_b14_lane_still_refuses_anything_but_the_chosen_origin() -> None:
    transport, seen = _transport(CloudflareB14UpstreamTransport, origin=ORIGIN)
    async with httpx.AsyncClient(transport=transport, timeout=5.0) as client:
        for url, method in (
            ("https://elsewhere.example" + COMPLETED_PATH, "POST"),
            ("http://b14.padiem.net" + COMPLETED_PATH, "POST"),
            ("https://b14.padiem.net:8443" + COMPLETED_PATH, "POST"),
        ):
            with pytest.raises(httpx.RequestError):
                await client.request(method, url, content=b"{}")
    assert "url" not in seen


def test_https_mode_now_composes_a_worker_transport_instead_of_refusing(monkeypatch) -> None:
    import sys

    module = SimpleNamespace(fetch=None, AbortSignal=None)
    monkeypatch.setitem(sys.modules, "js", module)
    resolved = resolve_b14_upstream(
        {"B14_UPSTREAM_MODE": "https", "B14_UPSTREAM_URL": ORIGIN}
    )
    transport = build_b14_transport(
        binding=object(),
        request_factory=lambda *a, **k: None,
        proof_secret=None,
        upstream=resolved,
    )
    assert isinstance(transport, B14HttpsTransport)
    inner = transport._client._transport
    assert isinstance(inner, CloudflareB14UpstreamTransport)
    assert inner.MAX_POST_BODY_BYTES is None
    assert inner._allowed_hosts == frozenset({"b14.padiem.net"})
