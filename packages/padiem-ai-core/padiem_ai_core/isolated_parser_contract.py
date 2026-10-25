"""Bounded wire contract shared by the isolated parser client and service (#2824).

Why this module exists
----------------------
``padiem_ai_core.isolated_parser_client`` owns the caller surface and
``padiem_ai_core.isolated_parser_service`` owns the parser-side handler. Both
must agree byte-for-byte on the bounded JSON envelope, including the document
provenance (page/slide/row locators) that #2824 preserves for the model. This
module is that single wire authority: pure stdlib, no network, no process and
no parser implementation of its own.

The envelope carries only the canonical document identity, the payload, and
the already-reviewed Core parse result. No endpoint, host, credential,
deadline or parser-selection field exists on the wire.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
from typing import Any

from .document_normalization import (
    MAX_BINARY_DOCUMENT_BYTES,
    MAX_DOCUMENT_CHARS,
    NormalizedDocument,
    normalize_document_text,
    validate_document_identity,
)
from .document_semantics import (
    MAX_DOCUMENT_SEGMENTS,
    DocumentLocator,
    DocumentNormalizationError,
    DocumentSegment,
    ExtractionStatus,
    LocatorKind,
    LocatorPrecision,
    normalize_document_warnings,
)

#: JSON ``type`` discriminator for the outbound bounded request envelope.
ISOLATED_PARSER_REQUEST_KIND = "isolated_parser_request"
#: JSON ``type`` discriminator for a success response (document material).
ISOLATED_PARSER_DOCUMENT_KIND = "document"
#: JSON ``type`` discriminator for a bounded failure response (reason code).
ISOLATED_PARSER_ERROR_KIND = "error"

#: Response ceiling derived from Core document bounds. A success envelope
#: carries the flat text plus the same content as located segments, and a
#: JSON string may escape up to six bytes per character. Two full
#: ``MAX_DOCUMENT_CHARS`` representations therefore bound the payload; the
#: fixed overhead covers identity, status, warnings and structure. Not caller
#: configurable and not a document content limit.
ISOLATED_PARSER_MAX_RESPONSE_BYTES = (
    2 * MAX_DOCUMENT_CHARS * 6 + 32 * 1024
)

#: Request ceiling derived from ``MAX_BINARY_DOCUMENT_BYTES`` base64
#: expansion plus fixed envelope overhead. Not caller configurable.
ISOLATED_PARSER_MAX_REQUEST_BYTES = ((MAX_BINARY_DOCUMENT_BYTES + 2) // 3) * 4 + 4096

#: Bounded transport-failure code (static message; never carries ``str(exc)``).
ISOLATED_PARSER_TRANSPORT_FAILED = "isolated_parser_transport_failed"
#: Bounded code for a response that exceeds the size ceiling.
ISOLATED_PARSER_RESPONSE_UNBOUNDED = "isolated_parser_response_unbounded"
#: Bounded code for a structurally invalid or over-wide response envelope.
ISOLATED_PARSER_RESPONSE_INVALID = "isolated_parser_response_invalid"
#: Bounded code for a request that exceeds the transport ceiling.
ISOLATED_PARSER_REQUEST_UNBOUNDED = "isolated_parser_request_unbounded"
#: Bounded code for an unexpected parser-side failure.
ISOLATED_PARSER_INTERNAL_FAILED = "isolated_parser_internal_error"

_REQUEST_KIND = ISOLATED_PARSER_REQUEST_KIND
_DOCUMENT_KIND = ISOLATED_PARSER_DOCUMENT_KIND
_ERROR_KIND = ISOLATED_PARSER_ERROR_KIND

_TRANSPORT_FAILED_MESSAGE = (
    "Isolated parser transport failed before a bounded response was available."
)
_RESPONSE_UNBOUNDED_MESSAGE = "Isolated parser response exceeds the size ceiling."
_RESPONSE_INVALID_MESSAGE = "Isolated parser response is not a bounded contract envelope."
_REQUEST_INVALID_MESSAGE = "Isolated parser request is not a bounded contract envelope."

#: Only these keys may appear on a request envelope.
REQUEST_FIELDS = frozenset({"type", "name", "media_type", "payload_b64"})
#: Only these keys may appear on a success document response.
DOCUMENT_RESPONSE_FIELDS = frozenset(
    {
        "type",
        "name",
        "media_type",
        "text",
        "byte_size",
        "source_kind",
        "status",
        "warnings",
        "segments",
    }
)
#: Only these keys may appear on a failure response.
ERROR_RESPONSE_FIELDS = frozenset({"type", "code"})
#: Only these keys may appear on one encoded segment.
SEGMENT_FIELDS = frozenset({"text", "order", "locator"})
#: Only these keys may appear on one encoded locator.
LOCATOR_FIELDS = frozenset({"kind", "value", "precision"})

#: Bounded, machine-only reason-code shape (lowercase token; no paths/spaces).
_SAFE_CODE_RE = re.compile(r"^[a-z][a-z0-9._:-]{0,63}$")


def bounded_failure_code(value: Any) -> str:
    """Return one safe reason code or raise a bounded contract error."""

    if not isinstance(value, str) or not _SAFE_CODE_RE.fullmatch(value):
        raise DocumentNormalizationError(
            ISOLATED_PARSER_RESPONSE_INVALID, _RESPONSE_INVALID_MESSAGE
        )
    return value


def encode_request(*, name: str, media_type: str, payload: bytes) -> bytes:
    """Encode one bounded request envelope; identity must already be validated."""

    envelope = {
        "type": _REQUEST_KIND,
        "name": name,
        "media_type": media_type,
        "payload_b64": base64.b64encode(payload).decode("ascii"),
    }
    return json.dumps(envelope, separators=(",", ":"), sort_keys=True).encode("utf-8")


def decode_request(raw: Any) -> tuple[str, str, bytes]:
    """Validate and decode one request envelope into identity plus original bytes."""

    if not isinstance(raw, (bytes, bytearray)):
        raise DocumentNormalizationError(
            ISOLATED_PARSER_RESPONSE_INVALID, _REQUEST_INVALID_MESSAGE
        )
    body = bytes(raw)
    if not body or len(body) > ISOLATED_PARSER_MAX_REQUEST_BYTES:
        raise DocumentNormalizationError(
            ISOLATED_PARSER_REQUEST_UNBOUNDED, _REQUEST_INVALID_MESSAGE
        )
    try:
        envelope = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise DocumentNormalizationError(
            ISOLATED_PARSER_RESPONSE_INVALID, _REQUEST_INVALID_MESSAGE
        ) from None
    if not isinstance(envelope, dict) or set(envelope) != REQUEST_FIELDS:
        raise DocumentNormalizationError(
            ISOLATED_PARSER_RESPONSE_INVALID, _REQUEST_INVALID_MESSAGE
        )
    if envelope.get("type") != _REQUEST_KIND:
        raise DocumentNormalizationError(
            ISOLATED_PARSER_RESPONSE_INVALID, _REQUEST_INVALID_MESSAGE
        )
    safe_name, safe_media = validate_document_identity(
        name=envelope.get("name"),
        media_type=envelope.get("media_type"),
        source_kind="binary",
    )
    encoded = envelope.get("payload_b64")
    if not isinstance(encoded, str) or not encoded:
        raise DocumentNormalizationError(
            "invalid_binary_payload", "Binary document payload is required."
        )
    try:
        payload = base64.b64decode(encoded.encode("ascii"), validate=True)
    except (UnicodeEncodeError, binascii.Error, ValueError):
        raise DocumentNormalizationError(
            "invalid_binary_payload", "Binary document payload is not valid base64."
        ) from None
    if not payload:
        raise DocumentNormalizationError("empty_document", "Document payload is empty.")
    return safe_name, safe_media, payload


def decode_response(
    raw: Any,
    *,
    name: str,
    media_type: str,
    byte_size: int,
) -> NormalizedDocument:
    """Decode one bounded response envelope into the canonical Core document.

    Error envelopes become the same bounded ``DocumentNormalizationError`` the
    in-process parser raises, so callers cannot distinguish an isolated parse
    failure from a local one by shape alone.
    """

    if not isinstance(raw, (bytes, bytearray)):
        raise DocumentNormalizationError(
            ISOLATED_PARSER_RESPONSE_INVALID, _RESPONSE_INVALID_MESSAGE
        )
    body = bytes(raw)
    if not body:
        raise DocumentNormalizationError(
            ISOLATED_PARSER_RESPONSE_INVALID, _RESPONSE_INVALID_MESSAGE
        )
    if len(body) > ISOLATED_PARSER_MAX_RESPONSE_BYTES:
        raise DocumentNormalizationError(
            ISOLATED_PARSER_RESPONSE_UNBOUNDED, _RESPONSE_UNBOUNDED_MESSAGE
        )
    try:
        envelope = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise DocumentNormalizationError(
            ISOLATED_PARSER_RESPONSE_INVALID, _RESPONSE_INVALID_MESSAGE
        ) from None
    if not isinstance(envelope, dict):
        raise DocumentNormalizationError(
            ISOLATED_PARSER_RESPONSE_INVALID, _RESPONSE_INVALID_MESSAGE
        )
    response_kind = envelope.get("type")
    if response_kind == _ERROR_KIND:
        if set(envelope) - ERROR_RESPONSE_FIELDS:
            raise DocumentNormalizationError(
                ISOLATED_PARSER_RESPONSE_INVALID, _RESPONSE_INVALID_MESSAGE
            )
        code = bounded_failure_code(envelope.get("code"))
        raise DocumentNormalizationError(
            code, "Isolated parser reported a bounded failure."
        )
    if response_kind != _DOCUMENT_KIND:
        raise DocumentNormalizationError(
            ISOLATED_PARSER_RESPONSE_INVALID, _RESPONSE_INVALID_MESSAGE
        )
    return _document_from_envelope(
        envelope, name=name, media_type=media_type, byte_size=byte_size
    )


def encode_error(code: Any) -> bytes:
    """Encode one bounded failure response; unknown codes collapse to a safe code."""

    try:
        safe = bounded_failure_code(code)
    except DocumentNormalizationError:
        safe = ISOLATED_PARSER_INTERNAL_FAILED
    return json.dumps(
        {"type": _ERROR_KIND, "code": safe}, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")


def encode_document(document: NormalizedDocument) -> bytes:
    """Encode one already-reviewed Core document, preserving locator provenance."""

    if not isinstance(document, NormalizedDocument):
        raise DocumentNormalizationError(
            ISOLATED_PARSER_RESPONSE_INVALID, _RESPONSE_INVALID_MESSAGE
        )
    if document.source_kind != "binary":
        raise DocumentNormalizationError(
            ISOLATED_PARSER_RESPONSE_INVALID, _RESPONSE_INVALID_MESSAGE
        )
    envelope = {
        "type": _DOCUMENT_KIND,
        "name": document.name,
        "media_type": document.media_type,
        "text": document.text,
        "byte_size": document.byte_size,
        "source_kind": "binary",
        "status": document.status.value,
        "warnings": list(document.warnings),
        "segments": [_encode_segment(segment) for segment in document.segments],
    }
    raw = json.dumps(envelope, separators=(",", ":"), sort_keys=True).encode("utf-8")
    if len(raw) > ISOLATED_PARSER_MAX_RESPONSE_BYTES:
        return encode_error(ISOLATED_PARSER_RESPONSE_UNBOUNDED)
    return raw


def _encode_segment(segment: DocumentSegment) -> dict[str, Any]:
    locator = segment.locator
    return {
        "text": segment.text,
        "order": segment.order,
        "locator": None if locator is None else locator.to_public_dict(),
    }


def _decode_segment(value: Any) -> DocumentSegment:
    if not isinstance(value, dict) or set(value) != SEGMENT_FIELDS:
        raise DocumentNormalizationError(
            ISOLATED_PARSER_RESPONSE_INVALID, _RESPONSE_INVALID_MESSAGE
        )
    raw_locator = value.get("locator")
    locator: DocumentLocator | None
    if raw_locator is None:
        locator = None
    else:
        if not isinstance(raw_locator, dict) or set(raw_locator) != LOCATOR_FIELDS:
            raise DocumentNormalizationError(
                ISOLATED_PARSER_RESPONSE_INVALID, _RESPONSE_INVALID_MESSAGE
            )
        try:
            locator = DocumentLocator(
                kind=LocatorKind(raw_locator.get("kind")),
                value=raw_locator.get("value"),
                precision=LocatorPrecision(raw_locator.get("precision")),
            )
        except (TypeError, ValueError):
            raise DocumentNormalizationError(
                ISOLATED_PARSER_RESPONSE_INVALID, _RESPONSE_INVALID_MESSAGE
            ) from None
    try:
        return DocumentSegment(
            text=value.get("text"),
            order=value.get("order"),
            locator=locator,
        )
    except DocumentNormalizationError:
        raise DocumentNormalizationError(
            ISOLATED_PARSER_RESPONSE_INVALID, _RESPONSE_INVALID_MESSAGE
        ) from None


def _decode_segments(value: Any) -> tuple[DocumentSegment, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or len(value) > MAX_DOCUMENT_SEGMENTS:
        raise DocumentNormalizationError(
            ISOLATED_PARSER_RESPONSE_INVALID, _RESPONSE_INVALID_MESSAGE
        )
    return tuple(_decode_segment(item) for item in value)


def _document_from_envelope(
    envelope: dict[str, Any],
    *,
    name: str,
    media_type: str,
    byte_size: int,
) -> NormalizedDocument:
    if set(envelope) - DOCUMENT_RESPONSE_FIELDS:
        raise DocumentNormalizationError(
            ISOLATED_PARSER_RESPONSE_INVALID, _RESPONSE_INVALID_MESSAGE
        )
    if envelope.get("source_kind") != "binary":
        raise DocumentNormalizationError(
            ISOLATED_PARSER_RESPONSE_INVALID, _RESPONSE_INVALID_MESSAGE
        )
    if envelope.get("name") != name or envelope.get("media_type") != media_type:
        raise DocumentNormalizationError(
            ISOLATED_PARSER_RESPONSE_INVALID, _RESPONSE_INVALID_MESSAGE
        )
    declared_size = envelope.get("byte_size")
    if isinstance(declared_size, bool) or not isinstance(declared_size, int):
        raise DocumentNormalizationError(
            ISOLATED_PARSER_RESPONSE_INVALID, _RESPONSE_INVALID_MESSAGE
        )
    if declared_size != byte_size:
        raise DocumentNormalizationError(
            ISOLATED_PARSER_RESPONSE_INVALID, _RESPONSE_INVALID_MESSAGE
        )
    try:
        text = normalize_document_text(envelope.get("text"))
    except DocumentNormalizationError:
        raise DocumentNormalizationError(
            ISOLATED_PARSER_RESPONSE_INVALID, _RESPONSE_INVALID_MESSAGE
        ) from None
    raw_status = envelope.get("status", ExtractionStatus.COMPLETE.value)
    try:
        status = ExtractionStatus(raw_status)
    except ValueError:
        raise DocumentNormalizationError(
            ISOLATED_PARSER_RESPONSE_INVALID, _RESPONSE_INVALID_MESSAGE
        ) from None
    raw_warnings = envelope.get("warnings", ())
    if not isinstance(raw_warnings, (list, tuple)):
        raise DocumentNormalizationError(
            ISOLATED_PARSER_RESPONSE_INVALID, _RESPONSE_INVALID_MESSAGE
        )
    try:
        warnings = normalize_document_warnings(tuple(raw_warnings))
        segments = _decode_segments(envelope.get("segments"))
        return NormalizedDocument(
            name=name,
            media_type=media_type,
            text=text,
            byte_size=byte_size,
            source_kind="binary",
            status=status,
            segments=segments,
            warnings=warnings,
        )
    except DocumentNormalizationError:
        raise DocumentNormalizationError(
            ISOLATED_PARSER_RESPONSE_INVALID, _RESPONSE_INVALID_MESSAGE
        ) from None


__all__ = [
    "DOCUMENT_RESPONSE_FIELDS",
    "ERROR_RESPONSE_FIELDS",
    "ISOLATED_PARSER_DOCUMENT_KIND",
    "ISOLATED_PARSER_ERROR_KIND",
    "ISOLATED_PARSER_INTERNAL_FAILED",
    "ISOLATED_PARSER_MAX_REQUEST_BYTES",
    "ISOLATED_PARSER_MAX_RESPONSE_BYTES",
    "ISOLATED_PARSER_REQUEST_KIND",
    "ISOLATED_PARSER_REQUEST_UNBOUNDED",
    "ISOLATED_PARSER_RESPONSE_INVALID",
    "ISOLATED_PARSER_RESPONSE_UNBOUNDED",
    "ISOLATED_PARSER_TRANSPORT_FAILED",
    "LOCATOR_FIELDS",
    "REQUEST_FIELDS",
    "SEGMENT_FIELDS",
    "bounded_failure_code",
    "decode_request",
    "decode_response",
    "encode_document",
    "encode_error",
    "encode_request",
]
