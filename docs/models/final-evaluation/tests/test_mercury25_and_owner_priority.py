"""2026-10-09 owner order + Inception Mercury 2.5 independent evaluation truth guards.
No provider call, no secret access, no Production mutation.
"""
import json
import unittest
from pathlib import Path

DIR = Path(__file__).resolve().parents[1]
ROOT = DIR.parents[2]
REPORT = DIR / "B14_FINAL_MERCURY_2_5_2026-10-09.md"
LEDGER = DIR / "B14_FINAL_MODEL_EVALUATION_2026-10-09.md"
AGNES = DIR / "B14_FINAL_AGNES_3_0_FLASH_2026-10-09.md"
REGISTRY = ROOT / "apps/korean-ai-platform/app/pilot/b14_models.json"


class Mercury25NewEvaluationGuard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = REPORT.read_text(encoding="utf-8")
        cls.ledger = LEDGER.read_text(encoding="utf-8")
        cls.agnes = AGNES.read_text(encoding="utf-8")
        cls.registry = json.loads(REGISTRY.read_text(encoding="utf-8"))

    def test_owner_reordered_evaluation_queue_not_live_registry(self):
        self.assertIn("| 7 | `inception/mercury-2.5` |", self.ledger)
        self.assertIn("| 8 | `atria/Atria-Dawn-Preview` |", self.ledger)
        self.assertIn("| 9 | `agnes-ai/agnes-3.0-flash` |", self.ledger)
        self.assertEqual(sum("| 7 | `inception/mercury-2.5` |" in s for s in self.ledger.splitlines()), 1)
        self.assertIn("ERROR_B14_HTTP429 / DEFERRED", self.ledger)
        self.assertIn("Owner 우선순위 변경", self.ledger)
        self.assertIn("모델 등록·노출·사용자 수동 선택·기본값을 변경하지 않는다", self.ledger)
        self.assertIn("ERROR_B14_HTTP429 / DEFERRED", self.agnes)

    def test_exact_model_registry_from_canonical_source(self):
        ids = [m["id"] for m in self.registry["models"]]
        self.assertEqual(len(ids), 10)
        m = next(m for m in self.registry["models"] if m["id"] == "inception/mercury-2.5")
        self.assertTrue(m["enabled"])
        self.assertEqual(m["upstream_model"], "mercury-2.5")
        self.assertEqual(m["provider_id"], "inception")
        p = self.registry["providers"]["inception"]
        self.assertTrue(p["enabled"])
        self.assertEqual(p["base_origin"], "https://api.inceptionlabs.ai/v1")
        self.assertEqual(p["credential_binding_name"], "PADIEM_INCEPTION_MERCURY_API_KEY")

    def test_independent_round_official_sources_and_unknown_limits(self):
        for item in ("B14_FINAL_MODEL_EVALUATION_2026-10-09", "260K", "inception/mercury-2.5",
                     "mercury-2.5", "api.inceptionlabs.ai", "2026-09-08",
                     "RPM", "TPM", "RPD", "UNKNOWN"):
            self.assertIn(item, self.report)

    def test_preflight_403_is_not_model_post_failure(self):
        for phrase in ("B14_PREFLIGHT_HTTP403", "health", "models", "**B14 POST 0회**",
                       "**NOT_TESTED**", "SOURCE_REGISTERED"):
            self.assertIn(phrase, self.report)
        self.assertNotIn("B14 HTTP429", self.report)

    def test_direct_sample_scope_and_timeout_not_mislabeled(self):
        for phrase in ("QKR-001", "QKR-002", "QKR-003", "QKR-004~010",
                       "5,907ms", "3,656ms", "65,078ms", "1,184", "1,465",
                       "871", "1,064", "project_name", "2/3 HTTP200", "1/2",
                       "65초", "NOT_ATTEMPTED"):
            self.assertIn(phrase, self.report)
        self.assertIn("timeout", self.report.lower())
        self.assertIn("504로 잘못", self.report)
        self.assertIn("재시도·모델 교체 없음", self.report)

    def test_f6_and_approval_require_real_evidence(self):
        self.assertIn("F6 — B66 QuoteCore", self.report)
        self.assertIn("**NOT_TESTED.**", self.report)
        self.assertIn("IN_PROGRESS — 승인 불가", self.report)
        self.assertIn("B14_FINAL_MERCURY_2_5_2026-10-09.md", self.ledger)
        self.assertNotIn("FINAL_PASS", self.report)


if __name__ == "__main__":
    unittest.main()
