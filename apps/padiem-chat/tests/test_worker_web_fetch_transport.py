from __future__ import annotations

import ast
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from app.config import Settings
from app.web_tools import DaumWebProvider, FirecrawlWebProvider, WebToolError


ROOT = Path(__file__).resolve().parents[1]
WORKER_PATH = ROOT / "worker.py"


def _load_worker_web_transport():
    source = WORKER_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    names = {
        "_CloudflareReadableByteStream",
        "_CloudflareExternalFetchByteStream",
        "_CloudflareEmptyAsyncByteStream",
        "CloudflareExternalHttpTransport",
    }
    selected = [
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name in names
    ]
    found = {node.name for node in selected}
    assert found == names
    module = ast.Module(body=selected, type_ignores=[])
    namespace = {"httpx": httpx, "Any": Any}
    exec(compile(module, str(WORKER_PATH), "exec"), namespace)
    return namespace["CloudflareExternalHttpTransport"]


class FakeHeadersIterator:
    def __init__(self, entries):
        self._entries = list(entries)
        self._index = 0

    async def next(self):
        if self._index >= len(self._entries):
            return SimpleNamespace(done=True, value=None)
        value = self._entries[self._index]
        self._index += 1
        return SimpleNamespace(done=False, value=value)


class FakeHeaders:
    def __init__(self, values: dict[str, str]):
        self._values = dict(values)

    def entries(self):
        return FakeHeadersIterator(self._values.items())

    def __iter__(self):
        return iter(self._values)

    def get(self, key):
        return self._values.get(key)


class FakeReader:
    def __init__(self, chunks):
        self._chunks = list(chunks)
        self._index = 0
        self.cancel_count = 0
        self.release_count = 0

    async def read(self):
        if self._index >= len(self._chunks):
            return SimpleNamespace(done=True, value=None)
        value = self._chunks[self._index]
        self._index += 1
        return SimpleNamespace(done=False, value=value)

    async def cancel(self):
        self.cancel_count += 1

    def releaseLock(self):
        self.release_count += 1


class FakeBody:
    def __init__(self, chunks):
        self.reader = FakeReader(chunks)
        self.get_reader_count = 0

    def getReader(self):
        self.get_reader_count += 1
        return self.reader


class FakeResponse:
    def __init__(self, status: int, payload: dict):
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        cut = max(1, len(raw) // 3)
        self.status = status
        self.headers = FakeHeaders({"content-type": "application/json"})
        self.body = FakeBody([raw[:cut], raw[cut : cut * 2], raw[cut * 2 :]])


class FakeAbortSignalAPI:
    def __init__(self):
        self.calls: list[int] = []
        self.next_signal = None

    def timeout(self, milliseconds: int):
        self.calls.append(milliseconds)
        signal = self.next_signal or SimpleNamespace(aborted=False)
        self.next_signal = None
        return signal


@pytest.mark.asyncio
async def test_worker_web_transport_runs_firecrawl_through_real_httpx_family():
    transport_type = _load_worker_web_transport()
    abort_api = FakeAbortSignalAPI()
    seen = {}

    async def fake_fetch(url, init):
        seen["url"] = url
        seen["init"] = init
        return FakeResponse(
            200,
            {
                "success": True,
                "data": {
                    "web": [
                        {
                            "title": "Worker result",
                            "url": "https://example.com/a",
                            "description": "Worker fetch transport result",
                        }
                    ]
                },
            },
        )

    transport = transport_type(
        fetch_impl=fake_fetch,
        abort_signal_api=abort_api,
    )
    assert isinstance(transport, httpx.AsyncBaseTransport)

    provider = FirecrawlWebProvider(
        Settings.from_values(
            web_provider="firecrawl",
            firecrawl_api_key="fc-test-secret",
            web_timeout_seconds="9",
        ),
        transport=transport,
    )
    results = await provider.search("worker transport", 1)

    assert len(results) == 1
    assert results[0].url == "https://example.com/a"
    assert seen["url"] == "https://api.firecrawl.dev/v2/search"
    assert seen["init"]["method"] == "POST"
    assert seen["init"]["redirect"] == "manual"
    assert seen["init"]["headers"]["authorization"] == "Bearer fc-test-secret"
    assert "host" not in seen["init"]["headers"]
    assert "content-length" not in seen["init"]["headers"]
    assert "connection" not in seen["init"]["headers"]
    assert json.loads(bytes(seen["init"]["body"]).decode("utf-8")) == {
        "query": "worker transport",
        "limit": 1,
        "sources": ["web"],
    }
    assert abort_api.calls == [9000]


@pytest.mark.asyncio
async def test_worker_web_transport_preserves_daum_query_params_and_headers():
    transport_type = _load_worker_web_transport()
    abort_api = FakeAbortSignalAPI()
    seen = {}

    async def fake_fetch(url, init):
        seen["url"] = url
        seen["init"] = init
        return FakeResponse(
            200,
            {
                "documents": [
                    {
                        "title": "<b>Daum result</b>",
                        "url": "https://example.com/daum",
                        "contents": "Daum worker transport",
                    }
                ]
            },
        )

    transport = transport_type(
        fetch_impl=fake_fetch,
        abort_signal_api=abort_api,
    )
    provider = DaumWebProvider(
        Settings.from_values(
            web_provider="daum",
            daum_rest_api_key="daum-test-secret",
            web_timeout_seconds="7",
        ),
        transport=transport,
    )

    results = await provider.search("광주 인공지능", 1)

    assert len(results) == 1
    assert seen["url"].startswith("https://dapi.kakao.com/v2/search/web?")
    assert "query=" in seen["url"]
    assert "size=1" in seen["url"]
    assert seen["init"]["method"] == "GET"
    assert "body" not in seen["init"]
    assert seen["init"]["headers"]["authorization"] == "KakaoAK daum-test-secret"
    assert abort_api.calls == [7000]


@pytest.mark.asyncio
async def test_worker_web_transport_timeout_maps_through_core_provider_boundary():
    transport_type = _load_worker_web_transport()
    abort_api = FakeAbortSignalAPI()
    signal = SimpleNamespace(aborted=True)
    abort_api.next_signal = signal

    async def fake_fetch(url, init):
        assert init["signal"] is signal
        raise RuntimeError("synthetic Worker fetch timeout")

    transport = transport_type(
        fetch_impl=fake_fetch,
        abort_signal_api=abort_api,
    )
    provider = FirecrawlWebProvider(
        Settings.from_values(
            web_provider="firecrawl",
            firecrawl_api_key="fc-test-secret",
            web_timeout_seconds="3",
        ),
        transport=transport,
    )

    with pytest.raises(WebToolError) as info:
        await provider.search("timeout")

    assert info.value.code == "web_timeout"
    assert info.value.status_code == 504
    assert abort_api.calls == [3000]


def test_worker_entrypoint_injects_external_web_transport_into_app_factory():
    source = WORKER_PATH.read_text(encoding="utf-8")
    assert "web_transport = CloudflareExternalHttpTransport()" in source
    assert "web_transport=web_transport" in source
    assert "class CloudflareExternalHttpTransport(httpx.AsyncBaseTransport)" in source
    assert "from js import fetch as js_fetch" in source
    assert "from js import AbortSignal as js_abort_signal" in source
