#!/usr/bin/env python3
"""Deterministic generator for the B66 quotation E2E fixture corpus (#3205).

Purpose
-------
Produce the synthetic, non-sensitive Korean quotation corpus that the Business
66 template-cloner acceptance run (#3186) needs, without any model call,
network call, or production mutation.

Design
------
* Every fixture is produced by this generator; no hand-edited binaries and no
  ``%TEMP%`` benchmark leftovers are used as a source.
* The native PDF family is authored with ReportLab's built-in Korean CID font
  (``UnicodeCIDFont("HYSMyeongJo-Medium")``). The repository's embedded OFL
  authoring font is a deliberate 106-character subset that cannot carry a real
  Korean quotation, and no font may be downloaded, so the fixture path uses the
  CID route instead.
* Raster fixtures are rendered from *those same Korean quotation documents*
  through ``padiem_ai_core.pdf_render`` (pypdfium2). Each raster fixture has its
  Korean source PDF committed alongside it, so the "scan came from the Korean
  source" claim is directly checkable.
* DOCX/XLSX are written by this module as fixed-metadata OOXML ZIP archives.

Scope note: this generator is fixture tooling. It does not change, and does not
widen, any product PDF-authoring authority.

Determinism contract
--------------------
Each fixture declares ``determinism``:

* ``byte_identical`` — the writer is pure Python and the bytes are expected to
  reproduce exactly on any platform that has the same pinned dependency set.
* ``normalized`` — the raster pixels depend on which CJK font the rasterizer can
  resolve on the running platform, so exact bytes are recorded for committed
  integrity and reproducibility is asserted within the generating environment
  through ``normalized_fingerprint`` (8x8 quantized luminance grid). Nothing
  here silently allows a drifting SHA-256: the class is explicit, and the
  fingerprint is defined and tested.
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
from xml.sax.saxutils import escape

CORPUS_ID = "b66-quotation-e2e-v1"
GENERATOR_VERSION = "2"
MANIFEST_NAME = "manifest.json"

# Fixed ZIP member metadata keeps the OOXML archives byte-identical between
# runs; the DOS epoch is the value ``zipfile`` itself uses for "no date".
FIXED_ZIP_DATE = (1980, 1, 1, 0, 0, 0)

SYNTHETIC_MARKER = "SYNTHETIC TEST DATA / 실사용 금지"

SUPPLIER_NAME = "주식회사 테스트상사"
SUPPLIER_BIZ = "000-00-00000"
SUPPLIER_ADDRESS = "광주광역시 테스트구 견적로 123"
SUPPLIER_PHONE = "062-000-0000"

RECIPIENTS = (
    "주식회사 예시테크",
    "주식회사 샘플산업",
    "주식회사 견본물산",
)

# Field labels. The fixture family carries real Korean labels in every format;
# the manifest asserts these tokens against the extracted document text.
KOREAN_LABELS = {
    "title": "견적서",
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
    "address": "주소",
    "business_number": "사업자번호",
    "phone": "전화",
}

# ReportLab ships the Adobe-Korea1 CID font *metrics* as pure Python data: the
# PDF references the font by name and nothing is fetched at build time. This is
# the documented built-in Korean route, verified in this repository's CI.
CID_FONT_NAME = "HYSMyeongJo-Medium"
CID_FONT_SOURCE = "reportlab_builtin_adobe_korea1_cid"

CORPUS_DIR = Path(__file__).resolve().parent

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


_WIDE_KINDS = ("배관", "밸브", "플랜지", "가스켓", "볼트", "너트", "와셔", "호스")
_WIDE_MATERIALS = ("스테인리스", "알루미늄", "황동", "주철")


def _wide_items() -> tuple[LineItem, ...]:
    """F12 needs enough rows to span more than one page."""

    items = []
    for index in range(28):
        kind = _WIDE_KINDS[index % len(_WIDE_KINDS)]
        material = _WIDE_MATERIALS[index % len(_WIDE_MATERIALS)]
        items.append(
            LineItem(
                f"{material} {kind} 규격 {index + 1}0mm",
                index + 2,
                "개",
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
        "F11": Quotation(None, None, None, (), "unknown", None),
        "F12": Quotation("Q-2026-3012", "2026-03-16", RECIPIENTS[1], _wide_items(), "separate", "납기 협의"),
        "F13": Quotation("Q-2026-3013", "2026-03-17", RECIPIENTS[2], _default_items(), "separate", "납기 협의"),
    }


FIXED_TERMS = {
    "납기": "발주 후 7일",
    "결제조건": "협의",
    "유효기간": "견적일로부터 30일",
}

LOGO_TEXT = "PADIEM TEST / SYNTHETIC QUOTE"


# --------------------------------------------------------------------------
# shared fact projections
# --------------------------------------------------------------------------


def synthetic_identity() -> dict[str, str]:
    return {
        "supplier_name": SUPPLIER_NAME,
        "supplier_business_number": SUPPLIER_BIZ,
        "supplier_address": SUPPLIER_ADDRESS,
        "supplier_phone": SUPPLIER_PHONE,
        "synthetic_marker": SYNTHETIC_MARKER,
    }


def template_only_facts(*, column_order: tuple[str, ...], with_logo: bool) -> list[str]:
    facts = [
        "item column order: " + " | ".join(column_order),
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


# --------------------------------------------------------------------------
# Korean PDF authoring (fixture-local, ReportLab CID route)
# --------------------------------------------------------------------------

_CID_REGISTERED = False


def _reportlab() -> dict[str, object]:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.platypus import (
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    return {
        "A4": A4,
        "Paragraph": Paragraph,
        "ParagraphStyle": ParagraphStyle,
        "SimpleDocTemplate": SimpleDocTemplate,
        "Spacer": Spacer,
        "TA_LEFT": TA_LEFT,
        "Table": Table,
        "TableStyle": TableStyle,
        "UnicodeCIDFont": UnicodeCIDFont,
        "colors": colors,
        "mm": mm,
        "pdfmetrics": pdfmetrics,
    }


def _cid_font(reportlab: dict[str, object]) -> str:
    global _CID_REGISTERED
    if not _CID_REGISTERED:
        reportlab["pdfmetrics"].registerFont(reportlab["UnicodeCIDFont"](CID_FONT_NAME))
        _CID_REGISTERED = True
    return CID_FONT_NAME


def author_korean_pdf(
    *,
    heading: str,
    lines: list[str],
    rows: tuple[tuple[str, ...], ...] = (),
    title: str,
    subject: str,
    keywords: tuple[str, ...],
) -> bytes:
    """Author one deterministic Korean PDF through the ReportLab CID route."""

    reportlab = _reportlab()
    font = _cid_font(reportlab)
    heading_style = reportlab["ParagraphStyle"](
        "B66AuthoringHeading",
        fontName=font,
        fontSize=18,
        leading=24,
        spaceAfter=8,
        alignment=reportlab["TA_LEFT"],
    )
    body_style = reportlab["ParagraphStyle"](
        "B66AuthoringBody",
        fontName=font,
        fontSize=10,
        leading=15,
        spaceAfter=6,
        alignment=reportlab["TA_LEFT"],
    )
    cell_style = reportlab["ParagraphStyle"](
        "B66AuthoringCell", parent=body_style, fontSize=9, leading=12
    )

    story: list[object] = [reportlab["Paragraph"](escape(heading), heading_style)]
    for line in lines:
        story.append(reportlab["Paragraph"](escape(line), body_style))
    if rows:
        column_count = len(rows[0])
        total_width = 170 * reportlab["mm"]
        column_width = total_width / column_count
        table = reportlab["Table"](
            [
                [reportlab["Paragraph"](escape(cell), cell_style) for cell in row]
                for row in rows
            ],
            colWidths=(column_width,) * column_count,
            repeatRows=1,
        )
        table.setStyle(
            reportlab["TableStyle"](
                [
                    ("FONTNAME", (0, 0), (-1, -1), font),
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

    output = BytesIO()
    document = reportlab["SimpleDocTemplate"](
        output,
        pagesize=reportlab["A4"],
        leftMargin=18 * reportlab["mm"],
        rightMargin=18 * reportlab["mm"],
        topMargin=18 * reportlab["mm"],
        bottomMargin=18 * reportlab["mm"],
        # ``invariant=1`` pins document identifiers and timestamps, which is what
        # makes the authored bytes reproducible.
        invariant=1,
        title=title,
        author="Padiem B66 fixture generator",
        subject=subject,
        creator="Padiem B66 fixture generator",
        producer="ReportLab",
        keywords=" ".join(keywords),
    )
    document.build(story)
    return output.getvalue()


def _table_rows(quotation: Quotation) -> tuple[tuple[str, ...], ...]:
    rows = [tuple(quotation.column_order)]
    for item in quotation.items:
        values = {
            "품목": item.description,
            "수량": f"{item.quantity}",
            "단가": f"{item.unit_price:,}",
            "금액": f"{item.amount:,}",
        }
        rows.append(tuple(values[column] for column in quotation.column_order))
    return tuple(rows)


def _pdf_lines(quotation: Quotation, *, with_terms: bool = False) -> list[str]:
    lines: list[str] = [SYNTHETIC_MARKER]
    lines.append(
        f"{KOREAN_LABELS['supplier']}: {SUPPLIER_NAME} / "
        f"{KOREAN_LABELS['business_number']}: {SUPPLIER_BIZ}"
    )
    lines.append(
        f"{KOREAN_LABELS['address']}: {SUPPLIER_ADDRESS} / "
        f"{KOREAN_LABELS['phone']}: {SUPPLIER_PHONE}"
    )
    if quotation.recipient:
        lines.append(f"{KOREAN_LABELS['recipient']}: {quotation.recipient}")
    if quotation.quote_number:
        lines.append(f"{KOREAN_LABELS['quote_number']}: {quotation.quote_number}")
    if quotation.quote_date:
        lines.append(f"{KOREAN_LABELS['quote_date']}: {quotation.quote_date}")
    lines.append(f"{KOREAN_LABELS['supply']}: {quotation.supply_amount:,}")
    if quotation.vat_mode == "separate":
        lines.append(
            f"{KOREAN_LABELS['vat']}: {quotation.vat_amount:,} ({quotation.vat_label})"
        )
    elif quotation.vat_mode in {"inclusive", "exempt"}:
        lines.append(f"{KOREAN_LABELS['vat']}: {quotation.vat_label}")
    if quotation.vat_mode != "unknown":
        lines.append(f"{KOREAN_LABELS['total']}: {quotation.total_amount:,}")
    if quotation.memo:
        lines.append(f"{KOREAN_LABELS['memo']}: {quotation.memo}")
    if with_terms:
        lines.append("기본 조건")
        for term, value in FIXED_TERMS.items():
            lines.append(f"{term}: {value}")
    return lines


def author_quotation_pdf(quotation: Quotation, *, with_terms: bool = False) -> bytes:
    return author_korean_pdf(
        heading=KOREAN_LABELS["title"],
        lines=_pdf_lines(quotation, with_terms=with_terms),
        rows=_table_rows(quotation) if quotation.items else (),
        title="B66 synthetic quotation fixture",
        subject=f"합성 견적서 {quotation.quote_number or '번호 없음'}",
        keywords=("b66", "synthetic", "fixture", "quotation", "3205"),
    )


def author_logo_pdf() -> bytes:
    """Author the synthetic logo card used by fixture F11."""

    return author_korean_pdf(
        heading=LOGO_TEXT,
        lines=[SYNTHETIC_MARKER, "로고 위치는 템플릿 고정 요소입니다"],
        title="B66 synthetic logo fixture",
        subject="합성 로고",
        keywords=("b66", "synthetic", "logo", "fixture", "3205"),
    )


# --------------------------------------------------------------------------
# OOXML authoring (DOCX / XLSX)
# --------------------------------------------------------------------------


def _xml_header() -> str:
    return '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'


def _zip_part(name: str, data: str | bytes) -> tuple[zipfile.ZipInfo, bytes]:
    info = zipfile.ZipInfo(filename=name, date_time=FIXED_ZIP_DATE)
    info.compress_type = zipfile.ZIP_DEFLATED
    # ``zipfile`` derives the archive's creator platform from the running
    # interpreter (FAT on Windows, Unix elsewhere), which changes the
    # "version made by" field and therefore the whole archive digest. Pin it so
    # the OOXML fixtures are byte-identical on every platform.
    info.create_system = 0
    info.create_version = 20
    info.extract_version = 20
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
    body: list[str] = []

    def paragraph(value: str) -> str:
        return f"<w:p><w:r><w:t>{escape(value)}</w:t></w:r></w:p>"

    body.append(paragraph(KOREAN_LABELS["title"]))
    body.append(paragraph(SYNTHETIC_MARKER))
    body.append(
        paragraph(
            f"{KOREAN_LABELS['supplier']}: {SUPPLIER_NAME} / "
            f"{KOREAN_LABELS['business_number']}: {SUPPLIER_BIZ}"
        )
    )
    body.append(
        paragraph(f"{KOREAN_LABELS['address']}: {SUPPLIER_ADDRESS} / {KOREAN_LABELS['phone']}: {SUPPLIER_PHONE}")
    )
    if quotation.recipient:
        body.append(paragraph(f"{KOREAN_LABELS['recipient']}: {quotation.recipient}"))
    if quotation.quote_number:
        body.append(paragraph(f"{KOREAN_LABELS['quote_number']}: {quotation.quote_number}"))
    if quotation.quote_date:
        body.append(paragraph(f"{KOREAN_LABELS['quote_date']}: {quotation.quote_date}"))

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
        body.append(
            paragraph(
                f"{KOREAN_LABELS['supply']}: {quotation.supply_amount:,} / "
                f"{KOREAN_LABELS['vat']}: {quotation.vat_amount:,}"
            )
        )
        body.append(paragraph(f"{KOREAN_LABELS['total']}: {quotation.total_amount:,}"))
    elif quotation.vat_mode in {"inclusive", "exempt"}:
        body.append(
            paragraph(f"{KOREAN_LABELS['total']}: {quotation.total_amount:,} ({quotation.vat_label})")
        )
    if quotation.memo:
        body.append(paragraph(f"{KOREAN_LABELS['memo']}: {quotation.memo}"))
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
    rows: list[list[str | int]] = [[KOREAN_LABELS["title"]], [SYNTHETIC_MARKER]]
    rows.append([KOREAN_LABELS["supplier"], SUPPLIER_NAME, KOREAN_LABELS["business_number"], SUPPLIER_BIZ])
    rows.append([KOREAN_LABELS["address"], SUPPLIER_ADDRESS, KOREAN_LABELS["phone"], SUPPLIER_PHONE])
    if quotation.recipient:
        rows.append([KOREAN_LABELS["recipient"], quotation.recipient])
    if quotation.quote_number:
        rows.append([KOREAN_LABELS["quote_number"], quotation.quote_number])
    if quotation.quote_date:
        rows.append([KOREAN_LABELS["quote_date"], quotation.quote_date])
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
    rows.append([KOREAN_LABELS["supply"], quotation.supply_amount])
    if quotation.vat_mode != "unknown":
        rows.append([KOREAN_LABELS["vat"], quotation.vat_amount, quotation.vat_label])
    rows.append([KOREAN_LABELS["total"], quotation.total_amount])
    if quotation.memo:
        rows.append([KOREAN_LABELS["memo"], quotation.memo])
    return rows


def _sheet_xml(quotation: Quotation) -> str:
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

    The exact bytes of a raster depend on which CJK font the rasterizer can
    resolve and on the Pillow build, so reproducibility is asserted through a
    coarse luminance grid: the image is reduced to ``grid`` x ``grid`` cells,
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


def extracted_pdf_text(pdf_bytes: bytes) -> str:
    """Native text of every page, through the canonical pypdf reader."""

    pypdf = import_module("pypdf")
    reader = pypdf.PdfReader(BytesIO(pdf_bytes))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def assert_korean_labels(pdf_bytes: bytes, *, required: tuple[str, ...]) -> list[str]:
    """Fail generation when a Korean source document lost its field labels."""

    text = extracted_pdf_text(pdf_bytes)
    missing = [label for label in required if label not in text]
    if missing:
        raise ValueError(
            "Korean quotation source is missing field labels: " + ", ".join(missing)
        )
    return list(required)


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


def _business_facts(quotation: Quotation) -> dict[str, object]:
    return {
        "quote_number": quotation.quote_number,
        "quote_date": quotation.quote_date,
        "sender": SUPPLIER_NAME,
        "recipient": quotation.recipient,
        "items": [
            {
                "description": item.description,
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
        "memo": quotation.memo,
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


# Labels every Korean quotation document must carry once its fields are present.
REQUIRED_LABELS_ALWAYS = (
    KOREAN_LABELS["title"],
    KOREAN_LABELS["supplier"],
    KOREAN_LABELS["supply"],
)


def _quotation_source(
    fixture_id: str, filename: str, quotation: Quotation, *, with_terms: bool = False
) -> tuple[bytes, list[str]]:
    """Author one Korean quotation PDF and prove its labels survived."""

    required = REQUIRED_LABELS_ALWAYS + (
        KOREAN_LABELS["recipient"],
        KOREAN_LABELS["item"],
        KOREAN_LABELS["quantity"],
        KOREAN_LABELS["amount"],
    )
    if quotation.quote_number:
        required = required + (KOREAN_LABELS["quote_number"],)
    if quotation.vat_mode != "unknown":
        required = required + (KOREAN_LABELS["vat"], KOREAN_LABELS["total"])
    pdf_bytes = author_quotation_pdf(quotation, with_terms=with_terms)
    return pdf_bytes, assert_korean_labels(pdf_bytes, required=required)


def build_fixtures() -> tuple[list[Fixture], list[dict[str, object]]]:
    quotations = _quotations()
    fixtures: list[Fixture] = []
    raster_sources: list[dict[str, object]] = []

    def pdf_fixture(
        fixture_id: str,
        filename: str,
        quotation: Quotation,
        *,
        structural: list[str],
        notes: str = "",
        extra: dict[str, object] | None = None,
        with_terms: bool = False,
    ) -> Fixture:
        pdf_bytes, _labels = _quotation_source(
            fixture_id, filename, quotation, with_terms=with_terms
        )
        page_count = len(import_module("pypdf").PdfReader(BytesIO(pdf_bytes)).pages)
        return Fixture(
            fixture_id=fixture_id,
            filename=filename,
            media_type="application/pdf",
            source_kind="native_document",
            determinism="byte_identical",
            data=pdf_bytes,
            structural_facts=structural,
            business_facts=_business_facts(quotation),
            template_facts=template_only_facts(
                column_order=quotation.column_order, with_logo=False
            ),
            variable_facts=variable_content_facts(quotation),
            vat_mode=quotation.vat_mode,
            page_or_sheet_count=page_count,
            column_order=quotation.column_order,
            notes=notes,
            extra=extra or {},
        )

    def raster_fixture(
        fixture_id: str,
        filename: str,
        source_filename: str,
        quotation: Quotation,
        *,
        structural: list[str],
        degrade: bool,
        notes: str = "",
        extra: dict[str, object] | None = None,
    ) -> Fixture:
        source_pdf, labels = _quotation_source(fixture_id, source_filename, quotation)
        png_bytes, width, height = render_png(source_pdf)
        raster_sources.append(
            {
                "fixture_id": fixture_id,
                "relative_path": source_filename,
                "media_type": "application/pdf",
                "byte_size": len(source_pdf),
                "sha256": hashlib.sha256(source_pdf).hexdigest(),
                "korean_labels_verified": labels,
                "generated_by": "author_korean_pdf via ReportLab CID font",
                "cjk_font": CID_FONT_NAME,
                "cjk_font_source": CID_FONT_SOURCE,
            }
        )
        if degrade:
            png_bytes = degrade_png(png_bytes)
        return Fixture(
            fixture_id=fixture_id,
            filename=filename,
            media_type="image/png",
            source_kind="raster_image",
            determinism="normalized",
            data=png_bytes,
            structural_facts=structural,
            business_facts=_business_facts(quotation),
            template_facts=template_only_facts(
                column_order=quotation.column_order, with_logo=False
            ),
            variable_facts=variable_content_facts(quotation),
            vat_mode=quotation.vat_mode,
            page_or_sheet_count=1,
            column_order=quotation.column_order,
            notes=notes,
            extra={
                "raster_source_path": source_filename,
                "raster_source_sha256": hashlib.sha256(source_pdf).hexdigest(),
                "raster_source_korean_labels": labels,
                "pixel_width": width,
                "pixel_height": height,
                **(extra or {}),
            },
        )

    fixtures.append(
        pdf_fixture(
            "F01",
            "f01-native-quotation.pdf",
            quotations["F01"],
            structural=[
                "single page A4 portrait",
                "native extractable Korean text layer (no rasterization)",
                "title, supplier identity, item table, totals, memo",
            ],
            notes="clean native Korean PDF control case",
        )
    )

    fixtures.append(
        raster_fixture(
            "F02",
            "f02-scanned-quotation.png",
            "f02-scanned-quotation.source.pdf",
            quotations["F02"],
            structural=[
                "raster page preview with no text layer",
                "rendered from the committed Korean quotation source document",
                "same layout family as F01 with a different quotation number",
            ],
            degrade=False,
            notes=(
                "byte-level reproducibility is declared normalized: raster pixels "
                "depend on the CJK font the rasterizer resolves; see determinism contract"
            ),
        )
    )

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
                "Korean paragraph text is extractable without a rasterizer",
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
                "header row carries the Korean item column order",
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
            with_terms=True,
            notes="terms are declared template-only facts for the cloner",
        )
    )

    logo_png, logo_width, logo_height = render_png(author_logo_pdf())
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
                "logo_text": LOGO_TEXT,
            },
            template_facts=[
                "logo placement is a template-only fact",
                "logo pixels carry no per-quote business value",
            ],
            variable_facts=[],
            vat_mode="not_applicable",
            page_or_sheet_count=1,
            column_order=(),
            notes=(
                "byte-level reproducibility is declared normalized: raster pixels "
                "depend on the CJK font the rasterizer resolves; see determinism contract"
            ),
            extra={"pixel_width": logo_width, "pixel_height": logo_height},
        )
    )

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

    fixtures.append(
        raster_fixture(
            "F13",
            "f13-degraded-scan.png",
            "f13-degraded-scan.source.pdf",
            quotations["F13"],
            structural=[
                "downscaled, low-quality re-upscaled and slightly rotated page",
                "rendered from the committed Korean quotation source document",
                "degradation is fixed and reproducible, not random noise",
            ],
            degrade=True,
            extra={"degradation": "downscale_x4+rotate_1.8deg"},
            notes=(
                "vision robustness fixture; raster pixels depend on the CJK font the "
                "rasterizer resolves; no model is called by this generator"
            ),
        )
    )

    return fixtures, raster_sources


def build_manifest(
    fixtures: list[Fixture], raster_sources: list[dict[str, object]]
) -> dict[str, object]:
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
        "korean_fidelity": {
            "native_pdf_labels": sorted(KOREAN_LABELS.values()),
            "font": CID_FONT_NAME,
            "font_source": CID_FONT_SOURCE,
            "download_required": False,
            "raster_sources": "each raster fixture commits the Korean quotation PDF it was rendered from",
        },
        "determinism_contract": {
            "byte_identical": [
                "every PDF, DOCX and XLSX fixture is written by a pure-Python writer "
                "and is expected to reproduce byte-for-byte on any platform with the "
                "same pinned dependency set"
            ],
            "normalized": [
                "every PNG fixture's pixels depend on which CJK font the pinned "
                "pypdfium2/pdfium and Pillow builds can resolve on the running "
                "platform, so exact bytes are recorded for committed integrity while "
                "reproducibility is asserted within the generating environment through "
                "normalized_fingerprint (8x8 quantized luminance grid)"
            ],
        },
        "synthetic_identity": synthetic_identity(),
        "fixtures": [fixture.to_manifest() for fixture in fixtures],
        "raster_sources": raster_sources,
    }


def generate(output_dir: Path) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    fixtures, raster_sources = build_fixtures()
    for fixture in fixtures:
        (output_dir / fixture.filename).write_bytes(fixture.data)
    for source in raster_sources:
        # The source PDFs are written by the raster fixture builder; re-authoring
        # them here keeps the manifest and the files in step.
        quotation = _quotations()[source["fixture_id"]]
        (output_dir / source["relative_path"]).write_bytes(
            author_quotation_pdf(quotation)
        )
    manifest = build_manifest(fixtures, raster_sources)
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
    print(f"B66_E2E_RASTER_SOURCE_COUNT={len(manifest['raster_sources'])}")
    print(f"B66_E2E_FIXTURE_ROOT={arguments.output}")
    print(f"KOREAN_PDF_FONT={manifest['korean_fidelity']['font']}")
    print("MODEL_CALLS=0")
    print("NETWORK_CALLS=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
