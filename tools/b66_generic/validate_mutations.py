# -*- coding: utf-8 -*-
"""B66 generic mutation-robustness validator.

For each case: render the mutated PDF from the compiled template, derive the
allowed region from the *changed slots' own cover rects* (not a hand-picked
box), and assert that no pixel outside that region changed.

Usage:
    validate_mutations.py --template-dir <dir> --cases <dir> --outdir <dir> --dpi 150
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import fitz

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import render as R  # noqa: E402


def slot_regions(template: dict, slot: str) -> list[list[float]]:
    """Declared isolation regions that contain the changed slot's own anchors.

    The allowed area is the template's region set (source-derived, padded beyond
    the cover rects so cover-edge anti-aliasing stays inside), exactly as the
    certification contract defines it — not an ad-hoc box.
    """
    slots = template["mutable_slots"]
    pts: list[list[float]] = []

    def collect(node):
        if isinstance(node, dict):
            if isinstance(node.get("origin"), list):
                pts.append(node["origin"])
            if isinstance(node.get("cover"), list):
                c = node["cover"]
                pts.append([(c[0] + c[2]) / 2, (c[1] + c[3]) / 2])
            if isinstance(node.get("rect"), list):
                c = node["rect"]
                pts.append([(c[0] + c[2]) / 2, (c[1] + c[3]) / 2])
            for v in node.values():
                collect(v)
        elif isinstance(node, list):
            for v in node:
                collect(v)

    if slot in slots["camera"]:
        collect(slots["camera"][slot])
    elif slot.startswith("item_"):
        collect(slots["item_rows"].get(slot.split("_", 1)[1], {}).get("anchors", {}))
    elif slot in slots["totals"]:
        collect(slots["totals"][slot])

    hits = []
    for name, r in template["regions"].items():
        if any(r[0] <= p[0] <= r[2] and r[1] <= p[1] <= r[3] for p in pts):
            hits.append(r)
    return hits


def pixel_diff(base_pdf, mut_pdf, pno, dpi, threshold=8):
    db = fitz.open(base_pdf); dm = fitz.open(mut_pdf)
    m = fitz.Matrix(dpi / 72, dpi / 72)
    pb = db[pno].get_pixmap(matrix=m, alpha=False)
    pm = dm[pno].get_pixmap(matrix=m, alpha=False)
    scale = dpi / 72.0
    sb, sm = pb.samples, pm.samples
    pts = []
    for y in range(pb.height):
        row = y * pb.stride
        for x in range(pb.width):
            i = row + x * 3
            if max(abs(sb[i] - sm[i]), abs(sb[i + 1] - sm[i + 1]),
                   abs(sb[i + 2] - sm[i + 2])) > threshold:
                pts.append((x / scale, y / scale))
    db.close(); dm.close()
    return pts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--template-dir", required=True)
    ap.add_argument("--cases", required=True)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--dpi", type=int, default=150)
    ap.add_argument("--threshold", type=int, default=8)
    a = ap.parse_args()

    tdir = Path(a.template_dir)
    template = json.loads((tdir / "quote_template.json").read_text(encoding="utf-8"))
    pno = template["page"].get("index", 0)
    outdir = Path(a.outdir); outdir.mkdir(parents=True, exist_ok=True)
    cases_dir = Path(a.cases)

    results = []
    for cf in sorted(cases_dir.glob("*.json")):
        name = cf.stem
        out_pdf = outdir / f"{name}.pdf"
        try:
            res = R.render(str(cf), str(out_pdf), tdir)
        except R.B66RenderError as e:
            results.append({"case": name, "status": "REJECTED", "code": e.code})
            continue
        if res["byte_identical"]:
            results.append({"case": name, "status": "NO_CHANGE"})
            continue
        allowed = []
        for s in res["changed_slots"]:
            allowed += slot_regions(template, s)
        pts = pixel_diff(tdir / template["resources"]["base_document"]["file"],
                         out_pdf, pno, a.dpi, a.threshold)
        outside = [p for p in pts
                   if not any(r[0] <= p[0] <= r[2] and r[1] <= p[1] <= r[3] for r in allowed)]
        results.append({"case": name, "status": "PASS" if not outside else "FAIL",
                        "changed_slots": res["changed_slots"],
                        "total_changed": len(pts), "outside_changed": len(outside),
                        "outside_sample": [[round(x, 1), round(y, 1)] for x, y in outside[:5]]})
    print(json.dumps(results, ensure_ascii=False, indent=1))
    n_fail = sum(1 for r in results if r["status"] == "FAIL")
    print(f"\nCASES={len(results)} FAIL={n_fail}")
    sys.exit(1 if n_fail else 0)


if __name__ == "__main__":
    main()
