"""Private isolated Parser Authority Worker for PADIEM Chat (#2824).

The production Chat Worker cannot run the synchronous pypdf/openpyxl parser in
its own isolate: a Python Worker has no process isolation and cannot bound or
kill synchronous CPU work. This Worker is that isolation boundary. Chat reaches
it only through the deployment-owned ``DOCUMENT_PARSER_SERVICE`` Service
Binding, forwards the already-bounded Core request envelope, and receives the
already-validated Core result envelope.

Routes
------
``POST /internal/v1/parse``
    Runs the existing reviewed Core binary parser
    (``padiem_ai_core.isolated_parser_service`` -> ``extract_binary_document``)
    over one bounded request envelope and returns the bounded response
    envelope, including page/slide/table-row provenance.

Every document-level failure is a **200** response carrying the contract's
``{"type": "error", "code": ...}`` envelope, so the Chat-side client applies
the same bounded code mapping it applies to a local parse. Route, method,
content-type and transport-level refusals answer a non-200 status; the Chat
transport treats those as an unavailable service and fails closed.

This Worker holds no storage, no user identity and no model authority. It sees
only the document identity and bytes that Chat already validated, and it never
logs a document name or body.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from workers import Response, WorkerEntrypoint

from padiem_ai_core.isolated_parser_contract import (
    ISOLATED_PARSER_MAX_REQUEST_BYTES,
    encode_error,
)
from padiem_ai_core.isolated_parser_service import handle_isolated_parser_request

PARSE_PATH = "/internal/v1/parse"

_JSON_HEADERS = {
    "Content-Type": "application/json",
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
}


class _BodyTooLarge(Exception):
    """The body crossed the contract ceiling while it was being received."""


class _BodyUnreadable(Exception):
    """The request stream could not be read at all."""


def _chunk_bytes(value: Any) -> bytes:
    """Decode one workerd stream chunk; a JS typed array is not Python bytes.

    The Python Workers SDK hands a Uint8Array chunk over as a proxy that
    exposes ``to_bytes()`` (and, for converted values, ``to_py()``), so both
    conversions are tried before treating the chunk as a buffer.
    """

    if value is None:
        return b""
    if isinstance(value, bytes):
        return value
    if isinstance(value, (bytearray, memoryview)):
        return bytes(value)
    to_py = getattr(value, "to_py", None)
    if callable(to_py):
        converted = to_py()
        if converted is not None:
            return bytes(converted)
    to_bytes = getattr(value, "to_bytes", None)
    if callable(to_bytes):
        converted = to_bytes()
        return converted if isinstance(converted, bytes) else bytes(converted)
    return memoryview(value).tobytes()


async def _cancel(reader: Any) -> None:
    cancel = getattr(reader, "cancel", None)
    if not callable(cancel):
        return
    try:
        await cancel()
    except Exception:
        pass


def _release(reader: Any) -> None:
    release = getattr(reader, "releaseLock", None)
    if callable(release):
        try:
            release()
        except Exception:
            pass


async def _read_bounded_body(request: Any, *, max_bytes: int) -> bytes:
    """Receive one body without ever retaining more than ``max_bytes``.

    Same enforcement as the shared Worker and Service-Binding readers in this
    repository: the ceiling is checked on every chunk, so an absent or wrong
    ``Content-Length`` cannot make the Worker buffer a body it will refuse. The
    stream is cancelled at the chunk that crosses the bound. The ``text()``
    branch only exists for a body shape that is not a workerd ReadableStream;
    a production request always takes the streaming branch.
    """

    body = getattr(request, "body", None)
    get_reader = getattr(body, "getReader", None)
    if not callable(get_reader):
        try:
            text = await request.text()
        except Exception as exc:
            raise _BodyUnreadable from exc
        raw = text.encode("utf-8") if isinstance(text, str) else bytes(text)
        if len(raw) > max_bytes:
            raise _BodyTooLarge
        return raw

    try:
        reader = get_reader()
    except Exception as exc:
        raise _BodyUnreadable from exc

    chunks: list[bytes] = []
    total = 0
    try:
        while True:
            try:
                result = await reader.read()
            except Exception as exc:
                await _cancel(reader)
                raise _BodyUnreadable from exc
            if bool(getattr(result, "done", False)):
                break
            try:
                chunk = _chunk_bytes(getattr(result, "value", None))
            except Exception as exc:
                await _cancel(reader)
                raise _BodyUnreadable from exc
            if total + len(chunk) > max_bytes:
                await _cancel(reader)
                raise _BodyTooLarge
            if chunk:
                chunks.append(chunk)
                total += len(chunk)
    finally:
        _release(reader)
    return b"".join(chunks)


def _json_error(status: int, code: str) -> Response:
    return Response(encode_error(code), status=status, headers=_JSON_HEADERS)


class Default(WorkerEntrypoint):
    async def fetch(self, request: Any) -> Response:
        if urlparse(str(request.url)).path != PARSE_PATH:
            return _json_error(404, "not_found")
        if str(request.method).upper() != "POST":
            return _json_error(405, "method_not_allowed")

        headers = getattr(request, "headers", None)
        content_type = headers.get("content-type") if headers is not None else None
        if (
            not isinstance(content_type, str)
            or content_type.split(";", 1)[0].strip().lower() != "application/json"
        ):
            return _json_error(415, "unsupported_media_type")

        declared = headers.get("content-length") if headers is not None else None
        if declared:
            try:
                if int(declared) > ISOLATED_PARSER_MAX_REQUEST_BYTES:
                    return _json_error(413, "request_too_large")
            except (TypeError, ValueError):
                return _json_error(400, "invalid_content_length")

        # A declared length is only a pre-check: the ceiling is enforced again on
        # every received chunk, so a missing or understated header cannot make
        # this Worker buffer a body larger than the contract allows.
        try:
            body = await _read_bounded_body(
                request, max_bytes=ISOLATED_PARSER_MAX_REQUEST_BYTES,
            )
        except _BodyTooLarge:
            return _json_error(413, "request_too_large")
        except _BodyUnreadable:
            return _json_error(400, "invalid_request_body")
        if not body:
            return _json_error(400, "empty_request_body")

        envelope = handle_isolated_parser_request(body)
        return Response(envelope, status=200, headers=_JSON_HEADERS)


__all__ = ["Default", "PARSE_PATH"]
