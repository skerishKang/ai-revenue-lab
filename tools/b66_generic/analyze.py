# -*- coding: utf-8 -*-
"""B66 generic source analyzer (template-agnostic).

READ-ONLY. Produces two evidence JSONs from a source pair:

    analyze.py --xlsx <path> --pdf <path> --outdir <dir>

    <outdir>/xlsx_analysis.json   workbook/sheet/cell/merge/drawing/VML facts
    <outdir>/pdf_analysis.json    page geometry, per-char text spans, images,
                                  vector drawing ops

This module contains NO template-specific, customer-specific or document-specific
literal. Everything it emits is a raw observation of the input files; semantic
role assignment happens later in the generic compiler.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

NS = {
    "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "xdr": "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006",
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(p: Path) -> str:
    return sha256_bytes(Path(p).read_bytes())


def col_to_index(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def index_to_col(idx: int) -> str:
    letters, n = "", idx + 1
    while n > 0:
        n, rem = divmod(n - 1, 26)
        letters = chr(ord("A") + rem) + letters
    return letters


def _resolve_mc_children(container) -> list:
    """Expand mc:AlternateContent to its Fallback branch (Excel-applied branch).

    HanCell/Excel save styles.xml with AlternateContent wrappers; the Fallback
    branch is what Excel actually applies, so style indices must be counted with
    those children inlined (#3535 lesson).
    """
    out = []
    for child in container:
        tag = child.tag.split("}")[-1]
        if tag == "AlternateContent":
            fb = child.find(f"{{{NS['mc']}}}Fallback")
            if fb is not None:
                out.extend(_resolve_mc_children(fb))
        else:
            out.append(child)
    return out


# ────────────────────────────── XLSX ──────────────────────────────

def analyze_xlsx(path: Path) -> dict:
    data = path.read_bytes()
    zf = zipfile.ZipFile(path)
    nsm = {"m": NS["main"]}
    names = zf.namelist()

    wb = ET.fromstring(zf.read("xl/workbook.xml"))
    sheets = [{"name": s.get("name"), "sheet_id": s.get("sheetId"),
               "rel_id": s.get("{%s}id" % NS["r"])}
              for s in wb.findall(".//m:sheet", nsm)]
    defined_names = [{"name": d.get("name"), "value": (d.text or "").strip()}
                     for d in wb.findall(".//m:definedNames/m:definedName", nsm)]

    rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    relmap = {r.get("Id"): r.get("Target") for r in rels}

    shared = []
    if "xl/sharedStrings.xml" in names:
        ss = ET.fromstring(zf.read("xl/sharedStrings.xml"))
        for si in ss.findall("m:si", nsm):
            shared.append("".join(t.text or "" for t in si.findall(".//m:t", nsm)))

    styles_root = ET.fromstring(zf.read("xl/styles.xml"))
    fonts = []
    for f in _resolve_mc_children(styles_root.find("m:fonts", nsm)):
        nm = f.find("m:name", nsm); sz = f.find("m:sz", nsm)
        b = f.find("m:b", nsm); col = f.find("m:color", nsm)
        fonts.append({"name": nm.get("val") if nm is not None else None,
                      "size": float(sz.get("val")) if sz is not None else None,
                      "bold": b is not None,
                      "color": (col.get("rgb") or col.get("theme")) if col is not None else None})
    numfmts = {}
    nfc = styles_root.find("m:numFmts", nsm)
    if nfc is not None:
        for nf in _resolve_mc_children(nfc):
            numfmts[nf.get("numFmtId")] = nf.get("formatCode")
    cellxfs = []
    for xf in _resolve_mc_children(styles_root.find("m:cellXfs", nsm)):
        al = xf.find("m:alignment", nsm)
        cellxfs.append({
            "num_fmt_id": int(xf.get("numFmtId", "0")),
            "font_id": int(xf.get("fontId", "0")),
            "fill_id": int(xf.get("fillId", "0")),
            "border_id": int(xf.get("borderId", "0")),
            "alignment": ({"horizontal": al.get("horizontal"), "vertical": al.get("vertical"),
                           "wrap_text": al.get("wrapText") == "1",
                           "shrink_to_fit": al.get("shrinkToFit") == "1"}
                          if al is not None else {}),
        })

    sheets_out = {}
    for sh in sheets:
        target = relmap.get(sh["rel_id"])
        if not target:
            continue
        ws = "xl/" + target.lstrip("/")
        if ws not in names:
            ws = "xl/worksheets/" + Path(target).name
        if ws not in names:
            continue
        root = ET.fromstring(zf.read(ws))
        dim = root.find("m:dimension", nsm)
        cells = {}
        for row in root.find("m:sheetData", nsm):
            rnum = int(row.get("r"))
            for c in row.findall("m:c", nsm):
                ref = c.get("r")
                letters = re.match(r"([A-Z]+)", ref).group(1)
                t = c.get("t", "n")
                v_el = c.find("m:v", nsm); f_el = c.find("m:f", nsm)
                raw = v_el.text if v_el is not None else None
                formula = ("=" + f_el.text) if (f_el is not None and f_el.text) else None
                if t == "s" and raw is not None:
                    raw = shared[int(raw)]
                elif t == "n" and raw is not None and re.match(r"^-?\d+$", raw):
                    raw = int(raw)
                elif t == "n" and raw is not None:
                    try:
                        raw = float(raw)
                    except ValueError:
                        pass
                cells[ref] = {"coord": ref, "col": col_to_index(letters), "row": rnum,
                              "value": raw, "formula": formula,
                              "style_id": int(c.get("s", "0"))}
        merges = [m.get("ref") for m in root.findall(".//m:mergeCell", nsm)]
        rows = {}
        for row in root.find("m:sheetData", nsm):
            rnum = int(row.get("r"))
            ht = row.get("ht")
            rows[rnum] = {"height_pt": float(ht) if ht else None,
                          "custom_height": row.get("customHeight") == "1",
                          "hidden": row.get("hidden") == "1"}
        cols = {}
        for c in root.findall(".//m:cols/m:col", nsm):
            if c.get("min") is None or c.get("max") is None:
                continue
            cmin, cmax = int(c.get("min")), int(c.get("max"))
            w = c.get("width")
            for i in range(cmin, cmax + 1):
                cols[index_to_col(i - 1)] = {
                    "width_units": float(w) if w else None,
                    "custom_width": c.get("customWidth") == "1",
                    "hidden": c.get("hidden") == "1"}
        ps = root.find("m:pageSetup", nsm)
        pm = root.find("m:pageMargins", nsm)
        page = {
            "paper_size": ps.get("paperSize") if ps is not None else None,
            "orientation": ps.get("orientation") if ps is not None else None,
            "scale": ps.get("scale") if ps is not None else None,
            "fit_to_width": ps.get("fitToWidth") if ps is not None else None,
            "fit_to_height": ps.get("fitToHeight") if ps is not None else None,
            "margins_pt": ({k: round(float(pm.get(k)) * 72, 3)
                            for k in ("left", "right", "top", "bottom", "header", "footer")}
                           if pm is not None else {}),
        }
        sheets_out[sh["name"]] = {
            "dimension": dim.get("ref") if dim is not None else None,
            "cells": dict(sorted(cells.items())),
            "merges": merges, "rows": rows, "columns": dict(sorted(cols.items())),
            "page": page,
        }

    # drawings (images with anchors)
    drawing_images = []
    for dn in sorted(n for n in names if re.match(r"xl/drawings/drawing\d+\.xml$", n)):
        relpath = f"xl/drawings/_rels/{Path(dn).name}.rels"
        drels = {}
        if relpath in names:
            for rel in ET.fromstring(zf.read(relpath)):
                drels[rel.get("Id")] = rel.get("Target")
        droot = ET.fromstring(zf.read(dn))
        for anchor in droot:
            pic = anchor.find(".//xdr:pic", NS)
            if pic is None:
                continue
            blip = pic.find(".//a:blip", NS)
            embed = blip.get("{%s}embed" % NS["r"]) if blip is not None else None
            media = drels.get(embed, "").replace("../", "xl/")
            nm = pic.find(".//xdr:cNvPr", NS)

            def cellpos(el):
                if el is None:
                    return None
                return {"col": int(el.find("xdr:col", NS).text),
                        "col_off_emu": int(el.find("xdr:colOff", NS).text),
                        "row": int(el.find("xdr:row", NS).text),
                        "row_off_emu": int(el.find("xdr:rowOff", NS).text)}
            drawing_images.append({
                "drawing": dn, "name": nm.get("name") if nm is not None else None,
                "media": media, "embed_rid": embed,
                "from": cellpos(anchor.find("xdr:from", NS)),
                "to": cellpos(anchor.find("xdr:to", NS)),
                "sha256": sha256_bytes(zf.read(media)) if media in names else None})

    # VML shapes (camera / linked picture)
    vml_shapes = []
    for vn in [n for n in names if n.endswith(".vml")]:
        txt = zf.read(vn).decode("utf-8", "ignore")
        for sm in re.finditer(r'<v:shape id="([^"]+)"[^>]*>((?:(?!</v:shape>).)*)</v:shape>', txt, re.S):
            sid, body = sm.group(1), sm.group(2)
            am = re.search(r"<x:Anchor>([^<]*)</x:Anchor>", body)
            fm = re.search(r"<x:FmlaPict>([^<]*)</x:FmlaPict>", body)
            rm = re.search(r'<v:imagedata o:relid="(rId\d+)"', body)
            vml_shapes.append({"file": vn, "shape_id": sid,
                               "anchor_raw": am.group(1) if am else None,
                               "fmla_pict": fm.group(1) if fm else None,
                               "is_camera": "<x:Camera" in body,
                               "imagedata_relid": rm.group(1) if rm else None})

    return {
        "source": {"path": str(path), "sha256": sha256_bytes(data), "size": len(data)},
        "workbook": {"sheets": sheets, "defined_names": defined_names},
        "sheet_names": [s["name"] for s in sheets],
        "sheets": sheets_out,
        "styles": {"fonts": fonts, "cellxfs": cellxfs, "numfmts_custom": numfmts},
        "drawing_images": drawing_images,
        "vml_shapes": vml_shapes,
    }


# ────────────────────────────── PDF ──────────────────────────────

def analyze_pdf(path: Path) -> dict:
    import fitz
    data = path.read_bytes()
    doc = fitz.open(path)
    pages = []
    font_buffers = {}
    for pno, page in enumerate(doc):
        page_fonts = []
        for xref, ext, ftype, basefont, name, encoding, referencer in page.get_fonts(full=True):
            page_fonts.append({"xref": xref, "ext": ext, "type": ftype,
                               "basefont": basefont, "ref_name": name})
            if xref not in font_buffers:
                try:
                    _bn, ext2, ftype2, buf = doc.extract_font(xref)
                    font_buffers[str(xref)] = {"basefont": basefont, "ext": ext2,
                                               "type": ftype2,
                                               "sha256": sha256_bytes(buf) if buf else None,
                                               "size": len(buf) if buf else 0}
                except Exception:
                    pass
        raw = page.get_text("rawdict",
                            flags=fitz.TEXTFLAGS_DICT & ~fitz.TEXT_PRESERVE_LIGATURES)
        spans = []
        for block in raw.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                if line.get("wmode", 0) != 0:
                    continue
                for span in line.get("spans", []):
                    chars = [{"c": ch["c"],
                              "origin": [round(v, 2) for v in ch["origin"]],
                              "bbox": [round(v, 2) for v in ch["bbox"]]}
                             for ch in span.get("chars", [])]
                    if not chars:
                        continue
                    spans.append({"font": span["font"], "size": round(span["size"], 3),
                                  "flags": span["flags"], "color": span["color"],
                                  "bbox": [round(v, 2) for v in span["bbox"]],
                                  "text": "".join(c["c"] for c in chars),
                                  "chars": chars, "page": pno})
        images = []
        for entry in page.get_images(full=True):
            xref, smask, pw, ph = entry[0], entry[1], entry[2], entry[3]
            rects = page.get_image_rects(xref)
            base = doc.extract_image(xref)
            smask_bytes = None
            if smask:
                sm = doc.extract_image(smask)
                smask_bytes = {"xref": smask, "ext": sm["ext"],
                               "sha256": sha256_bytes(sm["image"])}
            images.append({"xref": xref, "smask_xref": smask, "has_alpha": smask > 0,
                           "pixel_w": pw, "pixel_h": ph, "ext": base["ext"],
                           "sha256": sha256_bytes(base["image"]),
                           "bboxes": [[round(v, 2) for v in r] for r in rects],
                           "smask_bytes": smask_bytes, "page": pno})
        ops = []
        for d in page.get_drawings():
            ops.append({
                "type": d.get("type"),
                "rect": [round(v, 2) for v in d["rect"]],
                "fill": d.get("fill"), "color": d.get("color"), "width": d.get("width"),
                "even_odd": d.get("even_odd"),
                "fill_opacity": d.get("fill_opacity"),
                "stroke_opacity": d.get("stroke_opacity"),
                "items": [{"op": it[0],
                           "points": [round(v, 2) for pt in it[1:]
                                      if isinstance(pt, (tuple, list)) for v in pt],
                           "rect": ([round(v, 2) for v in it[1]]
                                    if it[0] == "re" and len(it) > 1 else None)}
                          for it in d.get("items", [])],
                "page": pno})
        pages.append({"index": pno,
                      "width_pt": round(page.rect.width, 3),
                      "height_pt": round(page.rect.height, 3),
                      "mediabox": [round(v, 2) for v in page.mediabox],
                      "text_spans": spans, "images": images, "drawings": ops,
                      "page_fonts": page_fonts})
    result = {"source": {"path": str(path), "sha256": sha256_bytes(data), "size": len(data)},
              "page_count": doc.page_count, "pages": pages, "fonts_declared": font_buffers}
    doc.close()
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description="B66 generic source analyzer")
    ap.add_argument("--xlsx", required=True)
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--outdir", required=True)
    a = ap.parse_args()
    outdir = Path(a.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    x = analyze_xlsx(Path(a.xlsx))
    (outdir / "xlsx_analysis.json").write_text(
        json.dumps(x, ensure_ascii=False, indent=1), encoding="utf-8")
    p = analyze_pdf(Path(a.pdf))
    (outdir / "pdf_analysis.json").write_text(
        json.dumps(p, ensure_ascii=False), encoding="utf-8")
    print("written:", outdir / "xlsx_analysis.json", outdir / "pdf_analysis.json")
    print("sheets:", x["sheet_names"], "| pages:", p["page_count"])


if __name__ == "__main__":
    main()
