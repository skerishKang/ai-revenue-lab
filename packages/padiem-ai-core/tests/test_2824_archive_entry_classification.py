"""#2824: the OOXML archive authority must classify link entries and encrypted
packages, not just oversized or malformed ones.

Every fixture is generated in memory. The OLE compound file is built to
[MS-CFS] layout and read back by the local walker at the bottom of this file, so
a fixture that only *looks* like an encrypted wrapper fails here instead of
quietly passing.
"""

from __future__ import annotations

import struct
import stat
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import pytest

from padiem_ai_core.document_normalization import (
    DocumentNormalizationError,
    extract_binary_document,
    validate_ooxml_archive,
)

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
SECTOR = 512
ENDOFCHAIN = -2
FREESECT = -1
_ENCRYPTED_FLAG = 0x1


def _zip(entries: dict[str, bytes]) -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for name, payload in entries.items():
            member = ZipInfo(name)
            member.filename = name
            member.compress_type = ZIP_DEFLATED
            archive.writestr(member, payload)
    return output.getvalue()


def _zip_with_link(name: str, target: str, *,
                   part: tuple[str, bytes | None] = ("word/document.xml", None)) -> bytes:
    """An ordinary package plus one member whose stored mode says symlink.

    The link is written with a raw name after construction, the way the
    existing suite does, so a Windows ``os.sep`` rewrite cannot neutralise the
    fixture.
    """

    part_name, part_payload = part
    if part_payload is None:
        part_payload = _docx_xml("SAFE")
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        member = ZipInfo(part_name)
        member.filename = part_name
        member.compress_type = ZIP_DEFLATED
        archive.writestr(member, part_payload)
        link = ZipInfo(name)
        link.filename = name
        link.compress_type = ZIP_DEFLATED
        # create_system 3 = Unix, so the high 16 bits of external_attr carry a
        # real mode. This is what a POSIX archiver writes for a symlinked part.
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(link, target.encode())
    return output.getvalue()


def _mark_local_header_encrypted(payload: bytes) -> bytes:
    """Set the encrypted flag on every local file header, leaving the central
    directory claiming the archive is plain.

    ``zipfile`` reports only the central copy, so the stdlib view of the fixture
    below is an unencrypted archive.
    """

    data = bytearray(payload)
    position = 0
    while True:
        index = data.find(b"PK\x03\x04", position)
        if index == -1:
            break
        data[index + 6] |= _ENCRYPTED_FLAG
        position = index + 4
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
        f"<p:cSld><p:spTree><a:p>{body}</a:p></p:spTree></p:cSld></p:sld>"
    ).encode()


def _docx_link_code(name: str) -> str:
    try:
        validate_ooxml_archive(_zip_with_link(name, "../../Windows/win.ini"))
    except DocumentNormalizationError as exc:
        return exc.code
    return "accepted"


# --------------------------------------------------------------------------- #
# A spec-shaped OLE compound file, small enough to build inline.
# --------------------------------------------------------------------------- #


def _dir_entry(name: str, *, obj_type: int, left: int, right: int, child: int,
                start: int, size: int) -> bytes:
    encoded = name.encode("utf-16-le") + b"\x00\x00"
    entry = bytearray(128)
    entry[0:64] = encoded + b"\x00" * (64 - len(encoded))
    struct.pack_into("<H", entry, 64, len(encoded))
    entry[66] = obj_type
    entry[67] = 1  # black
    struct.pack_into("<i", entry, 68, left)
    struct.pack_into("<i", entry, 72, right)
    struct.pack_into("<i", entry, 76, child)
    struct.pack_into("<i", entry, 116, start)
    struct.pack_into("<Q", entry, 120, size)
    return bytes(entry)


def _ole(streams: list[tuple[str, bytes]]) -> bytes:
    """Directory in sector 0, one FAT in sector 1, then one sector per stream."""

    count = len(streams)
    entries = [
        _dir_entry("Root Entry", obj_type=5, left=-1, right=-1,
                   child=(1 if count else ENDOFCHAIN), start=ENDOFCHAIN, size=0)
    ]
    for index, (name, payload) in enumerate(streams, start=1):
        entries.append(
            _dir_entry(name, obj_type=2, left=-1,
                       right=(index + 1 if index < count else -1),
                       child=ENDOFCHAIN, start=index + 1, size=len(payload))
        )
    directory = b"".join(entries)
    directory += b"\x00" * (SECTOR - len(directory))

    fat = bytearray(b"\xff" * SECTOR)

    def put(sector_index: int, value: int) -> None:
        struct.pack_into("<i", fat, sector_index * 4, value)

    put(0, ENDOFCHAIN)
    put(1, -3)  # FATSECT
    for index in range(count):
        put(2 + index, ENDOFCHAIN)
    for index in range(2 + count, SECTOR // 4):
        put(index, FREESECT)

    header = bytearray(SECTOR)
    header[0:8] = OLE_MAGIC
    struct.pack_into("<H", header, 24, 0x003E)
    struct.pack_into("<H", header, 26, 0x0003)
    struct.pack_into("<H", header, 28, 0xFFFE)
    struct.pack_into("<H", header, 30, 9)
    struct.pack_into("<H", header, 32, 6)
    struct.pack_into("<I", header, 44, 1)          # one FAT sector
    struct.pack_into("<i", header, 48, 0)          # directory starts at sector 0
    struct.pack_into("<I", header, 56, 4096)       # mini-stream cutoff
    struct.pack_into("<i", header, 60, ENDOFCHAIN)
    struct.pack_into("<i", header, 68, ENDOFCHAIN)
    struct.pack_into("<i", header, 76, 1)          # DIFAT[0] = the FAT sector
    for index in range(1, 109):
        struct.pack_into("<i", header, 76 + 4 * index, FREESECT)

    body = directory + bytes(fat[:SECTOR])
    for _, payload in streams:
        body += payload + b"\x00" * (SECTOR - len(payload))
    return bytes(header) + body


def _ole_stream_names(blob: bytes) -> list[str]:
    """Read the stream names back out of the fixture's directory sector."""

    first_directory = struct.unpack_from("<i", blob, 48)[0]
    sector_shift = struct.unpack_from("<H", blob, 30)[0]
    size = 1 << sector_shift
    directory = blob[SECTOR + first_directory * size:][:size]
    names: list[str] = []
    for offset in range(0, len(directory), 128):
        entry = directory[offset:offset + 128]
        if len(entry) < 128 or entry[66] not in (1, 2, 5):
            continue
        raw_len = struct.unpack_from("<H", entry, 64)[0]
        if raw_len == 0:
            continue
        names.append(entry[0:raw_len - 2].decode("utf-16-le"))
    return names


ENCRYPTED_DOCX = _ole([
    ("EncryptedPackage", b"\x0e\x00\x00\x00" + b"AESBLOB" * 20),
    ("Versions", b"\x01\x00\x00\x00"),
])
LEGACY_DOCX = _ole([("WordDocument", b"legacy word binary" * 8)])


# --------------------------------------------------------------------------- #
# Link entries
# --------------------------------------------------------------------------- #


def test_a_link_member_is_refused_by_the_code_the_intake_gate_already_uses():
    assert _docx_link_code("word/link.xml") == "ooxml_link_entry"


@pytest.mark.parametrize("name", ["link.xml", "word/link.xml", "xl/_rels/link.xml",
                                  "word/media/hmm", "x" * 200])
def test_a_link_member_is_refused_wherever_it_sits(name: str) -> None:
    assert _docx_link_code(name) == "ooxml_link_entry"


def test_a_link_member_is_refused_before_the_package_is_read_for_text() -> None:
    """The link is the reason, not a missing part or a failed parse."""

    payload = _zip_with_link("word/link.xml", "../../Windows/win.ini")
    with pytest.raises(DocumentNormalizationError) as refused:
        extract_binary_document(name="report.docx", media_type=DOCX_MIME, payload=payload)
    assert refused.value.code == "ooxml_link_entry"


def test_an_unsafe_named_link_is_still_refused_and_names_the_path_first() -> None:
    """One member can fail two guards; the answer stays a single bounded code."""

    payload = _zip_with_link("../../evil.xml", "../../Windows/win.ini")
    with pytest.raises(DocumentNormalizationError) as refused:
        validate_ooxml_archive(payload)
    assert refused.value.code == "ooxml_unsafe_path"


def test_a_regular_file_mode_is_not_mistaken_for_a_link() -> None:
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        member = ZipInfo("word/document.xml")
        member.compress_type = ZIP_DEFLATED
        archive.writestr(member, _docx_xml("SAFE"))
        regular = ZipInfo("word/media/image1.png")
        regular.create_system = 3
        regular.external_attr = (stat.S_IFREG | 0o644) << 16
        archive.writestr(regular, b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
    validate_ooxml_archive(output.getvalue())


def test_pptx_link_member_is_refused_before_any_slide_is_read() -> None:
    payload = _zip_with_link(
        "ppt/link.xml", "../secret",
        part=("ppt/slides/slide1.xml", _pptx_xml("hello")),
    )
    with pytest.raises(DocumentNormalizationError) as refused:
        validate_ooxml_archive(payload)
    assert refused.value.code == "ooxml_link_entry"


# --------------------------------------------------------------------------- #
# Encryption: two copies of one flag
# --------------------------------------------------------------------------- #


def test_local_header_encryption_is_classified_encrypted() -> None:
    payload = _mark_local_header_encrypted(_zip({"word/document.xml": _docx_xml("SAFE")}))
    with ZipFile(BytesIO(payload)) as archive:
        # The stdlib view still says "plain" — that is the whole point.
        assert not archive.infolist()[0].flag_bits & _ENCRYPTED_FLAG
    with pytest.raises(DocumentNormalizationError) as refused:
        validate_ooxml_archive(payload)
    assert refused.value.code == "ooxml_encrypted"


def test_local_header_encryption_refuses_the_document_route_not_only_the_gate() -> None:
    payload = _mark_local_header_encrypted(_zip({"word/document.xml": _docx_xml("SAFE")}))
    with pytest.raises(DocumentNormalizationError) as refused:
        extract_binary_document(name="report.docx", media_type=DOCX_MIME, payload=payload)
    assert refused.value.code == "ooxml_encrypted"


def test_an_ordinary_package_is_not_refused_by_the_local_header_read() -> None:
    payload = _zip({"word/document.xml": _docx_xml("SAFE")})
    extract_binary_document(name="report.docx", media_type=DOCX_MIME, payload=payload)


# --------------------------------------------------------------------------- #
# Encryption: the OLE wrapper Office writes
# --------------------------------------------------------------------------- #


def test_the_ole_fixture_is_a_real_compound_file() -> None:
    assert ENCRYPTED_DOCX[:8] == OLE_MAGIC
    assert _ole_stream_names(ENCRYPTED_DOCX) == ["Root Entry", "EncryptedPackage", "Versions"]
    assert _ole_stream_names(LEGACY_DOCX) == ["Root Entry", "WordDocument"]


@pytest.mark.parametrize("media", [DOCX_MIME, PPTX_MIME, XLSX_MIME])
def test_an_ole_wrapped_encrypted_package_is_classified_encrypted(media: str) -> None:
    suffix = {DOCX_MIME: "docx", PPTX_MIME: "pptx", XLSX_MIME: "xlsx"}[media]
    with pytest.raises(DocumentNormalizationError) as refused:
        extract_binary_document(name=f"secret.{suffix}", media_type=media,
                                payload=ENCRYPTED_DOCX)
    assert refused.value.code == "ooxml_encrypted"


def test_a_password_protected_package_is_not_reported_as_corrupt() -> None:
    try:
        validate_ooxml_archive(ENCRYPTED_DOCX)
    except DocumentNormalizationError as exc:
        assert exc.code != "ooxml_malformed"
        return
    raise AssertionError("an encrypted package was admitted")


def test_a_legacy_ole_document_claimed_as_docx_stays_corrupt_not_encrypted() -> None:
    with pytest.raises(DocumentNormalizationError) as refused:
        extract_binary_document(name="legacy.docx", media_type=DOCX_MIME, payload=LEGACY_DOCX)
    assert refused.value.code == "ooxml_malformed"
