"""#4434: the boundary between the ordinary Python XLSX path and the Office path.

Real workbook bytes, the real editor and the real independent verifier. Each case
is the routing outcome the PC lane reports for the web task.
"""

from __future__ import annotations

from hashlib import sha256
from io import BytesIO
import unittest
import zipfile

from openpyxl import Workbook, load_workbook

from padiem_ai_core.document_normalization import (
    extract_binary_document, read_xlsx_table,
)

from kagent.local_xlsx_python_copy_editor import (
    IndependentZipXlsxRevisionVerifier, OfficeFidelityRequired, PythonXlsxValueCopyEditor,
)
from kagent.contracts import ContractError
from kagent.local_xlsx_revision_pdf import ReviewedCellRevision
from kagent.xlsx_fidelity_route import XlsxRoute, classify_xlsx

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
OFFICE_ONLY_PARTS = (
    "xl/vbaProject.bin",
    "xl/externalLinks/externalLink1.xml",
    "xl/pivotCache/pivotCacheDefinition1.xml",
    "xl/charts/chart1.xml",
    "xl/comments1.xml",
    "customxml/item1.xml",
)

EDITOR = PythonXlsxValueCopyEditor()
VERIFIER = IndependentZipXlsxRevisionVerifier()


def build(*, sheets: int = 1, formula: bool = False) -> bytes:
    book = Workbook()
    first = book.active
    first.title = "Quote"
    first["A1"] = "기존 항목"
    first["B2"] = 88_000_000
    first["C2"] = "text kept"
    first["A5"] = "merged note"
    first.merge_cells("A5:C5")
    if formula:
        first["B3"] = "=B2*0.1"
    for index in range(2, sheets + 1):
        sheet = book.create_sheet(f"Sheet{index}")
        sheet["A1"] = f"시트 {index} 값"
        sheet["B2"] = index * 1000
    buffer = BytesIO()
    book.save(buffer)
    book.close()
    return buffer.getvalue()


def with_part(data: bytes, name: str, payload: bytes = b"\x00\x01binary") -> bytes:
    source = zipfile.ZipFile(BytesIO(data), mode="r")
    output = BytesIO()
    with zipfile.ZipFile(output, mode="w") as archive:
        for info in source.infolist():
            archive.writestr(info, source.read(info.filename))
        archive.writestr(name, payload)
    source.close()
    return output.getvalue()


def edit(sheet: str, cell: str, previous, replacement) -> ReviewedCellRevision:
    return ReviewedCellRevision(
        sheet_name=sheet, cell=cell, previous_value=previous,
        replacement_value=replacement,
    )


def changed_parts(source: bytes, revised: bytes) -> list[str]:
    before = zipfile.ZipFile(BytesIO(source))
    after = zipfile.ZipFile(BytesIO(revised))
    return [name for name in before.namelist() if before.read(name) != after.read(name)]


class XlsxCapabilityScopeTests(unittest.TestCase):
    def test_value_edit_in_a_later_sheet_leaves_the_other_sheets_alone(self) -> None:
        source = build(sheets=3)
        edits = (edit("Sheet2", "B2", 2000, 777_000),)
        revised = EDITOR.revise_xlsx_copy(source, edits)

        self.assertIs(VERIFIER.verify_only_reviewed_edits(source, revised, edits), True)
        self.assertEqual(changed_parts(source, revised), ["xl/worksheets/sheet2.xml"])
        book = load_workbook(BytesIO(revised))
        self.assertEqual(book["Sheet2"]["B2"].value, 777_000)
        self.assertEqual(book["Sheet3"]["B2"].value, 3000)
        self.assertEqual(book["Quote"]["B2"].value, 88_000_000)
        self.assertEqual(book["Sheet2"]["A1"].value, "시트 2 값")

    def test_korean_text_and_multi_cell_revisions_round_trip(self) -> None:
        source = build(sheets=3)
        edits = (
            edit("Quote", "C2", "text kept", "  최종 견적  "),
            edit("Quote", "B2", 88_000_000, -3_500),
            edit("Sheet2", "A1", "시트 2 값", "rename confirmed"),
        )
        revised = EDITOR.revise_xlsx_copy(source, edits)
        self.assertIs(VERIFIER.verify_only_reviewed_edits(source, revised, edits), True)

        sheet = load_workbook(BytesIO(revised))["Quote"]
        self.assertEqual(sheet["C2"].value, "  최종 견적  ")
        self.assertEqual(sheet["B2"].value, -3_500)
        self.assertEqual(load_workbook(BytesIO(revised))["Sheet2"]["A1"].value,
                         "rename confirmed")

        flat = extract_binary_document(name="book.xlsx", media_type=XLSX_MIME, payload=revised)
        self.assertIn("[Quote!B2] -3500", flat.text)
        # Leading and trailing spaces survive because the replacement is
        # written with xml:space="preserve".
        self.assertIn("[Quote!C2]   최종 견적  ", flat.text)
        self.assertEqual(read_xlsx_table(
            name="book.xlsx", media_type=XLSX_MIME, payload=revised,
        ).sheet_title, "Quote")

    def test_merged_cells_and_styles_survive_the_python_path(self) -> None:
        source = build()
        revised = EDITOR.revise_xlsx_copy(source, (edit("Quote", "B2", 88_000_000, 1),))

        self.assertEqual(changed_parts(source, revised), ["xl/worksheets/sheet1.xml"])
        before = zipfile.ZipFile(BytesIO(source))
        after = zipfile.ZipFile(BytesIO(revised))
        self.assertEqual(before.read("xl/styles.xml"), after.read("xl/styles.xml"))
        sheet = load_workbook(BytesIO(revised))["Quote"]
        self.assertEqual([str(r) for r in sheet.merged_cells.ranges], ["A5:C5"])
        self.assertEqual(sheet["A5"].value, "merged note")
        self.assertEqual(sheet["A1"].value, "기존 항목")

    def test_many_rows_are_edited_without_touching_the_rest(self) -> None:
        book = Workbook()
        sheet = book.active
        sheet.title = "Rows"
        for row in range(1, 201):
            sheet.cell(row=row, column=1, value=f"행 {row}")
            sheet.cell(row=row, column=2, value=row)
        buffer = BytesIO()
        book.save(buffer)
        book.close()
        source = buffer.getvalue()

        edits = (edit("Rows", "B150", 150, 1_500_000),)
        revised = EDITOR.revise_xlsx_copy(source, edits)
        self.assertIs(VERIFIER.verify_only_reviewed_edits(source, revised, edits), True)
        checked = load_workbook(BytesIO(revised))["Rows"]
        self.assertEqual(checked["B150"].value, 1_500_000)
        self.assertEqual(checked["A149"].value, "행 149")
        self.assertEqual(checked["B200"].value, 200)

    def test_workbooks_the_office_path_must_handle_are_routed_away(self) -> None:
        for extra_part in OFFICE_ONLY_PARTS:
            with self.subTest(extra_part=extra_part):
                source = with_part(build(), extra_part)
                self.assertIs(
                    classify_xlsx(source, local_only=True).route, XlsxRoute.OFFICE_FALLBACK,
                )
                with self.assertRaises(OfficeFidelityRequired):
                    EDITOR.revise_xlsx_copy(source, (edit("Quote", "B2", 88_000_000, 1),))

    def test_formula_and_calculation_chain_never_get_a_stale_result(self) -> None:
        formula = build(formula=True)
        with self.assertRaises(OfficeFidelityRequired):
            EDITOR.revise_xlsx_copy(formula, (edit("Quote", "B2", 88_000_000, 1),))
        chained = with_part(build(), "xl/calcChain.xml", b"<calcChain/>")
        with self.assertRaises(OfficeFidelityRequired):
            EDITOR.revise_xlsx_copy(chained, (edit("Quote", "B2", 88_000_000, 1),))
        with self.assertRaises(OfficeFidelityRequired):
            EDITOR.revise_xlsx_copy(formula, (edit("Quote", "B3", 8_800_000, 1),))

    def test_untrusted_or_unsupported_input_is_refused_before_routing(self) -> None:
        self.assertIs(classify_xlsx(b"PK\x03\x04", local_only=True).route, XlsxRoute.REJECT)
        with self.assertRaises(Exception):
            EDITOR.revise_xlsx_copy(b"PK\x03\x04garbage", (edit("Quote", "B2", 1, 2),))
        with self.assertRaises(Exception):
            EDITOR.revise_xlsx_copy(build(), (edit("Quote", "K7", 0, 1),))
        with self.assertRaises(Exception):
            EDITOR.revise_xlsx_copy(build(), (edit("Absent", "B2", 88_000_000, 1),))

    def test_literal_only_revision_contract_refuses_float_and_code(self) -> None:
        with self.assertRaises(ContractError):
            edit("Quote", "D3", 12.5, 14.75)
        with self.assertRaises(ContractError):
            edit("Quote", "C2", "text kept", "=HYPERLINK(\"https://x\")")
        with self.assertRaises(ContractError):
            edit("Quote", "B2", 88_000_000, True)

    def test_original_bytes_are_untouched_by_a_revision(self) -> None:
        source = build()
        digest = sha256(source).hexdigest()
        EDITOR.revise_xlsx_copy(source, (edit("Quote", "B2", 88_000_000, 42),))
        self.assertEqual(sha256(source).hexdigest(), digest)


if __name__ == "__main__":
    unittest.main()
