"""#3036 KAgent PDF inspection composition tests."""

from __future__ import annotations

import unittest
from io import BytesIO
from unittest import mock

try:
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
except ModuleNotFoundError:  # pragma: no cover
    PdfWriter = None
    DecodedStreamObject = DictionaryObject = NameObject = None

from kagent.claw_skill_registry import CAPABILITY_PDF_INSPECT, CAPABILITY_PDF_READ
from kagent.file_intake_safety import DetectedFormat
from kagent.pdf_inspection import PDF_CAPABILITY_IDS, inspect_pdf_document


class PdfInspectionCompositionTests(unittest.TestCase):
    def _pdf_or_skip(self, text: str = "native page text") -> bytes:
        if PdfWriter is None:
            self.skipTest("pypdf is provided by the documents extra")
        writer = PdfWriter()
        page = writer.add_blank_page(width=320, height=180)
        font = DictionaryObject({
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        })
        font_ref = writer._add_object(font)
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref})
        })
        content = DecodedStreamObject()
        content.set_data(f"BT /F1 14 Tf 36 90 Td ({text}) Tj ET".encode("ascii"))
        page[NameObject("/Contents")] = writer._add_object(content)
        output = BytesIO()
        writer.write(output)
        return output.getvalue()

    def test_pdf_inspection_reuses_gate_before_core_reader(self) -> None:
        calls: list[str] = []
        import kagent.pdf_inspection as module
        real_gate = module.inspect_file
        real_core = module.inspect_pdf

        def gate(name, data):
            calls.append("gate")
            return real_gate(name, data)

        def core(**kwargs):
            calls.append("core")
            return real_core(**kwargs)

        with mock.patch.object(module, "inspect_file", gate), mock.patch.object(module, "inspect_pdf", core):
            result = inspect_pdf_document("report.pdf", self._pdf_or_skip())
        self.assertEqual(calls, ["gate", "core"])
        self.assertTrue(result.safe_to_read)
        self.assertIsNotNone(result.inspection)
        assert result.inspection is not None
        self.assertEqual(result.inspection.pages[0].page_number, 1)
        self.assertTrue(result.native_text_available)
        self.assertEqual(result.native_text_state, "native_text_present")
        self.assertEqual(
            PDF_CAPABILITY_IDS,
            (CAPABILITY_PDF_INSPECT, CAPABILITY_PDF_READ),
        )
        self.assertIs(result.gate.detected_format, DetectedFormat.PDF)

    def test_denied_pdf_never_reaches_core_reader(self) -> None:
        import kagent.pdf_inspection as module
        with mock.patch.object(module, "inspect_pdf") as reader:
            result = inspect_pdf_document("spoofed.pdf", b"\x89PNG\r\n\x1a\n")
        self.assertFalse(result.safe_to_read)
        self.assertIsNone(result.inspection)
        self.assertIsNone(result.native_text_available)
        self.assertIsNone(result.native_text_state)
        reader.assert_not_called()

    def test_textless_pdf_reports_bounded_native_text_absence(self) -> None:
        result = inspect_pdf_document("scan.pdf", self._pdf_or_skip(""))
        self.assertTrue(result.safe_to_read)
        self.assertFalse(result.native_text_available)
        self.assertEqual(
            result.native_text_state,
            "no_native_text_ocr_may_be_required",
        )
