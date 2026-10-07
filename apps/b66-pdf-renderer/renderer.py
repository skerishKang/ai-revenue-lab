"""Render resolved QuoteCore values into an approved PDF-native slot package.

The base is returned verbatim for a no-op. Changed slots remove superseded
text only inside their compiled cover regions, then use the isolated
Form-XObject overlay method. Images and line art remain untouched. Money, tax,
rounding, Korean number words and issue dates arrive resolved. This module
never fills absent quote values from the template sample.
"""

from __future__ import annotations

import hashlib
import math
import re
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

RENDERER_CONTRACT = "b66.certified-pdf.render-only.v1"
ENGINE_VERSION = "1.26.3"
_MAX_INTEGER = 9_007_199_254_740_991
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_PERCENT = re.compile(r"^(\d+(?:\.\d+)?)%$")


class B66CertifiedPdfError(ValueError):
    """Bounded code; callers must not expose customer values or native traces."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def renderer_source_sha256() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _object(value: Any) -> dict:
    if not isinstance(value, dict):
        raise B66CertifiedPdfError("REJECT_MISSING_RENDER_VALUES")
    return value


def _text(value: Any, *, empty: bool = True) -> str:
    if not isinstance(value, str) or len(value) > 4096 or (not empty and not value):
        raise B66CertifiedPdfError("REJECT_MISSING_RENDER_VALUES")
    if any(ord(c) < 32 for c in value):
        raise B66CertifiedPdfError("REJECT_INVALID_TEXT")
    return value


def _integer(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise B66CertifiedPdfError("REJECT_INVALID_AMOUNT")
    if not math.isfinite(value) or value != int(value) or abs(value) > _MAX_INTEGER:
        raise B66CertifiedPdfError("REJECT_INVALID_AMOUNT")
    if value < 0:
        raise B66CertifiedPdfError("REJECT_NEGATIVE_AMOUNT")
    return int(value)


def _resolved_values(model: dict, template: dict) -> tuple[dict, dict]:
    """Validate and project existing browser contracts; no business arithmetic."""
    model = _object(model)
    if (type(model.get("schemaVersion")) is not int or model["schemaVersion"] != 1
            or model.get("derivedBy") != "quote-core"):
        raise B66CertifiedPdfError("REJECT_CALCULATION_AUTHORITY")
    if _object(model.get("template")).get("approved") is not True:
        raise B66CertifiedPdfError("REJECT_UNAPPROVED_TEMPLATE")
    if _object(model.get("taxReview")).get("required") is not False:
        raise B66CertifiedPdfError("REJECT_UNRESOLVED_TAX")
    facts = _object(model.get("facts"))
    meta = _object(facts.get("meta"))
    recipient = _object(facts.get("recipient"))
    core = _object(model.get("coreTotals"))
    if core.get("mode") not in {"EXCLUSIVE", "INCLUSIVE", "EXEMPT"}:
        raise B66CertifiedPdfError("REJECT_UNRESOLVED_TAX")
    if core.get("detailGroups"):
        raise B66CertifiedPdfError("REJECT_UNSUPPORTED_DETAIL_PAGES")
    rows = core.get("effectiveItems")
    amounts = core.get("amounts")
    max_rows = template["supported_scope"]["max_item_rows"]
    if not isinstance(rows, list) or not isinstance(amounts, list) or not rows:
        raise B66CertifiedPdfError("REJECT_MISSING_RENDER_VALUES")
    if len(rows) > max_rows:
        raise B66CertifiedPdfError("REJECT_ITEM_OVERFLOW")
    if len(rows) != len(amounts):
        raise B66CertifiedPdfError("REJECT_MISSING_RENDER_VALUES")

    issue_date = _text(meta.get("issueDate"), empty=False)
    try:
        if not _ISO_DATE.fullmatch(issue_date):
            raise ValueError
        parsed = date.fromisoformat(issue_date)
        # The v2 slot package declares the full Excel serial [1, 2958465]
        # support interval. This is range validation, not date generation.
        if template["supported_scope"].get("date_serial_range") != [1, 2958465]:
            raise B66CertifiedPdfError("REJECT_TEMPLATE_SCOPE")
        if parsed < date(1899, 12, 31):
            raise ValueError
    except ValueError as exc:
        if isinstance(exc, B66CertifiedPdfError):
            raise
        raise B66CertifiedPdfError("REJECT_INVALID_DATE") from None

    normalized_rows = []
    for row in rows:
        row = _object(row)
        normalized_rows.append({
            "name": _text(row.get("name")),
            "qty": _integer(row.get("qty")),
            "unit_price": _integer(row.get("unitPrice")),
        })
    final_amounts = [_integer(value) for value in amounts]
    _integer(core.get("subtotal"))
    # Extra physical rows are explicitly blank, never sample quote defaults.
    while len(normalized_rows) < max_rows:
        normalized_rows.append({"name": "", "qty": 0, "unit_price": 0})
        final_amounts.append(0)
    rate_text = _text(facts.get("taxRateText"), empty=False)
    rate_match = _PERCENT.fullmatch(rate_text)
    if not rate_match:
        raise B66CertifiedPdfError("REJECT_UNRESOLVED_TAX")
    if not 0 <= float(rate_match.group(1)) < 100:
        raise B66CertifiedPdfError("REJECT_INVALID_VAT_RATE")
    grand = _integer(core.get("grand"))
    values = {
        "quote_number": _text(meta.get("quoteNo"), empty=False),
        "issue_date": issue_date,
        "recipient": _text(recipient.get("company"), empty=False),
        "project_name": _text(meta.get("projectName")),
        "vat_rate_text": rate_text,
        "items": normalized_rows,
    }
    derived = {
        "amounts": final_amounts,
        "subtotal": _integer(core.get("supply")),
        "vat": _integer(core.get("vat")),
        "grand": grand,
        "written_words": _text(model.get("writtenWords"), empty=False),
        "grand_comma": format(grand, ",d"),
    }
    return values, derived


def _color_rgb(value: int) -> tuple[float, float, float]:
    color = int(value or 0)
    return ((color >> 16 & 255) / 255.0,
            (color >> 8 & 255) / 255.0, (color & 255) / 255.0)


def _region_for_origin(template: dict, origin: list[float]) -> str:
    hits = [(name, rect) for name, rect in template["regions"].items()
            if rect[0] <= origin[0] <= rect[2] and rect[1] <= origin[1] <= rect[3]]
    if not hits:
        raise B66CertifiedPdfError("REJECT_NO_REGION")
    return min(hits, key=lambda item:
               (item[1][2] - item[1][0]) * (item[1][3] - item[1][1]))[0]


def build_changes(*, template: dict, baseline_render_model: dict,
                  render_model: dict) -> list[dict]:
    """Keep the certified slot geometry, consuming only resolved Core values."""
    if template.get("schema") != "b66.quote_template.v2":
        raise B66CertifiedPdfError("REJECT_TEMPLATE_SCHEMA")
    values, derived = _resolved_values(render_model, template)
    base, base_derived = _resolved_values(baseline_render_model, template)
    slots = template["mutable_slots"]
    changes: list[dict] = []

    def text_change(slot: str, spans: list[dict], text: str, align: str = "left"):
        covers, draws = [], []
        for span in spans:
            if span.get("cover"):
                covers.append({"rect": span["cover"], "bg_fill": span.get("bg_fill"),
                               "decorations": span.get("decorations", [])})
            if text:
                region = template["regions"][_region_for_origin(template, span["origin"])]
                room = (region[2] - span["origin"][0] if align == "left"
                        else span["right_x"] - region[0])
                draws.append({"text": text, "origin": span["origin"],
                              "font": span["font"], "size": span["size"],
                              "color": span["color"], "align": align,
                              "right_x": span.get("right_x"), "room": room})
        changes.append({"slot": slot, "covers": covers, "draws": draws})

    for field in ("quote_number", "recipient", "project_name"):
        if values[field] != base[field]:
            text_change(field, slots["camera"][field]["spans"], values[field])
    if values["issue_date"] != base["issue_date"]:
        slot = slots["camera"]["issue_date"]
        year, month, day = values["issue_date"].split("-")
        date_parts = {"Y": year, "M": month, "D": day}
        draws = []
        for span in slot["spans"]:
            if span["kind"] not in date_parts:
                continue
            region = template["regions"][_region_for_origin(template, span["origin"])]
            draws.append({"text": date_parts[span["kind"]], "origin": span["origin"],
                          "font": span["font"], "size": span["size"],
                          "color": span["color"], "align": "left", "right_x": None,
                          "room": region[2] - span["origin"][0]})
        changes.append({"slot": "issue_date", "covers": [slot["group"]], "draws": draws})

    for index, (row, base_row) in enumerate(zip(values["items"], base["items"]), start=1):
        anchors = slots["item_rows"][str(index)]["anchors"]
        changed = [field for field in ("name", "qty", "unit_price")
                   if row[field] != base_row[field]]
        amount, base_amount = derived["amounts"][index - 1], base_derived["amounts"][index - 1]
        if amount != base_amount:
            changed.append("amount")
        if not changed:
            continue
        covers, draws = [], []
        blank_row = not row["name"] and row["qty"] == 0 and row["unit_price"] == 0 and amount == 0
        for field in changed:
            anchor = anchors[field]
            if anchor is None:
                raise B66CertifiedPdfError("REJECT_UNSUPPORTED_SLOT")
            if blank_row:
                text = ""
            elif field == "name":
                text = row["name"]
            elif field == "qty":
                text = str(row["qty"])
            else:
                value = amount if field == "amount" else row["unit_price"]
                text = (template["format_rules"]["empty_amount_display"]
                        if value == 0 and field == "amount" else format(value, ",d"))
            if anchor.get("cover"):
                covers.append({"rect": anchor["cover"], "bg_fill": anchor.get("bg_fill"),
                               "decorations": anchor.get("decorations", [])})
            if text:
                region = template["regions"][_region_for_origin(template, anchor["origin"])]
                align = "left" if field == "name" else "right"
                room = region[2] - anchor["origin"][0] if align == "left" else anchor["right_x"] - region[0]
                draws.append({"text": text, "origin": anchor["origin"],
                              "font": anchor["font"], "size": anchor["size"],
                              "color": anchor["color"], "align": align,
                              "right_x": anchor.get("right_x"), "room": room})
        changes.append({"slot": f"item_{index}", "covers": covers, "draws": draws})

    totals = slots["totals"]
    for field, slot in (("subtotal", "subtotal"), ("vat", "vat"), ("grand", "grand_total")):
        if derived[field] != base_derived[field]:
            text_change(slot, [totals[slot]], format(derived[field], ",d"), "right")
    if values["vat_rate_text"] != base["vat_rate_text"]:
        percent = _PERCENT.fullmatch(values["vat_rate_text"]).group(1)
        text = template["format_rules"]["vat_rate_display"].format(rate_percent=float(percent))
        text_change("vat_rate_display", [totals["vat_rate_display"]], text, "right")
    if (derived["grand"] != base_derived["grand"]
            or derived["written_words"] != base_derived["written_words"]):
        text = template["format_rules"]["written_total_wrapper"].format(
            words=derived["written_words"], grand_comma=derived["grand_comma"])
        text_change("written_total", [totals["written_total"]], text)
    return changes


def _engine():
    try:
        import fitz
    except ImportError:
        raise B66CertifiedPdfError("PDF_RUNTIME_UNAVAILABLE") from None
    if fitz.VersionBind != ENGINE_VERSION:
        raise B66CertifiedPdfError("PDF_RUNTIME_VERSION_MISMATCH")
    return fitz


def render_pdf(*, template: dict, baseline_render_model: dict, render_model: dict,
               base_pdf: bytes, fonts: dict[str, bytes]) -> bytes:
    """Render bytes without introducing a second calculation authority."""
    try:
        changes = build_changes(template=template, baseline_render_model=baseline_render_model,
                                render_model=render_model)
        if not isinstance(base_pdf, bytes) or not base_pdf.startswith(b"%PDF-"):
            raise B66CertifiedPdfError("PDF_BASE_INVALID")
        fitz = _engine()
        if not changes:
            with fitz.open(stream=base_pdf, filetype="pdf") as original:
                if (original.page_count != template["page"]["count"]
                        or original.page_count != 1
                        or abs(original[0].rect.width - template["page"]["width_pt"]) > 1e-6
                        or abs(original[0].rect.height - template["page"]["height_pt"]) > 1e-6):
                    raise B66CertifiedPdfError("PDF_BASE_GEOMETRY_MISMATCH")
            return base_pdf
        with tempfile.TemporaryDirectory(prefix="b66_pdf_") as directory:
            paths, font_cache, native_fonts, aliases = {}, {}, {}, {}
            for family, info in template["resources"]["fonts"].items():
                member = info["file"]
                body = fonts.get(member)
                if not isinstance(body, bytes) or hashlib.sha256(body).hexdigest() != info["sha256"]:
                    raise B66CertifiedPdfError("PDF_FONT_INTEGRITY_FAILED")
                if member not in paths:
                    path = Path(directory) / (str(len(paths)) + Path(member).suffix)
                    path.write_bytes(body)
                    paths[member] = str(path)
                    native_fonts[member] = fitz.Font(fontfile=paths[member])
                    aliases[member] = "b66mut" + str(len(aliases))
                font_cache[family] = (native_fonts[member], paths[member], aliases[member])

            for change in changes:
                for draw in change["draws"]:
                    if draw["font"] not in font_cache:
                        raise B66CertifiedPdfError("REJECT_UNSUPPORTED_FONT")
                    font, _, _ = font_cache[draw["font"]]
                    if font.text_length(draw["text"], draw["size"]) > draw["room"] + 1e-6:
                        raise B66CertifiedPdfError("REJECT_TEXT_OVERFLOW")

            with fitz.open() as overlay, fitz.open(stream=base_pdf, filetype="pdf") as document:
                width, height = template["page"]["width_pt"], template["page"]["height_pt"]
                if (document.page_count != 1 or template["page"]["count"] != 1
                        or abs(document[0].rect.width - width) > 1e-6
                        or abs(document[0].rect.height - height) > 1e-6):
                    raise B66CertifiedPdfError("PDF_BASE_GEOMETRY_MISMATCH")

                # The visual cover alone is insufficient for a customer-facing
                # PDF: source text would remain searchable / copyable beneath
                # the replacement.  Isolate the original graphics state, then
                # remove text only inside changed compiled slot covers.  Images
                # and line art remain untouched; the certified overlay below
                # restores the compiled fill/decorations and draws new values.
                base_page = document[0]
                base_page.wrap_contents()
                redaction_rects: list[tuple[float, float, float, float]] = []
                seen_rects: set[tuple[float, float, float, float]] = set()
                for change in changes:
                    for cover in change["covers"]:
                        rect = cover.get("rect") if isinstance(cover, dict) else None
                        if (not isinstance(rect, list) or len(rect) != 4
                                or any(not isinstance(value, (int, float)) for value in rect)):
                            raise B66CertifiedPdfError("REJECT_TEMPLATE_SCOPE")
                        key = tuple(float(value) for value in rect)
                        if key not in seen_rects:
                            seen_rects.add(key)
                            redaction_rects.append(key)
                for rect in redaction_rects:
                    base_page.add_redact_annot(fitz.Rect(rect), fill=None, cross_out=False)
                if redaction_rects:
                    base_page.apply_redactions(
                        images=fitz.PDF_REDACT_IMAGE_NONE,
                        graphics=fitz.PDF_REDACT_LINE_ART_NONE,
                        text=fitz.PDF_REDACT_TEXT_REMOVE,
                    )

                page = overlay.new_page(width=width, height=height)
                for change in changes:
                    for cover in change["covers"]:
                        rect = cover["rect"]
                        page.draw_rect(fitz.Rect(rect), color=None,
                                       fill=cover.get("bg_fill") or (1.0, 1.0, 1.0))
                        for decoration in cover.get("decorations", []):
                            x0, x1 = max(decoration["x0"], rect[0]), min(decoration["x1"], rect[2])
                            if x1 > x0:
                                page.draw_line(fitz.Point(x0, decoration["y"]),
                                               fitz.Point(x1, decoration["y"]),
                                               color=tuple(decoration["color"]), width=decoration["width"])
                for change in changes:
                    for draw in change["draws"]:
                        font, path, alias = font_cache[draw["font"]]
                        x = draw["origin"][0]
                        if draw["align"] == "right":
                            x = draw["right_x"] - font.text_length(draw["text"], draw["size"])
                        page.insert_text(fitz.Point(x, draw["origin"][1]), draw["text"],
                                         fontsize=draw["size"], fontname=alias, fontfile=path,
                                         color=_color_rgb(draw["color"]))
                document[0].show_pdf_page(document[0].rect, overlay, 0, overlay=True)
                # Compress newly materialized/redacted streams so bounded
                # customer downloads stay well below the route response cap.
                # The no-op baseline path above still returns base_pdf verbatim.
                output = document.tobytes(deflate=True)
            with fitz.open(stream=output, filetype="pdf") as reopened:
                if reopened.page_count != 1:
                    raise B66CertifiedPdfError("PDF_OUTPUT_INVALID")
            return output
    except B66CertifiedPdfError:
        raise
    except Exception:
        raise B66CertifiedPdfError("PDF_RENDER_FAILED") from None
