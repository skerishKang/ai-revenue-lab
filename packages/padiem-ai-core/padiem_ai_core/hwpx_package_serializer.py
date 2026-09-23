"""Single bounded HWPX package content authority for Padiem AI Core.

This module is the only place in Core that *creates* an ``application/hwp+zip``
package from a content model, and the only place that owns the package's
section-XML shape, member-naming policy and archive-member policy. Callers
supply a small structured in-memory content model of section paragraphs only:
never raw XML, ZIP member names, or archive paths. Output is deterministic
memory-only bytes that must re-enter the existing common file-intake gate and
the existing Core HWPX reader for round-trip validation.

Editing an already admitted package without destroying the members this model
cannot represent is a different authority: ``hwpx_package_mutation`` composes
this module's section producer and member policy with Core's single archive
gate and single HWPX reader. It is not a second way to create a package — it
cannot change an archive's member set, so it can only preserve.

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
    validate_ooxml_member_name,
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
    section_payloads = [serialize_hwpx_section_part(section.paragraphs) for section in content.sections]
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
            validate_hwpx_paragraph_text(text)
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


def validate_hwpx_paragraph_text(text: str) -> None:
    """The single paragraph-text content rule for the writable HWPX subset.

    Type, length and XML-character policy are decided here and nowhere else.
    The whole-package validator and the package-preserving mutator both call
    it, so the two can never drift apart about what a writable paragraph may
    contain.
    """

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


def _escape_xml_text(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def serialize_hwpx_section_part(paragraphs: tuple[str, ...]) -> bytes:
    """Produce the one canonical section-part byte shape for this subset.

    This is the single section-XML producer in Core. The package writer calls
    it for every section it emits, and the package-preserving mutator calls it
    for the one section member it rewrites, so a rewritten part is
    byte-identical to what a freshly created package would carry for the same
    paragraphs. Every paragraph text passes the single content rule before it
    reaches the XML layer, so no caller can emit text the model would refuse.
    """

    if not isinstance(paragraphs, tuple):
        raise DocumentNormalizationError(
            "hwpx_serialize_model",
            "HWPX serialize paragraphs must be a tuple of strings.",
        )
    for text in paragraphs:
        validate_hwpx_paragraph_text(text)
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
    """The single archive-member policy in Core.

    A fixed timestamp, stored compression and a fixed create-system, so the same
    member sequence always produces the same bytes and no caller-supplied value
    can influence how a member is stored.

    The member permission bits are *not* set here: the standard library's member
    writer assigns them itself and overwrites whatever this factory put on the
    ``ZipInfo``, so an assignment would be dead code that only looked like
    policy. Determinism comes from the values below, which the writer does keep.
    """

    info = ZipInfo(filename=name, date_time=_FIXED_ZIP_TIMESTAMP)
    info.create_system = 0
    info.compress_type = ZIP_STORED
    return info


def assemble_hwpx_package_members(members: tuple[tuple[str, bytes], ...]) -> bytes:
    """Assemble one package from an ordered, already-decided member sequence.

    This is the single place in Core that writes an ``application/hwp+zip``
    archive, and the single place the archive-member policy lives. The
    canonical package creator and the package-preserving mutator both reach the
    archive through it, so Core keeps exactly one member policy.

    It is a writer, not a content authority. It invents no member, it cannot
    reorder or drop one, and every name is judged by the same predicate the
    archive gate applies to every member it walks — so this function can never
    produce an archive Core's own gate would refuse, and a caller-supplied name
    can never become an archive path.
    """

    if not isinstance(members, tuple) or not members:
        raise DocumentNormalizationError(
            "hwpx_assemble_model",
            "HWPX package assembly requires a non-empty tuple of members.",
        )
    if len(members) > MAX_OOXML_ENTRIES:
        raise DocumentNormalizationError(
            "hwpx_assemble_member_count",
            "HWPX package assembly exceeds the archive entry budget.",
        )
    names: list[str] = []
    for member in members:
        if not isinstance(member, tuple) or len(member) != 2:
            raise DocumentNormalizationError(
                "hwpx_assemble_model",
                "HWPX package members must be (name, payload) pairs.",
            )
        name, member_payload = member
        names.append(validate_ooxml_member_name(name))
        if not isinstance(member_payload, bytes) or not member_payload:
            raise DocumentNormalizationError(
                "hwpx_assemble_payload",
                "HWPX package member payload must be non-empty bytes.",
            )
    if len(set(names)) != len(names):
        raise DocumentNormalizationError(
            "hwpx_assemble_member_name",
            "HWPX package member names must be unique.",
        )

    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_STORED) as archive:
        for name, member_payload in members:
            archive.writestr(_fixed_member(name), member_payload)
    payload = buffer.getvalue()
    if len(payload) > MAX_BINARY_DOCUMENT_BYTES:
        raise DocumentNormalizationError(
            "hwpx_assemble_output_size",
            "HWPX package assembly exceeds the output size limit.",
        )
    return payload


def _package_bytes(section_payloads: list[bytes]) -> bytes:
    """Build the canonical member sequence and assemble it."""

    members: list[tuple[str, bytes]] = [("mimetype", HWPX_MEDIA_TYPE.encode("ascii"))]
    for index, payload in enumerate(section_payloads, start=1):
        members.append((f"Contents/section{index}.xml", payload))
    return assemble_hwpx_package_members(tuple(members))


__all__ = [
    "HWPX_MEDIA_TYPE",
    "MAX_HWPX_PACKAGE_TEXT_CHARS",
    "MAX_HWPX_PARAGRAPH_CHARS",
    "MAX_HWPX_PARAGRAPHS",
    "MAX_HWPX_SECTIONS",
    "HwpxPackageContent",
    "HwpxPackageSection",
    "assemble_hwpx_package_members",
    "deserialize_hwpx_package",
    "serialize_hwpx_package",
    "serialize_hwpx_section_part",
    "validate_hwpx_paragraph_text",
]
