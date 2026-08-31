from __future__ import annotations

from io import BytesIO
from pathlib import PurePosixPath
import re
from zipfile import BadZipFile, ZipFile
import xml.etree.ElementTree as ET


MAX_ARCHIVE_BYTES = 2 * 1024 * 1024
MAX_ENTRIES = 256
MAX_ENTRY_UNCOMPRESSED_BYTES = 1024 * 1024
MAX_TOTAL_UNCOMPRESSED_BYTES = 8 * 1024 * 1024
MAX_EXTRACTED_TEXT_CHARS = 40_000

_DOCX_MAIN = "word/document.xml"
_PPTX_SLIDE_RE = re.compile(r"ppt/slides/slide([1-9][0-9]*)\.xml\Z")
_WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_DRAWING_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"


class OOXMLExtractionError(ValueError):
    pass


def _reject_unsafe_member_name(name: str) -> None:
    if not name or "\\" in name or name.startswith("/") or re.match(r"^[A-Za-z]:", name):
        raise OOXMLExtractionError("unsafe OOXML archive member path")
    path = PurePosixPath(name)
    if any(part in {"", ".", ".."} for part in path.parts):
        raise OOXMLExtractionError("unsafe OOXML archive member path")


def _open_bounded_archive(payload: bytes) -> ZipFile:
    if not isinstance(payload, (bytes, bytearray)):
        raise OOXMLExtractionError("OOXML payload must be bytes")
    if not payload or len(payload) > MAX_ARCHIVE_BYTES:
        raise OOXMLExtractionError("OOXML archive size out of bounds")

    try:
        archive = ZipFile(BytesIO(bytes(payload)))
        infos = archive.infolist()
    except BadZipFile as exc:
        raise OOXMLExtractionError("malformed OOXML ZIP archive") from exc

    try:
        if len(infos) > MAX_ENTRIES:
            raise OOXMLExtractionError("OOXML archive has too many entries")

        total_uncompressed = 0
        for info in infos:
            _reject_unsafe_member_name(info.filename)
            if info.flag_bits & 0x1:
                raise OOXMLExtractionError("encrypted OOXML entries are not supported")
            if info.file_size > MAX_ENTRY_UNCOMPRESSED_BYTES:
                raise OOXMLExtractionError("OOXML entry exceeds size limit")
            total_uncompressed += info.file_size
            if total_uncompressed > MAX_TOTAL_UNCOMPRESSED_BYTES:
                raise OOXMLExtractionError("OOXML archive exceeds total uncompressed limit")

        # Common archive-level DTD guard: scan bounded XML parts for <!DOCTYPE case-insensitively.
        # This covers XLSX via validate_ooxml_archive before openpyxl and hardens DOCX/PPTX beyond per-part checks.
        for info in infos:
            if info.is_dir():
                continue
            name_lower = info.filename.lower()
            if not (name_lower.endswith(".xml") or name_lower.endswith(".rels")):
                continue
            raw = archive.read(info.filename)
            if b"<!DOCTYPE" in raw.upper():
                raise OOXMLExtractionError("OOXML DTDs are not supported")
    except Exception:
        archive.close()
        raise

    return archive


def validate_ooxml_archive(payload: bytes) -> None:
    archive = _open_bounded_archive(payload)
    archive.close()


def _read_xml_part(archive: ZipFile, name: str) -> ET.Element:
    try:
        raw = archive.read(name)
    except KeyError as exc:
        raise OOXMLExtractionError(f"missing OOXML part: {name}") from exc

    if b"<!DOCTYPE" in raw.upper():
        raise OOXMLExtractionError("OOXML DTDs are not supported")
    try:
        return ET.fromstring(raw)
    except ET.ParseError as exc:
        raise OOXMLExtractionError(f"invalid OOXML XML part: {name}") from exc


def _bounded_join(parts: list[str], separator: str = "\n") -> str:
    text = separator.join(part for part in parts if part)
    if len(text) > MAX_EXTRACTED_TEXT_CHARS:
        raise OOXMLExtractionError("extracted OOXML text exceeds limit")
    return text


def extract_docx_text(payload: bytes) -> str:
    archive = _open_bounded_archive(payload)
    try:
        root = _read_xml_part(archive, _DOCX_MAIN)
        paragraphs: list[str] = []
        for paragraph in root.iter(f"{{{_WORD_NS}}}p"):
            pieces = [node.text or "" for node in paragraph.iter(f"{{{_WORD_NS}}}t")]
            paragraphs.append("".join(pieces))
        return _bounded_join(paragraphs)
    finally:
        archive.close()


def extract_pptx_text(payload: bytes) -> str:
    archive = _open_bounded_archive(payload)
    try:
        slides: list[tuple[int, str]] = []
        for name in archive.namelist():
            match = _PPTX_SLIDE_RE.fullmatch(name)
            if match:
                slides.append((int(match.group(1)), name))
        if not slides:
            raise OOXMLExtractionError("missing PPTX slide XML parts")

        slide_text: list[str] = []
        for _, name in sorted(slides):
            root = _read_xml_part(archive, name)
            pieces = [node.text or "" for node in root.iter(f"{{{_DRAWING_NS}}}t")]
            slide_text.append("\n".join(piece for piece in pieces if piece))
        return _bounded_join(slide_text, separator="\n")
    finally:
        archive.close()
