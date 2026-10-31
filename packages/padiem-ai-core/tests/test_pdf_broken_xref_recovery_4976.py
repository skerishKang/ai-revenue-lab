"""#4976 structural-recovery tests for the Core PDF document-text path.

A damaged cross-reference section is what real exporters actually produce; strict
pypdf refuses the whole file, so the document disappears from PC file reading and
search. These tests pin both the recovery and the gates that must stay closed.
"""

from __future__ import annotations

import pytest

pytest.importorskip("pypdf")

from padiem_ai_core.document_normalization import (
    DocumentNormalizationError,
    extract_binary_document,
    inspect_pdf,
)
from padiem_ai_core.pdf_operations import merge_pdfs

PAGE_TEXT = "PADIEM quarterly revenue summary"


def _plain_pdf(*, broken_xref: bool) -> bytes:
    """Build an uncompressed one-page PDF, optionally with a garbage xref section."""
    objects = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 320 180] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>\nendobj\n",
        b"4 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n",
    ]
    stream = f"BT /F1 12 Tf 20 90 Td ({PAGE_TEXT}) Tj ET".encode("latin-1")
    objects.append(
        b"5 0 obj\n<< /Length " + str(len(stream)).encode() + b" >>\nstream\n"
        + stream + b"\nendstream\nendobj\n"
    )

    body = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for obj in objects:
        offsets.append(len(body))
        body.extend(obj)

    xref_at = len(body)
    if broken_xref:
        body.extend(b"this section was written by a broken exporter\n")
    else:
        body.extend(b"xref\n0 6\n0000000000 65535 f \n")
        for offset in offsets:
            body.extend(("%010d 00000 n \n" % offset).encode())
    body.extend(
        b"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n"
        + str(xref_at).encode()
        + b"\n%%EOF\n"
    )
    return bytes(body)


BROKEN = _plain_pdf(broken_xref=True)
CLEAN = _plain_pdf(broken_xref=False)


def test_clean_pdf_text_still_reads() -> None:
    document = extract_binary_document(name="ok.pdf", media_type="application/pdf", payload=CLEAN)
    assert PAGE_TEXT in document.text


def test_broken_xref_pdf_text_is_recovered() -> None:
    document = extract_binary_document(name="deck.pdf", media_type="application/pdf", payload=BROKEN)
    assert PAGE_TEXT in document.text
    assert document.segments[0].locator.value == "1"


def test_broken_xref_pdf_inspection_reports_native_text() -> None:
    inspection = inspect_pdf(name="deck.pdf", media_type="application/pdf", payload=BROKEN)
    assert inspection.page_count == 1
    assert inspection.native_text_available is True
    assert PAGE_TEXT in inspection.pages[0].text


def test_unrecoverable_pdf_still_reports_pdf_invalid() -> None:
    with pytest.raises(DocumentNormalizationError) as error:
        extract_binary_document(name="junk.pdf", media_type="application/pdf", payload=b"%PDF-broken")
    assert error.value.code == "pdf_invalid"


def test_wrong_magic_still_rejected_on_the_recovery_path() -> None:
    with pytest.raises(DocumentNormalizationError) as error:
        extract_binary_document(name="note.pdf", media_type="application/pdf", payload=b"not a pdf")
    assert error.value.code == "pdf_magic_mismatch"


def test_pdf_operations_keep_the_strict_reader() -> None:
    with pytest.raises(DocumentNormalizationError) as error:
        merge_pdfs((BROKEN,))
    assert error.value.code == "pdf_invalid"
