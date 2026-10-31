"""#2824: an encrypted or link-bearing document must not be reported as corrupt.

The rejection the owner reads has to name the real reason. A password the owner
set themselves is not a damaged file, and a package containing a link entry is
not a package that failed to open.
"""

from __future__ import annotations

import base64
import stat
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import pytest

from app.attachments import AttachmentValidationError, parse_attachments
from app.ooxml_stdlib import OOXMLExtractionError, validate_ooxml_archive

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def _docx_xml(text: str = "SAFE") -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>"
    ).encode()


def _plain_docx() -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", _docx_xml())
    return output.getvalue()


def _docx_with_link(name: str = "word/link.xml") -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        part = ZipInfo("word/document.xml")
        part.filename = "word/document.xml"
        part.compress_type = ZIP_DEFLATED
        archive.writestr(part, _docx_xml())
        link = ZipInfo(name)
        link.filename = name
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(link, b"../../Windows/win.ini")
    return output.getvalue()


def _docx_local_header_encrypted() -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", _docx_xml())
    data = bytearray(output.getvalue())
    index = data.find(b"PK\x03\x04")
    data[index + 6] |= 0x01
    return bytes(data)


def _ole_encrypted_package() -> bytes:
    """OLE signature plus a directory-shaped UTF-16LE ``EncryptedPackage`` name.

    Core's own suite builds and walks the full compound file; here the copy is
    what is under test, so the fixture only has to reach Core's classifier.
    """

    return (
        OLE_MAGIC
        + b"\x00" * 504
        + "EncryptedPackage".encode("utf-16-le")
        + b"\x00\x00"
    )


def _upload(name: str, media_type: str, payload: bytes):
    return parse_attachments([
        {
            "type": "document",
            "name": name,
            "media_type": media_type,
            "base64": base64.b64encode(payload).decode("ascii"),
        }
    ])


@pytest.mark.parametrize(
    ("name", "payload"),
    [
        ("secret.docx", _ole_encrypted_package()),
        ("locked.docx", _docx_local_header_encrypted()),
    ],
)
def test_an_encrypted_docx_is_named_encrypted_not_corrupt(name: str, payload: bytes) -> None:
    with pytest.raises(AttachmentValidationError) as refused:
        _upload(name, DOCX_MIME, payload)
    assert str(refused.value) == "암호화된 DOCX는 현재 첨부할 수 없습니다."
    assert "안전하게 읽지 못했습니다" not in str(refused.value)


def test_a_link_entry_is_named_as_an_unsafe_member_not_a_failed_read() -> None:
    with pytest.raises(AttachmentValidationError) as refused:
        _upload("report.docx", DOCX_MIME, _docx_with_link())
    assert str(refused.value) == "문서 압축 안에 안전하지 않은 경로 항목이 있어 열지 않았습니다."


def test_the_ordinary_docx_still_uploads_after_the_copy_change() -> None:
    attachment = _upload("report.docx", DOCX_MIME, _plain_docx())[0]
    assert attachment.name == "report.docx"
    assert "SAFE" in attachment.text


def test_the_stdlib_projection_carries_the_same_two_reasons() -> None:
    with pytest.raises(OOXMLExtractionError) as link:
        validate_ooxml_archive(_docx_with_link())
    assert str(link.value) == "link entries are not permitted in OOXML archives"

    with pytest.raises(OOXMLExtractionError) as locked:
        validate_ooxml_archive(_docx_local_header_encrypted())
    assert str(locked.value) == "encrypted OOXML entries are not supported"
