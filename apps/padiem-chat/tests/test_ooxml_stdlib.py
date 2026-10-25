from __future__ import annotations

from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from padiem_ai_core.document_normalization import (
    DocumentNormalizationError,
    validate_ooxml_member_name,
)

from app.ooxml_stdlib import (
    MAX_ARCHIVE_BYTES,
    MAX_ENTRIES,
    MAX_ENTRY_UNCOMPRESSED_BYTES,
    MAX_TOTAL_UNCOMPRESSED_BYTES,
    OOXMLExtractionError,
    extract_docx_text,
    extract_pptx_text,
    validate_ooxml_archive,
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


def test_archive_over_the_old_byte_total_is_not_refused_for_its_size() -> None:
    # #4379: an OOXML archive carries no PADIEM byte total. The archive is
    # parsed and the malformed-archive rule refuses it. The per-entry and the
    # total uncompressed bounds stay as the decompression-bomb protection.
    with pytest.raises(OOXMLExtractionError, match="malformed OOXML ZIP archive"):
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


@pytest.mark.parametrize("unsafe_name", ["../evil.xml", "/absolute.xml", "C:/drive.xml"])
def test_unsafe_archive_member_paths_are_rejected(unsafe_name: str) -> None:
    payload = _zip_bytes({unsafe_name: b"x", "word/document.xml": _docx_xml(DOCX_TEXT)})
    with pytest.raises(OOXMLExtractionError, match="unsafe OOXML archive member path"):
        extract_docx_text(payload)


def test_backslash_member_name_is_rejected_by_the_shared_predicate() -> None:
    """A backslash member name must fail the single path-safety predicate.

    This is asserted on the predicate rather than on an archive because CPython
    normalises ``os.sep`` to "/" inside ``ZipInfo.__init__`` on both the write
    and the read path, so on Windows the gate can never observe a member named
    "a\\b.xml" -- the archive reader has already turned it into the safe
    "a/b.xml". The predicate is the layer that actually decides, and the
    product applies it to every member it walks or writes.
    """

    with pytest.raises(DocumentNormalizationError, match="unsafe member path"):
        validate_ooxml_member_name("a" + chr(92) + "b.xml")
    # Sanity: the forward-slash spelling of the same tree stays allowed.
    assert validate_ooxml_member_name("a/b.xml") == "a/b.xml"


def test_capacity_is_not_a_refusal_and_a_bomb_still_is() -> None:
    """#5734: member count and member bytes stopped being reasons to refuse.

    Three shapes that used to fail here are ordinary documents: more members than
    the old 256 count, one member over the old 1MiB bound, and a package whose
    parts summed past the old 8MiB total. The shape that must still be refused is
    a decompression bomb — content that expands enormously against the bytes it
    was carried in — and the path, encryption and DTD checks are untouched.
    """

    many = {f"safe/{i}.xml": b"<a/>" for i in range(MAX_ENTRIES * 4)}
    many["word/document.xml"] = _docx_xml(DOCX_TEXT)
    assert DOCX_TEXT in extract_docx_text(_zip_bytes(many))

    big = {"word/document.xml": _docx_xml(DOCX_TEXT),
           "big.bin": b"abcdefgh" * (MAX_ENTRY_UNCOMPRESSED_BYTES * 4)}
    assert DOCX_TEXT in extract_docx_text(_zip_bytes(big))

    chunk = b"abcdefgh" * (MAX_ENTRY_UNCOMPRESSED_BYTES // 8)
    wide = {f"safe/{i}.bin": chunk for i in range(MAX_ENTRIES)}
    wide["word/document.xml"] = _docx_xml(DOCX_TEXT)
    assert DOCX_TEXT in extract_docx_text(_zip_bytes(wide))

    # This reader answers every upstream structural refusal with one safe
    # message of its own; what matters is that the bomb is refused at all.
    bomb = {"word/document.xml": _docx_xml(DOCX_TEXT),
            "bomb.bin": bytes(64 * 1024 * 1024)}
    with pytest.raises(OOXMLExtractionError, match="extraction failed safely"):
        extract_docx_text(_zip_bytes(bomb))


def test_xlsx_archive_level_dtd_is_rejected_before_openpyxl():
    malicious_xml = b'<?xml version="1.0" encoding="UTF-8"?><!DOCTYPE x [<!ENTITY e "x">]><workbook/>'
    payload = _zip_bytes(
        {
            "xl/workbook.xml": malicious_xml,
            "[Content_Types].xml": b'<?xml version="1.0" encoding="UTF-8"?><Types/>',
            "_rels/.rels": b'<?xml version="1.0" encoding="UTF-8"?><Relationships/>',
        }
    )
    with pytest.raises(OOXMLExtractionError, match="DTDs are not supported"):
        validate_ooxml_archive(payload)

    # Case-insensitive variant and different XML part
    malicious_lower = b'<?xml?><!doctype x SYSTEM "http://example.com/x.dtd"><x/>'
    payload2 = _zip_bytes(
        {
            "xl/worksheets/sheet1.xml": malicious_lower,
            "[Content_Types].xml": b'<?xml?><Types/>',
        }
    )
    with pytest.raises(OOXMLExtractionError, match="DTDs are not supported"):
        validate_ooxml_archive(payload2)

    # Ensure DOCX/PPTX per-part guard still works but archive-level also catches DTD in secondary part
    payload3 = _zip_bytes(
        {
            "word/document.xml": _docx_xml(DOCX_TEXT),
            "word/comments.xml": b'<!DOCTYPE foo>',
        }
    )
    with pytest.raises(OOXMLExtractionError, match="DTDs are not supported"):
        validate_ooxml_archive(payload3)
