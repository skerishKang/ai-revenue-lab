"""Provider-neutral Worker isolated parser client contract (#2936, parent #2824).

Why this module exists
----------------------
``padiem_ai_core.document_parser_boundary`` is the single binary parser
*authority* decision: on the production Cloudflare Worker (Pyodide) it fails
closed with ``document_parser_isolation_unavailable`` unless trusted server
composition installs an isolated authority. This module is the caller side of
that authority: a bounded request/response shape plus a transport port whose
transport is injected exclusively by trusted server composition.

The byte-level envelope (including document provenance) lives in
``padiem_ai_core.isolated_parser_contract`` so the parser-side handler and this
client can never drift. This module owns only the synchronous client surface
used by local/CPython callers and the composition seam. The asynchronous
Cloudflare Worker client lives in ``isolated_parser_async_client``.

What this module deliberately does NOT do
-----------------------------------------
* No endpoint, host, base URL, executable, command, module path, parser
  implementation, timeout, deadline or resource-ceiling parameter exists on
  the public surface. Callers provide only the canonical bounded document
  identity and payload.
* No network, process, thread, signal or subprocess primitive is imported or
  referenced. The transport port is abstract; production wiring lives outside
  this module. Tests inject an in-memory fake.
* No raw exception text, traceback, host path, service metadata or
  credential value may cross back through the client: transport failures
  collapse to a bounded ``DocumentNormalizationError`` code.
* Importing this contract never arms a parser. The production Worker still
  raises isolation-unavailable until trusted composition binds a real
  authority.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from .document_normalization import NormalizedDocument, validate_document_identity
from .document_semantics import DocumentNormalizationError
from .isolated_parser_contract import (
    ISOLATED_PARSER_DOCUMENT_KIND,
    ISOLATED_PARSER_ERROR_KIND,
    ISOLATED_PARSER_MAX_REQUEST_BYTES,
    ISOLATED_PARSER_MAX_RESPONSE_BYTES,
    ISOLATED_PARSER_REQUEST_KIND,
    ISOLATED_PARSER_RESPONSE_INVALID,
    ISOLATED_PARSER_RESPONSE_UNBOUNDED,
    ISOLATED_PARSER_TRANSPORT_FAILED,
    decode_response,
    encode_request,
)

_TRANSPORT_FAILED_MESSAGE = (
    "Isolated parser transport failed before a bounded response was available."
)


@runtime_checkable
class IsolatedParserTransport(Protocol):
    """Trusted server-composed transport port for one isolated parse round-trip.

    The transport (and any endpoint, host, deadline or credential it needs)
    is supplied only by trusted server composition at construction time. The
    client passes a single bounded request byte string and expects a single
    bounded response byte string; it never inspects or builds a URL.
    """

    def exchange(self, request: bytes) -> bytes: ...


def _bounded_binary_payload(payload: Any) -> bytes:
    if not isinstance(payload, (bytes, bytearray)):
        raise DocumentNormalizationError(
            "invalid_binary_payload",
            "Binary document payload must be bytes.",
        )
    binary = bytes(payload)
    if not binary:
        raise DocumentNormalizationError("empty_document", "Document payload is empty.")
    # #4379: a binary document carries no PADIEM byte total.
    return binary


class IsolatedParserClient:
    """Bounded isolated-parser client with no caller-controlled transport inputs.

    The constructor requires a trusted injected transport and nothing else.
    ``parse_binary_document`` accepts the same keyword-only surface as
    ``BinaryDocumentParserPort`` (``name``, ``media_type``, ``payload``) so a
    reviewed composition can present this client as that port without widening
    any caller input.
    """

    __slots__ = ("_transport",)

    def __init__(self, *, transport: IsolatedParserTransport) -> None:
        if transport is None:
            raise ValueError("transport is required")
        if not callable(getattr(transport, "exchange", None)):
            raise ValueError("transport must provide exchange(request) -> bytes")
        object.__setattr__(self, "_transport", transport)

    @property
    def transport(self) -> IsolatedParserTransport:
        """Injected transport reference (trusted composition only; read-only)."""

        return self._transport  # type: ignore[attr-defined]

    def parse_binary_document(
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
        # An explicitly binary-capable trusted transport receives original bytes.
        # Existing JSON-only transports retain their published wire contract.
        exchange_binary = getattr(self._transport, "exchange_binary", None)
        request = None if callable(exchange_binary) else encode_request(
            name=safe_name, media_type=safe_media, payload=binary,
        )
        # Raise the bounded failure *after* the except block so the raw
        # exception is never left on ``__context__``/``__cause__`` either.
        transport_failed = False
        raw: Any = None
        try:
            if callable(exchange_binary):
                raw = exchange_binary(name=safe_name, media_type=safe_media, payload=binary)
            else:
                raw = self._transport.exchange(request)  # type: ignore[attr-defined]
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
    "ISOLATED_PARSER_DOCUMENT_KIND",
    "ISOLATED_PARSER_ERROR_KIND",
    "ISOLATED_PARSER_MAX_REQUEST_BYTES",
    "ISOLATED_PARSER_MAX_RESPONSE_BYTES",
    "ISOLATED_PARSER_REQUEST_KIND",
    "ISOLATED_PARSER_RESPONSE_INVALID",
    "ISOLATED_PARSER_RESPONSE_UNBOUNDED",
    "ISOLATED_PARSER_TRANSPORT_FAILED",
    "IsolatedParserClient",
    "IsolatedParserTransport",
]
