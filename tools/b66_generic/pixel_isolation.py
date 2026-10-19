# -*- coding: utf-8 -*-
"""Pixel-isolation check: compare a mutated render against the base document
and report changed pixels inside vs outside the declared allowed region."""
import argparse, json, sys
from pathlib import Path
import fitz

def render_page(pdf_path, pno, dpi):
    doc = fitz.open(pdf_path)
    pg = doc[pno]
    m = fitz.Matrix(dpi / 72, dpi / 72)
    pix = pg.get_pixmap(matrix=m, alpha=False)
    return pix

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--mut", required=True)
    ap.add_argument("--page", type=int, required=True)
    ap.add_argument("--region", required=True, help="x0,y0,x1,y1 allowed region (pt)")
    ap.add_argument("--dpi", type=int, default=150)
    ap.add_argument("--threshold", type=int, default=8)
    a = ap.parse_args()
    r = [float(x) for x in a.region.split(",")]

    pb = render_page(a.base, a.page, a.dpi)
    pm = render_page(a.mut, a.page, a.dpi)
    if (pb.width, pb.height) != (pm.width, pm.height):
        print("SIZE MISMATCH", (pb.width, pb.height), (pm.width, pm.height)); sys.exit(2)
    sb, sm = pb.samples, pm.samples
    scale = a.dpi / 72.0
    total = 0; outside = 0; obbox = None
    minx = miny = 10**9; maxx = maxy = -1
    for y in range(pb.height):
        row = y * pb.stride
        for x in range(pb.width):
            i = row + x * 3
            d = max(abs(sb[i]-sm[i]), abs(sb[i+1]-sm[i+1]), abs(sb[i+2]-sm[i+2]))
            if d > a.threshold:
                total += 1
                px, py = x / scale, y / scale
                minx = min(minx, px); maxx = max(maxx, px)
                miny = min(miny, py); maxy = max(maxy, py)
                if not (r[0] <= px <= r[2] and r[1] <= py <= r[3]):
                    outside += 1
                    if obbox is None:
                        obbox = [px, py, px, py]
                    else:
                        obbox[0] = min(obbox[0], px); obbox[1] = min(obbox[1], py)
                        obbox[2] = max(obbox[2], px); obbox[3] = max(obbox[3], py)
    out = {"dpi": a.dpi, "threshold": a.threshold, "region": r,
           "total_changed": total, "outside_changed": outside,
           "changed_bbox": [round(v, 1) for v in (minx, miny, maxx, maxy)] if total else None,
           "outside_bbox": [round(v, 1) for v in obbox] if obbox else None}
    print(json.dumps(out, ensure_ascii=False))

if __name__ == "__main__":
    main()
