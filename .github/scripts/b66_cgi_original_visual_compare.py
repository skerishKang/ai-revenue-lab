"""Bounded visual measurement: current CGI browser PDF vs approved original PDF.

Expected quote facts differ, so source template's 30 dynamic slot rectangles
are masked before measurement. No raw PDF, source text or customer PII printed.
This is a MEASUREMENT, not owner-approved source-equivalent certification.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

def measure(original_path: Path, output_bytes: bytes, template_path: Path, manifest_path: Path):
    import fitz
    original_path=Path(original_path)
    template_path=Path(template_path)
    manifest=json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    expected=manifest["artifacts"]["source/original.pdf"]["sha256"]
    if hashlib.sha256(original_path.read_bytes()).hexdigest()!=expected:
        raise ValueError("approved_reference_hash_mismatch")
    tpl=json.loads(template_path.read_text(encoding="utf-8"))
    with fitz.open(original_path) as source, fitz.open(stream=output_bytes,filetype="pdf") as rendered:
        if len(source)!=1 or len(rendered)!=1:
            raise ValueError("cgi_page_count_mismatch")
        w=source[0].rect.width
        h=source[0].rect.height
        if abs(w-rendered[0].rect.width)>0.01 or abs(h-rendered[0].rect.height)>0.01:
            raise ValueError("cgi_page_size_mismatch")
        if w!=595.0 or h!=841.0:
            raise ValueError("reference_not_certified_a4")
        src=source[0].get_pixmap(matrix=fitz.Matrix(2,2),colorspace=fitz.csGRAY,alpha=False)
        dst=rendered[0].get_pixmap(matrix=fitz.Matrix(2,2),colorspace=fitz.csGRAY,alpha=False)
        if src.width!=dst.width or src.height!=dst.height:
            raise ValueError("cgi_image_dimensions_mismatch")
        width,height=src.width,src.height
        mask=bytearray(width*height)
        # Caution: no tolerance is claimed for the 2pt safety pad.
        for field in tpl["bindings"]:
            x0,y0,x1,y1=field["bbox"]
            xa=max(0,int((x0-2)*2));xb=min(width,int((x1+2)*2+1))
            ya=max(0,int((y0-2)*2));yb=min(height,int((y1+2)*2+1))
            for y in range(ya,yb):
                offset=y*width
                mask[offset+xa:offset+xb]=bytes([1])*(xb-xa)
        compared=changed16=changed32=mae=0
        a,b=src.samples,dst.samples
        for i in range(0,len(a),2):
            if mask[i]:continue
            compared+=1
            delta=abs(a[i]-b[i])
            mae+=delta
            changed16+=delta>16
            changed32+=delta>32
        if compared<width*height//6:
            raise ValueError("unmasked_reference_area_too_small")
        return {
            "pageCount":1,"pageWidthPt":w,"pageHeightPt":h,
            "originalTextCharacters":len(source[0].get_text().strip()),
            "browserTextCharacters":len(rendered[0].get_text().strip()),
            "maskedSlotCount":len(tpl["bindings"]),
            "unmaskedSamples":compared,
            "unmaskedMAE":round(mae/compared,3),
            "unmaskedChanged16Percent":round(100*changed16/compared,3),
            "unmaskedChanged32Percent":round(100*changed32/compared,3),
        }
