"""#2824: Chat attaches the existing Core parser result with provenance.

Parse success is proven here against real synthetic PDF/DOCX/PPTX/XLSX bytes.
The model-facing context test proves the page/slide/table/sheet/formula facts
reach the same reference-context seam the provider request already uses; it is
not a mock of the parser.
"""

from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import httpx
import pytest

from app.attachments import parse_attachments
from app.documents import DocumentAttachment, build_document_context

PDF_MIME = "application/pdf"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"


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


def _attachment(name: str, media_type: str, payload: bytes) -> DocumentAttachment:
    parsed = parse_attachments(
        [
            {
                "type": "document",
                "name": name,
                "media_type": media_type,
                "base64": base64.b64encode(payload).decode("ascii"),
            }
        ]
    )
    assert len(parsed) == 1
    assert isinstance(parsed[0], DocumentAttachment)
    return parsed[0]


def test_pdf_page_provenance_reaches_the_model_context() -> None:
    attachment = _attachment(
        "report.pdf",
        PDF_MIME,
        _text_pdf(
            [
                "Padiem page one token 4317",
                "The launch code on page two is 2824.",
            ]
        ),
    )
    context = build_document_context(attachment)

    assert "[페이지 1]" in context
    assert "[페이지 2]" in context
    assert "Padiem page one token 4317" in context
    assert "The launch code on page two is 2824." in context
    assert "첨부 문서 데이터 규칙" in context
    assert "Alpha" not in repr(attachment)


def test_docx_body_and_table_values_reach_the_model_context() -> None:
    attachment = _attachment(
        "report.docx",
        DOCX_MIME,
        _zip_bytes({"word/document.xml": _docx_xml()}),
    )
    context = build_document_context(attachment)

    assert "Padiem body paragraph" in context
    assert "[표 1 행 2]" in context
    assert "Alpha | 42" in context
    assert "Padiem closing paragraph" in context


def test_pptx_slide_provenance_reaches_the_model_context() -> None:
    attachment = _attachment(
        "deck.pptx",
        PPTX_MIME,
        _zip_bytes(
            {
                "ppt/slides/slide2.xml": _pptx_xml("Slide two: budget 2824"),
                "ppt/slides/slide1.xml": _pptx_xml("Slide one: overview"),
            }
        ),
    )
    context = build_document_context(attachment)

    assert "[슬라이드 1]" in context
    assert "[슬라이드 2]" in context
    assert "Slide two: budget 2824" in context


def test_xlsx_sheet_cell_and_formula_reach_the_model_context() -> None:
    attachment = _attachment("book.xlsx", XLSX_MIME, _xlsx_bytes())
    context = build_document_context(attachment)

    assert "[Revenue!B2] 10" in context
    assert "[Revenue!B4] =SUM(B2:B3) => (no cached value)" in context


def test_text_document_context_keeps_the_existing_contract() -> None:
    parsed = parse_attachments(
        [{"type": "document", "name": "notes.txt", "media_type": "text/plain", "text": "hello"}]
    )
    context = build_document_context(parsed[0])
    body = context.split("문서 내용:\n", 1)[1]

    assert body == "hello"
    assert "첨부 문서 데이터 규칙" in context


@pytest.mark.asyncio
async def test_health_reports_binary_attachment_readiness() -> None:
    from app.app_factory import create_app
    from app.config import Settings

    app = create_app(Settings(runtime_mode="mock", web_provider="mock"))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json()["binary_document_attachment_ready"] is True


def test_browser_capability_follows_the_runtime_readiness_signal() -> None:
    capabilities = (STATIC / "attachment-capabilities.js").read_text(encoding="utf-8")
    binary = (STATIC / "document-binary.js").read_text(encoding="utf-8")
    locale = (STATIC / "locale.js").read_text(encoding="utf-8")
    app_js = (STATIC / "app.js").read_text(encoding="utf-8")

    assert "setBinarySupport(value)" in capabilities
    assert "get binarySupported()" in capabilities
    assert "attachmentCapabilities.binarySupported !== false" in binary
    assert 'fetch("/health"' in locale
    assert 'data.binary_document_attachment_ready' in locale
    assert "padiem:attachmentcapabilitychange" in locale
    assert "padiem:attachmentcapabilitychange" in app_js
