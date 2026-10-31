"""#2824: existing Core parsers keep source provenance for the model.

The extraction entry point stays the reviewed Core parser. This slice adds no
second parser and no new size/page/row ceiling: it preserves the page, slide,
table-row and sheet/cell/formula facts that the flat text already contained,
so a model can answer "which page/sheet/slide" questions from the same read.
"""

from __future__ import annotations

import sys
from io import BytesIO
from unittest import mock
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from padiem_ai_core.document_normalization import extract_binary_document
from padiem_ai_core.document_parser_boundary import (
    PRODUCTION_WORKER_PLATFORM,
    binary_document_parser_ready,
    clear_worker_isolated_parser_composition,
    install_worker_isolated_parser_composition,
)

PDF_MIME = "application/pdf"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _zip_bytes(entries: dict[str, bytes]) -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for name, payload in entries.items():
            archive.writestr(name, payload)
    return output.getvalue()


def _text_pdf(pages: list[str]) -> bytes:
    PdfWriter = pytest.importorskip("pypdf").PdfWriter
    generic = pytest.importorskip("pypdf.generic")
    writer = PdfWriter()
    font = generic.DictionaryObject(
        {
            generic.NameObject("/Type"): generic.NameObject("/Font"),
            generic.NameObject("/Subtype"): generic.NameObject("/Type1"),
            generic.NameObject("/BaseFont"): generic.NameObject("/Helvetica"),
        }
    )
    font_ref = writer._add_object(font)
    for text in pages:
        page = writer.add_blank_page(width=320, height=180)
        page[generic.NameObject("/Resources")] = generic.DictionaryObject(
            {
                generic.NameObject("/Font"): generic.DictionaryObject(
                    {generic.NameObject("/F1"): font_ref}
                )
            }
        )
        content = generic.DecodedStreamObject()
        escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        content.set_data(f"BT /F1 14 Tf 36 90 Td ({escaped}) Tj ET".encode("ascii"))
        page[generic.NameObject("/Contents")] = writer._add_object(content)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def _docx_xml() -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body>"
        "<w:p><w:r><w:t>Padiem body paragraph</w:t></w:r></w:p>"
        "<w:tbl>"
        "<w:tr>"
        "<w:tc><w:p><w:r><w:t>Item</w:t></w:r></w:p></w:tc>"
        "<w:tc><w:p><w:r><w:t>Value</w:t></w:r></w:p></w:tc>"
        "</w:tr>"
        "<w:tr>"
        "<w:tc><w:p><w:r><w:t>Alpha</w:t></w:r></w:p></w:tc>"
        "<w:tc><w:p><w:r><w:t>42</w:t></w:r></w:p></w:tc>"
        "</w:tr>"
        "</w:tbl>"
        "<w:p><w:r><w:t>Padiem closing paragraph</w:t></w:r></w:p>"
        "</w:body></w:document>"
    ).encode()


def _pptx_xml(text: str) -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        '<p:cSld><p:spTree><p:sp><p:txBody><a:p><a:r><a:t>'
        + text
        + "</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld></p:sld>"
    ).encode()


def _xlsx_bytes() -> bytes:
    Workbook = pytest.importorskip("openpyxl").Workbook
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Revenue"
    sheet["A1"] = "Month"
    sheet["B1"] = "Amount"
    sheet["A2"] = "January"
    sheet["B2"] = 10
    sheet["A3"] = "February"
    sheet["B3"] = 20
    sheet["B4"] = "=SUM(B2:B3)"
    output = BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()


def _locators(document) -> list[tuple[str | None, str | None]]:
    return [
        (segment.locator.kind.value, segment.locator.value)
        if segment.locator is not None
        else (None, None)
        for segment in document.segments
    ]


def test_pdf_keeps_exact_page_numbers() -> None:
    payload = _text_pdf(
        [
            "Padiem page one token 4317",
            "The launch code on page two is 2824.",
        ]
    )
    document = extract_binary_document(name="report.pdf", media_type=PDF_MIME, payload=payload)

    assert _locators(document) == [("page", "1"), ("page", "2")]
    assert "Padiem page one token 4317" in document.text
    assert "The launch code on page two is 2824." in document.text


def test_docx_keeps_body_order_and_table_rows() -> None:
    payload = _zip_bytes({"word/document.xml": _docx_xml()})
    document = extract_binary_document(name="report.docx", media_type=DOCX_MIME, payload=payload)

    assert _locators(document) == [(None, None), ("row", "1.1"), ("row", "1.2"), (None, None)]
    assert document.text == (
        "Padiem body paragraph\n"
        "Item | Value\n"
        "Alpha | 42\n"
        "Padiem closing paragraph"
    )


def test_pptx_keeps_slide_numbers_and_order() -> None:
    payload = _zip_bytes(
        {
            "ppt/slides/slide2.xml": _pptx_xml("Slide two: budget 2824"),
            "ppt/slides/slide1.xml": _pptx_xml("Slide one: overview"),
        }
    )
    document = extract_binary_document(name="deck.pptx", media_type=PPTX_MIME, payload=payload)

    assert _locators(document) == [("slide", "1"), ("slide", "2")]
    assert document.text == "Slide one: overview\nSlide two: budget 2824"


def test_xlsx_keeps_sheet_cell_and_formula_meaning() -> None:
    document = extract_binary_document(name="book.xlsx", media_type=XLSX_MIME, payload=_xlsx_bytes())

    assert "[Revenue!A1] Month" in document.text
    assert "[Revenue!B2] 10" in document.text
    # The formula text and the absence of a computed cached value are both
    # visible; openpyxl-created files do not compute formulas on save.
    assert "[Revenue!B4] =SUM(B2:B3) => (no cached value)" in document.text
    assert len(document.segments) == 1
    assert document.segments[0].locator is None


def test_readiness_reflects_the_installed_parser_authority() -> None:
    class _Authority:
        def parse_binary_document(self, *, name, media_type, payload):
            raise AssertionError("not called")

    assert binary_document_parser_ready() is True
    with mock.patch.object(sys, "platform", PRODUCTION_WORKER_PLATFORM):
        assert binary_document_parser_ready() is False
        install_worker_isolated_parser_composition(_Authority())
        try:
            assert binary_document_parser_ready() is True
        finally:
            clear_worker_isolated_parser_composition()
        assert binary_document_parser_ready() is False
    assert binary_document_parser_ready() is True
