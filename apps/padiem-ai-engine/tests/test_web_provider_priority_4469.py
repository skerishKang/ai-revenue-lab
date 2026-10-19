"""#4469: Engine uses Core priority with fixed Worker public origins only.

CPython/offline tests: no real provider, B14, secret or Production mutation.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.cloudflare_external_transport import (
    CloudflarePublicWebTransport,
    public_web_worker_transport,
)

APP_ROOT = Path(__file__).resolve().parents[1]


class Headers:
    def entries(self):
        class Entries:
            def next(self):
                return SimpleNamespace(done=True, value=None)
        return Entries()


class Abort:
    def timeout(self, _ms):
        return SimpleNamespace(aborted=False)


def test_worker_source_reuses_core_and_defaults_to_off():
    worker = (APP_ROOT / "worker.py").read_text(encoding="utf-8")
    identity = (APP_ROOT / "worker_identity.py").read_text(encoding="utf-8")
    assert 'ENGINE_WEB_PROVIDER_ENV = "PADIEM_ENGINE_WEB_PROVIDER"' in worker
    assert 'or "off"' in worker
    assert "TinyFishDaumPriorityWebProvider" in worker
    assert 'ENGINE_TINYFISH_API_KEY_ENV = "PADIEM_ENGINE_TINYFISH_API_KEY"' in worker
    assert '_engine_web_provider_for_env(env)' in worker
    assert 'legacy_worker._engine_web_provider_for_env(env)' in identity
    assert "B14_SERVICE" in worker


def test_native_web_transport_is_worker_only():
    assert public_web_worker_transport() is None


@pytest.mark.asyncio
async def test_tinyfish_fetch_post_is_the_only_allowed_post():
    hits = []

    async def fetch(url, init):
        hits.append((url, init))
        return SimpleNamespace(status=200, headers=Headers(), body=None)

    transport = CloudflarePublicWebTransport(fetch_impl=fetch, abort_signal_api=Abort())
    async with httpx.AsyncClient(transport=transport) as client:
        response = await client.post(
            "https://api.fetch.tinyfish.ai",
            json={"urls": ["https://example.org/public"]},
            headers={"X-API-Key": "synthetic-key"},
        )
    assert response.status_code == 200
    assert len(hits) == 1
    assert hits[0][1]["method"] == "POST"
    assert '"urls"' in hits[0][1]["body"]
    assert hits[0][1]["redirect"] == "manual"


@pytest.mark.asyncio
@pytest.mark.parametrize(("method", "url"), [
    ("GET", "https://api.fetch.tinyfish.ai"),
    ("POST", "https://api.search.tinyfish.ai"),
    ("POST", "https://dapi.kakao.com/v2/search/web"),
    ("GET", "https://evil.example/web"),
    ("GET", "https://api.search.tinyfish.ai/other"),
    ("GET", "https://dapi.kakao.com/v2/search/other"),
    ("GET", "http://api.search.tinyfish.ai"),
    ("GET", "https://api.search.tinyfish.ai:8443"),
    ("GET", "https://api.search.tinyfish.ai.evil.example"),
])
async def test_unapproved_network_destination_never_reaches_fetch(method, url):
    called = []

    async def fetch(_url, _init):
        called.append(_url)
        raise AssertionError("unapproved external fetch")

    transport = CloudflarePublicWebTransport(fetch_impl=fetch, abort_signal_api=Abort())
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(httpx.RequestError):
            await client.request(method, url)
    assert not called
