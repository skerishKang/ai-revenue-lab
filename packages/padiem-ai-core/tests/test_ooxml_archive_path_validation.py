"""File-based OOXML judgement: same rules as the byte gate, no whole-file load.

#6579 step 2 needs to judge a 1 GiB package that is already a file on disk. The
rules (member path, link entry, encryption, DTD, inflation ratio) are the shared
ones; only the I/O differs, so these tests pin that the two entry points agree.
"""
from __future__ import annotations

import io
import zipfile

import pytest

from padiem_ai_core.document_normalization import (
    DocumentNormalizationError,
    validate_ooxml_archive,
)
from padiem_ai_core.ooxml_archive_path import validate_ooxml_archive_path


def _package(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)
    return buffer.getvalue()


GOOD = {
    "[Content_Types].xml": b'<?xml version="1.0"?><Types/>',
    "xl/workbook.xml": b'<?xml version="1.0"?><workbook/>',
    "xl/worksheets/sheet1.xml": b'<?xml version="1.0"?><worksheet/>',
}


def _write(tmp_path, payload: bytes):
    path = tmp_path / "book.xlsx"
    path.write_bytes(payload)
    return path


def test_a_normal_package_passes_both_entry_points(tmp_path):
    payload = _package(GOOD)
    validate_ooxml_archive(payload)
    validate_ooxml_archive_path(_write(tmp_path, payload))


def test_an_unsafe_member_path_is_refused_from_the_file_too(tmp_path):
    payload = _package({**GOOD, "../escape.xml": b"<x/>"})
    with pytest.raises(DocumentNormalizationError):
        validate_ooxml_archive(payload)
    with pytest.raises(DocumentNormalizationError):
        validate_ooxml_archive_path(_write(tmp_path, payload))


def test_a_dtd_is_refused_from_the_file_too(tmp_path):
    payload = _package({**GOOD, "xl/shared.xml": b'<!DOCTYPE x><x/>'})
    with pytest.raises(DocumentNormalizationError):
        validate_ooxml_archive(payload)
    with pytest.raises(DocumentNormalizationError):
        validate_ooxml_archive_path(_write(tmp_path, payload))


def test_an_ole_wrapper_is_refused_without_reading_it_whole(tmp_path):
    from padiem_ai_core.document_normalization import (
        _ENCRYPTED_PACKAGE_MARKER,
        _OLE_COMPOUND_MAGIC,
    )

    payload = _OLE_COMPOUND_MAGIC + b"\x00" * 4096 + _ENCRYPTED_PACKAGE_MARKER + b"\x00" * 64
    with pytest.raises(DocumentNormalizationError):
        validate_ooxml_archive_path(_write(tmp_path, payload))


def test_a_missing_empty_or_directory_path_is_a_bounded_refusal(tmp_path):
    with pytest.raises(DocumentNormalizationError):
        validate_ooxml_archive_path(tmp_path / "absent.xlsx")
    with pytest.raises(DocumentNormalizationError):
        validate_ooxml_archive_path(_write(tmp_path, b""))
    with pytest.raises(DocumentNormalizationError):
        validate_ooxml_archive_path(tmp_path)


def test_a_zip_that_is_not_a_zip_is_refused_from_the_file(tmp_path):
    with pytest.raises(Exception):
        validate_ooxml_archive_path(_write(tmp_path, b"not a zip at all" * 100))
