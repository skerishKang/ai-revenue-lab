"""#3933 WEB-FIRST deterministic, scoped Hark XLSX quote editing.

Limited to a verified one-sheet quote footprint; NEVER a generic Office/PDF
renderer. Bytes in, bytes out; caller must independently obtain exact P01
write approval and own the private workcopy before invoking.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from decimal import Decimal
from io import BytesIO
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile, ZipInfo, ZIP_DEFLATED

from padiem_ai_core.document_normalization import (
    DocumentNormalizationError, validate_ooxml_archive,
)

MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
MAIN = "{" + MAIN_NS + "}"
ET.register_namespace("", MAIN_NS)
_SOURCE_MAX = 1_048_576
_PACKAGE_MAX = 8_388_608
_SHEET = "xl/worksheets/sheet1.xml"
_REQUIRED = frozenset({"A1", "B4", "B5", "B6", "B7"})
_ALLOWED_PART = re.compile(
    r"^(?:\[Content_Types\]\.xml|_rels/\.rels|"
    r"xl/workbook\.xml|xl/_rels/workbook\.xml\.rels|"
    r"xl/worksheets/sheet1\.xml|xl/styles\.xml|"
    r"xl/sharedStrings\.xml|xl/theme/theme1\.xml|"
    r"docProps/(?:app|core)\.xml)$"
)
_BANNED = ("external", "connection", "vba", "macro", "activex", "ole",
           "pivot", "embedding", "drawing", "chart", "query", "calcchain")


class WebQuoteEditUnsupported(ValueError):
    """Reject unsupported workbook layout/fidelity or attempted broad edits."""


@dataclass(frozen=True, slots=True)
class WebQuoteRevision:
    source_sha256: str
    revised_sha256: str
    revised_xlsx: bytes
    requested_school_name: str
    requested_supply_amount: int
    vat_amount: int
    total_amount: int
    output_format: str = "xlsx"
    print_pdf_fidelity: str = "UNSUPPORTED_REQUIRES_APPROVED_RENDERER"


def _load(data: bytes):
    if type(data) is not bytes or not 100 <= len(data) <= _SOURCE_MAX:
        raise WebQuoteEditUnsupported("XLSX_SIZE_OUTSIDE_SUPPORTED_BOUND")
    try:
        validate_ooxml_archive(data)
        with ZipFile(BytesIO(data)) as package:
            infos = package.infolist()
            names = [info.filename for info in infos]
            if (len(names) != len(set(names)) or len(infos) > 25
                    or any(not _ALLOWED_PART.fullmatch(name) for name in names)
                    or any(word in name.lower() for name in names for word in _BANNED)
                    or any(info.flag_bits & 0x1 for info in infos)
                    or sum(item.file_size for item in infos) > _PACKAGE_MAX
                    or package.testzip() is not None
                    or not {"[Content_Types].xml", "xl/workbook.xml", _SHEET} <= set(names)):
                raise WebQuoteEditUnsupported("XLSX_UNSUPPORTED_OR_UNSAFE_PACKAGE")
            parts = {name: package.read(name) for name in names}
    except (BadZipFile, KeyError, DocumentNormalizationError, OSError, ValueError) as exc:
        if isinstance(exc, WebQuoteEditUnsupported):
            raise
        raise WebQuoteEditUnsupported("XLSX_CORRUPT_OR_UNSAFE") from exc
    for name, blob in parts.items():
        if b"<!DOCTYPE" in blob.upper() or b"<!ENTITY" in blob.upper():
            raise WebQuoteEditUnsupported("XLSX_XML_ENTITIES_UNSUPPORTED")
    try:
        sheet = ET.fromstring(parts[_SHEET])
        book = ET.fromstring(parts["xl/workbook.xml"])
    except ET.ParseError as exc:
        raise WebQuoteEditUnsupported("XLSX_XML_INVALID") from exc
    if sheet.tag != MAIN + "worksheet" or book.tag != MAIN + "workbook":
        raise WebQuoteEditUnsupported("XLSX_UNKNOWN_XML_SCHEMA")
    # A ZIP with plausible XML is NOT enough to be a genuine Excel workbook.
    # Require canonical OOXML package, workbook relationship and content types.
    try:
        rel_ns = "{http://schemas.openxmlformats.org/package/2006/relationships}"
        office_rel = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
        content_ns = "{http://schemas.openxmlformats.org/package/2006/content-types}"
        package_rels = ET.fromstring(parts["_rels/.rels"])
        workbook_rels = ET.fromstring(parts["xl/_rels/workbook.xml.rels"])
        content = ET.fromstring(parts["[Content_Types].xml"])
        styles = ET.fromstring(parts["xl/styles.xml"])
        relations = list(package_rels.iter(rel_ns + "Relationship"))
        if not any(r.get("Target") == "xl/workbook.xml"
                   and r.get("Type", "").endswith("/officeDocument")
                   for r in relations):
            raise WebQuoteEditUnsupported("XLSX_MISSING_OFFICE_RELATIONSHIP")
        sheets = list(book.iter(MAIN + "sheet"))
        if len(sheets) != 1:
            raise WebQuoteEditUnsupported("XLSX_MULTI_SHEET_OR_PROTECTED")
        sheet_rel = sheets[0].get(office_rel + "id")
        if not sheet_rel or not any(
            r.get("Id") == sheet_rel
            and r.get("Target") == "worksheets/sheet1.xml"
            and r.get("Type", "").endswith("/worksheet")
            for r in workbook_rels.iter(rel_ns + "Relationship")
        ):
            raise WebQuoteEditUnsupported("XLSX_SHEET_RELATIONSHIP_INVALID")
        types = {node.get("PartName"): node.get("ContentType")
                 for node in content.iter(content_ns + "Override")}
        if (not types.get("/xl/workbook.xml", "").endswith(
                    "spreadsheetml.sheet.main+xml")
                or not types.get("/xl/worksheets/sheet1.xml", "").endswith(
                    "spreadsheetml.worksheet+xml")
                or styles.tag != MAIN + "styleSheet"
                or styles.find(MAIN + "cellXfs") is None):
            raise WebQuoteEditUnsupported("XLSX_INVALID_PACKAGE_MANIFEST")
        style_count = len(list(styles.find(MAIN + "cellXfs")))
        if style_count < 1 or any(
            int(c.get("s", "0")) >= style_count
            for c in sheet.iter(MAIN + "c")
        ):
            raise WebQuoteEditUnsupported("XLSX_STYLE_REFERENCE_INVALID")
    except KeyError as exc:
        raise WebQuoteEditUnsupported("XLSX_REQUIRED_RELATIONSHIPS_MISSING") from exc
    except (ET.ParseError, ValueError) as exc:
        if isinstance(exc, WebQuoteEditUnsupported):
            raise
        raise WebQuoteEditUnsupported("XLSX_RELATIONSHIP_OR_STYLE_INVALID") from exc
    # Reject formula-sharing, external references, protected sheets and
    # nontrivial render targets until a verified Office converter is wired.
    sheets = list(book.iter(MAIN + "sheet"))
    if len(sheets) != 1 or sheet.find(MAIN + "sheetProtection") is not None:
        raise WebQuoteEditUnsupported("XLSX_MULTI_SHEET_OR_PROTECTED")
    if any(node is not None for node in (
        sheet.find(MAIN + "drawing"), sheet.find(MAIN + "legacyDrawing"),
        sheet.find(MAIN + "oleObjects"), sheet.find(MAIN + "tableParts"),
    )):
        raise WebQuoteEditUnsupported("XLSX_ADVANCED_PRINT_ASSETS_UNSUPPORTED")
    return parts, sheet


def _cells(sheet: ET.Element):
    cells = {}
    for element in sheet.iter(MAIN + "c"):
        ref = element.get("r")
        if not isinstance(ref, str) or ref in cells:
            raise WebQuoteEditUnsupported("XLSX_DUPLICATE_OR_MISSING_CELL_REFERENCE")
        cells[ref] = element
    if not _REQUIRED <= set(cells):
        raise WebQuoteEditUnsupported("XLSX_QUOTE_CELL_TEMPLATE_MISSING")
    merges = {m.get("ref") for m in sheet.iter(MAIN + "mergeCell")}
    if "A1:D1" not in merges:
        raise WebQuoteEditUnsupported("XLSX_QUOTE_MERGED_HEADER_MISSING")
    # All existing formulas must match the one supported quote tax pattern.
    formulas = {r: cell.find(MAIN + "f") for r, cell in cells.items()
                if cell.find(MAIN + "f") is not None}
    if (set(formulas) != {"B6", "B7"}
            or (formulas["B6"].text or "").replace(" ", "") != "B4*B5"
            or (formulas["B7"].text or "").replace(" ", "") != "SUM(B4,B6)"
            or any(element.attrib for element in formulas.values())):
        raise WebQuoteEditUnsupported("XLSX_FORMULA_RECALC_UNSUPPORTED")
    return cells


def _money(cell: ET.Element) -> Decimal:
    if cell.find(MAIN + "f") is not None or cell.get("t") not in (None, "n"):
        raise WebQuoteEditUnsupported("XLSX_EXPECTED_NUMERIC_INPUT")
    value = cell.find(MAIN + "v")
    try:
        amount = Decimal(value.text) if value is not None else Decimal("NaN")
    except (ArithmeticError, ValueError, TypeError) as exc:
        raise WebQuoteEditUnsupported("XLSX_NUMERIC_VALUE_INVALID") from exc
    if not amount.is_finite():
        raise WebQuoteEditUnsupported("XLSX_NONFINITE_NUMBER")
    return amount


def revise_single_sheet_quote(
    *, original: bytes, original_sha256: str,
    school_name: str, supply_amount: int, output_formats: tuple[str, ...] = ("xlsx",),
) -> WebQuoteRevision:
    """Produce a distinct, deterministic quote XLSX, preserving untouched parts.

    No network/file I/O and no implied P01 grant. PDF requested on a generic
    workbook is a HARD failure: never generate a visually misleading file.
    """
    if (type(original) is not bytes
            or type(original_sha256) is not str
            or not re.fullmatch(r"[0-9a-f]{64}", original_sha256)
            or hashlib.sha256(original).hexdigest() != original_sha256):
        raise WebQuoteEditUnsupported("XLSX_SOURCE_SHA_MISMATCH")
    if (type(output_formats) is not tuple or output_formats != ("xlsx",)):
        raise WebQuoteEditUnsupported("PDF_FIDELITY_REQUIRES_APPROVED_OFFICE_RENDERER")
    if (type(school_name) is not str or not 1 <= len(school_name) <= 120
            or school_name != school_name.strip()
            or school_name.startswith(("=", "+", "-", "@"))
            or any(ord(ch) < 32 or ord(ch) == 127 for ch in school_name)):
        raise WebQuoteEditUnsupported("XLSX_SCHOOL_NAME_UNSAFE")
    if type(supply_amount) is not int or not 1 <= supply_amount <= 999_999_999_999:
        raise WebQuoteEditUnsupported("XLSX_SUPPLY_AMOUNT_OUT_OF_RANGE")
    parts, sheet = _load(original)
    cells = _cells(sheet)
    if cells["A1"].get("t") not in ("inlineStr", "s", "str"):
        raise WebQuoteEditUnsupported("XLSX_HEADER_STRING_TYPE_UNSUPPORTED")
    old = _money(cells["B4"])
    vat_rate = _money(cells["B5"])
    if old <= 0 or vat_rate != Decimal("0.1"):
        raise WebQuoteEditUnsupported("XLSX_QUOTE_TAX_TEMPLATE_UNSUPPORTED")
    new_vat = supply_amount // 10
    if supply_amount % 10:
        raise WebQuoteEditUnsupported("XLSX_NON_INTEGER_VAT_UNSUPPORTED")
    total = supply_amount + new_vat

    header = cells["A1"]
    for child in list(header):
        header.remove(child)
    header.attrib["t"] = "inlineStr"
    text = ET.SubElement(ET.SubElement(header, MAIN + "is"), MAIN + "t")
    text.text = school_name
    for ref, value in (("B4", supply_amount), ("B6", new_vat), ("B7", total)):
        cell = cells[ref]
        if cell.get("t") not in (None, "n"):
            raise WebQuoteEditUnsupported("XLSX_CALCULATED_CELL_NOT_NUMERIC")
        node = cell.find(MAIN + "v")
        if node is None:
            raise WebQuoteEditUnsupported("XLSX_CALCULATED_CACHE_MISSING")
        node.text = str(value)

    parts[_SHEET] = ET.tostring(sheet, encoding="utf-8", xml_declaration=True)
    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED, compresslevel=6) as package:
        for path, content in parts.items():
            # ZipFile.writestr(name, ...) silently timestamps each member with
            # wall-clock local time. The same authorized edit then gets a
            # different SHA-256 across minute boundaries, breaking P01's
            # exact revision proof. Use a canonical DOS epoch for every part.
            entry = ZipInfo(path, date_time=(1980, 1, 1, 0, 0, 0))
            package.writestr(entry, content, compress_type=ZIP_DEFLATED, compresslevel=6)
    updated = buffer.getvalue()
    if len(updated) > _SOURCE_MAX:
        raise WebQuoteEditUnsupported("XLSX_RESULT_EXCEEDS_STORAGE_BOUND")
    # Structural postflight verifies every supported input remains recognized,
    # all formulas still present and no other package part bytes changed.
    new_parts, new_sheet = _load(updated)
    after = _cells(new_sheet)
    if (
        any(new_parts[k] != v for k, v in parts.items() if k != _SHEET)
        or any(cells[k].get("s") != after[k].get("s") for k in cells)
        or _money(after["B4"]) != supply_amount
        or _money(after["B5"]) != vat_rate
        or after["B6"].find(MAIN + "v").text != str(new_vat)
        or after["B7"].find(MAIN + "v").text != str(total)
    ):
        raise WebQuoteEditUnsupported("XLSX_POSTFLIGHT_PARITY_FAILED")
    return WebQuoteRevision(
        source_sha256=original_sha256,
        revised_sha256=hashlib.sha256(updated).hexdigest(),
        revised_xlsx=updated,
        requested_school_name=school_name,
        requested_supply_amount=supply_amount,
        vat_amount=new_vat,
        total_amount=total,
    )
