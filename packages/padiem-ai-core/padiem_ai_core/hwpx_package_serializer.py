"""Single bounded HWPX package content authority for Padiem AI Core.

This module is the only place in Core that assembles ``application/hwp+zip``
package bytes. Callers supply a small structured in-memory content model of
section paragraphs only: never raw XML, ZIP member names, or archive paths.
Output is deterministic memory-only bytes that must re-enter the existing
common file-intake gate and the existing Core HWPX reader for round-trip
validation.

Reading bytes back into the model goes through :func:`deserialize_hwpx_package`,
which reuses Core's single HWPX archive-and-XML reader and adds no parsing of
its own: it only judges whether what that reader found fits this writable
subset. This module therefore never walks an archive, never parses XML, never
reads or writes the host filesystem, and never opens a network or provider
surface.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from zipfile import ZIP_STORED, ZipFile, ZipInfo

from .document_normalization import (
    MAX_BINARY_DOCUMENT_BYTES,
    MAX_DOCUMENT_CHARS,
    MAX_OOXML_ENTRIES,
    parse_hwpx_sections,
)
from .document_semantics import (
    MAX_DOCUMENT_SEGMENTS,
    DocumentNormalizationError,
)

HWPX_MEDIA_TYPE = "application/hwp+zip"

MAX_HWPX_SECTIONS = 64
MAX_HWPX_PARAGRAPHS = MAX_DOCUMENT_SEGMENTS
MAX_HWPX_PARAGRAPH_CHARS = 4_000
MAX_HWPX_PACKAGE_TEXT_CHARS = MAX_DOCUMENT_CHARS

_SECTION_NAMESPACE = "http://www.hancom.co.kr/hwpml/2011/section"
_PARAGRAPH_NAMESPACE = "http://www.hancom.co.kr/hwpml/2011/paragraph"
_SECTION_ROOT_TAG = f"{{{_SECTION_NAMESPACE}}}sec"
_FIXED_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
_XML_DECLARATION = '<?xml version="1.0" encoding="UTF-8"?>'


@dataclass(frozen=True, slots=True)
class HwpxPackageSection:
    """One bounded section of plain paragraph strings."""

    paragraphs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class HwpxPackageContent:
    """Structured caller content model; no raw XML or member authority."""

    sections: tuple[HwpxPackageSection, ...]


def serialize_hwpx_package(content: HwpxPackageContent) -> bytes:
    """Serialize bounded structured content into deterministic HWPX bytes.

    The only accepted input is :class:`HwpxPackageContent`. The only output is
    an in-memory ``application/hwp+zip`` byte string whose member names are
    fixed by this authority. Malformed, oversized, empty, or injection-shaped
    caller structures fail closed with a bounded Core reason code.
    """

    _validate_content(content)
    section_payloads = [_section_xml(section.paragraphs) for section in content.sections]
    payload = _package_bytes(section_payloads)
    if len(payload) > MAX_BINARY_DOCUMENT_BYTES:
        raise DocumentNormalizationError(
            "hwpx_serialize_output_size",
            "Serialized HWPX package exceeds the output size limit.",
        )
    return payload


def deserialize_hwpx_package(payload: bytes) -> HwpxPackageContent:
    """Recover the structured content model from HWPX bytes, or refuse.

    The inverse of :func:`serialize_hwpx_package` over the subset this authority
    owns. Parsing happens once, in Core's single HWPX archive-and-XML reader;
    this function only decides whether what it found can be put back into the
    editable model without losing anything, and then re-runs the writer's own
    bounds so a returned model is always one this module could serialize again.

    A package outside the supported subset fails closed instead of being
    projected into a model that would silently drop shape on the next write.
    That covers tables, images, shapes and any other element anywhere in the
    part, paragraphs that hold other paragraphs, paragraphs whose text came
    from more than one run or from none, a section root this writer would never
    emit, repeated section numbers, and a part carrying a carriage return, whose
    text an XML parser has already rewritten into a line feed.
    """

    sections: list[HwpxPackageSection] = []
    previous_index = 0
    for parsed in parse_hwpx_sections(payload):
        if parsed.root_tag != _SECTION_ROOT_TAG:
            raise DocumentNormalizationError(
                "hwpx_unsupported_section_root",
                "HWPX section part root is not the section element this decoder supports.",
            )
        if parsed.index <= previous_index:
            raise DocumentNormalizationError(
                "hwpx_unsupported_section_order",
                "HWPX section parts are repeated or not in ascending order.",
            )
        previous_index = parsed.index
        if parsed.has_carriage_return:
            raise DocumentNormalizationError(
                "hwpx_unsupported_control_character",
                "HWPX part contains a carriage return that XML parsing cannot preserve.",
            )
        if parsed.unsupported_nodes:
            raise DocumentNormalizationError(
                "hwpx_unsupported_structure",
                "HWPX contains a structure the editable model cannot represent.",
            )
        paragraphs: list[str] = []
        for paragraph in parsed.paragraphs:
            if paragraph.holds_nested_paragraph:
                raise DocumentNormalizationError(
                    "hwpx_unsupported_structure",
                    "HWPX contains a paragraph structure the editable model cannot represent.",
                )
            if paragraph.text_nodes != 1:
                raise DocumentNormalizationError(
                    "hwpx_unsupported_run_semantics",
                    "HWPX paragraph text does not come from exactly one run text node.",
                )
            if "\r" in paragraph.text:
                # A character reference can survive parsing as a carriage return
                # where a literal one was rewritten to a line feed; neither shape
                # can be written and read back unchanged.
                raise DocumentNormalizationError(
                    "hwpx_unsupported_control_character",
                    "HWPX paragraph contains a carriage return this model cannot round-trip.",
                )
            paragraphs.append(paragraph.text)
        sections.append(HwpxPackageSection(paragraphs=tuple(paragraphs)))
    content = HwpxPackageContent(sections=tuple(sections))
    _validate_content(content)
    return content


def _validate_content(content: HwpxPackageContent) -> None:
    if not isinstance(content, HwpxPackageContent):
        raise DocumentNormalizationError(
            "hwpx_serialize_model",
            "HWPX serialize content must be an HwpxPackageContent model.",
        )
    if not isinstance(content.sections, tuple) or not content.sections:
        raise DocumentNormalizationError(
            "hwpx_serialize_model",
            "HWPX serialize content requires a non-empty tuple of sections.",
        )
    if len(content.sections) > MAX_HWPX_SECTIONS:
        raise DocumentNormalizationError(
            "hwpx_serialize_section_limit",
            "HWPX serialize content exceeds the section limit.",
        )
    if len(content.sections) > MAX_OOXML_ENTRIES - 1:
        raise DocumentNormalizationError(
            "hwpx_serialize_section_limit",
            "HWPX serialize content exceeds the archive entry budget.",
        )
    paragraph_count = 0
    total_chars = 0
    has_readable = False
    for section in content.sections:
        if not isinstance(section, HwpxPackageSection):
            raise DocumentNormalizationError(
                "hwpx_serialize_model",
                "HWPX serialize sections must be HwpxPackageSection values.",
            )
        if not isinstance(section.paragraphs, tuple):
            raise DocumentNormalizationError(
                "hwpx_serialize_model",
                "HWPX serialize paragraphs must be a tuple of strings.",
            )
        paragraph_count += len(section.paragraphs)
        if paragraph_count > MAX_HWPX_PARAGRAPHS:
            raise DocumentNormalizationError(
                "hwpx_serialize_paragraph_limit",
                "HWPX serialize content exceeds the paragraph limit.",
            )
        for text in section.paragraphs:
            if not isinstance(text, str):
                raise DocumentNormalizationError(
                    "hwpx_serialize_model",
                    "HWPX serialize paragraphs must contain only strings.",
                )
            if len(text) > MAX_HWPX_PARAGRAPH_CHARS:
                raise DocumentNormalizationError(
                    "hwpx_serialize_paragraph_text_limit",
                    "HWPX serialize paragraph exceeds the text limit.",
                )
            for character in text:
                if not _is_xml_char(character):
                    raise DocumentNormalizationError(
                        "hwpx_serialize_control_char",
                        "HWPX serialize text contains a disallowed control character.",
                    )
            total_chars += len(text)
        section_text = "\n".join(text for text in section.paragraphs if text).strip()
        if section_text:
            has_readable = True
    if total_chars > MAX_HWPX_PACKAGE_TEXT_CHARS:
        raise DocumentNormalizationError(
            "hwpx_serialize_text_limit",
            "HWPX serialize content exceeds the total text limit.",
        )
    if not has_readable:
        raise DocumentNormalizationError(
            "hwpx_serialize_empty",
            "HWPX serialize content contains no readable text.",
        )


def _is_xml_char(character: str) -> bool:
    codepoint = ord(character)
    return (
        codepoint in (0x09, 0x0A, 0x0D)
        or 0x20 <= codepoint <= 0xD7FF
        or 0xE000 <= codepoint <= 0xFFFD
        or 0x10000 <= codepoint <= 0x10FFFF
    )


def _escape_xml_text(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _section_xml(paragraphs: tuple[str, ...]) -> bytes:
    body = "".join(
        f"<hp:p><hp:runs><hp:t>{_escape_xml_text(text)}</hp:t></hp:runs></hp:p>"
        for text in paragraphs
    )
    document = (
        f"{_XML_DECLARATION}"
        f'<hs:sec xmlns:hs="{_SECTION_NAMESPACE}" xmlns:hp="{_PARAGRAPH_NAMESPACE}">'
        f"{body}</hs:sec>"
    )
    return document.encode("utf-8")


def _fixed_member(name: str) -> ZipInfo:
    info = ZipInfo(filename=name, date_time=_FIXED_ZIP_TIMESTAMP)
    info.create_system = 0
    info.external_attr = 0
    info.compress_type = ZIP_STORED
    return info


def _package_bytes(section_payloads: list[bytes]) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_STORED) as archive:
        archive.writestr(_fixed_member("mimetype"), HWPX_MEDIA_TYPE.encode("ascii"))
        for index, payload in enumerate(section_payloads, start=1):
            archive.writestr(_fixed_member(f"Contents/section{index}.xml"), payload)
    return buffer.getvalue()


__all__ = [
    "HWPX_MEDIA_TYPE",
    "MAX_HWPX_PACKAGE_TEXT_CHARS",
    "MAX_HWPX_PARAGRAPH_CHARS",
    "MAX_HWPX_PARAGRAPHS",
    "MAX_HWPX_SECTIONS",
    "HwpxPackageContent",
    "HwpxPackageSection",
    "deserialize_hwpx_package",
    "serialize_hwpx_package",
]
