"""Asynchronous isolated parser client for the Cloudflare Worker (#2824).

Why this module exists
----------------------
A Cloudflare Service Binding ``fetch`` is asynchronous, and the Chat Worker
must await it without blocking the isolate. The synchronous client in
``isolated_parser_client`` cannot await that transport, so this module owns the
async caller surface over the exact same bounded wire contract. It adds no
second parser, endpoint, credential, deadline or parser-selection input; the
transport is injected only by trusted server composition.

Raw transport exceptions never cross this boundary: they collapse to the
bounded ``isolated_parser_transport_failed`` code after the ``except`` block so
no exception text is left on ``__context__`` or ``__cause__``.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from .document_normalization import NormalizedDocument, validate_document_identity
from .document_semantics import DocumentNormalizationError
from .isolated_parser_client import _bounded_binary_payload
from .isolated_parser_contract import (
    ISOLATED_PARSER_TRANSPORT_FAILED,
    decode_response,
    encode_request,
)

_TRANSPORT_FAILED_MESSAGE = (
    "Isolated parser transport failed before a bounded response was available."
)


@runtime_checkable
class AsyncIsolatedParserTransport(Protocol):
    """Trusted async transport port for one isolated parse round-trip."""

    async def exchange(self, request: bytes) -> bytes: ...


class IsolatedParserAsyncClient:
    """Bounded async isolated-parser client over an injected transport."""

    __slots__ = ("_transport",)

    def __init__(self, *, transport: AsyncIsolatedParserTransport) -> None:
        if transport is None:
            raise ValueError("transport is required")
        if not callable(getattr(transport, "exchange", None)):
            raise ValueError("transport must provide exchange(request) -> bytes")
        object.__setattr__(self, "_transport", transport)

    @property
    def transport(self) -> AsyncIsolatedParserTransport:
        """Injected transport reference (trusted composition only; read-only)."""

        return self._transport  # type: ignore[attr-defined]

    async def parse_binary_document(
        self,
        *,
        name: Any,
        media_type: Any,
        payload: Any,
    ) -> NormalizedDocument:
        safe_name, safe_media = validate_document_identity(
            name=name,
            media_type=media_type,
            source_kind="binary",
        )
        binary = _bounded_binary_payload(payload)
        request = encode_request(
            name=safe_name, media_type=safe_media, payload=binary,
        )
        transport_failed = False
        raw: Any = None
        try:
            raw = await self._transport.exchange(request)
        except DocumentNormalizationError:
            raise
        except Exception:
            transport_failed = True
        if transport_failed:
            raise DocumentNormalizationError(
                ISOLATED_PARSER_TRANSPORT_FAILED,
                _TRANSPORT_FAILED_MESSAGE,
            )
        return decode_response(
            raw,
            name=safe_name,
            media_type=safe_media,
            byte_size=len(binary),
        )


__all__ = [
    "AsyncIsolatedParserTransport",
    "IsolatedParserAsyncClient",
]
