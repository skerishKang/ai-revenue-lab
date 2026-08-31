from __future__ import annotations

import base64
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from openpyxl import Workbook
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from app.attachments import AttachmentValidationError, parse_attachments
from app.binary_documents import MAX_BINARY_DOCUMENT_BYTES
from app.documents import DocumentAttachment


PDF_MIME = "application/pdf"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _b64(payload: bytes) -> str:
    return base64.b64encode(payload).decode("ascii")


def _binary_item(name: str, media_type: str, payload: bytes) -> dict[str, str]:
    return {"type": "document", "name": name, "media_type": media_type, "base64": _b64(payload)}


def _minimal_text_pdf(text: str) -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(width=320, height=180)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    font_ref = writer._add_object(font)
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref})}
    )
    content = DecodedStreamObject()
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    content.set_data(f"BT /F1 14 Tf 36 90 Td ({escaped}) Tj ET".encode("ascii"))
    page[NameObject("/Contents")] = writer._add_object(content)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def _blank_pdf(*, encrypted: bool = False) -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=320, height=180)
    if encrypted:
        writer.encrypt("secret")
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def _zip_bytes(entries: dict[str, bytes]) -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for name, payload in entries.items():
            archive.writestr(name, payload)
    return output.getvalue()


def _docx_xml(text: str) -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:body><w:p><w:r><w:t>' + text + '</w:t></w:r></w:p></w:body></w:document>'
    ).encode()


def _pptx_xml(text: str) -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        '<p:cSld><p:spTree><p:sp><p:txBody><a:p><a:r><a:t>'
        + text
        + '</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld></p:sld>'
    ).encode()


def _xlsx_bytes() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Summary"
    sheet["A1"] = "Padiem XLSX"
    sheet["B2"] = 42
    detail = workbook.create_sheet("Detail")
    detail["C3"] = "bounded"
    output = BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()


def _only_attachment(item: dict[str, str]) -> DocumentAttachment:
    attachments = parse_attachments([item])
    assert len(attachments) == 1
    attachment = attachments[0]
    assert isinstance(attachment, DocumentAttachment)
    return attachment


def test_pdf_attachment_extracts_text_and_keeps_binary_private() -> None:
    payload = _minimal_text_pdf("Padiem PDF attachment")
    item = _binary_item("sample.pdf", PDF_MIME, payload)
    attachment = _only_attachment(item)

    assert "Padiem PDF attachment" in attachment.text
    assert attachment.byte_size == len(payload)
    assert attachment.public_dict() == {
        "type": "document",
        "name": "sample.pdf",
        "media_type": PDF_MIME,
        "byte_size": len(payload),
        "text_chars": len(attachment.text),
    }
    assert item["base64"] not in repr(attachment)
    assert item["base64"] not in str(attachment.public_dict())


def test_docx_and_pptx_extract_ordinary_text_in_order() -> None:
    docx = _zip_bytes({"word/document.xml": _docx_xml("Padiem DOCX")})
    pptx = _zip_bytes(
        {
            "ppt/slides/slide2.xml": _pptx_xml("slide two"),
            "ppt/slides/slide1.xml": _pptx_xml("slide one"),
        }
    )

    assert _only_attachment(_binary_item("sample.docx", DOCX_MIME, docx)).text == "Padiem DOCX"
    assert _only_attachment(_binary_item("slides.pptx", PPTX_MIME, pptx)).text == "slide one\nslide two"


def test_xlsx_extracts_bounded_values_with_sheet_and_cell_context() -> None:
    attachment = _only_attachment(_binary_item("book.xlsx", XLSX_MIME, _xlsx_bytes()))
    assert "[Summary!A1] Padiem XLSX" in attachment.text
    assert "[Summary!B2] 42" in attachment.text
    assert "[Detail!C3] bounded" in attachment.text


def test_existing_text_document_contract_is_preserved() -> None:
    attachments = parse_attachments(
        [{"type": "document", "name": "notes.txt", "media_type": "text/plain", "text": "hello"}]
    )
    assert len(attachments) == 1
    assert isinstance(attachments[0], DocumentAttachment)
    assert attachments[0].text == "hello"


def test_binary_and_text_fields_are_mutually_exclusive() -> None:
    item = _binary_item("sample.pdf", PDF_MIME, _minimal_text_pdf("safe"))
    item["text"] = "ambiguous"
    with pytest.raises(AttachmentValidationError, match="중 하나만"):
        parse_attachments([item])


@pytest.mark.parametrize(
    ("name", "media_type"),
    [
        ("sample.docx", PDF_MIME),
        ("sample.pdf", DOCX_MIME),
        ("sample.xlsx", PPTX_MIME),
    ],
)
def test_binary_media_type_and_extension_must_match(name: str, media_type: str) -> None:
    with pytest.raises(AttachmentValidationError, match="확장자와 파일 형식"):
        parse_attachments([_binary_item(name, media_type, b"not-used")])


def test_invalid_and_oversized_base64_fail_closed_without_echo() -> None:
    with pytest.raises(AttachmentValidationError, match="문서 데이터가 올바르지") as invalid:
        parse_attachments([{"type": "document", "name": "x.pdf", "media_type": PDF_MIME, "base64": "!!!PRIVATE!!!"}])
    assert "PRIVATE" not in str(invalid.value)

    too_large = b"x" * (MAX_BINARY_DOCUMENT_BYTES + 1)
    encoded = _b64(too_large)
    with pytest.raises(AttachmentValidationError, match="2 MiB 이하") as oversized:
        parse_attachments([{"type": "document", "name": "x.pdf", "media_type": PDF_MIME, "base64": encoded}])
    assert encoded[:100] not in str(oversized.value)


def test_encrypted_and_scanned_only_pdf_fail_with_safe_specific_messages() -> None:
    with pytest.raises(AttachmentValidationError, match="암호화된 PDF"):
        parse_attachments([_binary_item("locked.pdf", PDF_MIME, _blank_pdf(encrypted=True))])

    with pytest.raises(AttachmentValidationError, match="OCR은 아직 지원하지 않습니다"):
        parse_attachments([_binary_item("scan.pdf", PDF_MIME, _blank_pdf())])


def test_binary_document_still_obeys_single_attachment_limit() -> None:
    pdf = _binary_item("a.pdf", PDF_MIME, _minimal_text_pdf("a"))
    docx = _binary_item("b.docx", DOCX_MIME, _zip_bytes({"word/document.xml": _docx_xml("b")}))
    with pytest.raises(AttachmentValidationError, match="한 번에 하나"):
        parse_attachments([pdf, docx])


def _inject_dtd_into_xlsx(valid_xlsx: bytes, target: str, dtd_payload: bytes) -> bytes:
    # Read valid XLSX and re-create with malicious XML part containing DTD.
    # The DTD payload is the raw XML content for the target entry.
    input_zip = ZipFile(BytesIO(valid_xlsx))
    entries: dict[str, bytes] = {name: input_zip.read(name) for name in input_zip.namelist()}
    input_zip.close()
    entries[target] = dtd_payload
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return output.getvalue()


def test_xlsx_with_dtd_is_rejected_archive_level_without_echo() -> None:
    valid = _xlsx_bytes()
    # Inject DTD into xl/workbook.xml (common XLSX XML part)
    malicious_xml = b'<?xml version="1.0" encoding="UTF-8"?><!DOCTYPE x [<!ENTITY e "evil">]><workbook/>'
    malicious = _inject_dtd_into_xlsx(valid, "xl/workbook.xml", malicious_xml)
    item = _binary_item("evil.xlsx", XLSX_MIME, malicious)
    with pytest.raises(AttachmentValidationError, match="안전하게 읽지 못했습니다") as exc:
        parse_attachments([item])
    # Do not echo payload content or base64 in error
    assert "evil" not in str(exc.value).lower() or "evil.xlsx" in str(exc.value)  # allow filename, but not payload
    assert _b64(malicious)[:80] not in str(exc.value)
    assert malicious[:80].decode(errors="ignore") not in str(exc.value)

    # Case-insensitive variant in different sheet part
    lower_malicious = b'<?xml?><!doctype x SYSTEM "http://example.com/x.dtd"><x/>'
    malicious2 = _inject_dtd_into_xlsx(valid, "xl/worksheets/sheet1.xml", lower_malicious)
    item2 = _binary_item("evil2.xlsx", XLSX_MIME, malicious2)
    with pytest.raises(AttachmentValidationError, match="안전하게 읽지 못했습니다") as exc2:
        parse_attachments([item2])
    assert _b64(malicious2)[:80] not in str(exc2.value)
