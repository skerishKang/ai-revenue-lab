"""Bounded deterministic structured PDF authoring over ReportLab."""

from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any
from xml.sax.saxutils import escape

from .document_normalization import (
    MAX_BINARY_DOCUMENT_BYTES,
    DocumentNormalizationError,
)
from .image_helpers import ImageContractError, inspect_image, thumbnail_image

PDF_AUTHORING_SCOPE = "bounded_structured_supported_corpus"
PDF_AUTHORING_ENGINE = "reportlab"
PDF_AUTHORING_ENGINE_VERSION = "5.0.1"
PDF_AUTHORING_FONT_NAME = "PadiemNotoSansKRAuthoringTest"
PDF_AUTHORING_FONT_FAMILY = "Padiem Noto Sans KR Authoring Test"
PDF_AUTHORING_FONT_LICENSE = "OFL-1.1"
PDF_AUTHORING_FONT_SHA256 = (
    "6167552e625694a57d20b2d5ba69a2c9db60a4d8b2a4488959ecace4e200678b"
)
PDF_AUTHORING_FONT_BYTES = 62_604
MAX_PDF_AUTHORING_BLOCKS = 128
MAX_PDF_AUTHORING_TEXT_CHARS = 65_536
MAX_PDF_AUTHORING_BLOCK_TEXT_CHARS = 8_192
MAX_PDF_AUTHORING_TABLE_ROWS = 64
MAX_PDF_AUTHORING_TABLE_COLUMNS = 12
MAX_PDF_AUTHORING_TABLE_CELLS = 768
MAX_PDF_AUTHORING_IMAGES = 16
MAX_PDF_AUTHORING_TOTAL_IMAGE_BYTES = 8 * 1024 * 1024
MAX_PDF_AUTHORING_IMAGE_EDGE = 2048
MAX_PDF_AUTHORING_PAGES = 32
MAX_PDF_AUTHORING_OUTPUT_BYTES = MAX_BINARY_DOCUMENT_BYTES
PDF_AUTHORING_ACTIVE_CONTENT_POLICY = "forbidden"
PDF_AUTHORING_EXTERNAL_URI_FETCH = 0
PDF_AUTHORING_EMBEDDED_SCRIPT_EXECUTION = 0

_FONT_LOCK = threading.Lock()


def _error(code: str, message: str) -> DocumentNormalizationError:
    return DocumentNormalizationError(code, message)


def _normalize_text(
    value: object, *, field_name: str, maximum: int, required: bool
) -> str:
    if not isinstance(value, str):
        raise _error(
            "pdf_authoring_text_invalid", f"PDF authoring {field_name} must be text."
        )
    normalized = (
        value.replace("\r\n", "\n").replace("\r", "\n").replace("\t", " ").strip()
    )
    if required and not normalized:
        raise _error(
            "pdf_authoring_text_invalid",
            f"PDF authoring {field_name} must not be empty.",
        )
    if len(normalized) > maximum:
        raise _error(
            "pdf_authoring_text_limit", f"PDF authoring {field_name} exceeds its limit."
        )
    return normalized


@dataclass(frozen=True, slots=True)
class PdfAuthoringMetadata:
    title: str
    author: str = ""
    subject: str = ""
    keywords: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        title = _normalize_text(
            self.title,
            field_name="title",
            maximum=512,
            required=True,
        )
        author = _normalize_text(
            self.author,
            field_name="author",
            maximum=512,
            required=False,
        )
        subject = _normalize_text(
            self.subject,
            field_name="subject",
            maximum=512,
            required=False,
        )
        if not isinstance(self.keywords, tuple) or len(self.keywords) > 16:
            raise _error(
                "pdf_authoring_metadata_invalid",
                "PDF authoring keywords must be a bounded tuple.",
            )
        keywords = tuple(
            _normalize_text(
                value,
                field_name="keyword",
                maximum=64,
                required=True,
            )
            for value in self.keywords
        )
        if len(set(keywords)) != len(keywords):
            raise _error(
                "pdf_authoring_metadata_invalid",
                "PDF authoring keywords must be unique.",
            )
        if sum(map(len, (title, author, subject, *keywords))) > 2048:
            raise _error(
                "pdf_authoring_metadata_limit",
                "PDF authoring metadata exceeds its limit.",
            )
        object.__setattr__(self, "title", title)
        object.__setattr__(self, "author", author)
        object.__setattr__(self, "subject", subject)
        object.__setattr__(self, "keywords", keywords)

    def safe_dict(self) -> dict[str, object]:
        return {
            "title": self.title,
            "author": self.author,
            "subject": self.subject,
            "keywords": list(self.keywords),
        }


@dataclass(frozen=True, slots=True)
class PdfAuthoringFont:
    data: bytes = field(repr=False)
    family: str = PDF_AUTHORING_FONT_FAMILY
    license: str = PDF_AUTHORING_FONT_LICENSE

    def __post_init__(self) -> None:
        if not isinstance(self.data, bytes) or not self.data:
            raise _error(
                "pdf_authoring_font_invalid", "PDF authoring font must be bytes."
            )
        if len(self.data) != PDF_AUTHORING_FONT_BYTES:
            raise _error(
                "pdf_authoring_font_limit", "PDF authoring font size is not approved."
            )
        if (
            self.family != PDF_AUTHORING_FONT_FAMILY
            or self.license != PDF_AUTHORING_FONT_LICENSE
        ):
            raise _error(
                "pdf_authoring_font_unapproved",
                "PDF authoring font identity is not approved.",
            )
        if hashlib.sha256(self.data).hexdigest() != PDF_AUTHORING_FONT_SHA256:
            raise _error(
                "pdf_authoring_font_unapproved",
                "PDF authoring font digest is not approved.",
            )

    @property
    def size_bytes(self) -> int:
        return len(self.data)

    @property
    def sha256(self) -> str:
        return PDF_AUTHORING_FONT_SHA256

    def safe_dict(self) -> dict[str, object]:
        return {
            "family": self.family,
            "license": self.license,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "embedded": True,
        }


@dataclass(frozen=True, slots=True)
class PdfHeadingBlock:
    text: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "text",
            _normalize_text(
                self.text,
                field_name="heading",
                maximum=MAX_PDF_AUTHORING_BLOCK_TEXT_CHARS,
                required=True,
            ),
        )

    @property
    def kind(self) -> str:
        return "heading"


@dataclass(frozen=True, slots=True)
class PdfTextBlock:
    text: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "text",
            _normalize_text(
                self.text,
                field_name="text",
                maximum=MAX_PDF_AUTHORING_BLOCK_TEXT_CHARS,
                required=True,
            ),
        )

    @property
    def kind(self) -> str:
        return "text"


@dataclass(frozen=True, slots=True)
class PdfTableBlock:
    rows: tuple[tuple[str, ...], ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.rows, tuple)
            or not self.rows
            or len(self.rows) > MAX_PDF_AUTHORING_TABLE_ROWS
        ):
            raise _error(
                "pdf_authoring_table_invalid", "PDF authoring table rows are invalid."
            )
        normalized_rows: list[tuple[str, ...]] = []
        for row in self.rows:
            if not isinstance(row, tuple) or not row:
                raise _error(
                    "pdf_authoring_table_invalid",
                    "PDF authoring table row is invalid.",
                )
            if len(row) > MAX_PDF_AUTHORING_TABLE_COLUMNS:
                raise _error(
                    "pdf_authoring_table_limit",
                    "PDF authoring table column count exceeds its limit.",
                )
            normalized_rows.append(
                tuple(
                    _normalize_text(
                        value,
                        field_name="table cell",
                        maximum=MAX_PDF_AUTHORING_BLOCK_TEXT_CHARS,
                        required=False,
                    )
                    for value in row
                )
            )
        column_count = len(normalized_rows[0])
        if any(len(row) != column_count for row in normalized_rows):
            raise _error(
                "pdf_authoring_table_invalid",
                "PDF authoring table rows must be rectangular.",
            )
        if len(normalized_rows) * column_count > MAX_PDF_AUTHORING_TABLE_CELLS:
            raise _error(
                "pdf_authoring_table_limit",
                "PDF authoring table cell count exceeds its limit.",
            )
        object.__setattr__(self, "rows", tuple(normalized_rows))

    @property
    def kind(self) -> str:
        return "table"


@dataclass(frozen=True, slots=True)
class PdfImageBlock:
    filename: str
    data: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.filename, str)
            or not self.filename
            or len(self.filename.encode("utf-8")) > 255
            or "\x00" in self.filename
        ):
            raise _error(
                "pdf_authoring_image_invalid",
                "PDF authoring image filename is invalid.",
            )
        if not isinstance(self.data, bytes) or not self.data:
            raise _error(
                "pdf_authoring_image_invalid", "PDF authoring image bytes are invalid."
            )
        if len(self.data) > MAX_BINARY_DOCUMENT_BYTES:
            raise _error(
                "pdf_authoring_image_limit",
                "PDF authoring image bytes exceed its limit.",
            )

    @property
    def kind(self) -> str:
        return "image"


@dataclass(frozen=True, slots=True)
class PdfPageBreakBlock:
    @property
    def kind(self) -> str:
        return "page_break"


PdfAuthoringBlock = (
    PdfHeadingBlock | PdfTextBlock | PdfTableBlock | PdfImageBlock | PdfPageBreakBlock
)


@dataclass(frozen=True, slots=True)
class PdfAuthoringDocument:
    metadata: PdfAuthoringMetadata
    font: PdfAuthoringFont
    blocks: tuple[PdfAuthoringBlock, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.metadata, PdfAuthoringMetadata):
            raise _error(
                "pdf_authoring_request_invalid", "PDF authoring metadata is invalid."
            )
        if not isinstance(self.font, PdfAuthoringFont):
            raise _error(
                "pdf_authoring_request_invalid", "PDF authoring font is invalid."
            )
        if (
            not isinstance(self.blocks, tuple)
            or not self.blocks
            or len(self.blocks) > MAX_PDF_AUTHORING_BLOCKS
        ):
            raise _error(
                "pdf_authoring_request_invalid", "PDF authoring blocks are invalid."
            )
        allowed = (
            PdfHeadingBlock,
            PdfTextBlock,
            PdfTableBlock,
            PdfImageBlock,
            PdfPageBreakBlock,
        )
        if any(not isinstance(block, allowed) for block in self.blocks):
            raise _error(
                "pdf_authoring_request_invalid",
                "PDF authoring block type is unsupported.",
            )
        if isinstance(self.blocks[0], PdfPageBreakBlock) or isinstance(
            self.blocks[-1], PdfPageBreakBlock
        ):
            raise _error(
                "pdf_authoring_page_break_invalid",
                "PDF authoring page break is misplaced.",
            )
        if any(
            isinstance(left, PdfPageBreakBlock) and isinstance(right, PdfPageBreakBlock)
            for left, right in zip(self.blocks, self.blocks[1:])
        ):
            raise _error(
                "pdf_authoring_page_break_invalid",
                "PDF authoring page breaks are consecutive.",
            )
        text_chars = len(self.metadata.title) + len(self.metadata.author)
        text_chars += len(self.metadata.subject) + sum(map(len, self.metadata.keywords))
        for block in self.blocks:
            if isinstance(block, (PdfHeadingBlock, PdfTextBlock)):
                text_chars += len(block.text)
            elif isinstance(block, PdfTableBlock):
                text_chars += sum(len(cell) for row in block.rows for cell in row)
        if text_chars > MAX_PDF_AUTHORING_TEXT_CHARS:
            raise _error(
                "pdf_authoring_text_limit", "PDF authoring text exceeds its limit."
            )
        images = tuple(
            block for block in self.blocks if isinstance(block, PdfImageBlock)
        )
        if len(images) > MAX_PDF_AUTHORING_IMAGES:
            raise _error(
                "pdf_authoring_image_limit",
                "PDF authoring image count exceeds its limit.",
            )
        if (
            sum(len(block.data) for block in images)
            > MAX_PDF_AUTHORING_TOTAL_IMAGE_BYTES
        ):
            raise _error(
                "pdf_authoring_image_limit",
                "PDF authoring image bytes exceed their limit.",
            )
        if (
            sum(isinstance(block, PdfPageBreakBlock) for block in self.blocks)
            >= MAX_PDF_AUTHORING_PAGES
        ):
            raise _error(
                "pdf_authoring_page_limit", "PDF authoring page limit can be exceeded."
            )


@dataclass(frozen=True, slots=True)
class PdfAuthoringCounts:
    heading: int
    text: int
    table: int
    image: int
    page_break: int

    def __post_init__(self) -> None:
        values = (
            self.heading,
            self.text,
            self.table,
            self.image,
            self.page_break,
        )
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in values
        ):
            raise _error(
                "pdf_authoring_counts_invalid", "PDF authoring counts are invalid."
            )
        if sum(values) > MAX_PDF_AUTHORING_BLOCKS:
            raise _error(
                "pdf_authoring_counts_invalid",
                "PDF authoring counts exceed their limit.",
            )

    def safe_dict(self) -> dict[str, int]:
        return {
            "heading": self.heading,
            "text": self.text,
            "table": self.table,
            "image": self.image,
            "page_break": self.page_break,
        }


@dataclass(frozen=True, slots=True)
class PdfAuthoringArtifact:
    data: bytes = field(repr=False)
    page_count: int
    metadata: PdfAuthoringMetadata
    font: PdfAuthoringFont
    counts: PdfAuthoringCounts

    def __post_init__(self) -> None:
        if not isinstance(self.metadata, PdfAuthoringMetadata):
            raise _error(
                "pdf_authoring_output_invalid",
                "PDF authoring metadata receipt is invalid.",
            )
        if not isinstance(self.font, PdfAuthoringFont):
            raise _error(
                "pdf_authoring_output_invalid",
                "PDF authoring font receipt is invalid.",
            )
        if not isinstance(self.counts, PdfAuthoringCounts):
            raise _error(
                "pdf_authoring_output_invalid",
                "PDF authoring count receipt is invalid.",
            )
        if not isinstance(self.data, bytes) or not self.data.startswith(b"%PDF-"):
            raise _error(
                "pdf_authoring_output_invalid", "PDF authoring output is invalid."
            )
        if len(self.data) > MAX_PDF_AUTHORING_OUTPUT_BYTES:
            raise _error(
                "pdf_authoring_output_limit", "PDF authoring output exceeds its limit."
            )
        if (
            isinstance(self.page_count, bool)
            or not isinstance(self.page_count, int)
            or not 1 <= self.page_count <= MAX_PDF_AUTHORING_PAGES
        ):
            raise _error(
                "pdf_authoring_page_limit", "PDF authoring page count is invalid."
            )

    @property
    def size_bytes(self) -> int:
        return len(self.data)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()

    def safe_dict(self) -> dict[str, object]:
        return {
            "scope": PDF_AUTHORING_SCOPE,
            "production_ready": False,
            "engine": PDF_AUTHORING_ENGINE,
            "engine_version": PDF_AUTHORING_ENGINE_VERSION,
            "page_count": self.page_count,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "metadata": self.metadata.safe_dict(),
            "font": self.font.safe_dict(),
            "block_counts": self.counts.safe_dict(),
            "active_content_policy": PDF_AUTHORING_ACTIVE_CONTENT_POLICY,
            "active_content_state": "not_generated",
            "external_uri_fetch_count": PDF_AUTHORING_EXTERNAL_URI_FETCH,
            "embedded_script_execution_count": PDF_AUTHORING_EMBEDDED_SCRIPT_EXECUTION,
        }


def _load_reportlab() -> dict[str, Any]:
    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_LEFT
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.platypus import Image as ReportLabImage
        from reportlab.platypus import (
            PageBreak,
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )
    except ModuleNotFoundError as error:
        raise _error(
            "pdf_authoring_dependency_unavailable",
            "PDF authoring dependency is unavailable.",
        ) from error
    return {
        "A4": A4,
        "Image": ReportLabImage,
        "PageBreak": PageBreak,
        "Paragraph": Paragraph,
        "ParagraphStyle": ParagraphStyle,
        "SimpleDocTemplate": SimpleDocTemplate,
        "Spacer": Spacer,
        "Table": Table,
        "TableStyle": TableStyle,
        "TA_LEFT": TA_LEFT,
        "TTFont": TTFont,
        "colors": colors,
        "mm": mm,
        "pdfmetrics": pdfmetrics,
    }


def _document_characters(document: PdfAuthoringDocument) -> set[str]:
    characters: set[str] = set()
    characters.update(document.metadata.title)
    characters.update(document.metadata.author)
    characters.update(document.metadata.subject)
    characters.update(" ".join(document.metadata.keywords))
    for block in document.blocks:
        if isinstance(block, (PdfHeadingBlock, PdfTextBlock)):
            characters.update(block.text)
        elif isinstance(block, PdfTableBlock):
            for row in block.rows:
                for cell in row:
                    characters.update(cell)
    return {character for character in characters if character not in "\r\n\t"}


def _register_font(document: PdfAuthoringDocument, reportlab: dict[str, Any]) -> str:
    pdfmetrics = reportlab["pdfmetrics"]
    TTFont = reportlab["TTFont"]
    try:
        font = TTFont(PDF_AUTHORING_FONT_NAME, BytesIO(document.font.data))
        char_to_glyph = font.face.charToGlyph
    except Exception as error:
        raise _error(
            "pdf_authoring_font_invalid", "PDF authoring font could not be parsed."
        ) from error
    missing = sorted(
        character
        for character in _document_characters(document)
        if ord(character) not in char_to_glyph or char_to_glyph[ord(character)] == 0
    )
    if missing:
        raise _error(
            "pdf_authoring_font_glyph_missing",
            "PDF authoring font does not cover the requested text.",
        )
    with _FONT_LOCK:
        pdfmetrics.registerFont(font)
    return PDF_AUTHORING_FONT_NAME


def _escaped_text(value: str) -> str:
    return escape(value).replace("\n", "<br/>")


def _image_flowable(block: PdfImageBlock, reportlab: dict[str, Any]) -> Any:
    try:
        inspection = inspect_image(block.data)
    except ImageContractError as error:
        raise _error(
            "pdf_authoring_image_rejected", "PDF authoring image was rejected."
        ) from error
    if inspection.format not in {"PNG", "JPEG"} or inspection.multi_frame:
        raise _error(
            "pdf_authoring_image_unsupported",
            "PDF authoring supports one-frame PNG and JPEG images only.",
        )
    try:
        normalized = thumbnail_image(
            block.data,
            size=(MAX_PDF_AUTHORING_IMAGE_EDGE, MAX_PDF_AUTHORING_IMAGE_EDGE),
            output_format="PNG",
        )
    except ImageContractError as error:
        raise _error(
            "pdf_authoring_image_rejected", "PDF authoring image was rejected."
        ) from error
    edge = 240.0
    maximum_height = 180.0
    ratio = normalized.width / normalized.height
    width = min(edge, maximum_height * ratio)
    height = width / ratio
    if height > maximum_height:
        height = maximum_height
        width = height * ratio
    return reportlab["Image"](
        BytesIO(normalized.data),
        width=width,
        height=height,
    )


def _story(
    document: PdfAuthoringDocument, reportlab: dict[str, Any], font_name: str
) -> list[Any]:
    heading_style = reportlab["ParagraphStyle"](
        "PadiemAuthoringHeading",
        fontName=font_name,
        fontSize=18,
        leading=24,
        spaceAfter=8,
        alignment=reportlab["TA_LEFT"],
    )
    body_style = reportlab["ParagraphStyle"](
        "PadiemAuthoringBody",
        fontName=font_name,
        fontSize=10,
        leading=15,
        spaceAfter=8,
        alignment=reportlab["TA_LEFT"],
    )
    cell_style = reportlab["ParagraphStyle"](
        "PadiemAuthoringCell",
        parent=body_style,
        fontSize=9,
        leading=12,
    )
    story: list[Any] = []
    for block in document.blocks:
        if isinstance(block, PdfHeadingBlock):
            story.append(
                reportlab["Paragraph"](_escaped_text(block.text), heading_style)
            )
        elif isinstance(block, PdfTextBlock):
            story.append(reportlab["Paragraph"](_escaped_text(block.text), body_style))
        elif isinstance(block, PdfTableBlock):
            column_count = len(block.rows[0])
            total_width = 170 * reportlab["mm"]
            column_width = total_width / column_count
            table_data = [
                [
                    reportlab["Paragraph"](_escaped_text(cell), cell_style)
                    for cell in row
                ]
                for row in block.rows
            ]
            table = reportlab["Table"](
                table_data,
                colWidths=(column_width,) * column_count,
                repeatRows=1,
            )
            table.setStyle(
                reportlab["TableStyle"](
                    [
                        ("FONTNAME", (0, 0), (-1, -1), font_name),
                        ("GRID", (0, 0), (-1, -1), 0.5, reportlab["colors"].black),
                        (
                            "BACKGROUND",
                            (0, 0),
                            (-1, 0),
                            reportlab["colors"].HexColor("#eeeeee"),
                        ),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 4),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                        ("TOPPADDING", (0, 0), (-1, -1), 4),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ]
                )
            )
            story.extend((table, reportlab["Spacer"](1, 8)))
        elif isinstance(block, PdfImageBlock):
            story.extend((_image_flowable(block, reportlab), reportlab["Spacer"](1, 8)))
        else:
            story.append(reportlab["PageBreak"]())
    return story


def author_structured_pdf(document: PdfAuthoringDocument) -> PdfAuthoringArtifact:
    if not isinstance(document, PdfAuthoringDocument):
        raise _error(
            "pdf_authoring_request_invalid", "PDF authoring request is invalid."
        )
    reportlab = _load_reportlab()
    font_name = _register_font(document, reportlab)
    output = BytesIO()

    def apply_metadata(canvas: Any, document_template: Any) -> None:
        del document_template
        canvas.setTitle(document.metadata.title)
        canvas.setAuthor(document.metadata.author)
        canvas.setSubject(document.metadata.subject)
        canvas.setKeywords(" ".join(document.metadata.keywords))
        canvas.setCreator("Padiem bounded PDF authoring")
        canvas.setProducer("ReportLab")

    document_template = reportlab["SimpleDocTemplate"](
        output,
        pagesize=reportlab["A4"],
        leftMargin=18 * reportlab["mm"],
        rightMargin=18 * reportlab["mm"],
        topMargin=18 * reportlab["mm"],
        bottomMargin=18 * reportlab["mm"],
        invariant=1,
    )
    try:
        document_template.build(
            _story(document, reportlab, font_name),
            onFirstPage=apply_metadata,
        )
    except DocumentNormalizationError:
        raise
    except Exception as error:
        raise _error(
            "pdf_authoring_engine_failed", "PDF authoring engine failed."
        ) from error
    data = output.getvalue()
    page_count = getattr(document_template, "page", 0)
    if not 1 <= page_count <= MAX_PDF_AUTHORING_PAGES:
        raise _error(
            "pdf_authoring_page_limit", "PDF authoring page count exceeds its limit."
        )
    counts = PdfAuthoringCounts(
        heading=sum(isinstance(block, PdfHeadingBlock) for block in document.blocks),
        text=sum(isinstance(block, PdfTextBlock) for block in document.blocks),
        table=sum(isinstance(block, PdfTableBlock) for block in document.blocks),
        image=sum(isinstance(block, PdfImageBlock) for block in document.blocks),
        page_break=sum(
            isinstance(block, PdfPageBreakBlock) for block in document.blocks
        ),
    )
    return PdfAuthoringArtifact(
        data=data,
        page_count=page_count,
        metadata=document.metadata,
        font=document.font,
        counts=counts,
    )


__all__ = [
    "MAX_PDF_AUTHORING_BLOCKS",
    "MAX_PDF_AUTHORING_IMAGES",
    "MAX_PDF_AUTHORING_OUTPUT_BYTES",
    "MAX_PDF_AUTHORING_PAGES",
    "MAX_PDF_AUTHORING_TABLE_CELLS",
    "MAX_PDF_AUTHORING_TABLE_COLUMNS",
    "MAX_PDF_AUTHORING_TABLE_ROWS",
    "MAX_PDF_AUTHORING_TEXT_CHARS",
    "PDF_AUTHORING_ACTIVE_CONTENT_POLICY",
    "PDF_AUTHORING_EMBEDDED_SCRIPT_EXECUTION",
    "PDF_AUTHORING_ENGINE",
    "PDF_AUTHORING_ENGINE_VERSION",
    "PDF_AUTHORING_EXTERNAL_URI_FETCH",
    "PDF_AUTHORING_FONT_BYTES",
    "PDF_AUTHORING_FONT_FAMILY",
    "PDF_AUTHORING_FONT_LICENSE",
    "PDF_AUTHORING_FONT_NAME",
    "PDF_AUTHORING_FONT_SHA256",
    "PDF_AUTHORING_SCOPE",
    "PdfAuthoringArtifact",
    "PdfAuthoringBlock",
    "PdfAuthoringCounts",
    "PdfAuthoringDocument",
    "PdfAuthoringFont",
    "PdfAuthoringMetadata",
    "PdfHeadingBlock",
    "PdfImageBlock",
    "PdfPageBreakBlock",
    "PdfTableBlock",
    "PdfTextBlock",
    "author_structured_pdf",
]
