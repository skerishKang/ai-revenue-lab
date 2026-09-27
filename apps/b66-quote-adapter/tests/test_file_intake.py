from __future__ import annotations

import base64
from pathlib import Path
import unittest

from app.file_intake import (
    MODEL_DEPENDENCY,
    PROVIDER_IDS_IN_ADAPTER,
    SERVER_ROUTE_DEPLOYED,
    handle_intake_payload,
)
from padiem_ai_core.document_normalization import NormalizedDocument
from padiem_ai_core.document_parser_boundary import (
    DocumentParserAuthorityUnavailable,
)
from padiem_ai_core.document_semantics import DocumentNormalizationError


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


class B66FileIntakeTests(unittest.TestCase):
    def test_request_shape_is_exact_and_rejects_model_fields(self) -> None:
        self.assertEqual(
            handle_intake_payload(None),
            {
                "ok": False,
                "error": {
                    "code": "invalid_request",
                    "message": "파일 요청 형식이 올바르지 않습니다.",
                },
            },
        )
        result = handle_intake_payload(
            {
                "name": "quote.pdf",
                "media_type": "application/pdf",
                "base64": b64(b"%PDF-1.4\n"),
                "model": "forbidden",
            }
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "unsupported_fields")

    def test_invalid_base64_empty_and_document_size_fail_safe(self) -> None:
        for raw, expected in [
            ("%%%", "invalid_base64"),
            ("", "invalid_base64"),
        ]:
            result = handle_intake_payload(
                {
                    "name": "quote.pdf",
                    "media_type": "application/pdf",
                    "base64": raw,
                }
            )
            self.assertFalse(result["ok"])
            self.assertEqual(result["error"]["code"], expected)

        empty = handle_intake_payload(
            {
                "name": "quote.pdf",
                "media_type": "application/pdf",
                "base64": b64(b""),
            }
        )
        self.assertFalse(empty["ok"])
        self.assertEqual(empty["error"]["code"], "invalid_base64")

        too_large = handle_intake_payload(
            {
                "name": "quote.pdf",
                "media_type": "application/pdf",
                "base64": b64(b"x" * (2 * 1024 * 1024 + 1)),
            }
        )
        self.assertFalse(too_large["ok"])
        self.assertEqual(too_large["error"]["code"], "document_too_large")

    def test_legacy_hwp_and_media_extension_mismatch(self) -> None:
        legacy = handle_intake_payload(
            {
                "name": "quote.hwp",
                "media_type": "application/x-hwp",
                "base64": b64(b"hwp"),
            }
        )
        self.assertFalse(legacy["ok"])
        self.assertEqual(legacy["error"]["code"], "legacy_hwp_unsupported")

        mismatch = handle_intake_payload(
            {
                "name": "quote.docx",
                "media_type": "application/pdf",
                "base64": b64(b"docx"),
            }
        )
        self.assertFalse(mismatch["ok"])
        self.assertEqual(mismatch["error"]["code"], "media_extension_mismatch")

    def test_native_document_reuses_parser_port_and_projects_text(self) -> None:
        calls: list[tuple[str, str, bytes]] = []

        def parser(*, name: str, media_type: str, payload: bytes) -> NormalizedDocument:
            calls.append((name, media_type, payload))
            return NormalizedDocument(
                name=name,
                media_type=media_type,
                text="견적번호 Q-1\n홈페이지 제작 1 1500000",
                byte_size=len(payload),
                source_kind="binary",
            )

        raw = b"%PDF-1.4\nsynthetic"
        result = handle_intake_payload(
            {
                "name": "quote.pdf",
                "media_type": "application/pdf",
                "base64": b64(raw),
            },
            parser=parser,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(calls, [("quote.pdf", "application/pdf", raw)])
        body = result["result"]
        self.assertEqual(body["kind"], "native_document")
        self.assertEqual(body["text"], "견적번호 Q-1\n홈페이지 제작 1 1500000")
        self.assertEqual(body["text_chars"], len(body["text"]))
        self.assertEqual(body["next"], "text_extraction_model_pending")
        self.assertFalse(body["model_called"])

    def test_supported_ooxml_and_hwpx_flow_through_same_parser_port(self) -> None:
        media = {
            "quote.docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "quote.pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "quote.xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "quote.hwpx": "application/hwp+zip",
        }
        seen: list[str] = []

        def parser(*, name: str, media_type: str, payload: bytes) -> NormalizedDocument:
            seen.append(name)
            return NormalizedDocument(
                name=name,
                media_type=media_type,
                text="synthetic text",
                byte_size=len(payload),
                source_kind="binary",
            )

        for name, media_type in media.items():
            result = handle_intake_payload(
                {
                    "name": name,
                    "media_type": media_type,
                    "base64": b64(b"synthetic"),
                },
                parser=parser,
            )
            self.assertTrue(result["ok"], (name, result))
            self.assertEqual(result["result"]["kind"], "native_document")

        self.assertEqual(seen, list(media))

    def test_textless_pdf_becomes_scanned_pdf_candidate(self) -> None:
        def parser(**_: object) -> NormalizedDocument:
            raise DocumentNormalizationError(
                "pdf_empty_text",
                "PDF contains no readable text.",
            )

        result = handle_intake_payload(
            {
                "name": "scan.pdf",
                "media_type": "application/pdf",
                "base64": b64(b"%PDF synthetic scan"),
            },
            parser=parser,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["result"]["kind"], "scanned_pdf_candidate")
        self.assertEqual(result["result"]["next"], "scanned_pdf_vision_pending")
        self.assertFalse(result["result"]["model_called"])

    def test_parser_authority_unavailable_fails_closed(self) -> None:
        def parser(**_: object) -> NormalizedDocument:
            raise DocumentParserAuthorityUnavailable()

        result = handle_intake_payload(
            {
                "name": "quote.pdf",
                "media_type": "application/pdf",
                "base64": b64(b"%PDF synthetic"),
            },
            parser=parser,
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "parser_authority_unavailable")

    def test_image_candidates_validate_magic_and_do_not_call_parser(self) -> None:
        calls = 0

        def parser(**_: object) -> NormalizedDocument:
            nonlocal calls
            calls += 1
            raise AssertionError("image intake must not call document parser")

        fixtures = [
            ("quote.jpg", "image/jpeg", b"\xff\xd8\xffsynthetic"),
            ("quote.jpeg", "image/jpeg", b"\xff\xd8\xffsynthetic"),
            ("quote.png", "image/png", b"\x89PNG\r\n\x1a\nsynthetic"),
            ("quote.webp", "image/webp", b"RIFF1234WEBPsynthetic"),
        ]
        for name, media_type, raw in fixtures:
            result = handle_intake_payload(
                {
                    "name": name,
                    "media_type": media_type,
                    "base64": b64(raw),
                },
                parser=parser,
            )
            self.assertTrue(result["ok"], (name, result))
            self.assertEqual(result["result"]["kind"], "image_candidate")
            self.assertEqual(result["result"]["next"], "vision_model_pending")
            self.assertFalse(result["result"]["model_called"])
        self.assertEqual(calls, 0)

        bad = handle_intake_payload(
            {
                "name": "quote.png",
                "media_type": "image/png",
                "base64": b64(b"not-png"),
            },
            parser=parser,
        )
        self.assertFalse(bad["ok"])
        self.assertEqual(bad["error"]["code"], "image_magic_mismatch")

    def test_image_size_cap(self) -> None:
        result = handle_intake_payload(
            {
                "name": "quote.jpg",
                "media_type": "image/jpeg",
                "base64": b64(b"\xff\xd8\xff" + b"x" * (4 * 1024 * 1024)),
            }
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "image_too_large")

    def test_source_has_no_provider_model_or_arbitrary_url_surface(self) -> None:
        source = Path(__file__).resolve().parents[1].joinpath("app", "file_intake.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("parse_binary_document_via_authority", source)
        self.assertNotIn("provider_id", source)
        self.assertNotIn("model_id", source)
        self.assertNotIn("base_url", source)
        self.assertNotIn("http://", source)
        self.assertNotIn("https://", source)
        self.assertFalse(MODEL_DEPENDENCY)
        self.assertEqual(PROVIDER_IDS_IN_ADAPTER, 0)
        self.assertFalse(SERVER_ROUTE_DEPLOYED)


if __name__ == "__main__":
    unittest.main()
