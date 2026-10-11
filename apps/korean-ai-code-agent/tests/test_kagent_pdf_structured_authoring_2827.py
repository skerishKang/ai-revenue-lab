"""#2827 KAgent bounded structured PDF authoring tests."""

from __future__ import annotations

import unittest
from io import BytesIO
from pathlib import Path
from unittest import mock

from kagent import pdf_structured_authoring
from kagent.claw_skill_registry import CAPABILITY_PDF_CREATE
from kagent.file_intake_safety import inspect_file
from kagent.pdf_structured_authoring import (
    PDF_STRUCTURED_AUTHORING_REASON_AUTHORING_FAILED,
    PDF_STRUCTURED_AUTHORING_REASON_IMAGE_REJECTED,
    PDF_STRUCTURED_AUTHORING_REASON_IMAGE_UNSUPPORTED,
    PDF_STRUCTURED_AUTHORING_REASON_OUTPUT_REJECTED,
    PDF_STRUCTURED_AUTHORING_REASON_REQUEST_INVALID,
    PDF_STRUCTURED_AUTHORING_SOURCE_KIND,
    PDF_STRUCTURED_AUTHORING_VALIDATION_PASS,
    PdfStructuredAuthoringError,
    create_structured_pdf,
)
from padiem_ai_core.document_normalization import DocumentNormalizationError
from padiem_ai_core.pdf_authoring import (
    PdfAuthoringDocument,
    PdfAuthoringFont,
    PdfAuthoringMetadata,
    PdfHeadingBlock,
    PdfImageBlock,
    PdfPageBreakBlock,
    PdfTableBlock,
    PdfTextBlock,
)
from PIL import Image

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
FONT_PATH = (
    REPOSITORY_ROOT
    / "packages"
    / "padiem-ai-core"
    / "tests"
    / "fixtures"
    / "pdf_authoring"
    / "PadiemNotoSansKRAuthoringTest-Regular.ttf"
)


def _image(image_format: str) -> bytes:
    output = BytesIO()
    Image.new("RGB", (120, 80), "white").save(output, format=image_format)
    return output.getvalue()


def _document(
    image_format: str = "PNG", *, valid_image: bool = True
) -> PdfAuthoringDocument:
    extension = {"PNG": "png", "JPEG": "jpg", "WEBP": "webp"}[image_format]
    image = _image(image_format) if valid_image else b"not-an-image"
    return PdfAuthoringDocument(
        metadata=PdfAuthoringMetadata(
            title="한글 구조화 문서",
            author="Padiem QA",
            subject="bounded authoring probe",
            keywords=("pdf", "korean", "bounded"),
        ),
        font=PdfAuthoringFont(data=FONT_PATH.read_bytes()),
        blocks=(
            PdfHeadingBlock("한글 제목"),
            PdfTextBlock("본문 내용입니다.\n두 번째 줄입니다."),
            PdfTableBlock(
                (
                    ("이름", "수량", "금액"),
                    ("본문", "2", "12,000"),
                )
            ),
            PdfImageBlock(f"page.{extension}", image),
            PdfPageBreakBlock(),
            PdfHeadingBlock("두 번째 페이지"),
            PdfTextBlock("페이지 내용은 인스펙션됩니다."),
        ),
    )


class PdfStructuredAuthoringTests(unittest.TestCase):
    def test_creates_inspected_korean_pdf_with_table_and_image(self) -> None:
        result = create_structured_pdf(_document())

        self.assertEqual(result.capability_id, CAPABILITY_PDF_CREATE)
        self.assertEqual(result.source_kind, PDF_STRUCTURED_AUTHORING_SOURCE_KIND)
        self.assertEqual(
            result.validation_status, PDF_STRUCTURED_AUTHORING_VALIDATION_PASS
        )
        self.assertEqual(result.artifact.page_count, 2)
        self.assertIsNotNone(result.inspection.inspection)
        self.assertTrue(result.inspection.native_text_available)
        self.assertEqual(
            [page.text for page in result.inspection.inspection.pages],
            [
                "한글 제목\n본문 내용입니다.\n두 번째 줄입니다.\n이름\n수량\n금액\n본문\n2\n12,000",
                "두 번째 페이지\n페이지 내용은 인스펙션됩니다.",
            ],
        )

    def test_png_and_jpeg_sources_pass_the_existing_image_gate(self) -> None:
        for image_format in ("PNG", "JPEG"):
            with self.subTest(image_format=image_format):
                result = create_structured_pdf(_document(image_format))
                self.assertEqual(result.artifact.page_count, 2)
                self.assertTrue(result.inspection.native_text_available)

    def test_public_projection_and_repr_exclude_pdf_and_font_bytes(self) -> None:
        result = create_structured_pdf(_document())
        public = result.to_public_dict()

        self.assertEqual(public["artifact"]["page_count"], 2)
        self.assertEqual(public["artifact"]["production_ready"], False)
        self.assertIn("output_gate", public)
        self.assertNotIn("input_gate", public)
        self.assertEqual(public["native_text_available"], True)
        self.assertNotIn("data", public["artifact"])
        self.assertNotIn(str(result.artifact.data), repr(result))
        self.assertNotIn(str(result.artifact.data), str(public))
        self.assertNotIn(str(result.artifact.font.data), repr(result))
        self.assertNotIn(str(result.artifact.font.data), str(public))

    def test_gate_denial_never_reaches_core_authoring(self) -> None:
        with (
            mock.patch.object(pdf_structured_authoring, "_author_core") as author,
            self.assertRaises(PdfStructuredAuthoringError) as error,
        ):
            create_structured_pdf(_document(valid_image=False))

        self.assertEqual(
            error.exception.code, PDF_STRUCTURED_AUTHORING_REASON_IMAGE_REJECTED
        )
        author.assert_not_called()

    def test_unsupported_image_type_never_reaches_core_authoring(self) -> None:
        with (
            mock.patch.object(pdf_structured_authoring, "_author_core") as author,
            self.assertRaises(PdfStructuredAuthoringError) as error,
        ):
            create_structured_pdf(_document("WEBP"))

        self.assertEqual(
            error.exception.code,
            PDF_STRUCTURED_AUTHORING_REASON_IMAGE_UNSUPPORTED,
        )
        author.assert_not_called()

    def test_output_gate_or_page_mismatch_returns_no_artifact(self) -> None:
        denied_gate = inspect_file("denied.pdf", b"not a pdf")
        with (
            mock.patch.object(
                pdf_structured_authoring,
                "inspect_pdf_document",
                return_value=pdf_structured_authoring.PdfInspectionResult(
                    None, denied_gate
                ),
            ),
            self.assertRaises(PdfStructuredAuthoringError) as error,
        ):
            create_structured_pdf(_document())

        self.assertEqual(
            error.exception.code, PDF_STRUCTURED_AUTHORING_REASON_OUTPUT_REJECTED
        )

        inspection = mock.Mock()
        inspection.safe_to_read = True
        inspection.inspection.page_count = 1
        inspection.inspection.native_text_available = True
        with (
            mock.patch.object(
                pdf_structured_authoring,
                "inspect_pdf_document",
                return_value=inspection,
            ),
            self.assertRaises(PdfStructuredAuthoringError) as mismatch,
        ):
            create_structured_pdf(_document())

        self.assertEqual(
            mismatch.exception.code, PDF_STRUCTURED_AUTHORING_REASON_OUTPUT_REJECTED
        )

    def test_invalid_request_and_engine_failure_map_to_stable_codes(self) -> None:
        with self.assertRaises(PdfStructuredAuthoringError) as request_error:
            create_structured_pdf(object())
        self.assertEqual(
            request_error.exception.code,
            PDF_STRUCTURED_AUTHORING_REASON_REQUEST_INVALID,
        )

        with (
            mock.patch.object(
                pdf_structured_authoring,
                "_author_core",
                side_effect=DocumentNormalizationError(
                    "pdf_authoring_engine_failed",
                    "failed",
                ),
            ),
            self.assertRaises(PdfStructuredAuthoringError) as author_error,
        ):
            create_structured_pdf(_document())
        self.assertEqual(
            author_error.exception.code,
            PDF_STRUCTURED_AUTHORING_REASON_AUTHORING_FAILED,
        )

    def test_facade_has_no_new_registry_ocr_parser_render_or_network_authority(
        self,
    ) -> None:
        source = (
            Path(pdf_structured_authoring.__file__).read_text(encoding="utf-8").lower()
        )
        for token in (
            "httpx",
            "pdfplumber",
            "pypdfium2",
            "requests",
            "run_ocr",
            "subprocess",
            "urllib",
        ):
            self.assertNotIn(token, source)
        self.assertEqual(CAPABILITY_PDF_CREATE, "pdf.create")


if __name__ == "__main__":
    unittest.main()
