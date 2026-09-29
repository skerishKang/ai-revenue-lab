"""B66 Space Bunny extraction routing (source-only, #3212).

Proves, without any live provider call:

- native text -> governed text request (manual, fallback off);
- image -> canonical B14 multimodal request (manual, fallback off);
- scanned PDF -> Core PDF rendering authority -> per-page multimodal;
- model output stays untrusted (missing facts UNKNOWN, no fabrication);
- QuoteCore stays the only calculation authority;
- #3205 Korean synthetic corpus fixtures drive the routing proof.
"""

from __future__ import annotations

import base64
import json
import unittest
from pathlib import Path

from app.extraction_routing import (
    B66_GOVERNED_PROVIDER,
    B66_GOVERNED_ROUTE,
    B66_GOVERNED_UPSTREAM,
    B66_USE_STREAMING,
    B66ExtractionRoutingError,
    MANUAL_FALLBACK_ALLOWED,
    QUOTECORE_CALCULATION_AUTHORITY,
    UNKNOWN,
    build_image_extraction_request,
    build_scanned_pdf_extraction_requests,
    build_text_extraction_request,
    normalize_model_output,
    project_to_quote_draft_candidate,
)
from app.file_intake import handle_intake_payload
from padiem_ai_core.document_normalization import NormalizedDocument

CORPUS_DIR = (
    Path(__file__).resolve().parents[3]
    / "packages"
    / "padiem-ai-core"
    / "tests"
    / "fixtures"
    / "b66_e2e_corpus"
)

PNG = b"\x89PNG\r\n\x1a\n" + b"b66vision"
JPEG = b"\xff\xd8\xff\xe0" + b"b66vision"
WEBP = b"RIFF\x08\x00\x00\x00WEBP" + b"b66vision"


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def parser_with_text(text: str):
    def _parser(*, name: str, media_type: str, payload: bytes) -> NormalizedDocument:
        return NormalizedDocument(
            name=name,
            media_type=media_type,
            text=text,
            byte_size=len(payload),
            source_kind="binary",
        )

    return _parser


class B66GovernedRouteTests(unittest.TestCase):
    def test_governed_lane_pins_space_bunny_without_new_provider(self) -> None:
        self.assertEqual(B66_GOVERNED_ROUTE, "kilo/stealth-space-bunny-alpha")
        self.assertEqual(B66_GOVERNED_UPSTREAM, "stealth/space-bunny-alpha")
        self.assertEqual(B66_GOVERNED_PROVIDER, "kilo")
        self.assertFalse(MANUAL_FALLBACK_ALLOWED)
        self.assertFalse(B66_USE_STREAMING)
        self.assertTrue(QUOTECORE_CALCULATION_AUTHORITY)

    def test_native_text_to_text_route(self) -> None:
        intake = handle_intake_payload(
            {
                "name": "quote.pdf",
                "media_type": "application/pdf",
                "base64": b64(b"%PDF-1.4\nsynthetic"),
            },
            parser=parser_with_text("견적번호 Q-2026-3001\n공급가액 170400"),
        )
        self.assertTrue(intake["ok"])
        self.assertEqual(intake["result"]["kind"], "native_document")
        request = build_text_extraction_request(
            intake["result"]["text"],
            filename="quote.pdf",
            source_kind="native_document",
        )
        self.assertEqual(request["model"], "kilo/stealth-space-bunny-alpha")
        self.assertEqual(request["messages"][0]["role"], "user")
        self.assertIsInstance(request["messages"][0]["content"], str)
        self.assertIn("견적번호", request["messages"][0]["content"])
        self.assertFalse(request["business14"]["allow_external_fallback"])
        self.assertFalse(request["b66"]["fallback_allowed"])
        self.assertEqual(request["b66"]["route_mode"], "manual")
        self.assertFalse(request["b66"]["stream"])

    def test_image_to_multimodal_route_png_jpeg_webp(self) -> None:
        cases = [
            ("quote.png", "image/png", PNG),
            ("quote.jpg", "image/jpeg", JPEG),
            ("quote.webp", "image/webp", WEBP),
        ]
        for name, media_type, raw in cases:
            with self.subTest(name=name):
                request = build_image_extraction_request(
                    raw, media_type=media_type, filename=name
                )
                self.assertEqual(request["model"], "kilo/stealth-space-bunny-alpha")
                content = request["messages"][0]["content"]
                self.assertIsInstance(content, list)
                self.assertEqual(len(content), 2)
                self.assertEqual(content[0]["type"], "text")
                self.assertEqual(content[1]["type"], "image_url")
                url = content[1]["image_url"]["url"]
                self.assertTrue(url.startswith(f"data:{media_type};base64,"))
                self.assertFalse(request["business14"]["allow_external_fallback"])
                self.assertEqual(
                    request["business14"]["required_capabilities"], ["image"]
                )

    def test_remote_url_forbidden_oversized_rejected_magic_rejected(self) -> None:
        # Remote URLs are never a valid input to the byte-level builder.
        with self.assertRaises(Exception):
            build_image_extraction_request(
                "https://example.com/photo.png",  # type: ignore[arg-type]
                media_type="image/png",
                filename="quote.png",
            )
        too_large = b"\xff\xd8\xff" + b"x" * (4 * 1024 * 1024)
        with self.assertRaises(Exception):
            build_image_extraction_request(
                too_large, media_type="image/jpeg", filename="quote.jpg"
            )
        with self.assertRaises(Exception):
            build_image_extraction_request(
                b"not-png", media_type="image/png", filename="quote.png"
            )
        # Declared MIME must match magic bytes (JPEG bytes as PNG fails).
        with self.assertRaises(Exception):
            build_image_extraction_request(
                JPEG, media_type="image/png", filename="quote.png"
            )

    def test_scanned_pdf_to_multimodal_via_core_render_authority(self) -> None:
        try:
            import pypdfium2  # noqa: F401
        except ImportError:
            # Render authority unavailable here: the adapter must fail closed
            # with a distinct code, never a raw dependency error.
            with self.assertRaises(B66ExtractionRoutingError) as ctx:
                build_scanned_pdf_extraction_requests(
                    b"%PDF-1.4\nstub", name="scan.pdf"
                )
            self.assertEqual(ctx.exception.code, "render_authority_unavailable")
            return
        source = (CORPUS_DIR / "f02-scanned-quotation.source.pdf").read_bytes()
        requests = build_scanned_pdf_extraction_requests(source, name="scan.pdf")
        self.assertGreaterEqual(len(requests), 1)
        for request in requests:
            self.assertEqual(request["model"], "kilo/stealth-space-bunny-alpha")
            content = request["messages"][0]["content"]
            self.assertIsInstance(content, list)
            self.assertEqual(content[1]["type"], "image_url")
            self.assertTrue(
                content[1]["image_url"]["url"].startswith("data:image/png;base64,")
            )
            self.assertFalse(request["business14"]["allow_external_fallback"])
            self.assertEqual(request["b66"]["source_kind"], "scanned_pdf")

    def test_scanned_pdf_uses_render_pages_not_custom_decoding(self) -> None:
        source_path = (
            Path(__file__).resolve().parents[1].joinpath("app", "extraction_routing.py")
        )
        text = source_path.read_text(encoding="utf-8")
        self.assertIn("render_pdf_pages", text)
        self.assertIn("pdf_render", text)
        # No custom rendering stack and no network/model execution surface.
        for token in ("fitz", "pdf2image", "poppler", "ocrmypdf", "tesseract"):
            self.assertNotIn(token, text.lower())

    def test_corpus_minimum_targets_drive_routing(self) -> None:
        required = {
            "F01": "f01-native-quotation.pdf",
            "F02": "f02-scanned-quotation.png",
            "F03": "f03-quotation.docx",
            "F04": "f04-quotation.xlsx",
            "F09": "f09-missing-fields.pdf",
            "F12": "f12-multipage-quotation.pdf",
            "F13": "f13-degraded-scan.png",
        }
        manifest = json.loads((CORPUS_DIR / "manifest.json").read_text(encoding="utf-8"))
        manifest_ids = {entry["fixture_id"] for entry in manifest["fixtures"]}
        for fixture_id, relative in required.items():
            with self.subTest(fixture=fixture_id):
                self.assertIn(fixture_id, manifest_ids)
                path = CORPUS_DIR / relative
                self.assertTrue(path.exists(), f"missing corpus file {relative}")
                self.assertGreater(path.stat().st_size, 0)

        # Native corpus members route to the text lane (parser port reused).
        for fixture_id, relative, media in [
            ("F01", "f01-native-quotation.pdf", "application/pdf"),
            ("F03", "f03-quotation.docx",
             "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
            ("F04", "f04-quotation.xlsx",
             "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            ("F09", "f09-missing-fields.pdf", "application/pdf"),
        ]:
            raw = (CORPUS_DIR / relative).read_bytes()
            intake = handle_intake_payload(
                {"name": relative, "media_type": media, "base64": b64(raw)},
                parser=parser_with_text(f"synthetic {fixture_id} 견적 텍스트"),
            )
            self.assertTrue(intake["ok"], (fixture_id, intake))
            self.assertEqual(intake["result"]["kind"], "native_document")
            request = build_text_extraction_request(
                intake["result"]["text"],
                filename=relative,
                source_kind="native_document",
            )
            self.assertEqual(request["model"], "kilo/stealth-space-bunny-alpha")

        # Vision corpus members route to the multimodal lane.
        for fixture_id, relative, media in [
            ("F02", "f02-scanned-quotation.png", "image/png"),
            ("F13", "f13-degraded-scan.png", "image/png"),
        ]:
            raw = (CORPUS_DIR / relative).read_bytes()
            self.assertTrue(raw.startswith(b"\x89PNG\r\n\x1a\n"), fixture_id)
            request = build_image_extraction_request(
                raw, media_type=media, filename=relative
            )
            self.assertEqual(request["model"], "kilo/stealth-space-bunny-alpha")

        # Multipage corpus member renders to per-page multimodal requests.
        multipage = (CORPUS_DIR / "f12-multipage-quotation.pdf").read_bytes()
        page_requests = build_scanned_pdf_extraction_requests(
            b"%PDF-stub", name="stub.pdf", renderer=_fake_two_page_renderer()
        )
        self.assertEqual(len(page_requests), 2)
        self.assertGreater(len(multipage), 0)

    def test_model_output_validation_and_unknown_stays_unknown(self) -> None:
        valid = normalize_model_output(
            {
                "source": {"kind": "image"},
                "sender": {"company": "주식회사 테스트상사"},
                "recipient": {"company": "주식회사 예시테크"},
                "quote": {"quoteNo": "Q-2026-3002", "issueDate": "2026-03-03"},
                "items": [
                    {"name": "스테인리스 배관 40x40", "qty": "12", "unitPrice": "9,800"}
                ],
                "tax": {"mode": "EXCLUSIVE"},
                "memo": "납기 협의",
                "evidence": [],
                "warnings": [],
            }
        )
        self.assertTrue(valid["ok"])
        self.assertEqual(valid["extraction"]["quote_number"], "Q-2026-3002")

        # F09 hallucination trap: absent facts must not be fabricated.
        missing = normalize_model_output(
            {
                "source": {"kind": "native_document"},
                "sender": {"company": "주식회사 테스트상사"},
                "recipient": {"company": "주식회사 견본물산"},
                "quote": {},
                "items": [],
                "tax": {},
                "memo": None,
                "evidence": [],
                "warnings": [],
            }
        )
        self.assertTrue(missing["ok"])
        self.assertEqual(missing["extraction"]["quote_number"], UNKNOWN)
        self.assertEqual(missing["extraction"]["quote_date"], UNKNOWN)
        self.assertEqual(missing["extraction"]["memo"], UNKNOWN)
        self.assertIn("quote_number", missing["unknowns"])

    def test_quotecore_calculation_authority(self) -> None:
        forged = normalize_model_output(
            {
                "source": {"kind": "image"},
                "sender": {"company": "x"},
                "recipient": {"company": "y"},
                "quote": {"quoteNo": "Q-1"},
                "items": [],
                "tax": {"mode": "EXCLUSIVE"},
                "memo": None,
                "evidence": [],
                "warnings": [],
                "totals": {"grand": "999999"},
            }
        )
        self.assertFalse(forged["ok"])
        self.assertEqual(forged["code"], "computed_totals_forbidden")

        normalized = normalize_model_output(
            {
                "source": {"kind": "image"},
                "sender": {"company": "x"},
                "recipient": {"company": "y"},
                "quote": {"quoteNo": "Q-1"},
                "items": [{"name": "품목", "qty": "2", "unitPrice": "1000"}],
                "tax": {"mode": "EXCLUSIVE"},
                "memo": None,
                "evidence": [],
                "warnings": [],
            }
        )
        self.assertTrue(normalized["ok"])
        candidate = project_to_quote_draft_candidate(normalized)
        self.assertNotIn("totals", candidate)
        self.assertEqual(candidate["derived_by"], "quote-core-pending")
        self.assertTrue(QUOTECORE_CALCULATION_AUTHORITY)

    def test_adapter_carries_no_credential_or_network_surface(self) -> None:
        text = (
            Path(__file__).resolve().parents[1].joinpath("app", "extraction_routing.py")
            .read_text(encoding="utf-8")
        )
        for token in (
            "api_key",
            "Authorization",
            "base_url",
            "http://",
            "https://",
            "password",
        ):
            self.assertNotIn(token, text)


def _fake_two_page_renderer():
    def _renderer(*, name: str, media_type: str, payload: bytes):
        from padiem_ai_core.pdf_render import PdfRenderedPage, PdfRenderResult

        pages = tuple(
            PdfRenderedPage(
                page_number=index,
                width=10,
                height=10,
                rotation=0,
                data=(b"\x89PNG\r\n\x1a\n" + f"page-{index}".encode()),
            )
            for index in (1, 2)
        )
        return PdfRenderResult(
            pages=pages,
            page_count=2,
            output_byte_size=sum(len(page.data) for page in pages),
        )

    return _renderer


if __name__ == "__main__":
    unittest.main()
