from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.service_binding_response import (
    ServiceBindingResponseError,
    ServiceBindingResponseTooLarge,
    cloudflare_chunk_bytes,
    read_bounded_service_binding_body,
)


class FakeReader:
    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.read_count = 0
        self.cancel_count = 0
        self.release_count = 0

    async def read(self):
        self.read_count += 1
        if self.chunks:
            return SimpleNamespace(done=False, value=self.chunks.pop(0))
        return SimpleNamespace(done=True, value=None)

    async def cancel(self):
        self.cancel_count += 1

    def releaseLock(self):
        self.release_count += 1


class FakeBody:
    def __init__(self, reader):
        self.reader = reader
        self.get_reader_count = 0

    def getReader(self):
        self.get_reader_count += 1
        return self.reader


class FakeResponse:
    def __init__(self, chunks, *, fallback_text="fallback"):
        self.reader = FakeReader(chunks)
        self.body = FakeBody(self.reader)
        self.text_calls = 0
        self._fallback_text = fallback_text

    async def text(self):
        self.text_calls += 1
        return self._fallback_text


class IntegerIterableChunk:
    def __init__(self, raw: bytes):
        self._raw = raw

    def __iter__(self):
        return iter(self._raw)


def test_stream_body_is_read_incrementally_without_text_fallback():
    response = FakeResponse([b"abc", IntegerIterableChunk(b"def")])
    body = asyncio.run(
        read_bounded_service_binding_body(response, max_bytes=6)
    )

    assert body == b"abcdef"
    assert response.text_calls == 0
    assert response.reader.read_count == 3
    assert response.reader.cancel_count == 0
    assert response.reader.release_count == 1


def test_stream_overflow_cancels_before_later_chunks_are_read():
    response = FakeResponse([b"12345", b"6", b"never-read"])

    with pytest.raises(ServiceBindingResponseTooLarge):
        asyncio.run(
            read_bounded_service_binding_body(response, max_bytes=5)
        )

    assert response.text_calls == 0
    assert response.reader.read_count == 2
    assert response.reader.cancel_count == 1
    assert response.reader.release_count == 1
    assert response.reader.chunks == [b"never-read"]


def test_unsupported_stream_chunk_fails_closed_and_cancels():
    response = FakeResponse([object()])

    with pytest.raises(ServiceBindingResponseError):
        asyncio.run(
            read_bounded_service_binding_body(response, max_bytes=32)
        )

    assert response.text_calls == 0
    assert response.reader.cancel_count == 1
    assert response.reader.release_count == 1


def test_chunk_conversion_keeps_workerd_integer_iterable_semantics():
    assert cloudflare_chunk_bytes(IntegerIterableChunk(b"typed-array")) == b"typed-array"
