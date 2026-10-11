"""Provider-neutral Worker isolated parser client contract (#2936, parent #2824).

Why this module exists
----------------------
``padiem_ai_core.document_parser_boundary`` is the single binary parser
*authority* decision: on the production Cloudflare Worker (Pyodide) it fails
closed with ``document_parser_isolation_unavailable`` because the runtime has
no subprocess/multiprocessing and therefore no reviewed in-Worker isolation
for synchronous CPU parse work. A real Worker parser will require a
separately reviewed isolated runtime/service binding.

This child defines only the missing **client/transport contract** for that
later composition: a bounded request/response shape plus a transport port
whose authority is injected exclusively by trusted server composition. It
does not bind any live service, endpoint, host, command or sandbox, and it
does not change the production Worker fail-closed default.

What this module deliberately does NOT do
-----------------------------------------
* No endpoint, host, base URL, executable, command, module path, parser
  implementation, timeout, deadline or resource-ceiling parameter exists on
  the public surface. Callers provide only the canonical bounded document
  identity and payload.
* No network, process, thread, signal or subprocess primitive is imported or
  referenced. The transport port is abstract; production wiring (when later
  reviewed) lives outside this module. Tests inject an in-memory fake.
* No raw exception text, traceback, host path, service metadata or
  credential value may cross back through the client: transport failures
  collapse to a bounded ``DocumentNormalizationError`` code.
* ``document_parser_boundary.resolve_binary_document_parser_authority`` is
  intentionally untouched. Importing this contract never arms a parser, and
  the production Worker still raises isolation-unavailable until a later
  explicitly reviewed composition binds a real authority.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
from typing import Any, Protocol, runtime_checkable

from .document_normalization import (
    MAX_BINARY_DOCUMENT_BYTES,
    NormalizedDocument,
    normalize_document_text,
    validate_document_identity,
)
from .document_semantics import (
    DocumentNormalizationError,
    ExtractionStatus,
    normalize_document_warnings,
)

#: JSON ``type`` discriminator for the outbound bounded request envelope.
ISOLATED_PARSER_REQUEST_KIND = "isolated_parser_request"
#: JSON ``type`` discriminator for a success response (document material).
ISOLATED_PARSER_DOCUMENT_KIND = "document"
#: JSON ``type`` discriminator for a bounded failure response (reason code).
ISOLATED_PARSER_ERROR_KIND = "error"

#: Response ceiling derived from Core document bounds: worst-case UTF-8
#: expansion of the full ``MAX_DOCUMENT_CHARS`` text budget plus identity,
#: status, warning and JSON structural overhead, with margin. Not caller
#: configurable.
ISOLATED_PARSER_MAX_RESPONSE_BYTES = 256 * 1024

#: Request ceiling derived from ``MAX_BINARY_DOCUMENT_BYTES`` base64
#: expansion plus fixed envelope overhead. Not caller configurable.
ISOLATED_PARSER_MAX_REQUEST_BYTES = ((MAX_BINARY_DOCUMENT_BYTES + 2) // 3) * 4 + 4096

#: Bounded transport-failure code (static message; never carries ``str(exc)``).
ISOLATED_PARSER_TRANSPORT_FAILED = "isolated_parser_transport_failed"
#: Bounded code for a response that exceeds the size ceiling.
ISOLATED_PARSER_RESPONSE_UNBOUNDED = "isolated_parser_response_unbounded"
#: Bounded code for a structurally invalid or over-wide response envelope.
ISOLATED_PARSER_RESPONSE_INVALID = "isolated_parser_response_invalid"

_REQUEST_KIND = ISOLATED_PARSER_REQUEST_KIND
_DOCUMENT_KIND = ISOLATED_PARSER_DOCUMENT_KIND
_ERROR_KIND = ISOLATED_PARSER_ERROR_KIND

_TRANSPORT_FAILED_MESSAGE = (
    "Isolated parser transport failed before a bounded response was available."
)
_RESPONSE_UNBOUNDED_MESSAGE = "Isolated parser response exceeds the size ceiling."
_RESPONSE_INVALID_MESSAGE = "Isolated parser response is not a bounded contract envelope."

#: Only these keys may appear on a success document response.
_DOCUMENT_RESPONSE_FIELDS = frozenset(
    {
        "type",
        "name",
        "media_type",
        "text",
        "byte_size",
        "source_kind",
        "status",
        "warnings",
    }
)
#: Only these keys may appear on a failure response.
_ERROR_RESPONSE_FIELDS = frozenset({"type", "code"})

#: Bounded, machine-only reason-code shape (lowercase token; no paths/spaces).
_SAFE_CODE_RE = re.compile(r"^[a-z][a-z0-9._:-]{0,63}$")

_TRANSPORT_FAILED_NAME = "isolated_parser_transport_failed"
_UNBOUNDED_NAME = "isolated_parser_response_unbounded"
_INVALID_NAME = "isolated_parser_response_invalid"


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
    if len(binary) > MAX_BINARY_DOCUMENT_BYTES:
        raise DocumentNormalizationError(
            "binary_too_large",
            "Binary document exceeds the byte limit.",
        )
    return binary


def _encode_request(*, name: str, media_type: str, payload: bytes) -> bytes:
    envelope = {
        "type": _REQUEST_KIND,
        "name": name,
        "media_type": media_type,
        "payload_b64": base64.b64encode(payload).decode("ascii"),
    }
    raw = json.dumps(envelope, separators=(",", ":"), sort_keys=True).encode("utf-8")
    if len(raw) > ISOLATED_PARSER_MAX_REQUEST_BYTES:
        raise DocumentNormalizationError(
            "isolated_parser_request_unbounded",
            "Isolated parser request exceeds the size ceiling.",
        )
    return raw


def _reject(message_code: str, message: str) -> DocumentNormalizationError:
    return DocumentNormalizationError(message_code, message)


def _decode_json_object(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, (bytes, bytearray)):
        raise _reject(_INVALID_NAME, _RESPONSE_INVALID_MESSAGE)
    body = bytes(raw)
    if not body:
        raise _reject(_INVALID_NAME, _RESPONSE_INVALID_MESSAGE)
    if len(body) > ISOLATED_PARSER_MAX_RESPONSE_BYTES:
        raise _reject(_UNBOUNDED_NAME, _RESPONSE_UNBOUNDED_MESSAGE)
    try:
        decoded = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise _reject(_INVALID_NAME, _RESPONSE_INVALID_MESSAGE) from None
    if not isinstance(decoded, dict):
        raise _reject(_INVALID_NAME, _RESPONSE_INVALID_MESSAGE)
    return decoded


def _bounded_failure_code(value: Any) -> str:
    if not isinstance(value, str) or not _SAFE_CODE_RE.fullmatch(value):
        raise _reject(_INVALID_NAME, _RESPONSE_INVALID_MESSAGE)
    return value


def _document_from_response(
    envelope: dict[str, Any],
    *,
    name: str,
    media_type: str,
    byte_size: int,
) -> NormalizedDocument:
    if set(envelope) - _DOCUMENT_RESPONSE_FIELDS:
        raise _reject(_INVALID_NAME, _RESPONSE_INVALID_MESSAGE)
    if envelope.get("type") != _DOCUMENT_KIND:
        raise _reject(_INVALID_NAME, _RESPONSE_INVALID_MESSAGE)
    if envelope.get("source_kind") != "binary":
        raise _reject(_INVALID_NAME, _RESPONSE_INVALID_MESSAGE)
    if envelope.get("name") != name or envelope.get("media_type") != media_type:
        raise _reject(_INVALID_NAME, _RESPONSE_INVALID_MESSAGE)
    declared_size = envelope.get("byte_size")
    if isinstance(declared_size, bool) or not isinstance(declared_size, int):
        raise _reject(_INVALID_NAME, _RESPONSE_INVALID_MESSAGE)
    if declared_size != byte_size:
        raise _reject(_INVALID_NAME, _RESPONSE_INVALID_MESSAGE)
    try:
        text = normalize_document_text(envelope.get("text"))
    except DocumentNormalizationError:
        raise _reject(_INVALID_NAME, _RESPONSE_INVALID_MESSAGE) from None
    raw_status = envelope.get("status", ExtractionStatus.COMPLETE.value)
    try:
        status = ExtractionStatus(raw_status)
    except ValueError:
        raise _reject(_INVALID_NAME, _RESPONSE_INVALID_MESSAGE) from None
    raw_warnings = envelope.get("warnings", ())
    if not isinstance(raw_warnings, (list, tuple)):
        raise _reject(_INVALID_NAME, _RESPONSE_INVALID_MESSAGE)
    try:
        warnings = normalize_document_warnings(tuple(raw_warnings))
    except DocumentNormalizationError:
        raise _reject(_INVALID_NAME, _RESPONSE_INVALID_MESSAGE) from None
    try:
        return NormalizedDocument(
            name=name,
            media_type=media_type,
            text=text,
            byte_size=byte_size,
            source_kind="binary",
            status=status,
            warnings=warnings,
        )
    except DocumentNormalizationError:
        raise _reject(_INVALID_NAME, _RESPONSE_INVALID_MESSAGE) from None


class IsolatedParserClient:
    """Bounded isolated-parser client with no caller-controlled transport inputs.

    The constructor requires a trusted injected transport and nothing else.
    ``parse_binary_document`` accepts the same keyword-only surface as
    ``BinaryDocumentParserPort`` (``name``, ``media_type``, ``payload``) so a
    later reviewed composition can present this client as that port without
    widening any caller input.
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
        request = _encode_request(name=safe_name, media_type=safe_media, payload=binary)
        # Raise the bounded failure *after* the except block so the raw
        # exception is never left on ``__context__``/``__cause__`` either.
        transport_failed = False
        raw: Any = None
        try:
            raw = self._transport.exchange(request)  # type: ignore[attr-defined]
        except DocumentNormalizationError:
            raise
        except Exception:
            transport_failed = True
        if transport_failed:
            raise DocumentNormalizationError(
                _TRANSPORT_FAILED_NAME,
                _TRANSPORT_FAILED_MESSAGE,
            )
        envelope = _decode_json_object(raw)
        response_kind = envelope.get("type")
        if response_kind == _ERROR_KIND:
            if set(envelope) - _ERROR_RESPONSE_FIELDS:
                raise _reject(_INVALID_NAME, _RESPONSE_INVALID_MESSAGE)
            code = _bounded_failure_code(envelope.get("code"))
            raise DocumentNormalizationError(code, "Isolated parser reported a bounded failure.")
        if response_kind == _DOCUMENT_KIND:
            return _document_from_response(
                envelope,
                name=safe_name,
                media_type=safe_media,
                byte_size=len(binary),
            )
        raise _reject(_INVALID_NAME, _RESPONSE_INVALID_MESSAGE)


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
