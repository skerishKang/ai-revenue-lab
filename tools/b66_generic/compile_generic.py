# -*- coding: utf-8 -*-
"""B66 GENERIC analyzer/compiler.

Derives the `b66.quote_template.v2` compiled-template package from raw source
observations alone:

    compile_generic.py --evidence <dir> --sheet <name> --page <n> --outdir <dir>

Design contract (the whole point of this child, #3628):

* This module must contain **no** document-specific cell reference, no
  document-specific coordinate constant and no customer literal. Every slot
  binding is produced by *source-derived observation*:
    1. semantic role inference from the source's own field labels
       (label token -> adjacent value span on the same text row);
    2. geometric structure detection for the item table (header row detected
       from the column-name tokens, item rows detected below it) and the totals
       block (label rows detected from the totals vocabulary);
    3. XLSX provenance binding by matching the observed value text to a cell.
* The only literals permitted here are **generic Korean quotation vocabulary**
  (field labels, table column names, totals words) and generic formatting
  rules. They are vocabulary, not template structure: any quotation using the
  same vocabulary is handled by the same code path.

Output package:
    base_document.pdf      byte-identical copy of the reference PDF
    quote_template.json    slot bindings / regions / format rules / scope
    fonts/                 system fonts for mutation text
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

WORKDIR = Path(__file__).resolve().parent
sys.path.insert(0, str(WORKDIR.parent))
sys.path.insert(0, str(WORKDIR))

from datetime import date  # noqa: E402

from textfmt import (  # noqa: E402
    format_comma, korean_number_words, norm_text, serial_to_date,
)

# ── generic Korean quotation vocabulary (labels, not coordinates) ──
LABELS = {
    "quote_number": ["견적번호", "견적 번호", "견적no"],
    "issue_date": ["작성일자", "견적일자", "견적일", "작성일"],
    "recipient": ["제출처", "수신처", "공급받는자", "받는자", "수신"],
    "project_name": ["건명", "공사명", "품명(공사)", "건 명"],
    "author": ["작성자", "작 성 자"],
    "contact": ["담당자", "담 당 자"],
}
ITEM_COLS = {"name": ["품명", "품목", "품명및규격", "품 명"],
             "qty": ["수량", "수 량"],
             "unit_price": ["단가", "단 가"],
             "amount": ["금액", "금 액"]}
TOTAL_LABELS = {"subtotal": ["소계", "소 계", "합계(부가세별도)"],
                "vat": ["부가세", "부 가 세", "v.a.t", "vat"],
                "grand_total": ["합계", "총계", "총 계", "합 계", "종합금액"]}
WRITTEN_MARKERS = ["합계금액", "일금"]
SYSTEM_FONTS = {
    "MalgunGothic": r"C:\Windows\Fonts\malgun.ttf",
    "MalgunGothicBold": r"C:\Windows\Fonts\malgunbd.ttf",
    "GulimChe": r"C:\Windows\Fonts\gulim.ttc",
    "Gulim": r"C:\Windows\Fonts\gulim.ttc",
}
ROW_TOL = 3.0  # pt: same-text-row tolerance


def sha256_file(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def cover_of(bbox, pad_x=1.0, pad_y=1.5):
    return [bbox[0] - pad_x, bbox[1] - pad_y, bbox[2] + pad_x, bbox[3] + pad_y]


def union(rects, pad_x=0.0, pad_y=0.0):
    return [min(r[0] for r in rects) - pad_x, min(r[1] for r in rects) - pad_y,
            max(r[2] for r in rects) + pad_x, max(r[3] for r in rects) + pad_y]


def bg_fill_for(cover, drawings):
    best = None
    for d in drawings:
        if d.get("type") != "f" or not d.get("fill"):
            continue
        if d.get("fill_opacity") not in (None, 1.0):
            continue
        if not all(it.get("op") == "re" for it in d.get("items", [])):
            continue
        r = d["rect"]
        if r[0] <= cover[0] and r[1] <= cover[1] and r[2] >= cover[2] and r[3] >= cover[3]:
            best = d["fill"]
    return best


def decorations_for(cover, drawings):
    out, cw = [], cover[2] - cover[0]
    for d in drawings:
        if d.get("type") != "s" or not d.get("color"):
            continue
        r = d["rect"]
        if r[3] - r[1] > 1.5 or (r[2] - r[0]) < 0.3 * cw:
            continue
        if r[2] < cover[0] or cover[2] < r[0] or r[3] < cover[1] or cover[3] < r[1]:
            continue
        out.append({"x0": r[0], "x1": r[2], "y": (r[1] + r[3]) / 2,
                    "width": d.get("width") or 0.8, "color": d["color"]})
    return out


def decorate(node, drawings):
    if isinstance(node, dict):
        cov = node.get("cover") if isinstance(node.get("cover"), list) else None
        if cov:
            node["bg_fill"] = bg_fill_for(cov, drawings)
            node["decorations"] = decorations_for(cov, drawings)
        for v in node.values():
            decorate(v, drawings)
    elif isinstance(node, list):
        for v in node:
            decorate(v, drawings)


def _match_label(text, vocab):
    """Return the vocabulary key whose token equals the normalized span text.

    Comparison is case-insensitive: the same field label may be emitted in any
    case by the source renderer (e.g. 'V.A.T' vs 'vat')."""
    n = norm_text(text).lower()
    if not n:
        return None
    for key, tokens in vocab.items():
        for t in tokens:
            if n == norm_text(t).lower():
                return key
    return None


def _row_spans(spans, y, tol=ROW_TOL):
    return [s for s in spans if abs(s["bbox"][1] - y) <= tol]


def compile_template(evidence_dir: Path, sheet_name: str, page_index: int,
                     outdir: Path) -> dict:
    xlsx = json.loads((evidence_dir / "xlsx_analysis.json").read_text(encoding="utf-8"))
    pdf = json.loads((evidence_dir / "pdf_analysis.json").read_text(encoding="utf-8"))
    page = pdf["pages"][page_index]
    spans = page["text_spans"]
    drawings = page.get("drawings", [])
    sheet = xlsx["sheets"][sheet_name]
    cells = sheet["cells"]

    outdir.mkdir(parents=True, exist_ok=True)

    # ---- base document: byte-identical copy of the reference PDF ----
    ref_pdf = Path(pdf["source"]["path"])
    base_doc = outdir / "base_document.pdf"
    shutil.copy2(ref_pdf, base_doc)
    base_sha = sha256_file(base_doc)

    # ---- fonts ----
    fonts_dir = outdir / "fonts"
    fonts_dir.mkdir(parents=True, exist_ok=True)
    font_resources = {}
    for family, src in SYSTEM_FONTS.items():
        p = Path(src)
        if not p.exists():
            continue
        dst = fonts_dir / p.name
        if not dst.exists() or sha256_file(dst) != sha256_file(p):
            shutil.copy2(p, dst)
        font_resources[family] = {"file": f"fonts/{dst.name}",
                                  "sha256": sha256_file(dst), "source": "system"}

    # ---- cell value index (display text -> cell ref) for provenance ----
    def cell_display(v):
        if v is None:
            return None
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return format_comma(int(v))
        return str(v)

    cell_index = {}
    for ref, c in cells.items():
        d = cell_display(c["value"])
        if d is not None:
            cell_index.setdefault(norm_text(d), ref)

    def bind_cell(text):
        return cell_index.get(norm_text(text))

    # ---- semantic slot detection: label token -> adjacent value span ----
    found = {}
    for s in spans:
        key = _match_label(s["text"], LABELS)
        if key is None or key in found:
            continue
        row = _row_spans(spans, s["bbox"][1])
        right = sorted([r for r in row if r["bbox"][0] >= s["bbox"][2] - 0.5],
                       key=lambda r: r["bbox"][0])
        val = None
        for r in right:
            if _match_label(r["text"], LABELS) is not None:
                continue
            if r["text"].strip() == "":
                continue
            val = r
            break
        if val is not None:
            found[key] = {"label": s, "value": val}

    # ---- item table: detect header row from column-name tokens ----
    header_row_y = None
    col_x = {}
    for s in spans:
        ck = _match_label(s["text"], ITEM_COLS)
        if ck is None:
            continue
        row = _row_spans(spans, s["bbox"][1])
        keys = {_match_label(r["text"], ITEM_COLS) for r in row}
        keys.discard(None)
        if len(keys) >= 3:  # a real header row names >=3 columns
            header_row_y = s["bbox"][1]
            for r in row:
                k = _match_label(r["text"], ITEM_COLS)
                if k:
                    col_x[k] = {"x0": r["bbox"][0], "x1": r["bbox"][2],
                                "center": (r["bbox"][0] + r["bbox"][2]) / 2}
            break
    assert header_row_y is not None, "item table header row not detected"

    # column bands: split at the midpoint between adjacent column-name centers.
    # The leftmost known column starts at its own header edge (minus slack), so
    # an unrelated leading column (e.g. a row-number column) is not swallowed.
    ordered = sorted(col_x.items(), key=lambda kv: kv[1]["center"])
    band = {}
    for i, (k, v) in enumerate(ordered):
        lo = (ordered[i - 1][1]["center"] + v["center"]) / 2 if i > 0 else v["x0"] - 3.0
        hi = ((ordered[i + 1][1]["center"] + v["center"]) / 2
              if i + 1 < len(ordered) else page["width_pt"])
        band[k] = (lo, hi)

    # totals block top: the first text row carrying a totals label. Item rows are
    # everything between the header row and that boundary.
    totals_top = page["height_pt"]
    for s in spans:
        if s["bbox"][1] > header_row_y and _match_label(s["text"], TOTAL_LABELS) is not None:
            totals_top = min(totals_top, s["bbox"][1])

    # item rows: text rows strictly below the header and above the totals block.
    # Distinct text baselines within ROW_TOL are the same visual table row.
    raw_ys = sorted({s["bbox"][1] for s in spans
                     if header_row_y + 2 < s["bbox"][1] < totals_top - 2})
    below = []
    for y in raw_ys:
        if not below or y - below[-1] > ROW_TOL:
            below.append(y)
    item_row_ys = []
    for y in below:
        row = _row_spans(spans, y)
        has_content = any(
            any(lo <= (r["bbox"][0] + r["bbox"][2]) / 2 <= hi for lo, hi in band.values())
            and r["text"].strip() for r in row)
        if has_content:
            item_row_ys.append(y)
    assert item_row_ys, "no item rows detected"

    def col_value(row, key):
        """Value span(s) for a column in an item row (splits combined runs)."""
        lo, hi = band[key]
        cands = [r for r in row if lo <= (r["bbox"][0] + r["bbox"][2]) / 2 <= hi]
        return cands

    def runs_of(span):
        runs, cur = [], []
        for ch in span["chars"]:
            if ch["c"].isspace():
                if cur:
                    runs.append(cur); cur = []
            else:
                cur.append(ch)
        if cur:
            runs.append(cur)
        out = []
        for cs in runs:
            out.append({"text": "".join(c["c"] for c in cs),
                        "origin": list(cs[0]["origin"]),
                        "x0": cs[0]["bbox"][0],
                        "x1": max(c["bbox"][2] for c in cs),
                        "y0": min(c["bbox"][1] for c in cs),
                        "y1": max(c["bbox"][3] for c in cs)})
        return out

    def anchor_from_run(run, font, size, color):
        return {"origin": run["origin"], "right_x": run["x1"],
                "cover": cover_of([run["x0"], run["y0"], run["x1"], run["y1"]]),
                "font": font, "size": size, "color": color, "text": run["text"]}

    item_rows = {}
    for idx, y in enumerate(item_row_ys, start=1):
        row = _row_spans(spans, y)
        rec = {"row_index": idx, "y_band": [y - 2, y + 12], "anchors": {}}
        # name (left-aligned, first non-empty span in the name band)
        name_spans = [r for r in col_value(row, "name") if r["text"].strip()]
        if name_spans:
            ns = min(name_spans, key=lambda r: r["bbox"][0])
            rec["anchors"]["name"] = {
                "origin": ns["chars"][0]["origin"], "right_x": ns["bbox"][2],
                "cover": cover_of(ns["bbox"]), "font": ns["font"],
                "size": ns["size"], "color": ns["color"], "text": ns["text"]}
        # numeric columns: collect candidate spans, split into runs by column band
        num_spans = []
        for key in ("qty", "unit_price", "amount"):
            num_spans += [(key, r) for r in col_value(row, key)]
        # also catch combined spans that straddle price/amount
        for r in row:
            if any(r is s for _, s in num_spans):
                continue
            lo, hi = band["unit_price"]
            if r["bbox"][2] > lo and r["bbox"][0] < page["width_pt"]:
                if re.search(r"\d", r["text"]):
                    num_spans.append(("combined", r))
        # assign runs
        run_pool = []
        for key, r in num_spans:
            for run in runs_of(r):
                if re.search(r"\d", run["text"]):
                    run_pool.append((key, run, r))
        used = set()
        for key in ("qty", "unit_price", "amount"):
            lo, hi = band[key]
            cand = [(rk, run, r) for (rk, run, r) in run_pool
                    if id(run) not in used and lo <= (run["x0"] + run["x1"]) / 2 <= hi]
            if not cand:
                continue
            rk, run, r = max(cand, key=lambda t: t[1]["x1"])
            used.add(id(run))
            rec["anchors"][key] = anchor_from_run(run, r["font"], r["size"], r["color"])
        item_rows[idx] = rec

    # ---- totals block ----
    totals = {}
    for s in spans:
        tk = _match_label(s["text"], TOTAL_LABELS)
        if tk is None or tk in totals:
            continue
        row = _row_spans(spans, s["bbox"][1])
        right = sorted([r for r in row if r["bbox"][0] >= s["bbox"][2] - 0.5],
                       key=lambda r: r["bbox"][0])
        cands = [r for r in right if re.search(r"\d", r["text"])]
        if not cands:
            continue
        r = cands[0]
        totals[tk] = {"origin": r["chars"][0]["origin"], "right_x": r["bbox"][2],
                      "cover": cover_of(r["bbox"]), "font": r["font"],
                      "size": r["size"], "color": r["color"], "text": r["text"]}

    # ---- written total line (contains the "일금 ... 원정" wrapper) ----
    written = None
    for s in spans:
        if all(norm_text(m) in norm_text(s["text"]) for m in WRITTEN_MARKERS):
            written = s
            break
    assert written is not None, "written-total line not detected"
    totals["written_total"] = {"origin": written["chars"][0]["origin"],
                               "right_x": written["bbox"][2],
                               "cover": cover_of(written["bbox"]),
                               "font": written["font"], "size": written["size"],
                               "color": written["color"], "text": written["text"]}

    # ---- vat rate display (percentage span near the vat row) ----
    rate_span = None
    if "vat" in totals:
        vat_y = totals["vat"]["cover"][1]
        for s in spans:
            if abs(s["bbox"][1] - vat_y) <= 14 and re.fullmatch(r"\s*\d+(\.\d+)?\s*%", s["text"]):
                rate_span = s
                break
    if rate_span is None:
        for s in spans:
            if re.fullmatch(r"\s*\d+(\.\d+)?\s*%", s["text"]):
                rate_span = s
                break
    if rate_span is not None:
        totals["vat_rate_display"] = {"origin": rate_span["chars"][0]["origin"],
                                      "right_x": rate_span["bbox"][2],
                                      "cover": cover_of(rate_span["bbox"]),
                                      "font": rate_span["font"], "size": rate_span["size"],
                                      "color": rate_span["color"]}

    # ---- date parts: split the issue-date value into digit / literal sub-parts ----
    # The source renders the date as one text run per token ('2020년', '10월',
    # '29일'). Digit groups become Y/M/D redraw targets; the literal suffixes
    # ('년','월','일') are never covered, so they survive a mutation untouched.
    def sub_parts(chars):
        out, cur, cur_digit = [], [], None
        for ch in chars:
            d = ch["c"].isdigit()
            if cur and d != cur_digit:
                out.append((cur_digit, cur)); cur = []
            cur.append(ch); cur_digit = d
        if cur:
            out.append((cur_digit, cur))
        parts = []
        for is_digit, cs in out:
            parts.append({
                "is_digit": is_digit,
                "text": "".join(c["c"] for c in cs),
                "origin": list(cs[0]["origin"]),
                "bbox": [cs[0]["bbox"][0], min(c["bbox"][1] for c in cs),
                         max(c["bbox"][2] for c in cs), max(c["bbox"][3] for c in cs)]})
        return parts

    date_slot = None
    if "issue_date" in found:
        dsp = found["issue_date"]["value"]
        kinds = ["Y", "M", "D"]
        parts = []
        for p in sub_parts(dsp["chars"]):
            if p["is_digit"] and kinds:
                kind = kinds.pop(0)
            else:
                kind = "lit"
            parts.append({"kind": kind, "text": p["text"], "origin": p["origin"],
                          "bbox": p["bbox"], "cover": cover_of(p["bbox"], pad_x=0.5),
                          "font": dsp["font"], "size": dsp["size"], "color": dsp["color"]})
        digit_parts = [p for p in parts if p["kind"] != "lit"]
        date_slot = {"spans": parts,
                     "group_cover": cover_of(union([p["bbox"] for p in digit_parts])
                                             if digit_parts else [dsp["bbox"]])}
        date_slot["group"] = {"rect": date_slot["group_cover"],
                              "bg_fill": bg_fill_for(date_slot["group_cover"], drawings),
                              "decorations": decorations_for(date_slot["group_cover"], drawings)}

    # ---- camera/header slots ----
    camera = {}
    for key in ("quote_number", "recipient", "project_name"):
        if key not in found:
            continue
        v = found[key]["value"]
        camera[key] = {"spans": [{"text": v["text"], "bbox": v["bbox"],
                                  "cover": cover_of(v["bbox"]),
                                  "origin": v["chars"][0]["origin"],
                                  "font": v["font"], "size": v["size"],
                                  "color": v["color"]}]}
    if date_slot:
        camera["issue_date"] = date_slot
    decorate(camera, drawings)
    for rec in item_rows.values():
        decorate(rec["anchors"], drawings)
    decorate(totals, drawings)

    # ---- baseline values from observations ----
    def value_text(key):
        return found[key]["value"]["text"] if key in found else None

    def parse_int(text):
        if text is None:
            return None
        digits = re.sub(r"[^0-9\-]", "", text)
        return int(digits) if digits not in ("", "-") else None

    items = []
    for idx in sorted(item_rows):
        rec = item_rows[idx]
        a = rec["anchors"]
        items.append({
            "name": a.get("name", {}).get("text"),
            "qty": parse_int(a.get("qty", {}).get("text")),
            "unit_price": parse_int(a.get("unit_price", {}).get("text")),
        })

    # ---- totals values (observed, not assumed) ----
    subtotal = parse_int(totals.get("subtotal", {}).get("text"))
    vat = parse_int(totals.get("vat", {}).get("text"))
    grand = parse_int(totals.get("grand_total", {}).get("text"))
    vat_rate = None
    if subtotal and vat is not None:
        vat_rate = round(vat / subtotal, 6)

    # ---- written-total wrapper derived from the observed grand total ----
    wrapper = str(written["text"])
    if grand is not None:
        words = korean_number_words(grand)
        comma = format_comma(grand)
        if words in wrapper:
            wrapper = wrapper.replace(words, "{words}")
        if comma in wrapper:
            wrapper = wrapper.replace(comma, "{grand_comma}")

    # ---- issue-date serial resolved from XLSX provenance ----
    # The reference renderer prints the date as text; the workbook stores it as
    # an Excel serial. Bind the two by matching the parsed calendar date to the
    # serial range — no cell reference is assumed.
    date_serial = None
    if date_slot:
        nums = [p["text"] for p in date_slot["spans"] if p["kind"] in ("Y", "M", "D")]
        if len(nums) == 3:
            try:
                target = date(int(nums[0]), int(nums[1]), int(nums[2]))
                for _ref, c in cells.items():
                    v = c["value"]
                    if isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= 2958465:
                        if serial_to_date(v) == target:
                            date_serial = v
                            break
            except Exception:
                date_serial = None

    # ---- regions ----
    header_spans = [s for s in spans if s["bbox"][1] < header_row_y - 2]
    item_spans_all = [s for s in spans
                      if item_row_ys[0] - 2 <= s["bbox"][1] <= item_row_ys[-1] + 12]
    regions = {}
    if header_spans:
        regions["camera_block"] = union([s["bbox"] for s in header_spans], pad_x=10, pad_y=6)
    regions["body_table"] = union([s["bbox"] for s in item_spans_all], pad_x=10, pad_y=6)
    for tk in ("subtotal", "vat", "grand_total"):
        if tk in totals:
            regions[f"{tk}_row"] = union([totals[tk]["cover"]], pad_x=2, pad_y=2)
    if "written_total" in totals:
        # The written-total line is a full-width line ("합계금액 : 일금 ...").
        # Its isolation band spans the page width so a longer number is not
        # falsely rejected against the baseline line's own glyph width.
        c = totals["written_total"]["cover"]
        regions["written_total_row"] = [0.0, c[1] - 6, page["width_pt"], c[3] + 6]

    max_rows = len(item_rows)
    template = {
        "schema": "b66.quote_template.v2",
        "source_provenance": {
            "source_xlsx": {"path": xlsx["source"]["path"], "sha256": xlsx["source"]["sha256"]},
            "reference_pdf": {"path": pdf["source"]["path"], "sha256": pdf["source"]["sha256"]},
            "compiled_by": "b66_generic_compiler",
        },
        "page": {"index": page_index, "count": pdf["page_count"],
                 "width_pt": page["width_pt"], "height_pt": page["height_pt"]},
        "resources": {"fonts": font_resources,
                      "base_document": {"file": "base_document.pdf", "sha256": base_sha}},
        "mutable_slots": {
            "camera": camera,
            "item_rows": {str(i): {"y_band": item_rows[i]["y_band"],
                                   "anchors": {k: v for k, v in item_rows[i]["anchors"].items() if v}}
                          for i in sorted(item_rows)},
            "totals": totals,
        },
        "baseline_values": {
            "quote_number": value_text("quote_number"),
            "issue_date_serial": date_serial,
            "recipient": value_text("recipient"),
            "project_name": value_text("project_name"),
            "vat_rate": vat_rate,
            "items": items,
        },
        "format_rules": {
            "number_comma": "#,##0",
            "date_parts": [{"kind": p["kind"]} for p in (date_slot["spans"] if date_slot else [])],
            "written_total_wrapper": wrapper,
            "vat_rate_display": "{rate_percent:g}%",
            "empty_amount_display": "-",
        },
        "regions": regions,
        "supported_scope": {"max_item_rows": max_rows,
                            "date_serial_range": [1, 2958465],
                            "amounts": "non-negative integers (fail-closed)",
                            "text_overflow": "fail-closed rejection"},
        "certification": {
            "generic_compiler": True,
            "template_specific_literals": "none",
            "source_sheet": sheet_name,
            "source_page_index": page_index,
            "detection": {"label_roles": sorted(found.keys()),
                          "item_columns": sorted(col_x.keys()),
                          "totals": sorted(totals.keys())},
            "source_cell_provenance": {
                "quote_number": bind_cell(value_text("quote_number")),
                "recipient": bind_cell(value_text("recipient")),
                "project_name": bind_cell(value_text("project_name")),
            },
        },
    }
    (outdir / "quote_template.json").write_text(
        json.dumps(template, ensure_ascii=False, indent=1), encoding="utf-8")
    return template


def main() -> None:
    ap = argparse.ArgumentParser(description="B66 generic compiler")
    ap.add_argument("--evidence", required=True)
    ap.add_argument("--sheet", required=True)
    ap.add_argument("--page", type=int, required=True)
    ap.add_argument("--outdir", required=True)
    a = ap.parse_args()
    t = compile_template(Path(a.evidence), a.sheet, a.page, Path(a.outdir))
    print("template written:", Path(a.outdir) / "quote_template.json")
    print("camera slots:", list(t["mutable_slots"]["camera"].keys()))
    print("item rows:", list(t["mutable_slots"]["item_rows"].keys()))
    print("totals:", list(t["mutable_slots"]["totals"].keys()))
    print("regions:", list(t["regions"].keys()))
    print("baseline items:", json.dumps(t["baseline_values"]["items"], ensure_ascii=False))


if __name__ == "__main__":
    main()
