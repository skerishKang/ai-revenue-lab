from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import re
import sys
import unittest


SCRIPT = Path(__file__).parents[1] / "scripts" / "b66_cgi_final_handoff_smoke.py"
SPEC = importlib.util.spec_from_file_location("b66_cgi_final_handoff_smoke", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


class FinalHandoffSmokeContractTests(unittest.TestCase):
    def test_exact_three_interpret_budget(self):
        self.assertEqual(module.MAX_INTERPRET_POSTS, 3)
        self.assertEqual(module.MAX_PDF_POSTS, 3)
        self.assertEqual(module.PDF_PATH, "/api/padiem/b66/quote/pdf")
        self.assertEqual(module.RETRY, 0)
        self.assertEqual(module.FALLBACK, 0)

    def test_exact_acceptance_inputs(self):
        self.assertEqual(
            module.COMPLETE_TEXT,
            "대한건설에 배관 100미터, 미터당 18000원, 부가세 별도",
        )
        self.assertEqual(
            module.PARTIAL_TEXT,
            "대한건설에 배관 100미터, 부가세 별도",
        )
        self.assertEqual(module.FOLLOWUP_TEXT, "미터당 18000원")

    def test_provider_host_detection_is_closed_to_real_provider_hosts(self):
        self.assertTrue(module._is_direct_provider("https://api.kilo.ai/v1/chat"))
        self.assertTrue(module._is_direct_provider("https://openrouter.ai/api/v1/chat"))
        self.assertFalse(
            module._is_direct_provider(
                "https://quick-quote-kr.pages.dev/api/padiem/b66/quote/interpret"
            )
        )

    def test_final_handoff_uses_real_certified_pdf_download_not_window_print(self):
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("page.expect_download", source)
        self.assertIn("cgi_browser_pdf_not_active", source)
        self.assertIn("cgi_browser_pdf_used_server", source)
        self.assertIn("CERTIFIED_BROWSER_PDF_DOWNLOADS=3", source)
        self.assertIn('print("PDF_POSTS=0")', source)
        self.assertIn('body.startswith(b"%PDF-")', source)
        self.assertNotIn("window.print =", source)

    def test_target_is_standalone_b66_production(self):
        self.assertEqual(module.TARGET_URL, "https://quick-quote-kr.pages.dev/")
        self.assertEqual(
            module.INTERPRET_PATH,
            "/api/padiem/b66/quote/interpret",
        )


class CanaryEvidenceSeamTests(unittest.TestCase):
    """#3655: the one-shot canary's bounded evidence contract."""

    def test_failure_detail_vocabulary_mirrors_kagent_port_exactly(self):
        # The smoke script cannot import product packages, so the vocabulary
        # is mirrored as a literal. This sync test fails if the port's closed
        # P01_FAILURE_DETAILS vocabulary and the mirror ever drift apart.
        adapter_source = (
            Path(__file__).parents[2]
            / "apps"
            / "korean-ai-code-agent"
            / "src"
            / "kagent"
            / "p01_adapter.py"
        ).read_text(encoding="utf-8")
        port_details = set(
            re.findall(
                r'^P01_FAILURE_DETAIL_[A-Z_]+ = "([a-z0-9_]+)"$',
                adapter_source,
                re.MULTILINE,
            )
        )
        self.assertTrue(port_details)
        self.assertEqual(port_details, set(module.CLAW_FAILURE_DETAIL_VOCABULARY))

    def test_evidence_header_allowlist_is_the_chat_route_vocabulary(self):
        self.assertEqual(
            set(module.CLAW_EVIDENCE_RESPONSE_HEADERS),
            {
                "x-padiem-claw-run-id",
                "x-padiem-orchestration-run-id",
                "x-padiem-selected-route-id",
                "x-padiem-provider-attempts",
                "x-padiem-fallback-used",
            },
        )
        route_source = (
            Path(__file__).parents[2]
            / "apps"
            / "padiem-chat"
            / "app"
            / "claw_general_routes.py"
        ).read_text(encoding="utf-8")
        for header in module.CLAW_EVIDENCE_RESPONSE_HEADERS:
            canonical = "-".join(word.capitalize() for word in header.split("-"))
            self.assertIn(canonical, route_source)
        self.assertIn(module.CLAW_EVIDENCE_MARKER, route_source)

    def test_bounded_evidence_headers_drop_unlisted_and_malformed(self):
        good = {
            "x-padiem-claw-run-id": "run_" + "b" * 24,
            "x-padiem-orchestration-run-id": "orch_test_001",
            "x-padiem-selected-route-id": "plus.agnes-3.0-flash.v1",
            "x-padiem-provider-attempts": "1",
            "x-padiem-fallback-used": "false",
        }
        self.assertEqual(module._bounded_evidence_headers(good), good)
        self.assertEqual(module._bounded_evidence_headers({"x-padiem-claw-run-id": "junk"}), {})
        self.assertEqual(module._bounded_evidence_headers(None), {})

    def test_bounded_error_class_never_carries_message_or_free_text(self):
        body = json.dumps(
            {
                "ok": False,
                "error": {
                    "code": "engine_execution_failed",
                    "message": "Engine 실행에 실패했습니다.",
                    "detail": "engine_provider_server_error",
                },
            }
        )
        self.assertEqual(
            module._bounded_error_class(body),
            ("engine_execution_failed", "engine_provider_server_error"),
        )
        # Out-of-vocabulary detail degrades to None; the message never survives.
        leaky = json.dumps(
            {"error": {"code": "engine_execution_failed", "detail": "prompt tokens xyz"}}
        )
        self.assertEqual(module._bounded_error_class(leaky), ("engine_execution_failed", None))
        self.assertEqual(module._bounded_error_class("not json"), (None, None))

    def test_admission_result_mapping_is_fail_closed(self):
        self.assertEqual(module._canonical_admission_result("engine_admission_denied"), "DENIED")
        self.assertEqual(module._canonical_admission_result("engine_provider_timeout"), "UNPROVEN")
        self.assertEqual(module._canonical_admission_result(None), "UNPROVEN")

    def test_one_shot_bounds_are_unchanged(self):
        self.assertEqual(module.MAX_CLAW_GENERAL_POSTS, 1)
        self.assertEqual(module.RETRY, 0)
        self.assertEqual(module.FALLBACK, 0)
        self.assertEqual(module.CLAW_EVIDENCE_MARKER, "one-shot")


if __name__ == "__main__":
    unittest.main()
