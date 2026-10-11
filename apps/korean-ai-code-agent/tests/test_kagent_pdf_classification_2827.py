"""#2827 deterministic PDF scanned/native classification tests."""

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

from kagent import pdf_classification, pdf_inspection
from kagent.claw_skill_registry import CAPABILITY_PDF_INSPECT
from kagent.file_intake_safety import inspect_file
from kagent.pdf_classification import (
    PDF_CLASSIFICATION_NATIVE_TEXT,
    PDF_CLASSIFICATION_NO_NATIVE_TEXT,
    classify_pdf_document,
)


class PdfClassificationTests(unittest.TestCase):
    def _pdf_or_skip(self, text: str = "") -> bytes:
        if PdfWriter is None:
            self.skipTest("pypdf is provided by the documents extra")
        writer = PdfWriter()
        page = writer.add_blank_page(width=320, height=180)
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        font_ref = writer._add_object(font)
        page[NameObject("/Resources")] = DictionaryObject({NameObject("/F1"): font_ref})
        content = DecodedStreamObject()
        content.set_data(f"BT /F1 14 Tf 36 90 Td ({text}) Tj ET".encode("ascii"))
        page[NameObject("/Contents")] = writer._add_object(content)
        output = BytesIO()
        writer.write(output)
        return output.getvalue()

    def test_native_text_classification_reuses_existing_provenance(self) -> None:
        result = classify_pdf_document("native.pdf", self._pdf_or_skip("native text"))
        self.assertTrue(result.safe_to_classify)
        self.assertEqual(result.classification, PDF_CLASSIFICATION_NATIVE_TEXT)
        self.assertFalse(result.ocr_candidate)
        self.assertEqual(
            result.to_public_dict()["capability_id"], CAPABILITY_PDF_INSPECT
        )
        self.assertEqual(result.to_public_dict()["page_count"], 1)

    def test_textless_pdf_is_an_explicit_ocr_candidate(self) -> None:
        result = classify_pdf_document("scan.pdf", self._pdf_or_skip(""))
        self.assertTrue(result.safe_to_classify)
        self.assertEqual(result.classification, PDF_CLASSIFICATION_NO_NATIVE_TEXT)
        self.assertTrue(result.ocr_candidate)
        self.assertEqual(
            result.to_public_dict()["native_text_state"],
            "no_native_text_ocr_may_be_required",
        )

    def test_gate_denial_never_classifies_or_reaches_core_reader(self) -> None:
        with mock.patch.object(pdf_inspection, "inspect_pdf") as reader:
            result = classify_pdf_document("spoofed.pdf", b"\x89PNG\r\n\x1a\n")
        self.assertFalse(result.safe_to_classify)
        self.assertIsNone(result.classification)
        self.assertIsNone(result.ocr_candidate)
        reader.assert_not_called()

    def test_classification_does_not_invoke_ocr(self) -> None:
        source = pdf_classification.__file__ or ""
        with open(source, encoding="utf-8") as handle:
            text = handle.read()
        self.assertNotIn("run_ocr", text)
        self.assertNotIn("ocr_engine", text)

    def test_public_projection_excludes_pdf_bytes(self) -> None:
        payload = self._pdf_or_skip("native text")
        result = classify_pdf_document("native.pdf", payload)
        public = str(result.to_public_dict())
        self.assertNotIn(str(payload), public)
        self.assertNotIn("payload", result.to_public_dict())
        self.assertEqual(result.inspection_result.gate.reason_code, "ok")
        self.assertEqual(
            inspect_file("native.pdf", payload).detected_format.value, "pdf"
        )


if __name__ == "__main__":
    unittest.main()
