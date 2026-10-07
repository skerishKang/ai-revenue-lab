# -*- coding: utf-8 -*-
"""Generate the public-safe synthetic second-template fixture.

The fixture is a *materially different* Korean quotation from the CGI reference
(landscape, left-aligned header block, a different item-column set, different
totals wording) but carries ONLY synthetic values, so it can live in the public
repository. It is the CI regression input for the generic analyzer/compiler.

Run:
    python make_synthetic_fixture.py --outdir .

Writes source.xlsx and reference.pdf next to this script.
No network call, no model call.
"""

from __future__ import annotations

import argparse
import zipfile
from pathlib import Path

# ── synthetic facts (SYNTHETIC TEST DATA — never real) ──
SYNTH = {
    "quote_number": "SYN-2ND-2026-0001",
    "date_serial": 45231,
    "recipient": "합성테스트주식회사",
    "project": "합성 견적서 일반화 검증 공사",
    "items": [
        ("합성장비 A", "식", 1, 12500000),
        ("합성장비 B", "개", 4, 830000),
        ("합성설치비", "식", 1, 2400000),
    ],
    "vat_rate": 0.1,
}
MARKER = "SYNTHETIC TEST DATA / 실사용 금지"


def _sheet_cells():
    """(ref, value) pairs laid out as a left-aligned header quotation."""
    rows = []
    rows.append(("A2", "견적번호")); rows.append(("B2", SYNTH["quote_number"]))
    rows.append(("A3", "작성일자")); rows.append(("B3", SYNTH["date_serial"]))
    rows.append(("A4", "제 출 처")); rows.append(("B4", SYNTH["recipient"]))
    rows.append(("A5", "건    명")); rows.append(("B5", SYNTH["project"]))
    rows.append(("A7", MARKER))
    rows.append(("A9", "번호")); rows.append(("B9", "품명")); rows.append(("C9", "규격"))
    rows.append(("D9", "단위")); rows.append(("E9", "수량")); rows.append(("F9", "단가"))
    rows.append(("G9", "금액"))
    r = 10
    for i, (name, unit, qty, price) in enumerate(SYNTH["items"], start=1):
        rows.append((f"A{r}", i)); rows.append((f"B{r}", name)); rows.append((f"C{r}", ""))
        rows.append((f"D{r}", unit)); rows.append((f"E{r}", qty)); rows.append((f"F{r}", price))
        rows.append((f"G{r}", qty * price))
        r += 1
    sub = sum(q * p for _, _, q, p in SYNTH["items"])
    vat = int(sub * SYNTH["vat_rate"])
    rows.append(("B15", "소계")); rows.append(("G15", sub))
    rows.append(("B16", "부가세")); rows.append(("G16", vat))
    rows.append(("B17", "총계")); rows.append(("G17", sub + vat))
    return rows, sub, vat, sub + vat


def write_xlsx(path: Path):
    rows, *_ = _sheet_cells()
    # shared strings
    strings, sidx = [], {}
    for _ref, v in rows:
        if isinstance(v, str) and v != "":
            if v not in sidx:
                sidx[v] = len(strings); strings.append(v)
    cell_xml = []
    by_row = {}
    for ref, v in rows:
        if v == "":
            continue
        row = int("".join(ch for ch in ref if ch.isdigit()))
        by_row.setdefault(row, []).append((ref, v))
    for row in sorted(by_row):
        cs = []
        for ref, v in sorted(by_row[row], key=lambda t: t[0]):
            if isinstance(v, int):
                cs.append(f'<c r="{ref}"><v>{v}</v></c>')
            else:
                cs.append(f'<c r="{ref}" t="s"><v>{sidx[v]}</v></c>')
        cell_xml.append(f'<row r="{row}">' + "".join(cs) + "</row>")
    sheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<dimension ref="A1:G17"/>'
        f'<sheetData>{"".join(cell_xml)}</sheetData>'
        '<pageMargins left="0.7" right="0.7" top="0.75" bottom="0.75" header="0.3" footer="0.3"/>'
        '<pageSetup paperSize="9" orientation="landscape" scale="100" fitToWidth="1" fitToHeight="1"/>'
        '</worksheet>')
    shared = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              f'<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
              f'count="{len(strings)}" uniqueCount="{len(strings)}">'
              + "".join(f"<si><t>{s}</t></si>" for s in strings) + "</sst>")
    workbook = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                '<sheets><sheet name="견적서" sheetId="1" r:id="rId1"/></sheets></workbook>')
    wbrels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
              '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
              '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" Target="sharedStrings.xml"/>'
              '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
              '</Relationships>')
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            '</Relationships>')
    ct = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
          '<Default Extension="xml" ContentType="application/xml"/>'
          '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
          '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
          '<Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>'
          '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
          '</Types>')
    styles = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
              '<fonts count="1"><font><sz val="9"/><name val="Malgun Gothic"/></font></fonts>'
              '<fills count="1"><fill><patternFill patternType="none"/></fill></fills>'
              '<borders count="1"><border/></borders>'
              '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
              '<cellXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/></cellXfs>'
              '</styleSheet>')
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", ct)
        z.writestr("_rels/.rels", rels)
        z.writestr("xl/workbook.xml", workbook)
        z.writestr("xl/_rels/workbook.xml.rels", wbrels)
        z.writestr("xl/worksheets/sheet1.xml", sheet)
        z.writestr("xl/sharedStrings.xml", shared)
        z.writestr("xl/styles.xml", styles)


def write_pdf(path: Path):
    from datetime import date, timedelta
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfgen import canvas
    FONT = "HYSMyeongJo-Medium"
    pdfmetrics.registerFont(UnicodeCIDFont(FONT))
    W, H = 841.89, 595.28  # A4 landscape
    c = canvas.Canvas(str(path), pagesize=(W, H), invariant=1)
    d = date(1899, 12, 30) + timedelta(days=SYNTH["date_serial"])
    date_text = f"{d.year:04d}년 {d.month:02d}월 {d.day:02d}일"
    c.setFont(FONT, 10)
    x = 70
    c.setFont(FONT, 22); c.drawString(x + 240, H - 60, "견  적  서"); c.setFont(FONT, 10)
    hdr = [("견적번호", SYNTH["quote_number"], 10.5),
           ("작성일자", date_text, 9),
           ("제 출 처", SYNTH["recipient"], 10),
           ("건    명", SYNTH["project"], 10)]
    y = H - 110
    for label, val, sz in hdr:
        c.setFont(FONT, 10); c.drawString(x, y, label)
        c.setFont(FONT, sz); c.drawString(x + 70, y, val)
        y -= 18
    c.setFont(FONT, 9)
    c.drawString(x, H - 200, MARKER)
    # written total
    rows, sub, vat, grand = _sheet_cells()
    from itertools import groupby
    c.setFont(FONT, 10)
    c.drawString(x, H - 232, f" 합계금액 : 일금 {grand:,}원정 ( \\ {grand:,} )")
    # item table
    ty = H - 270
    cols = [("번호", x), ("품명", x + 45), ("규격", x + 175), ("단위", x + 245),
            ("수량", x + 285), ("단가", x + 350), ("금액", x + 470)]
    c.setFont(FONT, 8.5)
    for name, cx in cols:
        c.drawString(cx, ty, name)
    ry = ty - 20
    for i, (name, unit, qty, price) in enumerate(SYNTH["items"], start=1):
        c.setFont(FONT, 9)
        c.drawString(x, ry, str(i))
        c.drawString(x + 45, ry, name)
        c.drawString(x + 245, ry, unit)
        c.drawRightString(x + 300, ry, str(qty))
        c.drawRightString(x + 400, ry, f"{price:,}")
        c.drawRightString(x + 520, ry, f"{qty * price:,}")
        ry -= 19
    # totals
    ty2 = ry - 30
    for label, val in (("[ 소  계 ]", sub), ("[ V.A.T ]", vat), ("[ 총  계 ]", grand)):
        c.setFont(FONT, 9)
        c.drawString(x + 90, ty2, label)
        c.drawRightString(x + 520, ty2, f"{val:,}")
        ty2 -= 19
    c.showPage(); c.save()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", default=str(Path(__file__).resolve().parent))
    a = ap.parse_args()
    out = Path(a.outdir); out.mkdir(parents=True, exist_ok=True)
    write_xlsx(out / "source.xlsx")
    write_pdf(out / "reference.pdf")
    print("wrote", out / "source.xlsx", out / "reference.pdf")


if __name__ == "__main__":
    main()
