# -*- coding: utf-8 -*-
"""B66 benchmark — deterministic, template-driven PDF renderer v2.

Renders a quotation PDF from the compiled template package
(base_document.pdf + quote_template.json + fonts/) and a values JSON.

Architecture (CENTRAL review v2):
- The renderer knows NO customer/document facts. Every fixed string, anchor,
  region, and format pattern comes from quote_template.json (compile-time
  extraction from the source evidence).
- Baseline render (no slot changes) = byte-identical copy of
  base_document.pdf.
- Mutations never rewrite the original page content streams. All replacement
  content (white cover rects + new text) is built in an isolated overlay
  document and placed as a Form XObject via show_pdf_page. Verified to leave
  every other pixel untouched.
- Fail-closed rejection: item overflow, negative/non-integer amounts,
  invalid date serial, and text that would exceed its slot room.
"""

from __future__ import annotations

import argparse
import json
import shutil
from copy import deepcopy
from pathlib import Path

import fitz

WORKDIR = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = WORKDIR / "template"

from textfmt import (  # noqa: E402
    EXCEL_SERIAL_MAX,
    EXCEL_SERIAL_MIN,
    format_comma,
    korean_number_words,
    serial_to_date,
)


class B66RenderError(ValueError):
    """Fail-closed rejection. .code is a stable machine-readable reason."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


# ─────────────────────────── values merging ───────────────────────────

def merge_values(template: dict, values: dict) -> dict:
    """Partial values JSON → full value set (baseline defaults from template)."""
    base = template["baseline_values"]
    merged = {
        "quote_number": str(base["quote_number"]),
        "issue_date_serial": int(base["issue_date_serial"]),
        "recipient": str(base["recipient"]),
        "project_name": str(base["project_name"]),
        "vat_rate": float(base["vat_rate"]),
        "items": [dict(row) for row in base["items"]],
    }
    for key in ("quote_number", "recipient", "project_name"):
        if values.get(key) is not None:
            merged[key] = str(values[key])
    if values.get("issue_date_serial") is not None:
        serial = values["issue_date_serial"]
        if isinstance(serial, bool) or not isinstance(serial, (int, float)) \
                or int(serial) != serial:
            raise B66RenderError("REJECT_INVALID_DATE", f"serial={serial!r}")
        merged["issue_date_serial"] = int(serial)
    if values.get("vat_rate") is not None:
        rate = values["vat_rate"]
        if isinstance(rate, bool) or not isinstance(rate, (int, float)):
            raise B66RenderError("REJECT_INVALID_VAT_RATE", f"rate={rate!r}")
        merged["vat_rate"] = float(rate)
    provided = values.get("items")
    if provided is not None:
        if not isinstance(provided, list):
            raise B66RenderError("REJECT_INVALID_ITEMS", "items must be a list")
        max_rows = template["supported_scope"]["max_item_rows"]
        if len(provided) > max_rows:
            raise B66RenderError(
                "REJECT_ITEM_OVERFLOW",
                f"{len(provided)} items > supported {max_rows}")
        for i, item in enumerate(provided):
            row = merged["items"][i]
            for field in ("name", "qty", "unit_price"):
                if isinstance(item, dict) and item.get(field) is not None:
                    row[field] = item[field]
    return merged


def compute_derived(items: list[dict], vat_rate: float) -> dict:
    amounts = []
    for item in items:
        qty = item.get("qty") or 0
        price = item.get("unit_price") or 0
        amounts.append(int(qty * price))
    subtotal = sum(amounts)
    vat = int(subtotal * vat_rate)
    grand = subtotal + vat
    return {"amounts": amounts, "subtotal": subtotal, "vat": vat,
            "grand": grand,
            "written_words": korean_number_words(grand),
            "grand_comma": format_comma(grand)}


# ─────────────────────────── fail-closed rejection ───────────────────────────

def check_rejections(template: dict, merged: dict) -> None:
    scope = template["supported_scope"]
    if len(merged["items"]) > scope["max_item_rows"]:
        raise B66RenderError("REJECT_ITEM_OVERFLOW", "unreachable")
    lo, hi = scope["date_serial_range"]
    if not (lo <= merged["issue_date_serial"] <= hi):
        raise B66RenderError("REJECT_INVALID_DATE",
                             f"serial={merged['issue_date_serial']} outside [{lo},{hi}]")
    rate = merged["vat_rate"]
    if not (0 <= rate < 1):
        raise B66RenderError("REJECT_INVALID_VAT_RATE", f"rate={rate}")
    for i, item in enumerate(merged["items"], start=1):
        for field in ("qty", "unit_price"):
            v = item.get(field)
            if v is None:
                continue
            if isinstance(v, bool) or not isinstance(v, (int, float)) or v != int(v):
                raise B66RenderError(
                    "REJECT_INVALID_AMOUNT", f"item {i} {field}={v!r} non-integer")
            if v < 0:
                raise B66RenderError(
                    "REJECT_NEGATIVE_AMOUNT", f"item {i} {field}={v!r}")


# ─────────────────────────── change list construction ───────────────────────────

def _color_rgb(color_int: int) -> tuple:
    c = int(color_int or 0)
    return ((c >> 16 & 255) / 255.0, (c >> 8 & 255) / 255.0, (c & 255) / 255.0)


def _region_for_origin(template: dict, origin: list[float]) -> str:
    hits = [(name, r) for name, r in template["regions"].items()
            if r[0] <= origin[0] <= r[2] and r[1] <= origin[1] <= r[3]]
    if not hits:
        raise B66RenderError("REJECT_NO_REGION", f"origin={origin}")
    name, r = min(hits, key=lambda kv: (kv[1][2] - kv[1][0]) * (kv[1][3] - kv[1][1]))
    return name


def build_changes(template: dict, merged: dict, derived: dict) -> list[dict]:
    """변경된 슬롯 → cover/draw 리스트 (원본 좌표계, overlay에 그려짐)."""
    base = template["baseline_values"]
    base_derived = compute_derived(base["items"], base["vat_rate"])
    slots = template["mutable_slots"]
    changes: list[dict] = []

    def text_change(slot: str, anchor_spans: list[dict], new_text: str | None,
                    align: str = "left") -> None:
        covers, draws = [], []
        for sp in anchor_spans:
            if sp.get("cover"):
                covers.append({"rect": sp["cover"], "bg_fill": sp.get("bg_fill"),
                               "decorations": sp.get("decorations", [])})
            if new_text:
                region = _region_for_origin(template, sp["origin"])
                room = ((region and template["regions"][region][2] - sp["origin"][0])
                        if align == "left"
                        else sp["right_x"] - template["regions"][region][0])
                draws.append({"text": new_text, "origin": sp["origin"],
                              "font": sp["font"], "size": sp["size"],
                              "color": sp["color"], "align": align,
                              "right_x": sp.get("right_x"), "room": room})
        changes.append({"slot": slot, "covers": covers, "draws": draws})

    # camera scalar slots
    if merged["quote_number"] != str(base["quote_number"]):
        text_change("quote_number", slots["camera"]["quote_number"]["spans"],
                    merged["quote_number"])
    if merged["recipient"] != str(base["recipient"]):
        text_change("recipient", slots["camera"]["recipient"]["spans"],
                    merged["recipient"])
    if merged["project_name"] != str(base["project_name"]):
        text_change("project_name", slots["camera"]["project_name"]["spans"],
                    merged["project_name"])

    # date: single group cover + per-part draws (literal parts stay original)
    if merged["issue_date_serial"] != int(base["issue_date_serial"]):
        date_slot = slots["camera"]["issue_date"]
        d = serial_to_date(merged["issue_date_serial"])
        kind_map = {"Y": f"{d.year:04d}", "M": f"{d.month:02d}", "D": f"{d.day:02d}"}
        covers = [date_slot["group"]]
        draws = []
        for sp in date_slot["spans"]:
            txt = kind_map.get(sp["kind"])
            if txt is None:  # literal part: unchanged, no redraw
                continue
            region = _region_for_origin(template, sp["origin"])
            draws.append({"text": txt, "origin": sp["origin"], "font": sp["font"],
                          "size": sp["size"], "color": sp["color"], "align": "left",
                          "right_x": None,
                          "room": template["regions"][region][2] - sp["origin"][0]})
        changes.append({"slot": "issue_date", "covers": covers, "draws": draws})

    # item rows: per-field change detection
    for i, (row, base_row) in enumerate(zip(merged["items"], base["items"]), start=1):
        anchors = slots["item_rows"][str(i)]["anchors"]
        changed_fields = [f for f in ("name", "qty", "unit_price")
                          if row.get(f) != base_row.get(f)]
        amount = derived["amounts"][i - 1]
        base_amount = base_derived["amounts"][i - 1]
        if amount != base_amount:
            changed_fields.append("amount")
        if not changed_fields:
            continue
        covers, draws = [], []
        for field in changed_fields:
            a = anchors[field]
            if a is None:
                continue
            if field == "name":
                new_text = "" if row.get("name") is None else str(row["name"])
            elif field == "qty":
                new_text = "" if row.get("qty") is None else str(int(row["qty"]))
            else:
                value = (amount if field == "amount"
                         else int(row["unit_price"]))
                new_text = (template["format_rules"]["empty_amount_display"]
                            if value == 0 and field == "amount"
                            else format_comma(value))
            if a.get("cover"):
                covers.append({"rect": a["cover"], "bg_fill": a.get("bg_fill"),
                               "decorations": a.get("decorations", [])})
            if new_text:
                region = _region_for_origin(template, a["origin"])
                align = "left" if field == "name" else "right"
                room = ((template["regions"][region][2] - a["origin"][0])
                        if align == "left"
                        else a["right_x"] - template["regions"][region][0])
                draws.append({"text": new_text, "origin": a["origin"],
                              "font": a["font"], "size": a["size"],
                              "color": a["color"], "align": align,
                              "right_x": a.get("right_x"), "room": room})
        changes.append({"slot": f"item_{i}", "covers": covers, "draws": draws})

    # totals
    totals = slots["totals"]
    if derived["subtotal"] != base_derived["subtotal"]:
        text_change("subtotal", [totals["subtotal"]], format_comma(derived["subtotal"]),
                    align="right")
    if (derived["vat"] != base_derived["vat"]
            or merged["vat_rate"] != float(base["vat_rate"])):
        text_change("vat", [totals["vat"]], format_comma(derived["vat"]), align="right")
    if merged["vat_rate"] != float(base["vat_rate"]) and "vat_rate_display" in totals:
        rate_text = template["format_rules"]["vat_rate_display"].format(
            rate_percent=merged["vat_rate"] * 100)
        text_change("vat_rate_display", [totals["vat_rate_display"]], rate_text,
                    align="right")
    if derived["grand"] != base_derived["grand"]:
        text_change("grand_total", [totals["grand_total"]],
                    format_comma(derived["grand"]), align="right")
    if (derived["grand"] != base_derived["grand"]
            or derived["grand_comma"] != base_derived["grand_comma"]):
        wrapper = template["format_rules"]["written_total_wrapper"]
        text_change("written_total", [totals["written_total"]],
                    wrapper.format(words=derived["written_words"],
                                   grand_comma=derived["grand_comma"]))

    return changes


# ─────────────────────────── overlay rendering ───────────────────────────

_FONT_CACHE: dict[str, fitz.Font] = {}


def _font_for(template: dict, family: str | None) -> tuple[fitz.Font, str]:
    fonts = template["resources"]["fonts"]
    info = fonts.get(family or "") or fonts.get("MalgunGothic")
    path = str(TEMPLATE_DIR / info["file"])
    if path not in _FONT_CACHE:
        _FONT_CACHE[path] = fitz.Font(fontfile=path)
    return _FONT_CACHE[path], path


def check_text_fit(changes: list[dict], template: dict) -> None:
    """Fail-closed: 새 텍스트가 자신의 슬롯 room을 벗어나면 렌더 거부."""
    for change in changes:
        for draw in change["draws"]:
            font, _ = _font_for(template, draw["font"])
            width = font.text_length(draw["text"], draw["size"])
            if width > draw["room"] + 1e-6:
                raise B66RenderError(
                    "REJECT_TEXT_OVERFLOW",
                    f"slot={change['slot']} width={width:.1f}pt room={draw['room']:.1f}pt "
                    f"text={draw['text'][:20]!r}")


def render_overlay_document(template: dict, changes: list[dict]) -> "fitz.Document":
    """모든 cover/draw를 격리된 overlay 문서에 작성 (원본 스트림 무손상).

    cover는 컴파일 시 기록된 배경색(bg_fill)으로 채우고, cover가 가린 수평
    밑줄(decorations)은 같은 위치에 다시 그려 원본 장식을 보존한다.
    """
    odoc = fitz.open()
    w = template["page"]["width_pt"]
    h = template["page"]["height_pt"]
    opage = odoc.new_page(width=w, height=h)
    for change in changes:
        for cover in change["covers"]:
            rect = cover["rect"]
            fill = cover.get("bg_fill") or (1.0, 1.0, 1.0)
            opage.draw_rect(fitz.Rect(rect), color=None, fill=fill)
            for dec in cover.get("decorations", []):
                x0 = max(dec["x0"], rect[0])
                x1 = min(dec["x1"], rect[2])
                if x1 > x0:
                    opage.draw_line(fitz.Point(x0, dec["y"]), fitz.Point(x1, dec["y"]),
                                    color=tuple(dec["color"]), width=dec["width"])
    for change in changes:
        for draw in change["draws"]:
            font, font_path = _font_for(template, draw["font"])
            x = draw["origin"][0]
            if draw["align"] == "right":
                x = draw["right_x"] - font.text_length(draw["text"], draw["size"])
            opage.insert_text(
                fitz.Point(x, draw["origin"][1]), draw["text"],
                fontsize=draw["size"], fontname="b66mut",
                fontfile=font_path, color=_color_rgb(draw["color"]))
    return odoc


# ─────────────────────────── main entry ───────────────────────────

def render(values_path: str, out_path: str, template_dir: Path | None = None) -> dict:
    global TEMPLATE_DIR
    if template_dir is not None:
        TEMPLATE_DIR = Path(template_dir)
    template = json.loads((TEMPLATE_DIR / "quote_template.json").read_text(encoding="utf-8"))
    values = json.loads(Path(values_path).read_text(encoding="utf-8"))

    merged = merge_values(template, values)
    check_rejections(template, merged)
    derived = compute_derived(merged["items"], merged["vat_rate"])
    changes = build_changes(template, merged, derived)

    base_path = TEMPLATE_DIR / template["resources"]["base_document"]["file"]

    if not changes:
        shutil.copyfile(base_path, out_path)
        return {"output": str(out_path), "byte_identical": True,
                "changed_slots": [], "derived": derived}

    check_text_fit(changes, template)
    odoc = render_overlay_document(template, changes)

    doc = fitz.open(str(base_path))
    page = doc[template["page"].get("index", 0)]
    page.show_pdf_page(page.rect, odoc, 0, overlay=True)
    doc.save(out_path)
    doc.close()
    odoc.close()

    return {"output": str(out_path), "byte_identical": False,
            "changed_slots": [c["slot"] for c in changes],
            "derived": derived}


def main() -> None:
    parser = argparse.ArgumentParser(description="B66 quotation PDF renderer")
    parser.add_argument("--values", required=True, help="values JSON file")
    parser.add_argument("--out", required=True, help="output PDF path")
    parser.add_argument("--template-dir", required=True, help="compiled template directory")
    args = parser.parse_args()
    result = render(args.values, args.out, Path(args.template_dir))
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
