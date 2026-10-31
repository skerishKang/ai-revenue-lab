"""Trusted Service Binding bridge to the isolated Parser Authority (#2824).

The Chat Worker never runs the binary document parser in its own isolate. This
module is the only transport between the existing Core parser authority and the
private ``padiem-document-parser`` Worker: it forwards the already-bounded Core
request envelope over the fixed ``DOCUMENT_PARSER_SERVICE`` binding and returns
the bounded response envelope to the async Core client, which remains the only
component that decodes and validates it.

The target Worker, path and response ceiling are fixed here. No request value,
document name, media type or environment variable can select a different
target, and raw transport failures never carry provider material upward.
"""

from __future__ import annotations

from typing import Any

from padiem_ai_core.document_semantics import DocumentNormalizationError
from padiem_ai_core.isolated_parser_contract import (
    ISOLATED_PARSER_MAX_RESPONSE_BYTES,
    ISOLATED_PARSER_RESPONSE_UNBOUNDED,
)

from .service_binding_response import (
    ServiceBindingResponseError,
    ServiceBindingResponseTooLarge,
    read_bounded_service_binding_body,
)

DOCUMENT_PARSER_SERVICE_ORIGIN = "https://padiem-document-parser"
DOCUMENT_PARSER_SERVICE_PATH = "/internal/v1/parse"

_RESPONSE_UNBOUNDED_MESSAGE = "Isolated parser response exceeds the size ceiling."


class CloudflareDocumentParserServiceTransport:
    """One bounded request/response exchange over the fixed Service Binding."""

    __slots__ = ("_binding", "_request_factory")

    def __init__(self, binding: Any, request_factory: Any) -> None:
        if binding is None:
            raise ValueError("document parser service binding is required")
        if not callable(request_factory):
            raise ValueError("request_factory is required")
        self._binding = binding
        self._request_factory = request_factory

    async def exchange(self, request: bytes) -> bytes:
        if not isinstance(request, (bytes, bytearray)):
            raise ValueError("request must be an encoded contract envelope")
        service_request = self._request_factory(
            DOCUMENT_PARSER_SERVICE_ORIGIN + DOCUMENT_PARSER_SERVICE_PATH,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            body=bytes(request).decode("utf-8"),
        )
        response = await self._binding.fetch(service_request.js_object)
        try:
            status = int(response.status)
        except Exception:
            raise RuntimeError("document parser service response is malformed") from None
        try:
            body = await read_bounded_service_binding_body(
                response,
                max_bytes=ISOLATED_PARSER_MAX_RESPONSE_BYTES,
            )
        except ServiceBindingResponseTooLarge:
            raise DocumentNormalizationError(
                ISOLATED_PARSER_RESPONSE_UNBOUNDED,
                _RESPONSE_UNBOUNDED_MESSAGE,
            ) from None
        except ServiceBindingResponseError:
            raise RuntimeError(
                "document parser service response is unavailable"
            ) from None
        if status != 200:
            raise RuntimeError("document parser service returned a non-success status")
        return bytes(body)


__all__ = [
    "CloudflareDocumentParserServiceTransport",
    "DOCUMENT_PARSER_SERVICE_ORIGIN",
    "DOCUMENT_PARSER_SERVICE_PATH",
]
