"""Offline metadata-only contract; does not access customer PDFs."""
import json
from pathlib import Path
from unittest import TestCase, main

ROOT = Path(__file__).resolve().parent


class RegistryContractTest(TestCase):
    def test_single_selected_renderer_and_safe_scope(self):
        data = json.loads((ROOT / "candidates.json").read_text(encoding="utf-8"))
        self.assertEqual(data["schema_version"], 1)
        self.assertEqual(data["family"], "cgi-fixed-one-page")
        self.assertEqual(data["preferred_candidate"], "sol61-certified")
        self.assertEqual(data["approval_state"], "SOURCE_SELECTED_REVIEW_PENDING")
        self.assertFalse(data["production_deployed"])
        self.assertFalse(data["private_assets_in_git"])
        self.assertFalse(data["auto_activate"])
        self.assertFalse(data["allow_paid_model_fallback"])
        self.assertEqual(data["max_certified_items"], 3)
        by_id = {c["id"]: c for c in data["candidates"]}
        self.assertEqual(set(by_id), {"sol61-certified", "glm53-alternative"})
        self.assertEqual(by_id["sol61-certified"]["built_by_model"], "gpt-6.1-sol")
        self.assertEqual(by_id["glm53-alternative"]["built_by_model"], "glm-5.3-flash")
        self.assertFalse(by_id["sol61-certified"]["historical_text_retained_after_mutation"])
        self.assertTrue(by_id["glm53-alternative"]["historical_text_retained_after_mutation"])

    def test_no_private_bundle_assets_in_registry(self):
        private_suffixes = {".pdf", ".xlsx", ".xls", ".png", ".jpg",
                            ".jpeg", ".emf", ".zip", ".zlib", ".ttf",
                            ".otf", ".woff", ".woff2", ".p12", ".pem"}
        for p in ROOT.parent.rglob("*"):
            if p.is_file():
                self.assertNotIn(p.suffix.lower(), private_suffixes, str(p))
                self.assertNotIn(p.name, {"template.json", "resources.pdf", "program.zlib"})


if __name__ == "__main__":
    main()
