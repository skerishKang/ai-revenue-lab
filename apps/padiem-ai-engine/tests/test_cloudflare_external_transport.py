from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from app.cloudflare_external_transport import (
    CloudflareExternalHttpTransport,
    drive_worker_transport,
)


class Headers:
    def __init__(self, values: dict[str, str]):
        self.values = values

    def entries(self):
        values = list(self.values.items())

        class Iterator:
            def __init__(self):
                self.index = 0

            def next(self):
                if self.index >= len(values):
                    return SimpleNamespace(done=True, value=None)
                value = values[self.index]
                self.index += 1
                return SimpleNamespace(done=False, value=value)

        return Iterator()


class Reader:
    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.cancel_calls = 0
        self.release_calls = 0

    async def read(self):
        if not self.chunks:
            return SimpleNamespace(done=True, value=None)
        return SimpleNamespace(done=False, value=self.chunks.pop(0))

    async def cancel(self):
        self.cancel_calls += 1

    def releaseLock(self):
        self.release_calls += 1


class Body:
    def __init__(self, chunks):
        self.reader = Reader(chunks)

    def getReader(self):
        return self.reader


class Abort:
    def __init__(self):
        self.calls: list[int] = []

    def timeout(self, milliseconds: int):
        self.calls.append(milliseconds)
        return SimpleNamespace(aborted=False)


@pytest.mark.asyncio
async def test_drive_worker_transport_uses_fetch_with_bounded_get() -> None:
    seen = {}
    abort = Abort()
    body = Body([b'{"files":', b"[]}"])

    async def fetch(url, init):
        seen["url"] = url
        seen["init"] = init
        return SimpleNamespace(
            status=200,
            headers=Headers({"content-type": "application/json"}),
            body=body,
        )

    transport = CloudflareExternalHttpTransport(
        allowed_hosts=frozenset({"www.googleapis.com"}),
        fetch_impl=fetch,
        abort_signal_api=abort,
    )
    async with httpx.AsyncClient(transport=transport, timeout=7.0) as client:
        response = await client.get(
            "https://www.googleapis.com/drive/v3/files?pageSize=1",
            headers={"Authorization": "Bearer private-token"},
        )
        assert await response.aread() == b'{"files":[]}'

    assert seen["url"].startswith("https://www.googleapis.com/drive/v3/files")
    assert seen["init"]["method"] == "GET"
    assert seen["init"]["redirect"] == "manual"
    assert seen["init"]["headers"]["authorization"] == "Bearer private-token"
    assert seen["init"]["headers"]["accept-encoding"] == "identity"
    assert abort.calls == [7000]
    assert body.reader.release_calls == 1


@pytest.mark.asyncio
async def test_drive_worker_transport_normalizes_fetch_decoded_encoding_headers() -> None:
    body = Body([b'{"files":[]}'])

    async def fetch(_url, _init):
        # Production-shaped Fetch behavior: body bytes are already decoded,
        # while stale origin encoding/length metadata can remain visible.
        return SimpleNamespace(
            status=200,
            headers=Headers(
                {
                    "content-type": "application/json",
                    "content-encoding": "gzip",
                    "content-length": "999",
                }
            ),
            body=body,
        )

    transport = CloudflareExternalHttpTransport(
        allowed_hosts=frozenset({"www.googleapis.com"}),
        fetch_impl=fetch,
        abort_signal_api=Abort(),
    )
    async with httpx.AsyncClient(transport=transport) as client:
        response = await client.get("https://www.googleapis.com/drive/v3/files")
        assert await response.aread() == b'{"files":[]}'
        assert "content-encoding" not in response.headers
        assert "content-length" not in response.headers


@pytest.mark.asyncio
async def test_drive_worker_transport_rejects_untrusted_target_before_fetch() -> None:
    calls = 0

    async def fetch(_url, _init):
        nonlocal calls
        calls += 1
        raise AssertionError("must not fetch")

    transport = CloudflareExternalHttpTransport(
        allowed_hosts=frozenset({"www.googleapis.com"}),
        fetch_impl=fetch,
        abort_signal_api=Abort(),
    )
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(httpx.RequestError):
            await client.get("https://evil.example/drive/v3/files")
    assert calls == 0


@pytest.mark.asyncio
async def test_drive_worker_transport_maps_fetch_failure_without_private_detail() -> None:
    async def fetch(_url, _init):
        raise RuntimeError("PRIVATE_FETCH_DETAIL")

    transport = CloudflareExternalHttpTransport(
        allowed_hosts=frozenset({"www.googleapis.com"}),
        fetch_impl=fetch,
        abort_signal_api=Abort(),
    )
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(httpx.ConnectError) as caught:
            await client.get("https://www.googleapis.com/drive/v3/files")
    assert "PRIVATE_FETCH_DETAIL" not in str(caught.value)


def test_drive_worker_transport_is_not_forced_into_cpython() -> None:
    assert drive_worker_transport() is None
