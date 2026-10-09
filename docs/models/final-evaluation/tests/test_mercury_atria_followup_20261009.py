"""Mercury 2.5 and Atria Dawn final evaluation follow-ups are documentary, offline-only."""
import json
import unittest
from pathlib import Path

DIR=Path(__file__).resolve().parents[1]
ROOT=DIR.parents[2]
LEDGER=DIR/"B14_FINAL_MODEL_EVALUATION_2026-10-09.md"
MERCURY=DIR/"B14_FINAL_MERCURY_2_5_2026-10-09.md"
ATRIA=DIR/"B14_FINAL_ATRIA_DAWN_PREVIEW_2026-10-09.md"
REGISTRY=ROOT/"apps/korean-ai-platform/app/pilot/b14_models.json"


class ModelFollowup20261009Guard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ledger=LEDGER.read_text(encoding="utf-8")
        cls.mercury=MERCURY.read_text(encoding="utf-8")
        cls.atria=ATRIA.read_text(encoding="utf-8")
        cls.registry=json.loads(REGISTRY.read_text(encoding="utf-8"))

    def test_owner_priority_and_explicit_model_registry_unchanged(self):
        for order,mid in [(7,"inception/mercury-2.5"),(8,"atria/Atria-Dawn-Preview"),(9,"agnes-ai/agnes-3.0-flash")]:
            self.assertIn(f"| {order} | `{mid}` |",self.ledger)
            self.assertEqual(sum(x.startswith(f"| {order} | `{mid}` |") for x in self.ledger.splitlines()),1)
        self.assertEqual(len(self.registry["models"]),9)
        ids={m["id"] for m in self.registry["models"]}
        self.assertIn("inception/mercury-2.5",ids)
        self.assertIn("atria/Atria-Dawn-Preview",ids)
        self.assertIn("agnes-ai/agnes-3.0-flash",ids)

    def test_mercury_bounded_retry_truth(self):
        for v in ("Mercury 2.5 추가 호출 및 종료 판정","1,844ms","5,875ms","5,641ms","45,078ms",
                  "QKR-005~010","2/3","UNSTABLE_TIMEOUT_REPEATED","max_tokens=100","max_tokens=800"):
            self.assertIn(v,self.mercury)
        self.assertIn("UNSTABLE_TIMEOUT_REPEATED / FOLLOWUP_DEFERRED",self.ledger)
        self.assertIn("B14 upstream Mercury POST는 0건",self.mercury)

    def test_atria_official_model_and_credential_reference(self):
        a=next(x for x in self.registry["models"] if x["id"]=="atria/Atria-Dawn-Preview")
        self.assertTrue(a["enabled"])
        self.assertEqual(a["upstream_model"],"Atria-Dawn-Preview")
        self.assertEqual(a["provider_id"],"atria")
        p=self.registry["providers"]["atria"]
        self.assertEqual(p["base_origin"],"https://api.atria-asi.ai/v1")
        for v in ("256K","65,536","Atria-Dawn-Preview","x-rpm-limit: 50","UNKNOWN"):
            self.assertIn(v,self.atria)

    def test_atria_outcomes_are_not_claimed_to_be_full_ten_pass(self):
        for v in ("17,859ms","50,328ms","31,625ms","27,031ms",
                  "65,000ms","59,204ms","1,093ms","HTTP422","1/1",
                  "QKR-003~010","NOT_TESTED","B14 provider POST 0회"):
            self.assertIn(v,self.atria)
        self.assertIn("PRODUCTION_B14_CHAT_HTTP200 / STREAM_PREVIEW_QKR001_STRICT_PASS",self.ledger)
        self.assertIn("B14_FINAL_ATRIA_DAWN_PREVIEW_2026-10-09.md",self.ledger)
        self.assertNotIn("**FINAL_PASS**",self.atria)

    def test_no_cross_model_pdf_or_fallback_claims(self):
        for report in (self.atria,self.mercury):
            self.assertIn("PDF",report)
            self.assertIn("no fallback",report.lower())
            self.assertIn("NOT_TESTED",report)
        self.assertIn("ERROR_B14_HTTP429 / DEFERRED",self.ledger)


if __name__=="__main__":
    unittest.main()
