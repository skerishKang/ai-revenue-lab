from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


SCRIPT = Path(__file__).parents[1] / "scripts" / "b66_cgi_partial_live_canary.py"
SPEC = importlib.util.spec_from_file_location("b66_cgi_partial_live_canary", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


class CanaryContractTests(unittest.TestCase):
    def test_one_shot_and_no_retry_contract(self):
        self.assertEqual(module.MAX_INTERPRET_POSTS, 1)
        self.assertEqual(module.USER_AGENT, "padiem-b66-cgi-partial-canary/1.0 (+github-actions)")
        self.assertEqual(module.RETRY, 0)
        self.assertEqual(module.FALLBACK, 0)

    def test_operator_exact_model_selection_is_required(self):
        allowed = [
            {"model_id": "agnes-ai/agnes-3.0-flash", "name": "Agnes"},
            {"model_id": "inception/mercury-2.5", "name": "Mercury"},
        ]
        self.assertEqual(
            module.selected_model_id("agnes-ai/agnes-3.0-flash", allowed),
            "agnes-ai/agnes-3.0-flash",
        )
        for bad in (None, "", "b14/auto", "padiem-profile/free", "google/gemma-4-31b-it"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                module.selected_model_id(bad, allowed)
        with self.assertRaises(ValueError):
            module.selected_model_id("agnes-ai/agnes-3.0-flash", allowed + [allowed[0]])
        with self.assertRaises(ValueError):
            module.selected_model_id("agnes-ai/agnes-3.0-flash", None)

    def test_canary_passes_explicit_id_separately_from_quote_message(self):
        source = SCRIPT.read_text(encoding="utf8")
        self.assertIn('"model_id": chosen_model_id', source)
        self.assertIn('"/api/padiem/b66/quote/models"', source)
        self.assertIn('SELECTED_MODEL_ENV = "B66_CGI_CANARY_SELECTED_MODEL_ID"', source)
        wf = (SCRIPT.parents[1] / "workflows" / "b66-cgi-partial-live-canary.yml").read_text(encoding="utf8")
        self.assertIn("selected_model_id:", wf)
        self.assertIn("required: true", wf)
        self.assertIn("B66_CGI_CANARY_SELECTED_MODEL_ID: " + chr(36) + "{{ inputs.selected_model_id }}", wf)


    def test_upstream_class_is_closed_allowlist(self):
        self.assertEqual(
            module.sanitize_upstream_class("upstream_non_text_content"),
            "upstream_non_text_content",
        )
        self.assertEqual(
            module.sanitize_upstream_class("provider raw detail"),
            "ABSENT_OR_UNKNOWN",
        )

    def test_public_error_is_closed_allowlist(self):
        self.assertEqual(
            module.sanitize_public_error("quote_interpretation_failed"),
            "quote_interpretation_failed",
        )
        self.assertEqual(
            module.sanitize_public_error("provider raw detail"),
            "ABSENT_OR_UNKNOWN",
        )

    def test_missing_fields_are_bounded(self):
        self.assertEqual(
            module.sanitize_missing(["items[0].unitPrice"]),
            ("items[0].unitPrice",),
        )
        self.assertEqual(
            module.sanitize_missing(["private.raw.field"]),
            ("UNKNOWN_FIELD",),
        )

    def test_free_text_diagnostic_is_redacted(self):
        self.assertEqual(
            module._bounded_diagnostic("items[0].unitPrice"),
            "items[0].unitPrice",
        )
        self.assertEqual(
            module._bounded_diagnostic("raw customer detail"),
            "PRESENT_REDACTED",
        )


if __name__ == "__main__":
    unittest.main()
