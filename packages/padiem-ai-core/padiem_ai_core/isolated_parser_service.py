"""Parser-side handler for the isolated parser Worker (#2824).

Why this module exists
----------------------
The standalone ``padiem-document-parser`` Worker receives one bounded JSON
envelope over a private Service Binding. This module is its single handler: it
decodes the envelope, invokes the existing reviewed Core parser
(``extract_binary_document``) inside that isolated Worker's own isolate, and
returns the canonical result — including document provenance — as one bounded
response envelope.

It adds no parser implementation, no document cap and no caller-controlled
parser selection. Every failure is returned as a bounded reason code; raw
exception text, tracebacks, host paths and document content never cross the
service boundary.
"""

from __future__ import annotations

from .document_normalization import extract_binary_document
from .document_semantics import DocumentNormalizationError
from .isolated_parser_contract import (
    ISOLATED_PARSER_INTERNAL_FAILED,
    decode_request,
    encode_document,
    encode_error,
)


def handle_isolated_parser_request(request: bytes) -> bytes:
    """Parse one bounded request envelope and return one bounded response.

    The returned bytes are always a contract envelope: either a canonical
    document with locator provenance or ``{"type": "error", "code": ...}``.
    This function never raises for malformed input or parser failure.
    """

    try:
        name, media_type, payload = decode_request(request)
    except DocumentNormalizationError as exc:
        return encode_error(exc.code)
    except Exception:
        return encode_error(ISOLATED_PARSER_INTERNAL_FAILED)
    try:
        document = extract_binary_document(
            name=name,
            media_type=media_type,
            payload=payload,
        )
        return encode_document(document)
    except DocumentNormalizationError as exc:
        return encode_error(exc.code)
    except Exception:
        return encode_error(ISOLATED_PARSER_INTERNAL_FAILED)


__all__ = ["handle_isolated_parser_request"]
