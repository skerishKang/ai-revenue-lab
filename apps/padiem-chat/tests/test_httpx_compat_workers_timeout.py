from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
SHIM_PATH = ROOT / "app" / "httpx_compat.py"


class FakeHeadersIterator:
    async def next(self):
        return SimpleNamespace(done=True, value=None)


class FakeHeaders:
    def entries(self):
        return FakeHeadersIterator()


class FakeURLSearchParams:
    def __init__(self):
        self.items = []

    @classmethod
    def new(cls):
        return cls()

    def append(self, key, value):
        self.items.append((key, value))

    def __str__(self):
        return "&".join(f"{k}={v}" for k, v in self.items)


class FakeAbortSignalAPI:
    calls: list[int] = []
    next_signal = None
    fail = False

    @classmethod
    def timeout(cls, milliseconds: int):
        cls.calls.append(milliseconds)
        if cls.fail:
            raise RuntimeError("timeout signal unavailable")
        signal = cls.next_signal or SimpleNamespace(aborted=False)
        cls.next_signal = None
        return signal


def _load_workers_shim(fetch_impl, *, include_abort_signal: bool = True):
    fake_js = types.ModuleType("js")
    fake_js.fetch = fetch_impl
    fake_js.URLSearchParams = FakeURLSearchParams
    if include_abort_signal:
        fake_js.AbortSignal = FakeAbortSignalAPI

    previous = sys.modules.get("js")
    sys.modules["js"] = fake_js
    try:
        spec = importlib.util.spec_from_file_location(
            "_httpx_compat_workers_timeout_test",
            SHIM_PATH,
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        if previous is None:
            sys.modules.pop("js", None)
        else:
            sys.modules["js"] = previous


@pytest.fixture(autouse=True)
def _reset_abort_signal_api():
    FakeAbortSignalAPI.calls = []
    FakeAbortSignalAPI.next_signal = None
    FakeAbortSignalAPI.fail = False


def test_workers_fetch_receives_total_timeout_signal():
    seen = {}

    async def fake_fetch(url, init):
        seen["url"] = url
        seen["init"] = init
        return SimpleNamespace(status=200, headers=FakeHeaders(), body=None)

    shim = _load_workers_shim(fake_fetch)

    async def run():
        timeout = shim.Timeout(15.0, connect=8.0)
        async with shim.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            async with client.stream("GET", "https://example.test/userinfo") as response:
                assert response.status_code == 200

    asyncio.run(run())

    assert FakeAbortSignalAPI.calls == [15000]
    assert seen["url"] == "https://example.test/userinfo"
    assert seen["init"]["signal"] is not None
    assert seen["init"]["redirect"] == "manual"


def test_workers_fetch_without_timeout_does_not_attach_signal():
    seen = {}

    async def fake_fetch(url, init):
        seen["init"] = init
        return SimpleNamespace(status=204, headers=FakeHeaders(), body=None)

    shim = _load_workers_shim(fake_fetch)

    async def run():
        async with shim.AsyncClient(timeout=None) as client:
            async with client.stream("GET", "https://example.test/ping") as response:
                assert response.status_code == 204

    asyncio.run(run())

    assert FakeAbortSignalAPI.calls == []
    assert "signal" not in seen["init"]


def test_workers_fetch_timeout_before_headers_maps_to_read_timeout():
    signal = SimpleNamespace(aborted=True)
    FakeAbortSignalAPI.next_signal = signal

    async def fake_fetch(url, init):
        assert init["signal"] is signal
        raise RuntimeError("synthetic TimeoutError")

    shim = _load_workers_shim(fake_fetch)

    async def run():
        timeout = shim.Timeout(0.25, connect=0.1)
        async with shim.AsyncClient(timeout=timeout) as client:
            async with client.stream("GET", "https://example.test/slow"):
                raise AssertionError("unreachable")

    with pytest.raises(shim.ReadTimeout) as info:
        asyncio.run(run())

    assert "before response headers" in str(info.value)
    assert info.value.request is not None
    assert info.value.request.url == "https://example.test/slow"
    assert FakeAbortSignalAPI.calls == [250]


def test_workers_fetch_timeout_during_body_maps_to_read_timeout():
    signal = SimpleNamespace(aborted=False)
    FakeAbortSignalAPI.next_signal = signal

    class Reader:
        async def read(self):
            signal.aborted = True
            raise RuntimeError("synthetic aborted body read")

        async def cancel(self):
            return None

    class Body:
        def getReader(self):
            return Reader()

    async def fake_fetch(url, init):
        assert init["signal"] is signal
        return SimpleNamespace(
            status=200,
            headers=FakeHeaders(),
            body=Body(),
        )

    shim = _load_workers_shim(fake_fetch)

    async def run():
        timeout = shim.Timeout(1.5, connect=0.5)
        async with shim.AsyncClient(timeout=timeout) as client:
            async with client.stream("GET", "https://example.test/body") as response:
                return [chunk async for chunk in response.aiter_bytes()]

    with pytest.raises(shim.ReadTimeout) as info:
        asyncio.run(run())

    assert "while reading response body" in str(info.value)
    assert info.value.request is not None
    assert info.value.request.url == "https://example.test/body"
    assert FakeAbortSignalAPI.calls == [1500]


def test_workers_configured_timeout_fails_closed_if_abort_signal_is_unavailable():
    FakeAbortSignalAPI.fail = True

    async def fake_fetch(url, init):
        raise AssertionError("fetch must not run without an enforceable timeout")

    shim = _load_workers_shim(fake_fetch)

    async def run():
        async with shim.AsyncClient(timeout=shim.Timeout(5.0)) as client:
            async with client.stream("GET", "https://example.test/no-signal"):
                raise AssertionError("unreachable")

    with pytest.raises(shim.RequestError) as info:
        asyncio.run(run())

    assert "timeout signal is unavailable" in str(info.value)
    assert info.value.request is not None
    assert info.value.request.url == "https://example.test/no-signal"


def test_workers_mode_does_not_fall_back_to_real_httpx_when_abort_signal_is_missing():
    seen = {}

    async def fake_fetch(url, init):
        seen["url"] = url
        return SimpleNamespace(status=204, headers=FakeHeaders(), body=None)

    shim = _load_workers_shim(fake_fetch, include_abort_signal=False)

    assert shim._IN_WORKERS is True

    async def unbounded_run():
        async with shim.AsyncClient(timeout=None) as client:
            async with client.stream("GET", "https://example.test/no-timeout") as response:
                assert response.status_code == 204

    asyncio.run(unbounded_run())
    assert seen["url"] == "https://example.test/no-timeout"

    async def bounded_run():
        async with shim.AsyncClient(timeout=shim.Timeout(1.0)) as client:
            async with client.stream("GET", "https://example.test/must-fail-closed"):
                raise AssertionError("unreachable")

    with pytest.raises(shim.RequestError, match="timeout signal is unavailable"):
        asyncio.run(bounded_run())
