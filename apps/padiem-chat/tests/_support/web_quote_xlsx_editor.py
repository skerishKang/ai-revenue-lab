"""공용 시험 준비 — 웹 견적 XLSX 합성 픽스처(고객 데이터 없음).

test_3933_web_quote_xlsx_editor가 들고 있던 quote_fixture를 여기 옮겨
시험끼리 import가 없게 한다(#8061).
"""
from __future__ import annotations

from io import BytesIO
from zipfile import ZipFile

MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def quote_fixture(*, extra=None, sheet_extra="", formula="B4*B5") -> bytes:
    out = BytesIO()

    def cell(ref, inner, style="1", t=""):
        return f'<c r="{ref}" s="{style}"{t}>{inner}</c>'

    sheet = (
        f'<worksheet xmlns="{MAIN}">'
        '<sheetData><row r="1">'
        + cell("A1", '<is><t>Original University</t></is>', t=' t="inlineStr"')
        + '</row><row r="4">'
        + cell("B4", "<v>88000000</v>")
        + '</row><row r="5">'
        + cell("B5", "<v>0.1</v>")
        + '</row><row r="6">'
        + cell("B6", f"<f>{formula}</f><v>8800000</v>")
        + '</row><row r="7">'
        + cell("B7", "<f>SUM(B4,B6)</f><v>96800000</v>")
        + '</row></sheetData>'
        '<mergeCells count="1"><mergeCell ref="A1:D1"/></mergeCells>'
        + sheet_extra + '</worksheet>'
    )
    with ZipFile(out, "w") as z:
        z.writestr("[Content_Types].xml",
                   '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                   '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                   '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
                   '</Types>')
        z.writestr("_rels/.rels",
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
                   '</Relationships>')
        z.writestr("xl/workbook.xml",
                   f'<workbook xmlns="{MAIN}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                   '<sheets><sheet name="Quote" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
                   '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
                   '</Relationships>')
        z.writestr("xl/worksheets/sheet1.xml", sheet)
        z.writestr("xl/styles.xml",
                   f'<styleSheet xmlns="{MAIN}"><fonts count="1"><font><sz val="11"/></font></fonts>'
                   '<fills count="1"><fill><patternFill patternType="none"/></fill></fills>'
                   '<borders count="1"><border/></borders>'
                   '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
                   '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
                   '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/></cellXfs></styleSheet>')
        if extra:
            z.writestr(extra, b"unexpected")
    return out.getvalue()
