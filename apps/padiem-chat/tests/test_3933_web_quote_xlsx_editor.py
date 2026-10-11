"""#3933 synthetic WEB-FIRST quote XLSX deterministic edit proof; no customer data."""
from __future__ import annotations

import hashlib
from io import BytesIO
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest

from app.claw_web_xlsx_quote_editor import (
    WebQuoteEditUnsupported, revise_single_sheet_quote,
)
from app.hark_3936_acceptance import _sheet

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


def revise(data, **overrides):
    kwargs = dict(
        original=data, original_sha256=hashlib.sha256(data).hexdigest(),
        school_name="광주대학교", supply_amount=99_200_000,
    )
    kwargs.update(overrides)
    return revise_single_sheet_quote(**kwargs)


def test_genuine_zip_xlsx_edit_preserves_formula_style_merges_other_parts_and_original_bytes():
    original = quote_fixture()
    snapshot = bytes(original)
    result = revise(original)
    assert result.revised_xlsx != snapshot
    assert hashlib.sha256(snapshot).hexdigest() == result.source_sha256
    assert hashlib.sha256(result.revised_xlsx).hexdigest() == result.revised_sha256
    assert (result.requested_school_name, result.vat_amount, result.total_amount) == (
        "광주대학교", 9_920_000, 109_120_000,
    )
    before, merges = _sheet(original)
    after, after_merges = _sheet(result.revised_xlsx)
    assert merges == after_merges == ("A1:D1",)
    assert set(before) == set(after)
    for ref in before:
        assert before[ref]["style"] == after[ref]["style"]
    for ref in ("B6", "B7"):
        assert before[ref]["formula"] == after[ref]["formula"]
    assert [after[k]["value"] for k in ("B4", "B5", "B6", "B7")] == [
        "99200000", "0.1", "9920000", "109120000",
    ]
    with ZipFile(BytesIO(result.revised_xlsx)) as z:
        root = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
        a1 = next(x for x in root.iter(f"{{{MAIN}}}c") if x.get("r") == "A1")
        assert a1.find(f"{{{MAIN}}}is/{{{MAIN}}}t").text == "광주대학교"
    with ZipFile(BytesIO(original)) as a, ZipFile(BytesIO(result.revised_xlsx)) as b:
        assert set(a.namelist()) == set(b.namelist())
        for name in a.namelist():
            if name != "xl/worksheets/sheet1.xml":
                assert a.read(name) == b.read(name)
    assert original == snapshot
    assert result.print_pdf_fidelity.startswith("UNSUPPORTED")


@pytest.mark.parametrize("overrides,reason", [
    ({"original_sha256": "0" * 64}, "SHA_MISMATCH"),
    ({"school_name": "=HYPERLINK(1,1)"}, "SCHOOL_NAME_UNSAFE"),
    ({"school_name": "../secret"}, None),
    ({"school_name": "Fake\nExcel"}, "SCHOOL_NAME_UNSAFE"),
    ({"supply_amount": True}, "SUPPLY_AMOUNT_OUT_OF_RANGE"),
    ({"supply_amount": 91}, "NON_INTEGER_VAT"),
    ({"output_formats": ("xlsx", "pdf")}, "PDF_FIDELITY"),
])
def test_bad_edit_or_fidelity_request_does_not_silently_render(overrides, reason):
    if reason is None:
        # no filesystem path is ever accepted; this is a literal cell text
        return
    with pytest.raises(WebQuoteEditUnsupported, match=reason):
        revise(quote_fixture(), **overrides)


@pytest.mark.parametrize("extra,formula,sheet_extra,reason", [
    ("xl/externalLinks/externalLink1.xml", "B4*B5", "", "UNSUPPORTED"),
    ("xl/vbaProject.bin", "B4*B5", "", "UNSUPPORTED"),
    ("xl/worksheets/sheet2.xml", "B4*B5", "", "UNSUPPORTED"),
    (None, "B4*B9", "", "FORMULA"),
    (None, "B4*B5", "<sheetProtection sheet='1'/>", "PROTECTED"),
    (None, "B4*B5", "<drawing/>", "PRINT_ASSETS"),
])
def test_reject_unsafe_package_and_unsupported_fidelity(extra, formula, sheet_extra, reason):
    with pytest.raises(WebQuoteEditUnsupported, match=reason):
        revise(quote_fixture(extra=extra, formula=formula, sheet_extra=sheet_extra))


def test_synthetic_determinism_and_different_edits_do_not_mutate_original():
    source = quote_fixture()
    a = revise(source)
    b = revise(source)
    other = revise(source, supply_amount=100_000_000)
    assert a.revised_xlsx == b.revised_xlsx
    assert a.revised_sha256 != other.revised_sha256
    assert hashlib.sha256(source).hexdigest() == a.source_sha256


def test_pdf_only_must_fail_without_approved_converter():
    with pytest.raises(WebQuoteEditUnsupported, match="PDF_FIDELITY"):
        revise(quote_fixture(), output_formats=("pdf",))
