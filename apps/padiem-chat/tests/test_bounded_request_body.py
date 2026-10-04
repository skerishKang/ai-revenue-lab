from __future__ import annotations

import asyncio

import pytest

from app.bounded_request_body import RequestBodyTooLarge, read_bounded_request_body


class FakeRequest:
    def __init__(self, chunks: list[bytes], *, content_length: str | None = None) -> None:
        self._chunks = list(chunks)
        self.headers = {}
        if content_length is not None:
            self.headers["content-length"] = content_length
        self.stream_calls = 0
        self.yield_count = 0

    def stream(self):
        self.stream_calls += 1

        async def _iter():
            for chunk in self._chunks:
                self.yield_count += 1
                yield chunk

        return _iter()


def test_exact_limit_accepts_multiple_chunks() -> None:
    request = FakeRequest([b"ab", b"cd"])
    body = asyncio.run(read_bounded_request_body(request, max_bytes=4))

    assert body == b"abcd"
    assert request.stream_calls == 1
    assert request.yield_count == 2


def test_chunked_oversize_stops_before_later_chunks() -> None:
    request = FakeRequest([b"1234", b"5", b"never-read"])

    with pytest.raises(RequestBodyTooLarge):
        asyncio.run(read_bounded_request_body(request, max_bytes=4))

    assert request.stream_calls == 1
    assert request.yield_count == 2


def test_declared_oversize_rejects_before_stream_is_opened() -> None:
    request = FakeRequest([b"never-read"], content_length="5")

    with pytest.raises(RequestBodyTooLarge):
        asyncio.run(read_bounded_request_body(request, max_bytes=4))

    assert request.stream_calls == 0
    assert request.yield_count == 0


def test_missing_or_malformed_length_uses_incremental_counter() -> None:
    request = FakeRequest([b"12", b"34"], content_length="not-a-number")
    body = asyncio.run(read_bounded_request_body(request, max_bytes=4))

    assert body == b"1234"
    assert request.stream_calls == 1
    assert request.yield_count == 2
