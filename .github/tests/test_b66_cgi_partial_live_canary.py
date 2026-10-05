from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


SCRIPT = Path(__file__).parents[1] / "scripts" / "b66_cgi_partial_live_canary.py"
SPEC = importlib.util.spec_from_file_location("b66_cgi_partial_live_canary", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class CanaryContractTests(unittest.TestCase):
    def test_one_shot_and_no_retry_contract(self):
        self.assertEqual(module.MAX_INTERPRET_POSTS, 1)
        self.assertEqual(module.RETRY, 0)
        self.assertEqual(module.FALLBACK, 0)

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
