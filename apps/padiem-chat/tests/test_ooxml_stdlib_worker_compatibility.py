from __future__ import annotations

from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from app.ooxml_stdlib_probe import (
    MAX_ENTRIES,
    MAX_ENTRY_UNCOMPRESSED_BYTES,
    MAX_TOTAL_UNCOMPRESSED_BYTES,
    OOXMLCompatibilityError,
    extract_docx_text_stdlib,
    extract_pptx_text_stdlib,
)


DOCX_TEXT = "Padiem DOCX stdlib worker compatibility"
PPTX_TEXT_1 = "Padiem PPTX slide one"
PPTX_TEXT_2 = "Padiem PPTX slide two"


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
        '<w:body><w:p><w:r><w:t>'
        + text
        + '</w:t></w:r></w:p></w:body></w:document>'
    ).encode()


def _pptx_slide_xml(text: str) -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        '<p:cSld><p:spTree><p:sp><p:txBody><a:p><a:r><a:t>'
        + text
        + '</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld></p:sld>'
    ).encode()


def test_docx_stdlib_extracts_known_text() -> None:
    payload = _zip_bytes({
        "[Content_Types].xml": b"<Types/>",
        "word/document.xml": _docx_xml(DOCX_TEXT),
    })
    assert extract_docx_text_stdlib(payload) == DOCX_TEXT


def test_pptx_stdlib_extracts_text_in_numeric_slide_order() -> None:
    payload = _zip_bytes({
        "[Content_Types].xml": b"<Types/>",
        "ppt/slides/slide2.xml": _pptx_slide_xml(PPTX_TEXT_2),
        "ppt/slides/slide1.xml": _pptx_slide_xml(PPTX_TEXT_1),
    })
    assert extract_pptx_text_stdlib(payload) == f"{PPTX_TEXT_1}\n{PPTX_TEXT_2}"


@pytest.mark.parametrize("extractor", [extract_docx_text_stdlib, extract_pptx_text_stdlib])
def test_malformed_zip_fails_closed(extractor) -> None:
    with pytest.raises(OOXMLCompatibilityError, match="malformed OOXML ZIP archive"):
        extractor(b"not-a-zip")


def test_missing_docx_main_part_fails_closed() -> None:
    with pytest.raises(OOXMLCompatibilityError, match="missing OOXML part"):
        extract_docx_text_stdlib(_zip_bytes({"[Content_Types].xml": b"<Types/>"}))


def test_missing_pptx_slides_fail_closed() -> None:
    with pytest.raises(OOXMLCompatibilityError, match="missing PPTX slide XML parts"):
        extract_pptx_text_stdlib(_zip_bytes({"[Content_Types].xml": b"<Types/>"}))


def test_invalid_xml_fails_closed() -> None:
    payload = _zip_bytes({"word/document.xml": b"<w:document"})
    with pytest.raises(OOXMLCompatibilityError, match="invalid OOXML XML part"):
        extract_docx_text_stdlib(payload)


def test_doctype_is_rejected() -> None:
    payload = _zip_bytes({
        "word/document.xml": b'<!DOCTYPE x [<!ENTITY e "x">]><x>&e;</x>',
    })
    with pytest.raises(OOXMLCompatibilityError, match="DTDs are not supported"):
        extract_docx_text_stdlib(payload)


@pytest.mark.parametrize("unsafe_name", ["../evil.xml", "/absolute.xml", "C:/drive.xml", "a\\b.xml"])
def test_unsafe_archive_member_paths_are_rejected(unsafe_name: str) -> None:
    payload = _zip_bytes({unsafe_name: b"x", "word/document.xml": _docx_xml(DOCX_TEXT)})
    with pytest.raises(OOXMLCompatibilityError, match="unsafe OOXML archive member path"):
        extract_docx_text_stdlib(payload)


def test_entry_count_limit_rejects_archive() -> None:
    entries = {f"safe/{i}.xml": b"x" for i in range(MAX_ENTRIES + 1)}
    payload = _zip_bytes(entries)
    with pytest.raises(OOXMLCompatibilityError, match="too many entries"):
        extract_docx_text_stdlib(payload)


def test_individual_uncompressed_entry_limit_rejects_compressed_bomb() -> None:
    payload = _zip_bytes({
        "oversized.bin": b"x" * (MAX_ENTRY_UNCOMPRESSED_BYTES + 1),
        "word/document.xml": _docx_xml(DOCX_TEXT),
    })
    with pytest.raises(OOXMLCompatibilityError, match="entry exceeds size limit"):
        extract_docx_text_stdlib(payload)


def test_total_uncompressed_limit_rejects_multi_entry_bomb() -> None:
    chunk = b"x" * MAX_ENTRY_UNCOMPRESSED_BYTES
    count = (MAX_TOTAL_UNCOMPRESSED_BYTES // MAX_ENTRY_UNCOMPRESSED_BYTES) + 1
    entries = {f"safe/{i}.bin": chunk for i in range(count)}
    entries["word/document.xml"] = _docx_xml(DOCX_TEXT)
    payload = _zip_bytes(entries)
    with pytest.raises(OOXMLCompatibilityError, match="total uncompressed limit"):
        extract_docx_text_stdlib(payload)
