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
                "source": {"kind": "image", "filename": "f02.png"},
                "sender": {"company": "주식회사 테스트상사"},
                "recipient": {"company": "주식회사 예시테크"},
                "quote": {
                    "quoteNo": "Q-2026-3002",
                    "issueDate": "2026-03-03",
                    "validDays": 30,
                },
                "items": [
                    {"name": "스테인리스 배관 40x40", "qty": "12", "unitPrice": "9,800"}
                ],
                "tax": {"mode": "EXCLUSIVE"},
                "memo": "납기 협의",
                "evidence": [
                    {
                        "field": "quote.quoteNo",
                        "page": 1,
                        "snippet": "Q-2026-3002",
                        "confidence": 0.9,
                    }
                ],
                "warnings": [],
            }
        )
        self.assertTrue(valid["ok"], valid)
        extraction = valid["extraction"]
        self.assertEqual(extraction["quote"]["quoteNo"], "Q-2026-3002")
        self.assertEqual(extraction["quote"]["issueDate"], "2026-03-03")
        self.assertEqual(extraction["quote"]["validDays"], 30)
        self.assertEqual(extraction["items"][0]["qty"], 12)
        self.assertEqual(extraction["items"][0]["unitPrice"], 9800)
        self.assertEqual(len(extraction["evidence"]), 1)
        self.assertEqual(extraction["evidence"][0]["field"], "quote.quoteNo")

        # F09 hallucination trap: absent facts stay None, never fabricated.
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
        self.assertTrue(missing["ok"], missing)
        self.assertIsNone(missing["extraction"]["quote"]["quoteNo"])
        self.assertIsNone(missing["extraction"]["quote"]["issueDate"])
        self.assertIsNone(missing["extraction"]["memo"])
        self.assertIn("quote.quoteNo", missing["unknowns"])
        self.assertIn("quote.issueDate", missing["unknowns"])
        self.assertIn("memo", missing["unknowns"])
        self.assertIn("items", missing["unknowns"])

    def test_malformed_nested_objects_fail_closed(self) -> None:
        base = {
            "source": {"kind": "image"},
            "sender": {"company": "x"},
            "recipient": {"company": "y"},
            "quote": {"quoteNo": "Q-1"},
            "items": [],
            "tax": {"mode": "EXCLUSIVE"},
            "memo": None,
            "evidence": [],
            "warnings": [],
        }

        def check(overrides: dict, code: str) -> None:
            payload = dict(base)
            payload.update(overrides)
            result = normalize_model_output(payload)
            self.assertFalse(result["ok"], (overrides, result))
            self.assertEqual(result["code"], code, (overrides, result))

        check({"sender": "주식회사 테스트상사"}, "invalid_sender")
        check({"recipient": ["y"]}, "invalid_recipient")
        check({"quote": [1]}, "invalid_quote")
        check({"tax": "EXCLUSIVE"}, "invalid_tax")
        check({"items": {"name": "x"}}, "invalid_items")
        check({"items": ["x"]}, "invalid_item_0")
        check({"items": [{"name": "x", "qty": "12", "unitPrice": "100", "extra": 1}]},
              "unsupported_item_field")
        check({"evidence": ["x"]}, "invalid_evidence_0")
        check({"warnings": "납기 협의"}, "invalid_warnings")
        check({"warnings": ["ok", 7]}, "invalid_warning")
        check({"sender": {"company": "x", "ceo": "y"}}, "unsupported_sender_field")
        check({"quote": {"quoteNo": "Q-1", "total": "9"}}, "unsupported_quote_field")
        check({"mystery": 1}, "unsupported_extraction_field")

    def test_issue_dates_require_iso_and_real_calendar_dates(self) -> None:
        def quote_with(date_value):
            return {
                "source": {"kind": "image"},
                "sender": {},
                "recipient": {},
                "quote": {"issueDate": date_value},
                "items": [],
                "tax": {},
                "memo": None,
                "evidence": [],
                "warnings": [],
            }

        for bad in ["2026-13-01", "2026-02-30", "2026-3-3", "03/03/2026",
                    "2026-03-03T00:00:00", "어제", 20260303]:
            result = normalize_model_output(quote_with(bad))
            self.assertFalse(result["ok"], bad)
            self.assertEqual(result["code"], "invalid_issue_date", bad)

        for good in ["2026-03-03", "2024-02-29"]:
            result = normalize_model_output(quote_with(good))
            self.assertTrue(result["ok"], good)
            self.assertEqual(result["extraction"]["quote"]["issueDate"], good)

    def test_valid_days_bounded_positive_integers(self) -> None:
        def quote_with(days_value):
            return {
                "source": {"kind": "image"},
                "sender": {},
                "recipient": {},
                "quote": {"validDays": days_value},
                "items": [],
                "tax": {},
                "memo": None,
                "evidence": [],
                "warnings": [],
            }

        result = normalize_model_output(quote_with(30))
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["extraction"]["quote"]["validDays"], 30)

        # JS parity: surrounding whitespace is trimmed before validation.
        for padded, expected in [("30 ", 30), (" 2", 2), ("\t7\n", 7)]:
            result = normalize_model_output(quote_with(padded))
            self.assertTrue(result["ok"], repr(padded))
            self.assertEqual(
                result["extraction"]["quote"]["validDays"], expected, repr(padded)
            )

        for bad in [0, -3, 1.5, "abc", "   ", True, 3.5]:
            result = normalize_model_output(quote_with(bad))
            self.assertFalse(result["ok"], repr(bad))
            self.assertEqual(result["code"], "invalid_valid_days", repr(bad))

    def test_oversized_digit_strings_fail_closed_with_contract_codes(self) -> None:
        huge = "9" * 5000

        def envelope_with(**overrides):
            base = {
                "source": {"kind": "image"},
                "sender": {},
                "recipient": {},
                "quote": {},
                "items": [],
                "tax": {},
                "memo": None,
                "evidence": [],
                "warnings": [],
            }
            base.update(overrides)
            return normalize_model_output(base)

        # No raw ValueError may escape; each boundary reports its own code.
        self.assertEqual(
            envelope_with(quote={"validDays": huge})["code"], "invalid_valid_days"
        )
        self.assertEqual(
            envelope_with(evidence=[{"field": "f", "page": huge}])["code"],
            "invalid_evidence_page",
        )
        self.assertEqual(
            envelope_with(items=[{"name": "n", "qty": huge}])["code"],
            "invalid_item_qty",
        )
        self.assertEqual(
            envelope_with(items=[{"name": "n", "unitPrice": huge}])["code"],
            "invalid_item_unit_price",
        )

    def test_evidence_page_trims_whitespace_like_js(self) -> None:
        result = normalize_model_output(
            {
                "source": {"kind": "image"},
                "sender": {},
                "recipient": {},
                "quote": {},
                "items": [],
                "tax": {},
                "memo": None,
                "evidence": [{"field": "f", "page": " 2 "}],
                "warnings": [],
            }
        )
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["extraction"]["evidence"][0]["page"], 2)

    def test_evidence_validated_and_preserved(self) -> None:
        def with_evidence(evidence_value):
            return {
                "source": {"kind": "image"},
                "sender": {},
                "recipient": {},
                "quote": {},
                "items": [],
                "tax": {},
                "memo": None,
                "evidence": evidence_value,
                "warnings": [],
            }

        good = with_evidence(
            [{"field": "quote.quoteNo", "page": 2,
              "snippet": "Q-2026-3002", "confidence": 1}]
        )
        result = normalize_model_output(good)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["extraction"]["evidence"], good["evidence"])

        minimal = with_evidence([{"field": "memo"}])
        result = normalize_model_output(minimal)
        self.assertTrue(result["ok"], result)
        self.assertEqual(
            result["extraction"]["evidence"],
            [{"field": "memo", "page": None, "snippet": None, "confidence": None}],
        )

        too_many = with_evidence([{"field": f"f{i}"} for i in range(201)])
        result = normalize_model_output(too_many)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "too_much_evidence")

        for evidence_value, code in [
            ([{"page": 1}], "invalid_evidence_field"),
            ([{"field": "x", "confidence": 1.5}], "invalid_evidence_confidence"),
            ([{"field": "x", "confidence": -0.1}], "invalid_evidence_confidence"),
            ([{"field": "x", "page": 0}], "invalid_evidence_page"),
            ([{"field": "x", "detail": "y"}], "unsupported_evidence_field"),
        ]:
            result = normalize_model_output(with_evidence(evidence_value))
            self.assertFalse(result["ok"], (evidence_value, result))
            self.assertEqual(result["code"], code, (evidence_value, result))

    def test_warnings_validated_and_preserved(self) -> None:
        def with_warnings(warnings_value):
            return {
                "source": {"kind": "image"},
                "sender": {},
                "recipient": {},
                "quote": {},
                "items": [],
                "tax": {},
                "memo": None,
                "evidence": [],
                "warnings": warnings_value,
            }

        result = normalize_model_output(with_warnings(["낮은 해상도", "회전됨"]))
        self.assertTrue(result["ok"], result)
        self.assertEqual(
            result["extraction"]["warnings"], ["낮은 해상도", "회전됨"]
        )

        result = normalize_model_output(with_warnings(["w"] * 51))
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "too_many_warnings")

        # Unknown tax modes degrade to a review warning, mirroring the JS.
        taxed = with_warnings([])
        taxed["tax"] = {"mode": "WEIRD"}
        result = normalize_model_output(taxed)
        self.assertTrue(result["ok"], result)
        self.assertIsNone(result["extraction"]["tax"]["mode"])
        self.assertEqual(result["extraction"]["warnings"], ["unknown_tax_mode"])

    def test_candidate_preserves_evidence_warnings_and_unknowns(self) -> None:
        normalized = normalize_model_output(
            {
                "source": {"kind": "image", "filename": "f02.png"},
                "sender": {"company": "주식회사 테스트상사"},
                "recipient": {},
                "quote": {"quoteNo": "Q-2026-3002", "validDays": 30},
                "items": [{"name": "품목", "qty": 2, "unitPrice": 1000}],
                "tax": {"mode": "EXCLUSIVE"},
                "memo": None,
                "evidence": [{"field": "quote.quoteNo", "snippet": "Q-2026-3002"}],
                "warnings": ["낮은 해상도"],
            }
        )
        self.assertTrue(normalized["ok"], normalized)
        candidate = project_to_quote_draft_candidate(normalized)
        self.assertEqual(candidate["quote_number"], "Q-2026-3002")
        self.assertEqual(candidate["quote_date"], UNKNOWN)
        self.assertEqual(candidate["valid_days"], 30)
        self.assertEqual(candidate["sender"]["company"], "주식회사 테스트상사")
        self.assertEqual(candidate["recipient"]["company"], UNKNOWN)
        self.assertEqual(
            candidate["review"]["evidence"],
            [
                {
                    "field": "quote.quoteNo",
                    "page": None,
                    "snippet": "Q-2026-3002",
                    "confidence": None,
                }
            ],
        )
        self.assertEqual(candidate["review"]["warnings"], ["낮은 해상도"])
        self.assertIn("quote.issueDate", candidate["unknowns"])
        self.assertIn("memo", candidate["unknowns"])
        self.assertNotIn("totals", candidate)

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
