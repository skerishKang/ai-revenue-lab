from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import PurePath, PurePosixPath
from typing import Any
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

from .document_semantics import (
    DOCUMENT_CONTENT_TRUST_CLASS,
    MAX_DOCUMENT_SEGMENTS,
    MAX_SEGMENT_TEXT_CHARS,
    DocumentKind,
    DocumentSegment,
    DocumentNormalizationError,
    ExtractionStatus,
    document_kind_for_media,
    normalize_document_warnings,
)

MAX_DOCUMENT_NAME_CHARS = 120
MAX_DOCUMENT_CHARS = MAX_SEGMENT_TEXT_CHARS
MAX_TEXT_DOCUMENT_BYTES = 96 * 1024
MAX_BINARY_DOCUMENT_BYTES = 2 * 1024 * 1024
#: Largest drawable extent, in HWPUNIT, this Core accepts for a picture block.
#: One HWPUNIT is 1/7200 inch, so this is roughly 138 inches: far beyond any
#: page, and bounded so a caller-supplied size can never inflate the section
#: part without limit.
MAX_HWPX_PICTURE_HWPUNIT = 1_000_000
MAX_PDF_PAGES = 80
MAX_PDF_PAGE_TEXT_CHARS = 16_000
PDF_NATIVE_TEXT_PRESENT = "native_text_present"
PDF_NATIVE_TEXT_ABSENT = "no_native_text_ocr_may_be_required"
MAX_OOXML_ENTRIES = 256
MAX_OOXML_MEMBER_NAME_CHARS = 255
MAX_OOXML_ENTRY_UNCOMPRESSED_BYTES = 1 * 1024 * 1024
MAX_OOXML_TOTAL_UNCOMPRESSED_BYTES = 8 * 1024 * 1024
MAX_XLSX_SHEETS = 20
MAX_XLSX_ROWS = 500
MAX_XLSX_COLUMNS = 50
MAX_XLSX_NONEMPTY_CELLS = 5_000

TEXT_DOCUMENT_MEDIA: dict[str, frozenset[str]] = {
    "text/plain": frozenset({".txt"}),
    "text/markdown": frozenset({".md", ".markdown"}),
    "text/csv": frozenset({".csv"}),
    "application/json": frozenset({".json"}),
}

BINARY_DOCUMENT_MEDIA: dict[str, frozenset[str]] = {
    "application/pdf": frozenset({".pdf"}),
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": frozenset({".docx"}),
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": frozenset({".pptx"}),
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": frozenset({".xlsx"}),
    # LEGACY_HWP_DECISION=UNSUPPORTED: legacy .hwp is an OLE2 compound binary, not a zip
    # container, so no bounded pure-stdlib parser is realistic in this slice; application/x-hwp
    # stays outside every allow-list and fails closed. HWPX below is the OOXML-style zip path.
    "application/hwp+zip": frozenset({".hwpx"}),
}


# ``DocumentNormalizationError`` is defined in ``document_semantics`` and re-exported
# here so both import paths keep resolving to one error type.


@dataclass(frozen=True, slots=True)
class NormalizedDocument:
    """The single canonical normalized-document object in Core.

    Semantic fields (``status``, ``segments``, ``warnings``) are additive and
    backward compatible: every field above was already consumed by products.
    Raw body text never appears in ``repr`` or in the public projection. A
    failed or rejected extraction is always an exception, never an instance.
    """

    name: str
    media_type: str
    text: str = field(repr=False)
    byte_size: int = 0
    source_kind: str = "text"
    status: ExtractionStatus = ExtractionStatus.COMPLETE
    segments: tuple[DocumentSegment, ...] = field(default=(), repr=False)
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.status, ExtractionStatus):
            raise DocumentNormalizationError(
                "invalid_document_status",
                "Document status must be a supported extraction status.",
            )
        if not self.segments and self.text:
            object.__setattr__(
                self,
                "segments",
                (DocumentSegment(text=self.text, order=0),),
            )
        if not isinstance(self.segments, tuple):
            object.__setattr__(self, "segments", tuple(self.segments))
        if any(not isinstance(item, DocumentSegment) for item in self.segments):
            raise DocumentNormalizationError(
                "invalid_document_segments",
                "Document segments must contain DocumentSegment values.",
            )
        if len(self.segments) > MAX_DOCUMENT_SEGMENTS:
            raise DocumentNormalizationError(
                "document_segment_limit",
                "Document segments exceed the bounded count.",
            )
        if sum(item.char_count for item in self.segments) > MAX_DOCUMENT_CHARS:
            raise DocumentNormalizationError(
                "document_segment_budget",
                "Document segments exceed the bounded character budget.",
            )
        orders = tuple(item.order for item in self.segments)
        if len(set(orders)) != len(orders):
            raise DocumentNormalizationError(
                "duplicate_segment_order",
                "Document segment orders must be unique.",
            )
        object.__setattr__(self, "warnings", normalize_document_warnings(self.warnings))
        if self.status is ExtractionStatus.TRUNCATED and not self.warnings:
            raise DocumentNormalizationError(
                "truncation_requires_warning",
                "A truncated document must carry at least one warning identifier.",
            )

    @property
    def kind(self) -> DocumentKind | None:
        """Canonical content kind derived from the validated media identity."""

        return document_kind_for_media(self.media_type)

    @property
    def segment_count(self) -> int:
        return len(self.segments)

    @property
    def text_chars(self) -> int:
        return len(self.text)

    @property
    def truncated(self) -> bool:
        return self.status is ExtractionStatus.TRUNCATED

    @property
    def content_trust_class(self) -> str:
        """Core-fixed classification; can never be set by callers."""

        return DOCUMENT_CONTENT_TRUST_CLASS

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "type": "document",
            "name": self.name,
            "media_type": self.media_type,
            "byte_size": self.byte_size,
            "text_chars": len(self.text),
        }


def normalize_document_name(value: Any) -> str:
    if not isinstance(value, str):
        raise DocumentNormalizationError("invalid_name", "Document name must be a string.")
    cleaned = "".join(ch for ch in value.strip() if ch >= " " and ch != "\x7f")
    if not cleaned:
        raise DocumentNormalizationError("name_required", "Document name is required.")
    return cleaned[:MAX_DOCUMENT_NAME_CHARS]


def _validated_media(name: str, media_type: Any, allowed: dict[str, frozenset[str]], *, kind: str) -> str:
    if not isinstance(media_type, str) or media_type not in allowed:
        raise DocumentNormalizationError(f"unsupported_{kind}_media_type", f"Unsupported {kind} document media type.")
    suffix = PurePath(name.lower()).suffix
    if suffix not in allowed[media_type]:
        raise DocumentNormalizationError("media_extension_mismatch", "Document extension does not match media type.")
    return media_type


def validate_document_identity(*, name: Any, media_type: Any, source_kind: str) -> tuple[str, str]:
    safe_name = normalize_document_name(name)
    if source_kind == "text":
        allowed = TEXT_DOCUMENT_MEDIA
    elif source_kind == "binary":
        allowed = BINARY_DOCUMENT_MEDIA
    else:
        raise DocumentNormalizationError("invalid_source_kind", "Document source kind must be text or binary.")
    return safe_name, _validated_media(safe_name, media_type, allowed, kind=source_kind)


def normalize_document_text(value: Any) -> str:
    if not isinstance(value, str):
        raise DocumentNormalizationError("invalid_text", "Document text must be a string.")
    text = value.removeprefix("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    if not text.strip():
        raise DocumentNormalizationError("empty_document", "Document text is empty.")
    if len(text) > MAX_DOCUMENT_CHARS:
        raise DocumentNormalizationError("text_too_long", "Document text exceeds the character limit.")
    if "\x00" in text:
        raise DocumentNormalizationError("binary_text_rejected", "NUL bytes are not allowed in text documents.")
    bad_controls = sum(1 for ch in text if ord(ch) < 32 and ch not in {"\n", "\t"})
    if bad_controls > max(3, len(text) // 500):
        raise DocumentNormalizationError("excessive_control_characters", "Document contains too many control characters.")
    return text


def normalize_text_document(*, name: Any, media_type: Any, text: Any) -> NormalizedDocument:
    safe_name, safe_media = validate_document_identity(name=name, media_type=media_type, source_kind="text")
    normalized = normalize_document_text(text)
    byte_size = len(normalized.encode("utf-8"))
    if byte_size > MAX_TEXT_DOCUMENT_BYTES:
        raise DocumentNormalizationError("text_bytes_too_large", "Text document exceeds the byte limit.")
    return NormalizedDocument(
        name=safe_name,
        media_type=safe_media,
        text=normalized,
        byte_size=byte_size,
        source_kind="text",
    )


def _append_bounded(parts: list[str], value: str) -> None:
    if not value:
        return
    parts.append(value)
    if sum(len(part) for part in parts) + max(0, len(parts) - 1) > MAX_DOCUMENT_CHARS:
        raise DocumentNormalizationError("extracted_text_too_long", "Extracted document text exceeds the character limit.")


def _safe_ooxml_member(name: str) -> bool:
    if not name or "\\" in name or name.startswith("/") or "//" in name:
        return False
    if len(name) >= 2 and name[1] == ":":
        return False
    parts = PurePosixPath(name).parts
    return all(part not in {"", ".", ".."} for part in parts)


def validate_ooxml_member_name(name: object) -> str:
    """Judge one archive member name with the single path-safety predicate.

    The archive gate already applies this predicate to every member it walks.
    Exposing it lets the package writer apply the same predicate to every member
    it emits, so Core can never write an archive its own gate would refuse, and
    a caller-supplied name never becomes an archive path.
    """

    if not isinstance(name, str) or not name or len(name) > MAX_OOXML_MEMBER_NAME_CHARS:
        raise DocumentNormalizationError(
            "ooxml_unsafe_path",
            "OOXML archive contains an unsafe member path.",
        )
    if not _safe_ooxml_member(name):
        raise DocumentNormalizationError(
            "ooxml_unsafe_path",
            "OOXML archive contains an unsafe member path.",
        )
    return name


def validate_ooxml_archive(payload: bytes) -> None:
    if not isinstance(payload, (bytes, bytearray)) or not payload or len(payload) > MAX_BINARY_DOCUMENT_BYTES:
        raise DocumentNormalizationError("ooxml_archive_size", "OOXML archive size is out of bounds.")
    try:
        with ZipFile(BytesIO(bytes(payload))) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_OOXML_ENTRIES:
                raise DocumentNormalizationError("ooxml_entry_count", "OOXML archive contains too many entries.")
            total = 0
            for info in infos:
                if not _safe_ooxml_member(info.filename):
                    raise DocumentNormalizationError("ooxml_unsafe_path", "OOXML archive contains an unsafe member path.")
                if info.flag_bits & 0x1:
                    raise DocumentNormalizationError("ooxml_encrypted", "Encrypted OOXML entries are not supported.")
                if info.file_size > MAX_OOXML_ENTRY_UNCOMPRESSED_BYTES:
                    raise DocumentNormalizationError("ooxml_entry_size", "OOXML archive entry exceeds the size limit.")
                total += info.file_size
                if total > MAX_OOXML_TOTAL_UNCOMPRESSED_BYTES:
                    raise DocumentNormalizationError("ooxml_total_size", "OOXML archive exceeds the total uncompressed size limit.")
                lowered = info.filename.lower()
                if lowered.endswith(".xml") or lowered.endswith(".rels"):
                    xml = archive.read(info)
                    if b"<!doctype" in xml.lower():
                        raise DocumentNormalizationError("ooxml_dtd_rejected", "DTDs are not supported in OOXML documents.")
    except DocumentNormalizationError:
        raise
    except (BadZipFile, OSError, ValueError, RuntimeError) as exc:
        raise DocumentNormalizationError("ooxml_malformed", "Malformed OOXML ZIP archive.") from exc


def _parse_xml(xml: bytes) -> ElementTree.Element:
    if b"<!doctype" in xml.lower():
        raise DocumentNormalizationError("ooxml_dtd_rejected", "DTDs are not supported in OOXML documents.")
    try:
        return ElementTree.fromstring(xml)
    except ElementTree.ParseError as exc:
        raise DocumentNormalizationError("ooxml_invalid_xml", "Invalid OOXML XML part.") from exc


def _local_name(element: ElementTree.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def extract_docx_text(payload: bytes) -> str:
    validate_ooxml_archive(payload)
    try:
        with ZipFile(BytesIO(payload)) as archive:
            try:
                root = _parse_xml(archive.read("word/document.xml"))
            except KeyError as exc:
                raise DocumentNormalizationError("docx_missing_part", "DOCX is missing word/document.xml.") from exc
    except DocumentNormalizationError:
        raise
    except (BadZipFile, OSError, ValueError, RuntimeError) as exc:
        raise DocumentNormalizationError("ooxml_malformed", "Malformed OOXML ZIP archive.") from exc

    paragraphs: list[str] = []
    for paragraph in root.iter():
        if _local_name(paragraph) != "p":
            continue
        pieces = [node.text or "" for node in paragraph.iter() if _local_name(node) == "t"]
        value = "".join(pieces)
        if value:
            _append_bounded(paragraphs, value)
    text = "\n".join(paragraphs).strip()
    if not text:
        raise DocumentNormalizationError("docx_empty", "DOCX contains no readable text.")
    return text


def _slide_sort_key(name: str) -> tuple[int, str]:
    stem = PurePosixPath(name).stem
    suffix = stem.removeprefix("slide")
    return (int(suffix) if suffix.isdigit() else 10**9, name)


def extract_pptx_text(payload: bytes) -> str:
    validate_ooxml_archive(payload)
    try:
        with ZipFile(BytesIO(payload)) as archive:
            slide_names = sorted(
                (
                    name
                    for name in archive.namelist()
                    if name.startswith("ppt/slides/slide") and name.endswith(".xml") and "/_rels/" not in name
                ),
                key=_slide_sort_key,
            )
            if not slide_names:
                raise DocumentNormalizationError("pptx_missing_slides", "PPTX contains no slide XML parts.")
            slides: list[str] = []
            for slide_name in slide_names:
                root = _parse_xml(archive.read(slide_name))
                pieces = [node.text or "" for node in root.iter() if _local_name(node) == "t"]
                slide = "\n".join(piece for piece in pieces if piece).strip()
                if slide:
                    _append_bounded(slides, slide)
    except DocumentNormalizationError:
        raise
    except (BadZipFile, OSError, ValueError, RuntimeError) as exc:
        raise DocumentNormalizationError("ooxml_malformed", "Malformed OOXML ZIP archive.") from exc
    text = "\n".join(slides).strip()
    if not text:
        raise DocumentNormalizationError("pptx_empty", "PPTX contains no readable text.")
    return text


def _hwpx_section_index(name: str) -> int | None:
    path = PurePosixPath(name)
    if path.parent.as_posix() != "Contents" or not name.endswith(".xml"):
        return None
    digits = path.stem.removeprefix("section")
    return int(digits) if digits.isdigit() else None


# Public name for the single HWPX section-member naming rule. A
# package-preserving mutator locates a section part with the reader's own
# predicate instead of restating the rule, so the two can never disagree about
# which member a section index refers to.
hwpx_section_index = _hwpx_section_index


# The legacy public projection recognizes only paragraph/run/text nodes. The
# structured decoder separately recognizes bounded table nodes through the
# ordered fact layer below.
_HWPX_CANONICAL_LOCAL_NAMES = frozenset({"p", "runs", "t"})


@dataclass(frozen=True, slots=True)
class HwpxParsedParagraph:
    """One parsed paragraph element and the structural facts about it.

    ``text`` is the same value the flat authority has always produced: every
    text node under the paragraph joined in document order. ``text_nodes`` and
    ``holds_nested_paragraph`` say how much shape that join hid, so a caller
    that needs lossless structure can refuse instead of trusting a flattened
    string.
    """

    text: str
    text_nodes: int
    holds_nested_paragraph: bool


@dataclass(frozen=True, slots=True)
class HwpxParsedCellParagraph:
    """Lossless shape facts for one paragraph inside a table cell."""

    text: str
    text_nodes: int
    runs: int
    text_form: str


@dataclass(frozen=True, slots=True)
class HwpxParsedTableCell:
    """One table cell in source order."""

    paragraphs: tuple[HwpxParsedCellParagraph, ...]
    unsupported: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class HwpxParsedTable:
    """One table fact with row-major order retained."""

    rows: tuple[tuple[HwpxParsedTableCell, ...], ...]
    unsupported: tuple[str, ...]


#: The exact ``hp:pic`` child set Core's single section producer emits, in
#: order. The reader recognizes a picture only when this is its child sequence,
#: so the read shape and the write shape are one contract expressed once here.
#: A real Hancom picture carries more (``flip``, ``rotationInfo``,
#: ``renderingInfo``, populated ``effects``); such a picture is deliberately
#: *not* recognized, and therefore still fails the writable-subset gate.
HWPX_PICTURE_CHILD_NAMES = (
    "offset",
    "orgSz",
    "curSz",
    "sz",
    "pos",
    "imgRect",
    "imgClip",
    "inMargin",
    "imgDim",
    "img",
    "effects",
    "outMargin",
    "shapeComment",
)

#: Local names a recognized picture block is allowed to contain anywhere below
#: its own paragraph. Anything else under the picture counts as unsupported.
_HWPX_PICTURE_LOCAL_NAMES = frozenset(
    {"pic", "runs", "run", "t", "pt0", "pt1", "pt2", "pt3"}
).union(HWPX_PICTURE_CHILD_NAMES)

#: The binary-item id grammar this reader accepts: the deterministic
#: ``BIN####`` shape the image authority allocates. A manifest may legitimately
#: carry other ids, so this bounds what the *writable picture subset* claims
#: rather than what a package may contain. The length is ``BIN`` plus exactly
#: four decimal digits, so a five-digit id is as much a different shape as a
#: three-digit one.
_HWPX_BINARY_ITEM_ID_MAX_CHARS = 7


def is_hwpx_binary_item_id(value: object) -> bool:
    """Whether a value has the deterministic ``BIN####`` id shape."""

    if not isinstance(value, str) or len(value) != _HWPX_BINARY_ITEM_ID_MAX_CHARS:
        return False
    if not value.startswith("BIN") or not value[3:].isdigit():
        return False
    # ``str.isdigit`` also accepts non-ASCII digits, which are not the ASCII
    # decimal the allocator emits and would not match a member name.
    return all(character in "0123456789" for character in value[3:])


@dataclass(frozen=True, slots=True)
class HwpxParsedPicture:
    """One recognized ``hp:pic``/``hc:img`` reference and its draw extent.

    ``binary_item_id_ref`` is the ``hc:img/@binaryItemIDRef`` value, which names
    a manifest item rather than a ZIP member: resolving it is a manifest lookup,
    not a path authority. ``width_hwpunit``/``height_hwpunit`` are the HWPUNIT
    draw size. ``unsupported`` lists every deviation that makes this picture
    outside the writable subset, so a caller can refuse instead of rewriting a
    shape the model does not own.
    """

    binary_item_id_ref: str
    width_hwpunit: int
    height_hwpunit: int
    unsupported: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class HwpxSectionBlockFact:
    """One ordered direct section block: paragraph, table or picture."""

    kind: str
    paragraph: HwpxParsedParagraph | None = None
    table: HwpxParsedTable | None = None
    picture: HwpxParsedPicture | None = None


@dataclass(frozen=True, slots=True)
class HwpxSectionBlockFacts:
    """Internal fact projection created during the one HWPX parse."""

    index: int
    root_tag: str
    unsupported_nodes: int
    has_carriage_return: bool
    blocks: tuple[HwpxSectionBlockFact, ...]
    paragraphs: tuple[HwpxParsedParagraph, ...]
    structured_unsupported_nodes: int = 0
    legacy_unsupported_nodes: int = 0


_HWPX_SECTION_FACTS: ContextVar[tuple[HwpxSectionBlockFacts, ...] | None] = ContextVar(
    "hwpx_section_facts",
    default=None,
)


def _last_hwpx_section_facts() -> tuple[HwpxSectionBlockFacts, ...] | None:
    """Return facts from the parse that produced the last public projection."""

    return _HWPX_SECTION_FACTS.get()


def read_hwpx_section_facts(payload: bytes) -> tuple[HwpxSectionBlockFacts, ...]:
    """Return the ordered structured facts of one HWPX package.

    This is the public door onto the same single archive-and-XML walk that
    produces :func:`parse_hwpx_sections`' projection: it calls that function and
    then returns the facts the walk already computed, so a caller that needs
    picture/table shape opens no second archive and parses no second XML. The
    length check is the same integrity condition
    :func:`padiem_ai_core.hwpx_package_serializer.deserialize_hwpx_package`
    applies before trusting the side channel.
    """

    sections = parse_hwpx_sections(payload)
    facts = _last_hwpx_section_facts()
    if facts is None or len(facts) != len(sections):
        raise DocumentNormalizationError(
            "hwpx_missing_part",
            "HWPX structured facts are unavailable.",
        )
    return facts


@dataclass(frozen=True, slots=True)
class HwpxParsedSection:
    """One located section part, in numeric section order.

    ``index`` is the ``Contents/section<N>.xml`` number and ``root_tag`` the
    parsed element's namespace-qualified tag. ``unsupported_nodes`` counts the
    elements in the part that fall outside the section/paragraph/run/text shape
    this Core subset owns — over the whole part, so a table or image is visible
    wherever it sits, not only when it hides inside a paragraph.
    ``has_carriage_return`` says whether the raw part held a ``0x0D`` byte: an
    XML parser normalizes that to a newline, so a paragraph's exact text cannot
    be recovered from the parsed tree alone and must be judged from the part it
    came from.
    """

    index: int
    root_tag: str
    unsupported_nodes: int
    has_carriage_return: bool
    paragraphs: tuple[HwpxParsedParagraph, ...]


def _paragraph_fact(paragraph: ElementTree.Element) -> HwpxParsedParagraph:
    descendants = list(paragraph.iter())
    text_nodes = [node for node in descendants if _local_name(node) == "t"]
    return HwpxParsedParagraph(
        text="".join(node.text or "" for node in text_nodes),
        text_nodes=len(text_nodes),
        holds_nested_paragraph=any(node is not paragraph and _local_name(node) == "p" for node in descendants),
    )


def _cell_paragraph_fact(paragraph: ElementTree.Element) -> HwpxParsedCellParagraph:
    fact = _paragraph_fact(paragraph)
    runs = sum(1 for node in paragraph.iter() if _local_name(node) == "runs")
    if fact.text_nodes == 0:
        text_form = "no_text"
    elif fact.text_nodes == 1 and not fact.text:
        text_form = "empty_text"
    elif fact.text_nodes == 1:
        text_form = "non_empty_text"
    else:
        text_form = "multiple_text_nodes"
    return HwpxParsedCellParagraph(fact.text, fact.text_nodes, runs, text_form)


def _attribute_local_name(name: str) -> str:
    return name.rsplit("}", 1)[-1].lower()


def _table_fact(table: ElementTree.Element) -> HwpxParsedTable:
    unsupported: list[str] = []
    if any(node is not table and _local_name(node) == "tbl" for node in table.iter()):
        unsupported.append("nested_table")
    rows: list[tuple[HwpxParsedTableCell, ...]] = []
    for row in table:
        if _local_name(row) != "tr":
            if _local_name(row) not in {"tbl", "p", "runs", "t"}:
                unsupported.append(f"table_child:{_local_name(row)}")
            continue
        cells: list[HwpxParsedTableCell] = []
        for cell in row:
            if _local_name(cell) != "tc":
                unsupported.append(f"row_child:{_local_name(cell)}")
                continue
            cell_unsupported: list[str] = []
            attrs = {_attribute_local_name(name) for name in (*row.attrib, *cell.attrib)}
            if attrs & {"rowspan", "colspan", "gridspan", "colindex", "rowindex"}:
                cell_unsupported.append("merged_or_spanned")
            paragraphs = tuple(_cell_paragraph_fact(node) for node in cell.iter() if _local_name(node) == "p")
            for node in cell.iter():
                local = _local_name(node)
                if local in {"tbl", "img", "pic", "drawing", "draw", "gm", "container", "rect", "ole"}:
                    cell_unsupported.append(local)
            cells.append(HwpxParsedTableCell(paragraphs, tuple(dict.fromkeys(cell_unsupported))))
        rows.append(tuple(cells))
    return HwpxParsedTable(tuple(rows), tuple(dict.fromkeys(unsupported)))


def _bounded_hwpunit(value: str | None) -> int | None:
    """Read one positive decimal HWPUNIT attribute, or refuse it as absent."""

    if value is None or not value.isdigit() or not all(c in "0123456789" for c in value):
        return None
    extent = int(value)
    return extent if 0 < extent <= MAX_HWPX_PICTURE_HWPUNIT else None


def _picture_fact(paragraph: ElementTree.Element) -> HwpxParsedPicture | None:
    """Recognize Core's own bounded picture shape, or report the deviation.

    A paragraph is a picture block only when it holds exactly one ``hp:pic``
    whose child sequence, attributes and ``hc:img/@binaryItemIDRef`` are exactly
    the ones the single section producer emits. A picture that differs in any
    way is still reported — with every deviation named in ``unsupported`` — so
    the writable-subset decoder refuses it instead of silently dropping a shape
    the model does not own. ``None`` means the paragraph holds no picture at
    all, which is an ordinary paragraph.
    """

    pictures = [node for node in paragraph.iter() if _local_name(node) == "pic"]
    if not pictures:
        return None

    unsupported: list[str] = []
    if len(pictures) > 1:
        unsupported.append("multiple_pictures")
    picture = pictures[0]

    if _local_name(paragraph) != "p":  # pragma: no cover - callers pass a paragraph
        unsupported.append("picture_outside_paragraph")
    # A picture block owns its whole paragraph: a picture sharing a paragraph
    # with a text run is a shape the model does not own.
    if any(_local_name(node) == "t" for node in paragraph.iter() if node is not picture):
        unsupported.append("picture_shares_paragraph_with_text")

    child_names = tuple(_local_name(node) for node in picture)
    if child_names != HWPX_PICTURE_CHILD_NAMES:
        unsupported.append("picture_children:" + ",".join(child_names))
    for node in picture.iter():
        if node is not picture and _local_name(node) not in _HWPX_PICTURE_LOCAL_NAMES:
            unsupported.append(f"picture_descendant:{_local_name(node)}")
    if len(list(picture)) != len(HWPX_PICTURE_CHILD_NAMES):
        unsupported.append("picture_child_count")

    sizes: dict[str, tuple[int | None, int | None]] = {}
    for name in ("orgSz", "curSz", "sz"):
        holder = next((node for node in picture if _local_name(node) == name), None)
        width = _bounded_hwpunit(None if holder is None else holder.get("width"))
        height = _bounded_hwpunit(None if holder is None else holder.get("height"))
        if width is None or height is None:
            unsupported.append(f"picture_{name}_invalid")
        sizes[name] = (width, height)
    org_size, cur_size, draw_size = sizes["orgSz"], sizes["curSz"], sizes["sz"]
    if None not in org_size and org_size != cur_size:
        unsupported.append("picture_org_cur_size_mismatch")
    if None not in cur_size and cur_size != draw_size:
        unsupported.append("picture_cur_draw_size_mismatch")

    image = next((node for node in picture if _local_name(node) == "img"), None)
    reference = "" if image is None else (image.get("binaryItemIDRef") or "").strip()
    if not is_hwpx_binary_item_id(reference):
        unsupported.append("picture_binary_item_id_ref")

    width, height = draw_size
    return HwpxParsedPicture(
        binary_item_id_ref=reference,
        width_hwpunit=width or 0,
        height_hwpunit=height or 0,
        unsupported=tuple(dict.fromkeys(unsupported)),
    )


def _ordered_section_block_facts(*, index: int, root: ElementTree.Element, part: bytes) -> HwpxSectionBlockFacts:
    nodes = list(root.iter())
    legacy = tuple(_paragraph_fact(node) for node in nodes if _local_name(node) == "p")
    blocks: list[HwpxSectionBlockFact] = []
    # Node identities covered by a *recognized* picture. A recognized picture is
    # part of the writable subset, so its own nodes must not be counted as
    # unsupported structure; an unrecognized picture contributes no ids here and
    # is therefore still counted and refused.
    picture_node_ids: set[int] = set()
    for child in root:
        local = _local_name(child)
        if local == "p":
            picture = _picture_fact(child)
            if picture is None:
                blocks.append(HwpxSectionBlockFact("paragraph", paragraph=_paragraph_fact(child)))
                continue
            blocks.append(HwpxSectionBlockFact("picture", picture=picture))
            if not picture.unsupported:
                picture_node_ids.update(id(node) for node in child.iter())
        elif local == "tbl":
            blocks.append(HwpxSectionBlockFact("table", table=_table_fact(child)))
    return HwpxSectionBlockFacts(
        index=index,
        root_tag=root.tag,
        unsupported_nodes=sum(1 for node in nodes if node is not root and _local_name(node) not in _HWPX_CANONICAL_LOCAL_NAMES),
        has_carriage_return=13 in part,
        blocks=tuple(blocks),
        paragraphs=legacy,
        structured_unsupported_nodes=sum(
            1
            for node in nodes
            if node is not root
            and _local_name(node) not in {"p", "runs", "t", "tbl", "tr", "tc"}
            and id(node) not in picture_node_ids
        ),
        legacy_unsupported_nodes=sum(
            1
            for node in nodes
            if node is not root and _local_name(node) not in {"p", "runs", "t"}
        ),
    )


def parse_hwpx_sections(payload: bytes) -> tuple[HwpxParsedSection, ...]:
    """Parse one HWPX package and return the stable paragraph projection.

    The ordered structured facts from the same archive walk are retained in a
    private context-local side channel. The decoder reads them immediately after
    this call, so both projections remain based on exactly one parse without
    adding fields to the public result type.
    """

    validate_ooxml_archive(payload)
    sections: list[HwpxParsedSection] = []
    fact_sections: list[HwpxSectionBlockFacts] = []
    try:
        with ZipFile(BytesIO(payload)) as archive:
            names = archive.namelist()
            if "mimetype" in names:
                declared = archive.read("mimetype").decode("utf-8", "replace").strip()
                if declared != "application/hwp+zip":
                    raise DocumentNormalizationError(
                        "hwpx_mimetype_mismatch",
                        "HWPX mimetype entry does not match the declared media type.",
                    )
            located = [(index, name) for name in names if (index := _hwpx_section_index(name)) is not None]
            if not located:
                raise DocumentNormalizationError("hwpx_missing_part", "HWPX is missing Contents/section<N>.xml parts.")
            for index, section_name in sorted(located):
                part = archive.read(section_name)
                root = _parse_xml(part)
                facts = _ordered_section_block_facts(index=index, root=root, part=part)
                fact_sections.append(facts)
                sections.append(
                    HwpxParsedSection(
                        index=facts.index,
                        root_tag=facts.root_tag,
                        unsupported_nodes=facts.legacy_unsupported_nodes,
                        has_carriage_return=facts.has_carriage_return,
                        paragraphs=facts.paragraphs,
                    )
                )
    except DocumentNormalizationError:
        raise
    except (BadZipFile, OSError, ValueError, RuntimeError) as exc:
        raise DocumentNormalizationError("ooxml_malformed", "Malformed OOXML ZIP archive.") from exc
    _HWPX_SECTION_FACTS.set(tuple(fact_sections))
    return tuple(sections)


def extract_hwpx_text(payload: bytes) -> str:
    """Flatten an HWPX package to text, unchanged from its pre-factoring shape.

    Nested paragraph holders stay skipped, paragraphs and empty sections are
    dropped, and the same character budget applies, so every accepted fixture
    keeps producing byte-identical text while the walk itself now lives in
    :func:`parse_hwpx_sections`.
    """

    sections: list[str] = []
    for parsed in parse_hwpx_sections(payload):
        paragraphs: list[str] = []
        for paragraph in parsed.paragraphs:
            if paragraph.holds_nested_paragraph:
                continue
            _append_bounded(paragraphs, paragraph.text)
        section = "\n".join(paragraphs).strip()
        if section:
            _append_bounded(sections, section)
    text = "\n".join(sections).strip()
    if not text:
        raise DocumentNormalizationError("hwpx_empty", "HWPX contains no readable text.")
    return text


@dataclass(frozen=True, slots=True)
class HwpxPackageMember:
    """One raw archive member of an already admitted HWPX package.

    ``payload`` is the member's decompressed bytes exactly as the archive holds
    them, kept out of ``repr`` so a package's content never leaks through a
    log or an error. The name is the archive's own member name: it is never
    supplied by a caller and is never projected back to one.
    """

    name: str
    payload: bytes = field(repr=False)


def read_hwpx_package_members(payload: bytes) -> tuple[HwpxPackageMember, ...]:
    """Read every member of an admitted HWPX package, in archive order.

    This is the raw-member accessor of Core's single HWPX archive authority.
    It runs the same :func:`validate_ooxml_archive` gate every other HWPX read
    runs — so path traversal, entry count, per-entry and total size, encryption
    and DTD policy are decided in exactly one place — and then returns each
    member's decompressed bytes without parsing any XML and without
    interpreting any member's content.

    It exists for one purpose: a package-preserving mutator has to copy the
    members it does not understand byte-for-byte rather than project them
    through a model that would silently drop their shape. Reading by
    ``ZipInfo`` (not by name) keeps duplicate names distinguishable, so the
    caller can preserve an archive's member sequence exactly.
    """

    validate_ooxml_archive(payload)
    members: list[HwpxPackageMember] = []
    try:
        with ZipFile(BytesIO(bytes(payload))) as archive:
            for info in archive.infolist():
                members.append(HwpxPackageMember(name=info.filename, payload=archive.read(info)))
    except DocumentNormalizationError:
        raise
    except (BadZipFile, OSError, ValueError, RuntimeError) as exc:
        raise DocumentNormalizationError("ooxml_malformed", "Malformed OOXML ZIP archive.") from exc
    return tuple(members)


@dataclass(frozen=True, slots=True)
class PdfPageInspection:
    """Native page text with exact page provenance; no OCR or layout authority."""

    page_index: int
    page_number: int
    page_count: int
    text: str
    text_source: str = "native_pypdf"

    def safe_dict(self) -> dict[str, object]:
        return {
            "page_index": self.page_index,
            "page_number": self.page_number,
            "page_count": self.page_count,
            "text": self.text,
            "text_source": self.text_source,
        }


@dataclass(frozen=True, slots=True)
class PdfInspection:
    """Bounded PDF inspection result using the canonical Core pypdf authority."""

    name: str
    media_type: str
    byte_size: int
    page_count: int
    pages: tuple[PdfPageInspection, ...]
    native_text_available: bool
    native_text_state: str

    def safe_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "media_type": self.media_type,
            "byte_size": self.byte_size,
            "page_count": self.page_count,
            "native_text_available": self.native_text_available,
            "native_text_state": self.native_text_state,
            "pages": [page.safe_dict() for page in self.pages],
        }


def _open_pdf_reader(payload: bytes) -> Any:
    if not payload.startswith(b"%PDF-"):
        raise DocumentNormalizationError("pdf_magic_mismatch", "PDF magic does not match the declared media type.")
    try:
        from pypdf import PdfReader
    except ModuleNotFoundError as exc:
        raise DocumentNormalizationError("document_dependency_unavailable", "PDF extraction dependency is unavailable.") from exc
    try:
        reader = PdfReader(BytesIO(payload), strict=True)
    except Exception as exc:
        raise DocumentNormalizationError("pdf_invalid", "PDF could not be parsed safely.") from exc
    if reader.is_encrypted:
        raise DocumentNormalizationError("pdf_encrypted", "Encrypted PDF documents are not supported.")
    if len(reader.pages) < 1:
        raise DocumentNormalizationError("pdf_no_pages", "PDF contains no readable pages.")
    if len(reader.pages) > MAX_PDF_PAGES:
        raise DocumentNormalizationError("pdf_page_limit", "PDF exceeds the page limit.")
    return reader


def inspect_pdf(*, name: Any, media_type: Any, payload: Any) -> PdfInspection:
    """Inspect PDF metadata and native page text through the canonical pypdf reader."""
    safe_name, safe_media = validate_document_identity(name=name, media_type=media_type, source_kind="binary")
    if safe_media != "application/pdf":
        raise DocumentNormalizationError("unsupported_binary_media_type", "Unsupported binary document media type.")
    if not isinstance(payload, (bytes, bytearray)) or not payload:
        raise DocumentNormalizationError("invalid_binary_payload", "PDF payload must be non-empty bytes.")
    binary = bytes(payload)
    if len(binary) > MAX_BINARY_DOCUMENT_BYTES:
        raise DocumentNormalizationError("binary_too_large", "Binary document exceeds the byte limit.")
    reader = _open_pdf_reader(binary)
    try:
        page_count = len(reader.pages)
        pages: list[PdfPageInspection] = []
        for index, page in enumerate(reader.pages):
            try:
                text = (page.extract_text() or "").strip()
            except Exception as exc:
                raise DocumentNormalizationError("pdf_page_text_invalid", "PDF page text could not be read safely.") from exc
            if len(text) > MAX_PDF_PAGE_TEXT_CHARS:
                raise DocumentNormalizationError("pdf_page_text_limit", "PDF page text exceeds the character limit.")
            pages.append(PdfPageInspection(index, index + 1, page_count, text))
    finally:
        reader.close() if hasattr(reader, "close") else None
    native_text_available = any(page.text for page in pages)
    native_text_state = (
        PDF_NATIVE_TEXT_PRESENT if native_text_available else PDF_NATIVE_TEXT_ABSENT
    )
    return PdfInspection(
        name=safe_name,
        media_type=safe_media,
        byte_size=len(binary),
        page_count=page_count,
        pages=tuple(pages),
        native_text_available=native_text_available,
        native_text_state=native_text_state,
    )


def _extract_pdf_text(payload: bytes) -> str:
    reader = _open_pdf_reader(payload)
    try:
        parts: list[str] = []
        for page in reader.pages:
            extracted = (page.extract_text() or "").strip()
            if extracted:
                _append_bounded(parts, extracted)
        text = "\n\n".join(parts).strip()
        if not text:
            raise DocumentNormalizationError("pdf_empty_text", "PDF contains no extractable text; OCR is not enabled.")
        return text
    except DocumentNormalizationError:
        raise
    except Exception as exc:
        raise DocumentNormalizationError("pdf_invalid", "PDF could not be parsed safely.") from exc
    finally:
        reader.close() if hasattr(reader, "close") else None


def _cell_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    return str(value)


def _extract_xlsx_text(payload: bytes) -> str:
    validate_ooxml_archive(payload)
    try:
        from openpyxl import load_workbook
    except ModuleNotFoundError as exc:
        raise DocumentNormalizationError("document_dependency_unavailable", "XLSX extraction dependency is unavailable.") from exc
    try:
        workbook = load_workbook(BytesIO(payload), read_only=True, data_only=True, keep_links=False)
    except Exception as exc:
        raise DocumentNormalizationError("xlsx_invalid", "XLSX could not be parsed safely.") from exc
    try:
        if len(workbook.sheetnames) < 1:
            raise DocumentNormalizationError("xlsx_no_sheets", "XLSX contains no worksheets.")
        if len(workbook.sheetnames) > MAX_XLSX_SHEETS:
            raise DocumentNormalizationError("xlsx_sheet_limit", "XLSX exceeds the worksheet limit.")
        parts: list[str] = []
        nonempty_cells = 0
        for worksheet in workbook.worksheets:
            max_row = int(worksheet.max_row or 0)
            max_column = int(worksheet.max_column or 0)
            if max_row > MAX_XLSX_ROWS or max_column > MAX_XLSX_COLUMNS:
                raise DocumentNormalizationError("xlsx_dimension_limit", "XLSX worksheet dimensions exceed the allowed range.")
            for row in worksheet.iter_rows(max_row=min(max_row, MAX_XLSX_ROWS), max_col=min(max_column, MAX_XLSX_COLUMNS)):
                for cell in row:
                    value = _cell_text(cell.value)
                    if not value:
                        continue
                    nonempty_cells += 1
                    if nonempty_cells > MAX_XLSX_NONEMPTY_CELLS:
                        raise DocumentNormalizationError("xlsx_cell_limit", "XLSX contains too many non-empty cells.")
                    _append_bounded(parts, f"[{worksheet.title}!{cell.coordinate}] {value}")
        text = "\n".join(parts).strip()
        if not text:
            raise DocumentNormalizationError("xlsx_empty", "XLSX contains no readable values.")
        return text
    finally:
        workbook.close()


def extract_binary_document(*, name: Any, media_type: Any, payload: Any) -> NormalizedDocument:
    safe_name, safe_media = validate_document_identity(name=name, media_type=media_type, source_kind="binary")
    if not isinstance(payload, (bytes, bytearray)):
        raise DocumentNormalizationError("invalid_binary_payload", "Binary document payload must be bytes.")
    binary = bytes(payload)
    if not binary:
        raise DocumentNormalizationError("empty_document", "Document payload is empty.")
    if len(binary) > MAX_BINARY_DOCUMENT_BYTES:
        raise DocumentNormalizationError("binary_too_large", "Binary document exceeds the byte limit.")

    if safe_media == "application/pdf":
        text = _extract_pdf_text(binary)
    elif safe_media == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        text = extract_docx_text(binary)
    elif safe_media == "application/vnd.openxmlformats-officedocument.presentationml.presentation":
        text = extract_pptx_text(binary)
    elif safe_media == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":
        text = _extract_xlsx_text(binary)
    elif safe_media == "application/hwp+zip":
        text = extract_hwpx_text(binary)
    else:  # pragma: no cover - guarded by media validation
        raise DocumentNormalizationError("unsupported_binary_media_type", "Unsupported binary document media type.")

    normalized = normalize_document_text(text)
    return NormalizedDocument(
        name=safe_name,
        media_type=safe_media,
        text=normalized,
        byte_size=len(binary),
        source_kind="binary",
    )
