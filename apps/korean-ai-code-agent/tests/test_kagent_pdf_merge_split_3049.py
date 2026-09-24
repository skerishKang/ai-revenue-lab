"""#3049 KAgent PDF merge/split composition tests."""

from __future__ import annotations

import unittest
from io import BytesIO
from unittest import mock

from pypdf import PdfReader, PdfWriter

from kagent import pdf_merge_split
from kagent.claw_skill_registry import CAPABILITY_PDF_CREATE, CAPABILITY_PDF_TRANSFORM
from kagent.file_intake_safety import DetectedFormat, inspect_file
from kagent.pdf_inspection import PdfInspectionResult
from kagent.pdf_merge_split import merge_pdf_documents, split_pdf_document


def _pdf(*widths: int) -> bytes:
    writer = PdfWriter()
    for width in widths:
        writer.add_blank_page(width=width, height=200)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def _widths(payload: bytes) -> tuple[float, ...]:
    return tuple(
        float(page.mediabox.width)
        for page in PdfReader(BytesIO(payload), strict=True).pages
    )


class PdfMergeSplitCompositionTests(unittest.TestCase):
    def test_merge_reuses_gate_and_preserves_order_and_provenance(self) -> None:
        result = merge_pdf_documents(
            (
                ("a.pdf", _pdf(101, 102)),
                ("b.pdf", _pdf(201)),
            )
        )
        self.assertEqual(result.receipt.status, "ok")
        self.assertEqual(result.receipt.capability_id, CAPABILITY_PDF_CREATE)
        self.assertEqual(
            result.receipt.validation_status, "output_gate_and_readback_pass"
        )
        self.assertIsNotNone(result.artifact)
        assert result.artifact is not None
        self.assertEqual(_widths(result.artifact.payload), (101, 102, 201))
        self.assertEqual(
            [item.source_document_index for item in result.receipt.page_provenance],
            [0, 0, 1],
        )

    def test_split_uses_explicit_one_based_ranges(self) -> None:
        result = split_pdf_document("source.pdf", _pdf(101, 102, 103), ((2, 3), (1, 1)))
        self.assertEqual(result.receipt.status, "ok")
        self.assertEqual(result.receipt.capability_id, CAPABILITY_PDF_TRANSFORM)
        self.assertIsNotNone(result.artifact)
        assert result.artifact is not None
        self.assertEqual(_widths(result.artifact.payload), (102, 103, 101))
        self.assertEqual(
            [item.source_page_number for item in result.receipt.page_provenance],
            [2, 3, 1],
        )

    def test_gate_runs_before_core_merge_and_denied_input_has_no_artifact(self) -> None:
        calls: list[str] = []
        real_gate = pdf_merge_split.inspect_file

        def gate(name, data):
            calls.append("gate")
            return real_gate(name, data)

        with (
            mock.patch.object(pdf_merge_split, "inspect_file", side_effect=gate),
            mock.patch.object(pdf_merge_split, "merge_pdfs") as merge,
        ):
            result = merge_pdf_documents((("bad.pdf", b"not pdf"),))
        self.assertEqual(calls, ["gate"])
        self.assertEqual(result.receipt.status, "refused")
        self.assertIsNone(result.artifact)
        merge.assert_not_called()

    def test_encrypted_and_invalid_split_inputs_fail_closed(self) -> None:
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=200)
        writer.encrypt("secret")
        encrypted = BytesIO()
        writer.write(encrypted)
        encrypted_result = split_pdf_document(
            "locked.pdf", encrypted.getvalue(), ((1, 1),)
        )
        self.assertEqual(encrypted_result.receipt.status, "refused")
        self.assertIsNone(encrypted_result.artifact)

        invalid = split_pdf_document("source.pdf", _pdf(101, 102), ((0, 1),))
        self.assertEqual(invalid.receipt.status, "refused")
        self.assertIsNone(invalid.artifact)

    def test_output_gate_failure_refuses_artifact(self) -> None:
        source = _pdf(101)
        real_gate = pdf_merge_split.inspect_file
        admitted = real_gate("source.pdf", source)
        denied = real_gate("bad.pdf", b"not pdf")
        with mock.patch.object(
            pdf_merge_split, "inspect_file", side_effect=[admitted, denied]
        ):
            result = merge_pdf_documents((("source.pdf", source),))
        self.assertEqual(result.receipt.reason_code, "pdf_output_gate_rejected")
        self.assertIsNone(result.artifact)

    def test_output_readback_failure_refuses_artifact(self) -> None:
        source = _pdf(101)
        denied_gate = inspect_file("source.pdf", b"not pdf")
        with mock.patch.object(
            pdf_merge_split,
            "inspect_pdf_document",
            return_value=PdfInspectionResult(None, denied_gate),
        ):
            result = merge_pdf_documents((("source.pdf", source),))
        self.assertEqual(result.receipt.reason_code, "pdf_output_readback_rejected")
        self.assertIsNone(result.artifact)

    def test_public_receipt_never_contains_payload(self) -> None:
        result = merge_pdf_documents((("source.pdf", _pdf(101)),))
        self.assertIsNotNone(result.artifact)
        assert result.artifact is not None
        public = result.to_public_dict()
        self.assertNotIn("payload", public)
        self.assertNotIn(str(result.artifact.payload), str(public))

    def test_gate_uses_content_pdf_authority(self) -> None:
        result = merge_pdf_documents((("renamed.bin", _pdf(101)),))
        self.assertEqual(result.receipt.status, "ok")
        self.assertEqual(
            inspect_file("renamed.bin", _pdf(101)).detected_format, DetectedFormat.PDF
        )


if __name__ == "__main__":
    unittest.main()
