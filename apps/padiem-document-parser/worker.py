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

        try:
            text = await request.text()
            body = text.encode("utf-8") if isinstance(text, str) else bytes(text)
        except Exception:
            return _json_error(400, "invalid_request_body")
        if not body:
            return _json_error(400, "empty_request_body")
        if len(body) > ISOLATED_PARSER_MAX_REQUEST_BYTES:
            return _json_error(413, "request_too_large")

        envelope = handle_isolated_parser_request(body)
        return Response(envelope, status=200, headers=_JSON_HEADERS)


__all__ = ["Default", "PARSE_PATH"]
