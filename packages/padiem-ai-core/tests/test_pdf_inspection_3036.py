"""#3036 PDF inspect/native page-text foundation tests."""

from __future__ import annotations

from io import BytesIO

import pytest

try:
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
except ModuleNotFoundError:  # pragma: no cover
    PdfWriter = None
    DecodedStreamObject = DictionaryObject = NameObject = None

from padiem_ai_core.document_normalization import (
    MAX_PDF_PAGES,
    PDF_NATIVE_TEXT_ABSENT,
    PDF_NATIVE_TEXT_PRESENT,
    DocumentNormalizationError,
    inspect_pdf,
)


def _pdf(*texts: str) -> bytes:
    if PdfWriter is None:
        pytest.skip("pypdf is provided by the documents extra")
    writer = PdfWriter()
    for text in texts:
        page = writer.add_blank_page(width=320, height=180)
        font = DictionaryObject({
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        })
        font_ref = writer._add_object(font)
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref})
        })
        content = DecodedStreamObject()
        content.set_data(f"BT /F1 14 Tf 36 90 Td ({text}) Tj ET".encode("ascii"))
        page[NameObject("/Contents")] = writer._add_object(content)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def test_inspect_pdf_preserves_exact_page_provenance() -> None:
    result = inspect_pdf(name="report.pdf", media_type="application/pdf", payload=_pdf("Page one", "Page two"))
    assert result.page_count == 2
    assert [(page.page_index, page.page_number, page.text) for page in result.pages] == [
        (0, 1, "Page one"),
        (1, 2, "Page two"),
    ]
    assert all(page.text_source == "native_pypdf" for page in result.pages)
    assert result.native_text_available is True
    assert result.native_text_state == PDF_NATIVE_TEXT_PRESENT
    assert result.safe_dict()["native_text_available"] is True
    assert result.safe_dict()["native_text_state"] == PDF_NATIVE_TEXT_PRESENT
    assert result.safe_dict()["pages"][0]["page_number"] == 1


def test_pdf_inspection_rejects_wrong_media_and_page_limit() -> None:
    with pytest.raises(DocumentNormalizationError) as media:
        inspect_pdf(name="report.txt", media_type="text/plain", payload=b"text")
    assert media.value.code == "unsupported_binary_media_type"
    with pytest.raises(DocumentNormalizationError) as pages:
        inspect_pdf(
            name="report.pdf",
            media_type="application/pdf",
            payload=_pdf(*(["page"] * (MAX_PDF_PAGES + 1))),
        )
    assert pages.value.code == "pdf_page_limit"


def test_pdf_inspection_classifies_no_native_text_without_claiming_scan() -> None:
    result = inspect_pdf(name="scan.pdf", media_type="application/pdf", payload=_pdf(""))
    assert result.pages[0].text == ""
    assert result.pages[0].text_source == "native_pypdf"
    assert result.native_text_available is False
    assert result.native_text_state == PDF_NATIVE_TEXT_ABSENT
    assert "scan" not in result.native_text_state
    assert "render" not in repr(result).lower()
