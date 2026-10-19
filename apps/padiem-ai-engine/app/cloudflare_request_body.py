"""Bounded Cloudflare Workers request-body reader for Engine HTTP entrypoints.

Production Workers Requests expose body.getReader(). The reader below keeps
route byte ceilings real while receiving a request instead of materializing the
whole body first. A narrow request.text() fallback exists only for existing
CPython test doubles that do not model the workerd ReadableStream shape.
"""

from __future__ import annotations

from typing import Any

from app.cloudflare_transport import CloudflareReadableByteStream


class RequestBodyTooLarge(ValueError):
    """Raised as soon as a request crosses its route-specific byte ceiling."""


class RequestBodyReadError(RuntimeError):
    """Raised when the Workers request stream cannot be read safely."""


async def _cancel_reader(reader: Any) -> None:
    cancel = getattr(reader, "cancel", None)
    if not callable(cancel):
        return
    try:
        await cancel()
    except Exception:
        pass


def _release_reader(reader: Any) -> None:
    release = getattr(reader, "releaseLock", None)
    if not callable(release):
        return
    try:
        release()
    except Exception:
        pass


def _declared_length(request: Any) -> int | None:
    headers = getattr(request, "headers", None)
    if headers is None:
        return None
    try:
        raw = headers.get("content-length")
    except Exception:
        return None
    if raw is None:
        return None
    try:
        value = int(str(raw))
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


async def read_bounded_worker_request_body(request: Any, *, max_bytes: int) -> bytes:
    """Read one request body without ever retaining more than max_bytes.

    A valid oversized Content-Length is refused before opening the stream.
    Missing/chunked/malformed lengths are governed by the same incremental byte
    counter. Real workerd requests therefore never use the full-buffer fallback.
    """

    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 1:
        raise ValueError("max_bytes must be a positive integer")

    declared = _declared_length(request)
    if declared is not None and declared > max_bytes:
        raise RequestBodyTooLarge("request body exceeded the byte limit")

    body = getattr(request, "body", None)
    get_reader = getattr(body, "getReader", None)
    if callable(get_reader):
        try:
            reader = get_reader()
        except Exception as exc:
            raise RequestBodyReadError("request stream reader is unavailable") from exc

        chunks: list[bytes] = []
        total = 0
        try:
            while True:
                result = await reader.read()
                if bool(getattr(result, "done", False)):
                    break
                try:
                    chunk = CloudflareReadableByteStream._to_bytes(
                        getattr(result, "value", None)
                    )
                except Exception as exc:
                    await _cancel_reader(reader)
                    raise RequestBodyReadError("request stream yielded unreadable bytes") from exc
                if total + len(chunk) > max_bytes:
                    await _cancel_reader(reader)
                    raise RequestBodyTooLarge("request body exceeded the byte limit")
                if chunk:
                    chunks.append(chunk)
                    total += len(chunk)
        except RequestBodyTooLarge:
            raise
        except RequestBodyReadError:
            raise
        except Exception as exc:
            await _cancel_reader(reader)
            raise RequestBodyReadError("request stream read failed") from exc
        finally:
            _release_reader(reader)

        return b"".join(chunks)

    # Compatibility only: existing CPython unit-test Requests often expose
    # text() but no workerd ReadableStream. Production Workers Requests use
    # the streaming branch above.
    text_reader = getattr(request, "text", None)
    if not callable(text_reader):
        raise RequestBodyReadError("request body reader is unavailable")
    try:
        text = await text_reader()
        raw = str(text).encode("utf-8")
    except Exception as exc:
        raise RequestBodyReadError("request body could not be read") from exc
    if len(raw) > max_bytes:
        raise RequestBodyTooLarge("request body exceeded the byte limit")
    return raw
