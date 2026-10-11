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
    MAX_HWPX_PICTURE_HWPUNIT,
    MAX_OOXML_ENTRIES,
    HWPX_PICTURE_CHILD_NAMES,
    _last_hwpx_section_facts,
    is_hwpx_binary_item_id,
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
MAX_HWPX_TABLE_ROWS = 32
MAX_HWPX_TABLE_COLUMNS = 16
MAX_HWPX_TABLE_CELLS = MAX_HWPX_TABLE_ROWS * MAX_HWPX_TABLE_COLUMNS
MAX_HWPX_CELL_TEXT_CHARS = 4_000
MAX_HWPX_PACKAGE_TABLE_CELLS = MAX_HWPX_TABLE_CELLS
MAX_HWPX_PACKAGE_TEXT_CHARS = MAX_DOCUMENT_CHARS
#: Largest number of picture blocks one content model may carry. Bounded so a
#: model cannot be used to inflate a section part without limit.
MAX_HWPX_PACKAGE_PICTURES = 32

_SECTION_NAMESPACE = "http://www.hancom.co.kr/hwpml/2011/section"
_PARAGRAPH_NAMESPACE = "http://www.hancom.co.kr/hwpml/2011/paragraph"
_CORE_NAMESPACE = "http://www.hancom.co.kr/hwpml/2011/core"
_SECTION_ROOT_TAG = f"{{{_SECTION_NAMESPACE}}}sec"
_FIXED_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
_XML_DECLARATION = '<?xml version="1.0" encoding="UTF-8"?>'


@dataclass(frozen=True, slots=True)
class HwpxTableCell:
    """One bounded cell containing canonical paragraph text."""

    text: str


@dataclass(frozen=True, slots=True)
class HwpxTable:
    """One Core-owned rectangular bounded table."""

    rows: tuple[tuple[HwpxTableCell, ...], ...]


@dataclass(frozen=True, slots=True)
class HwpxPicture:
    """One bounded picture block: a ``BIN####`` reference and a draw extent.

    ``binary_item_id_ref`` names a ``content.hpf`` manifest item, not a ZIP
    member, so holding this value grants no package-path authority. The
    dimensions are HWPUNIT (1/7200 inch).
    """

    binary_item_id_ref: str
    width_hwpunit: int
    height_hwpunit: int


@dataclass(frozen=True, slots=True)
class HwpxSectionBlock:
    """One ordered section block: a paragraph, a table or a picture."""

    kind: str
    text: str | None = None
    table: HwpxTable | None = None
    picture: HwpxPicture | None = None


@dataclass(frozen=True, slots=True)
class HwpxPackageSection:
    """One bounded section with ordered paragraph/table blocks.

    ``paragraphs`` remains the legacy paragraph-only projection. It is derived
    from ``blocks`` for table-aware sections and remains unchanged for callers
    constructing the paragraph-only subset.
    """

    paragraphs: tuple[str, ...]
    blocks: tuple[HwpxSectionBlock, ...] = ()


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
    section_payloads = [
        serialize_hwpx_section_part(section.paragraphs) if not section.blocks else serialize_hwpx_section_blocks(section.blocks)
        for section in content.sections
    ]
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
    This covers unsupported table structures, images, shapes and any other
    element anywhere in the part, paragraphs that hold other paragraphs,
    paragraphs whose text came
    from more than one run or from none, a section root this writer would never
    emit, repeated section numbers, and a part carrying a carriage return, whose
    text an XML parser has already rewritten into a line feed.
    """

    sections: list[HwpxPackageSection] = []
    previous_index = 0
    parsed_sections = parse_hwpx_sections(payload)
    parsed_facts = _last_hwpx_section_facts()
    if parsed_facts is None or len(parsed_facts) != len(parsed_sections):
        raise DocumentNormalizationError("hwpx_unsupported_structure", "HWPX facts are unavailable.")
    for parsed, facts in zip(parsed_sections, parsed_facts, strict=True):
        if parsed.root_tag != _SECTION_ROOT_TAG:
            raise DocumentNormalizationError("hwpx_unsupported_section_root", "HWPX section part root is not supported.")
        if parsed.index <= previous_index:
            raise DocumentNormalizationError("hwpx_unsupported_section_order", "HWPX section parts are not ascending.")
        previous_index = parsed.index
        if parsed.has_carriage_return:
            raise DocumentNormalizationError("hwpx_unsupported_control_character", "HWPX part contains a carriage return.")
        if facts.structured_unsupported_nodes:
            raise DocumentNormalizationError("hwpx_unsupported_structure", "HWPX contains an unsupported structure.")
        blocks: list[HwpxSectionBlock] = []
        for block in facts.blocks:
            if block.kind == "paragraph":
                if block.paragraph is None or block.paragraph.holds_nested_paragraph:
                    raise DocumentNormalizationError("hwpx_unsupported_structure", "HWPX paragraph shape is unsupported.")
                if block.paragraph.text_nodes != 1:
                    raise DocumentNormalizationError("hwpx_unsupported_run_semantics", "HWPX paragraph text does not come from exactly one run text node.")
                if "\r" in block.paragraph.text:
                    raise DocumentNormalizationError("hwpx_unsupported_control_character", "HWPX paragraph contains a carriage return.")
                blocks.append(HwpxSectionBlock("paragraph", block.paragraph.text))
            elif block.kind == "table" and block.table is not None:
                if (
                    not block.table.rows
                    or block.table.unsupported
                    or any(
                        not row
                        or any(
                            cell.unsupported
                            or any(
                                paragraph.runs != 1
                                or paragraph.text_nodes != 1
                                or paragraph.text_form not in {"empty_text", "non_empty_text"}
                                for paragraph in cell.paragraphs
                            )
                            for cell in row
                        )
                        for row in block.table.rows
                    )
                ):
                    raise DocumentNormalizationError("hwpx_unsupported_structure", "HWPX table contains an unsupported structure.")
                rows = tuple(
                    tuple(
                        HwpxTableCell(paragraphs[0].text)
                        for cell in row
                        for paragraphs in [cell.paragraphs]
                        if len(paragraphs) == 1 and paragraphs[0].runs == 1 and paragraphs[0].text_nodes == 1
                    )
                    for row in block.table.rows
                )
                if len(rows) != len(block.table.rows) or any(len(row) != len(block.table.rows[0]) for row in rows):
                    raise DocumentNormalizationError("hwpx_unsupported_structure", "HWPX table shape is unsupported.")
                blocks.append(HwpxSectionBlock("table", table=HwpxTable(rows)))
            elif block.kind == "picture" and block.picture is not None:
                if block.picture.unsupported:
                    raise DocumentNormalizationError("hwpx_unsupported_structure", "HWPX picture structure is unsupported.")
                picture = HwpxPicture(
                    binary_item_id_ref=block.picture.binary_item_id_ref,
                    width_hwpunit=block.picture.width_hwpunit,
                    height_hwpunit=block.picture.height_hwpunit,
                )
                # Re-run the block's own content rule so a decoded picture is
                # always one this module could serialize again.
                _validate_picture(picture)
                blocks.append(HwpxSectionBlock("picture", picture=picture))
            else:
                raise DocumentNormalizationError("hwpx_unsupported_structure", "HWPX section block is unsupported.")
        paragraphs = tuple(block.text for block in blocks if block.kind == "paragraph")
        sections.append(HwpxPackageSection(paragraphs=paragraphs, blocks=tuple(blocks) if any(block.kind in {"table", "picture"} for block in blocks) else ()))
    content = HwpxPackageContent(sections=tuple(sections))
    # A decoded picture is judged against the same picture bound the section
    # producer applies, so a picture this decoder returns is always one
    # :func:`serialize_hwpx_picture_paragraph` could write.
    _validate_content(content, allow_pictures=True)
    return content


def _validate_table(table: HwpxTable) -> int:
    if not isinstance(table, HwpxTable) or not isinstance(table.rows, tuple) or not table.rows:
        raise DocumentNormalizationError("hwpx_serialize_table_model", "HWPX tables require non-empty row tuples.")
    if len(table.rows) > MAX_HWPX_TABLE_ROWS:
        raise DocumentNormalizationError("hwpx_serialize_table_row_limit", "HWPX table exceeds the row limit.")
    widths = {len(row) for row in table.rows if isinstance(row, tuple)}
    if not widths or len(widths) != 1 or 0 in widths or next(iter(widths)) > MAX_HWPX_TABLE_COLUMNS:
        raise DocumentNormalizationError("hwpx_serialize_table_shape", "HWPX table rows must be rectangular and bounded.")
    cell_count = len(table.rows) * next(iter(widths))
    if cell_count > MAX_HWPX_TABLE_CELLS:
        raise DocumentNormalizationError("hwpx_serialize_table_cell_limit", "HWPX table exceeds the cell limit.")
    total = 0
    for row in table.rows:
        for cell in row:
            if not isinstance(cell, HwpxTableCell):
                raise DocumentNormalizationError("hwpx_serialize_table_model", "HWPX table cells must be HwpxTableCell values.")
            if len(cell.text) > MAX_HWPX_CELL_TEXT_CHARS:
                raise DocumentNormalizationError("hwpx_serialize_cell_text_limit", "HWPX table cell exceeds the text limit.")
            validate_hwpx_paragraph_text(cell.text)
            total += len(cell.text)
    return total


def _serialize_table_xml(table: HwpxTable) -> str:
    rows: list[str] = []
    for row in table.rows:
        cells = "".join(
            f"<hp:tc><hp:p><hp:runs><hp:t>{_escape_xml_text(cell.text)}</hp:t></hp:runs></hp:p></hp:tc>"
            for cell in row
        )
        rows.append(f"<hp:tr>{cells}</hp:tr>")
    return "<hp:tbl>" + "".join(rows) + "</hp:tbl>"


def _validate_picture(picture: HwpxPicture) -> None:
    """Judge one picture block against the bounded model.

    Type, id grammar, draw-extent type and draw-extent bounds are decided here
    and nowhere else, so the whole-package writer and the image-insertion
    authority can never disagree about what a picture block may contain.
    """

    if not isinstance(picture, HwpxPicture):
        raise DocumentNormalizationError(
            "hwpx_serialize_picture_model",
            "HWPX picture blocks require a HwpxPicture value.",
        )
    if not is_hwpx_binary_item_id(picture.binary_item_id_ref):
        raise DocumentNormalizationError(
            "hwpx_serialize_picture_model",
            "HWPX picture binaryItemIDRef must use the BIN#### id shape.",
        )
    for value in (picture.width_hwpunit, picture.height_hwpunit):
        if not isinstance(value, int) or isinstance(value, bool):
            raise DocumentNormalizationError(
                "hwpx_serialize_picture_model",
                "HWPX picture dimensions must be integers.",
            )
        if not 0 < value <= MAX_HWPX_PICTURE_HWPUNIT:
            raise DocumentNormalizationError(
                "hwpx_serialize_picture_dimension_limit",
                "HWPX picture dimension is out of bounds.",
            )


def _picture_xml(picture: HwpxPicture) -> str:
    """Produce the one canonical ``hp:pic``/``hc:img`` block.

    This is the only place Core writes a picture block, and the child sequence is
    exactly :data:`HWPX_PICTURE_CHILD_NAMES`, which is the sequence the single
    reader recognizes. Drawing defaults are fixed here (square wrap, no flip,
    no rotation, no effects) rather than accepted from a caller: this slice owns
    a shape it can both write and read, not the full HWPX picture vocabulary.

    The core namespace is declared on ``hp:pic`` itself rather than on the
    section root, so one picture paragraph is self-contained: the whole-package
    writer can emit it inside a section it also writes, and the image-insertion
    authority can splice the very same bytes into a section part it must not
    otherwise touch, without either side having to own the other's root element.
    """

    width = picture.width_hwpunit
    height = picture.height_hwpunit
    size = f'width="{width}" height="{height}"'
    return (
        '<hp:p><hp:runs><hp:pic xmlns:hc="' + _CORE_NAMESPACE + '"'
        ' textWrap="SQUARE" textFlow="BOTH_SIDES"'
        ' reverse="0" numberingType="PICTURE" id="0" zOrder="0"'
        ' instid="0" lock="0" dropcapstyle="None" href="" groupLevel="0">'
        '<hp:offset x="0" y="0"/>'
        f"<hp:orgSz {size}/>"
        f"<hp:curSz {size}/>"
        f'<hp:sz {size} widthRelTo="ABSOLUTE" heightRelTo="ABSOLUTE" protect="0"/>'
        '<hp:pos relativeFrom="para" vertOffset="0" horzOffset="0"'
        ' vertAlign="top" horzAlign="left" relativeTo="column" wrap="square"/>'
        "<hp:imgRect>"
        '<hp:pt0 x="0" y="0"/>'
        f'<hp:pt1 x="{width}" y="0"/>'
        f'<hp:pt2 x="{width}" y="{height}"/>'
        f'<hp:pt3 x="0" y="{height}"/>'
        "</hp:imgRect>"
        f'<hp:imgClip left="0" right="{width}" top="0" bottom="{height}"/>'
        '<hp:inMargin left="0" right="0" top="0" bottom="0"/>'
        f'<hp:imgDim dimwidth="{width}" dimheight="{height}"/>'
        f'<hc:img binaryItemIDRef="{picture.binary_item_id_ref}"'
        ' bright="0" contrast="0" effect="REAL_PIC" alpha="0"/>'
        "<hp:effects/>"
        '<hp:outMargin left="0" right="0" top="0" bottom="0"/>'
        "<hp:shapeComment/>"
        "</hp:pic></hp:runs></hp:p>"
    )


def serialize_hwpx_picture_paragraph(picture: HwpxPicture) -> bytes:
    """Produce the one canonical, self-contained picture paragraph.

    This is the public seam the image-insertion authority reaches for. It is the
    same bytes :func:`serialize_hwpx_section_blocks` places inside a section it
    writes, so an inserted picture is byte-identical to a picture this Core
    created from scratch, and a template's own section part is never rewritten
    beyond the one paragraph this call appends to it.
    """

    if not isinstance(picture, HwpxPicture):
        raise DocumentNormalizationError(
            "hwpx_serialize_picture_model",
            "HWPX picture paragraphs require a HwpxPicture value.",
        )
    _validate_picture(picture)
    return _picture_xml(picture).encode("utf-8")


def serialize_hwpx_section_blocks(blocks: tuple[HwpxSectionBlock, ...]) -> bytes:
    """Serialize the single canonical ordered paragraph/table/picture shape."""

    if not isinstance(blocks, tuple) or not blocks:
        raise DocumentNormalizationError("hwpx_serialize_model", "HWPX section blocks must be a non-empty tuple.")
    body: list[str] = []
    for block in blocks:
        if block.kind == "paragraph":
            if block.table is not None or block.picture is not None or not isinstance(block.text, str):
                raise DocumentNormalizationError("hwpx_serialize_model", "HWPX paragraph block shape is invalid.")
            validate_hwpx_paragraph_text(block.text)
            body.append(f"<hp:p><hp:runs><hp:t>{_escape_xml_text(block.text)}</hp:t></hp:runs></hp:p>")
        elif block.kind == "table":
            if block.text is not None or block.table is None or block.picture is not None:
                raise DocumentNormalizationError("hwpx_serialize_model", "HWPX table block shape is invalid.")
            _validate_table(block.table)
            body.append(_serialize_table_xml(block.table))
        elif block.kind == "picture":
            if block.text is not None or block.table is not None or block.picture is None:
                raise DocumentNormalizationError("hwpx_serialize_model", "HWPX picture block shape is invalid.")
            _validate_picture(block.picture)
            body.append(_picture_xml(block.picture))
        else:
            raise DocumentNormalizationError("hwpx_serialize_model", "HWPX section block kind is unsupported.")
    document = f"{_XML_DECLARATION}<hs:sec xmlns:hs=\"{_SECTION_NAMESPACE}\" xmlns:hp=\"{_PARAGRAPH_NAMESPACE}\">" + "".join(body) + "</hs:sec>"
    return document.encode("utf-8")


def _validate_content(content: HwpxPackageContent, *, allow_pictures: bool = False) -> None:
    """Judge one content model, and say up front which writer may carry pictures.

    A picture block names a ``content.hpf`` manifest item, and a manifest item
    names a ``BinData`` member. :func:`serialize_hwpx_package` creates a package
    holding only ``mimetype`` and section parts — it owns no manifest and no
    binary data — so it must refuse a picture rather than emit a section that
    references an id nothing in the package can resolve. The section-level
    producer and the image-insertion authority are the only writers that place a
    picture, and they place it into a package whose manifest this Core did not
    create. The decoder therefore asks for pictures to be allowed, and the
    from-scratch writer does not.
    """

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
    table_cell_count = 0
    picture_count = 0
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
        if not isinstance(section.blocks, tuple):
            raise DocumentNormalizationError("hwpx_serialize_model", "HWPX serialize blocks must be a tuple.")
        if section.blocks:
            if any(block.kind == "paragraph" and block.text not in section.paragraphs for block in section.blocks):
                raise DocumentNormalizationError("hwpx_serialize_model", "HWPX section paragraphs must match ordered blocks.")
            expected = tuple(block.text for block in section.blocks if block.kind == "paragraph")
            if expected != section.paragraphs:
                raise DocumentNormalizationError("hwpx_serialize_model", "HWPX section paragraphs must match ordered blocks.")
            for block in section.blocks:
                if block.kind == "paragraph":
                    if not isinstance(block.text, str):
                        raise DocumentNormalizationError("hwpx_serialize_model", "HWPX paragraph blocks require text.")
                    validate_hwpx_paragraph_text(block.text)
                    total_chars += len(block.text)
                    if block.text.strip():
                        has_readable = True
                elif block.kind == "table":
                    if block.text is not None or block.table is None:
                        raise DocumentNormalizationError("hwpx_serialize_model", "HWPX table block shape is invalid.")
                    total_chars += _validate_table(block.table)
                    table_cell_count += len(block.table.rows) * len(block.table.rows[0])
                    if table_cell_count > MAX_HWPX_PACKAGE_TABLE_CELLS:
                        raise DocumentNormalizationError(
                            "hwpx_serialize_table_cell_limit",
                            "HWPX package exceeds the bounded table-cell budget.",
                        )
                    if any(cell.text.strip() for row in block.table.rows for cell in row):
                        has_readable = True
                elif block.kind == "picture":
                    if block.text is not None or block.picture is None:
                        raise DocumentNormalizationError("hwpx_serialize_model", "HWPX picture block shape is invalid.")
                    if not allow_pictures:
                        raise DocumentNormalizationError(
                            "hwpx_serialize_picture_unsupported",
                            "HWPX from-scratch serialization does not create a picture manifest.",
                        )
                    _validate_picture(block.picture)
                    picture_count += 1
                    if picture_count > MAX_HWPX_PACKAGE_PICTURES:
                        raise DocumentNormalizationError(
                            "hwpx_serialize_picture_limit",
                            "HWPX content exceeds the picture-count limit.",
                        )
                else:
                    raise DocumentNormalizationError("hwpx_serialize_model", "HWPX section block kind is unsupported.")
            paragraph_count += len(section.paragraphs)
            if any(text for text in section.paragraphs):
                has_readable = True
        else:
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


def _assemble_hwpx_package_members(members: tuple[tuple[str, bytes], ...]) -> bytes:
    """Internal archive assembly seam for already-decided member sequences.

    This is the single place in Core that writes an ``application/hwp+zip``
    archive, and the single place the archive-member policy lives. The
    canonical package creator and the package-preserving mutator both reach the
    archive through this private seam, so Core keeps exactly one member policy
    without exposing a generic raw-member ZIP writer as public API.

    It is a writer, not a caller-facing content authority. It invents no member,
    it cannot reorder or drop one, and every name is judged by the same path
    predicate the archive gate uses — so this function can never produce an
    archive Core's own gate would refuse.
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
    return _assemble_hwpx_package_members(tuple(members))


__all__ = [
    "HWPX_MEDIA_TYPE",
    "MAX_HWPX_PACKAGE_TEXT_CHARS",
    "MAX_HWPX_PACKAGE_PICTURES",
    "MAX_HWPX_PARAGRAPH_CHARS",
    "MAX_HWPX_PARAGRAPHS",
    "MAX_HWPX_TABLE_ROWS",
    "MAX_HWPX_TABLE_COLUMNS",
    "MAX_HWPX_TABLE_CELLS",
    "MAX_HWPX_CELL_TEXT_CHARS",
    "MAX_HWPX_PACKAGE_TABLE_CELLS",
    "MAX_HWPX_SECTIONS",
    "HwpxPackageContent",
    "HwpxPackageSection",
    "HwpxPicture",
    "HwpxSectionBlock",
    "HwpxTable",
    "HwpxTableCell",
    "serialize_hwpx_section_blocks",
    "serialize_hwpx_picture_paragraph",
    "deserialize_hwpx_package",
    "serialize_hwpx_package",
    "serialize_hwpx_section_part",
    "validate_hwpx_paragraph_text",
]
