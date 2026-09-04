from __future__ import annotations

from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from openpyxl import Workbook
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from padiem_ai_core.document_normalization import (
    MAX_BINARY_DOCUMENT_BYTES,
    MAX_DOCUMENT_CHARS,
    MAX_OOXML_ENTRIES,
    MAX_OOXML_ENTRY_UNCOMPRESSED_BYTES,
    MAX_OOXML_TOTAL_UNCOMPRESSED_BYTES,
    MAX_PDF_PAGES,
    BINARY_DOCUMENT_MEDIA,
    DocumentNormalizationError,
    extract_binary_document,
    extract_docx_text,
    extract_pptx_text,
    normalize_text_document,
    validate_document_identity,
    validate_ooxml_archive,
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


def _mark_first_entry_encrypted(payload: bytes) -> bytes:
    data = bytearray(payload)
    for signature, flag_offset in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        index = data.find(signature)
        assert index >= 0
        start = index + flag_offset
        flags = int.from_bytes(data[start : start + 2], "little") | 0x1
        data[start : start + 2] = flags.to_bytes(2, "little")
    return bytes(data)


def _docx_xml(*paragraphs: str) -> bytes:
    body = "".join(f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>" for text in paragraphs)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}</w:body></w:document>"
    ).encode()


def _pptx_xml(*parts: str) -> bytes:
    body = "".join(f"<a:r><a:t>{text}</a:t></a:r>" for text in parts)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        f"<p:cSld><p:spTree><p:sp><p:txBody><a:p>{body}</a:p></p:txBody></p:sp></p:spTree></p:cSld></p:sld>"
    ).encode()


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


def _blank_pdf(*, encrypted: bool = False, pages: int = 1) -> bytes:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=320, height=180)
    if encrypted:
        writer.encrypt("secret")
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


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


def _replace_zip_entry(payload: bytes, target: str, replacement: bytes) -> bytes:
    with ZipFile(BytesIO(payload)) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    entries[target] = replacement
    return _zip_bytes(entries)


def test_text_normalization_is_bounded_and_public_projection_is_safe() -> None:
    document = normalize_text_document(
        name=" notes.txt ",
        media_type="text/plain",
        text="\ufefffirst\r\nsecond\rthird",
    )
    assert document.name == "notes.txt"
    assert document.text == "first\nsecond\nthird"
    assert document.source_kind == "text"
    assert document.to_public_dict() == {
        "type": "document",
        "name": "notes.txt",
        "media_type": "text/plain",
        "byte_size": len(document.text.encode("utf-8")),
        "text_chars": len(document.text),
    }
    assert document.text not in repr(document)


@pytest.mark.parametrize(
    ("name", "media_type", "code"),
    [
        ("notes.pdf", "text/plain", "media_extension_mismatch"),
        ("notes.txt", "application/pdf", "unsupported_text_media_type"),
        ("legacy.hwp", "application/x-hwp", "unsupported_text_media_type"),
        ("legacy.hwpx", "application/zip", "unsupported_text_media_type"),
    ],
)
def test_text_identity_fails_closed(name: str, media_type: str, code: str) -> None:
    with pytest.raises(DocumentNormalizationError) as exc:
        normalize_text_document(name=name, media_type=media_type, text="safe")
    assert exc.value.code == code


def test_text_rejects_nul_controls_and_character_overflow_without_echo() -> None:
    secret = "PRIVATE-DOCUMENT-SECRET"
    with pytest.raises(DocumentNormalizationError) as nul:
        normalize_text_document(name="x.txt", media_type="text/plain", text=secret + "\x00")
    assert nul.value.code == "binary_text_rejected"
    assert secret not in str(nul.value)

    with pytest.raises(DocumentNormalizationError) as controls:
        normalize_text_document(name="x.txt", media_type="text/plain", text="safe\x01\x02\x03\x04")
    assert controls.value.code == "excessive_control_characters"

    with pytest.raises(DocumentNormalizationError) as large:
        normalize_text_document(name="x.txt", media_type="text/plain", text="x" * (MAX_DOCUMENT_CHARS + 1))
    assert large.value.code == "text_too_long"


def test_binary_identity_is_product_neutral_and_has_no_path_or_url_authority() -> None:
    name, media = validate_document_identity(name="sample.pdf", media_type=PDF_MIME, source_kind="binary")
    assert (name, media) == ("sample.pdf", PDF_MIME)
    assert set(BINARY_DOCUMENT_MEDIA) == {PDF_MIME, DOCX_MIME, PPTX_MIME, XLSX_MIME}
    with pytest.raises(DocumentNormalizationError) as mismatch:
        validate_document_identity(name="sample.docx", media_type=PDF_MIME, source_kind="binary")
    assert mismatch.value.code == "media_extension_mismatch"

    # The Core contract accepts only caller-provided values/bytes. There is no
    # filesystem path or remote URL parameter that could silently acquire I/O authority.
    import inspect

    assert tuple(inspect.signature(extract_binary_document).parameters) == ("name", "media_type", "payload")


def test_pdf_extracts_text_and_never_retains_raw_binary() -> None:
    payload = _minimal_text_pdf("Padiem Core PDF")
    document = extract_binary_document(name="sample.pdf", media_type=PDF_MIME, payload=payload)
    assert "Padiem Core PDF" in document.text
    assert document.byte_size == len(payload)
    assert document.source_kind == "binary"
    assert repr(payload[:24]) not in repr(document)
    assert "Padiem Core PDF" not in repr(document)
    assert "text" not in document.to_public_dict()


def test_pdf_bad_magic_encryption_page_limit_and_scanned_only_fail_closed() -> None:
    with pytest.raises(DocumentNormalizationError) as magic:
        extract_binary_document(name="x.pdf", media_type=PDF_MIME, payload=b"not a pdf")
    assert magic.value.code == "pdf_magic_mismatch"

    with pytest.raises(DocumentNormalizationError) as encrypted:
        extract_binary_document(name="x.pdf", media_type=PDF_MIME, payload=_blank_pdf(encrypted=True))
    assert encrypted.value.code == "pdf_encrypted"

    with pytest.raises(DocumentNormalizationError) as pages:
        extract_binary_document(name="x.pdf", media_type=PDF_MIME, payload=_blank_pdf(pages=MAX_PDF_PAGES + 1))
    assert pages.value.code == "pdf_page_limit"

    with pytest.raises(DocumentNormalizationError) as scanned:
        extract_binary_document(name="x.pdf", media_type=PDF_MIME, payload=_blank_pdf())
    assert scanned.value.code == "pdf_empty_text"


def test_docx_preserves_paragraphs_and_pptx_preserves_slide_order() -> None:
    docx = _zip_bytes({"word/document.xml": _docx_xml("paragraph one", "paragraph two")})
    document = extract_binary_document(name="sample.docx", media_type=DOCX_MIME, payload=docx)
    assert document.text == "paragraph one\nparagraph two"

    pptx = _zip_bytes(
        {
            "ppt/slides/slide2.xml": _pptx_xml("slide two", "second line"),
            "ppt/slides/slide1.xml": _pptx_xml("slide one"),
        }
    )
    presentation = extract_binary_document(name="slides.pptx", media_type=PPTX_MIME, payload=pptx)
    assert presentation.text == "slide one\nslide two\nsecond line"


def test_ooxml_malformed_missing_dtd_encryption_and_paths_fail_closed() -> None:
    with pytest.raises(DocumentNormalizationError) as malformed:
        extract_docx_text(b"not-a-zip")
    assert malformed.value.code == "ooxml_malformed"

    with pytest.raises(DocumentNormalizationError) as missing:
        extract_docx_text(_zip_bytes({"safe.xml": b"<x/>"}))
    assert missing.value.code == "docx_missing_part"

    dtd = _zip_bytes({"word/document.xml": b'<!DOCTYPE x [<!ENTITY e "private">]><x>&e;</x>'})
    with pytest.raises(DocumentNormalizationError) as rejected:
        extract_docx_text(dtd)
    assert rejected.value.code == "ooxml_dtd_rejected"
    assert "private" not in str(rejected.value)

    encrypted = _mark_first_entry_encrypted(_zip_bytes({"word/document.xml": _docx_xml("safe")}))
    with pytest.raises(DocumentNormalizationError) as locked:
        extract_docx_text(encrypted)
    assert locked.value.code == "ooxml_encrypted"

    for unsafe in ("../evil.xml", "/absolute.xml", "C:/drive.xml", "a\\b.xml", "a//b.xml"):
        payload = _zip_bytes({unsafe: b"x", "word/document.xml": _docx_xml("safe")})
        with pytest.raises(DocumentNormalizationError) as path_error:
            extract_docx_text(payload)
        assert path_error.value.code == "ooxml_unsafe_path"


def test_ooxml_entry_count_and_uncompressed_bounds_fail_closed() -> None:
    entries = {f"safe/{index}.xml": b"x" for index in range(MAX_OOXML_ENTRIES + 1)}
    with pytest.raises(DocumentNormalizationError) as count:
        validate_ooxml_archive(_zip_bytes(entries))
    assert count.value.code == "ooxml_entry_count"

    oversized = _zip_bytes({"oversized.bin": b"x" * (MAX_OOXML_ENTRY_UNCOMPRESSED_BYTES + 1)})
    with pytest.raises(DocumentNormalizationError) as entry:
        validate_ooxml_archive(oversized)
    assert entry.value.code == "ooxml_entry_size"

    chunk = b"x" * MAX_OOXML_ENTRY_UNCOMPRESSED_BYTES
    total_entries = {
        f"safe/{index}.bin": chunk
        for index in range((MAX_OOXML_TOTAL_UNCOMPRESSED_BYTES // MAX_OOXML_ENTRY_UNCOMPRESSED_BYTES) + 1)
    }
    with pytest.raises(DocumentNormalizationError) as total:
        validate_ooxml_archive(_zip_bytes(total_entries))
    assert total.value.code == "ooxml_total_size"


def test_xlsx_extracts_values_and_archive_dtd_is_rejected_before_openpyxl() -> None:
    payload = _xlsx_bytes()
    document = extract_binary_document(name="book.xlsx", media_type=XLSX_MIME, payload=payload)
    assert "[Summary!A1] Padiem XLSX" in document.text
    assert "[Summary!B2] 42" in document.text
    assert "[Detail!C3] bounded" in document.text

    malicious = _replace_zip_entry(
        payload,
        "xl/workbook.xml",
        b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e "private">]><workbook/>',
    )
    with pytest.raises(DocumentNormalizationError) as dtd:
        extract_binary_document(name="book.xlsx", media_type=XLSX_MIME, payload=malicious)
    assert dtd.value.code == "ooxml_dtd_rejected"
    assert "private" not in str(dtd.value)


def test_binary_size_bound_fails_without_echoing_payload() -> None:
    payload = b"PRIVATE" + b"x" * MAX_BINARY_DOCUMENT_BYTES
    with pytest.raises(DocumentNormalizationError) as exc:
        extract_binary_document(name="x.pdf", media_type=PDF_MIME, payload=payload)
    assert exc.value.code == "binary_too_large"
    assert "PRIVATE" not in str(exc.value)
