"""Bounded Cloudflare Service Binding response-body helpers.

Production workerd Responses expose a ReadableStream body.  These helpers keep
the byte ceiling active while that stream is consumed and centralize the proxy
chunk conversion shared by completed and streaming Chat transports.
"""

from __future__ import annotations

from typing import Any


class ServiceBindingResponseError(RuntimeError):
    pass


class ServiceBindingResponseTooLarge(ServiceBindingResponseError):
    pass


def cloudflare_chunk_bytes(value: Any) -> bytes:
    """Convert one already-delivered workerd stream chunk without whole-body buffering."""

    if value is None:
        return b""
    if isinstance(value, bytes):
        return value
    if isinstance(value, (bytearray, memoryview)):
        return bytes(value)

    try:
        return memoryview(value).tobytes()
    except (TypeError, ValueError):
        pass

    to_bytes = getattr(value, "to_bytes", None)
    if callable(to_bytes):
        try:
            converted = to_bytes()
        except Exception as exc:
            raise ServiceBindingResponseError("service binding returned unreadable bytes") from exc
        if isinstance(converted, (bytes, bytearray, memoryview)):
            return bytes(converted)
        try:
            return bytes(converted)
        except Exception as exc:
            raise ServiceBindingResponseError("service binding returned unreadable bytes") from exc

    try:
        return bytes(value)
    except (TypeError, ValueError) as exc:
        raise ServiceBindingResponseError("service binding returned unsupported bytes") from exc


async def _cancel_reader(reader: Any) -> None:
    cancel = getattr(reader, "cancel", None)
    if not callable(cancel):
        return
    try:
        await cancel()
    except Exception:
        pass


def _release_reader(reader: Any) -> None:
    release_lock = getattr(reader, "releaseLock", None)
    if not callable(release_lock):
        return
    try:
        release_lock()
    except Exception:
        pass


async def read_bounded_service_binding_body(
    response: Any,
    *,
    max_bytes: int,
    allow_text_fallback: bool = True,
) -> bytes:
    """Read a Service Binding response with a hard aggregate byte ceiling.

    Workerd's ReadableStream path is always used when available.  The text()
    fallback exists for narrow CPython/test adapters that predate stream-shaped
    fakes; real workerd Responses expose body.getReader().
    """

    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 1:
        raise ValueError("max_bytes must be a positive integer")

    body = getattr(response, "body", None)
    get_reader = getattr(body, "getReader", None)
    if callable(get_reader):
        try:
            reader = get_reader()
        except Exception as exc:
            raise ServiceBindingResponseError("service binding stream reader is unavailable") from exc

        raw = bytearray()
        try:
            while True:
                result = await reader.read()
                if bool(getattr(result, "done", False)):
                    return bytes(raw)
                chunk = cloudflare_chunk_bytes(getattr(result, "value", None))
                if len(raw) + len(chunk) > max_bytes:
                    await _cancel_reader(reader)
                    raise ServiceBindingResponseTooLarge("service binding response exceeded the byte limit")
                raw.extend(chunk)
        except ServiceBindingResponseTooLarge:
            raise
        except ServiceBindingResponseError:
            await _cancel_reader(reader)
            raise
        except Exception as exc:
            await _cancel_reader(reader)
            raise ServiceBindingResponseError("service binding response read failed") from exc
        finally:
            _release_reader(reader)

    if not allow_text_fallback:
        raise ServiceBindingResponseError("service binding response stream is unavailable")
    text_method = getattr(response, "text", None)
    if not callable(text_method):
        raise ServiceBindingResponseError("service binding response body is unavailable")
    try:
        text = await text_method()
    except Exception as exc:
        raise ServiceBindingResponseError("service binding response read failed") from exc
    if not isinstance(text, str):
        raise ServiceBindingResponseError("service binding response text is invalid")
    encoded = text.encode("utf-8")
    if len(encoded) > max_bytes:
        raise ServiceBindingResponseTooLarge("service binding response exceeded the byte limit")
    return encoded
