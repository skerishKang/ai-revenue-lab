from __future__ import annotations

import asyncio

import pytest

from app.cloudflare_request_body import (
    RequestBodyReadError,
    RequestBodyTooLarge,
    read_bounded_worker_request_body,
)


class _Result:
    def __init__(self, *, value=None, done: bool = False) -> None:
        self.value = value
        self.done = done


class _Reader:
    def __init__(self, chunks, *, fail_at: int | None = None) -> None:
        self._chunks = list(chunks)
        self._index = 0
        self._fail_at = fail_at
        self.read_calls = 0
        self.cancel_calls = 0
        self.release_calls = 0

    async def read(self):
        self.read_calls += 1
        if self._fail_at is not None and self.read_calls == self._fail_at:
            raise RuntimeError("stream failure")
        if self._index >= len(self._chunks):
            return _Result(done=True)
        value = self._chunks[self._index]
        self._index += 1
        return _Result(value=value)

    async def cancel(self):
        self.cancel_calls += 1

    def releaseLock(self):
        self.release_calls += 1


class _Body:
    def __init__(self, reader: _Reader) -> None:
        self.reader = reader
        self.get_reader_calls = 0

    def getReader(self):
        self.get_reader_calls += 1
        return self.reader


class _Request:
    def __init__(self, chunks=None, *, content_length: str | None = None, fallback_text: str | None = None):
        self.headers = {}
        if content_length is not None:
            self.headers["content-length"] = content_length
        self._fallback_text = fallback_text
        self.text_calls = 0
        self.reader = _Reader(chunks or [])
        self.body = _Body(self.reader) if chunks is not None else None

    async def text(self):
        self.text_calls += 1
        if self._fallback_text is None:
            raise RuntimeError("no fallback")
        return self._fallback_text


def test_stream_accepts_exact_bound_and_releases_reader() -> None:
    request = _Request([b"ab", b"cd"])
    body = asyncio.run(read_bounded_worker_request_body(request, max_bytes=4))

    assert body == b"abcd"
    assert request.reader.read_calls == 3
    assert request.reader.cancel_calls == 0
    assert request.reader.release_calls == 1
    assert request.text_calls == 0


def test_chunked_overflow_cancels_at_crossing_chunk() -> None:
    request = _Request([b"1234", b"5", b"never-read"])

    with pytest.raises(RequestBodyTooLarge):
        asyncio.run(read_bounded_worker_request_body(request, max_bytes=4))

    assert request.reader.read_calls == 2
    assert request.reader.cancel_calls == 1
    assert request.reader.release_calls == 1
    assert request.text_calls == 0


def test_stream_read_failure_cancels_and_releases() -> None:
    request = _Request([b"12", b"34"])
    request.reader._fail_at = 2

    with pytest.raises(RequestBodyReadError):
        asyncio.run(read_bounded_worker_request_body(request, max_bytes=4))

    assert request.reader.cancel_calls == 1
    assert request.reader.release_calls == 1


def test_declared_oversize_rejects_before_stream_reader_creation() -> None:
    request = _Request([b"never-read"], content_length="5")

    with pytest.raises(RequestBodyTooLarge):
        asyncio.run(read_bounded_worker_request_body(request, max_bytes=4))

    assert request.body.get_reader_calls == 0
    assert request.reader.read_calls == 0


def test_text_fallback_is_only_used_when_stream_shape_is_absent() -> None:
    request = _Request(fallback_text="abcd")
    body = asyncio.run(read_bounded_worker_request_body(request, max_bytes=4))

    assert body == b"abcd"
    assert request.text_calls == 1

    oversized = _Request(fallback_text="abcde")
    with pytest.raises(RequestBodyTooLarge):
        asyncio.run(read_bounded_worker_request_body(oversized, max_bytes=4))
