# -*- coding: utf-8 -*-
"""B66 generic certification — critical fidelity gates, measured separately.

Aggregate raster similarity alone never passes: every gate below comes from its
own observation of the two PDFs and is reported on its own.

What each gate actually measures (no two of them are the same comparison):

    BASELINE_BYTE_IDENTICAL  the whole file's sha256
    PAGE_GEOMETRY            the page rectangle
    PAGE_COUNT               informational: number of pages
    TEXT_POSITION            where each text span starts (x, y)
    FONT_FAMILY              the set of font names
    FONT_SIZE                the set of font sizes
    TEXT_SPACING_BASELINE    each span's advance extents (width, height) plus its
                             font/size/colour — glyph metrics, never the origin
    WRAP_SHRINK              line-break structure: how many lines the text
                             breaks into and how many spans / characters each
                             holds, in reading order (never a position)
    LAYOUT_GEOMETRY          every drawing's rect, kind, fill and stroke colour
    TABLE_LINES_BORDERS      stroke-only drawings including stroke width and
                             dash pattern (a rule is not a fill)
    IMAGE_PLACEMENT          the sorted set of image rectangles
    STAMP_ALPHA              how many images carry a soft mask (transparency)
    ASSET_LAYERING           image paint order as a permutation of the sorted
                             placement — z-order, not position
    REFERENCE_VALUE_PARITY   compiled values exist as source cell values
    RASTER_SIMILARITY        whole-page pixels at 72/150/300 dpi

Two honest limits, stated rather than papered over:

* Logo and stamp are **not** separate gates. The compiled template carries no
  semantic asset roles, so `IMAGE_PLACEMENT`/`STAMP_ALPHA`/`ASSET_LAYERING`
  measure every image the same way. Earlier revisions reported `LOGO_GEOMETRY`
  and `STAMP_GEOMETRY` as two names over one comparison; that inflated the gate
  count, so the duplicate names are gone rather than kept as aliases.
* `ASSET_LAYERING` knows image-against-image order only. MuPDF does not expose
  how images interleave with vector paint operations, so this gate does not
  claim to prove image-versus-vector layering.

Usage:
    certify.py --template-dir <dir> --baseline <pdf> --evidence <dir> --out <json>
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import fitz

CRITICAL_GATES = [
    "BASELINE_BYTE_IDENTICAL", "PAGE_GEOMETRY", "TEXT_POSITION", "FONT_FAMILY",
    "FONT_SIZE", "TEXT_SPACING_BASELINE", "WRAP_SHRINK", "LAYOUT_GEOMETRY",
    "TABLE_LINES_BORDERS", "IMAGE_PLACEMENT", "STAMP_ALPHA", "ASSET_LAYERING",
    "REFERENCE_VALUE_PARITY",
]
RASTER_DPIS = (72, 150, 300)


def sha256(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def raster_diff(a_pdf, b_pdf, pno, dpi, threshold=8):
    da, db = fitz.open(a_pdf), fitz.open(b_pdf)
    m = fitz.Matrix(dpi / 72, dpi / 72)
    pa = da[pno].get_pixmap(matrix=m, alpha=False)
    pb = db[pno].get_pixmap(matrix=m, alpha=False)
    n = 0
    if (pa.width, pa.height) == (pb.width, pb.height):
        sa, sb = pa.samples, pb.samples
        for i in range(0, len(sa), 3):
            if max(abs(sa[i] - sb[i]), abs(sa[i + 1] - sb[i + 1]),
                   abs(sa[i + 2] - sb[i + 2])) > threshold:
                n += 1
    else:
        n = -1
    da.close(); db.close()
    return n


def spans_of(pdf, pno):
    d = fitz.open(pdf)
    out = []
    for b in d[pno].get_text("dict")["blocks"]:
        if b.get("type") != 0:
            continue
        for l in b.get("lines", []):
            for s in l.get("spans", []):
                out.append((round(s["bbox"][0], 2), round(s["bbox"][1], 2),
                            round(s["bbox"][2], 2), round(s["bbox"][3], 2),
                            s["font"], round(s["size"], 2), s["color"],
                            "".join(c["c"] for c in s["chars"]) if "chars" in s else s["text"]))
    d.close()
    out.sort()
    return out


def span_extents(spans):
    """Glyph metrics per span: how much room the run occupies, not where it sits."""
    return sorted((round(s[2] - s[0], 2), round(s[3] - s[1], 2), s[4], s[5], s[6])
                  for s in spans)


def line_structure(pdf, pno):
    """How the text breaks into lines and how much each line holds.

    Reading order, no coordinates: moving a line or changing its font size must
    leave this gate alone, while splitting one line into two must move it. The
    origin of a line is `TEXT_POSITION`'s job, not this gate's.
    """
    d = fitz.open(pdf)
    out = []
    for b in d[pno].get_text("dict")["blocks"]:
        if b.get("type") != 0:
            continue
        for l in b.get("lines", []):
            spans = l.get("spans", [])
            if not spans:
                continue
            chars = sum(len("".join(c["c"] for c in s["chars"])) if "chars" in s
                        else len(s["text"]) for s in spans)
            out.append((len(spans), chars))
    d.close()
    return out


def drawings_of(pdf, pno):
    """Every drawing: rect, kind, fill and stroke colour (no stroke width)."""
    d = fitz.open(pdf)
    out = sorted((tuple(round(v, 2) for v in dr["rect"]), dr.get("type"),
                  str(dr.get("fill")), str(dr.get("color"))) for dr in d[pno].get_drawings())
    d.close()
    return out


def rules_of(pdf, pno):
    """Stroke-only drawings as table rules: rect, kind, colour, width, dashes.

    A filled shape has no stroke width, so a fill colour change moves
    `LAYOUT_GEOMETRY` and leaves this gate alone — and a rule width change does
    the opposite. That is what makes this a separate observation instead of a
    second name for the layout comparison.
    """
    d = fitz.open(pdf)
    out = []
    for dr in d[pno].get_drawings():
        if dr.get("type") not in ("s", "fs"):
            continue
        out.append((tuple(round(v, 2) for v in dr["rect"]), dr.get("type"),
                    str(dr.get("color")), round(float(dr.get("width") or 0), 2),
                    str(dr.get("dashes"))))
    d.close()
    return sorted(out)


def image_rects(pdf, pno):
    d = fitz.open(pdf)
    pg = d[pno]
    out = []
    for xref, smask, *_ in pg.get_images(full=True):
        for r in pg.get_image_rects(xref):
            out.append(tuple(round(v, 2) for v in r))
    d.close()
    return sorted(out)


def image_alpha(image_list):
    """How many images carry a soft mask — transparency as a count, not a place."""
    return sorted(1 if smask > 0 else 0 for _xref, smask, *_ in image_list)


def image_paint_order(pdf, pno):
    """Image z-order as a permutation of the sorted placement.

    `[0, 1]` means the first-painted image is also the left-most/top-most one;
    `[1, 0]` means two images swapped paint order without moving. Identical
    rectangles are indistinguishable and collapse, which is stated rather than
    guessed at.
    """
    d = fitz.open(pdf)
    pg = d[pno]
    infos = pg.get_image_info(xrefs=True)
    ordered = [tuple(round(v, 2) for v in info["bbox"])
               for info in sorted(infos, key=lambda i: i.get("number", 0))]
    ranks = {rect: n for n, rect in enumerate(sorted(set(ordered)))}
    d.close()
    return [ranks[rect] for rect in ordered]


def image_list(pdf, pno):
    d = fitz.open(pdf)
    out = list(d[pno].get_images(full=True))
    d.close()
    return out


def gates_for_page(base_pdf, baseline_pdf, pno) -> dict:
    """Every non-document, non-raster gate for one page of two PDFs."""
    gates = {}
    gates["BASELINE_BYTE_IDENTICAL"] = sha256(base_pdf) == sha256(baseline_pdf)

    d1, d2 = fitz.open(base_pdf), fitz.open(baseline_pdf)
    gates["PAGE_GEOMETRY"] = ([round(v, 2) for v in d1[pno].rect] ==
                              [round(v, 2) for v in d2[pno].rect])
    gates["PAGE_COUNT"] = d1.page_count == d2.page_count
    d1.close(); d2.close()

    s1, s2 = spans_of(base_pdf, pno), spans_of(baseline_pdf, pno)
    gates["TEXT_POSITION"] = [s[:2] for s in s1] == [s[:2] for s in s2]
    gates["FONT_FAMILY"] = sorted({s[4] for s in s1}) == sorted({s[4] for s in s2})
    gates["FONT_SIZE"] = sorted({s[5] for s in s1}) == sorted({s[5] for s in s2})
    gates["TEXT_SPACING_BASELINE"] = span_extents(s1) == span_extents(s2)
    gates["WRAP_SHRINK"] = (line_structure(base_pdf, pno) ==
                            line_structure(baseline_pdf, pno))

    gates["LAYOUT_GEOMETRY"] = (drawings_of(base_pdf, pno) ==
                                drawings_of(baseline_pdf, pno))
    gates["TABLE_LINES_BORDERS"] = rules_of(base_pdf, pno) == rules_of(baseline_pdf, pno)

    gates["IMAGE_PLACEMENT"] = image_rects(base_pdf, pno) == image_rects(baseline_pdf, pno)
    gates["STAMP_ALPHA"] = (image_alpha(image_list(base_pdf, pno)) ==
                            image_alpha(image_list(baseline_pdf, pno)))
    gates["ASSET_LAYERING"] = (image_paint_order(base_pdf, pno) ==
                               image_paint_order(baseline_pdf, pno))
    return gates


def reference_value_gate(template: dict, xlsx: dict) -> dict:
    """Compiled values must exist as values of the source's own cells."""
    import re

    def norm(s):
        return re.sub(r"[^0-9A-Za-z가-힣]", "", str(s)).lower()

    bv = template["baseline_values"]
    all_cells = []
    for sh in xlsx["sheets"].values():
        all_cells += [norm(c["value"]) for c in sh["cells"].values() if c["value"] is not None]
    cell_set = set(all_cells)
    checks = {
        "quote_number": norm(bv["quote_number"]) in cell_set,
        "recipient": norm(bv["recipient"]) in cell_set,
        "project_name": norm(bv["project_name"]) in cell_set,
        "issue_date_serial": str(int(bv["issue_date_serial"])) in cell_set,
        "items": all(norm(i["unit_price"]) in cell_set for i in bv["items"]
                     if i.get("unit_price") is not None),
    }
    return {"REFERENCE_VALUE_PARITY": all(checks.values()),
            "REFERENCE_VALUE_PARITY_detail": checks}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--template-dir", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--evidence", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    tdir = Path(a.template_dir)
    template = json.loads((tdir / "quote_template.json").read_text(encoding="utf-8"))
    xlsx = json.loads((Path(a.evidence) / "xlsx_analysis.json").read_text(encoding="utf-8"))
    base_pdf = tdir / template["resources"]["base_document"]["file"]
    pno = template["page"].get("index", 0)

    gates = gates_for_page(base_pdf, a.baseline, pno)
    gates.update(reference_value_gate(template, xlsx))
    gates["RASTER_SIMILARITY"] = {f"{dpi}dpi": raster_diff(base_pdf, a.baseline, pno, dpi)
                                  for dpi in RASTER_DPIS}

    all_pass = (all(gates[k] for k in CRITICAL_GATES)
                and all(v == 0 for v in gates["RASTER_SIMILARITY"].values()))
    result = {"template": "second_unrelated_quotation", "page_index": pno,
              "gates": gates, "critical_gates": CRITICAL_GATES,
              "CRITICAL_GATES_PASS": all_pass,
              "SECOND_TEMPLATE_CERTIFICATION": "PASS" if all_pass else "FAIL"}
    Path(a.out).write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: gates[k] for k in CRITICAL_GATES}, ensure_ascii=False, indent=1))
    print("RASTER_SIMILARITY:", gates["RASTER_SIMILARITY"])
    print("SECOND_TEMPLATE_CERTIFICATION:", result["SECOND_TEMPLATE_CERTIFICATION"])


if __name__ == "__main__":
    main()
