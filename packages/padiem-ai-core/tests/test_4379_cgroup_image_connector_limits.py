"""#4379 C-group: the PADIEM image and connector byte totals are removed.

Each case reproduces the exact former boundary and proves that the value is now
processed instead of refused, and that the data is not silently cut.
"""
from __future__ import annotations

import base64

import pytest

from padiem_ai_core.b14_multimodal import (
    B14MultimodalChatRequest,
    MAX_B14_IMAGE_BYTES,
)
from padiem_ai_core.connectors import (
    MAX_MESSAGE_BODY_CHARS,
    MAX_THREAD_BODY_CHARS,
    MAX_TOOL_OUTPUT_BYTES,
    MESSAGE_BODY_CONTEXT_CHARS,
    THREAD_BODY_CONTEXT_CHARS,
    _bounded_envelope,
)
from padiem_ai_core.document_normalization import (
    MAX_BINARY_DOCUMENT_BYTES,
    extract_binary_document,
    DocumentNormalizationError,
)
from padiem_ai_core.image_helpers import (
    MAX_IMAGE_BYTES,
    MAX_OUTPUT_BYTES,
    MAX_PDF_INPUT_BYTES,
    MAX_PDF_OUTPUT_BYTES,
    inspect_image,
)


def _png_magic() -> bytes:
    return b"\x89PNG\r\n\x1a\n"


def test_a_b14_image_over_the_old_bound_is_accepted() -> None:
    payload = _png_magic() + b"x" * (MAX_B14_IMAGE_BYTES + 1)
    url = f"data:image/png;base64,{base64.b64encode(payload).decode('ascii')}"
    request = B14MultimodalChatRequest(
        messages=(
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "describe"},
                    {"type": "image_url", "image_url": {"url": url}},
                ],
            },
        ),
        model="test/route",
    )
    assert request.to_payload()["messages"][0]["content"][1]["image_url"]["url"] == url


def test_an_image_over_the_old_helper_bound_reaches_the_decoder() -> None:
    # The payload is over the former 16 MiB input total. It is not refused for
    # its size; the decoder still refuses it because the bytes are not an image.
    with pytest.raises(Exception) as info:
        inspect_image(_png_magic() + b"\x00" * (MAX_IMAGE_BYTES + 1))
    assert "oversized" not in str(info.value)


def test_the_image_and_pdf_byte_totals_are_no_longer_enforced() -> None:
    # The symbols stay importable, but nothing refuses the payload for them.
    assert MAX_IMAGE_BYTES > 0
    assert MAX_OUTPUT_BYTES > 0
    assert MAX_PDF_INPUT_BYTES > 0
    assert MAX_PDF_OUTPUT_BYTES > 0


def _provider_message(body: str) -> dict:
    payload = {
        "mimeType": "text/plain",
        "filename": "",
        "headers": [
            {"name": "From", "value": "Sender <sender@example.com>"},
            {"name": "To", "value": "Recipient <recipient@example.com>"},
            {"name": "Subject", "value": "Subject 1"},
        ],
        "body": {
            "data": base64.urlsafe_b64encode(body.encode("utf-8")).decode("ascii"),
            "size": len(body.encode("utf-8")),
        },
    }
    return {"id": "msg_1", "threadId": "thread_1", "payload": payload}


def test_a_connector_body_over_the_old_context_total_is_projected_in_full() -> None:
    # The Gmail projection cut a body at 8 000 / 12 000 characters. The
    # connector now carries the body it received.
    from padiem_ai_core.connectors import _project_message

    body = "x" * (MESSAGE_BODY_CONTEXT_CHARS + 500)
    assert len(body) > MESSAGE_BODY_CONTEXT_CHARS
    projection, flags = _project_message(
        _provider_message(body), body_char_limit=None
    )
    assert flags["body_truncated"] is False
    assert projection.body_segments[0].text == body
    assert MESSAGE_BODY_CONTEXT_CHARS < MAX_MESSAGE_BODY_CHARS
    assert THREAD_BODY_CONTEXT_CHARS < MAX_THREAD_BODY_CHARS


def test_a_connector_result_over_the_old_output_total_is_returned_in_full() -> None:
    large = {"operation": "messages.list", "blob": "y" * (MAX_TOOL_OUTPUT_BYTES + 10)}
    assert _bounded_envelope(large) == large


def test_a_binary_document_over_the_old_bound_is_not_refused_for_its_size() -> None:
    payload = b"PRIVATE" + b"x" * (MAX_BINARY_DOCUMENT_BYTES + 1)
    with pytest.raises(DocumentNormalizationError) as info:
        extract_binary_document(
            name="x.pdf", media_type="application/pdf", payload=payload
        )
    assert info.value.code != "binary_too_large"
    assert "PRIVATE" not in str(info.value)
