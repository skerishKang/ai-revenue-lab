"""B66 extraction routing under full Space Bunny retirement (source-only).

Proves, without any live provider call, the owner final retirement decision
(2026-10-07):

- the canonical Padiem primary stays pending/None (no successor selected);
- the Space Bunny lane identity survives as historical metadata only;
- the retired lane is absent from KILO_FREE_ROUTES and from the catalog;
- manual resolution of the retired lane fails closed;
- every B66 request builder fails closed (model_route_unavailable) and no
  builder emits a Space Bunny (or any other) model request;
- no fallback and no silent substitution of a new model exists;
- model output validation authority is unchanged (missing facts null;
  UNKNOWN is display-only) and QuoteCore stays the only calculation
  authority;
- #3205 Korean synthetic corpus fixtures remain the shared fixture basis.
"""

from __future__ import annotations

import ast
import base64
import importlib.util
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
# CI runs this suite with PYTHONPATH limited to padiem-ai-core + this adapter,
# so the platform pilot modules are read via AST instead of imported.
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

KILO_SPACE_BUNNY_ROUTE_ID = "kilo/stealth-space-bunny-alpha"

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


def normalize_from_model(raw):
    """Legacy-shaped test helper with trusted source supplied out-of-band.

    Existing test payloads predate #3212's server-owned provenance boundary
    and often include an exact source object. The production normalizer now
    receives the authoritative source from intake/render metadata; this helper
    derives the same trusted fixture facts while leaving the model payload
    unchanged so exact-match compatibility is also exercised.
    """
    source = raw.get("source") if isinstance(raw, dict) else None
    source = source if isinstance(source, dict) else {}
    kind = source.get("kind") or "image"
    default_name = {
        "text": "fixture.txt",
        "native_document": "fixture.pdf",
        "image": "fixture.png",
        "scanned_pdf": "fixture.pdf",
    }.get(kind, "fixture.bin")
    filename = source.get("filename") or default_name
    return normalize_model_output(raw, source_kind=kind, filename=filename)


class B66GovernedRouteTests(unittest.TestCase):
    def test_retired_lane_identity_survives_as_metadata_only(self) -> None:
        # Historical identity constants are preserved, but they name a retired
        # lane, not an executable route.
        self.assertEqual(B66_GOVERNED_ROUTE, "kilo/stealth-space-bunny-alpha")
        self.assertEqual(B66_GOVERNED_UPSTREAM, "stealth/space-bunny-alpha")
        self.assertEqual(B66_GOVERNED_PROVIDER, "kilo")
        self.assertFalse(MANUAL_FALLBACK_ALLOWED)
        self.assertFalse(B66_USE_STREAMING)
        self.assertTrue(QUOTECORE_CALCULATION_AUTHORITY)

    def test_text_builder_fails_closed_under_hold(self) -> None:
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
        # HOLD fail-closed: the builder emits no model request at all.
        with self.assertRaises(B66ExtractionRoutingError) as ctx:
            build_text_extraction_request(
                intake["result"]["text"],
                filename="quote.pdf",
                source_kind="native_document",
            )
        self.assertEqual(ctx.exception.code, "model_route_unavailable")

    def test_image_builder_fails_closed_under_hold(self) -> None:
        cases = [
            ("quote.png", "image/png", PNG),
            ("quote.jpg", "image/jpeg", JPEG),
            ("quote.webp", "image/webp", WEBP),
        ]
        for name, media_type, raw in cases:
            with self.subTest(name=name):
                # HOLD fail-closed: the builder emits no model request at all,
                # for every modality, with no successor substitution.
                with self.assertRaises(B66ExtractionRoutingError) as ctx:
                    build_image_extraction_request(
                        raw, media_type=media_type, filename=name
                    )
                self.assertEqual(ctx.exception.code, "model_route_unavailable")

    def test_image_builder_fails_closed_before_any_shape_check(self) -> None:
        # Under the HOLD the builder raises the deterministic route-unavailable
        # code regardless of input shape: remote URLs, oversized payloads, and
        # magic mismatches can never reach a model request.
        too_large = b"\xff\xd8\xff" + b"x" * (4 * 1024 * 1024)
        for raw, media_type, filename in (
            ("https://example.com/photo.png", "image/png", "quote.png"),
            (too_large, "image/jpeg", "quote.jpg"),
            (b"not-png", "image/png", "quote.png"),
            (JPEG, "image/png", "quote.png"),
        ):
            with self.subTest(media_type=media_type):
                with self.assertRaises(B66ExtractionRoutingError) as ctx:
                    build_image_extraction_request(
                        raw,  # type: ignore[arg-type]
                        media_type=media_type,
                        filename=filename,
                    )
                self.assertEqual(ctx.exception.code, "model_route_unavailable")

    def test_scanned_pdf_builder_fails_closed_under_hold(self) -> None:
        # HOLD fail-closed applies with or without a render authority: no page
        # is rendered, no per-page model request is produced.
        try:
            import pypdfium2  # noqa: F401
        except ImportError:
            pass
        with self.assertRaises(B66ExtractionRoutingError) as ctx:
            build_scanned_pdf_extraction_requests(
                b"%PDF-1.4\nstub", name="scan.pdf"
            )
        self.assertEqual(ctx.exception.code, "model_route_unavailable")

    def test_builder_source_has_no_executable_model_or_render_surface(self) -> None:
        source_path = (
            Path(__file__).resolve().parents[1].joinpath("app", "extraction_routing.py")
        )
        text = source_path.read_text(encoding="utf-8")
        # The retired route is named only as historical metadata; the builder
        # fail-closed constant exists; no render/OCR stack and no network
        # surface exist.
        self.assertIn("B66_MODEL_ROUTE_UNAVAILABLE", text)
        self.assertIn("model_route_unavailable", text)
        self.assertIn("raise B66ExtractionRoutingError(B66_MODEL_ROUTE_UNAVAILABLE)", text)
        for token in ("fitz", "pdf2image", "poppler", "ocrmypdf", "tesseract"):
            self.assertNotIn(token, text.lower())
        # No builder body constructs a provider request anymore.
        self.assertNotIn('"model": B66_GOVERNED_ROUTE', text)

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

        # Native corpus members still pass intake (parser port reused), but
        # the text builder fails closed under the HOLD.
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
            with self.assertRaises(B66ExtractionRoutingError) as ctx:
                build_text_extraction_request(
                    intake["result"]["text"],
                    filename=relative,
                    source_kind="native_document",
                )
            self.assertEqual(ctx.exception.code, "model_route_unavailable")

        # Vision corpus members: image builder fails closed as well.
        for fixture_id, relative, media in [
            ("F02", "f02-scanned-quotation.png", "image/png"),
            ("F13", "f13-degraded-scan.png", "image/png"),
        ]:
            raw = (CORPUS_DIR / relative).read_bytes()
            self.assertTrue(raw.startswith(b"\x89PNG\r\n\x1a\n"), fixture_id)
            with self.assertRaises(B66ExtractionRoutingError) as ctx:
                build_image_extraction_request(
                    raw, media_type=media, filename=relative
                )
            self.assertEqual(ctx.exception.code, "model_route_unavailable")

        # Multipage corpus member stays valid fixture data; the scanned-PDF
        # builder never renders or emits anything.
        multipage = (CORPUS_DIR / "f12-multipage-quotation.pdf").read_bytes()
        self.assertGreater(len(multipage), 0)
        with self.assertRaises(B66ExtractionRoutingError) as ctx:
            build_scanned_pdf_extraction_requests(
                b"%PDF-stub", name="stub.pdf", renderer=_fake_two_page_renderer()
            )
        self.assertEqual(ctx.exception.code, "model_route_unavailable")

    def test_extraction_prompt_contract_is_retained_for_successor_lane(self) -> None:
        # The bounded prompt contract stays as documented authority for the
        # future successor lane; builders themselves emit nothing under HOLD.
        from app.extraction_routing import _EXTRACTION_JSON_CONTRACT

        prompt = _EXTRACTION_JSON_CONTRACT
        self.assertIn("JSON 객체 하나만", prompt)
        self.assertIn("JSON null", prompt)
        self.assertIn("source는 서버가 소유", prompt)
        self.assertIn("마크다운/설명 문장을 덧붙이지", prompt)
        self.assertIn("공급자", prompt)
        self.assertIn("공급받는 자", prompt)
        self.assertIn("sender 값을 recipient에 복사", prompt)
        self.assertNotIn("없는 값은 UNKNOWN", prompt)

    def test_literal_unknown_is_rejected_as_model_fact(self) -> None:
        result = normalize_model_output(
            {
                "sender": {"company": "UNKNOWN"},
                "recipient": {},
                "quote": {},
                "items": [],
                "tax": {},
                "memo": None,
                "evidence": [],
                "warnings": [],
            },
            source_kind="image",
            filename="trusted.png",
        )
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["code"], "reserved_unknown_sentinel")

    def test_server_owned_source_provenance_cannot_be_overridden(self) -> None:
        payload = {
            "sender": {},
            "recipient": {},
            "quote": {},
            "items": [],
            "tax": {},
            "memo": None,
            "evidence": [],
            "warnings": [],
        }
        normalized = normalize_model_output(
            payload, source_kind="image", filename="trusted.png"
        )
        self.assertTrue(normalized["ok"], normalized)
        self.assertEqual(
            normalized["extraction"]["source"],
            {"kind": "image", "filename": "trusted.png"},
        )

        wrong_name = dict(payload)
        wrong_name["source"] = {"kind": "image", "filename": "model-changed.png"}
        result = normalize_model_output(
            wrong_name, source_kind="image", filename="trusted.png"
        )
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["code"], "source_provenance_mismatch")

        wrong_kind = dict(payload)
        wrong_kind["source"] = {"kind": "native_document", "filename": "trusted.png"}
        result = normalize_model_output(
            wrong_kind, source_kind="image", filename="trusted.png"
        )
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["code"], "source_provenance_mismatch")

    def test_legacy_quote_draft_projection_does_not_own_saved_skill_approval(self) -> None:
        doc = project_to_quote_draft_candidate.__doc__ or ""
        self.assertIn("legacy #3147 QuoteDraft seam", doc)
        self.assertIn("not the Saved Quote Skill approval path", doc)
        source = (
            Path(__file__).resolve().parents[1]
            / "app"
            / "extraction_routing.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("quote-template-store", source)
        self.assertNotIn("SavedQuoteSkill", source)

    def test_model_output_validation_and_unknown_stays_unknown(self) -> None:
        valid = normalize_from_model(
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
        missing = normalize_from_model(
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
            result = normalize_from_model(payload)
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
            result = normalize_from_model(quote_with(bad))
            self.assertFalse(result["ok"], bad)
            self.assertEqual(result["code"], "invalid_issue_date", bad)

        for good in ["2026-03-03", "2024-02-29"]:
            result = normalize_from_model(quote_with(good))
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

        result = normalize_from_model(quote_with(30))
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["extraction"]["quote"]["validDays"], 30)

        # JS parity: surrounding whitespace is trimmed before validation.
        for padded, expected in [("30 ", 30), (" 2", 2), ("\t7\n", 7)]:
            result = normalize_from_model(quote_with(padded))
            self.assertTrue(result["ok"], repr(padded))
            self.assertEqual(
                result["extraction"]["quote"]["validDays"], expected, repr(padded)
            )

        for bad in [0, -3, 1.5, "abc", "   ", True, 3.5]:
            result = normalize_from_model(quote_with(bad))
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
            return normalize_from_model(base)

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
        result = normalize_from_model(
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
        result = normalize_from_model(good)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["extraction"]["evidence"], good["evidence"])

        minimal = with_evidence([{"field": "memo"}])
        result = normalize_from_model(minimal)
        self.assertTrue(result["ok"], result)
        self.assertEqual(
            result["extraction"]["evidence"],
            [{"field": "memo", "page": None, "snippet": None, "confidence": None}],
        )

        too_many = with_evidence([{"field": f"f{i}"} for i in range(201)])
        result = normalize_from_model(too_many)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "too_much_evidence")

        for evidence_value, code in [
            ([{"page": 1}], "invalid_evidence_field"),
            ([{"field": "x", "confidence": 1.5}], "invalid_evidence_confidence"),
            ([{"field": "x", "confidence": -0.1}], "invalid_evidence_confidence"),
            ([{"field": "x", "page": 0}], "invalid_evidence_page"),
            ([{"field": "x", "detail": "y"}], "unsupported_evidence_field"),
        ]:
            result = normalize_from_model(with_evidence(evidence_value))
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

        result = normalize_from_model(with_warnings(["낮은 해상도", "회전됨"]))
        self.assertTrue(result["ok"], result)
        self.assertEqual(
            result["extraction"]["warnings"], ["낮은 해상도", "회전됨"]
        )

        result = normalize_from_model(with_warnings(["w"] * 51))
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "too_many_warnings")

        # Unknown tax modes degrade to a review warning, mirroring the JS.
        taxed = with_warnings([])
        taxed["tax"] = {"mode": "WEIRD"}
        result = normalize_from_model(taxed)
        self.assertTrue(result["ok"], result)
        self.assertIsNone(result["extraction"]["tax"]["mode"])
        self.assertEqual(result["extraction"]["warnings"], ["unknown_tax_mode"])

    def test_candidate_preserves_evidence_warnings_and_unknowns(self) -> None:
        normalized = normalize_from_model(
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
        forged = normalize_from_model(
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

        normalized = normalize_from_model(
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


class B66CanonicalIntegrationTests(unittest.TestCase):
    """Minimal B66-specific integration under full Space Bunny retirement.

    This class pins that the B66 server-side adapter cannot drift from the
    retirement truth:

    - ``padiem_ai_core.model_primary`` stays in the model-neutral HOLD state
      (canonical text+vision primary pending successor selection, no
      secondary, no fallback, no silent fallback anywhere);
    - the retired Space Bunny lane is absent from ``KILO_FREE_ROUTES`` and
      from the catalog, and is declared in ``RETIRED_KILO_FREE_MODEL_IDS``;
      manual resolution fails closed with ``model_not_in_catalog``;
    - the historical metadata (model id / upstream id / credential binding
      constant / dated evidence snapshot) survives for audit only;
    - the B66 builders fail closed and emit no model request.
    """

    @staticmethod
    def _repo_root() -> Path:
        return Path(__file__).resolve().parents[3]

    @staticmethod
    def _load_model_primary():
        path = (
            B66CanonicalIntegrationTests._repo_root()
            / "packages"
            / "padiem-ai-core"
            / "padiem_ai_core"
            / "model_primary.py"
        )
        # Side-effect-free load: model_primary is stdlib-only by contract.
        spec = importlib.util.spec_from_file_location(
            "b66_model_primary_probe", path
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    @staticmethod
    def _space_bunny_lane_facts() -> tuple[str, str, frozenset]:
        path = (
            B66CanonicalIntegrationTests._repo_root()
            / "apps"
            / "korean-ai-platform"
            / "app"
            / "pilot"
            / "kilo_provider.py"
        )
        tree = ast.parse(path.read_text(encoding="utf-8"))
        model_id = upstream = None
        capabilities: frozenset = frozenset()
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                target = node.targets[0]
                if (
                    isinstance(target, ast.Name)
                    and target.id == "KILO_SPACE_BUNNY_MODEL_ID"
                    and isinstance(node.value, ast.Constant)
                ):
                    model_id = node.value.value
                if (
                    isinstance(target, ast.Name)
                    and target.id == "KILO_SPACE_BUNNY_UPSTREAM_MODEL"
                    and isinstance(node.value, ast.Constant)
                ):
                    upstream = node.value.value
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "_KiloFreeRoute"
            ):
                keywords = {k.arg: k.value for k in node.keywords if k.arg}
                route_ref = keywords.get("model_id")
                if (
                    isinstance(route_ref, ast.Name)
                    and route_ref.id == "KILO_SPACE_BUNNY_MODEL_ID"
                ):
                    caps = keywords.get("capabilities")
                    if (
                        isinstance(caps, ast.Call)
                        and len(caps.args) == 1
                        and isinstance(caps.args[0], (ast.Set, ast.List, ast.Tuple))
                    ):
                        capabilities = frozenset(
                            elt.value
                            for elt in caps.args[0].elts
                            if isinstance(elt, ast.Constant)
                        )
        assert model_id is not None and upstream is not None
        # Historical metadata only: the lane is retired, so no registered
        # capabilities exist anymore. Keep whatever the constants name.
        return model_id, upstream, capabilities

    @staticmethod
    def _kilo_route_registration_facts() -> tuple[str, frozenset[str]]:
        """AST-read kilo_provider: raw source + model ids registered as routes.

        A model id counts as registered only when a ``_KiloFreeRoute(...)``
        entry inside ``KILO_FREE_ROUTES`` names it (register_kilo_provider
        turns exactly those entries into catalog entries).
        """
        path = (
            B66CanonicalIntegrationTests._repo_root()
            / "apps"
            / "korean-ai-platform"
            / "app"
            / "pilot"
            / "kilo_provider.py"
        )
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        registered: set[str] = set()
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "_KiloFreeRoute"
            ):
                keywords = {k.arg: k.value for k in node.keywords if k.arg}
                route_ref = keywords.get("model_id")
                if isinstance(route_ref, ast.Name):
                    registered.add(f"<ref:{route_ref.id}>")
                elif isinstance(route_ref, ast.Constant) and isinstance(
                    route_ref.value, str
                ):
                    registered.add(route_ref.value)
        return source, frozenset(registered)

    @staticmethod
    def _retired_set_contains_space_bunny(kilo_source: str) -> bool:
        """AST-verify the retired frozenset references the Space Bunny id."""
        tree = ast.parse(kilo_source)
        found = False
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "RETIRED_KILO_FREE_MODEL_IDS"
            ):
                call = node.value
                if (
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Name)
                    and call.func.id == "frozenset"
                    and call.args
                    and isinstance(call.args[0], (ast.Set, ast.List, ast.Tuple))
                ):
                    for elt in call.args[0].elts:
                        if (
                            isinstance(elt, ast.Name)
                            and elt.id == "KILO_SPACE_BUNNY_MODEL_ID"
                        ):
                            found = True
        return found

    def test_canonical_primary_pending_and_lane_fully_retired(self) -> None:
        primary = self._load_model_primary()
        # Canonical Padiem primary stays model-neutral HOLD: pending successor
        # selection, no provider, no upstream model, no secondary, no fallback.
        self.assertEqual(primary.TEXT_PRIMARY_DECISION, "PENDING_SUCCESSOR_SELECTION")
        self.assertIsNone(primary.TEXT_PRIMARY_MODEL_ID)
        self.assertIsNone(primary.TEXT_PRIMARY_PROVIDER_ID)
        self.assertIsNone(primary.TEXT_PRIMARY_UPSTREAM_MODEL)
        self.assertEqual(primary.VISION_PRIMARY_DECISION, "PENDING_SUCCESSOR_SELECTION")
        self.assertIsNone(primary.VISION_PRIMARY_MODEL_ID)
        self.assertIsNone(primary.VISION_PRIMARY_PROVIDER_ID)
        self.assertIsNone(primary.VISION_PRIMARY_UPSTREAM_MODEL)
        self.assertIsNone(primary.TEXT_SECONDARY_MODEL_ID)
        self.assertFalse(primary.TEXT_FALLBACK_ENABLED)
        # The B66 historical lane identity survives as metadata only.
        self.assertEqual(B66_GOVERNED_ROUTE, "kilo/stealth-space-bunny-alpha")
        self.assertEqual(B66_GOVERNED_UPSTREAM, "stealth/space-bunny-alpha")
        self.assertEqual(B66_GOVERNED_PROVIDER, "kilo")
        # Full retirement: the lane is in the retired set, absent from
        # KILO_FREE_ROUTES and from the catalog (read via AST so this suite
        # never imports the platform runtime).
        kilo_source, registered_routes = self._kilo_route_registration_facts()
        self.assertTrue(self._retired_set_contains_space_bunny(kilo_source))
        self.assertNotIn(KILO_SPACE_BUNNY_ROUTE_ID, registered_routes)
        self.assertNotEqual(primary.TEXT_PRIMARY_MODEL_ID, B66_GOVERNED_ROUTE)
        self.assertNotEqual(primary.VISION_PRIMARY_MODEL_ID, B66_GOVERNED_ROUTE)

    def test_retired_lane_metadata_preserved_but_unregistered(self) -> None:
        model_id, upstream, capabilities = self._space_bunny_lane_facts()
        # Historical constants survive as metadata...
        self.assertEqual(B66_GOVERNED_ROUTE, model_id)
        self.assertEqual(B66_GOVERNED_UPSTREAM, upstream)
        # ...but the lane is no longer a registered free route and the
        # historical image capability exists nowhere executable.
        kilo_source, registered_routes = self._kilo_route_registration_facts()
        self.assertNotIn(model_id, registered_routes)
        self.assertTrue(self._retired_set_contains_space_bunny(kilo_source))
        self.assertNotIn("image", capabilities | set())

    @staticmethod
    def _gateway_allowed_request_fields() -> tuple[frozenset[str], frozenset[str]]:
        path = (
            B66CanonicalIntegrationTests._repo_root()
            / "apps"
            / "korean-ai-platform"
            / "app"
            / "pilot"
            / "gateway.py"
        )
        tree = ast.parse(path.read_text(encoding="utf-8"))
        found: dict[str, frozenset[str]] = {}
        for node in tree.body:
            if not isinstance(node, ast.Assign) or len(node.targets) != 1:
                continue
            target = node.targets[0]
            if not isinstance(target, ast.Name):
                continue
            if target.id not in {"_ALLOWED_CHAT_FIELDS", "_ALLOWED_B14_FIELDS"}:
                continue
            call = node.value
            if (
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Name)
                and call.func.id == "frozenset"
                and len(call.args) == 1
                and isinstance(call.args[0], (ast.Set, ast.List, ast.Tuple))
            ):
                found[target.id] = frozenset(
                    elt.value
                    for elt in call.args[0].elts
                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                )
        assert set(found) == {"_ALLOWED_CHAT_FIELDS", "_ALLOWED_B14_FIELDS"}
        return found["_ALLOWED_CHAT_FIELDS"], found["_ALLOWED_B14_FIELDS"]

    def test_gateway_allowed_fields_are_unchanged_for_future_lane(self) -> None:
        # The gateway field allow-lists stay exactly as the future successor
        # lane will find them; the HOLD changes routing, not the gateway
        # contract surface.
        allowed_chat, allowed_b14 = self._gateway_allowed_request_fields()
        self.assertIn("model", allowed_chat)
        self.assertIn("messages", allowed_chat)
        self.assertIn("stream", allowed_chat)
        self.assertIn("business14", allowed_chat)
        self.assertIn("allow_external_fallback", allowed_b14)
        self.assertIn("max_attempts", allowed_b14)
        self.assertIn("required_capabilities", allowed_b14)

    def test_builders_emit_no_space_bunny_request_and_fail_closed(self) -> None:
        # B66_TEXT_REQUEST_EMITS_SPACE_BUNNY=NO,
        # B66_IMAGE_REQUEST_EMITS_SPACE_BUNNY=NO,
        # B66_SCANNED_PDF_REQUEST_EMITS_SPACE_BUNNY=NO,
        # B66_SUCCESSOR_AUTO_SUBSTITUTION=NO (builders raise; nothing else).
        cases = (
            ("text", lambda: build_text_extraction_request(
                "견적번호 Q-2026-3001", filename="quote.pdf"
            )),
            ("image", lambda: build_image_extraction_request(
                (CORPUS_DIR / "f02-scanned-quotation.png").read_bytes(),
                media_type="image/png",
                filename="f02-scanned-quotation.png",
            )),
            ("scanned_pdf", lambda: build_scanned_pdf_extraction_requests(
                b"%PDF-stub", name="stub.pdf", renderer=_fake_two_page_renderer()
            )),
        )
        for name, call in cases:
            with self.subTest(builder=name):
                with self.assertRaises(B66ExtractionRoutingError) as ctx:
                    call()
                self.assertEqual(ctx.exception.code, "model_route_unavailable")


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
