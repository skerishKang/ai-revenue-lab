"""#2827 KAgent PDFium full-page rendering facade tests."""

from __future__ import annotations

import importlib.util
import unittest
from io import BytesIO
from pathlib import Path
from unittest import mock

from padiem_ai_core.image_helpers import image_to_pdf
from PIL import Image

from kagent import pdf_render
from kagent.claw_skill_registry import CAPABILITY_PDF_INSPECT
from kagent.pdf_render import (
    PDF_RENDER_SOURCE_KIND,
    PdfRenderError,
    render_pdf_page_previews,
)


def _image_pdf(*sizes: tuple[int, int]) -> bytes:
    images: list[bytes] = []
    for size in sizes:
        image = Image.new("RGB", size, (20, 40, 60))
        output = BytesIO()
        image.save(output, format="PNG")
        images.append(output.getvalue())
    return image_to_pdf(tuple(images)).data


@unittest.skipUnless(
    importlib.util.find_spec("pypdfium2") is not None,
    "pypdfium2 is provided by the documents extra",
)
class PdfRenderFacadeTests(unittest.TestCase):
    def test_full_page_rendering_reuses_pdf_inspect_capability(self) -> None:
        result = render_pdf_page_previews("report.pdf", _image_pdf((64, 48)))

        self.assertEqual(result.capability_id, CAPABILITY_PDF_INSPECT)
        self.assertEqual(result.source_kind, PDF_RENDER_SOURCE_KIND)
        self.assertEqual(result.artifact.page_count, 1)
        self.assertEqual(result.artifact.pages[0].page_number, 1)
        self.assertEqual(result.to_public_dict()["full_page_render_claimed"], True)

    def test_public_projection_excludes_rendered_bytes(self) -> None:
        result = render_pdf_page_previews("report.pdf", _image_pdf((64, 48)))
        public = result.to_public_dict()

        self.assertNotIn("data", public)
        self.assertNotIn(str(result.artifact.pages[0].data), str(public))
        self.assertNotIn(str(result.artifact.pages[0].data), repr(result))

    def test_gate_rejection_never_reaches_pdfium(self) -> None:
        with (
            mock.patch.object(pdf_render, "_render_core") as renderer,
            self.assertRaises(PdfRenderError) as error,
        ):
            render_pdf_page_previews("spoofed.pdf", b"not a pdf")

        self.assertEqual(error.exception.code, "pdf_render_input_rejected")
        renderer.assert_not_called()

    def test_raw_renderer_errors_are_stable_at_facade_boundary(self) -> None:
        for raw_error in (
            ValueError("bad value"),
            TypeError("bad type"),
            RuntimeError("pdfium"),
        ):
            with self.subTest(error_type=type(raw_error).__name__):
                with (
                    mock.patch.object(
                        pdf_render, "_render_core", side_effect=raw_error
                    ),
                    self.assertRaises(PdfRenderError) as error,
                ):
                    render_pdf_page_previews("report.pdf", _image_pdf((64, 48)))
                self.assertEqual(error.exception.code, "pdf_render_failed")

    def test_output_page_count_mismatch_fails_closed(self) -> None:
        two_page_result = pdf_render._render_core(
            name="two.pdf",
            media_type="application/pdf",
            payload=_image_pdf((32, 24), (24, 32)),
        )
        with (
            mock.patch.object(pdf_render, "_render_core", return_value=two_page_result),
            self.assertRaises(PdfRenderError) as error,
        ):
            render_pdf_page_previews("one.pdf", _image_pdf((32, 24)))
        self.assertEqual(error.exception.code, "pdf_render_output_mismatch")

    def test_render_source_has_no_external_renderer_or_ocr_authority(self) -> None:
        source = Path(pdf_render.__file__).read_text(encoding="utf-8")
        for token in ("subprocess", "fitz", "pymupdf", "ghostscript", "ocr", "http"):
            self.assertNotIn(token, source.lower())


if __name__ == "__main__":
    unittest.main()
