"""Incremental request-body reader for bounded public HTTP routes."""

from __future__ import annotations

from typing import Any


class RequestBodyTooLarge(ValueError):
    """Raised as soon as a request body crosses its route-specific byte ceiling."""


async def read_bounded_request_body(request: Any, *, max_bytes: int) -> bytes:
    """Read a Starlette-style request stream without materializing past *max_bytes*.

    A valid Content-Length above the limit is rejected before the stream is
    touched. Missing, chunked, or malformed lengths are handled by the same
    incremental byte counter, so the application limit remains real during
    reception rather than becoming a post-hoc check.
    """

    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 1:
        raise ValueError("max_bytes must be a positive integer")

    headers = getattr(request, "headers", None)
    if headers is not None:
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
            if len(raw) + len(chunk_bytes) > max_bytes:
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
    if len(raw_bytes) > max_bytes:
        raise RequestBodyTooLarge("request body exceeded the byte limit")
    return raw_bytes
