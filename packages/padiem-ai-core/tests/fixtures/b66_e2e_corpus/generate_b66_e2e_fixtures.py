#!/usr/bin/env python3
"""Deterministic generator for the B66 quotation E2E fixture corpus (#3205).

Purpose
-------
Produce the synthetic, non-sensitive document corpus that the Business 66
template-cloner acceptance run (#3186) needs, without any model call, network
call, or production mutation.

Design
------
* Every fixture is produced by this generator; no hand-edited binaries and no
  ``%TEMP%`` benchmark leftovers are used as a source.
* Korean text is rendered with the repository's own OFL-licensed authoring
  font (``tests/fixtures/pdf_authoring/``), which the Core pins by SHA-256.
* PDF authoring goes through ``padiem_ai_core.pdf_authoring`` (ReportLab
  ``invariant=1``), raster previews through ``padiem_ai_core.pdf_render``
  (pypdfium2). DOCX/XLSX are written by this module as fixed-metadata OOXML
  ZIP archives.

Determinism contract
--------------------
Each fixture declares ``determinism``:

* ``byte_identical`` — the writer is pure Python and the bytes are expected to
  reproduce exactly on any platform that has the same pinned dependency set.
* ``normalized`` — the bytes depend on a native rasterizer build, so exact
  bytes are recorded for integrity but cross-platform reproducibility is
  asserted through ``normalized_fingerprint`` instead. Nothing here silently
  allows a drifting SHA-256: the class is explicit, and the fingerprint is
  defined and tested.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from dataclasses import dataclass, field
from importlib import import_module
from io import BytesIO
from pathlib import Path

CORPUS_ID = "b66-quotation-e2e-v1"
GENERATOR_VERSION = "1"
MANIFEST_NAME = "manifest.json"

# Fixed ZIP member metadata keeps the OOXML archives byte-identical between
# runs; the DOS epoch is the value ``zipfile`` itself uses for "no date".
FIXED_ZIP_DATE = (1980, 1, 1, 0, 0, 0)

# The repository's OFL authoring font is a 106-character subset (see
# ``tests/fixtures/pdf_authoring/FONT_SOURCE.json``). PDF and raster fixtures
# therefore use ASCII field labels plus the Korean syllables that subset
# actually carries. DOCX/XLSX carry unrestricted UTF-8 Korean text.
SYNTHETIC_MARKER = "SYNTHETIC TEST DATA"
SYNTHETIC_MARKER_KOREAN = "SYNTHETIC TEST DATA / 실사용 금지"

SUPPLIER_NAME = "주식회사 테스트상사"
SUPPLIER_BIZ = "000-00-00000"
SUPPLIER_ADDRESS = "광주광역시 테스트구 견적로 123"
SUPPLIER_PHONE = "062-000-0000"

SUPPLIER_NAME_ASCII = "TEST SUPPLIER CO"
SUPPLIER_ADDRESS_ASCII = "123 TEST STREET, TEST CITY"

RECIPIENTS = (
    "주식회사 예시테크",
    "주식회사 샘플산업",
    "주식회사 견본물산",
)

RECIPIENTS_ASCII = (
    "SAMPLE TECH CO",
    "SAMPLE INDUSTRY CO",
    "SAMPLE TRADING CO",
)

# Field labels used by the PDF/raster fixtures. Every label is composed from
# the subset's ASCII range so the pinned font can render it.
PDF_LABELS = {
    "quote_number": "QUOTE NO",
    "quote_date": "DATE",
    "supplier": "SUPPLIER",
    "recipient": "RECIPIENT",
    "item": "ITEM",
    "quantity": "QTY",
    "unit_price": "PRICE",
    "amount": "AMOUNT",
    "supply": "SUPPLY",
    "vat": "VAT",
    "total": "TOTAL",
    "memo": "MEMO",
    "page": "PAGE",
    "terms": "TERMS",
}

# Korean labels used by the DOCX/XLSX fixtures (unrestricted UTF-8).
KOREAN_LABELS = {
    "quote_number": "견적번호",
    "quote_date": "견적일자",
    "supplier": "공급자",
    "recipient": "공급받는 자",
    "item": "품목",
    "quantity": "수량",
    "unit_price": "단가",
    "amount": "금액",
    "supply": "공급가액",
    "vat": "부가세",
    "total": "총액",
    "memo": "메모",
}

CORPUS_DIR = Path(__file__).resolve().parent
FONT_PATH = CORPUS_DIR.parent / "pdf_authoring" / "PadiemNotoSansKRAuthoringTest-Regular.ttf"

DEFAULT_COLUMN_ORDER = ("품목", "수량", "단가", "금액")
VARIANT_COLUMN_ORDER = ("수량", "품목", "금액", "단가")


# --------------------------------------------------------------------------
# business material
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LineItem:
    description: str
    quantity: int
    unit: str
    unit_price: int

    @property
    def amount(self) -> int:
        return self.quantity * self.unit_price

    def ascii_description(self) -> str:
        """A description the pinned PDF authoring font can actually render."""

        return _ASCII_ITEM_NAMES.get(self.description, f"ITEM {self.quantity}x{self.unit_price}")


@dataclass(frozen=True, slots=True)
class Quotation:
    quote_number: str | None
    quote_date: str | None
    recipient: str | None
    items: tuple[LineItem, ...]
    vat_mode: str
    memo: str | None
    column_order: tuple[str, ...] = DEFAULT_COLUMN_ORDER

    @property
    def supply_amount(self) -> int:
        return sum(item.amount for item in self.items)

    @property
    def vat_amount(self) -> int:
        if self.vat_mode == "separate":
            return self.supply_amount // 10
        return 0

    @property
    def total_amount(self) -> int:
        if self.vat_mode == "separate":
            return self.supply_amount + self.vat_amount
        return self.supply_amount

    @property
    def vat_label(self) -> str:
        if self.vat_mode == "separate":
            return "부가세 별도"
        if self.vat_mode == "inclusive":
            return "부가세 포함"
        if self.vat_mode == "exempt":
            return "면세"
        return ""


def _default_items() -> tuple[LineItem, ...]:
    return (
        LineItem("스테인리스 배관 40x40", 12, "m", 9_800),
        LineItem("알루미늄 브래킷", 24, "개", 2_200),
    )


# PDF fixtures render through the pinned 106-character subset font, so their
# item names need an ASCII-safe twin. The numbers stay identical across
# formats; only the label language differs.
_ASCII_ITEM_NAMES = {
    "스테인리스 배관 40x40": "STAINLESS PIPE 40X40",
    "알루미늄 브래킷": "ALUMINUM BRACKET",
    "청결 볼트 M10": "CLEAN BOLT M10",
}

_ASCII_KINDS = ("PIPE", "VALVE", "FLANGE", "GASKET", "BOLT", "NUT", "WASHER", "HOSE")
_ASCII_MATERIALS = ("STAINLESS", "ALUMINUM", "BRASS", "CAST IRON")


def _wide_items() -> tuple[LineItem, ...]:
    """F12 is PDF-only, so its item names are authored ASCII-safe directly."""

    items = []
    for index in range(28):
        kind = _ASCII_KINDS[index % len(_ASCII_KINDS)]
        material = _ASCII_MATERIALS[index % len(_ASCII_MATERIALS)]
        items.append(
            LineItem(
                f"{material} {kind} SPEC {index + 1}0MM",
                index + 2,
                "EA",
                1_500 + index * 250,
            )
        )
    return tuple(items)


def _quotations() -> dict[str, Quotation]:
    return {
        "F01": Quotation("Q-2026-3001", "2026-03-02", RECIPIENTS[0], _default_items(), "separate", "납기 협의"),
        "F02": Quotation("Q-2026-3002", "2026-03-03", RECIPIENTS[1], _default_items(), "separate", "납기 협의"),
        "F03": Quotation("Q-2026-3003", "2026-03-04", RECIPIENTS[2], _default_items(), "separate", "결제조건 협의"),
        "F04": Quotation("Q-2026-3004", "2026-03-05", RECIPIENTS[0], _default_items(), "separate", None),
        "F05": Quotation("Q-2026-3005", "2026-03-06", RECIPIENTS[1], _default_items(), "separate", "납기 협의", VARIANT_COLUMN_ORDER),
        "F06": Quotation("Q-2026-3006", "2026-03-09", RECIPIENTS[2], _default_items(), "separate", "부가세 별도 기준"),
        "F07": Quotation("Q-2026-3007", "2026-03-10", RECIPIENTS[0], _default_items(), "inclusive", "부가세 포함 금액입니다"),
        "F08": Quotation("Q-2026-3008", "2026-03-11", RECIPIENTS[1], _default_items(), "exempt", "면세 항목입니다"),
        "F09": Quotation(None, None, RECIPIENTS[2], (LineItem("청결 볼트 M10", 30, "개", 900),), "unknown", None),
        "F10": Quotation("Q-2026-3010", "2026-03-13", RECIPIENTS[0], _default_items(), "separate", None),
        "F12": Quotation("Q-2026-3012", "2026-03-16", RECIPIENTS[1], _wide_items(), "separate", "납기 협의"),
        "F13": Quotation("Q-2026-3013", "2026-03-17", RECIPIENTS[2], _default_items(), "separate", "납기 협의"),
    }


FIXED_TERMS = {
    "납기": "발주 후 7일",
    "결제조건": "협의",
    "유효기간": "견적일로부터 30일",
}


# --------------------------------------------------------------------------
# constants shared with every fixture
# --------------------------------------------------------------------------


def synthetic_identity() -> dict[str, str]:
    return {
        "supplier_name": SUPPLIER_NAME,
        "supplier_business_number": SUPPLIER_BIZ,
        "supplier_address": SUPPLIER_ADDRESS,
        "supplier_phone": SUPPLIER_PHONE,
        "synthetic_marker": SYNTHETIC_MARKER,
    }


def template_only_facts(
    *, column_order: tuple[str, ...], with_logo: bool, ascii_labels: bool = False
) -> list[str]:
    rendered = tuple(
        {
            "품목": PDF_LABELS["item"],
            "수량": PDF_LABELS["quantity"],
            "단가": PDF_LABELS["unit_price"],
            "금액": PDF_LABELS["amount"],
        }.get(column, column)
        for column in column_order
    ) if ascii_labels else column_order
    facts = [
        "item column order: " + " | ".join(rendered),
        "table header row is repeated on every page",
        "grid borders and left alignment for item rows",
        "fixed memo/default terms block placement",
        "vat presentation style line beneath the item table",
    ]
    if with_logo:
        facts.append("synthetic logo placed above the document title")
    return facts


def variable_content_facts(quotation: Quotation) -> list[str]:
    return [
        "recipient",
        "quotation number" if quotation.quote_number else "quotation number (absent by design)",
        "quotation date" if quotation.quote_date else "quotation date (absent by design)",
        "item descriptions",
        "item quantities",
        "item unit prices",
        "supply amount",
        "vat amount",
        "total amount",
        "memo text" if quotation.memo else "memo text (absent by design)",
    ]


def _load_font_bytes() -> bytes:
    return FONT_PATH.read_bytes()


_FONT_COVERAGE: frozenset[str] | None = None


def font_covered_characters() -> frozenset[str]:
    """Characters the pinned OFL authoring font subset can actually render.

    The font is a deliberate 106-character subset, so PDF/raster authoring must
    fail loudly instead of silently dropping or substituting glyphs.
    """

    global _FONT_COVERAGE
    if _FONT_COVERAGE is None:
        ttfonts = import_module("reportlab.pdfbase.ttfonts")
        font = ttfonts.TTFont("b66-coverage-probe", BytesIO(_load_font_bytes()))
        _FONT_COVERAGE = frozenset(
            chr(code)
            for code, glyph in font.face.charToGlyph.items()
            if glyph
        )
    return _FONT_COVERAGE


def assert_font_safe(text: str) -> None:
    """Refuse to author text the pinned font cannot render."""

    missing = sorted(char for char in set(text) if char not in font_covered_characters())
    if missing:
        raise ValueError(
            "PDF authoring text uses characters outside the pinned font subset: "
            + " ".join(f"U+{ord(char):04X}" for char in missing)
        )


# --------------------------------------------------------------------------
# PDF authoring
# --------------------------------------------------------------------------


def _table_rows(quotation: Quotation, *, ascii_labels: bool = False) -> tuple[tuple[str, ...], ...]:
    if ascii_labels:
        header = tuple(
            {
                "품목": PDF_LABELS["item"],
                "수량": PDF_LABELS["quantity"],
                "단가": PDF_LABELS["unit_price"],
                "금액": PDF_LABELS["amount"],
            }[column]
            for column in quotation.column_order
        )
    else:
        header = tuple(quotation.column_order)
    rows = [header]
    for item in quotation.items:
        values = {
            "품목": item.ascii_description() if ascii_labels else item.description,
            "수량": f"{item.quantity}",
            "단가": f"{item.unit_price:,}",
            "금액": f"{item.amount:,}",
        }
        rows.append(tuple(values[column] for column in quotation.column_order))
    return tuple(rows)


_LOGO_TEXT_BLOCKS = ("PADIEM TEST", "SYNTHETIC QUOTE")
_LOGO_METADATA = {
    "title": "B66 synthetic logo fixture",
    "author": "Padiem B66 fixture generator",
    "subject": "synthetic placeholder logo",
    "keywords": ("b66", "synthetic", "logo", "fixture", "3205"),
}


def author_logo_pdf():
    """Author the synthetic logo card used by fixture F11."""

    pdf_authoring = import_module("padiem_ai_core.pdf_authoring")
    # Validate the exact literals that go into the document, not copies of them.
    for value in (
        *_LOGO_TEXT_BLOCKS,
        SYNTHETIC_MARKER,
        _LOGO_METADATA["title"],
        _LOGO_METADATA["author"],
        _LOGO_METADATA["subject"],
        *_LOGO_METADATA["keywords"],
    ):
        assert_font_safe(value)
    document = pdf_authoring.PdfAuthoringDocument(
        metadata=pdf_authoring.PdfAuthoringMetadata(
            title=_LOGO_METADATA["title"],
            author=_LOGO_METADATA["author"],
            subject=_LOGO_METADATA["subject"],
            keywords=_LOGO_METADATA["keywords"],
        ),
        font=pdf_authoring.PdfAuthoringFont(data=_load_font_bytes()),
        blocks=(
            pdf_authoring.PdfHeadingBlock(_LOGO_TEXT_BLOCKS[0]),
            pdf_authoring.PdfTextBlock(_LOGO_TEXT_BLOCKS[1]),
            pdf_authoring.PdfTextBlock(SYNTHETIC_MARKER),
        ),
    )
    return pdf_authoring.author_structured_pdf(document)



_ASCII_MEMOS = {
    "납기 협의": "DELIVERY TBD",
    "결제조건 협의": "PAYMENT TERMS TBD",
    "부가세 별도 기준": "VAT SEPARATE BASIS",
    "부가세 포함 금액입니다": "VAT INCLUDED AMOUNT",
    "면세 항목입니다": "EXEMPT ITEM",
}


def _ascii_memo(value: str | None) -> str | None:
    if value is None:
        return None
    return _ASCII_MEMOS.get(value, value)


def _pdf_lines(quotation: Quotation) -> list[str]:
    """Render one quotation as PDF-safe text lines."""

    lines: list[str] = ["QUOTATION", SYNTHETIC_MARKER]
    lines.append(f"{PDF_LABELS['supplier']}: {SUPPLIER_NAME_ASCII} / {SUPPLIER_BIZ}")
    lines.append(f"ADDRESS: {SUPPLIER_ADDRESS_ASCII} / TEL: {SUPPLIER_PHONE}")
    recipient = quotation.recipient
    if recipient:
        index = RECIPIENTS.index(recipient)
        lines.append(f"{PDF_LABELS['recipient']}: {RECIPIENTS_ASCII[index]}")
    if quotation.quote_number:
        lines.append(f"{PDF_LABELS['quote_number']}: {quotation.quote_number}")
    if quotation.quote_date:
        lines.append(f"{PDF_LABELS['quote_date']}: {quotation.quote_date}")
    lines.append(f"{PDF_LABELS['supply']}: {quotation.supply_amount:,}")
    if quotation.vat_mode == "separate":
        lines.append(f"{PDF_LABELS['vat']}: {quotation.vat_amount:,} (SEPARATE)")
    elif quotation.vat_mode == "inclusive":
        lines.append(f"{PDF_LABELS['vat']}: INCLUDED")
    elif quotation.vat_mode == "exempt":
        lines.append(f"{PDF_LABELS['vat']}: EXEMPT")
    if quotation.vat_mode != "unknown":
        lines.append(f"{PDF_LABELS['total']}: {quotation.total_amount:,}")
    if quotation.memo:
        lines.append(f"{PDF_LABELS['memo']}: {_ascii_memo(quotation.memo)}")
    return lines


def author_quotation_pdf(quotation: Quotation, *, with_logo: bool = False, logo_png: bytes | None = None):
    pdf_authoring = import_module("padiem_ai_core.pdf_authoring")
    heading = pdf_authoring.PdfHeadingBlock
    text = pdf_authoring.PdfTextBlock
    table = pdf_authoring.PdfTableBlock

    blocks: list[object] = []
    if with_logo and logo_png:
        blocks.append(pdf_authoring.PdfImageBlock(filename="f11-simple-logo.png", data=logo_png))
    blocks.append(heading("QUOTATION"))
    for line in _pdf_lines(quotation)[1:]:
        assert_font_safe(line)
        blocks.append(text(line))
    for row in _table_rows(quotation, ascii_labels=True):
        for cell in row:
            assert_font_safe(cell)
    blocks.append(table(_table_rows(quotation, ascii_labels=True)))
    assert_font_safe("B66 synthetic quotation fixture")
    assert_font_safe("Padiem B66 fixture generator")
    for keyword in ("b66", "synthetic", "fixture", "quotation", "3205"):
        assert_font_safe(keyword)

    document = pdf_authoring.PdfAuthoringDocument(
        metadata=pdf_authoring.PdfAuthoringMetadata(
            title="B66 synthetic quotation fixture",
            author="Padiem B66 fixture generator",
            subject=f"synthetic quotation {quotation.quote_number or 'NO-NUMBER'}",
            keywords=("b66", "synthetic", "fixture", "quotation", "3205"),
        ),
        font=pdf_authoring.PdfAuthoringFont(data=_load_font_bytes()),
        blocks=tuple(blocks),
    )
    return pdf_authoring.author_structured_pdf(document)


# --------------------------------------------------------------------------
# OOXML authoring (DOCX / XLSX)
# --------------------------------------------------------------------------


def _xml_header() -> str:
    return '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'


def _zip_part(name: str, data: str | bytes) -> tuple[zipfile.ZipInfo, bytes]:
    info = zipfile.ZipInfo(filename=name, date_time=FIXED_ZIP_DATE)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o600 << 16
    payload = data.encode("utf-8") if isinstance(data, str) else data
    return info, payload


def build_ooxml_archive(parts: list[tuple[zipfile.ZipInfo, bytes]]) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for info, payload in parts:
            archive.writestr(info, payload)
    return buffer.getvalue()


def _document_xml(quotation: Quotation) -> str:
    from xml.sax.saxutils import escape

    body: list[str] = []

    def paragraph(value: str) -> str:
        return f"<w:p><w:r><w:t>{escape(value)}</w:t></w:r></w:p>"

    body.append(paragraph("견적서"))
    body.append(paragraph(SYNTHETIC_MARKER_KOREAN))
    body.append(paragraph(f"공급자: {SUPPLIER_NAME} | 사업자번호: {SUPPLIER_BIZ}"))
    body.append(paragraph(f"주소: {SUPPLIER_ADDRESS} | 전화: {SUPPLIER_PHONE}"))
    if quotation.recipient:
        body.append(paragraph(f"공급받는 자: {quotation.recipient}"))
    if quotation.quote_number:
        body.append(paragraph(f"견적번호: {quotation.quote_number}"))
    if quotation.quote_date:
        body.append(paragraph(f"견적일자: {quotation.quote_date}"))

    rows = []
    for row in _table_rows(quotation):
        cells = "".join(
            f"<w:tc><w:p><w:r><w:t>{escape(value)}</w:t></w:r></w:p></w:tc>" for value in row
        )
        rows.append(f"<w:tr>{cells}</w:tr>")
    body.append(
        "<w:tbl><w:tblPr><w:tblBorders>"
        '<w:top w:val="single" w:sz="4"/><w:left w:val="single" w:sz="4"/>'
        '<w:bottom w:val="single" w:sz="4"/><w:right w:val="single" w:sz="4"/>'
        '<w:insideH w:val="single" w:sz="4"/><w:insideV w:val="single" w:sz="4"/>'
        "</w:tblBorders></w:tblPr>"
        + "".join(rows)
        + "</w:tbl>"
    )
    if quotation.vat_mode == "separate":
        body.append(paragraph(f"공급가액: {quotation.supply_amount:,} | 부가세: {quotation.vat_amount:,}"))
        body.append(paragraph(f"총액: {quotation.total_amount:,}"))
    elif quotation.vat_mode in {"inclusive", "exempt"}:
        body.append(paragraph(f"총액: {quotation.total_amount:,} ({quotation.vat_label})"))
    if quotation.memo:
        body.append(paragraph(f"메모: {quotation.memo}"))
    body.append("<w:sectPr/>")
    return (
        _xml_header()
        + '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        + "<w:body>"
        + "".join(body)
        + "</w:body></w:document>"
    )


DOCX_CONTENT_TYPES = (
    _xml_header()
    + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    + '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    + '<Default Extension="xml" ContentType="application/xml"/>'
    + '<Override PartName="/word/document.xml" '
    + 'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    + "</Types>"
)

DOCX_ROOT_RELS = (
    _xml_header()
    + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    + '<Relationship Id="rId1" '
    + 'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
    + 'Target="word/document.xml"/>'
    + "</Relationships>"
)


def build_docx(quotation: Quotation) -> bytes:
    return build_ooxml_archive(
        [
            _zip_part("[Content_Types].xml", DOCX_CONTENT_TYPES),
            _zip_part("_rels/.rels", DOCX_ROOT_RELS),
            _zip_part("word/document.xml", _document_xml(quotation)),
        ]
    )


XLSX_CONTENT_TYPES = (
    _xml_header()
    + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    + '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    + '<Default Extension="xml" ContentType="application/xml"/>'
    + '<Override PartName="/xl/workbook.xml" '
    + 'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
    + '<Override PartName="/xl/worksheets/sheet1.xml" '
    + 'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
    + "</Types>"
)

XLSX_ROOT_RELS = (
    _xml_header()
    + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    + '<Relationship Id="rId1" '
    + 'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
    + 'Target="xl/workbook.xml"/>'
    + "</Relationships>"
)

XLSX_WORKBOOK = (
    _xml_header()
    + '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
    + 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
    + '<sheets><sheet name="견적서" sheetId="1" r:id="rId1"/></sheets>'
    + "</workbook>"
)

XLSX_WORKBOOK_RELS = (
    _xml_header()
    + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    + '<Relationship Id="rId1" '
    + 'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
    + 'Target="worksheets/sheet1.xml"/>'
    + "</Relationships>"
)


def _column_letter(index: int) -> str:
    letters = ""
    current = index
    while current >= 0:
        letters = chr(ord("A") + current % 26) + letters
        current = current // 26 - 1
    return letters


def _sheet_rows(quotation: Quotation) -> list[list[str | int]]:
    rows: list[list[str | int]] = [["견적서"], [SYNTHETIC_MARKER_KOREAN]]
    rows.append(["공급자", SUPPLIER_NAME, "사업자번호", SUPPLIER_BIZ])
    rows.append(["주소", SUPPLIER_ADDRESS, "전화", SUPPLIER_PHONE])
    if quotation.recipient:
        rows.append(["공급받는 자", quotation.recipient])
    if quotation.quote_number:
        rows.append(["견적번호", quotation.quote_number])
    if quotation.quote_date:
        rows.append(["견적일자", quotation.quote_date])
    rows.append([])
    rows.append(list(quotation.column_order))
    for item in quotation.items:
        values: dict[str, str | int] = {
            "품목": item.description,
            "수량": item.quantity,
            "단가": item.unit_price,
            "금액": item.amount,
        }
        rows.append([values[column] for column in quotation.column_order])
    rows.append([])
    rows.append(["공급가액", quotation.supply_amount])
    if quotation.vat_mode != "unknown":
        rows.append(["부가세", quotation.vat_amount, quotation.vat_label])
    rows.append(["총액", quotation.total_amount])
    if quotation.memo:
        rows.append(["메모", quotation.memo])
    return rows


def _sheet_xml(quotation: Quotation) -> str:
    from xml.sax.saxutils import escape

    source_rows = _sheet_rows(quotation)
    sheet_rows: list[str] = []
    for row_index, row in enumerate(source_rows, start=1):
        cells: list[str] = []
        for column_index, value in enumerate(row):
            if value == "":
                continue
            reference = f"{_column_letter(column_index)}{row_index}"
            if isinstance(value, int):
                cells.append(f'<c r="{reference}"><v>{value}</v></c>')
            else:
                cells.append(
                    f'<c r="{reference}" t="inlineStr"><is><t>{escape(value)}</t></is></c>'
                )
        sheet_rows.append(f'<row r="{row_index}">' + "".join(cells) + "</row>")
    dimension_end = (
        f"{_column_letter(max(len(row) for row in source_rows) - 1)}"
        f"{len(source_rows)}"
    )
    return (
        _xml_header()
        + '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        + f'<dimension ref="A1:{dimension_end}"/>'
        + "<sheetData>"
        + "".join(sheet_rows)
        + "</sheetData></worksheet>"
    )


def build_xlsx(quotation: Quotation) -> bytes:
    return build_ooxml_archive(
        [
            _zip_part("[Content_Types].xml", XLSX_CONTENT_TYPES),
            _zip_part("_rels/.rels", XLSX_ROOT_RELS),
            _zip_part("xl/workbook.xml", XLSX_WORKBOOK),
            _zip_part("xl/_rels/workbook.xml.rels", XLSX_WORKBOOK_RELS),
            _zip_part("xl/worksheets/sheet1.xml", _sheet_xml(quotation)),
        ]
    )


# --------------------------------------------------------------------------
# raster authoring
# --------------------------------------------------------------------------


def render_png(pdf_bytes: bytes) -> tuple[bytes, int, int]:
    pdf_render = import_module("padiem_ai_core.pdf_render")
    result = pdf_render.render_pdf_pages(
        name="fixture.pdf", media_type="application/pdf", payload=pdf_bytes
    )
    page = result.pages[0]
    return page.data, page.width, page.height


def degrade_png(png_bytes: bytes) -> bytes:
    """Rotate, downscale and re-upscale a page preview to imitate a bad scan."""

    pil_image = import_module("PIL.Image")
    image = pil_image.open(BytesIO(png_bytes)).convert("L")
    small = image.resize(
        (max(1, image.width // 4), max(1, image.height // 4)),
        resample=pil_image.Resampling.BILINEAR,
    )
    restored = small.resize(image.size, resample=pil_image.Resampling.BILINEAR)
    rotated = restored.rotate(
        1.8, resample=pil_image.Resampling.BILINEAR, expand=False, fillcolor=255
    )
    output = BytesIO()
    rotated.save(output, format="PNG", optimize=False)
    return output.getvalue()


def normalized_image_fingerprint(png_bytes: bytes, grid: int = 8, levels: int = 16) -> str:
    """Canonical, rasterizer-tolerant fingerprint of a PNG fixture.

    The exact bytes of a raster depend on the native rasterizer and Pillow
    build, so cross-platform reproducibility is asserted through a coarse
    luminance grid instead: the image is reduced to ``grid`` x ``grid`` cells,
    each cell averaged and quantized into ``levels`` buckets.
    """

    pil_image = import_module("PIL.Image")
    pil_stat = import_module("PIL.ImageStat")
    image = pil_image.open(BytesIO(png_bytes)).convert("L")
    buckets: list[int] = []
    for row in range(grid):
        for column in range(grid):
            left = image.width * column // grid
            right = max(left + 1, image.width * (column + 1) // grid)
            top = image.height * row // grid
            bottom = max(top + 1, image.height * (row + 1) // grid)
            cell = image.crop((left, top, right, bottom))
            mean = pil_stat.Stat(cell).mean[0]
            buckets.append(min(levels - 1, int(mean) * levels // 256))
    payload = json.dumps(
        {
            "grid": grid,
            "levels": levels,
            "width": image.width,
            "height": image.height,
            "buckets": buckets,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


# --------------------------------------------------------------------------
# manifest
# --------------------------------------------------------------------------


@dataclass
class Fixture:
    fixture_id: str
    filename: str
    media_type: str
    source_kind: str
    determinism: str
    data: bytes
    structural_facts: list[str]
    business_facts: dict[str, object]
    template_facts: list[str]
    variable_facts: list[str]
    vat_mode: str
    page_or_sheet_count: int
    column_order: tuple[str, ...]
    notes: str = ""
    extra: dict[str, object] = field(default_factory=dict)

    def to_manifest(self) -> dict[str, object]:
        record: dict[str, object] = {
            "fixture_id": self.fixture_id,
            "relative_path": self.filename,
            "media_type": self.media_type,
            "byte_size": len(self.data),
            "sha256": hashlib.sha256(self.data).hexdigest(),
            "source_kind": self.source_kind,
            "determinism": self.determinism,
            "expected_structural_facts": self.structural_facts,
            "expected_business_facts": self.business_facts,
            "template_only_facts": self.template_facts,
            "variable_content_facts": self.variable_facts,
            "vat_mode": self.vat_mode,
            "page_count_or_sheet_count": self.page_or_sheet_count,
            "column_order": list(self.column_order),
            "synthetic": True,
        }
        if self.determinism == "normalized":
            record["normalized_fingerprint"] = normalized_image_fingerprint(self.data)
        if self.notes:
            record["notes"] = self.notes
        record.update(self.extra)
        return record


def _business_facts(quotation: Quotation, *, language: str = "korean") -> dict[str, object]:
    """Describe the facts a reader of the fixture can actually see.

    ``language`` selects the label language the fixture was authored in: the
    PDF/raster fixtures are ASCII-labelled, the DOCX/XLSX fixtures are Korean.
    """

    assert language in {"ascii", "korean"}
    ascii_labels = language == "ascii"
    if quotation.recipient is None:
        recipient = None
    elif ascii_labels:
        recipient = RECIPIENTS_ASCII[RECIPIENTS.index(quotation.recipient)]
    else:
        recipient = quotation.recipient
    return {
        "quote_number": quotation.quote_number,
        "quote_date": quotation.quote_date,
        "sender": SUPPLIER_NAME_ASCII if ascii_labels else SUPPLIER_NAME,
        "recipient": recipient,
        "items": [
            {
                "description": item.ascii_description() if ascii_labels else item.description,
                "quantity": str(item.quantity),
                "unit": item.unit,
                "unit_price": f"{item.unit_price:,}",
                "amount": f"{item.amount:,}",
            }
            for item in quotation.items
        ],
        "supply_amount": f"{quotation.supply_amount:,}",
        "vat_amount": f"{quotation.vat_amount:,}" if quotation.vat_mode != "unknown" else None,
        "total_amount": f"{quotation.total_amount:,}"
        if quotation.vat_mode != "unknown"
        else None,
        "vat_wording": quotation.vat_label or None,
        "memo": _ascii_memo(quotation.memo) if ascii_labels else quotation.memo,
        "intentionally_missing_facts": [
            name
            for name, value in (
                ("quote_number", quotation.quote_number),
                ("quote_date", quotation.quote_date),
                ("vat_wording", quotation.vat_label or None),
                ("memo", quotation.memo),
            )
            if value is None
        ],
    }


def build_fixtures() -> list[Fixture]:
    quotations = _quotations()
    fixtures: list[Fixture] = []

    def pdf_fixture(
        fixture_id: str,
        filename: str,
        quotation: Quotation,
        *,
        structural: list[str],
        notes: str = "",
        extra: dict[str, object] | None = None,
        with_logo: bool = False,
        logo_png: bytes | None = None,
    ) -> Fixture:
        artifact = author_quotation_pdf(quotation, with_logo=with_logo, logo_png=logo_png)
        return Fixture(
            fixture_id=fixture_id,
            filename=filename,
            media_type="application/pdf",
            source_kind="native_document",
            determinism="byte_identical",
            data=artifact.data,
            structural_facts=structural,
            business_facts=_business_facts(quotation, language="ascii"),
            template_facts=template_only_facts(
                column_order=quotation.column_order, with_logo=with_logo, ascii_labels=True
            ),
            variable_facts=variable_content_facts(quotation),
            vat_mode=quotation.vat_mode,
            page_or_sheet_count=artifact.page_count,
            column_order=quotation.column_order,
            notes=notes,
            extra=extra or {},
        )

    fixtures.append(
        pdf_fixture(
            "F01",
            "f01-native-quotation.pdf",
            quotations["F01"],
            structural=[
                "single page A4 portrait",
                "native extractable text layer (no rasterization)",
                "title, supplier identity, item table, totals, memo",
            ],
            notes="clean native PDF control case",
        )
    )

    # F02 — scanned/image quotation (raster, no text layer)
    source_pdf = author_quotation_pdf(quotations["F02"]).data
    scanned_png, width, height = render_png(source_pdf)
    fixtures.append(
        Fixture(
            fixture_id="F02",
            filename="f02-scanned-quotation.png",
            media_type="image/png",
            source_kind="raster_image",
            determinism="normalized",
            data=scanned_png,
            structural_facts=[
                f"raster page preview {width}x{height}",
                "no text layer: image-only quotation",
                "same layout family as F01 with a different quotation number",
            ],
            business_facts=_business_facts(quotations["F02"], language="ascii"),
            template_facts=template_only_facts(
                column_order=quotations["F02"].column_order, with_logo=False, ascii_labels=True
            ),
            variable_facts=variable_content_facts(quotations["F02"]),
            vat_mode="separate",
            page_or_sheet_count=1,
            column_order=quotations["F02"].column_order,
            notes="byte-level reproducibility is declared normalized: see determinism contract",
            extra={"pixel_width": width, "pixel_height": height},
        )
    )

    # F03 — DOCX
    fixtures.append(
        Fixture(
            fixture_id="F03",
            filename="f03-quotation.docx",
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            source_kind="native_document",
            determinism="byte_identical",
            data=build_docx(quotations["F03"]),
            structural_facts=[
                "OOXML wordprocessing document built from fixed-metadata parts",
                "single w:tbl item table with a border set",
                "paragraph text is extractable without a rasterizer",
            ],
            business_facts=_business_facts(quotations["F03"]),
            template_facts=template_only_facts(
                column_order=quotations["F03"].column_order, with_logo=False
            ),
            variable_facts=variable_content_facts(quotations["F03"]),
            vat_mode="separate",
            page_or_sheet_count=1,
            column_order=quotations["F03"].column_order,
        )
    )

    # F04 — XLSX
    xlsx_rows = _sheet_rows(quotations["F04"])
    fixtures.append(
        Fixture(
            fixture_id="F04",
            filename="f04-quotation.xlsx",
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            source_kind="native_document",
            determinism="byte_identical",
            data=build_xlsx(quotations["F04"]),
            structural_facts=[
                f"single worksheet with {len(xlsx_rows)} populated rows",
                "real cell/row/column structure with numeric quantity, unit price and amount cells",
                "header row carries the item column order",
            ],
            business_facts=_business_facts(quotations["F04"]),
            template_facts=template_only_facts(
                column_order=quotations["F04"].column_order, with_logo=False
            ),
            variable_facts=variable_content_facts(quotations["F04"]),
            vat_mode="separate",
            page_or_sheet_count=1,
            column_order=quotations["F04"].column_order,
        )
    )

    # F05 — column-order variant
    fixtures.append(
        pdf_fixture(
            "F05",
            "f05-column-order-variant.pdf",
            quotations["F05"],
            structural=[
                "item table uses the variant column order",
                "content is identical to the default-order family; only the presentation order changes",
            ],
            extra={"column_order_variant": True},
            notes="separates template structure from per-quote content",
        )
    )

    # F06/F07/F08 — VAT presentation modes
    fixtures.append(
        pdf_fixture(
            "F06",
            "f06-vat-separate.pdf",
            quotations["F06"],
            structural=["supply amount and VAT are presented on separate lines"],
            extra={"vat_variant": "separate"},
        )
    )
    fixtures.append(
        pdf_fixture(
            "F07",
            "f07-vat-inclusive.pdf",
            quotations["F07"],
            structural=["VAT-inclusive presentation: no separate VAT figure is printed"],
            extra={"vat_variant": "inclusive"},
        )
    )
    fixtures.append(
        pdf_fixture(
            "F08",
            "f08-vat-exempt.pdf",
            quotations["F08"],
            structural=["tax-exempt presentation: VAT line is absent and 면세 wording is used"],
            extra={"vat_variant": "exempt"},
        )
    )

    # F09 — missing fields
    fixtures.append(
        pdf_fixture(
            "F09",
            "f09-missing-fields.pdf",
            quotations["F09"],
            structural=[
                "quotation number, date, VAT wording and memo are absent by design",
                "ground truth keeps those facts unknown instead of inventing values",
            ],
            extra={"unknown_stays_unknown": True},
            notes="hallucination trap: absent facts must not be fabricated",
        )
    )

    # F10 — fixed memo / default terms
    fixtures.append(
        pdf_fixture(
            "F10",
            "f10-fixed-memo-terms.pdf",
            quotations["F10"],
            structural=[
                "default terms block is printed beneath the item table",
                "terms text is template-fixed, not per-quote content",
            ],
            extra={
                "fixed_terms": FIXED_TERMS,
                "template_fixed_terms": list(FIXED_TERMS.keys()),
            },
            notes="terms are declared template-only facts for the cloner",
        )
    )

    # F11 — synthetic logo card (no real corporate mark)
    logo_png, logo_width, logo_height = render_png(author_logo_pdf().data)
    fixtures.append(
        Fixture(
            fixture_id="F11",
            filename="f11-simple-logo.png",
            media_type="image/png",
            source_kind="raster_image",
            determinism="normalized",
            data=logo_png,
            structural_facts=[
                f"raster logo card {logo_width}x{logo_height}",
                "no real corporate mark: synthetic placeholder only",
                "usable as a template-only logo asset",
            ],
            business_facts={
                "synthetic_marker": SYNTHETIC_MARKER,
                "logo_text": "PADIEM TEST / SYNTHETIC QUOTE",
            },
            template_facts=[
                "logo placement is a template-only fact",
                "logo pixels carry no per-quote business value",
            ],
            variable_facts=[],
            vat_mode="not_applicable",
            page_or_sheet_count=1,
            column_order=(),
            notes="byte-level reproducibility is declared normalized: see determinism contract",
            extra={"pixel_width": logo_width, "pixel_height": logo_height},
        )
    )

    # F12 — multi-page
    fixtures.append(
        pdf_fixture(
            "F12",
            "f12-multipage-quotation.pdf",
            quotations["F12"],
            structural=[
                "item table spans more than one page",
                "the header row repeats on each page",
            ],
            extra={"multipage": True},
            notes="page count is asserted to be at least two",
        )
    )

    # F13 — degraded/skewed scan
    degraded = degrade_png(scanned_png)
    fixtures.append(
        Fixture(
            fixture_id="F13",
            filename="f13-degraded-scan.png",
            media_type="image/png",
            source_kind="raster_image",
            determinism="normalized",
            data=degraded,
            structural_facts=[
                "downscaled, low-quality re-upscaled and slightly rotated page",
                "degradation is fixed and reproducible, not random noise",
            ],
            business_facts=_business_facts(quotations["F13"], language="ascii"),
            template_facts=template_only_facts(
                column_order=quotations["F13"].column_order, with_logo=False, ascii_labels=True
            ),
            variable_facts=variable_content_facts(quotations["F13"]),
            vat_mode="separate",
            page_or_sheet_count=1,
            column_order=quotations["F13"].column_order,
            notes="vision robustness fixture; no model is called by this generator",
            extra={"degradation": "downscale_x4+rotate_1.8deg"},
        )
    )

    return fixtures


def build_manifest(fixtures: list[Fixture]) -> dict[str, object]:
    return {
        "corpus_id": CORPUS_ID,
        "issue": "#3205",
        "parent_issue": "#3186",
        "related_issues": ["#3180", "#3143"],
        "generator": "tests/fixtures/b66_e2e_corpus/generate_b66_e2e_fixtures.py",
        "generator_version": GENERATOR_VERSION,
        "synthetic": True,
        "non_sensitive": True,
        "synthetic_marker": SYNTHETIC_MARKER,
        "frozen_at": "before-any-model-call",
        "model_calls": 0,
        "network_calls": 0,
        "quote_core_calculation_authority": True,
        "fixture_totals_are_expected_source_facts_only": True,
        "determinism_contract": {
            "byte_identical": [
                "every PDF, DOCX and XLSX fixture is written by a pure-Python writer "
                "and is expected to reproduce byte-for-byte on any platform with the "
                "same pinned dependency set"
            ],
            "normalized": [
                "every PNG fixture depends on the pinned pypdfium2/pdfium and Pillow "
                "builds, so exact bytes are recorded for integrity while "
                "cross-platform reproducibility is asserted through "
                "normalized_fingerprint (8x8 quantized luminance grid)"
            ],
        },
        "synthetic_identity": synthetic_identity(),
        "fixtures": [fixture.to_manifest() for fixture in fixtures],
    }


def generate(output_dir: Path) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    fixtures = build_fixtures()
    for fixture in fixtures:
        (output_dir / fixture.filename).write_bytes(fixture.data)
    manifest = build_manifest(fixtures)
    (output_dir / MANIFEST_NAME).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=CORPUS_DIR,
        help="target directory (defaults to the committed corpus directory)",
    )
    arguments = parser.parse_args()
    manifest = generate(arguments.output)
    print(f"B66_E2E_FIXTURE_COUNT={len(manifest['fixtures'])}")
    print(f"B66_E2E_FIXTURE_ROOT={arguments.output}")
    print("MODEL_CALLS=0")
    print("NETWORK_CALLS=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
