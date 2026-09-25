"""#2827 PDF native/OCR fallback composition tests."""

from __future__ import annotations

import ast
import importlib.util
import io
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from kagent import pdf_ocr_fallback
from kagent.claw_skill_registry import CAPABILITY_PDF_OCR
from kagent.image_ocr_contract import (
    OCR_ISOLATION_FAILURE_REASON_CODE,
    OCR_RUNTIME_MISSING_REASON_CODE,
    OCR_TIMEOUT_REASON_CODE,
    OcrProvenance,
)
from kagent.image_ocr_isolation import IsolatedOcrResult, OcrOutcome
from kagent.image_skill import ImageSkillError
from kagent.pdf_inspection import PdfInspectionResult
from kagent.pdf_ocr_fallback import (
    PDF_OCR_RESULT_NATIVE,
    PDF_OCR_RESULT_OCR,
    PDF_OCR_SOURCE_NATIVE,
    PDF_OCR_SOURCE_OCR,
    PdfOcrError,
    compose_pdf_ocr_fallback,
)
from padiem_ai_core.document_normalization import PdfInspection, PdfPageInspection
from padiem_ai_core.pdf_render import PdfRenderedPage, PdfRenderResult

_PNG = b"\x89PNG\r\n\x1a\nbounded-render-fixture"
_PROVENANCE = OcrProvenance(
    runtime="paddleocr",
    runtime_revision="rev",
    detector_revision="detector-rev",
    recognizer_revision="recognizer-rev",
    canonical_png_sha256="a" * 64,
    mode="isolated",
)


def _inspection(page_texts: tuple[str, ...]) -> PdfInspectionResult:
    pages = tuple(
        PdfPageInspection(index, index + 1, len(page_texts), text)
        for index, text in enumerate(page_texts)
    )
    inspection = PdfInspection(
        name="mixed.pdf",
        media_type="application/pdf",
        byte_size=100,
        page_count=len(pages),
        pages=pages,
        native_text_available=any(page_texts),
        native_text_state="present" if any(page_texts) else "absent",
    )
    gate = SimpleNamespace(safe_dict=lambda: {"safe_to_parse": True})
    return PdfInspectionResult(inspection, gate)


def _rendered(page_count: int) -> SimpleNamespace:
    pages = tuple(
        PdfRenderedPage(index + 1, 10, 10, 0, _PNG + bytes([index]))
        for index in range(page_count)
    )
    return SimpleNamespace(
        artifact=PdfRenderResult(
            pages=pages,
            page_count=page_count,
            output_byte_size=sum(len(page.data) for page in pages),
        )
    )


def _ocr_completed(text: str = "ocr text") -> SimpleNamespace:
    isolated = IsolatedOcrResult(
        outcome=OcrOutcome.COMPLETED,
        reason_code="ok",
        provenance=_PROVENANCE,
        results=(
            SimpleNamespace(
                text=text,
                score=0.99,
                boxes=(),
                safe_dict=lambda: {"text": text, "score": 0.99, "boxes": []},
            ),
        ),
    )
    return SimpleNamespace(
        ocr=isolated, safe_dict=lambda: {"ocr": isolated.safe_dict()}
    )


def _ocr_failed(outcome: OcrOutcome, reason: str) -> SimpleNamespace:
    isolated = IsolatedOcrResult(outcome=outcome, reason_code=reason)
    return SimpleNamespace(
        ocr=isolated, safe_dict=lambda: {"ocr": isolated.safe_dict()}
    )


class PdfOcrFallbackTests(unittest.TestCase):
    def test_native_only_never_renders_or_calls_ocr(self) -> None:
        with (
            mock.patch.object(pdf_ocr_fallback, "render_pdf_page_previews") as renderer,
            mock.patch.object(pdf_ocr_fallback, "image_ocr") as ocr,
            mock.patch.object(
                pdf_ocr_fallback,
                "inspect_pdf_document",
                return_value=_inspection(("첫 페이지", "둘째 페이지")),
            ),
        ):
            result = compose_pdf_ocr_fallback(
                "native.pdf", b"%PDF-original", detector_dir="d", recognizer_dir="r"
            )

        self.assertEqual(result.capability_id, CAPABILITY_PDF_OCR)
        self.assertEqual(result.source_kind, "native_only")
        self.assertEqual(result.ocr_page_count, 0)
        self.assertEqual(
            [page.text_source for page in result.pages], [PDF_OCR_RESULT_NATIVE] * 2
        )
        renderer.assert_not_called()
        ocr.assert_not_called()

    def test_scanned_only_ocr_uses_only_pdfium_png_bytes(self) -> None:
        pdf_bytes = b"%PDF-original-must-not-reach-ocr"
        captured: dict[str, object] = {}

        def fake_ocr(payload: bytes, **kwargs: object) -> SimpleNamespace:
            captured["payload"] = payload
            captured["kwargs"] = kwargs
            return _ocr_completed("스캔 문서")

        with (
            mock.patch.object(
                pdf_ocr_fallback, "render_pdf_page_previews", return_value=_rendered(1)
            ),
            mock.patch.object(pdf_ocr_fallback, "image_ocr", side_effect=fake_ocr),
            mock.patch.object(
                pdf_ocr_fallback,
                "inspect_pdf_document",
                return_value=_inspection(("",)),
            ),
        ):
            result = compose_pdf_ocr_fallback(
                "scan.pdf",
                pdf_bytes,
                detector_dir="detector",
                recognizer_dir="recognizer",
            )

        self.assertEqual(result.source_kind, "ocr_fallback")
        self.assertEqual(result.ocr_page_count, 1)
        self.assertEqual(result.pages[0].source_kind, PDF_OCR_SOURCE_OCR)
        self.assertEqual(result.pages[0].text_source, PDF_OCR_RESULT_OCR)
        self.assertNotEqual(captured["payload"], pdf_bytes)
        self.assertTrue(bytes(captured["payload"]).startswith(b"\x89PNG"))
        self.assertEqual(captured["kwargs"]["filename"], "pdf-page-1.png")

    def test_mixed_pdf_preserves_native_pages_and_deterministic_order(self) -> None:
        calls: list[tuple[str, bytes]] = []

        def fake_ocr(payload: bytes, **kwargs: object) -> SimpleNamespace:
            calls.append((str(kwargs["filename"]), payload))
            return _ocr_completed("둘째 스캔 페이지")

        with (
            mock.patch.object(
                pdf_ocr_fallback, "render_pdf_page_previews", return_value=_rendered(3)
            ),
            mock.patch.object(pdf_ocr_fallback, "image_ocr", side_effect=fake_ocr),
            mock.patch.object(
                pdf_ocr_fallback,
                "inspect_pdf_document",
                return_value=_inspection(("첫 네이티브", "", "셋째 네이티브")),
            ),
        ):
            result = compose_pdf_ocr_fallback(
                "mixed.pdf", b"%PDF-mixed", detector_dir="d", recognizer_dir="r"
            )

        self.assertEqual(result.source_kind, "mixed_native_ocr")
        self.assertEqual([page.page_number for page in result.pages], [1, 2, 3])
        self.assertEqual(
            [page.source_kind for page in result.pages],
            [PDF_OCR_SOURCE_NATIVE, PDF_OCR_SOURCE_OCR, PDF_OCR_SOURCE_NATIVE],
        )
        self.assertEqual([name for name, _ in calls], ["pdf-page-2.png"])
        self.assertEqual(result.pages[0].text, "첫 네이티브")
        self.assertEqual(result.pages[2].text, "셋째 네이티브")

    def test_input_render_and_page_mismatch_fail_closed(self) -> None:
        cases = (
            ("pdf_ocr_input_rejected", "inspect", ValueError("malformed"), 1),
            ("pdf_ocr_input_rejected", "inspect", RuntimeError("encrypted"), 1),
            ("pdf_ocr_render_failed", "render", RuntimeError("pdfium"), 1),
            ("pdf_ocr_page_mismatch", "render", None, 2),
        )
        for expected, target, raw_error, page_count in cases:
            with self.subTest(expected=expected, target=target):
                if target == "inspect":
                    patches = (
                        mock.patch.object(
                            pdf_ocr_fallback,
                            "inspect_pdf_document",
                            side_effect=raw_error,
                        ),
                    )
                else:
                    render_value = (
                        SimpleNamespace(artifact=SimpleNamespace(page_count=99))
                        if expected == "pdf_ocr_page_mismatch"
                        else None
                    )
                    patches = (
                        mock.patch.object(
                            pdf_ocr_fallback,
                            "inspect_pdf_document",
                            return_value=_inspection(("",) * page_count),
                        ),
                        mock.patch.object(
                            pdf_ocr_fallback,
                            "render_pdf_page_previews",
                            side_effect=raw_error if raw_error else None,
                            return_value=render_value,
                        ),
                    )
                with ExitStack() as stack:
                    for patch in patches:
                        stack.enter_context(patch)
                    with self.assertRaises(PdfOcrError) as error:
                        compose_pdf_ocr_fallback(
                            "bad.pdf", b"%PDF-bad", detector_dir="d", recognizer_dir="r"
                        )
                self.assertEqual(error.exception.code, expected)

    def test_ocr_runtime_missing_timeout_and_failure_are_distinct_bounded_refusals(
        self,
    ) -> None:
        cases = (
            (
                OcrOutcome.FAILED,
                OCR_RUNTIME_MISSING_REASON_CODE,
                "pdf_ocr_runtime_missing",
            ),
            (OcrOutcome.TIMED_OUT, OCR_TIMEOUT_REASON_CODE, "pdf_ocr_timeout"),
            (OcrOutcome.FAILED, OCR_ISOLATION_FAILURE_REASON_CODE, "pdf_ocr_failed"),
        )
        for outcome, reason, expected in cases:
            with (
                self.subTest(reason=reason),
                mock.patch.object(
                    pdf_ocr_fallback,
                    "render_pdf_page_previews",
                    return_value=_rendered(1),
                ),
                mock.patch.object(
                    pdf_ocr_fallback,
                    "image_ocr",
                    return_value=_ocr_failed(outcome, reason),
                ),
                mock.patch.object(
                    pdf_ocr_fallback,
                    "inspect_pdf_document",
                    return_value=_inspection(("",)),
                ),
                self.assertRaises(PdfOcrError) as error,
            ):
                compose_pdf_ocr_fallback(
                    "scan.pdf", b"%PDF-scan", detector_dir="d", recognizer_dir="r"
                )
            self.assertEqual(error.exception.code, expected)
            self.assertEqual(error.exception.page_number, 1)

    def test_rendered_page_number_set_mismatch_fails_closed(self) -> None:
        rendered = SimpleNamespace(
            artifact=SimpleNamespace(
                page_count=1,
                pages=(PdfRenderedPage(2, 10, 10, 0, _PNG),),
            )
        )
        with (
            mock.patch.object(
                pdf_ocr_fallback, "render_pdf_page_previews", return_value=rendered
            ),
            mock.patch.object(
                pdf_ocr_fallback,
                "inspect_pdf_document",
                return_value=_inspection(("",)),
            ),
            self.assertRaises(PdfOcrError) as error,
        ):
            compose_pdf_ocr_fallback(
                "scan.pdf", b"%PDF-scan", detector_dir="d", recognizer_dir="r"
            )
        self.assertEqual(error.exception.code, "pdf_ocr_page_mismatch")

    def test_image_facade_refusal_is_stable_and_does_not_leak_its_message(self) -> None:
        with (
            mock.patch.object(
                pdf_ocr_fallback, "render_pdf_page_previews", return_value=_rendered(1)
            ),
            mock.patch.object(
                pdf_ocr_fallback,
                "image_ocr",
                side_effect=ImageSkillError("image_intake_refused"),
            ),
            mock.patch.object(
                pdf_ocr_fallback,
                "inspect_pdf_document",
                return_value=_inspection(("",)),
            ),
            self.assertRaises(PdfOcrError) as error,
        ):
            compose_pdf_ocr_fallback(
                "scan.pdf", b"%PDF-scan", detector_dir="d", recognizer_dir="r"
            )
        self.assertEqual(
            error.exception.safe_dict(),
            {"code": "pdf_ocr_input_rejected", "page_number": 1},
        )

    def test_public_projection_excludes_pdf_and_png_bytes_and_host_paths(self) -> None:
        with (
            mock.patch.object(
                pdf_ocr_fallback, "render_pdf_page_previews", return_value=_rendered(1)
            ),
            mock.patch.object(
                pdf_ocr_fallback, "image_ocr", return_value=_ocr_completed()
            ),
            mock.patch.object(
                pdf_ocr_fallback,
                "inspect_pdf_document",
                return_value=_inspection(("",)),
            ),
        ):
            result = compose_pdf_ocr_fallback(
                "scan.pdf",
                b"%PDF-secret",
                detector_dir="C:/secret-detector",
                recognizer_dir="C:/secret-recognizer",
            )
        public = result.to_public_dict()
        rendered_text = str(public) + repr(result)
        self.assertNotIn("%PDF-secret", rendered_text)
        self.assertNotIn(str(_PNG), rendered_text)
        self.assertNotIn("secret-detector", rendered_text)
        self.assertNotIn("secret-recognizer", rendered_text)

    def test_composition_adds_no_second_parser_renderer_ocr_or_network_authority(
        self,
    ) -> None:
        source = Path(pdf_ocr_fallback.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imports.update(
            node.module.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        )
        self.assertTrue(
            imports.isdisjoint(
                {"pypdf", "pypdfium2", "paddleocr", "subprocess", "http", "urllib"}
            )
        )


@unittest.skipUnless(importlib.util.find_spec("pypdf") is not None, "pypdf is required")
class PdfOcrRealPdfIntakeTests(unittest.TestCase):
    @staticmethod
    def _mixed_pdf() -> bytes:
        from pypdf import PdfWriter
        from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

        writer = PdfWriter()
        native = writer.add_blank_page(width=200, height=200)
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        native[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
        )
        content = DecodedStreamObject()
        content.set_data(b"BT /F1 12 Tf 20 100 Td (native page) Tj ET")
        native[NameObject("/Contents")] = writer._add_object(content)
        writer.add_blank_page(width=200, height=200)
        output = io.BytesIO()
        writer.write(output)
        return output.getvalue()

    @staticmethod
    def _encrypted_pdf() -> bytes:
        from pypdf import PdfWriter

        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        writer.encrypt("secret")
        output = io.BytesIO()
        writer.write(output)
        return output.getvalue()

    def test_real_malformed_and_encrypted_pdfs_fail_before_render_or_ocr(self) -> None:
        for name, payload in (
            ("malformed.pdf", b"%PDF-1.7\nnot a valid PDF"),
            ("encrypted.pdf", self._encrypted_pdf()),
        ):
            with self.subTest(name=name):
                with (
                    mock.patch.object(
                        pdf_ocr_fallback, "render_pdf_page_previews"
                    ) as renderer,
                    mock.patch.object(pdf_ocr_fallback, "image_ocr") as ocr,
                    self.assertRaises(PdfOcrError) as error,
                ):
                    compose_pdf_ocr_fallback(
                        name, payload, detector_dir="d", recognizer_dir="r"
                    )
                self.assertEqual(error.exception.code, "pdf_ocr_input_rejected")
                renderer.assert_not_called()
                ocr.assert_not_called()

    @unittest.skipUnless(
        importlib.util.find_spec("pypdfium2") is not None, "pypdfium2 is required"
    )
    def test_real_pdf_path_renders_only_fallback_page_and_calls_existing_image_facade(
        self,
    ) -> None:
        calls: list[tuple[str, bytes]] = []

        def fake_ocr(payload: bytes, **kwargs: object) -> SimpleNamespace:
            calls.append((str(kwargs["filename"]), payload))
            return _ocr_completed("rendered scan")

        pdf_bytes = self._mixed_pdf()
        with mock.patch.object(pdf_ocr_fallback, "image_ocr", side_effect=fake_ocr):
            result = compose_pdf_ocr_fallback(
                "mixed-real.pdf", pdf_bytes, detector_dir="d", recognizer_dir="r"
            )

        self.assertEqual(result.source_kind, "mixed_native_ocr")
        self.assertEqual([page.source_kind for page in result.pages], ["native", "ocr"])
        self.assertEqual([name for name, _ in calls], ["pdf-page-2.png"])
        self.assertTrue(calls[0][1].startswith(b"\x89PNG"))

    @unittest.skipUnless(
        importlib.util.find_spec("pypdfium2") is not None, "pypdfium2 is required"
    )
    def test_real_pdf_path_refuses_missing_local_ocr_runtime_without_download(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as missing:
            root = Path(missing)
            with self.assertRaises(PdfOcrError) as error:
                compose_pdf_ocr_fallback(
                    "mixed-real.pdf",
                    self._mixed_pdf(),
                    detector_dir=str(root / "detector"),
                    recognizer_dir=str(root / "recognizer"),
                )
        self.assertEqual(error.exception.code, "pdf_ocr_runtime_missing")
        self.assertEqual(error.exception.page_number, 2)


if __name__ == "__main__":
    unittest.main()
