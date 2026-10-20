"""Incremental request-body reader for bounded public HTTP routes."""

from __future__ import annotations

from typing import Any
from tempfile import SpooledTemporaryFile
from contextlib import asynccontextmanager


class RequestBodyTooLarge(ValueError):
    """Raised as soon as a request body crosses its route-specific byte ceiling."""


async def read_bounded_request_body(request: Any, *, max_bytes: int | None) -> bytes:
    """Read a Starlette-style request stream without materializing past *max_bytes*.

    A valid Content-Length above the limit is rejected before the stream is
    touched. Missing, chunked, or malformed lengths are handled by the same
    incremental byte counter, so the application limit remains real during
    reception rather than becoming a post-hoc check.
    """

    # #4379: ``max_bytes=None`` means the route declares no PADIEM byte total.
    # The reader stays incremental in both cases, so a body is never
    # materialized past the platform's own request limit.
    if max_bytes is not None and (
        isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 1
    ):
        raise ValueError("max_bytes must be a positive integer or None")

    headers = getattr(request, "headers", None)
    if headers is not None and max_bytes is not None:
        declared = headers.get("content-length")
        if declared is not None:
            try:
                declared_bytes = int(declared)
            except (TypeError, ValueError):
                declared_bytes = None
            if declared_bytes is not None and declared_bytes > max_bytes:
                raise RequestBodyTooLarge("request body exceeded the byte limit")

    stream = getattr(request, "stream", None)
    if callable(stream):
        raw = bytearray()
        async for chunk in stream():
            if not isinstance(chunk, (bytes, bytearray, memoryview)):
                raise TypeError("request stream yielded non-bytes")
            chunk_bytes = bytes(chunk)
            if max_bytes is not None and len(raw) + len(chunk_bytes) > max_bytes:
                raise RequestBodyTooLarge("request body exceeded the byte limit")
            raw.extend(chunk_bytes)
        return bytes(raw)

    # Narrow compatibility path for existing unit-test/request adapters that
    # predate Starlette's stream() shape. Production Starlette Requests always
    # expose stream(), so the deployed HTTP boundary never uses this fallback.
    body = getattr(request, "body", None)
    if not callable(body):
        raise TypeError("request stream is unavailable")
    raw_body = await body()
    if not isinstance(raw_body, (bytes, bytearray, memoryview)):
        raise TypeError("request body is not bytes")
    raw_bytes = bytes(raw_body)
    if max_bytes is not None and len(raw_bytes) > max_bytes:
        raise RequestBodyTooLarge("request body exceeded the byte limit")
    return raw_bytes


@asynccontextmanager
async def open_bounded_spooled_request(request: Any, *, max_bytes: int, spool_threshold: int = 256 * 1024):
    """Receive binary request chunks into a seekable temporary file.

    The existing parser still expects bytes; this avoids building an additional
    ever-growing Python bytearray while receiving the upload.
    """
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 1:
        raise ValueError("max_bytes must be a positive integer")
    declared = getattr(request, "headers", {}).get("content-length")
    if declared is not None:
        try:
            declared_size = int(declared)
        except (TypeError, ValueError):
            declared_size = None
        if declared_size is not None and declared_size > max_bytes:
            raise RequestBodyTooLarge("request body exceeded the byte limit")
    with SpooledTemporaryFile(max_size=spool_threshold, mode="w+b") as file:
        total = 0
        async for chunk in request.stream():
            if not isinstance(chunk, (bytes, bytearray, memoryview)):
                raise TypeError("request stream yielded non-bytes")
            total += len(chunk)
            if total > max_bytes:
                raise RequestBodyTooLarge("request body exceeded the byte limit")
            file.write(chunk)
        file.seek(0)
        yield file
