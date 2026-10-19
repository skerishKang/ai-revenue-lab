"""#3580 XLSX compatibility and local-only routing: no provider calls."""
from __future__ import annotations

import io
import unittest
import zipfile

from kagent.xlsx_fidelity_route import (
    XlsxRoute, classify_xlsx, MAX_XLSX_BYTES,
)

WORKBOOK = b'<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheets><sheet name="Quote" sheetId="1"/></sheets></workbook>'
SIMPLE_SHEET = b'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1"><v>3</v></c></row></sheetData></worksheet>'
FORMULA_SHEET = SIMPLE_SHEET.replace(b'<v>3</v>', b'<f>SUM(A2:A10)</f><v>3</v>')
STYLED_SHEET = SIMPLE_SHEET.replace(b'<c r="A1">', b'<c r="A1" s="2">')
CONTENT = b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>'
REL = b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>'


def workbook(*, sheet=SIMPLE_SHEET, additions=None, omit=None):
    files = {
        "[Content_Types].xml": CONTENT,
        "_rels/.rels": REL,
        "xl/workbook.xml": WORKBOOK,
        "xl/worksheets/sheet1.xml": sheet,
    }
    files.update(additions or {})
    for key in (omit or ()):
        files.pop(key, None)
    memory = io.BytesIO()
    with zipfile.ZipFile(memory, "w", compression=zipfile.ZIP_DEFLATED) as arc:
        for name, data in files.items():
            arc.writestr(name, data)
    return memory.getvalue()


class XlsxFidelityRouteTests(unittest.TestCase):
    def test_simple_works_as_candidate_only_without_auto_conversion(self):
        result = classify_xlsx(workbook())
        self.assertIs(result.route, XlsxRoute.NATIVE_CANDIDATE_REQUIRES_PROOF)
        self.assertFalse(result.may_automatically_convert)
        self.assertFalse(result.output_fidelity_verified)
        self.assertIn("explicit_verified_conversion", result.execution_target)
        self.assertFalse(result.public_projection()["auto_google_conversion"])
        self.assertNotIn("PK", str(result.public_projection()))

    def test_formulas_and_number_functions_force_office_fallback(self):
        for sheet in (FORMULA_SHEET, FORMULA_SHEET.replace(b"SUM", b"NUMBERSTRING")):
            result = classify_xlsx(workbook(sheet=sheet))
            self.assertIs(result.route, XlsxRoute.OFFICE_FALLBACK)
            self.assertEqual(result.execution_target, "ephemeral_office_renderer")

    def test_complex_styles_merged_ranges_and_print_area_are_sensitive(self):
        for sheet in (
            STYLED_SHEET,
            SIMPLE_SHEET.replace(b"</worksheet>", b"<mergeCells count='1'/></worksheet>"),
            SIMPLE_SHEET.replace(b"</worksheet>", b"<pageSetup orientation='landscape'/></worksheet>"),
        ):
            self.assertIs(classify_xlsx(workbook(sheet=sheet)).route, XlsxRoute.OFFICE_FALLBACK)

    def test_vba_external_drawings_pivots_and_media_force_fallback(self):
        for name in (
            "xl/vbaProject.bin", "xl/externalLinks/externalLink1.xml",
            "xl/drawings/drawing1.xml", "xl/pivotTables/pivotTable1.xml",
            "xl/media/image1.png", "xl/styles.xml",
        ):
            self.assertIs(classify_xlsx(workbook(additions={name:b"opaque"})).route,
                          XlsxRoute.OFFICE_FALLBACK)

    def test_local_only_never_assumes_cloud_fs_and_selects_desktop(self):
        for sheet in (FORMULA_SHEET, SIMPLE_SHEET):
            result = classify_xlsx(workbook(sheet=sheet), local_only=True)
            self.assertEqual(result.execution_target, "padiem_desktop_local_runner")
            self.assertTrue(result.preserves_original)
            self.assertFalse(result.may_automatically_convert)

    def test_invalid_zip_oversize_and_wrong_type_are_rejected(self):
        for bad in (b"", b"PK\x03\x04corrupt", b"not a zip",
                    b"x"*(MAX_XLSX_BYTES+1), "file path", 5):
            self.assertIs(classify_xlsx(bad).route, XlsxRoute.REJECT)

    def test_missing_core_workbook_member_fail_closed(self):
        for missing in ("[Content_Types].xml", "_rels/.rels",
                        "xl/workbook.xml", "xl/worksheets/sheet1.xml"):
            self.assertIs(classify_xlsx(workbook(omit=(missing,))).route, XlsxRoute.REJECT)

    def test_zip_slip_and_duplicate_name_fail_closed(self):
        self.assertIs(classify_xlsx(workbook(additions={"../evil.xml": b"evil"})).route,
                      XlsxRoute.REJECT)
        memory=io.BytesIO()
        with zipfile.ZipFile(memory, "w") as arc:
            arc.writestr("[Content_Types].xml", CONTENT)
            arc.writestr("[content_types].xml", CONTENT)
            arc.writestr("_rels/.rels", REL)
            arc.writestr("xl/workbook.xml", WORKBOOK)
            arc.writestr("xl/worksheets/sheet1.xml", SIMPLE_SHEET)
        self.assertIs(classify_xlsx(memory.getvalue()).route, XlsxRoute.REJECT)

    def test_xml_malformed_or_bomb_rejected(self):
        self.assertIs(classify_xlsx(workbook(sheet=b"<worksheet><broken></worksheet>")).route,
                      XlsxRoute.REJECT)
        self.assertIs(classify_xlsx(workbook(additions={"xl/worksheets/sheet2.xml": b"x"* (5*1024*1024)})).route,
                      XlsxRoute.REJECT)

    def test_invalid_locality_refuses_and_never_mints_authority(self):
        self.assertIs(classify_xlsx(workbook(), local_only="false").route, XlsxRoute.REJECT)
        self.assertEqual(classify_xlsx(workbook()).public_projection()["raw_workbook_bytes"], False)


if __name__ == "__main__":
    unittest.main()
