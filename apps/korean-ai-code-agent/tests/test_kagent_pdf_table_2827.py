"""#2827 KAgent PDF table facade tests."""

from __future__ import annotations

import unittest
from importlib import import_module
from io import BytesIO
from pathlib import Path
from unittest import mock

import pytest

pypdf = pytest.importorskip("pypdf")
pytest.importorskip("pdfplumber")
pypdf_generic = import_module("pypdf.generic")
PdfWriter = pypdf.PdfWriter
DecodedStreamObject = pypdf_generic.DecodedStreamObject
DictionaryObject = pypdf_generic.DictionaryObject
NameObject = pypdf_generic.NameObject

from padiem_ai_core.pdf_table import PdfTableResult

from kagent import pdf_table
from kagent.claw_skill_registry import CAPABILITY_PDF_READ
from kagent.pdf_table import PdfTableError, extract_pdf_tables_from_document


def _table_pdf() -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=200)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    font_ref = writer._add_object(font)
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref})}
    )
    commands = [
        "1 w",
        "50 50 m 250 50 l S",
        "50 100 m 250 100 l S",
        "50 150 m 250 150 l S",
        "50 50 m 50 150 l S",
        "150 50 m 150 150 l S",
        "250 50 m 250 150 l S",
        "BT /F1 12 Tf 60 115 Td (A1) Tj 90 0 Td (A2) Tj ET",
        "BT /F1 12 Tf 60 65 Td (B1) Tj 90 0 Td (B2) Tj ET",
    ]
    content = DecodedStreamObject()
    content.set_data("\n".join(commands).encode("ascii"))
    page[NameObject("/Contents")] = writer._add_object(content)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


class PdfTableFacadeTests(unittest.TestCase):
    def test_table_extraction_reuses_pdf_read_capability(self) -> None:
        result = extract_pdf_tables_from_document("table.pdf", _table_pdf())

        self.assertEqual(result.capability_id, CAPABILITY_PDF_READ)
        self.assertEqual(result.source_kind, "ruled_machine_generated")
        self.assertEqual(result.artifact.status, "tables_found")
        self.assertEqual(result.artifact.tables[0].rows, (("A1", "A2"), ("B1", "B2")))

    def test_public_projection_excludes_pdf_bytes(self) -> None:
        result = extract_pdf_tables_from_document("table.pdf", _table_pdf())
        public = result.to_public_dict()

        self.assertNotIn("data", public)
        self.assertNotIn("payload", public)
        self.assertNotIn(str(_table_pdf()), str(public))

    def test_gate_rejection_never_reaches_table_core(self) -> None:
        with (
            mock.patch.object(pdf_table, "_extract_core") as extractor,
            self.assertRaises(PdfTableError) as error,
        ):
            extract_pdf_tables_from_document("spoofed.pdf", b"not a pdf")

        self.assertEqual(error.exception.code, "pdf_table_input_rejected")
        extractor.assert_not_called()

    def test_core_errors_are_stable_at_facade_boundary(self) -> None:
        for raw_error in (ValueError("bad"), TypeError("bad"), RuntimeError("bad")):
            with self.subTest(error_type=type(raw_error).__name__):
                with (
                    mock.patch.object(
                        pdf_table, "_extract_core", side_effect=raw_error
                    ),
                    self.assertRaises(PdfTableError) as error,
                ):
                    extract_pdf_tables_from_document("table.pdf", _table_pdf())
                self.assertEqual(error.exception.code, "pdf_table_extraction_failed")

    def test_page_count_mismatch_fails_closed(self) -> None:
        mismatched = PdfTableResult(
            page_count=2,
            tables=(),
            unsupported_page_numbers=(1, 2),
        )
        with (
            mock.patch.object(pdf_table, "_extract_core", return_value=mismatched),
            self.assertRaises(PdfTableError) as error,
        ):
            extract_pdf_tables_from_document("table.pdf", _table_pdf())
        self.assertEqual(error.exception.code, "pdf_table_output_mismatch")

    def test_facade_source_has_no_ocr_or_external_authority(self) -> None:
        source = Path(pdf_table.__file__).read_text(encoding="utf-8")
        for token in ("ocr", "fitz", "pymupdf", "subprocess", "http", "requests"):
            self.assertNotIn(token, source.lower())


if __name__ == "__main__":
    unittest.main()
