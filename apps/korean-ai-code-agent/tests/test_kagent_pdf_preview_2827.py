"""#2827 KAgent embedded-image PDF preview facade tests."""

from __future__ import annotations

import unittest
from io import BytesIO
from pathlib import Path
from unittest import mock

from padiem_ai_core.document_normalization import DocumentNormalizationError
from padiem_ai_core.image_helpers import image_to_pdf
from PIL import Image
from pypdf import PdfWriter

from kagent import pdf_preview
from kagent.claw_skill_registry import CAPABILITY_PDF_TRANSFORM
from kagent.pdf_preview import (
    PDF_PREVIEW_SOURCE_KIND,
    PdfPreviewError,
    preview_pdf_pages,
)


def _image_bytes(
    image_format: str = "PNG",
    *,
    size: tuple[int, int] = (64, 40),
    color: tuple[int, int, int] = (30, 60, 90),
) -> bytes:
    image = Image.new("RGB", size, color)
    output = BytesIO()
    image.save(output, format=image_format)
    return output.getvalue()


def _image_backed_pdf() -> bytes:
    return image_to_pdf((_image_bytes(), _image_bytes("JPEG", size=(40, 64)))).data


def _blank_pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=100)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


class PdfPreviewFacadeTests(unittest.TestCase):
    def test_embedded_image_previews_reuse_transform_capability(self) -> None:
        result = preview_pdf_pages("report.pdf", _image_backed_pdf())

        self.assertEqual(result.capability_id, CAPABILITY_PDF_TRANSFORM)
        self.assertEqual(result.source_kind, PDF_PREVIEW_SOURCE_KIND)
        self.assertEqual(result.artifact.page_count, 2)
        self.assertEqual(result.artifact.embedded_image_count, 2)
        self.assertEqual(result.to_public_dict()["full_page_render_claimed"], False)
        self.assertEqual(result.to_public_dict()["status"], "embedded_image_previews")

    def test_public_projection_excludes_pdf_and_thumbnail_bytes(self) -> None:
        result = preview_pdf_pages("report.pdf", _image_backed_pdf())
        public = result.to_public_dict()

        self.assertNotIn("data", public)
        self.assertNotIn(str(result.artifact.pages[0].images[0].data), str(public))
        self.assertNotIn(str(result.artifact.pages[0].images[0].data), repr(result))

    def test_blank_pdf_returns_explicit_no_embedded_image_state(self) -> None:
        result = preview_pdf_pages("blank.pdf", _blank_pdf())
        public = result.to_public_dict()

        self.assertEqual(public["status"], "no_embedded_image_preview")
        self.assertEqual(public["embedded_image_count"], 0)
        self.assertEqual(public["output_byte_size"], 0)

    def test_gate_denial_never_reaches_core_renderer(self) -> None:
        with (
            mock.patch.object(pdf_preview, "_render_core") as renderer,
            self.assertRaises(PdfPreviewError) as error,
        ):
            preview_pdf_pages("spoofed.pdf", b"not a pdf")

        self.assertEqual(error.exception.code, "pdf_preview_input_gate_rejected")
        renderer.assert_not_called()

    def test_core_failure_is_mapped_to_stable_facade_error(self) -> None:
        with (
            mock.patch.object(
                pdf_preview,
                "_render_core",
                side_effect=DocumentNormalizationError(
                    "pdf_invalid", "PDF is invalid."
                ),
            ),
            self.assertRaises(PdfPreviewError) as error,
        ):
            preview_pdf_pages("report.pdf", _blank_pdf())

        self.assertEqual(error.exception.code, "pdf_preview_render_failed")

    def test_zero_page_core_error_is_stable_at_facade_boundary(self) -> None:
        with (
            mock.patch.object(
                pdf_preview,
                "_render_core",
                side_effect=DocumentNormalizationError(
                    "pdf_preview_no_pages", "PDF preview has no pages."
                ),
            ),
            self.assertRaises(PdfPreviewError) as error,
        ):
            preview_pdf_pages("empty.pdf", _blank_pdf())

        self.assertEqual(error.exception.code, "pdf_preview_render_failed")

    def test_raw_core_errors_cannot_escape_facade(self) -> None:
        for raw_error in (
            ValueError("bad value"),
            TypeError("bad type"),
            RuntimeError("pypdf"),
        ):
            with self.subTest(error_type=type(raw_error).__name__):
                with (
                    mock.patch.object(
                        pdf_preview, "_render_core", side_effect=raw_error
                    ),
                    self.assertRaises(PdfPreviewError) as error,
                ):
                    preview_pdf_pages("report.pdf", _blank_pdf())
                self.assertEqual(error.exception.code, "pdf_preview_render_failed")

    def test_preview_source_has_no_external_renderer_or_network_authority(self) -> None:
        source = Path(pdf_preview.__file__).read_text(encoding="utf-8")
        for token in (
            "fitz",
            "pymupdf",
            "ghostscript",
            "subprocess",
            "Popen",
            "urllib",
        ):
            self.assertNotIn(token, source)


if __name__ == "__main__":
    unittest.main()
