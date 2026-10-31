"""#5895 — read a legacy HWP (한글 5.x binary) document into plain text.

The COM2 file lane is the only place these bytes are opened, and olefile (BSD)
is the only library: the parser below is the format work itself — a record walk
plus a text walker — because pyhwp/hwp5txt are AGPL and stay out of this
repository (CTO decision 2026-10-28, which moved legacy .hwp from UNSUPPORTED
to lane-supported). The Chat Worker never imports any of this.

What the format gives us (한글 문서 파일 구조 5.0):

* an OLE2 container whose ``FileHeader`` stream starts with the signature
  "HWP Document File". Two writer families exist in the wild: the standard one
  keeps "V1.30 ..." inside the 32-byte signature and a plain DWORD of document
  flags at offset 32 (bit 0 압축, bit 1 배포용, bit 4 암호화); the government
  writer family pads the signature with nulls, keeps the same flag bits in the
  low word and the 5.0/5.1 marker in the high word at offset 34;
* ``BodyText/SectionN`` streams holding the records. Compressed streams are
  raw deflate (zlib wbits=-15) — the lane sniffs the stream instead of
  trusting the flag bit, because the two writer families disagree on it;
* records: a 4-byte header DWORD with the tag in the low 10 bits. The size
  lives in the next 22 bits for standard files (0x3FFFFF meaning the next 4
  bytes carry the real size), and in the top 12 bits for the government
  writer family (0xFFF meaning the same). The lane walks the stream under
  both layouts and keeps the one that lands exactly on the end of the stream
  with sane tags — they are mutually exclusive in practice;
* ``HWPTAG_PARA_TEXT`` (tag 67) carrying one paragraph as UTF-16LE chars with
  control characters: 0x0009 is a tab, 0x000A/0x000D are line breaks, and the
  inline object controls (표, 구역, 머리말 — markers such as 0x0002/0x000B/
  0x0010) carry a printable-ASCII 4-byte id and an instance payload after
  them; the same marker without such an id is a bare placeholder whose data
  lives in the following records. Either way no text is guessed from them.

A document this build cannot read is refused by code, never guessed at:
encrypted and 배포용 documents never open, and an OLE2 file without HWP5's
signature, with an older format version, or without text is refused too.
"""
from __future__ import annotations

import re
import zlib
from io import BytesIO

PARA_TEXT_TAG = 67
_SIGNATURE = b"HWP Document File"
_FLAG_DISTRIBUTABLE = 0x02
_FLAG_ENCRYPTED = 0x10


class HwpError(Exception):
    """A refusal with a stable code; the caller maps it to its own HTTP status."""

    def __init__(self, code: str) -> None:
        self.code = code


def _olefile():
    try:
        import olefile
    except Exception:  # pragma: no cover - the deployed lane always ships olefile
        raise HwpError("hwp_editor_unavailable") from None
    return olefile


def _ole(payload: bytes):
    try:
        return _olefile().OleFileIO(BytesIO(payload))
    except Exception:
        raise HwpError("hwp_unreadable") from None


def _header(ole) -> int:
    """The document flags: the DWORD the two writer families both keep at 32."""

    try:
        if not ole.exists("FileHeader"):
            raise HwpError("hwp_unreadable")
        header = ole.openstream("FileHeader").read(36)
    except HwpError:
        raise
    except Exception:
        raise HwpError("hwp_unreadable") from None
    if len(header) < 36 or not header.startswith(_SIGNATURE):
        raise HwpError("hwp_unreadable")
    if header[17:32] == b"\x00" * 15:
        # The padded-signature family: flags in the low word, 5.0/5.1 above.
        if int.from_bytes(header[34:36], "little") >> 8 != 0x05:
            raise HwpError("hwp_version_unsupported")
        return int.from_bytes(header[32:34], "little")
    # The standard signature: "HWP Document File V1.30 ...". V1.30 is HWP5;
    # V1.20/1.21/1.22 are the older 한글97 layout, not walked here.
    tail = header[17:24].decode("ascii", "ignore")
    match = re.search(r"V(\d+)\.(\d+)", tail)
    if match is None:
        raise HwpError("hwp_unreadable")
    if (int(match.group(1)), int(match.group(2))) < (1, 30):
        raise HwpError("hwp_version_unsupported")
    return int.from_bytes(header[32:36], "little")


def _sections(ole) -> list[str]:
    """The BodyText section stream names, in document order."""

    try:
        names = [entry[-1] for entry in ole.listdir() if len(entry) == 2
                 and entry[0] == "BodyText" and entry[1].startswith("Section")]
    except Exception:
        raise HwpError("hwp_unreadable") from None
    if not names:
        raise HwpError("hwp_no_text")
    return sorted(names, key=lambda name: int(name[7:] or "0"))


def _body(data: bytes) -> bytes:
    """The stream's records — inflated when the stream turns out to be deflate."""

    try:
        engine = zlib.decompressobj(-15)
        return engine.decompress(data) + engine.flush()
    except Exception:
        return data


def _walk(data: bytes, width: int):
    """One record-header layout, walked to the end or None.

    ``width`` 22 is the standard layout (size in the next 22 bits, escape
    0x3FFFFF); ``width`` 12 is the padded-signature family (size in the top
    12 bits, escape 0xFFF).
    """

    escape = (1 << width) - 1
    shift = 32 - width
    offset = 0
    total = len(data)
    tags: set[int] = set()
    count = 0
    while offset + 4 <= total:
        header = int.from_bytes(data[offset:offset + 4], "little")
        offset += 4
        tag = header & 0x3FF
        size = (header >> shift) & escape
        if size == escape:
            if offset + 4 > total:
                return None
            size = int.from_bytes(data[offset:offset + 4], "little")
            offset += 4
        if tag < 10 or tag > 100 or offset + size > total:
            return None
        tags.add(tag)
        count += 1
        offset += size
    if offset != total or count == 0 or PARA_TEXT_TAG not in tags:
        return None
    return True


def _records(data: bytes):
    """The section's records under the layout this section actually uses."""

    for width in (22, 12):
        if _walk(data, width) is not None:
            escape = (1 << width) - 1
            shift = 32 - width
            offset = 0
            total = len(data)
            while offset + 4 <= total:
                header = int.from_bytes(data[offset:offset + 4], "little")
                offset += 4
                tag = header & 0x3FF
                size = (header >> shift) & escape
                if size == escape:
                    size = int.from_bytes(data[offset:offset + 4], "little")
                    offset += 4
                yield tag, data[offset:offset + size]
                offset += size
            return
    raise HwpError("hwp_unreadable")


def _para_text(payload: bytes) -> str:
    """One paragraph's chars: the words, with controls dropped or unfolded."""

    out: list[str] = []
    i = 0
    total = len(payload)
    while i + 2 <= total:
        ch = int.from_bytes(payload[i:i + 2], "little")
        i += 2
        if 0xD800 <= ch <= 0xDBFF and i + 2 <= total:
            low = int.from_bytes(payload[i:i + 2], "little")
            if 0xDC00 <= low <= 0xDFFF:
                i += 2
                out.append(chr(0x10000 + ((ch - 0xD800) << 10) + (low - 0xDC00)))
                continue
        if ch in (0x000A, 0x000D):
            out.append("\n")
        elif ch == 0x0009:
            out.append("\t")
        elif (ch < 0x0020 and i + 6 <= total
              and all(0x20 <= byte <= 0x7E for byte in payload[i:i + 4])):
            # The inline object controls: a printable-ASCII 4-byte id, an
            # instance size, and the instance bytes. The id check is what
            # keeps the words after a bare marker out of the skip.
            size = int.from_bytes(payload[i + 4:i + 6], "little")
            i += 6 + size
        elif ch < 0x0020 or 0xD800 <= ch <= 0xDFFF:
            continue
        else:
            out.append(chr(ch))
    return "".join(out)


def extract_text(payload: bytes) -> str:
    """The document's paragraphs, joined with newlines. Never writes a file."""

    book = _ole(payload)
    try:
        flags = _header(book)
        if flags & _FLAG_ENCRYPTED:
            raise HwpError("hwp_encrypted")
        if flags & _FLAG_DISTRIBUTABLE:
            raise HwpError("hwp_distributable")
        paragraphs: list[str] = []
        for name in _sections(book):
            try:
                data = _body(book.openstream(["BodyText", name]).read())
            except HwpError:
                raise
            except Exception:
                raise HwpError("hwp_unreadable") from None
            for tag, record in _records(data):
                if tag == PARA_TEXT_TAG:
                    paragraphs.append(_para_text(record))
        text = "\n".join(part.strip("\n") for part in paragraphs if part.strip())
        if not text.strip():
            raise HwpError("hwp_no_text")
        return text
    finally:
        book.close()
