"""#2824 transfer ceiling: what the owner reads when a document is over the cap.

The isolated parser is bounded twice: the request envelope (base64 of the Core
binary bound) and the extracted-text report. Both refusals already carried a
constant reason code, but the Chat wording named the internal component and, for
the response ceiling, told the owner to retry — which can never help a document
that is simply too large. These tests pin the exact/+1 boundary and the plain
Korean answer that is now the only wording for those two codes.
"""

from __future__ import annotations

import pytest

from app.binary_documents import _translate_binary_error, guidance_for_reason_code
import padiem_ai_core.isolated_parser_contract as contract
from padiem_ai_core.document_semantics import DocumentNormalizationError
from padiem_ai_core.isolated_parser_contract import (
    ISOLATED_PARSER_MAX_RESPONSE_BYTES,
    ISOLATED_PARSER_REQUEST_UNBOUNDED,
    ISOLATED_PARSER_RESPONSE_UNBOUNDED,
)
from padiem_ai_core.document_semantics import MAX_SEGMENT_TEXT_CHARS

PDF_MIME = "application/pdf"
OVER_CAP_CODES = (ISOLATED_PARSER_REQUEST_UNBOUNDED, ISOLATED_PARSER_RESPONSE_UNBOUNDED)


def test_request_ceiling_is_exact_and_one_byte_over_is_a_bounded_refusal(monkeypatch) -> None:
    envelope = contract.encode_request(
        name="report.pdf", media_type=PDF_MIME, payload=b"%PDF-1.7 fixture"
    )
    # Pin the ceiling to the envelope's own length: the exact size must reach the
    # decoder, one extra byte must be refused before anything is parsed.
    monkeypatch.setattr(contract, "ISOLATED_PARSER_MAX_REQUEST_BYTES", len(envelope))

    name, media_type, payload = contract.decode_request(envelope)
    assert (name, media_type, payload) == ("report.pdf", PDF_MIME, b"%PDF-1.7 fixture")

    with pytest.raises(DocumentNormalizationError) as info:
        contract.decode_request(envelope + b" ")
    assert info.value.code == ISOLATED_PARSER_REQUEST_UNBOUNDED


def test_response_ceiling_is_the_text_allocation_the_owner_can_be_told_about() -> None:
    # Two six-byte-per-character copies of one segment's worth of text plus the
    # frame. This is a wire allocation, not a document verdict (#5734 stage 2).
    assert ISOLATED_PARSER_MAX_RESPONSE_BYTES == 2 * MAX_SEGMENT_TEXT_CHARS * 6 + 32 * 1024


@pytest.mark.parametrize("code", OVER_CAP_CODES)
@pytest.mark.parametrize("media_type", [PDF_MIME, None])
def test_over_cap_guidance_is_plain_korean(code: str, media_type) -> None:
    message = guidance_for_reason_code(code, media_type)

    assert isinstance(message, str) and message
    for leaked in ("문서 파서", "허용 크기", "다시 시도", "_unbounded", "isolated_"):
        assert leaked not in message, (code, leaked)
    # The one action that changes the outcome.
    assert "나누" in message


def test_over_cap_codes_reach_the_owner_through_the_document_error_path() -> None:
    for code in OVER_CAP_CODES:
        internal = DocumentNormalizationError(code, "isolated parser internal detail")
        translated = _translate_binary_error(internal, PDF_MIME)

        assert str(translated) == guidance_for_reason_code(code, PDF_MIME)
        assert "internal detail" not in str(translated)
        assert code not in str(translated)
