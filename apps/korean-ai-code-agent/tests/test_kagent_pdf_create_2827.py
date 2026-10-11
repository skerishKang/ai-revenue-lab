"""#2827 bounded image-backed PDF creation tests."""

from __future__ import annotations

import unittest
from io import BytesIO
from pathlib import Path
from unittest import mock

from PIL import Image
from pypdf import PdfReader

from kagent import image_skill, pdf_create
from kagent.claw_skill_registry import CAPABILITY_PDF_CREATE
from kagent.file_intake_safety import inspect_file
from kagent.pdf_create import (
    PDF_CREATE_REASON_OUTPUT_REJECTED,
    PDF_CREATE_REASON_PAGES_INVALID,
    PDF_CREATE_SOURCE_IMAGE_PAGES,
    PDF_CREATE_VALIDATION_PASS,
    PdfCreateError,
    create_pdf_from_image_pages,
)
from kagent.pdf_inspection import PdfInspectionResult


def _image_bytes(
    image_format: str,
    *,
    size: tuple[int, int] = (24, 16),
    color: tuple[int, int, int] = (20, 40, 60),
) -> bytes:
    image = Image.new("RGB", size, color)
    output = BytesIO()
    image.save(output, format=image_format)
    return output.getvalue()


class PdfCreateTests(unittest.TestCase):
    def test_ordered_image_pages_create_verified_pdf(self) -> None:
        result = create_pdf_from_image_pages(
            (
                ("first.png", _image_bytes("PNG", size=(30, 15))),
                ("second.jpg", _image_bytes("JPEG", size=(15, 30))),
            )
        )

        self.assertEqual(result.capability_id, CAPABILITY_PDF_CREATE)
        self.assertEqual(result.source_kind, PDF_CREATE_SOURCE_IMAGE_PAGES)
        self.assertEqual(result.validation_status, PDF_CREATE_VALIDATION_PASS)
        self.assertEqual(result.artifact.page_count, 2)
        self.assertEqual(
            [page.source_image_index for page in result.artifact.pages], [0, 1]
        )
        self.assertTrue(result.artifact.data.startswith(b"%PDF-"))
        self.assertEqual(len(PdfReader(BytesIO(result.artifact.data)).pages), 2)
        self.assertEqual(result.native_text_state, "no_native_text_ocr_may_be_required")

    def test_public_projection_and_repr_exclude_artifact_bytes(self) -> None:
        result = create_pdf_from_image_pages((("page.png", _image_bytes("PNG")),))
        public = result.to_public_dict()

        self.assertEqual(public["output_page_count"], 1)
        self.assertEqual(public["output_byte_size"], result.artifact.size_bytes)
        self.assertNotIn("payload", public)
        self.assertNotIn("data", public)
        self.assertNotIn(str(result.artifact.data), repr(result))
        self.assertNotIn(str(result.artifact.data), str(public))

    def test_gate_denial_never_reaches_core_emitter(self) -> None:
        with (
            mock.patch.object(image_skill, "_core_image_to_pdf") as emitter,
            self.assertRaises(PdfCreateError) as error,
        ):
            create_pdf_from_image_pages((("spoofed.png", b"not-an-image"),))

        self.assertEqual(error.exception.code, "image_intake_refused")
        emitter.assert_not_called()

    def test_invalid_request_shapes_fail_closed(self) -> None:
        for pages in ((), [], (("missing-bytes.png",),)):
            with self.subTest(pages=pages):
                with self.assertRaises(PdfCreateError) as error:
                    create_pdf_from_image_pages(pages)
                self.assertIn(
                    error.exception.code,
                    {
                        PDF_CREATE_REASON_PAGES_INVALID,
                        "image_bytes_invalid",
                    },
                )

    def test_output_gate_or_readback_failure_returns_no_artifact(self) -> None:
        denied_gate = inspect_file("denied.pdf", b"not a pdf")
        with (
            mock.patch.object(
                pdf_create,
                "inspect_pdf_document",
                return_value=PdfInspectionResult(None, denied_gate),
            ),
            self.assertRaises(PdfCreateError) as error,
        ):
            create_pdf_from_image_pages((("page.png", _image_bytes("PNG")),))

        self.assertEqual(error.exception.code, PDF_CREATE_REASON_OUTPUT_REJECTED)

    def test_page_count_mismatch_fails_closed(self) -> None:
        one_page = create_pdf_from_image_pages((("one.png", _image_bytes("PNG")),))
        one_page_readback = pdf_create.inspect_pdf_document(
            "one.pdf", one_page.artifact.data
        )
        with (
            mock.patch.object(
                pdf_create,
                "inspect_pdf_document",
                return_value=one_page_readback,
            ),
            self.assertRaises(PdfCreateError) as error,
        ):
            create_pdf_from_image_pages(
                (
                    ("one.png", _image_bytes("PNG")),
                    ("two.png", _image_bytes("PNG", color=(60, 40, 20))),
                )
            )

        self.assertEqual(error.exception.code, PDF_CREATE_REASON_OUTPUT_REJECTED)

    def test_create_source_has_no_ocr_provider_or_network_authority(self) -> None:
        source = Path(pdf_create.__file__).read_text(encoding="utf-8")
        for token in ("run_ocr", "ocr_engine", "httpx", "requests", "subprocess"):
            self.assertNotIn(token, source)


if __name__ == "__main__":
    unittest.main()
