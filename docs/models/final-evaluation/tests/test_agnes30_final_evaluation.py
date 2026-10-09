"""Agnes 3.0 Flash 2026-10-09 independent evaluation documentary guards. No provider POST."""
import json
import unittest
from pathlib import Path

REPORT = Path(__file__).resolve().parents[1] / "B14_FINAL_AGNES_3_0_FLASH_2026-10-09.md"
LEDGER = Path(__file__).resolve().parents[1] / "B14_FINAL_MODEL_EVALUATION_2026-10-09.md"
ROOT = Path(__file__).resolve().parents[4]
MODEL = "agnes-ai/agnes-3.0-flash"

class Agnes30FinalEvaluationGuard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = REPORT.read_text(encoding="utf-8")
        cls.ledger = LEDGER.read_text(encoding="utf-8")
        cls.registry = json.loads((ROOT / "apps/korean-ai-platform/app/pilot/b14_models.json").read_text(encoding="utf-8"))

    def test_canonical_exact_model_registration(self):
        m = next(m for m in self.registry["models"] if m["id"] == MODEL)
        self.assertEqual(m["upstream_model"], "agnes-3.0-flash")
        self.assertEqual(m["provider_id"], "agnes-ai")
        self.assertTrue(m["enabled"])
        self.assertTrue(self.registry["providers"]["agnes-ai"]["enabled"])

    def test_independent_round_and_model(self):
        for value in ("B14_FINAL_MODEL_EVALUATION_2026-10-09", MODEL, "apihub.agnes-ai.com", "512K", "65,536"):
            self.assertIn(value, self.report)

    def test_rate_limit_not_mislabeled_as_accuracy(self):
        for value in ("BLOCKED_HTTP429", "upstream_rate_limited", "평가 불가", "IN_PROGRESS", "10/10 HTTP200", "**8/10**"):
            self.assertIn(value, self.report)
        self.assertNotIn("**FINAL_PASS**", self.report)

    def test_failed_cases_scoped_to_project_name(self):
        for value in ("QKR-004", "QKR-007", "project_name", "품목별 검사 PASS"):
            self.assertIn(value, self.report)

    def test_thinking_partial_stop_truth(self):
        for value in ("enable_thinking=false/true", "6/10", "5/10", "2,563ms", "7,053ms", "**399**", "**717**", "조기 중단"):
            self.assertIn(value, self.report)
        self.assertIn("NOT_SUPPORTED_CURRENT_REQUEST_SCHEMA", self.report)

    def test_real_quote_core_pdf_and_e2e_boundary(self):
        for value in ("12/12", "6,500,000원", "650,000원", "7,150,000원", "133,454", "48자", "NOT_TESTED"):
            self.assertIn(value, self.report)

    def test_ledger_single_model_link(self):
        self.assertIn("B14_FINAL_AGNES_3_0_FLASH_2026-10-09.md", self.ledger)
        self.assertIn("| 7 | `agnes-ai/agnes-3.0-flash` |", self.ledger)
        self.assertIn("RATE_LIMIT_BLOCKED", self.ledger)

if __name__ == "__main__":
    unittest.main()
