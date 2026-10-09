"""Gemini 3.5 Flash-Lite final-round evidence consistency tests."""
from pathlib import Path
import json, unittest

HERE=Path(__file__).resolve().parents[1]
REPORT=HERE/"B14_FINAL_GEMINI_3_5_FLASH_LITE_2026-10-09.md"
LEDGER=HERE/"B14_FINAL_MODEL_EVALUATION_2026-10-09.md"
QUOTA=HERE/"GOOGLE_AI_STUDIO_FREE_TIER_QUOTAS_2026-10-09.json"
class FinalGemini35EvidenceTests(unittest.TestCase):
    def test_one_model_new_round_is_recorded(self):
        report=REPORT.read_text(encoding="utf-8")
        ledger=LEDGER.read_text(encoding="utf-8")
        for needle in ["gemini-3.5-flash-lite","1,048,576","65,536","minimal / low / medium / high","15","250,000","500","10/10","9/10","QKR-008","14,187","NOT_TESTED"]:
            with self.subTest(needle=needle):self.assertIn(needle,report)
        self.assertIn(REPORT.name,ledger)
        self.assertIn("Minimal 10/10",ledger)
        self.assertIn("40/40 HTTP 200",ledger)
    def test_owner_free_tier_snapshot_matches_report(self):
        data=json.loads(QUOTA.read_text(encoding="utf-8"))
        match=[x for x in data["models"] if x["display_name"]=="Gemini 3.5 Flash Lite"]
        self.assertEqual(len(match),1)
        self.assertEqual((match[0]["rpm"],match[0]["input_tpm"],match[0]["rpd"]),(15,250000,500))
    def test_isolated_from_historical_run(self):
        text=REPORT.read_text(encoding="utf-8")
        self.assertNotIn("41건",text)
        self.assertNotIn("2/3",text)
        for i in range(1,11): self.assertEqual(text.count("| QKR-%03d | 200 |"%i),1)
if __name__=="__main__":
    unittest.main()
