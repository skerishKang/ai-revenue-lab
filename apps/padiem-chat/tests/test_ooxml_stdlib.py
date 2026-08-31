from __future__ import annotations

from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from app.ooxml_stdlib import (
    MAX_ARCHIVE_BYTES,
    MAX_ENTRIES,
    MAX_ENTRY_UNCOMPRESSED_BYTES,
    MAX_TOTAL_UNCOMPRESSED_BYTES,
    OOXMLExtractionError,
    extract_docx_text,
    extract_pptx_text,
)


DOCX_TEXT = "Padiem DOCX product parser"
PPTX_TEXT_1 = "Padiem PPTX slide one"
PPTX_TEXT_2 = "Padiem PPTX slide two"


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


def test_docx_and_pptx_extract_known_text() -> None:
    assert extract_docx_text(_zip_bytes({"word/document.xml": _docx_xml(DOCX_TEXT)})) == DOCX_TEXT
    pptx = _zip_bytes(
        {
            "ppt/slides/slide2.xml": _pptx_xml(PPTX_TEXT_2),
            "ppt/slides/slide1.xml": _pptx_xml(PPTX_TEXT_1),
        }
    )
    assert extract_pptx_text(pptx) == f"{PPTX_TEXT_1}\n{PPTX_TEXT_2}"


@pytest.mark.parametrize("extractor", [extract_docx_text, extract_pptx_text])
def test_malformed_zip_fails_closed(extractor) -> None:
    with pytest.raises(OOXMLExtractionError, match="malformed OOXML ZIP archive"):
        extractor(b"not-a-zip")


def test_archive_byte_limit_fails_closed_before_zip_parsing() -> None:
    with pytest.raises(OOXMLExtractionError, match="archive size out of bounds"):
        extract_docx_text(b"x" * (MAX_ARCHIVE_BYTES + 1))


def test_missing_required_parts_fail_closed() -> None:
    with pytest.raises(OOXMLExtractionError, match="missing OOXML part"):
        extract_docx_text(_zip_bytes({"safe.xml": b"<x/>"}))
    with pytest.raises(OOXMLExtractionError, match="missing PPTX slide XML parts"):
        extract_pptx_text(_zip_bytes({"safe.xml": b"<x/>"}))


def test_invalid_xml_and_doctype_fail_closed() -> None:
    with pytest.raises(OOXMLExtractionError, match="invalid OOXML XML part"):
        extract_docx_text(_zip_bytes({"word/document.xml": b"<w:document"}))
    with pytest.raises(OOXMLExtractionError, match="DTDs are not supported"):
        extract_docx_text(_zip_bytes({"word/document.xml": b'<!DOCTYPE x [<!ENTITY e "x">]><x>&e;</x>'}))


def test_encrypted_entry_is_rejected_before_read() -> None:
    payload = _mark_first_entry_encrypted(_zip_bytes({"word/document.xml": _docx_xml(DOCX_TEXT)}))
    with pytest.raises(OOXMLExtractionError, match="encrypted OOXML entries"):
        extract_docx_text(payload)


@pytest.mark.parametrize("unsafe_name", ["../evil.xml", "/absolute.xml", "C:/drive.xml", "a\\b.xml"])
def test_unsafe_archive_member_paths_are_rejected(unsafe_name: str) -> None:
    payload = _zip_bytes({unsafe_name: b"x", "word/document.xml": _docx_xml(DOCX_TEXT)})
    with pytest.raises(OOXMLExtractionError, match="unsafe OOXML archive member path"):
        extract_docx_text(payload)


def test_entry_count_and_zip_bomb_bounds_fail_closed() -> None:
    entries = {f"safe/{i}.xml": b"x" for i in range(MAX_ENTRIES + 1)}
    with pytest.raises(OOXMLExtractionError, match="too many entries"):
        extract_docx_text(_zip_bytes(entries))

    payload = _zip_bytes(
        {
            "oversized.bin": b"x" * (MAX_ENTRY_UNCOMPRESSED_BYTES + 1),
            "word/document.xml": _docx_xml(DOCX_TEXT),
        }
    )
    with pytest.raises(OOXMLExtractionError, match="entry exceeds size limit"):
        extract_docx_text(payload)

    chunk = b"x" * MAX_ENTRY_UNCOMPRESSED_BYTES
    count = (MAX_TOTAL_UNCOMPRESSED_BYTES // MAX_ENTRY_UNCOMPRESSED_BYTES) + 1
    entries = {f"safe/{i}.bin": chunk for i in range(count)}
    entries["word/document.xml"] = _docx_xml(DOCX_TEXT)
    with pytest.raises(OOXMLExtractionError, match="total uncompressed limit"):
        extract_docx_text(_zip_bytes(entries))
