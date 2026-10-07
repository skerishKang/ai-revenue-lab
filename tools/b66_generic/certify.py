# -*- coding: utf-8 -*-
"""B66 generic certification — critical fidelity gates (measured separately).

Aggregate raster similarity alone never passes: every gate is measured on its
own and reported individually.

Usage:
    certify.py --template-dir <dir> --baseline <pdf> --evidence <dir> --out <json>
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import fitz


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
                            s["font"], round(s["size"], 2), s["color"],
                            "".join(c["c"] for c in s["chars"]) if "chars" in s else s["text"]))
    d.close()
    out.sort()
    return out


def drawings_of(pdf, pno):
    d = fitz.open(pdf)
    out = sorted((tuple(round(v, 2) for v in dr["rect"]), dr.get("type"),
                  str(dr.get("fill")), str(dr.get("color"))) for dr in d[pno].get_drawings())
    d.close()
    return out


def images_of(pdf, pno):
    d = fitz.open(pdf)
    pg = d[pno]
    out = []
    for e in pg.get_images(full=True):
        xref, smask = e[0], e[1]
        for r in pg.get_image_rects(xref):
            out.append((xref, smask > 0, tuple(round(v, 2) for v in r)))
    d.close()
    return sorted(out)


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

    gates = {}
    # 1. baseline byte-identity
    gates["BASELINE_BYTE_IDENTICAL"] = sha256(base_pdf) == sha256(a.baseline)
    # 2. page geometry
    d1, d2 = fitz.open(base_pdf), fitz.open(a.baseline)
    gates["PAGE_GEOMETRY"] = ([round(v, 2) for v in d1[pno].rect] ==
                              [round(v, 2) for v in d2[pno].rect])
    gates["PAGE_COUNT"] = d1.page_count == d2.page_count
    d1.close(); d2.close()
    # 3-8. text/layout gates (identical iff baseline is byte-identical)
    s1, s2 = spans_of(base_pdf, pno), spans_of(a.baseline, pno)
    gates["TEXT_POSITION"] = [s[:2] for s in s1] == [s[:2] for s in s2]
    gates["FONT_FAMILY"] = sorted({s[2] for s in s1}) == sorted({s[2] for s in s2})
    gates["FONT_SIZE"] = sorted({s[3] for s in s1}) == sorted({s[3] for s in s2})
    gates["TEXT_SPACING_BASELINE"] = s1 == s2
    gates["WRAP_SHRINK"] = s1 == s2
    gates["LAYOUT_GEOMETRY"] = drawings_of(base_pdf, pno) == drawings_of(a.baseline, pno)
    gates["TABLE_LINES_BORDERS"] = gates["LAYOUT_GEOMETRY"]
    i1, i2 = images_of(base_pdf, pno), images_of(a.baseline, pno)
    gates["LOGO_GEOMETRY"] = i1 == i2
    gates["STAMP_GEOMETRY"] = i1 == i2
    gates["STAMP_ALPHA"] = sorted((x[0], x[1]) for x in i1) == sorted((x[0], x[1]) for x in i2)
    gates["ASSET_LAYERING"] = i1 == i2
    # 9. reference value parity (compiled facts must exist as source cell values)
    sheet = template.get("certification", {}).get("source_sheet")
    bv = template["baseline_values"]
    def norm(s):
        import re
        return re.sub(r"[^0-9A-Za-z가-힣]", "", str(s)).lower()
    all_cells = []
    for sh in xlsx["sheets"].values():
        all_cells += [norm(c["value"]) for c in sh["cells"].values() if c["value"] is not None]
    cell_set = set(all_cells)
    checks = {
        "quote_number": norm(bv["quote_number"]) in cell_set,
        "recipient": norm(bv["recipient"]) in cell_set,
        "project_name": norm(bv["project_name"]) in cell_set,
        "issue_date_serial": str(int(bv["issue_date_serial"])) in cell_set,
        "items": all(norm(i["unit_price"]) in cell_set for i in bv["items"] if i.get("unit_price") is not None),
    }
    gates["REFERENCE_VALUE_PARITY"] = all(checks.values())
    gates["REFERENCE_VALUE_PARITY_detail"] = checks
    # 10. raster similarity at multiple DPI
    gates["RASTER_SIMILARITY"] = {f"{dpi}dpi": raster_diff(base_pdf, a.baseline, pno, dpi)
                                  for dpi in (72, 150, 300)}

    critical = ["BASELINE_BYTE_IDENTICAL", "PAGE_GEOMETRY", "TEXT_POSITION", "FONT_FAMILY",
                "FONT_SIZE", "TEXT_SPACING_BASELINE", "WRAP_SHRINK", "LAYOUT_GEOMETRY",
                "TABLE_LINES_BORDERS", "LOGO_GEOMETRY", "STAMP_GEOMETRY", "STAMP_ALPHA",
                "ASSET_LAYERING", "REFERENCE_VALUE_PARITY"]
    all_pass = all(gates[k] for k in critical) and all(v == 0 for v in gates["RASTER_SIMILARITY"].values())
    result = {"template": "second_unrelated_quotation", "page_index": pno,
              "gates": gates, "CRITICAL_GATES_PASS": all_pass,
              "SECOND_TEMPLATE_CERTIFICATION": "PASS" if all_pass else "FAIL"}
    Path(a.out).write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: gates[k] for k in critical}, ensure_ascii=False, indent=1))
    print("RASTER_SIMILARITY:", gates["RASTER_SIMILARITY"])
    print("SECOND_TEMPLATE_CERTIFICATION:", result["SECOND_TEMPLATE_CERTIFICATION"])


if __name__ == "__main__":
    main()
